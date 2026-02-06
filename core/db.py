import os
import sqlite3
from flask import g
from werkzeug.security import generate_password_hash
from .config import DATABASE


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            # Some environments may not allow WAL; continue safely.
            pass
    return db


def close_db(exception=None):
    db = g.pop("_database", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        nom_affichage TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        role TEXT DEFAULT 'prof',
        school_name TEXT DEFAULT '',
        default_subject TEXT DEFAULT '',
        lock_subject INTEGER DEFAULT 0
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS eleves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        nom_complet TEXT NOT NULL,
        niveau TEXT NOT NULL,
        remarques_t1 TEXT DEFAULT '',
        remarques_t2 TEXT DEFAULT '',
        remarques_t3 TEXT DEFAULT '',
        devoir_t1 REAL DEFAULT 0,
        activite_t1 REAL DEFAULT 0,
        compo_t1 REAL DEFAULT 0,
        devoir_t2 REAL DEFAULT 0,
        activite_t2 REAL DEFAULT 0,
        compo_t2 REAL DEFAULT 0,
        devoir_t3 REAL DEFAULT 0,
        activite_t3 REAL DEFAULT 0,
        compo_t3 REAL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        titre TEXT NOT NULL,
        type_doc TEXT NOT NULL,
        niveau TEXT NOT NULL,
        filename TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        UNIQUE(user_id, name),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        eleve_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        trimestre INTEGER NOT NULL,
        participation REAL DEFAULT 0,
        comportement REAL DEFAULT 0,
        cahier REAL DEFAULT 0,
        projet REAL DEFAULT 0,
        assiduite_outils REAL DEFAULT 0,
        activite REAL DEFAULT 0,
        devoir REAL DEFAULT 0,
        compo REAL DEFAULT 0,
        remarques TEXT DEFAULT '',
        UNIQUE(user_id, eleve_id, subject_id, trimestre),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(eleve_id) REFERENCES eleves(id),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        eleve_id INTEGER,
        subject_id INTEGER,
        details TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        niveau TEXT NOT NULL,
        day TEXT NOT NULL,
        slot TEXT NOT NULL,
        label TEXT NOT NULL,
        UNIQUE(user_id, niveau, day, slot),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    db.execute('CREATE INDEX IF NOT EXISTS idx_notes_user_subject_trim ON notes(user_id, subject_id, trimestre)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_change_log_user_time ON change_log(user_id, created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_eleves_user_niveau ON eleves(user_id, niveau)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_eleves_user_nom ON eleves(user_id, nom_complet)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_documents_user_type ON documents(user_id, type_doc)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_timetable_user_niveau ON timetable(user_id, niveau)')
    db.execute('''CREATE TABLE IF NOT EXISTS appreciations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        min_val REAL NOT NULL,
        max_val REAL NOT NULL,
        message TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS login_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        ip TEXT NOT NULL,
        username TEXT NOT NULL,
        success INTEGER NOT NULL
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_user_ip_ts ON login_attempts(username, ip, ts)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_ts ON login_attempts(ip, ts)')

    db.execute('''CREATE TABLE IF NOT EXISTS password_reset_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        used INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    # Add new columns safely (ignore if already exists).
    try:
        db.execute('ALTER TABLE eleves ADD COLUMN parent_phone TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE eleves ADD COLUMN parent_email TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN school_name TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN default_subject TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN lock_subject INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'prof'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE notes ADD COLUMN participation REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE notes ADD COLUMN comportement REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE notes ADD COLUMN cahier REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE notes ADD COLUMN projet REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE notes ADD COLUMN assiduite_outils REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    # Legacy cleanup: attendance module removed.
    db.execute('DROP INDEX IF EXISTS idx_attendance_user_trim_type')
    db.execute('DROP INDEX IF EXISTS idx_attendance_user_eleve_trim')
    db.execute('DROP TABLE IF EXISTS attendance')

    # Keep role/is_admin consistent.
    db.execute(
        """
        UPDATE users
        SET role = CASE
            WHEN COALESCE(role, '') = '' AND COALESCE(is_admin, 0) = 1 THEN 'admin'
            WHEN COALESCE(role, '') = '' THEN 'prof'
            ELSE role
        END
        """
    )
    db.execute("UPDATE users SET role = 'admin' WHERE COALESCE(is_admin, 0) = 1")
    db.execute("UPDATE users SET is_admin = CASE WHEN role = 'admin' THEN 1 ELSE 0 END")

    # Enforce single-subject mode for all non-admin accounts.
    db.execute("UPDATE users SET lock_subject = 1 WHERE COALESCE(is_admin, 0) = 0")
    db.execute(
        """
        UPDATE users
        SET default_subject = COALESCE(
            NULLIF(default_subject, ''),
            (SELECT s.name FROM subjects s WHERE s.user_id = users.id ORDER BY s.id LIMIT 1),
            'Sciences'
        )
        WHERE COALESCE(is_admin, 0) = 0
        """
    )
    db.commit()


def bootstrap_admin():
    admin_user = os.environ.get("ADMIN_USER")
    admin_pass = os.environ.get("ADMIN_PASS")
    admin_display = os.environ.get("ADMIN_DISPLAY", admin_user)
    if not admin_user or not admin_pass:
        return
    db = get_db()
    admin = db.execute('SELECT * FROM users WHERE username = ?', (admin_user,)).fetchone()
    if not admin:
        db.execute(
            "INSERT INTO users (username, password, nom_affichage, is_admin, role) VALUES (?, ?, ?, ?, ?)",
            (admin_user, generate_password_hash(admin_pass), admin_display or admin_user, 1, "admin")
        )
        db.commit()
