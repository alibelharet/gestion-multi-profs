"""Notifications blueprint — CRUD + badge API for unread notifications."""
import time
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from core.db import get_db
from core.security import login_required, admin_required

bp = Blueprint("notifications", __name__)


@bp.route("/notifications")
@login_required
def index():
    user_id = session["user_id"]
    db = get_db()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    notifs = []
    for r in rows:
        item = dict(r)
        try:
            from datetime import datetime
            item["time"] = datetime.fromtimestamp(item["created_at"]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            item["time"] = ""
        notifs.append(item)
    return render_template("notifications.html", notifications=notifs)


@bp.route("/notifications/read/<int:notif_id>", methods=["POST"])
@login_required
def mark_read(notif_id):
    user_id = session["user_id"]
    db = get_db()
    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notif_id, user_id),
    )
    db.commit()
    return redirect(url_for("notifications.index"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    user_id = session["user_id"]
    db = get_db()
    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ?",
        (user_id,),
    )
    db.commit()
    flash("Toutes les notifications marquees comme lues.", "success")
    return redirect(url_for("notifications.index"))


@bp.route("/api/notifications/count")
@login_required
def unread_count():
    user_id = session["user_id"]
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()
    return jsonify({"count": int(row["c"] or 0)})


def create_notification(db, user_id, title, body="", category="info"):
    """Helper to create a notification programmatically."""
    db.execute(
        "INSERT INTO notifications (user_id, title, body, category, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, title, body, category, int(time.time())),
    )
    db.commit()
