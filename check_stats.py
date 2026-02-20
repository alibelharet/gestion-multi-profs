import requests
from bs4 import BeautifulSoup
import sys

# Since app is running locally on 5000, we need to first login
s = requests.Session()
login_url = "http://127.0.0.1:5000/auth/login"

print("Logging in...")
try:
    r = s.get(login_url)
    r.raise_for_status()
    # Assume admin / admin123 works
    login_data = {"username": "admin", "password": "password"} # Try typical passwords
    r = s.post(login_url, data=login_data)
except Exception as e:
    print(f"Error accessing login: {e}")
    sys.exit(1)
            
print("Assuming login successful or we can check responses.")
# Check the stats page
stats_url = "http://127.0.0.1:5000/stats"
try:
    r = s.get(stats_url)
    if r.status_code == 200:
        print("Stats page loaded successfully (code 200).")
        soup = BeautifulSoup(r.text, 'html.parser')
        if "Statistiques" in r.text and "Moyenne générale" in r.text:
            print("Successfully found Stats UI elements!")
        else:
            print("Did not find expected Stats UI elements.")
    else:
         print(f"Stats page failed with status {r.status_code}")
except Exception as e:
    print(f"Error checking stats: {e}")

# Try to download the PDF
pdf_url = "http://127.0.0.1:5000/export_stats_pdf"
try:
    r = s.get(pdf_url)
    if r.status_code == 200 and 'application/pdf' in r.headers.get('Content-Type', ''):
        print("PDF export successful!")
    else:
        print(f"PDF export failed or did not return PDF: Status {r.status_code}, type {r.headers.get('Content-Type')}")
except Exception as e:
    print(f"Error checking PDF: {e}")
    
