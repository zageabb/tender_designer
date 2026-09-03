from __future__ import annotations

import os
from pathlib import Path


os.environ["TENDER_DESIGNER_MIGRATION_MODE"] = "1"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app  # noqa: E402


def _test_app(**overrides):
    config = {
        "TESTING": True,
        "DATA_DIR": Path("/tmp/tender-designer-version-test"),
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "test-password",
        "SECRET_KEY": "test-secret",
    }
    config.update(overrides)
    return create_app(config)


def test_default_version_is_visible_in_shared_navigation():
    app = _test_app()
    response = app.test_client().get("/auth/login")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Tender Designer" in body
    assert "v0.1.3" in body
    assert app.config["APP_VERSION"] == "0.1.3"


def test_config_version_override_is_visible():
    app = _test_app(APP_VERSION="0.2.3")
    response = app.test_client().get("/auth/login")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "v0.2.3" in body
    assert app.config["APP_VERSION"] == "0.2.3"
