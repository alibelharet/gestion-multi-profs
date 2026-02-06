import os
import uuid

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from core.db import get_db
from core.security import login_required, write_required
from core.utils import is_allowed_upload

bp = Blueprint("docs", __name__)


@bp.route("/ressources")
@login_required
def ressources():
    role = session.get("role") or ("admin" if session.get("is_admin") else "prof")
    can_edit = role != "read_only"
    docs = get_db().execute(
        "SELECT * FROM documents WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("ressources.html", docs=docs, can_edit=can_edit)


@bp.route("/upload", methods=["POST"])
@login_required
@write_required
def upload():
    f = request.files.get("fichier")
    if not f or not f.filename:
        flash("Aucun fichier sélectionné.", "danger")
        return redirect(url_for("docs.ressources"))

    filename = secure_filename(f.filename)
    if not is_allowed_upload(filename):
        flash("Type de fichier non autorisé.", "danger")
        return redirect(url_for("docs.ressources"))

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    f.save(os.path.join(current_app.config["UPLOAD_FOLDER"], unique_name))

    get_db().execute(
        "INSERT INTO documents (user_id, titre, type_doc, niveau, filename) VALUES (?, ?, ?, ?, ?)",
        (session["user_id"], request.form["titre"], request.form["type_doc"], "Global", unique_name),
    )
    get_db().commit()
    flash("Fichier envoyé.", "success")
    return redirect(url_for("docs.ressources"))


@bp.route("/supprimer_document/<int:id>", methods=["POST"])
@login_required
@write_required
def supprimer_document(id: int):
    db = get_db()
    doc = db.execute(
        "SELECT filename FROM documents WHERE id = ? AND user_id = ?",
        (id, session["user_id"]),
    ).fetchone()
    if doc:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], doc["filename"]))
        except Exception:
            pass
        db.execute("DELETE FROM documents WHERE id = ?", (id,))
        db.commit()
    return redirect(url_for("docs.ressources"))
