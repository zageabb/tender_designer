from __future__ import annotations

import os

from flask import Flask

from config import Config
from database import db
from routes.admin import admin_bp
from routes.chat import chat_bp
from routes.computer_finder import computer_finder_bp
from routes.dashboard import dashboard_bp
from routes.mailbox import mailbox_bp
from routes.rfqs import rfqs_bp
from routes.settings import settings_bp
from routes.tender_emails import tender_emails_bp
from routes.tenders import tenders_bp
from services.extraction_jobs import start_extraction_worker
from services.markdown_tools import render_markdown_html
from services.settings_service import ensure_default_settings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["DATA_DIR"].mkdir(parents=True, exist_ok=True)
    (app.config["DATA_DIR"] / "tenders").mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    with app.app_context():
        import models  # noqa: F401

        db.create_all()
        ensure_default_settings(db)
    app.jinja_env.globals["render_markdown_html"] = render_markdown_html

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(mailbox_bp)
    app.register_blueprint(tenders_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(computer_finder_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(rfqs_bp)
    app.register_blueprint(tender_emails_bp)
    start_extraction_worker(app)
    return app


app = create_app()


if __name__ == "__main__":
    debug_enabled = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=5050, debug=debug_enabled)
