from __future__ import annotations

import os

from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from config import Config
from database import db
from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.computer_finder import computer_finder_bp
from routes.dashboard import dashboard_bp
from routes.mailbox import mailbox_bp
from routes.rfqs import rfqs_bp
from routes.settings import settings_bp
from routes.tender_emails import tender_emails_bp
from routes.tenders import tenders_bp
from services.automation_scheduler import start_automation_scheduler
from services.auth_service import load_application_user
from services.extraction_jobs import start_extraction_worker
from services.mailbox_jobs import start_mailbox_sync_worker
from services.markdown_tools import render_markdown_html
from services.settings_service import ensure_default_settings
from services.schema_migrations import apply_schema_migrations
from services.tender_monitor import start_tender_monitor_worker


login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
DEFAULT_APP_VERSION = "0.1.2"


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app_version = str(
        app.config.get("APP_VERSION")
        or os.environ.get("TENDER_DESIGNER_VERSION")
        or DEFAULT_APP_VERSION
    ).strip() or DEFAULT_APP_VERSION
    app.config["APP_VERSION"] = app_version
    if app.config.get("PRODUCTION_MODE"):
        missing = []
        if not os.environ.get("SECRET_KEY"):
            missing.append("SECRET_KEY")
        if not (app.config.get("ADMIN_PASSWORD") or app.config.get("ADMIN_PASSWORD_HASH")):
            missing.append("ADMIN_PASSWORD or ADMIN_PASSWORD_HASH")
        if missing:
            raise RuntimeError("Missing required production security settings: " + ", ".join(missing))
    migration_mode = os.environ.get("TENDER_DESIGNER_MIGRATION_MODE", "").lower() in {"1", "true", "yes"}
    app.config["DATA_DIR"].mkdir(parents=True, exist_ok=True)
    (app.config["DATA_DIR"] / "tenders").mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.user_loader(load_application_user)

    with app.app_context():
        import models  # noqa: F401

        if not migration_mode:
            db.create_all()
            apply_schema_migrations()
            ensure_default_settings(db)
    app.jinja_env.globals["render_markdown_html"] = render_markdown_html
    app.jinja_env.globals["app_version"] = app_version

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(mailbox_bp)
    app.register_blueprint(tenders_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(computer_finder_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(rfqs_bp)
    app.register_blueprint(tender_emails_bp)

    @app.before_request
    def require_authenticated_user():
        from flask import request
        from flask_login import current_user

        if request.endpoint in {"auth.login", "static"} or current_user.is_authenticated:
            return None
        return login_manager.unauthorized()
    if not migration_mode:
        start_extraction_worker(app)
        start_mailbox_sync_worker(app)
        start_tender_monitor_worker(app)
        start_automation_scheduler(app)
    return app


app = create_app()


if __name__ == "__main__":
    debug_enabled = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=5050, debug=debug_enabled)
