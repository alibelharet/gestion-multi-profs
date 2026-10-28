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
   SECRET_LICENCE=un_secret_de_signature_long_et_aleatoire
   DATABASE_PATH=/home/votrenom/gestion-multi-profs/ecole_multi.db
   ```
   *(Remplacez `votrenom` !)* Ne publiez jamais ces valeurs dans Git. Pour creer le premier compte, configurez aussi temporairement `ADMIN_USER` et `ADMIN_PASS`; les comptes suivants se creent depuis l'espace administrateur.

## 8. Lancement
1. Retournez dans l'onglet **Web**.
2. Cliquez sur le gros bouton vert **Reload votrenom.pythonanywhere.com**.
3. Cliquez sur le lien en haut pour voir votre site !

## Dépannage
Si vous avez une erreur ("Something went wrong") :
- Regardez le fichier **Error log** (lien dans l'onglet Web).
- Vérifiez que le chemin dans `pa_wsgi.py` est correct (`project_home`).
- Vérifiez que vous avez bien installé les dépendances (`pip install`).

## Mise à jour GitHub et import d'un enseignant

Le code est mis à jour depuis une console Bash PythonAnywhere :

```bash
cd /home/alibelharet/gestion-multi-profs
git pull --ff-only origin main
```

Activez le virtualenv indiqué dans l'onglet Web (par exemple `workon edumaster-venv`).
Les comptes et les élèves sont conservés dans la base SQLite du serveur : un `git pull`
ne transfère pas la base du PC. Pour ajouter une liste, déposez le fichier Excel dans
votre dossier personnel avec PythonAnywhere > Files, puis lancez un aperçu :

```bash
python scripts/import_class_roster.py \
  --excel ~/Notes_controle_continu_classes.xlsx \
  --username profmath --display-name "Nom Prénom" \
  --school "Mon école" --subject "Mathématiques" --school-year 2026/2027
```

Ce format de classeur utilise un onglet par classe (`1M1`, `2M2`, etc.), les noms en
colonne Q et les numéros en colonne R, à partir de la ligne 8. Les numéros doivent
être continus. Seuls les noms et les classes sont importés ; aucune note n'est créée.
L'année scolaire est obligatoire pour ce format. Le chemin de la base est lu depuis
le `.env` du serveur ; `--database` permet de le préciser si nécessaire.

Si l'aperçu correspond à la liste attendue, relancez la même commande avec `--apply`.
Le script sauvegarde la base avant l'import, crée un compte professeur et ses
classes, puis affiche le chemin d'un fichier privé contenant son mot de passe
initial. Ce fichier reste dans `backups/`, hors du dépôt. Un compte existant n'est
réutilisé que si ses paramètres correspondent et son mot de passe est conservé.
Une seconde exécution ne duplique pas les élèves.

Chaque professeur accède à ses propres années scolaires. L'année active des autres
comptes reste en place. Après la mise à jour, cliquez **Web > Reload**, puis vérifiez
`/health` et connectez-vous avec le compte de l'enseignant.

Les fichiers Excel, les listes JSON, les bases et les identifiants restent dans
votre compte privé ; ne les ajoutez pas au dépôt GitHub public.