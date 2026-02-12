@echo off
echo Starting EduMaster Pro in Development Mode...

if exist .venv\Scripts\activate (
    call .venv\Scripts\activate
) else (
    echo Virtual environment not found in .venv. Attempting to run with system python...
)

set FLASK_APP=app.py
set FLASK_ENV=development
set FLASK_DEBUG=1
set OAUTHLIB_INSECURE_TRANSPORT=1

python app.py
pause
