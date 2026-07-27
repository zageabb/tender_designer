from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file, url_for

from database import db
from models import AppSetting, Tender, TenderDocument
from services.computer_finder_service import (
    ComputerFinderConfigError,
    find_computer_for_spec,
    parse_domain_list,
)
from services.file_storage import save_tender_bytes
from services.settings_service import DEFAULT_SETTINGS, ensure_default_settings, get_setting


computer_finder_bp = Blueprint("computer_finder", __name__, url_prefix="/computer-finder")


COMPUTER_FINDER_SETTING_KEYS = [
    "computer_finder_search_provider",
    "computer_finder_search_backend",
    "computer_finder_max_search_rounds",
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
        tenders=Tender.query.order_by(Tender.updated_at.desc()).limit(200).all(),
        chat_context={"page": "computer_finder"},
    )


@computer_finder_bp.route("/search", methods=["POST"])
def search():
    payload = request.get_json(force=True)
    computer_spec = (payload.get("spec") or "").strip()
    try:
        result = find_computer_for_spec(computer_spec)
    except ComputerFinderConfigError as exc:
        return jsonify({"ok": False, "message": str(exc), "steps": getattr(exc, "steps", [])}), 400
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


def _result_payload() -> tuple[str, str, list[dict]]:
    payload = request.get_json(force=True)
    computer_spec = str(payload.get("spec") or "").strip()[:20000]
    answer = str(payload.get("message") or "").strip()[:100000]
    sources = []
    for source in (payload.get("sources") or [])[:50]:
        if not isinstance(source, dict):
            continue
        title = " ".join(str(source.get("title") or "").split())[:500]
        source_url = str(source.get("url") or "").strip()[:2000]
        if source_url:
            sources.append({"title": title or source_url, "url": source_url})
    if not computer_spec or not answer:
        raise ValueError("Run a computer search before saving its result.")
    return computer_spec, answer, sources


def _result_markdown(computer_spec: str, answer: str, sources: list[dict]) -> str:
    lines = [
        "# Computer Finder Result",
        "",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Requested Specification",
        "",
        computer_spec,
        "",
        "## Recommendation",
        "",
        answer,
    ]
    if sources:
        lines.extend(["", "## Sources", ""])
        for index, source in enumerate(sources, start=1):
            lines.append(f"{index}. [{source['title']}]({source['url']})")
    return "\n".join(lines).strip() + "\n"


def _result_filename() -> str:
    return f"computer_finder_result_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"


@computer_finder_bp.route("/export", methods=["POST"])
def export_result():
    try:
        computer_spec, answer, sources = _result_payload()
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    content = _result_markdown(computer_spec, answer, sources).encode("utf-8")
    return send_file(
        BytesIO(content),
        mimetype="text/markdown",
        as_attachment=True,
        download_name=_result_filename(),
    )


@computer_finder_bp.route("/attach-to-tender", methods=["POST"])
def attach_result_to_tender():
    payload = request.get_json(force=True)
    tender_id = payload.get("tender_id")
    try:
        tender_id = int(tender_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Choose a tender before saving the result."}), 400
    tender = Tender.query.get(tender_id)
    if tender is None:
        return jsonify({"ok": False, "message": "The selected tender could not be found."}), 404
    try:
        computer_spec, answer, sources = _result_payload()
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    content_text = _result_markdown(computer_spec, answer, sources)
    original_name, stored_name, saved_path = save_tender_bytes(
        current_app.config["DATA_DIR"],
        tender.id,
        _result_filename(),
        content_text.encode("utf-8"),
    )
    document = TenderDocument(
        tender=tender,
        original_filename=original_name,
        stored_filename=stored_name,
        file_path=str(saved_path),
        file_type=Path(original_name).suffix.lstrip(".") or "md",
        extracted_text=content_text,
        processed=True,
        processing_notes="Saved from Computer Finder result.",
    )
    db.session.add(document)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": f"Saved Computer Finder result to tender {tender.tender_number}.",
            "document_id": document.id,
            "tender_url": url_for("tenders.detail_tender", tender_id=tender.id, _anchor="documents"),
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
        if key == "computer_finder_search_provider" and value not in {"ollama_agent", "direct"}:
            value = "ollama_agent"
        if key == "computer_finder_search_backend" and value not in {
            "auto", "bing", "brave", "duckduckgo", "google", "mojeek", "startpage", "yahoo", "yandex"
        }:
            value = "auto"
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
    values = {key: get_setting(key, DEFAULT_SETTINGS[key]["value"]) or "" for key in COMPUTER_FINDER_SETTING_KEYS}
    if values["computer_finder_search_provider"] not in {"ollama_agent", "direct"}:
        values["computer_finder_search_provider"] = "ollama_agent"
    return values
