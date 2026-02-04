from pathlib import Path
import sys
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core.backup import create_backup_zip

BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
zip_path = BACKUP_DIR / f"backup_{stamp}.zip"

buf = create_backup_zip()
with open(zip_path, "wb") as f:
    f.write(buf.getbuffer())

backups = sorted(BACKUP_DIR.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
for old in backups[10:]:
    old.unlink()

print(f"Backup created: {zip_path}")
