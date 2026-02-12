# Guide de Déploiement sur PythonAnywhere

Suivez ces étapes pour mettre votre application en ligne.

## 1. Préparation des Fichiers
Assurez-vous d'avoir les fichiers suivants prêts à être uploadés :
- Tout le dossier du projet (`edumaster`, `core`, `templates`, `static`, etc.)
- `requirements.txt`
- `pa_wsgi.py`
- `ecole_multi.db` (si vous voulez conserver vos données actuelles)

## 2. Transfert des Fichiers

### Option A : Via Git (Recommandé)
Si vous utilisez Git (comme sur votre capture d'écran) :
1. Poussez vos changements locaux : `git push`
2. Sur PythonAnywhere (Console Bash) :
   ```bash
   git clone https://github.com/votre-user/votre-repo.git gestion-multi-profs
   # OU si déjà cloné :
   cd ~/gestion-multi-profs
   git pull
   ```
   *Attention au nom du dossier ! (voir étape 4)*

### Option B : Upload Manuel
1. Créez un dossier nommé `Gestion_Multi_Profs` dans l'onglet **Files**.
2. Uploadez tous vos fichiers dans ce dossier via l'interface web.

## 3. Configuration de l'Environnement Virtuel
1. Ouvrez une console **Bash** (Dashboard > Consoles > Bash).
2. Allez dans le dossier du projet (adaptez le nom si besoin, ex: `gestion-multi-profs`) :
   ```bash
   cd ~/gestion-multi-profs
   ```
3. Créez l'environnement virtuel et installez les dépendances :
   ```bash
   mkvirtualenv --python=/usr/bin/python3.10 monenv
   pip install -r requirements.txt
   ```

## 4. Configuration Web
1. Allez dans l'onglet **Web**.
2. Cliquez sur **Add a new web app**.
3. Cliquez sur **Next**.
4. **IMPORTANT** : Choisissez **Manual configuration** (ne choisissez PAS Flask).
5. Choisissez **Python 3.10**.
6. Cliquez sur **Next** pour finir.

## 5. Réglages WSGI et Virtualenv
Toujours dans l'onglet **Web** :

1. **Virtualenv** :
   - Entrez le chemin de votre environnement virtuel (ex: `/home/votrenom/.virtualenvs/monenv`).
   - Validez (coche verte).

2. **Code** :
   - Cliquez sur le lien du fichier **WSGI configuration file** (ex: `/var/www/votrenom_pythonanywhere_com_wsgi.py`).
   - Effacez tout le contenu.
   - Copiez-collez le contenu de votre fichier `pa_wsgi.py`.
   - **Important** : Vérifiez la ligne `project_home = ...`.
     Si vous avez cloné dans `gestion-multi-profs` (minuscules, tirets), mettez :
     `project_home = '/home/votrenom/gestion-multi-profs'`
   - Cliquez sur **Save**.

## 6. Fichiers Statiques
Dans la section **Static files** (onglet Web) :

1. Cliquez sur **Enter URL** et mettez `/static/`.
2. Cliquez sur **Enter path** et mettez `/home/votrenom/gestion-multi-profs/static`.
   *(Adaptez le chemin selon le nom réel de votre dossier !)*

## 7. Variables d'Environnement (.env)
1. Dans l'onglet **Files**, assurez-vous d'avoir un fichier `.env` à la racine (`/home/votrenom/gestion-multi-profs/.env`).
2. Il doit contenir au minimum :
   ```
   SECRET_KEY=une_cle_tres_secrete_et_aleatoire
   DATABASE_PATH=/home/votrenom/gestion-multi-profs/ecole_multi.db
   ```
   *(Remplacez `votrenom` !)*

## 8. Lancement
1. Retournez dans l'onglet **Web**.
2. Cliquez sur le gros bouton vert **Reload votrenom.pythonanywhere.com**.
3. Cliquez sur le lien en haut pour voir votre site !

## Dépannage
Si vous avez une erreur ("Something went wrong") :
- Regardez le fichier **Error log** (lien dans l'onglet Web).
- Vérifiez que le chemin dans `pa_wsgi.py` est correct (`project_home`).
- Vérifiez que vous avez bien installé les dépendances (`pip install`).
