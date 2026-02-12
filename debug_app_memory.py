import sys
import os

# Set up paths
sys.path.append(r'h:\Autres ordinateurs\Mon ordinateur portable\Bureau\Gestion_Multi_Profs')

# Use in-memory DB to avoid locking issues
os.environ["DATABASE_PATH"] = ":memory:"
os.environ["SECRET_KEY"] = "dev-key"

from flask import Flask
from edumaster import create_app

try:
    print("Creating app with in-memory DB...")
    app = create_app()
    app.testing = True
    print("App created successfully.")

    print("Testing request to / ...")
    with app.test_client() as client:
        # Simulate login by setting session - we need to create the user first in the new DB
        with app.app_context():
            from core.db import get_db
            db = get_db()
            # Create a mock user
            db.execute("INSERT INTO users (username, password, nom_affichage, is_admin, role) VALUES (?, ?, ?, ?, ?)",
                       ("admin", "pass", "Admin", 1, "admin"))
            db.commit()
            user = db.execute("SELECT * FROM users WHERE username='admin'").fetchone()
            print(f"Created user: {user['id']}")

        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["is_admin"] = 1
            sess["role"] = "admin"
            sess["nom_affichage"] = "Admin"
        
        try:
            response = client.get("/")
            print(f"Response status: {response.status_code}")
            if response.status_code == 200:
                print("Success! The app code is fine, but the real database is likely locked or corrupt.")
            else:
                print(f"Failed with status: {response.status_code}")
        except Exception as e:
            print("Captured exception during request:")
            import traceback
            traceback.print_exc()

except Exception as e:
    import traceback
    traceback.print_exc()
