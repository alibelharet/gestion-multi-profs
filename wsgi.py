"""
PythonAnywhere WSGI configuration file for alibelharet.

INSTRUCTIONS:
1. Go to Web tab on PythonAnywhere
2. Click on the WSGI configuration file link
3. REPLACE ALL its content with the code below (from the line "import sys" onwards)
"""
import sys
import os
from dotenv import load_dotenv

project_home = '/home/alibelharet/gestion-multi-profs'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Load environment variables BEFORE importing the app
load_dotenv(os.path.join(project_home, '.env'))

from app import app as application
