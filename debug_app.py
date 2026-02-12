import sys
import os

# Set up paths
sys.path.append(r'h:\Autres ordinateurs\Mon ordinateur portable\Bureau\Gestion_Multi_Profs')

from flask import Flask
from edumaster import create_app

try:
    print("Creating app...")
    app = create_app()
    app.testing = True # Enable testing mode to propagate exceptions
    print("App created successfully.")

    print("Testing database connection...")
    with app.app_context():
        from core.db import get_db
        db = get_db()
        db.execute("SELECT 1")
        print("Database connection successful.")

    print("Testing request to / ...")
    with app.test_client() as client:
        # Simulate login by setting session
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["is_admin"] = 1
            sess["role"] = "admin"
            sess["nom_affichage"] = "Test User"
            sess["school_name"] = "Test School"
        
        try:
            response = client.get("/")
            print(f"Response status: {response.status_code}")
        except Exception as e:
            print("Captured exception during request:")
            import traceback
            traceback.print_exc()

except Exception as e:
    import traceback
    traceback.print_exc()
