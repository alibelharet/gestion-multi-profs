import time
import uuid

from werkzeug.security import generate_password_hash

from .config import RESET_TOKEN_TTL_SECONDS
from .db import get_db


def create_reset_token(user_id: int) -> str:
    db = get_db()
    token = uuid.uuid4().hex
    now = int(time.time())
    expires_at = now + RESET_TOKEN_TTL_SECONDS
    db.execute(
        "INSERT INTO password_reset_tokens (token, user_id, expires_at, used, created_at) VALUES (?, ?, ?, 0, ?)",
        (token, user_id, expires_at, now),
    )
    db.commit()
    return token


def consume_reset_token(token: str) -> int | None:
    """
    Mark token as used and return user_id, or None if invalid/expired/used.
    """
    db = get_db()
    now = int(time.time())
    row = db.execute(
        "SELECT token, user_id, expires_at, used FROM password_reset_tokens WHERE token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    if int(row["used"] or 0) != 0:
        return None
    if int(row["expires_at"] or 0) < now:
        return None

    db.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,))
    db.commit()
    return int(row["user_id"])


def set_user_password(user_id: int, new_password: str) -> None:
    db = get_db()
    db.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    db.commit()

