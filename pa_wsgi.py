import sys
import os
from dotenv import load_dotenv

# Ajout du dossier du projet au path
# Remplacer 'votrenom' par votre nom d'utilisateur PythonAnywhere
# et 'Gestion_Multi_Profs' par le nom de votre dossier s'il est différent
project_home = '/home/votrenom/Gestion_Multi_Profs'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Charger les variables d'environnement
load_dotenv(os.path.join(project_home, '.env'))

# Configuration Flask
from edumaster import create_app
application = create_app()
