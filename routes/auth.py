from __future__ import annotations

from urllib.parse import urljoin, urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from services.auth_service import authenticate_application_user


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next_url(target: str | None) -> bool:
    if not target:
        return False
    host = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in {"http", "https"} and candidate.netloc == host.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    configured = bool(current_app.config.get("ADMIN_PASSWORD") or current_app.config.get("ADMIN_PASSWORD_HASH"))
    if request.method == "POST":
        user = authenticate_application_user(
            (request.form.get("username") or "").strip(),
            request.form.get("password") or "",
        )
        if user is not None:
            login_user(user)
            next_url = request.args.get("next")
            return redirect(next_url if _safe_next_url(next_url) else url_for("dashboard.index"))
        flash("Invalid username or password.", "danger")
    return render_template("auth/login.html", authentication_configured=configured)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
