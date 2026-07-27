from __future__ import annotations

from dataclasses import dataclass

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash


@dataclass(frozen=True)
class ApplicationUser(UserMixin):
    id: str
    role: str = "admin"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def load_application_user(user_id: str) -> ApplicationUser | None:
    username = str(current_app.config.get("ADMIN_USERNAME") or "admin")
    return ApplicationUser(username) if user_id == username else None


def authenticate_application_user(username: str, password: str) -> ApplicationUser | None:
    configured_username = str(current_app.config.get("ADMIN_USERNAME") or "admin")
    if username != configured_username:
        return None
    password_hash = str(current_app.config.get("ADMIN_PASSWORD_HASH") or "")
    plain_password = str(current_app.config.get("ADMIN_PASSWORD") or "")
    if password_hash and check_password_hash(password_hash, password):
        return ApplicationUser(configured_username)
    if plain_password and password == plain_password:
        return ApplicationUser(configured_username)
    return None
