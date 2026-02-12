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
