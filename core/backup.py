import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

from .config import DATABASE, UPLOAD_FOLDER


@dataclass(frozen=True)
class RestoreResult:
    db_backup_path: str | None
    uploads_backup_path: str | None
    restored_files: int


def _create_sqlite_snapshot(source_db: str, target_db: str) -> None:
    """
    Create a consistent SQLite snapshot even when WAL is enabled.
    """
    src = None
    dst = None
    try:
        src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    except sqlite3.Error:
        # Fallback for environments that do not support URI mode.
        src = sqlite3.connect(source_db)

    try:
        dst = sqlite3.connect(target_db)
        src.backup(dst)
    finally:
        try:
            if dst is not None:
                dst.close()
        finally:
            if src is not None:
                src.close()


def create_backup_zip() -> BytesIO:
    """
    Create an in-memory ZIP backup with:
      - ecole_multi.db (consistent SQLite snapshot)
      - uploads/ (files only)
      - backup_info.json (metadata)
    """
    if not os.path.exists(DATABASE):
        raise FileNotFoundError("Base de donnees introuvable.")

    tmpdir = tempfile.mkdtemp(prefix="edumaster_backup_")
    snapshot_db = os.path.join(tmpdir, "ecole_multi.db")

    try:
        _create_sqlite_snapshot(DATABASE, snapshot_db)

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot_db, arcname="ecole_multi.db")

            if os.path.isdir(UPLOAD_FOLDER):
                for root, _, files in os.walk(UPLOAD_FOLDER):
                    for name in files:
                        src = os.path.join(root, name)
                        rel = os.path.relpath(src, UPLOAD_FOLDER)
                        zf.write(src, arcname=os.path.join("uploads", rel))

            info = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "includes": ["ecole_multi.db", "uploads/"],
                "sqlite_snapshot": True,
            }
            zf.writestr("backup_info.json", json.dumps(info, ensure_ascii=False, indent=2))

        buf.seek(0)
        return buf
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def restore_from_backup_zip(zip_path: str) -> RestoreResult:
    """
    Restore DATABASE and UPLOAD_FOLDER from a ZIP created by create_backup_zip().
    This function is intentionally conservative:
      - only accepts `ecole_multi.db` and paths under `uploads/`
      - prevents Zip Slip path traversal
      - keeps backups of previous db/uploads with a timestamp suffix
    """
    if not os.path.exists(zip_path):
        raise FileNotFoundError("Fichier zip introuvable.")

    tmpdir = tempfile.mkdtemp(prefix="edumaster_restore_")
    extracted_db = os.path.join(tmpdir, "ecole_multi.db")
    extracted_uploads = os.path.join(tmpdir, "uploads")
    restored_files = 0

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                name = member.filename.replace("\\", "/")
                if name.endswith("/"):
                    continue

                if name == "ecole_multi.db":
                    dest = extracted_db
                elif name.startswith("uploads/"):
                    dest = os.path.join(extracted_uploads, name[len("uploads/"):])
                elif name == "backup_info.json":
                    # metadata only
                    continue
                else:
                    # unknown entry -> ignore (backward/forward compatibility)
                    continue

                dest_dir = os.path.dirname(dest)
                os.makedirs(dest_dir, exist_ok=True)

                # Zip Slip protection
                dest_real = os.path.realpath(dest)
                tmp_real = os.path.realpath(tmpdir)
                if not dest_real.startswith(tmp_real + os.sep):
                    raise ValueError("Archive zip invalide (chemin dangereux).")

                with zf.open(member, "r") as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                restored_files += 1

        if not os.path.exists(extracted_db):
            raise ValueError("Archive zip invalide: ecole_multi.db manquant.")

        # Prepare backups
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_backup_path = None
        uploads_backup_path = None

        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        os.makedirs(os.path.dirname(UPLOAD_FOLDER), exist_ok=True)

        if os.path.exists(DATABASE):
            db_backup_path = f"{DATABASE}.bak_{stamp}"
            shutil.move(DATABASE, db_backup_path)

        if os.path.isdir(UPLOAD_FOLDER):
            uploads_backup_path = f"{UPLOAD_FOLDER}.bak_{stamp}"
            shutil.move(UPLOAD_FOLDER, uploads_backup_path)

        # Restore DB
        shutil.move(extracted_db, DATABASE)

        # Restore uploads (if present in zip)
        if os.path.isdir(extracted_uploads):
            shutil.move(extracted_uploads, UPLOAD_FOLDER)
        else:
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        return RestoreResult(
            db_backup_path=db_backup_path,
            uploads_backup_path=uploads_backup_path,
            restored_files=restored_files,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
