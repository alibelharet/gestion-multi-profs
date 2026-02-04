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
        is_admin INTEGER DEFAULT 0
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
            'INSERT INTO users (username, password, nom_affichage, is_admin) VALUES (?, ?, ?, ?)',
            (admin_user, generate_password_hash(admin_pass), admin_display or admin_user, 1)
        )
        db.commit()
