from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from database import db
from models import MailboxMessage, Tender
from services.mailbox_service import (
    create_tender_from_mailbox_message,
    delete_mailbox_message,
    import_mailbox_message_to_tender,
    list_mailbox_folders,
    mailbox_is_configured,
    sync_mailbox,
    sync_mailbox_folder,
)


mailbox_bp = Blueprint("mailbox", __name__, url_prefix="/mailbox")


@mailbox_bp.route("/")
def index():
    tender_id = request.args.get("tender_id", type=int)
    selected_folder = (request.args.get("folder") or "").strip()
    tender = Tender.query.get(tender_id) if tender_id else None
    folder_error = None
    folders: list[str] = []
    if mailbox_is_configured():
        try:
            folders = list_mailbox_folders()
        except Exception as exc:
            folder_error = str(exc)
    query = MailboxMessage.query
    if selected_folder:
        query = query.filter_by(mailbox_folder=selected_folder)
    messages = query.order_by(MailboxMessage.received_at.desc().nullslast(), MailboxMessage.created_at.desc()).limit(50).all()
    return render_template(
        "mailbox/index.html",
        messages=messages,
        tender=tender,
        folders=folders,
        folder_error=folder_error,
        selected_folder=selected_folder,
        mailbox_configured=mailbox_is_configured(),
        chat_context={
            "page": "mailbox",
            "tender_id": tender.id if tender else None,
            "visible_mailbox_message_ids": [message.id for message in messages[:12]],
            "mailbox_tender_id": tender.id if tender else None,
            "mailbox_folder": selected_folder,
        },
    )


@mailbox_bp.route("/sync", methods=["POST"])
def sync():
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or "").strip()
    try:
        result = (
            sync_mailbox_folder(current_app.config["DATA_DIR"], selected_folder)
            if selected_folder
            else sync_mailbox(current_app.config["DATA_DIR"])
        )
        label = selected_folder or "default folder"
        flash(
            f"Mailbox sync complete for {label}. Created {result['created']} message(s), updated {result['updated']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Mailbox sync failed: {exc}", "danger")
    route_kwargs = {}
    if tender_id:
        route_kwargs["tender_id"] = tender_id
    if selected_folder:
        route_kwargs["folder"] = selected_folder
    return redirect(url_for("mailbox.index", **route_kwargs))


@mailbox_bp.route("/<int:message_id>")
def view_message(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.args.get("tender_id", type=int)
    selected_folder = (request.args.get("folder") or mailbox_message.mailbox_folder or "").strip()
    tender = Tender.query.get(tender_id) if tender_id else None
    return render_template(
        "mailbox/view.html",
        mailbox_message=mailbox_message,
        tender=tender,
        selected_folder=selected_folder,
        chat_context={
            "page": "mailbox_message",
            "tender_id": tender.id if tender else None,
            "selected_mailbox_message_id": mailbox_message.id,
            "visible_mailbox_message_ids": [mailbox_message.id],
            "mailbox_folder": selected_folder,
        },
    )


@mailbox_bp.route("/<int:message_id>/create-tender", methods=["POST"])
def create_tender_from_message(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    try:
        tender = create_tender_from_mailbox_message(current_app.config["DATA_DIR"], mailbox_message)
        db.session.commit()
        flash(f"Created tender {tender.tender_number} from mailbox email.", "success")
        return redirect(url_for("tenders.detail_tender", tender_id=tender.id))
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not create a tender from that email: {exc}", "danger")
        route_kwargs = {"message_id": mailbox_message.id}
        if tender_id:
            route_kwargs["tender_id"] = tender_id
        if selected_folder:
            route_kwargs["folder"] = selected_folder
        return redirect(url_for("mailbox.view_message", **route_kwargs))


@mailbox_bp.route("/<int:message_id>/import-to-tender", methods=["POST"])
def import_to_tender(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    tender = Tender.query.get_or_404(tender_id)
    try:
        import_mailbox_message_to_tender(current_app.config["DATA_DIR"], mailbox_message, tender)
        db.session.commit()
        flash(f"Imported mailbox email into tender {tender.tender_number}.", "success")
        return redirect(url_for("tenders.detail_tender", tender_id=tender.id, _anchor="mailbox"))
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not import that email into the tender: {exc}", "danger")
        route_kwargs = {"message_id": mailbox_message.id, "tender_id": tender.id}
        if selected_folder:
            route_kwargs["folder"] = selected_folder
        return redirect(url_for("mailbox.view_message", **route_kwargs))


@mailbox_bp.route("/<int:message_id>/delete", methods=["POST"])
def delete_message(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    subject = mailbox_message.subject or "(No subject)"
    try:
        remote_status = delete_mailbox_message(current_app.config["DATA_DIR"], mailbox_message)
        db.session.commit()
        flash(f"Deleted mailbox email {subject}. Remote status: {remote_status}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not delete that mailbox email: {exc}", "danger")
    route_kwargs = {}
    if tender_id:
        route_kwargs["tender_id"] = tender_id
    if selected_folder:
        route_kwargs["folder"] = selected_folder
    return redirect(url_for("mailbox.index", **route_kwargs))
