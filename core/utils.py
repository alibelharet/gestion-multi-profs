import os
from .config import ALLOWED_UPLOAD_EXTENSIONS
from .db import get_db


def clean_note(val):
    if not val:
        return 0.0
    try:
        val_str = str(val).replace(',', '.').strip()
        if val_str == "" or val_str.lower() == "nan":
            return 0.0
        nombre = float(val_str)
        if nombre < 0:
            return 0.0
        if nombre > 20:
            return 20.0
        return nombre
    except ValueError:
        return 0.0


def is_allowed_upload(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in ALLOWED_UPLOAD_EXTENSIONS


def init_default_rules(user_id: int) -> None:
    db = get_db()
    exists = db.execute('SELECT 1 FROM appreciations WHERE user_id = ? LIMIT 1', (user_id,)).fetchone()
    if exists:
        return
    defaults = [
        (0, 4.99, "ضاعف المجهود"),
        (5, 9.99, "لديك قدرات يمكنك العمل أكثر"),
        (10, 11.99, "نتائج متوسطة"),
        (12, 13.99, "نتائج حسنة"),
        (14, 15.99, "نتائج جيدة"),
        (16, 17.99, "جيد جدا"),
        (18, 20, "ممتاز")
    ]
    for min_v, max_v, msg in defaults:
        db.execute('INSERT INTO appreciations (user_id, min_val, max_val, message) VALUES (?, ?, ?, ?)', (user_id, min_v, max_v, msg))
    db.commit()


def get_appreciation_dynamique(moy: float, user_id: int) -> str:
    db = get_db()
    rules = db.execute(
        'SELECT * FROM appreciations WHERE user_id = ? ORDER BY min_val',
        (user_id,),
    ).fetchall()
    if not rules:
        init_default_rules(user_id)
        rules = db.execute(
            'SELECT * FROM appreciations WHERE user_id = ? ORDER BY min_val',
            (user_id,),
        ).fetchall()
    for rule in rules:
        if rule['min_val'] <= moy <= rule['max_val']:
            return rule['message']
    return ""
