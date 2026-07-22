from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from database import db
from models import MailboxAttachment, MailboxMessage, MailboxSyncJob, Tender
from services.mailbox_jobs import enqueue_mailbox_sync_job, get_mailbox_worker_status
from services.mailbox_service import (
    _commit_with_retry,
    archive_mailbox_message,
    create_tender_from_mailbox_message,
    delete_mailbox_message,
    import_mailbox_message_to_tender,
    link_mailbox_message_to_tender,
    list_mailbox_folders,
    mailbox_is_configured,
    mailbox_message_conversation_key,
    mark_mailbox_message_read,
    normalize_conversation_subject,
    send_composed_message,
)


mailbox_bp = Blueprint("mailbox", __name__, url_prefix="/mailbox")


def _selected_message_ids() -> list[int]:
    message_ids: list[int] = []
    for raw_value in request.form.getlist("message_ids"):
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            continue
        if parsed not in message_ids:
            message_ids.append(parsed)
    return message_ids


def _route_kwargs(tender_id: int | None, selected_folder: str | None, view_mode: str | None = None, include_archived: bool = False) -> dict:
    route_kwargs: dict[str, object] = {}
    if tender_id:
        route_kwargs["tender_id"] = tender_id
    if selected_folder:
        route_kwargs["folder"] = selected_folder
    if view_mode and view_mode != "messages":
        route_kwargs["mode"] = view_mode
    if include_archived:
        route_kwargs["include_archived"] = 1
    return route_kwargs


def _is_archived_folder(folder: str | None) -> bool:
    normalized = (folder or "").strip().lower()
    return normalized in {"[gmail]/all mail", "[googlemail]/all mail", "all mail", "archive", "archived"}


def _conversation_summaries(messages: list[MailboxMessage]) -> list[dict]:
    grouped: dict[str, list[MailboxMessage]] = defaultdict(list)
    for message in messages:
        grouped[mailbox_message_conversation_key(message)].append(message)
    summaries: list[dict] = []
    for key, group in grouped.items():
        ordered = sorted(
            group,
            key=lambda item: (item.received_at or item.created_at, item.id),
            reverse=True,
        )
        latest = ordered[0]
        summaries.append(
            {
                "key": key,
                "subject": normalize_conversation_subject(latest.subject),
                "display_subject": latest.subject or "(No subject)",
                "latest_message": latest,
                "count": len(ordered),
                "unread_count": sum(1 for item in ordered if not item.is_read),
                "messages": ordered,
            }
        )
    return sorted(
        summaries,
        key=lambda item: ((item["latest_message"].received_at or item["latest_message"].created_at), item["latest_message"].id),
        reverse=True,
    )


@mailbox_bp.route("/")
def index():
    tender_id = request.args.get("tender_id", type=int)
    selected_folder = (request.args.get("folder") or "").strip()
    view_mode = (request.args.get("mode") or "messages").strip().lower()
    include_archived = request.args.get("include_archived", type=int) == 1
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
    messages = query.order_by(MailboxMessage.received_at.desc().nullslast(), MailboxMessage.created_at.desc()).limit(200).all()
    if not selected_folder and not include_archived:
        messages = [message for message in messages if not _is_archived_folder(message.mailbox_folder)]
    recent_sync_jobs = MailboxSyncJob.query.order_by(MailboxSyncJob.created_at.desc()).limit(5).all()
    conversation_summaries = _conversation_summaries(messages) if view_mode == "conversation" else []
    return render_template(
        "mailbox/index.html",
        messages=messages[:50],
        conversation_summaries=conversation_summaries[:50],
        tender=tender,
        tenders=Tender.query.order_by(Tender.updated_at.desc()).limit(200).all(),
        folders=folders,
        folder_error=folder_error,
        selected_folder=selected_folder,
        selected_view_mode=view_mode,
        include_archived=include_archived,
        recent_sync_jobs=recent_sync_jobs,
        mailbox_worker_status=get_mailbox_worker_status(),
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
    view_mode = (request.form.get("mode") or "messages").strip().lower()
    include_archived = request.form.get("include_archived", type=int) == 1
    label = selected_folder or "INBOX"
    job = MailboxSyncJob(
        mailbox_folder=selected_folder or "INBOX",
        status="queued",
        summary_message=f"Mailbox sync queued for {label}.",
    )
    db.session.add(job)
    db.session.commit()
    enqueue_mailbox_sync_job(job.id)
    flash(f"Mailbox sync queued for {label}. The page will refresh immediately while Gmail sync continues in the background.", "success")
    return redirect(url_for("mailbox.index", **_route_kwargs(tender_id, selected_folder, view_mode, include_archived)))


@mailbox_bp.route("/compose", methods=["GET", "POST"])
def compose_message():
    tender_id = request.values.get("tender_id", type=int)
    selected_folder = (request.values.get("folder") or "").strip()
    tender = Tender.query.get(tender_id) if tender_id else None
    if request.method == "POST":
        recipient_email = (request.form.get("recipient_email") or "").strip()
        cc_emails = (request.form.get("cc_emails") or "").strip()
        subject = (request.form.get("subject") or "").strip()
        body_text = (request.form.get("body_text") or "").strip()
        link_tender_id = request.form.get("link_tender_id", type=int)
        linked_tender = Tender.query.get(link_tender_id) if link_tender_id else tender
        try:
            mailbox_message = send_composed_message(
                current_app.config["DATA_DIR"],
                recipient_email,
                subject,
                body_text,
                cc_emails=cc_emails,
                tender=linked_tender,
            )
            _commit_with_retry()
            flash(f"Sent email to {recipient_email}.", "success")
            route_kwargs = {"message_id": mailbox_message.id}
            route_kwargs.update(_route_kwargs(linked_tender.id if linked_tender else None, selected_folder))
            return redirect(url_for("mailbox.view_message", **route_kwargs))
        except Exception as exc:
            db.session.rollback()
            flash(f"Could not send that email: {exc}", "danger")
    return render_template(
        "mailbox/compose.html",
        tender=tender,
        tenders=Tender.query.order_by(Tender.updated_at.desc()).limit(200).all(),
        selected_folder=selected_folder,
        chat_context={
            "page": "mailbox_compose",
            "tender_id": tender.id if tender else None,
            "mailbox_folder": selected_folder,
        },
    )


@mailbox_bp.route("/<int:message_id>")
def view_message(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.args.get("tender_id", type=int)
    selected_folder = (request.args.get("folder") or mailbox_message.mailbox_folder or "").strip()
    tender = Tender.query.get(tender_id) if tender_id else None
    try:
        mark_mailbox_message_read(mailbox_message)
        _commit_with_retry()
    except Exception:
        db.session.rollback()
    conversation_messages = [
        message
        for message in MailboxMessage.query.order_by(MailboxMessage.received_at.desc().nullslast(), MailboxMessage.created_at.desc()).limit(250).all()
        if mailbox_message_conversation_key(message) == mailbox_message_conversation_key(mailbox_message)
    ]
    return render_template(
        "mailbox/view.html",
        mailbox_message=mailbox_message,
        tender=tender,
        tenders=Tender.query.order_by(Tender.updated_at.desc()).limit(200).all(),
        conversation_messages=conversation_messages,
        selected_folder=selected_folder,
        chat_context={
            "page": "mailbox_message",
            "tender_id": tender.id if tender else None,
            "selected_mailbox_message_id": mailbox_message.id,
            "visible_mailbox_message_ids": [message.id for message in conversation_messages[:12]] or [mailbox_message.id],
            "mailbox_folder": selected_folder,
        },
    )


@mailbox_bp.route("/<int:message_id>/attachments/<int:attachment_id>/download")
def download_attachment(message_id: int, attachment_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    attachment = MailboxAttachment.query.filter_by(id=attachment_id, mailbox_message_id=mailbox_message.id).first_or_404()
    return send_file(attachment.file_path, as_attachment=True, download_name=attachment.original_filename)


@mailbox_bp.route("/<int:message_id>/create-tender", methods=["POST"])
def create_tender_from_message(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    try:
        tender = create_tender_from_mailbox_message(current_app.config["DATA_DIR"], mailbox_message)
        _commit_with_retry()
        flash(f"Created tender {tender.tender_number} from mailbox email.", "success")
        return redirect(url_for("tenders.detail_tender", tender_id=tender.id))
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not create a tender from that email: {exc}", "danger")
        return redirect(url_for("mailbox.view_message", message_id=mailbox_message.id, **_route_kwargs(tender_id, selected_folder)))


@mailbox_bp.route("/<int:message_id>/import-to-tender", methods=["POST"])
def import_to_tender(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    tender = Tender.query.get_or_404(tender_id)
    try:
        import_mailbox_message_to_tender(current_app.config["DATA_DIR"], mailbox_message, tender)
        _commit_with_retry()
        flash(f"Imported mailbox email into tender {tender.tender_number}.", "success")
        return redirect(url_for("tenders.detail_tender", tender_id=tender.id, _anchor="mailbox"))
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not import that email into the tender: {exc}", "danger")
        return redirect(url_for("mailbox.view_message", message_id=mailbox_message.id, tender_id=tender.id, folder=selected_folder))


@mailbox_bp.route("/<int:message_id>/link-to-tender", methods=["POST"])
def link_to_tender(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("link_tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    if not tender_id:
        flash("Choose a tender to link this email to.", "warning")
        return redirect(url_for("mailbox.view_message", message_id=mailbox_message.id, folder=selected_folder))
    tender = Tender.query.get_or_404(tender_id)
    try:
        link_mailbox_message_to_tender(mailbox_message, tender, notes="Linked from mailbox.")
        _commit_with_retry()
        flash(f"Linked mailbox email to tender {tender.tender_number}.", "success")
        return redirect(url_for("tenders.detail_tender", tender_id=tender.id, _anchor="mailbox"))
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not link that email to the tender: {exc}", "danger")
        return redirect(url_for("mailbox.view_message", message_id=mailbox_message.id, tender_id=tender.id, folder=selected_folder))


@mailbox_bp.route("/<int:message_id>/archive", methods=["POST"])
def archive_message(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    subject = mailbox_message.subject or "(No subject)"
    try:
        remote_status = archive_mailbox_message(mailbox_message)
        _commit_with_retry()
        flash(f"Archived mailbox email {subject}. Remote status: {remote_status}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not archive that mailbox email: {exc}", "danger")
    return redirect(url_for("mailbox.index", **_route_kwargs(tender_id, selected_folder, request.form.get("mode"), request.form.get("include_archived", type=int) == 1)))


@mailbox_bp.route("/<int:message_id>/delete", methods=["POST"])
def delete_message(message_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or mailbox_message.mailbox_folder or "").strip()
    subject = mailbox_message.subject or "(No subject)"
    try:
        remote_status = delete_mailbox_message(current_app.config["DATA_DIR"], mailbox_message)
        _commit_with_retry()
        flash(f"Deleted mailbox email {subject}. Remote status: {remote_status}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not delete that mailbox email: {exc}", "danger")
    return redirect(url_for("mailbox.index", **_route_kwargs(tender_id, selected_folder, request.form.get("mode"), request.form.get("include_archived", type=int) == 1)))


@mailbox_bp.route("/bulk-action", methods=["POST"])
def bulk_action():
    tender_id = request.form.get("tender_id", type=int)
    selected_folder = (request.form.get("folder") or "").strip()
    action_name = (request.form.get("bulk_action") or "").strip()
    view_mode = (request.form.get("mode") or "messages").strip().lower()
    include_archived = request.form.get("include_archived", type=int) == 1
    message_ids = _selected_message_ids()
    route_kwargs = _route_kwargs(tender_id, selected_folder, view_mode, include_archived)
    if not message_ids:
        flash("Select at least one email first.", "warning")
        return redirect(url_for("mailbox.index", **route_kwargs))

    messages = MailboxMessage.query.filter(MailboxMessage.id.in_(message_ids)).order_by(MailboxMessage.received_at.desc().nullslast()).all()
    if not messages:
        flash("The selected emails could not be found.", "warning")
        return redirect(url_for("mailbox.index", **route_kwargs))

    try:
        if action_name == "open":
            if len(messages) != 1:
                flash("Open Selected works with exactly one email.", "warning")
                return redirect(url_for("mailbox.index", **route_kwargs))
            return redirect(url_for("mailbox.view_message", message_id=messages[0].id, **route_kwargs))

        if action_name == "create_tender":
            created_tenders = []
            for mailbox_message in messages:
                created_tenders.append(create_tender_from_mailbox_message(current_app.config["DATA_DIR"], mailbox_message))
                _commit_with_retry()
            if len(created_tenders) == 1:
                flash(f"Created tender {created_tenders[0].tender_number} from the selected email.", "success")
                return redirect(url_for("tenders.detail_tender", tender_id=created_tenders[0].id))
            flash(f"Created {len(created_tenders)} tenders from the selected emails.", "success")
            return redirect(url_for("mailbox.index", **route_kwargs))

        if action_name == "import_to_tender":
            if not tender_id:
                flash("Choose a tender-linked mailbox view before importing emails into a tender.", "warning")
                return redirect(url_for("mailbox.index", **route_kwargs))
            tender = Tender.query.get_or_404(tender_id)
            for mailbox_message in messages:
                import_mailbox_message_to_tender(current_app.config["DATA_DIR"], mailbox_message, tender)
                _commit_with_retry()
            flash(f"Imported {len(messages)} email(s) into tender {tender.tender_number}.", "success")
            return redirect(url_for("tenders.detail_tender", tender_id=tender.id, _anchor="mailbox"))

        if action_name == "archive":
            archived_count = 0
            remote_statuses: list[str] = []
            for mailbox_message in messages:
                remote_statuses.append(archive_mailbox_message(mailbox_message))
                _commit_with_retry()
                archived_count += 1
            summary = ", ".join(sorted(dict.fromkeys(remote_statuses)))
            flash(f"Archived {archived_count} mailbox email(s). Remote status: {summary}.", "success")
            return redirect(url_for("mailbox.index", **route_kwargs))

        if action_name == "delete":
            deleted_count = 0
            remote_statuses = []
            for mailbox_message in messages:
                remote_statuses.append(delete_mailbox_message(current_app.config["DATA_DIR"], mailbox_message))
                _commit_with_retry()
                deleted_count += 1
            summary = ", ".join(sorted(dict.fromkeys(remote_statuses)))
            flash(f"Deleted {deleted_count} mailbox email(s). Remote status: {summary}.", "success")
            return redirect(url_for("mailbox.index", **route_kwargs))

        flash("That mailbox action is not supported.", "warning")
        return redirect(url_for("mailbox.index", **route_kwargs))
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not complete the mailbox action: {exc}", "danger")
        return redirect(url_for("mailbox.index", **route_kwargs))
