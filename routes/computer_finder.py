from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from database import db
from models import AppSetting
from services.computer_finder_service import (
    ComputerFinderConfigError,
    find_computer_for_spec,
    parse_domain_list,
)
from services.settings_service import DEFAULT_SETTINGS, ensure_default_settings, get_setting


computer_finder_bp = Blueprint("computer_finder", __name__, url_prefix="/computer-finder")


COMPUTER_FINDER_SETTING_KEYS = [
    "computer_finder_model",
    "computer_finder_results_per_domain",
    "computer_finder_max_pages_to_read",
    "computer_finder_allowed_domains",
    "computer_finder_blocked_domains",
    "computer_finder_market_country",
    "computer_finder_market_region",
    "computer_finder_market_city",
]


@computer_finder_bp.route("/", methods=["GET"])
def index():
    ensure_default_settings(db)
    return render_template(
        "computer_finder/index.html",
        finder_settings=_current_settings(),
        allowed_domains=parse_domain_list(get_setting("computer_finder_allowed_domains")),
        blocked_domains=parse_domain_list(get_setting("computer_finder_blocked_domains")),
        chat_context={"page": "computer_finder"},
    )


@computer_finder_bp.route("/search", methods=["POST"])
def search():
    payload = request.get_json(force=True)
    computer_spec = (payload.get("spec") or "").strip()
    try:
        result = find_computer_for_spec(computer_spec)
    except ComputerFinderConfigError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Computer search failed: {exc}"}), 500
    return jsonify(
        {
            "ok": True,
            "message": result["answer"],
            "sources": result.get("sources", []),
            "steps": result.get("steps", []),
        }
    )


@computer_finder_bp.route("/settings", methods=["POST"])
def update_settings():
    ensure_default_settings(db)
    payload = request.get_json(force=True)
    settings = {setting.key: setting for setting in AppSetting.query.all()}
    for key in COMPUTER_FINDER_SETTING_KEYS:
        record = settings.get(key)
        if record is None:
            default = DEFAULT_SETTINGS[key]
            record = AppSetting(key=key, value=default["value"], description=default["description"])
            db.session.add(record)
            settings[key] = record
        value = str(payload.get(key, "")).strip()
        if key in {"computer_finder_allowed_domains", "computer_finder_blocked_domains"}:
            value = "\n".join(parse_domain_list(value))
        if key == "computer_finder_market_country":
            value = value.upper()
        record.value = value
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": "Computer finder settings saved.",
            "settings": _current_settings(),
            "allowed_domains": parse_domain_list(get_setting("computer_finder_allowed_domains")),
            "blocked_domains": parse_domain_list(get_setting("computer_finder_blocked_domains")),
        }
    )


def _current_settings() -> dict:
    return {key: get_setting(key, DEFAULT_SETTINGS[key]["value"]) or "" for key in COMPUTER_FINDER_SETTING_KEYS}
