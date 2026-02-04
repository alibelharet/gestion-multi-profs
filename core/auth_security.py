import time

from flask import Request

from .config import LOGIN_LOCK_SECONDS, LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS


def get_client_ip(request: Request) -> str:
    """
    Best-effort client IP extraction.
    NOTE: X-Forwarded-For can be spoofed unless your proxy overwrites it.
    On platforms like PythonAnywhere, it’s generally set by the platform proxy.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip() or (request.remote_addr or "")
    return request.remote_addr or ""


def cleanup_old_login_attempts(db, keep_seconds: int = 7 * 24 * 3600) -> None:
    cutoff = int(time.time()) - keep_seconds
    db.execute("DELETE FROM login_attempts WHERE ts < ?", (cutoff,))
    db.commit()


def record_login_attempt(db, username: str, ip: str, success: bool) -> None:
    db.execute(
        "INSERT INTO login_attempts (ts, ip, username, success) VALUES (?, ?, ?, ?)",
        (int(time.time()), ip, (username or "").lower(), 1 if success else 0),
    )
    db.commit()


def _fail_stats(db, username: str, ip: str) -> tuple[int, int]:
    """
    Returns (fail_count_in_window, last_fail_ts_in_window).
    """
    now = int(time.time())
    window_start = now - LOGIN_WINDOW_SECONDS
    row = db.execute(
        """
        SELECT COUNT(*) AS c, MAX(ts) AS last_ts
        FROM login_attempts
        WHERE username = ? AND ip = ? AND success = 0 AND ts >= ?
        """,
        ((username or "").lower(), ip, window_start),
    ).fetchone()
    return int(row["c"] or 0), int(row["last_ts"] or 0)


def is_login_locked(db, username: str, ip: str) -> tuple[bool, int]:
    """
    Returns (locked, seconds_remaining).
    """
    fails, last_fail_ts = _fail_stats(db, username, ip)
    if fails < LOGIN_MAX_ATTEMPTS or not last_fail_ts:
        return False, 0
    now = int(time.time())
    elapsed = now - last_fail_ts
    remaining = LOGIN_LOCK_SECONDS - elapsed
    if remaining > 0:
        return True, remaining
    return False, 0


def lock_message(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    if m <= 0:
        return f"Trop de tentatives. Réessayez dans {s}s."
    return f"Trop de tentatives. Réessayez dans {m} min {s}s."

