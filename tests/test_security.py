"""Integration tests for core security and auth routes."""
import pytest


class TestCSRF:
    def test_post_without_csrf_returns_400(self, client):
        response = client.post("/login", data={"username": "test", "password": "test"})
        assert response.status_code == 400

    def test_static_bypass(self, client):
        response = client.get("/static/manifest.json")
        assert response.status_code == 200


class TestLogin:
    def test_login_page(self, client):
        response = client.get("/login")
        assert response.status_code == 200

    def test_login_bad_creds(self, client):
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "test"
        response = client.post("/login", data={
            "username": "nonexistent",
            "password": "wrong",
            "csrf_token": "test",
        }, follow_redirects=True)
        assert response.status_code == 200


class TestProtectedRoutes:
    def test_dashboard_requires_login(self, client):
        response = client.get("/")
        assert response.status_code == 302
        assert "/login" in response.headers.get("Location", "")

    def test_dashboard_accessible_when_logged_in(self, auth_client):
        response = auth_client.get("/")
        assert response.status_code == 200
