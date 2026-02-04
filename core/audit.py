import time

from .db import get_db


def log_change(action: str, user_id: int, details: str = "", eleve_id: int | None = None, subject_id: int | None = None) -> None:
    try:
        db = get_db()
        db.execute(
            "INSERT INTO change_log (user_id, action, eleve_id, subject_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, action, eleve_id, subject_id, details, int(time.time())),
        )
        db.commit()
    except Exception:
        # Best-effort logging: never break user flow.
        pass
