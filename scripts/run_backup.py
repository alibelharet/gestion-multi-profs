from pathlib import Path
import sys
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core.backup import BACKUP_DIR, create_backup_zip, record_backup_status

BACKUP_DIR = Path(BACKUP_DIR)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
zip_path = BACKUP_DIR / f"backup_{stamp}.zip"

try:
    buf = create_backup_zip()
    with open(zip_path, "wb") as f:
        f.write(buf.getbuffer())

    backups = sorted(BACKUP_DIR.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[10:]:
        old.unlink()

    record_backup_status(True, str(zip_path))
    print(f"Backup created: {zip_path}")
except Exception as exc:
    record_backup_status(False, error=str(exc))
    raise
