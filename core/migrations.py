"""Simple schema versioning system for SQLite.

Uses a `schema_version` table to track the current version.
Each migration function advances the schema by one version.
"""
import sqlite3


def _get_version(db):
    """Return the current schema version, or 0 if not tracked yet."""
    try:
        row = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return int(row["v"] or 0)
    except sqlite3.OperationalError:
        return 0


def _set_version(db, version):
    """Record a new schema version."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)"
    )
    db.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
        (version,),
    )


# ── Migration functions ───────────────────────────────────────────
# Each function receives the db connection and must NOT commit.
# The runner commits once after all migrations succeed.


def _migrate_to_v1(db):
    """Add notifications table."""
    db.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        category TEXT DEFAULT 'info',
        is_read INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read)")


def _migrate_to_v2(db):
    """Add homework table."""
    db.execute("""CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        school_year TEXT NOT NULL,
        niveau TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        due_date TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_homework_user_year ON homework(user_id, school_year)")


# Ordered list of migrations
_MIGRATIONS = [
    (1, _migrate_to_v1),
    (2, _migrate_to_v2),
]


def run_migrations(db):
    """Run all pending migrations in order."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)"
    )
    current = _get_version(db)
    applied = 0
    for version, func in _MIGRATIONS:
        if version > current:
            func(db)
            _set_version(db, version)
            applied += 1
    if applied:
        db.commit()
    return applied
