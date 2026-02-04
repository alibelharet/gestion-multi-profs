import os
import tempfile
from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from werkzeug.security import generate_password_hash

from core.backup import create_backup_zip, restore_from_backup_zip
from core.db import close_db, get_db
from core.password_reset import create_reset_token
from core.security import admin_required, login_required

bp = Blueprint("admin", __name__)


@bp.route("/admin")
@login_required
@admin_required
def admin():
    db = get_db()
    users = db.execute(
        "SELECT id, username, nom_affichage, is_admin FROM users ORDER BY is_admin DESC, id ASC"
    ).fetchall()
    all_docs = db.execute(
        """
        SELECT d.id, d.titre, d.type_doc, d.filename, u.nom_affichage
        FROM documents d
        JOIN users u ON u.id = d.user_id
        ORDER BY d.id DESC
        """
    ).fetchall()
    return render_template("admin.html", users=users, all_docs=all_docs)


@bp.route("/admin/backup")
@login_required
@admin_required
def admin_backup():
    buf = create_backup_zip()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"edumaster_backup_{stamp}.zip",
        mimetype="application/zip",
    )


@bp.route("/admin/restore", methods=["POST"])
@login_required
@admin_required
def admin_restore():
    f = request.files.get("backup_zip")
    if not f or not f.filename:
        flash("Aucun fichier selectionne.", "danger")
        return redirect(url_for("admin.admin"))

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    try:
        f.save(tmp_path)
        close_db()
        result = restore_from_backup_zip(tmp_path)
        flash(
            f"Restauration OK. Fichiers restaures: {result.restored_files}.",
            "success",
        )
        if result.db_backup_path or result.uploads_backup_path:
            flash(
                "Un backup de l'ancien etat a ete garde (suffixe .bak_...).",
                "info",
            )
    except Exception as e:
        flash(f"Erreur restauration: {e}", "danger")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    return redirect(url_for("admin.admin"))


@bp.route("/admin/reset_password/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_reset_password(user_id: int):
    db = get_db()
    user = db.execute(
        "SELECT id, username, is_admin FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user or int(user["is_admin"] or 0) == 1:
        abort(404)
    db.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (generate_password_hash("123456"), user_id),
    )
    db.commit()
    flash(f"Mot de passe reinitialise pour {user['username']} (123456).", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/reset_link/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_reset_link(user_id: int):
    db = get_db()
    user = db.execute(
        "SELECT id, username, is_admin FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user or int(user["is_admin"] or 0) == 1:
        abort(404)
    token = create_reset_token(int(user_id))
    link = request.host_url.rstrip("/") + url_for("auth.reset_password", token=token)
    flash(f"Lien reset pour {user['username']} (temporaire): {link}", "info")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/delete_user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id: int):
    db = get_db()
    user = db.execute(
        "SELECT id, username, is_admin FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user or int(user["is_admin"] or 0) == 1:
        abort(404)

    docs = db.execute(
        "SELECT filename FROM documents WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    for d in docs:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], d["filename"]))
        except Exception:
            pass

    db.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM eleves WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    flash(f"Utilisateur supprime: {user['username']}", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/voir_eleves/<int:user_id>")
@login_required
@admin_required
def admin_voir_eleves(user_id: int):
    db = get_db()
    prof = db.execute(
        "SELECT id, username, nom_affichage FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not prof:
        abort(404)

    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"
    niveau = request.args.get("niveau", "")

    classes = [
        r["niveau"]
        for r in db.execute(
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? ORDER BY niveau",
            (user_id,),
        ).fetchall()
    ]

    query = "SELECT * FROM eleves WHERE user_id = ?"
    params = [user_id]
    if niveau and niveau != "all":
        query += " AND niveau = ?"
        params.append(niveau)
    query += " ORDER BY niveau, id"

    eleves_db = db.execute(query, params).fetchall()
    eleves_list = []
    admis, total_moy, count_saisis, notes = 0, 0, 0, []

    for el in eleves_db:
        d, a, c = el[f"devoir_t{trim}"], el[f"activite_t{trim}"], el[f"compo_t{trim}"]
        moy = round(((d + a) / 2 + (c * 2)) / 3, 2)
        if moy > 0:
            count_saisis += 1
            total_moy += moy
            notes.append(moy)
        if moy >= 10:
            admis += 1
        eleves_list.append(
            {
                "id": el["id"],
                "nom_complet": el["nom_complet"],
                "niveau": el["niveau"],
                "remarques": el[f"remarques_t{trim}"],
                "devoir": d,
                "activite": a,
                "compo": c,
                "moyenne": moy,
            }
        )

    stats = {
        "moyenne_generale": round(total_moy / count_saisis, 2) if count_saisis else 0,
        "meilleure_note": max(notes) if notes else 0,
        "pire_note": min(notes) if notes else 0,
        "nb_admis": admis,
        "taux_reussite": round((admis / len(eleves_list)) * 100, 1) if eleves_list else 0,
        "nb_total": len(eleves_list),
        "nb_saisis": count_saisis,
    }

    return render_template(
        "admin_eleves.html",
        prof=prof,
        eleves=eleves_list,
        stats=stats,
        trimestre=trim,
        niveau_actuel=niveau,
        liste_classes=classes,
    )
