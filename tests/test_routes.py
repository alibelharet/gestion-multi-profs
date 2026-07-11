"""Integration tests for main application routes."""
import pytest


class TestRoutes:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}

    def test_register_page(self, client):
        response = client.get("/register")
        assert response.status_code == 404

    def test_profile_requires_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302

    def test_admin_requires_admin(self, auth_client):
        response = auth_client.get("/admin")
        # Teacher should get 403
        assert response.status_code == 403

    def test_history_page(self, auth_client):
        response = auth_client.get("/history")
        assert response.status_code == 200

    def test_settings_page(self, auth_client):
        response = auth_client.get("/settings")
        assert response.status_code == 200

    def test_dashboard_shows_save_guard_for_teacher(self, auth_client):
        response = auth_client.get("/")
        assert response.status_code == 200
        assert b'id="formSaveAll"' in response.data
        assert b'id="unsavedChangesBar"' in response.data
        assert b'id="gradeCompletionStatus"' in response.data
        assert b'data-grade-row' in response.data or b"Aucun resultat" in response.data

    def test_stats_page(self, auth_client):
        response = auth_client.get("/stats")
        assert response.status_code == 200

    def test_stats_page_shows_decline_panel_after_first_trimester(self, auth_client):
        response = auth_client.get("/stats?trimestre=2")
        assert response.status_code == 200
        assert "Baisses à surveiller" in response.get_data(as_text=True)

    def test_set_lang_ar(self, auth_client):
        response = auth_client.get("/lang/ar", follow_redirects=False)
        assert response.status_code == 302

    def test_set_lang_fr(self, auth_client):
        response = auth_client.get("/lang/fr", follow_redirects=False)
        assert response.status_code == 302

    def test_document_download_is_private(self, auth_client, app):
        with app.app_context():
            from pathlib import Path
            from core.db import get_db

            db = get_db()
            user = db.execute("SELECT id FROM users WHERE username = ?", ("testprof",)).fetchone()
            filename = "private-test.txt"
            Path(app.config["UPLOAD_FOLDER"], filename).write_text("contenu prive", encoding="utf-8")
            cur = db.execute(
                "INSERT INTO documents (user_id, titre, type_doc, niveau, filename) VALUES (?, ?, ?, ?, ?)",
                (user["id"], "Test", "cour", "Global", filename),
            )
            db.commit()
            doc_id = cur.lastrowid

        response = auth_client.get(f"/documents/{doc_id}/download")
        assert response.status_code == 200
        assert response.data == b"contenu prive"

        anonymous = app.test_client()
        response = anonymous.get(f"/documents/{doc_id}/download")
        assert response.status_code == 302
