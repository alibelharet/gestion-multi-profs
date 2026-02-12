@echo off
if exist .venv\Scripts\activate (
    call .venv\Scripts\activate
    python generateur_cle.py
) else (
    echo Environnement virtuel non trouve. Utilisation du python systeme.
    python generateur_cle.py
)
