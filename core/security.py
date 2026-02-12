import base64
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime
from functools import wraps

from flask import session, request, redirect, abort, flash, url_for
from markupsafe import Markup

from .config import LICENSE_FILE, CACHE_FILE, SECRET_LICENCE, DATABASE


def get_machine_id():
    node = uuid.getnode()
    return hashlib.md5(str(node).encode()).hexdigest().upper()[:12]


def verifier_manipulation_horloge():
    now_ts = datetime.now().timestamp()
    last_time = 0
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                val = f.read().strip()
                if val:
                    last_time = float(val)
        except Exception:
            pass
    if now_ts < (last_time - 600):
        return False
    if os.path.exists(DATABASE):
        try:
            db_mtime = os.path.getmtime(DATABASE)
            if now_ts < (db_mtime - 600):
                return False
        except Exception:
            pass
    try:
        with open(CACHE_FILE, 'w') as f:
            f.write(str(now_ts))
    except Exception:
        pass
    return True


def verifier_validite_licence():
    if not verifier_manipulation_horloge():
        return False, "Erreur Date Système"
    if not os.path.exists(LICENSE_FILE):
        return False, "Aucune licence trouvée"
    try:
        with open(LICENSE_FILE, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
        if not raw:
            return False, "Fichier licence invalide"

        # Backward compatible:
        # - New format: JSON {"cle": "...", "mid": "..."}
        # - Legacy format: file contains the license key string (EDUPRO-... or base64) only.
        try:
            licence_locale = json.loads(raw)
        except json.JSONDecodeError:
            licence_locale = {"cle": raw, "mid": get_machine_id()}
            # Best-effort migration to the new file format so we don't prompt activation again.
            try:
                with open(LICENSE_FILE, 'w', encoding='utf-8') as wf:
                    json.dump(licence_locale, wf)
            except Exception:
                pass

        if licence_locale.get('mid') != get_machine_id():
            return False, "Licence copiée illégalement."
        cle_val = licence_locale.get('cle')
        if not cle_val:
            return False, "Clé invalide."
        cle_nettoye = cle_val.replace("EDUPRO-", "")
        data = json.loads(base64.b64decode(cle_nettoye).decode())
        date_exp = data.get('date')
        sig = data.get('sig')
        if sig != hashlib.sha256(f"{date_exp}|{SECRET_LICENCE}".encode()).hexdigest()[:16].upper():
            return False, "Clé corrompue."
        if datetime.now() > datetime.strptime(date_exp, '%Y-%m-%d'):
            return False, f"Expirée le {date_exp}"
        return True, date_exp
    except Exception:
        return False, "Fichier licence invalide"


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_valid, msg = verifier_validite_licence()
        if not is_valid:
            from urllib.parse import urlencode
            return redirect("/activation?" + urlencode({"error": msg}))
        if 'user_id' not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect("/login")
        if not session.get('is_admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def write_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")

        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            role = session.get("role")
            if not role:
                role = "admin" if session.get("is_admin") else "prof"
            if role == "read_only":
                flash("Compte en lecture seule: modification non autorisee.", "warning")
                target = request.referrer
                if target:
                    return redirect(target)
                try:
                    return redirect(url_for("dashboard.index"))
                except Exception:
                    return redirect("/")
        return f(*args, **kwargs)

    return decorated_function


def _get_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def csrf_token():
    return _get_csrf_token()


def csrf_field():
    return Markup(f'<input type="hidden" name="csrf_token" value="{_get_csrf_token()}">')


def csrf_protect():
    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return
    if request.endpoint == 'static':
        return
    token = session.get('_csrf_token')
    form_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or not form_token or token != form_token:
        abort(400, description='CSRF token missing or invalid')


def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    return response


def init_security(app):
    app.before_request(csrf_protect)
    app.after_request(add_security_headers)
    app.jinja_env.globals['csrf_field'] = csrf_field
    app.jinja_env.globals['csrf_token'] = csrf_token
