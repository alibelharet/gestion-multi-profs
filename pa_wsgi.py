import os
import sys

from dotenv import load_dotenv


def _detect_project_home() -> str:
    explicit = (os.environ.get("PROJECT_HOME") or "").strip()
    candidates = []
    if explicit:
        candidates.append(explicit)

    user = (os.environ.get("USER") or "").strip()
    if user:
        candidates.extend(
            [
                f"/home/{user}/gestion-multi-profs",
                f"/home/{user}/Gestion_Multi_Profs",
            ]
        )

    candidates.extend(
        [
            os.path.expanduser("~/gestion-multi-profs"),
            os.path.expanduser("~/Gestion_Multi_Profs"),
        ]
    )

    for path in candidates:
        if path and os.path.isdir(path):
            return path

    raise RuntimeError(
        "Projet introuvable. Definissez PROJECT_HOME dans le fichier WSGI PythonAnywhere."
    )


project_home = _detect_project_home()
if project_home not in sys.path:
    sys.path.insert(0, project_home)

env_path = os.path.join(project_home, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

from edumaster import create_app

application = create_app()
