"""Pytest fixtures for EduMaster Pro tests."""
import os
import sys
import tempfile

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def app():
    """Create a test Flask app with an in-memory SQLite database."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.environ["DATABASE_PATH"] = db_path
    os.environ["SECRET_KEY"] = "test-secret-key"
    os.environ["STRICT_LICENSE_MACHINE_CHECK"] = "0"

    # Create a minimal license key so the app doesn't block
    import base64
    import hashlib
    import json
    from datetime import datetime, timedelta

    secret = os.environ.get("SECRET_LICENCE", "ALGERIE_ECOLE_PRO_2026_SUPER_SECRET")
    future_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    sig = hashlib.sha256(f"{future_date}|{secret}".encode()).hexdigest()[:16].upper()
    payload = base64.b64encode(json.dumps({"date": future_date, "sig": sig}).encode()).decode()
    key_val = f"EDUPRO-{payload}"

    from core.config import BASE_DIR
    license_path = os.path.join(BASE_DIR, "license.key")
    original_license = None
    if os.path.exists(license_path):
        with open(license_path, "r") as f:
            original_license = f.read()

    from core.security import get_machine_id
    mid = get_machine_id()
    with open(license_path, "w") as f:
        json.dump({"cle": key_val, "mid": mid}, f)

    from edumaster import create_app
    test_app = create_app()
    test_app.config["TESTING"] = True
    test_app.config["WTF_CSRF_ENABLED"] = False
    test_app.config["SESSION_COOKIE_SECURE"] = False

    yield test_app

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)
    if original_license is not None:
        with open(license_path, "w") as f:
            f.write(original_license)


@pytest.fixture()
def client(app):
    """Create a test HTTP client."""
    return app.test_client()


@pytest.fixture()
def db(app):
    """Get a database connection within the app context."""
    with app.app_context():
        from core.db import get_db
        yield get_db()


@pytest.fixture()
def auth_client(client, app):
    """Return a client logged in as a test teacher."""
    from werkzeug.security import generate_password_hash

    with app.app_context():
        from core.db import get_db
        db = get_db()
        db.execute(
            "INSERT OR IGNORE INTO users (username, password, nom_affichage, role, school_name, default_subject, lock_subject) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("testprof", generate_password_hash("password123"), "Prof Test", "prof", "Ecole Test", "Sciences", 1),
        )
        db.commit()
        user = db.execute("SELECT id FROM users WHERE username = 'testprof'").fetchone()
        db.execute("INSERT OR IGNORE INTO subjects (user_id, name) VALUES (?, ?)", (user["id"], "Sciences"))
        db.commit()

    # Disable CSRF for tests
    with client.session_transaction() as sess:
        sess["_csrf_token"] = "test-csrf"

    client.post("/login", data={
        "username": "testprof",
        "password": "password123",
        "csrf_token": "test-csrf",
    })
    return client
