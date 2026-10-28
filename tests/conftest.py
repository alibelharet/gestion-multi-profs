"""Pytest fixtures for EduMaster Pro tests."""
import os
import shutil
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
    os.environ["SECRET_LICENCE"] = "test-license-secret"
    os.environ["STRICT_LICENSE_MACHINE_CHECK"] = "0"

    # Modules may already have been imported during test collection; point all
    # module-level settings at disposable test files rather than user data.
    from core import config as config_module
    import core.db as db_module
    import core.security as security_module

    isolation_dir = tempfile.mkdtemp(prefix="edumaster_test_runtime_")
    license_path = os.path.join(isolation_dir, "license.key")
    cache_path = os.path.join(isolation_dir, ".sys_check")
    config_module.DATABASE = db_path
    config_module.LICENSE_FILE = license_path
    config_module.CACHE_FILE = cache_path
    config_module.SECRET_LICENCE = os.environ["SECRET_LICENCE"]
    db_module.DATABASE = db_path
    security_module.DATABASE = db_path
    security_module.LICENSE_FILE = license_path
    security_module.CACHE_FILE = cache_path
    security_module.SECRET_LICENCE = os.environ["SECRET_LICENCE"]

    # Create a minimal license key so the app doesn't block
    import base64
    import hashlib
    import json
    from datetime import datetime, timedelta

    secret = os.environ["SECRET_LICENCE"]
    future_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    sig = hashlib.sha256(f"{future_date}|{secret}".encode()).hexdigest()[:16].upper()
    payload = base64.b64encode(json.dumps({"date": future_date, "sig": sig}).encode()).decode()
    key_val = f"EDUPRO-{payload}"

    from core.security import get_machine_id
    mid = get_machine_id()
    with open(license_path, "w") as f:
        json.dump({"cle": key_val, "mid": mid}, f)

    from edumaster import create_app
    test_app = create_app()
    test_app.config["TESTING"] = True
    test_app.config["WTF_CSRF_ENABLED"] = False
    test_app.config["SESSION_COOKIE_SECURE"] = False
    uploads_dir = tempfile.mkdtemp(prefix="edumaster_test_uploads_")
    test_app.config["UPLOAD_FOLDER"] = uploads_dir

    yield test_app

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)
    shutil.rmtree(uploads_dir, ignore_errors=True)
    shutil.rmtree(isolation_dir, ignore_errors=True)


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
