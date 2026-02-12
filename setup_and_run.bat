@echo off
echo ==========================================
echo   EduMaster Pro - Installation & Demarrage
echo ==========================================

REM Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python n'est pas detecte avec la commande 'python'.
    echo Essai avec 'py'...
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo ERREUR: Python n'est pas installe ou pas dans le PATH.
        echo Veuillez installer Python depuis https://www.python.org/downloads/
        pause
        exit /b
    )
    set PYTHON_CMD=py
) else (
    set PYTHON_CMD=python
)

echo Utilisation de: %PYTHON_CMD%

REM Check if venv exists
if not exist ".venv" (
    echo Creation de l'environnement virtuel...
    %PYTHON_CMD% -m venv .venv
)

REM Activate venv
echo Activation de l'environnement virtuel...
call .venv\Scripts\activate

REM Install dependencies
echo Installation des dependances...
pip install -r requirements.txt

REM Run App
echo.
echo Demarrage de l'application...
set FLASK_APP=app.py
set FLASK_ENV=development
set FLASK_DEBUG=1
set OAUTHLIB_INSECURE_TRANSPORT=1

python app.py
pause
