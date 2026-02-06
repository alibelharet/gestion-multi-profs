import os

from flask import Flask

from core.config import BASE_DIR, MAX_CONTENT_LENGTH, UPLOAD_FOLDER
from core.db import bootstrap_admin, close_db, init_db
from core.i18n import get_lang, get_text_dir, tr
from core.security import init_security


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )

    # --- CONFIGURATION ---
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = True

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    if not app.config["SECRET_KEY"]:
        # Keeps dev usable, but production should always set SECRET_KEY
        app.config["SECRET_KEY"] = os.urandom(32)
        print("WARNING: SECRET_KEY not set; using a random key for this run.")

    # --- APP INIT ---
    init_security(app)
    app.teardown_appcontext(close_db)

    with app.app_context():
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        init_db()
        bootstrap_admin()

    @app.context_processor
    def inject_i18n():
        lang = get_lang()
        return {
            "tr": tr,
            "current_lang": lang,
            "text_dir": get_text_dir(lang),
        }

    # --- ROUTES ---
    from .routes.admin import bp as admin_bp
    from .routes.auth import bp as auth_bp
    from .routes.docs import bp as docs_bp
    from .routes.licence import bp as licence_bp
    from .routes.main import bp as main_bp

    app.register_blueprint(licence_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(admin_bp)

    return app
