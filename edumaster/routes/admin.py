import os
import re
import secrets
import tempfile
from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import generate_password_hash

from core.audit import log_change
from core.backup import create_backup_zip, restore_from_backup_zip
from core.db import close_db, get_db
from core.password_reset import create_reset_token
from core.security import admin_required, login_required
from core.utils import init_default_rules
from edumaster.services.common import get_active_school_year, list_school_years, resolve_school_year

bp = Blueprint("admin", __name__)


def _normalize_class_name(value: str) -> str:
    return (value or "").strip().upper()


def _promote_class_name(value: str) -> str:
    raw = _normalize_class_name(value)
    match = re.match(r"^(\d+)(.*)$", raw)
    if not match:
        return raw
    level = int(match.group(1))
    suffix = match.group(2) or ""
    return f"{level + 1}{suffix}"


@bp.route("/admin")
@login_required
@admin_required
def admin():
    db = get_db()
    users = db.execute(
        """
        SELECT
            id,
            username,
            nom_affichage,
            is_admin,
            COALESCE(role, CASE WHEN COALESCE(is_admin, 0) = 1 THEN 'admin' ELSE 'prof' END) AS role
        FROM users
        ORDER BY is_admin DESC, id ASC
        """
    ).fetchall()
    all_docs = db.execute(
        """
        SELECT d.id, d.titre, d.type_doc, d.filename, u.nom_affichage
        FROM documents d
        JOIN users u ON u.id = d.user_id
        ORDER BY d.id DESC
        """
    ).fetchall()
    school_years = list_school_years(db)
    active_school_year = get_active_school_year(db)
    teacher_subjects = db.execute(
        """
        SELECT
            u.id AS user_id,
            u.username,
            u.nom_affichage,
            s.id AS subject_id,
            s.name AS subject_name
        FROM users u
        JOIN subjects s ON s.user_id = u.id
        WHERE COALESCE(u.is_admin, 0) = 0
        ORDER BY u.nom_affichage COLLATE NOCASE, s.name COLLATE NOCASE
        """
    ).fetchall()
    assignments = db.execute(
        """
        SELECT
            a.id,
            a.school_year,
            a.class_name,
            u.nom_affichage,
            u.username,
            s.name AS subject_name
        FROM teacher_assignments a
        JOIN users u ON u.id = a.user_id
        JOIN subjects s ON s.id = a.subject_id
        ORDER BY a.school_year DESC, u.nom_affichage COLLATE NOCASE, s.name COLLATE NOCASE, a.class_name COLLATE NOCASE
        """
    ).fetchall()
    available_classes = [
        r["niveau"]
        for r in db.execute(
            "SELECT DISTINCT niveau FROM eleves ORDER BY niveau COLLATE NOCASE"
        ).fetchall()
    ]
    return render_template(
        "admin.html",
        users=users,
        all_docs=all_docs,
        school_years=school_years,
        active_school_year=active_school_year,
        teacher_subjects=teacher_subjects,
        assignments=assignments,
        available_classes=available_classes,
    )


@bp.route("/admin/school_year/add", methods=["POST"])
@login_required
@admin_required
def admin_add_school_year():
    label = (request.form.get("label") or "").strip()
    if not label:
        flash("Annee scolaire manquante.", "warning")
        return redirect(url_for("admin.admin"))
    match = re.match(r"^(\d{4})/(\d{4})$", label)
    if not match:
        flash("Format invalide. Utilisez AAAA/AAAA (ex: 2026/2027).", "warning")
        return redirect(url_for("admin.admin"))
    y1 = int(match.group(1))
    y2 = int(match.group(2))
    if y2 != y1 + 1:
        flash("Format invalide: la 2eme annee doit etre +1.", "warning")
        return redirect(url_for("admin.admin"))

    db = get_db()
    before = db.execute(
        "SELECT id FROM school_years WHERE label = ?",
        (label,),
    ).fetchone()
    db.execute(
        "INSERT OR IGNORE INTO school_years (label, is_active) VALUES (?, 0)",
        (label,),
    )
    db.commit()
    if before:
        flash("Annee scolaire deja existante.", "info")
    else:
        flash("Annee scolaire ajoutee.", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/school_year/activate/<int:year_id>", methods=["POST"])
@login_required
@admin_required
def admin_activate_school_year(year_id: int):
    db = get_db()
    row = db.execute("SELECT id, label FROM school_years WHERE id = ?", (year_id,)).fetchone()
    if not row:
        abort(404)
    db.execute("UPDATE school_years SET is_active = 0")
    db.execute("UPDATE school_years SET is_active = 1 WHERE id = ?", (year_id,))
    db.commit()
    flash(f"Annee active: {row['label']}", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/school_year/clone", methods=["POST"])
@login_required
@admin_required
def admin_clone_school_year():
    source_year = (request.form.get("from_year") or "").strip()
    target_year = (request.form.get("to_year") or "").strip()
    copy_assignments = (request.form.get("copy_assignments") or "") == "1"
    class_mode = (request.form.get("class_mode") or "keep").strip().lower()
    activate_target = (request.form.get("activate_target") or "") == "1"

    if not source_year or not target_year:
        flash("Source/cible manquante.", "warning")
        return redirect(url_for("admin.admin"))
    if source_year == target_year:
        flash("La source et la cible doivent etre differentes.", "warning")
        return redirect(url_for("admin.admin"))
    if class_mode not in ("keep", "auto_promote"):
        class_mode = "keep"

    def map_class_name(name: str) -> str:
        if class_mode == "auto_promote":
            return _promote_class_name(name)
        return _normalize_class_name(name)

    db = get_db()
    source_exists = db.execute(
        "SELECT id FROM school_years WHERE label = ?",
        (source_year,),
    ).fetchone()
    target_exists = db.execute(
        "SELECT id FROM school_years WHERE label = ?",
        (target_year,),
    ).fetchone()
    if not source_exists or not target_exists:
        flash("Annee source/cible introuvable.", "warning")
        return redirect(url_for("admin.admin"))

    existing_rows = db.execute(
        """
        SELECT user_id, nom_complet, niveau
        FROM eleves
        WHERE school_year = ?
        """,
        (target_year,),
    ).fetchall()
    existing = {
        (
            int(r["user_id"]),
            (r["nom_complet"] or "").strip().lower(),
            _normalize_class_name(r["niveau"]),
        )
        for r in existing_rows
    }

    source_rows = db.execute(
        """
        SELECT user_id, nom_complet, niveau, parent_phone, parent_email
        FROM eleves
        WHERE school_year = ?
        ORDER BY user_id, niveau COLLATE NOCASE, nom_complet COLLATE NOCASE
        """,
        (source_year,),
    ).fetchall()

    inserted = 0
    skipped = 0
    promoted = 0
    for row in source_rows:
        nom = (row["nom_complet"] or "").strip()
        source_niveau = _normalize_class_name(row["niveau"])
        target_niveau = map_class_name(source_niveau)
        key = (int(row["user_id"]), nom.lower(), target_niveau)
        if not nom or not target_niveau or key in existing:
            skipped += 1
            continue

        db.execute(
            """
            INSERT INTO eleves (
                user_id,
                school_year,
                nom_complet,
                niveau,
                parent_phone,
                parent_email
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(row["user_id"]),
                target_year,
                nom,
                target_niveau,
                (row["parent_phone"] or "").strip(),
                (row["parent_email"] or "").strip(),
            ),
        )
        inserted += 1
        if target_niveau != source_niveau:
            promoted += 1
        existing.add(key)

    new_assignments = 0
    if copy_assignments:
        existing_assignments_rows = db.execute(
            """
            SELECT user_id, subject_id, class_name
            FROM teacher_assignments
            WHERE school_year = ?
            """,
            (target_year,),
        ).fetchall()
        existing_assignments = {
            (
                int(r["user_id"]),
                int(r["subject_id"]),
                _normalize_class_name(r["class_name"]),
            )
            for r in existing_assignments_rows
        }

        src_assignments = db.execute(
            """
            SELECT user_id, subject_id, class_name
            FROM teacher_assignments
            WHERE school_year = ?
            """,
            (source_year,),
        ).fetchall()
        if src_assignments:
            for row in src_assignments:
                target_class = map_class_name(row["class_name"])
                key = (int(row["user_id"]), int(row["subject_id"]), target_class)
                if not target_class or key in existing_assignments:
                    continue
                db.execute(
                    """
                    INSERT INTO teacher_assignments (user_id, school_year, subject_id, class_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (int(row["user_id"]), target_year, int(row["subject_id"]), target_class),
                )
                existing_assignments.add(key)
                new_assignments += 1

    if activate_target:
        db.execute("UPDATE school_years SET is_active = 0")
        db.execute("UPDATE school_years SET is_active = 1 WHERE label = ?", (target_year,))

    db.commit()
    log_change(
        "clone_school_year",
        session["user_id"],
        details=(
            f"{source_year} -> {target_year} | "
            f"mode={class_mode} | eleves {inserted} (skip {skipped}, promoted {promoted}) | "
            f"assign {new_assignments} | active={1 if activate_target else 0}"
        ),
    )
    active_msg = " L annee cible est maintenant active." if activate_target else ""
    flash(
        f"Passage d annee termine: {inserted} eleves copies ({skipped} ignores, {promoted} promus), {new_assignments} affectations ajoutees.{active_msg}",
        "success",
    )
    return redirect(url_for("admin.admin"))


@bp.route("/admin/assignment/add", methods=["POST"])
@login_required
@admin_required
def admin_add_assignment():
    ref = (request.form.get("teacher_subject") or "").strip()
    school_year = (request.form.get("school_year") or "").strip()
    class_name = (request.form.get("class_name") or "").strip()
    if not ref or not school_year or not class_name:
        flash("Champs assignation manquants.", "warning")
        return redirect(url_for("admin.admin"))

    try:
        user_id_s, subject_id_s = ref.split("|", 1)
        user_id = int(user_id_s)
        subject_id = int(subject_id_s)
    except Exception:
        flash("Valeur enseignant/matiere invalide.", "danger")
        return redirect(url_for("admin.admin"))

    db = get_db()
    school_year_row = db.execute(
        "SELECT id FROM school_years WHERE label = ?",
        (school_year,),
    ).fetchone()
    if not school_year_row:
        flash("Annee scolaire introuvable.", "warning")
        return redirect(url_for("admin.admin"))
    class_name = class_name.upper()
    user_row = db.execute(
        "SELECT id, is_admin FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user_row:
        flash("Utilisateur introuvable.", "warning")
        return redirect(url_for("admin.admin"))
    if int(user_row["is_admin"] or 0) == 1:
        flash("Affectation impossible pour un compte admin.", "warning")
        return redirect(url_for("admin.admin"))
    link_row = db.execute(
        "SELECT 1 FROM subjects WHERE id = ? AND user_id = ?",
        (subject_id, user_id),
    ).fetchone()
    if not link_row:
        flash("La matiere ne correspond pas a cet enseignant.", "warning")
        return redirect(url_for("admin.admin"))

    exists = db.execute(
        """
        SELECT id
        FROM teacher_assignments
        WHERE user_id = ? AND school_year = ? AND subject_id = ? AND class_name = ?
        """,
        (user_id, school_year, subject_id, class_name),
    ).fetchone()
    db.execute(
        """
        INSERT OR IGNORE INTO teacher_assignments (user_id, school_year, subject_id, class_name)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, school_year, subject_id, class_name),
    )
    db.commit()
    if exists:
        flash("Affectation deja existante.", "info")
    else:
        flash("Affectation enregistree.", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/assignment/delete/<int:assignment_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_assignment(assignment_id: int):
    db = get_db()
    db.execute("DELETE FROM teacher_assignments WHERE id = ?", (assignment_id,))
    db.commit()
    flash("Affectation supprimee.", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/create_user", methods=["POST"])
@login_required
@admin_required
def admin_create_user():
    username = (request.form.get("username") or "").strip()
    display = (request.form.get("display_name") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "prof").strip().lower()
    school_name = (request.form.get("school_name") or "").strip()
    subject_name = (request.form.get("subject_name") or "").strip()

    if not username or not display or not password or not school_name or not subject_name:
        flash("Champs manquants.", "warning")
        return redirect(url_for("admin.admin"))

    if role not in ("admin", "prof", "read_only"):
        role = "prof"
    is_admin = 1 if role == "admin" else 0
    lock_subject = 0 if is_admin else 1
    db = get_db()
    existing = db.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if existing:
        flash("Username deja utilise.", "danger")
        return redirect(url_for("admin.admin"))

    cur = db.execute(
        "INSERT INTO users (username, password, nom_affichage, is_admin, role, school_name, default_subject, lock_subject) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (username, generate_password_hash(password), display, is_admin, role, school_name, subject_name, lock_subject),
    )
    db.commit()
    user_id = cur.lastrowid
    if subject_name:
        db.execute(
            "INSERT OR IGNORE INTO subjects (user_id, name) VALUES (?, ?)",
            (int(user_id), subject_name),
        )
        db.commit()
    init_default_rules(int(user_id))
    log_change("create_user", session["user_id"], details=username)
    flash("Utilisateur cree.", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/toggle_role/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_toggle_role(user_id: int):
    if session.get("user_id") == user_id:
        flash("Action interdite sur votre compte.", "warning")
        return redirect(url_for("admin.admin"))

    db = get_db()
    user = db.execute(
        "SELECT id, username, is_admin, COALESCE(role, CASE WHEN COALESCE(is_admin, 0)=1 THEN 'admin' ELSE 'prof' END) AS role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user:
        abort(404)

    new_role = 0 if int(user["is_admin"] or 0) == 1 else 1
    role_value = "admin" if new_role == 1 else "prof"
    db.execute(
        "UPDATE users SET is_admin = ?, role = ?, lock_subject = ? WHERE id = ?",
        (new_role, role_value, 0 if role_value == "admin" else 1, user_id),
    )
    db.commit()
    role_label = "admin" if new_role == 1 else "prof"
    log_change("toggle_role", session["user_id"], details=f"{user['username']} -> {role_label}")
    flash("Role mis a jour.", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/set_role/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_set_role(user_id: int):
    if session.get("user_id") == user_id:
        flash("Action interdite sur votre compte.", "warning")
        return redirect(url_for("admin.admin"))

    role = (request.form.get("role") or "").strip().lower()
    if role not in ("admin", "prof", "read_only"):
        flash("Role invalide.", "warning")
        return redirect(url_for("admin.admin"))

    db = get_db()
    user = db.execute(
        "SELECT id, username FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user:
        abort(404)

    is_admin = 1 if role == "admin" else 0
    lock_subject = 0 if role == "admin" else 1
    db.execute(
        "UPDATE users SET role = ?, is_admin = ?, lock_subject = ? WHERE id = ?",
        (role, is_admin, lock_subject, user_id),
    )
    db.commit()
    log_change("set_role", session["user_id"], details=f"{user['username']} -> {role}")
    flash("Role mis a jour.", "success")
    return redirect(url_for("admin.admin"))


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
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    temp_password = "".join(secrets.choice(alphabet) for _ in range(10))
    db.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (generate_password_hash(temp_password), user_id),
    )
    db.commit()
    log_change("admin_reset_password", session["user_id"], details=user["username"])
    flash(
        f"Mot de passe temporaire pour {user['username']}: {temp_password}",
        "success",
    )
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
    username = user["username"]

    try:
        db.execute("BEGIN")
        db.execute("DELETE FROM notes WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM change_log WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM timetable WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM appreciations WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM teacher_assignments WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM subjects WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM eleves WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM login_attempts WHERE username = ?", ((username or "").lower(),))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    except Exception as exc:
        db.rollback()
        flash(f"Suppression impossible: {exc}", "danger")
        return redirect(url_for("admin.admin"))

    for d in docs:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], d["filename"]))
        except Exception:
            pass

    log_change("delete_user", session["user_id"], details=username)
    flash(f"Utilisateur supprime: {user['username']}", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/delete_document/<int:doc_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_document(doc_id: int):
    db = get_db()
    doc = db.execute(
        "SELECT id, filename FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not doc:
        abort(404)

    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    db.commit()

    try:
        os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], doc["filename"]))
    except Exception:
        pass

    log_change("admin_delete_document", session["user_id"], details=str(doc_id))
    flash("Document supprime.", "success")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/voir_eleves/<int:user_id>")
@login_required
@admin_required
def admin_voir_eleves(user_id: int):
    db = get_db()
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=True,
    )
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
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? AND school_year = ? ORDER BY niveau",
            (user_id, selected_school_year),
        ).fetchall()
    ]

    subject_row = db.execute(
        """
        SELECT s.id
        FROM subjects s
        LEFT JOIN users u ON u.id = s.user_id
        WHERE s.user_id = ?
        ORDER BY
          CASE
            WHEN LOWER(TRIM(s.name)) = LOWER(TRIM(COALESCE(u.default_subject, ''))) THEN 0
            ELSE 1
          END,
          s.id
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    subject_id = int(subject_row["id"]) if subject_row else -1

    query = f"""
        SELECT
            e.id,
            e.nom_complet,
            e.niveau,
            COALESCE(n.devoir, e.devoir_t{trim}) AS devoir,
            COALESCE(n.activite, e.activite_t{trim}) AS activite,
            COALESCE(n.compo, e.compo_t{trim}) AS compo,
            COALESCE(n.remarques, e.remarques_t{trim}) AS remarques
        FROM eleves e
        LEFT JOIN notes n
          ON n.user_id = e.user_id
         AND n.eleve_id = e.id
         AND n.subject_id = ?
         AND n.trimestre = ?
        WHERE e.user_id = ? AND e.school_year = ?
    """
    params = [subject_id, int(trim), user_id, selected_school_year]
    if niveau and niveau != "all":
        query += " AND e.niveau = ?"
        params.append(niveau)
    query += " ORDER BY e.niveau, e.id"

    eleves_db = db.execute(query, params).fetchall()
    eleves_list = []
    admis, total_moy, count_saisis, notes = 0, 0, 0, []

    for el in eleves_db:
        d = float(el["devoir"] or 0)
        a = float(el["activite"] or 0)
        c = float(el["compo"] or 0)
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
                "remarques": el["remarques"] or "",
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
        school_year=selected_school_year,
        school_years=list_school_years(db),
        active_school_year=get_active_school_year(db),
        liste_classes=classes,
    )
