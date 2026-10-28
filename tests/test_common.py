"""Unit tests for edumaster.services.common and core.security modules."""
from edumaster.services.common import list_school_years, parse_trim, resolve_school_year, school_year
from datetime import datetime


class TestParseTrim:
    def test_valid(self):
        assert parse_trim("1") == "1"
        assert parse_trim("2") == "2"
        assert parse_trim("3") == "3"

    def test_invalid_returns_default(self):
        assert parse_trim("4") == "1"
        assert parse_trim("abc") == "1"
        assert parse_trim(None) == "1"

    def test_custom_default(self):
        assert parse_trim("bad", default="2") == "2"


class TestSchoolYear:
    def test_september_onward(self):
        dt = datetime(2025, 9, 15)
        assert school_year(dt) == "2025/2026"

    def test_before_september(self):
        dt = datetime(2026, 3, 1)
        assert school_year(dt) == "2025/2026"

    def test_january(self):
        dt = datetime(2026, 1, 1)
        assert school_year(dt) == "2025/2026"

def _school_year_database():
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE school_years (
            id INTEGER PRIMARY KEY, label TEXT UNIQUE, is_active INTEGER DEFAULT 0
        );
        CREATE TABLE eleves (user_id INTEGER, school_year TEXT);
        CREATE TABLE teacher_assignments (user_id INTEGER, school_year TEXT);
        INSERT INTO school_years (label, is_active) VALUES
            ('2024/2025', 0), ('2025/2026', 1), ('2026/2027', 0);
        INSERT INTO eleves (user_id, school_year) VALUES
            (1, '2026/2027'), (2, '2025/2026'),
            (3, '2024/2025'), (3, '2026/2027');
        INSERT INTO teacher_assignments (user_id, school_year) VALUES
            (4, '2024/2025');
    """)
    db.execute(
        "INSERT OR IGNORE INTO school_years (label, is_active) VALUES (?, 0)",
        (school_year(datetime.now()),),
    )
    db.commit()
    return db


class TestResolveSchoolYear:
    def setup_method(self):
        self.db = _school_year_database()

    def teardown_method(self):
        self.db.close()

    def test_teachers_default_to_their_own_year_without_changing_active_year(self):
        assert resolve_school_year(self.db, user_id=1) == "2026/2027"
        assert resolve_school_year(self.db, user_id=2) == "2025/2026"
        active = self.db.execute(
            "SELECT label FROM school_years WHERE is_active = 1"
        ).fetchall()
        assert [row["label"] for row in active] == ["2025/2026"]

    def test_requested_year_must_belong_to_teacher(self):
        assert resolve_school_year(self.db, " 2024/2025 ", user_id=3) == "2024/2025"
        assert resolve_school_year(self.db, "2025/2026", user_id=3) == "2026/2027"
        assert resolve_school_year(self.db, "2099/2100", user_id=3) == "2026/2027"

    def test_active_year_is_preferred_when_teacher_has_data_in_it(self):
        self.db.execute(
            "INSERT INTO eleves (user_id, school_year) VALUES (3, '2025/2026')"
        )
        assert resolve_school_year(self.db, user_id=3) == "2025/2026"

    def test_assignment_alone_makes_year_available(self):
        assert resolve_school_year(self.db, user_id=4) == "2024/2025"

    def test_teacher_without_data_and_call_without_session_use_active_year(self):
        assert resolve_school_year(self.db, "2026/2027", user_id=5) == "2025/2026"
        assert resolve_school_year(self.db, "2026/2027") == "2025/2026"

    def test_admin_can_choose_any_registered_year(self):
        assert resolve_school_year(self.db, "2024/2025", is_admin=True) == "2024/2025"
        assert resolve_school_year(self.db, "2099/2100", is_admin=True) == "2025/2026"

    def test_request_session_scopes_resolution_and_menu_to_teacher(self):
        from flask import Flask, session

        request_app = Flask(__name__)
        request_app.secret_key = "year-scope-test"
        with request_app.test_request_context("/"):
            session["user_id"] = 1
            session["is_admin"] = 0
            assert resolve_school_year(self.db) == "2026/2027"
            assert [row["label"] for row in list_school_years(self.db)] == ["2026/2027"]
            session["user_id"] = 4
            assert [row["label"] for row in list_school_years(self.db)] == ["2024/2025"]
            session["user_id"] = 5
            assert [row["label"] for row in list_school_years(self.db)] == ["2025/2026"]
            session["is_admin"] = 1
            assert {"2024/2025", "2025/2026", "2026/2027"} <= {
                row["label"] for row in list_school_years(self.db)
            }
        assert len(list_school_years(self.db)) >= 3


def test_dashboard_uses_teacher_year_and_rejects_another_teachers_year(auth_client, app):
    from core.db import get_db

    with app.app_context():
        db = get_db()
        teacher_id = db.execute(
            "SELECT id FROM users WHERE username = 'testprof'"
        ).fetchone()["id"]
        db.execute(
            "INSERT OR IGNORE INTO school_years (label, is_active) VALUES ('2025/2026', 0)"
        )
        db.execute(
            "INSERT OR IGNORE INTO school_years (label, is_active) VALUES ('2026/2027', 0)"
        )
        db.execute("UPDATE school_years SET is_active = (label = '2025/2026')")
        db.execute(
            "INSERT INTO users (username, password, nom_affichage) VALUES (?, ?, ?)",
            ("other-year-prof", "unused", "Other teacher"),
        )
        other_id = db.execute(
            "SELECT id FROM users WHERE username = 'other-year-prof'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO eleves (user_id, school_year, nom_complet, niveau) VALUES (?, ?, ?, ?)",
            (teacher_id, "2026/2027", "Student Alpha 2026", "1M1"),
        )
        db.execute(
            "INSERT INTO eleves (user_id, school_year, nom_complet, niveau) VALUES (?, ?, ?, ?)",
            (other_id, "2025/2026", "Student Beta 2025", "2M2"),
        )
        db.commit()

    for route in ("/", "/?school_year=2025/2026"):
        response = auth_client.get(route)
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert "Student Alpha 2026" in page
        assert "Student Beta 2025" not in page
        assert '<option value="2026/2027" selected' in page
        assert '<option value="2025/2026"' not in page

    for route in ("/stats", "/timetable"):
        response = auth_client.get(route)
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert '<select name="school_year"' in page
        assert '<option value="2026/2027"' in page
        assert '<option value="2025/2026"' not in page
