import base64
import hashlib
import json
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from core.config import CACHE_FILE, LICENSE_FILE, SECRET_LICENCE
from core.security import get_machine_id

bp = Blueprint("licence", __name__)


@bp.route("/activation", methods=["GET", "POST"])
def activation():
    error = request.args.get("error")
    if request.method == "POST":
        try:
            cle_input = request.form["cle_licence"].strip()
            data = json.loads(base64.b64decode(cle_input.replace("EDUPRO-", "")).decode())
            if data.get("sig") == hashlib.sha256(
                f"{data.get('date')}|{SECRET_LICENCE}".encode()
            ).hexdigest()[:16].upper():
                with open(LICENSE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"cle": cle_input, "mid": get_machine_id()}, f)
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    f.write(str(datetime.now().timestamp()))
                flash(f"Licence activée ! (Valide jusqu'au {data.get('date')})", "success")
                return redirect(url_for("auth.login"))
            flash("Clé invalide.", "danger")
        except Exception:
            flash("Clé non reconnue.", "danger")
    return render_template("activation.html", error=error)

