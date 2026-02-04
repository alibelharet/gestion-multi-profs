import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = str(Path(__file__).resolve().parent.parent)

DATABASE = os.path.join(BASE_DIR, "ecole_multi.db")
LICENSE_FILE = os.path.join(BASE_DIR, "license.key")
CACHE_FILE = os.path.join(BASE_DIR, ".sys_check")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

SECRET_LICENCE = os.environ.get("SECRET_LICENCE", "ALGERIE_ECOLE_PRO_2026_SUPER_SECRET")

ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xlsx", ".xls", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"
}

MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 10 * 1024 * 1024))

# --- AUTH SECURITY ---
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", 5))
LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", 15 * 60))
LOGIN_LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_SECONDS", 10 * 60))

# One-time admin-generated password reset links
RESET_TOKEN_TTL_SECONDS = int(os.environ.get("RESET_TOKEN_TTL_SECONDS", 2 * 60 * 60))
