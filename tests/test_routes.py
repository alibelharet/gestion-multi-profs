"""Integration tests for main application routes."""
import pytest


class TestRoutes:
    def test_register_page(self, client):
        response = client.get("/register")
        assert response.status_code == 200

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

    def test_stats_page(self, auth_client):
        response = auth_client.get("/stats")
        assert response.status_code == 200

    def test_set_lang_ar(self, auth_client):
        response = auth_client.get("/lang/ar", follow_redirects=False)
        assert response.status_code == 302

    def test_set_lang_fr(self, auth_client):
        response = auth_client.get("/lang/fr", follow_redirects=False)
        assert response.status_code == 302
