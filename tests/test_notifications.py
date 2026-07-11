"""Tests for application notifications."""

from edumaster.routes.notifications import create_notification


def test_create_notification_and_unread_badge(auth_client, app):
    with app.app_context():
        from core.db import get_db

        db = get_db()
        user = db.execute("SELECT id FROM users WHERE username = ?", ("testprof",)).fetchone()
        assert create_notification(db, user["id"], "Import terminé", "12 lignes", "success")

    response = auth_client.get("/api/notifications/count")
    assert response.status_code == 200
    assert response.get_json()["count"] == 1


def test_notification_fields_are_bounded(db):
    db.execute(
        "INSERT INTO users (username, password, nom_affichage) VALUES (?, ?, ?)",
        ("notif-user", "hash", "Notification User"),
    )
    db.commit()
    user_id = db.execute("SELECT id FROM users WHERE username = ?", ("notif-user",)).fetchone()["id"]

    assert create_notification(db, user_id, "T" * 200, "B" * 700, "unknown")
    row = db.execute("SELECT title, body, category FROM notifications WHERE user_id = ?", (user_id,)).fetchone()
    assert len(row["title"]) == 120
    assert len(row["body"]) == 500
    assert row["category"] == "info"
