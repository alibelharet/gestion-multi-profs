from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from core.auth_security import (
    cleanup_old_login_attempts,
    get_client_ip,
    is_login_locked,
    lock_message,
    record_login_attempt,
)
from core.db import get_db
from core.password_reset import consume_reset_token, set_user_password
from core.security import login_required, verifier_validite_licence
from core.utils import init_default_rules

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    is_valid, msg = verifier_validite_licence()
    if not is_valid:
        return redirect(url_for("licence.activation", error=msg))

    if request.method == "POST":
        db = get_db()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        nom_affichage = request.form.get("nom_affichage", "").strip()
        subject_name = request.form.get("subject_name", "").strip()
        school_name = request.form.get("school_name", "").strip()

        if not username or not password or not nom_affichage or not subject_name or not school_name:
            flash("Champs manquants.", "danger")
            return render_template("register.html")

        if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            flash("Utilisateur existe déjà.", "danger")
        else:
            db.execute(
                "INSERT INTO users (username, password, nom_affichage, school_name, default_subject, lock_subject) VALUES (?, ?, ?, ?, ?, ?)",
                (username, generate_password_hash(password), nom_affichage, school_name, subject_name, 1),
            )
            db.commit()
            user_id = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()[
                "id"
            ]
            if subject_name:
                db.execute(
                    "INSERT OR IGNORE INTO subjects (user_id, name) VALUES (?, ?)",
                    (int(user_id), subject_name),
                )
                db.commit()
            init_default_rules(int(user_id))
            return redirect(url_for("auth.login"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    is_valid, msg = verifier_validite_licence()
    if not is_valid:
        return redirect(url_for("licence.activation", error=msg))

    if request.method == "POST":
        db = get_db()
        cleanup_old_login_attempts(db)

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = get_client_ip(request)

        locked, remaining = is_login_locked(db, username, ip)
        if locked:
            flash(lock_message(remaining), "danger")
            record_login_attempt(db, username, ip, success=False)
            return render_template("login.html")

        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = bool(user and check_password_hash(user["password"], password))
        record_login_attempt(db, username, ip, success=ok)

        if ok:
            session["user_id"] = user["id"]
            session["nom_affichage"] = user["nom_affichage"]
            session["is_admin"] = user["is_admin"]
            session["school_name"] = user["school_name"] if "school_name" in user.keys() else ""
            session["lock_subject"] = user["lock_subject"] if "lock_subject" in user.keys() else 0
            session["default_subject"] = user["default_subject"] if "default_subject" in user.keys() else ""
            return redirect(url_for("main.index"))

        flash("Utilisateur ou mot de passe incorrect.", "danger")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/forgot")
def forgot():
    is_valid, msg = verifier_validite_licence()
    if not is_valid:
        return redirect(url_for("licence.activation", error=msg))
    return render_template("forgot.html")


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    is_valid, msg = verifier_validite_licence()
    if not is_valid:
        return redirect(url_for("licence.activation", error=msg))

    if request.method == "POST":
        pw = request.form.get("password") or ""
        pw2 = request.form.get("password_confirm") or ""
        if len(pw) < 6:
            return render_template(
                "reset_password.html", error="Mot de passe trop court (min 6)."
            )
        if pw != pw2:
            return render_template(
                "reset_password.html", error="Les mots de passe ne correspondent pas."
            )

        user_id = consume_reset_token(token)
        if not user_id:
            return render_template("reset_password.html", error="Lien invalide ou expiré.")

        set_user_password(user_id, pw)
        flash("Mot de passe mis à jour. Vous pouvez vous connecter.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html")


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        db = get_db()
        user_id = session["user_id"]
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if check_password_hash(user["password"], request.form["old_password"]):
            db.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (generate_password_hash(request.form["new_password"]), user_id),
            )
            db.commit()
            flash("Mot de passe modifié", "success")
        else:
            flash("Ancien mot de passe incorrect", "danger")

    is_valid, info = verifier_validite_licence()
    date_fin = info if is_valid else "-"
    try:
        jours_restants = (
            datetime.strptime(date_fin, "%Y-%m-%d") - datetime.now()
        ).days if is_valid else 0
    except Exception:
        jours_restants = 0

    return render_template(
        "profile.html",
        nom_prof=session.get("nom_affichage"),
        date_fin=date_fin,
        jours_restants=jours_restants,
    )
