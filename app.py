import os
import sys
from dotenv import load_dotenv

# Load env vars from .env file (if present)
load_dotenv()

from edumaster import create_app

app = create_app()


if __name__ == "__main__":
    # Local dev over http: Secure cookies would prevent session from persisting.
    app.config["SESSION_COOKIE_SECURE"] = False
    
    # Use FLASK_DEBUG from env or default to True for local dev
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
