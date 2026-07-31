from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file, url_for

from database import db
from models import AppSetting, Tender, TenderDocument, TenderItem, TenderSubItem
from services.computer_finder_service import (
    parse_domain_list,
)
from services.computer_finder_jobs import create_computer_finder_job, get_computer_finder_job
from services.file_storage import save_tender_bytes
from services.prompt_service import PROMPT_FILES, ensure_prompt_files, get_prompt_content, save_prompt_content
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

COMPUTER_FINDER_PROMPT_KEYS = [
    "computer_finder_query_planning",
    "computer_finder_search",
    "general_search_query_planning",
    "general_search_answer",
]


@computer_finder_bp.route("/", methods=["GET"])
def index():
    ensure_default_settings(db)
    ensure_prompt_files()
    tender = Tender.query.get(request.args.get("tender_id", type=int)) if request.args.get("tender_id") else None
    selected_items, selected_sub_items = _selected_tender_lines(tender)
    selected_spec = _selection_spec(tender, selected_items, selected_sub_items)
    return render_template(
        "computer_finder/index.html",
        finder_settings=_current_settings(),
        allowed_domains=parse_domain_list(get_setting("computer_finder_allowed_domains")),
        blocked_domains=parse_domain_list(get_setting("computer_finder_blocked_domains")),
        finder_prompts=[
            {
                "key": key,
                "title": PROMPT_FILES[key]["title"],
                "description": PROMPT_FILES[key]["description"],
                "content": get_prompt_content(key),
            }
            for key in COMPUTER_FINDER_PROMPT_KEYS
        ],
        tenders=Tender.query.order_by(Tender.updated_at.desc()).limit(200).all(),
        tender=tender,
        selected_items=selected_items,
        selected_sub_items=selected_sub_items,
        selected_spec=selected_spec,
        chat_context={"page": "computer_finder"},
    )


@computer_finder_bp.route("/tender/<int:tender_id>/select", methods=["GET"])
def select_tender_items(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    return render_template(
        "computer_finder/select_items.html",
        tender=tender,
        chat_context={"page": "computer_finder_selection", "tender_id": tender.id},
    )


@computer_finder_bp.route("/search", methods=["POST"])
def search():
    payload = request.get_json(force=True)
    computer_spec = _conversation_search_spec(payload)
    mode = "general" if payload.get("mode") == "general" else "computer"
    use_allowed_websites = mode == "computer" or bool(payload.get("use_allowed_websites"))
    if not computer_spec:
        message = "Enter a research question before searching." if mode == "general" else "Enter a computer specification before searching."
        return jsonify({"ok": False, "message": message}), 400
    job = create_computer_finder_job(
        current_app._get_current_object(),
        computer_spec,
        mode=mode,
        use_allowed_websites=use_allowed_websites,
    )
    return jsonify({"ok": True, "job": job}), 202


@computer_finder_bp.route("/search/<job_id>", methods=["GET"])
def search_status(job_id: str):
    job = get_computer_finder_job(job_id)
    if job is None:
        return jsonify({"ok": False, "message": "Computer Finder job not found."}), 404
    return jsonify({"ok": True, "job": job})


def _selected_tender_lines(tender: Tender | None) -> tuple[list[TenderItem], list[TenderSubItem]]:
    if tender is None:
        return [], []
    item_ids = set(request.args.getlist("item_ids", type=int))
    sub_item_ids = set(request.args.getlist("sub_item_ids", type=int))
    selected_items = [item for item in tender.items if item.id in item_ids]
    selected_sub_items = [
        sub_item
        for item in tender.items
        for sub_item in item.sub_items
        if sub_item.id in sub_item_ids
    ]
    return selected_items, selected_sub_items


def _selection_spec(
    tender: Tender | None,
    selected_items: list[TenderItem],
    selected_sub_items: list[TenderSubItem],
) -> str:
    lines: list[str] = []
    if tender is not None:
        lines.extend(
            [
                f"Tender: {tender.tender_number} — {tender.customer_name}",
                "Selected requirements:",
            ]
        )
    for item in selected_items:
        lines.append(f"- {item.description} | Quantity: {item.quantity_required}")
        if item.specification_summary:
            lines.append(f"  Specification: {item.specification_summary}")
        for specification in item.specifications:
            lines.append(f"  Requirement: {specification.specification_text}")
    for sub_item in selected_sub_items:
        lines.append(
            f"- {sub_item.tender_item.description} / {sub_item.description} | Quantity: {sub_item.quantity}"
        )
        if sub_item.notes:
            lines.append(f"  Notes: {sub_item.notes}")
        for specification in sub_item.specifications:
            lines.append(f"  Requirement: {specification.specification_text}")
    return "\n".join(lines).strip()


def _conversation_search_spec(payload: dict) -> str:
    base_spec = str(payload.get("base_spec") or payload.get("spec") or "").strip()[:20000]
    instruction = str(payload.get("instruction") or "").strip()[:5000]
    history_lines: list[str] = []
    for entry in (payload.get("history") or [])[-6:]:
        if not isinstance(entry, dict):
            continue
        role = "User" if entry.get("role") == "user" else "Previous recommendation"
        content = str(entry.get("content") or "").strip()[:6000]
        if content:
            history_lines.append(f"{role}: {content}")
    parts = [base_spec]
    if history_lines:
        parts.extend(["Previous search conversation:", *history_lines])
    if instruction:
        parts.extend(["Current refinement request:", instruction])
    return "\n\n".join(part for part in parts if part).strip()[:45000]


def _result_payload() -> tuple[str, str, list[dict], str]:
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
        raise ValueError("Run a research search before saving its result.")
    mode = "general" if payload.get("mode") == "general" else "computer"
    return computer_spec, answer, sources, mode


def _result_markdown(computer_spec: str, answer: str, sources: list[dict], mode: str = "computer") -> str:
    general = mode == "general"
    lines = [
        "# General Search Result" if general else "# Computer Finder Result",
        "",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Research Request" if general else "## Requested Specification",
        "",
        computer_spec,
        "",
        "## Answer" if general else "## Recommendation",
        "",
        answer,
    ]
    if sources:
        lines.extend(["", "## Sources", ""])
        for index, source in enumerate(sources, start=1):
            lines.append(f"{index}. [{source['title']}]({source['url']})")
    return "\n".join(lines).strip() + "\n"


def _result_filename(mode: str = "computer") -> str:
    prefix = "general_search_result" if mode == "general" else "computer_finder_result"
    return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"


@computer_finder_bp.route("/export", methods=["POST"])
def export_result():
    try:
        computer_spec, answer, sources, mode = _result_payload()
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    content = _result_markdown(computer_spec, answer, sources, mode).encode("utf-8")
    return send_file(
        BytesIO(content),
        mimetype="text/markdown",
        as_attachment=True,
        download_name=_result_filename(mode),
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
        computer_spec, answer, sources, mode = _result_payload()
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    content_text = _result_markdown(computer_spec, answer, sources, mode)
    original_name, stored_name, saved_path = save_tender_bytes(
        current_app.config["DATA_DIR"],
        tender.id,
        _result_filename(mode),
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
        processing_notes="Saved from General Search result." if mode == "general" else "Saved from Computer Finder result.",
    )
    db.session.add(document)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": f"Saved {'General Search' if mode == 'general' else 'Computer Finder'} result to tender {tender.tender_number}.",
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


@computer_finder_bp.route("/prompts", methods=["POST"])
def update_prompts():
    payload = request.get_json(force=True)
    prompts = payload.get("prompts")
    if not isinstance(prompts, dict):
        return jsonify({"ok": False, "message": "No Finder instructions were supplied."}), 400

    missing_keys = [key for key in COMPUTER_FINDER_PROMPT_KEYS if not str(prompts.get(key) or "").strip()]
    if missing_keys:
        return jsonify({"ok": False, "message": "All research instruction fields are required."}), 400

    for key in COMPUTER_FINDER_PROMPT_KEYS:
        save_prompt_content(key, str(prompts[key]))
    return jsonify({"ok": True, "message": "Research instructions saved."})


def _current_settings() -> dict:
    values = {key: get_setting(key, DEFAULT_SETTINGS[key]["value"]) or "" for key in COMPUTER_FINDER_SETTING_KEYS}
    if values["computer_finder_search_provider"] not in {"ollama_agent", "direct"}:
        values["computer_finder_search_provider"] = "ollama_agent"
    return values
