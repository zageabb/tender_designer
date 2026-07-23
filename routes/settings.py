from __future__ import annotations

from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for

from database import db
from models import AppSetting
from services.markdown_tools import render_markdown_html
from services.ollama_client import OllamaClient
from services.prompt_service import PROMPT_FILES, ensure_prompt_files, get_prompt_content, save_prompt_content
from services.settings_service import DEFAULT_SETTINGS, ensure_default_settings


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.route("/", methods=["GET", "POST"])
def index():
    ensure_default_settings(db)
    ensure_prompt_files()
    settings = {setting.key: setting for setting in AppSetting.query.order_by(AppSetting.key.asc()).all()}
    prompt_files = {
        prompt_key: {
            **payload,
            "content": get_prompt_content(prompt_key),
        }
        for prompt_key, payload in PROMPT_FILES.items()
    }
    signal_matrix_path = Path(__file__).resolve().parent.parent / "TENDER_SIGNAL_MATRIX.md"
    signal_matrix_markdown = signal_matrix_path.read_text(encoding="utf-8") if signal_matrix_path.exists() else ""
    if request.method == "POST":
        for key in DEFAULT_SETTINGS:
            record = settings.get(key)
            if record is None:
                continue
            record.value = request.form.get(key, "").strip()
        for prompt_key in PROMPT_FILES:
            field_name = f"prompt__{prompt_key}"
            if field_name in request.form:
                save_prompt_content(prompt_key, request.form.get(field_name, ""))
        db.session.commit()
        flash("Settings updated.", "success")
        return redirect(url_for("settings.index"))
    return render_template(
        "settings/index.html",
        settings=settings,
        defaults=DEFAULT_SETTINGS,
        prompt_files=prompt_files,
        signal_matrix_html=render_markdown_html(signal_matrix_markdown) if signal_matrix_markdown else "",
        chat_context={"page": "settings"},
    )


@settings_bp.route("/test-ollama", methods=["POST"])
def test_ollama():
    ensure_default_settings(db)
    settings = {setting.key: setting for setting in AppSetting.query.order_by(AppSetting.key.asc()).all()}
    ollama_url = settings.get("ollama_url").value if settings.get("ollama_url") else DEFAULT_SETTINGS["ollama_url"]["value"]
    try:
        client = OllamaClient(ollama_url)
        models = client.list_models()
        model_preview = ", ".join(models[:5]) if models else "no models returned"
        flash(f"Ollama connection OK. Available models: {model_preview}", "success")
    except Exception as exc:
        flash(f"Ollama connection failed: {exc}", "danger")
    return redirect(url_for("settings.index"))
