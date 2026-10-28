"""Preview or safely apply a teacher roster, locally or on PythonAnywhere.

Student data belongs in an ignored JSON file, never in this source file.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import tempfile
import unicodedata


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def load_roster(filename):
    data = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
    teacher = {key: normalized(value) for key, value in data["teacher"].items()}
    for field in ("username", "display_name", "school_name", "subject"):
        if not normalized(teacher.get(field)):
            raise ValueError(f"Missing teacher field: {field}")
    year = data["school_year"]
    match = re.fullmatch(r"(\d{4})/(\d{4})", year)
    if not match or int(match[2]) != int(match[1]) + 1:
        raise ValueError("Invalid school year")
    students, seen = [], set()
    for row in data["students"]:
        name = normalized(row["name"])
        class_name = normalized(row["class"]).upper()
        key = (class_name, name.casefold())
        if not name or not class_name or key in seen:
            raise ValueError("Empty or duplicate student in roster")
        seen.add(key)
        students.append({"name": name, "class": class_name})
    if not students:
        raise ValueError("Empty roster")
    return data, teacher, students


def validate_account(db, teacher):
    user = db.execute("SELECT * FROM users WHERE username = ?", (teacher["username"],)).fetchone()
    if user:
        expected = (normalized(teacher["display_name"]), normalized(teacher["school_name"]), normalized(teacher["subject"]))
        actual = tuple(normalized(user[k]) for k in ("nom_affichage", "school_name", "default_subject"))
        if actual != expected or user["is_admin"] or user["role"] != "prof":
            raise ValueError("Username belongs to an account with different teacher settings")
    return user


def preview(db, data, teacher, students):
    user = validate_account(db, teacher)
    existing = set()
    if user:
        existing = {(normalized(r["niveau"]).upper(), normalized(r["nom_complet"]).casefold()) for r in db.execute(
            "SELECT niveau,nom_complet FROM eleves WHERE user_id=? AND school_year=?", (user["id"], data["school_year"]))}
    matched = sum((r["class"], r["name"].casefold()) in existing for r in students)
    return {"username": teacher["username"], "account": "existing" if user else "new", "school_year": data["school_year"],
            "classes": dict(sorted(Counter(r["class"] for r in students).items())),
            "students": len(students), "to_add": len(students) - matched, "already_present": matched}


def apply_roster(database, roster_file, credentials_file=None):
    from werkzeug.security import generate_password_hash
    data, teacher, students = load_roster(roster_file)
    database = Path(database).resolve(strict=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.parent / "backups" / f"before_roster_{stamp}.sqlite3"
    backup.parent.mkdir(parents=True, exist_ok=True)
    credentials = Path(credentials_file) if credentials_file else backup.parent / f"access_{teacher['username']}_{stamp}.local.json"
    credentials.parent.mkdir(parents=True, exist_ok=True)
    created_credentials = False
    db = sqlite3.connect(str(database), timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        result = preview(db, data, teacher, students)
        with closing(sqlite3.connect(str(backup))) as target:
            db.backup(target)
        db.execute("BEGIN IMMEDIATE")
        user = validate_account(db, teacher)
        if user is None:
            password = secrets.token_urlsafe(18)
            cursor = db.execute("""INSERT INTO users
                (username,password,nom_affichage,is_admin,role,school_name,default_subject,lock_subject)
                VALUES (?,?,?,0,'prof',?,?,1)""",
                (teacher["username"], generate_password_hash(password), teacher["display_name"], teacher["school_name"], teacher["subject"]))
            user_id = cursor.lastrowid
            token = secrets.token_hex(32)
            now = int(time.time())
            db.execute("INSERT INTO password_reset_tokens (token,user_id,expires_at,used,created_at) VALUES (?,?,?,0,?)", (token,user_id,now+7200,now))
            access = {"username": teacher["username"], "temporary_password": password,
                      "reset_path": f"/reset/{token}", "reset_expires_at_utc": datetime.fromtimestamp(now+7200,timezone.utc).isoformat()}
            fd = os.open(str(credentials), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created_credentials = True
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(access,handle,ensure_ascii=False,indent=2)
        else:
            user_id = user["id"]
        db.execute("INSERT OR IGNORE INTO school_years (label,is_active) VALUES (?,0)", (data["school_year"],))
        db.execute("INSERT OR IGNORE INTO subjects (user_id,name) VALUES (?,?)", (user_id,teacher["subject"]))
        subject_id = db.execute("SELECT id FROM subjects WHERE user_id=? AND name=?", (user_id,teacher["subject"])).fetchone()[0]
        existing = {(normalized(r["niveau"]).upper(), normalized(r["nom_complet"]).casefold()) for r in db.execute(
            "SELECT niveau,nom_complet FROM eleves WHERE user_id=? AND school_year=?", (user_id,data["school_year"]))}
        added = 0
        for row in students:
            key = (row["class"],row["name"].casefold())
            if key not in existing:
                db.execute("INSERT INTO eleves (user_id,school_year,nom_complet,niveau) VALUES (?,?,?,?)", (user_id,data["school_year"],row["name"],row["class"]))
                existing.add(key)
                added += 1
        for class_name in sorted({r["class"] for r in students}):
            db.execute("INSERT OR IGNORE INTO teacher_assignments (user_id,school_year,subject_id,class_name) VALUES (?,?,?,?)", (user_id,data["school_year"],subject_id,class_name))
        if not db.execute("SELECT 1 FROM appreciations WHERE user_id=?", (user_id,)).fetchone():
            rules = [(0,4.99,"ضاعف المجهود"),(5,9.99,"لديك قدرات يمكنك العمل أكثر"),(10,11.99,"نتائج متوسطة"),(12,13.99,"نتائج حسنة"),(14,15.99,"نتائج جيدة"),(16,17.99,"جيد جدا"),(18,20,"ممتاز")]
            db.executemany("INSERT INTO appreciations (user_id,min_val,max_val,message) VALUES (?,?,?,?)", [(user_id,*r) for r in rules])
        db.execute("INSERT INTO change_log (user_id,action,details,created_at) VALUES (?,?,?,?)", (user_id,"import_roster",json.dumps({"school_year":data["school_year"],"added":added,"source_sha256":data.get("source_sha256","")}),int(time.time())))
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Foreign key check failed")
        db.commit()
        result.update({"added":added,"backup":str(backup),"user_id":user_id})
        if created_credentials:
            result["credentials_file"] = str(credentials)
        return result
    except Exception:
        db.rollback()
        if created_credentials:
            credentials.unlink(missing_ok=True)
        raise
    finally:
        db.close()


def load_excel_roster(filename, teacher, school_year):
    """Read the class workbook: names in Q, student numbers in R, from row 8."""
    import openpyxl
    source = Path(filename).resolve(strict=True)
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    students = []
    try:
        for sheet in workbook:
            class_name = normalized(sheet.title).upper()
            if not re.fullmatch(r"[1-4]M[0-9]+", class_name):
                continue
            numbers = []
            for row in sheet.iter_rows(min_row=8, values_only=True):
                if len(row) < 18:
                    continue
                number, name = row[17], row[16]
                if isinstance(number, bool) or not isinstance(number, (int, float)):
                    continue
                if int(number) != number or number < 1 or not normalized(name):
                    raise ValueError(f"Invalid student row in {class_name}")
                numbers.append(int(number))
                students.append({"class": class_name, "name": normalized(name)})
            if not numbers or numbers != list(range(1, len(numbers) + 1)):
                raise ValueError(f"Invalid or missing student numbering in {class_name}")
    finally:
        workbook.close()
    if not students:
        raise ValueError("No class sheets with names in Q and numbers in R were found")
    return {"version": 1, "teacher": teacher, "school_year": school_year,
            "source_file": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "students": students}


def main():
    from dotenv import load_dotenv
    project = Path(__file__).resolve().parent.parent
    load_dotenv(project / ".env")
    configured_database = Path(os.environ.get("DATABASE_PATH", project / "ecole_multi.db"))
    if not configured_database.is_absolute():
        configured_database = project / configured_database
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=str(configured_database))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--roster", help="Private JSON roster")
    source.add_argument("--excel", help="Class workbook with names in Q and student numbers in R")
    parser.add_argument("--username")
    parser.add_argument("--display-name")
    parser.add_argument("--school")
    parser.add_argument("--subject")
    parser.add_argument("--school-year")
    parser.add_argument("--apply", action="store_true", help="Create a backup then apply; otherwise preview only")
    parser.add_argument("--credentials-file")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="edumaster_roster_") as directory:
        roster_file = args.roster
        if args.excel:
            teacher = {"username": args.username, "display_name": args.display_name,
                       "school_name": args.school, "subject": args.subject}
            if not all(normalized(value) for value in teacher.values()) or not args.school_year:
                parser.error("--excel requires --username, --display-name, --school, --subject and --school-year")
            data = load_excel_roster(args.excel, teacher, args.school_year)
            roster_file = Path(directory) / "roster.json"
            roster_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if args.apply:
            result = apply_roster(args.database, roster_file, args.credentials_file)
        else:
            data, teacher, students = load_roster(roster_file)
            with closing(sqlite3.connect(Path(args.database).resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                result = preview(db, data, teacher, students)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
