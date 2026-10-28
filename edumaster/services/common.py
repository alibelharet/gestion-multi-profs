import sqlite3
from datetime import datetime
from flask import has_request_context, session

def school_year(now):
    if now.month >= 9:
        return f"{now.year}/{now.year + 1}"
    return f"{now.year - 1}/{now.year}"

def arabize(value):
    if value is None:
        return ""
    text = str(value)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text

def parse_trim(raw, default="1"):
    trim = str(raw or default).strip()
    if trim not in ("1", "2", "3"):
        return default
    return trim

def ensure_school_years(db):
    """
    Ensure at least one active school year exists.
    Returns the active school year label.
    """
    current_label = school_year(datetime.now())

    # Try a read-only fast path first to avoid write locks on every request
    try:
        active = db.execute(
            "SELECT label FROM school_years WHERE COALESCE(is_active, 0) = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        existing_current = db.execute(
            "SELECT id FROM school_years WHERE label = ?",
            (current_label,),
        ).fetchone()
        if active and existing_current:
            return active["label"]
    except sqlite3.OperationalError:
        # If the table doesn't exist yet, we fallback to the creation logic below
        pass

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS school_years (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 0
        )
        """
    )
    changed = False
    existing_current = db.execute(
        "SELECT id FROM school_years WHERE label = ?",
        (current_label,),
    ).fetchone()
    if not existing_current:
        db.execute(
            "INSERT OR IGNORE INTO school_years (label, is_active) VALUES (?, 0)",
            (current_label,),
        )
        changed = True
    active = db.execute(
        "SELECT id, label FROM school_years WHERE COALESCE(is_active, 0) = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not active:
        row = db.execute(
            "SELECT id, label FROM school_years ORDER BY label DESC, id DESC LIMIT 1"
        ).fetchone()
        if row:
            db.execute("UPDATE school_years SET is_active = 0")
            db.execute("UPDATE school_years SET is_active = 1 WHERE id = ?", (row["id"],))
            changed = True
            if changed:
                db.commit()
            return row["label"]
        return current_label
    if changed:
        db.commit()
    return active["label"]

def list_school_years(db):
    ensure_school_years(db)
    rows = db.execute(
        "SELECT id, label, is_active FROM school_years ORDER BY label DESC, id DESC"
    ).fetchall()
    if has_request_context() and session.get("user_id") and not session.get("is_admin"):
        own_years = _user_school_years(db, session["user_id"])
        return [row for row in rows if row["label"] in own_years] or [
            row for row in rows if row["is_active"]
        ]
    return rows


def _user_school_years(db, user_id):
    return [
        row["label"]
        for row in db.execute(
            """
            SELECT label FROM school_years
            WHERE label IN (
                SELECT school_year FROM eleves WHERE user_id = ?
                UNION
                SELECT school_year FROM teacher_assignments WHERE user_id = ?
            )
            ORDER BY label DESC, id DESC
            """,
            (user_id, user_id),
        ).fetchall()
    ]

def get_active_school_year(db):
    return ensure_school_years(db)

def resolve_school_year(db, requested=None, *, is_admin=False, user_id=None):
    active = get_active_school_year(db)
    req = (requested or "").strip()
    if is_admin:
        row = db.execute(
            "SELECT label FROM school_years WHERE label = ?", (req,)
        ).fetchone()
        return row["label"] if row else active
    if user_id is None and has_request_context():
        user_id = session.get("user_id")
    if user_id is None:
        return active
    own_years = _user_school_years(db, user_id)
    if req in own_years:
        return req
    if active in own_years:
        return active
    return own_years[0] if own_years else active

def get_user_assignment_scope(db, user_id: int, school_year_label: str):
    rows = db.execute(
        """
        SELECT subject_id, class_name
        FROM teacher_assignments
        WHERE user_id = ? AND school_year = ?
        """,
        (user_id, school_year_label),
    ).fetchall()

    subject_ids = set()
    classes = set()
    for r in rows:
        try:
            subject_ids.add(int(r["subject_id"]))
        except Exception:
            pass
        cls = (r["class_name"] or "").strip()
        if cls:
            classes.add(cls)

    return {
        "restricted": len(rows) > 0,
        "subject_ids": subject_ids,
        "classes": classes,
    }

def get_subjects(db, user_id):
    default_subject = ""
    lock_subject = 0
    try:
        user = db.execute(
            "SELECT default_subject, lock_subject FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        default_subject = (user["default_subject"] or "").strip() if user else ""
        lock_subject = int(user["lock_subject"] or 0) if user else 0
    except Exception:
        pass

    rows = db.execute(
        "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name",
        (user_id,),
    ).fetchall()

    if lock_subject and not default_subject:
        if rows:
            default_subject = (rows[0]["name"] or "").strip()
        else:
            default_subject = "Sciences"
        try:
            db.execute(
                "UPDATE users SET default_subject = ? WHERE id = ?",
                (default_subject, user_id),
            )
            db.commit()
        except Exception:
            pass

    if not rows:
        db.execute(
            "INSERT INTO subjects (user_id, name) VALUES (?, ?)",
            (user_id, default_subject or "Sciences"),
        )
        db.commit()
        rows = db.execute(
            "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name",
            (user_id,),
        ).fetchall()

    if lock_subject and default_subject:
        match = None
        for r in rows:
            if (r["name"] or "").strip().lower() == default_subject.lower():
                match = r
                break
        if not match:
            db.execute(
                "INSERT OR IGNORE INTO subjects (user_id, name) VALUES (?, ?)",
                (user_id, default_subject),
            )
            db.commit()
            rows = db.execute(
                "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name",
                (user_id,),
            ).fetchall()
            for r in rows:
                if (r["name"] or "").strip().lower() == default_subject.lower():
                    match = r
                    break
        if match:
            rows = [match]
    return rows

def select_subject_id(subjects, value):
    subject_map = {int(s["id"]): s for s in subjects}
    try:
        sid = int(value)
    except Exception:
        sid = None
    if sid not in subject_map:
        sid = int(subjects[0]["id"])
    return sid
