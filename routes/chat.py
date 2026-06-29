from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from database import db
from models import ChatAction, ChatSession, ChatUpload, Tender, TenderDocument
from services.chat_service import (
    add_chat_message,
    apply_confirmed_action,
    build_chat_response,
    classify_message_intent,
    get_or_create_session,
    get_recent_messages,
    log_chat_exchange,
)
from services.document_extraction import extract_text
from services.file_storage import save_chat_upload, save_tender_upload
from services.ollama_client import OllamaClient
from services.settings_service import get_setting, get_task_model


chat_bp = Blueprint("chat", __name__, url_prefix="/chat")


@chat_bp.route("/history", methods=["POST"])
def history():
    payload = request.get_json(force=True)
    page_context = payload.get("context") or {}
    tender_id = page_context.get("tender_id")
    session = get_or_create_session(db, tender_id, page_context)
    db.session.commit()
    return jsonify({"messages": get_recent_messages(session)})


@chat_bp.route("/clear", methods=["POST"])
def clear():
    payload = request.get_json(force=True)
    page_context = payload.get("context") or {}
    tender_id = page_context.get("tender_id")
    query = ChatSession.query
    if tender_id is None:
        query = query.filter(ChatSession.tender_id.is_(None))
    else:
        query = query.filter_by(tender_id=tender_id)
    sessions = query.all()
    cleared = 0
    for session in sessions:
        for upload in session.uploads:
            if upload.file_path and os.path.exists(upload.file_path):
                try:
                    os.remove(upload.file_path)
                except OSError:
                    pass
        db.session.delete(session)
        cleared += 1
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": "Chat cleared for this context." if cleared else "There was no saved chat history for this context.",
        }
    )


@chat_bp.route("/message", methods=["POST"])
def message():
    payload = request.get_json(force=True)
    user_message = payload.get("message", "").strip()
    page_context = payload.get("context") or {}
    tender_id = page_context.get("tender_id")
    tender = Tender.query.get(tender_id) if tender_id else None
    session = get_or_create_session(db, tender_id, page_context)
    normalized = user_message.lower().strip()
    latest_upload = ChatUpload.query.order_by(ChatUpload.created_at.desc()).first()
    classifier_steps: list[str] = []
    intent_hint = None
    answer_client = None
    answer_model_name = None
    try:
        ollama_url = get_setting("ollama_url", current_app.config["OLLAMA_URL"])
        model_name = get_task_model("orchestrator", current_app.config["LLM_MODELS"]["orchestrator"])
        answer_model_name = get_task_model("chat_answering", current_app.config["LLM_MODELS"]["chat_answering"])
        classifier_client = OllamaClient(ollama_url)
        answer_client = classifier_client
        intent_hint, classifier_steps = classify_message_intent(
            classifier_client,
            model_name,
            user_message,
            has_upload=latest_upload is not None,
            has_tender_context=tender is not None,
        )
    except Exception as exc:
        classifier_steps = [f"Intent classifier setup failed: {exc}"]
        intent_hint = None

    if normalized in {"confirm", "yes", "confirm this", "yes confirm"} or intent_hint == "confirm_action":
        action = (
            ChatAction.query.filter_by(chat_session_id=session.id, status="proposed")
            .order_by(ChatAction.created_at.desc())
            .first()
        )
        if action is not None:
            try:
                message_text = apply_confirmed_action(action, current_app.config["DATA_DIR"])
                result_payload = json.loads(action.result_json) if action.result_json else {}
                response_payload = {
                    "response_type": "answer",
                    "message": message_text,
                    "intermediate_steps": classifier_steps + [
                        "Found the latest proposed action for this chat session.",
                        "Applied the confirmed action and saved the result.",
                    ],
                    "actions": [],
                    "refresh_page": True,
                    "redirect_url": result_payload.get("redirect_path"),
                }
            except Exception as exc:
                action.status = "failed"
                action.result_json = json.dumps({"error": str(exc)})
                response_payload = {
                    "response_type": "error",
                    "message": f"I could not apply that action: {exc}",
                    "intermediate_steps": classifier_steps + [
                        "Found the latest proposed action for this chat session.",
                        "The action failed during execution.",
                    ],
                    "actions": [],
                }
        else:
            response_payload = {
                "response_type": "answer",
                "message": "There is no pending action to confirm right now.",
                "intermediate_steps": classifier_steps + [
                    "Checked the current chat session for a proposed action.",
                    "No matching pending action was found.",
                ],
                "actions": [],
            }
    else:
        response_payload = build_chat_response(
            user_message,
            page_context,
            tender,
            intent_hint=intent_hint,
            answer_client=answer_client,
            answer_model_name=answer_model_name,
        )
        if classifier_steps:
            response_payload["intermediate_steps"] = classifier_steps + response_payload.get("intermediate_steps", [])
    log_chat_exchange(db, session, user_message, response_payload)
    db.session.commit()
    return jsonify(response_payload)


@chat_bp.route("/upload", methods=["POST"])
def upload():
    upload = request.files.get("file")
    tender_id = request.form.get("tender_id", type=int)
    page_context = json.loads(request.form.get("context", "{}"))
    session = get_or_create_session(db, tender_id, page_context)
    if upload is None:
        return jsonify({"ok": False, "message": "A file is required."}), 400
    if tender_id is not None:
        tender = Tender.query.get_or_404(tender_id)
        original_name = secure_filename(upload.filename or "upload")
        existing_document = TenderDocument.query.filter_by(
            tender_id=tender.id,
            original_filename=original_name,
        ).first()
        stored_name_hint = existing_document.stored_filename if existing_document else None
        original_name, stored_name, saved_path = save_tender_upload(
            current_app.config["DATA_DIR"],
            tender.id,
            upload,
            stored_name=stored_name_hint,
        )
        text, error = extract_text(saved_path)
        if existing_document is not None:
            if existing_document.extracted_text_path and os.path.exists(existing_document.extracted_text_path):
                try:
                    os.remove(existing_document.extracted_text_path)
                except OSError:
                    pass
            document = existing_document
            document.stored_filename = stored_name
            document.file_path = str(saved_path)
            document.file_type = Path(original_name).suffix.lower().lstrip(".")
            document.extracted_text = text or None
            document.extracted_text_path = None
            document.processed = bool(text)
            document.processing_notes = error or "Uploaded via chat panel."
        else:
            document = TenderDocument(
                tender=tender,
                original_filename=original_name,
                stored_filename=stored_name,
                file_path=str(saved_path),
                file_type=Path(original_name).suffix.lower().lstrip("."),
                extracted_text=text or None,
                processed=bool(text),
                processing_notes=error or "Uploaded via chat panel.",
            )
            db.session.add(document)
        db.session.commit()
        if text:
            message = (
                f"I received {original_name}. It looks ready for review. "
                "You can now ask me to extract pricing, add it to RAG, or treat it as a tender addendum."
            )
        else:
            message = f"I received {original_name}, but I could not extract text yet: {error}"
        return jsonify({"ok": True, "message": message, "document_id": document.id})

    original_name, stored_name, saved_path = save_chat_upload(current_app.config["DATA_DIR"], session.id, upload)
    text, error = extract_text(saved_path)
    chat_upload = ChatUpload(
        chat_session=session,
        original_filename=original_name,
        stored_filename=stored_name,
        file_path=str(saved_path),
        file_type=Path(original_name).suffix.lower().lstrip("."),
        extracted_text=text or None,
        processing_notes=error or "Uploaded via main chat panel.",
    )
    db.session.add(chat_upload)
    db.session.commit()
    if text:
        message = (
            f"I received {original_name} and read its contents. "
            "If you want, say 'create a tender from this document' and I will prepare a new tender from it."
        )
    else:
        message = (
            f"I received {original_name}, but I could not extract readable text yet: {error}. "
            "You can still ask me to create a tender from the file for manual review."
        )
    return jsonify({"ok": True, "message": message, "chat_upload_id": chat_upload.id})


@chat_bp.route("/confirm-action", methods=["POST"])
def confirm_action():
    payload = request.get_json(force=True)
    action_id = payload.get("action_id")
    action = ChatAction.query.get_or_404(action_id)
    action.status = "confirmed"
    action.result_json = json.dumps({"message": "Confirmation recorded. Action execution hooks come next."})
    db.session.commit()
    return jsonify({"ok": True, "message": "Action confirmed."})


@chat_bp.route("/cancel-action", methods=["POST"])
def cancel_action():
    payload = request.get_json(force=True)
    action_id = payload.get("action_id")
    action = ChatAction.query.get_or_404(action_id)
    action.status = "cancelled"
    action.result_json = json.dumps({"message": "Action cancelled by user."})
    db.session.commit()
    return jsonify({"ok": True, "message": "Action cancelled."})
