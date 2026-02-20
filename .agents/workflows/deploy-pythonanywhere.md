---
description: Déployer EduMaster Pro sur PythonAnywhere
---

# Déploiement sur PythonAnywhere

## Pré-requis
- Un compte PythonAnywhere (gratuit ou payant)
- Votre nom d'utilisateur PythonAnywhere (ex: `alibelharet`)

---

## Étape 1 — Uploader le projet

### Option A : Via Git (recommandé)
```bash
# Dans la console Bash de PythonAnywhere :
cd ~
git clone https://github.com/VOTRE_REPO/gestion-multi-profs.git
```

### Option B : Via ZIP
1. Zipper votre dossier `Gestion_Multi_Profs`
2. Aller sur **PythonAnywhere > Files**
3. Uploader le .zip dans `/home/<username>/`
4. Ouvrir une console Bash et dézipper :
```bash
cd ~
unzip Gestion_Multi_Profs.zip -d gestion-multi-profs
```

---

## Étape 2 — Créer le virtualenv

```bash
cd ~/gestion-multi-profs
mkvirtualenv --python=/usr/bin/python3.10 edumaster-venv
pip install -r requirements.txt
```

---

## Étape 3 — Configurer le .env

```bash
cp .env.example .env
nano .env
```

Modifier avec vos valeurs :
```
SECRET_KEY=VOTRE_CLE_SECRETE_LONGUE
DATABASE_PATH=/home/<username>/gestion-multi-profs/ecole_multi.db
STRICT_LICENSE_MACHINE_CHECK=0
```

> **IMPORTANT** : Mettre `STRICT_LICENSE_MACHINE_CHECK=0` car la machine PythonAnywhere est différente de votre PC local.

---

## Étape 4 — Configurer le Web App

1. Aller sur **PythonAnywhere > Web tab**
2. Cliquer **Add a new web app**
3. Choisir **Manual configuration** → **Python 3.10**
4. Dans la section **Virtualenv**, entrer :
   ```
   /home/<username>/.virtualenvs/edumaster-venv
   ```
5. Dans **Source code**, entrer :
   ```
   /home/<username>/gestion-multi-profs
   ```

---

## Étape 5 — Configurer le WSGI

1. Dans le **Web tab**, cliquer sur le lien du fichier **WSGI configuration file** (ex: `/var/www/<username>_pythonanywhere_com_wsgi.py`)
2. **Remplacer TOUT le contenu** par :

```python
import sys
import os
from dotenv import load_dotenv

project_home = '/home/<username>/gestion-multi-profs'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

load_dotenv(os.path.join(project_home, '.env'))

from app import app as application
```

> Remplacez `<username>` par votre nom d'utilisateur PythonAnywhere partout.

---

## Étape 6 — Copier la licence

Si vous avez un fichier `license.key` local, uploadez-le dans `/home/<username>/gestion-multi-profs/license.key`.

---

## Étape 7 — Recharger

1. Retourner sur le **Web tab**
2. Cliquer le bouton vert **Reload**
3. Visiter `https://<username>.pythonanywhere.com`

---

## Dépannage

| Problème | Solution |
|----------|----------|
| Erreur 500 | Vérifier les **Error log** dans le Web tab |
| "Aucune licence trouvée" | Uploader `license.key` ou mettre `STRICT_LICENSE_MACHINE_CHECK=0` |
| "Erreur Date Système" | Ajouter `STRICT_LICENSE_MACHINE_CHECK=0` dans `.env` |
| Module introuvable | Vérifier que le virtualenv est activé et `pip install -r requirements.txt` |
| DB locked | Vérifier le chemin `DATABASE_PATH` dans `.env` |

---

## Mise à jour du site

```bash
cd ~/gestion-multi-profs
git pull  # si vous utilisez Git
# OU ré-uploader les fichiers modifiés

# Puis dans le Web tab : cliquer Reload
```
