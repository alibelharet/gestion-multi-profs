from datetime import datetime

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
    db.execute(
        "INSERT OR IGNORE INTO school_years (label, is_active) VALUES (?, 0)",
        (current_label,),
    )
    if not existing_current:
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
    return db.execute(
        "SELECT id, label, is_active FROM school_years ORDER BY label DESC, id DESC"
    ).fetchall()

def get_active_school_year(db):
    return ensure_school_years(db)

def resolve_school_year(db, requested=None, *, is_admin=False):
    active = get_active_school_year(db)
    req = (requested or "").strip()
    if not req:
        return active
    row = db.execute(
        "SELECT label, is_active FROM school_years WHERE label = ?",
        (req,),
    ).fetchone()
    if not row:
        return active
    if is_admin:
        return row["label"]
    # Non-admin users are pinned to the active year.
    return active

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
