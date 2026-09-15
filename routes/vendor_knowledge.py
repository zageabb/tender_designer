from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for

from database import db
from models import MailboxAttachment, MailboxMessage
from services.managed_paths import ManagedPathError, resolve_managed_path
from services.vendor_knowledge import (
    SUPPORTED_EXTENSIONS,
    archive_source,
    ingest_vendor_file,
    search_vendor_knowledge,
    set_source_active,
)
from vendor_models import VendorKnowledgeSource


vendor_knowledge_bp = Blueprint("vendor_knowledge", __name__, url_prefix="/vendor-knowledge")


@vendor_knowledge_bp.route("/", methods=["GET"])
def index():
    include_archived = request.args.get("include_archived", type=int) == 1
    query = VendorKnowledgeSource.query
    if not include_archived:
        query = query.filter(VendorKnowledgeSource.status == "active")
    sources = query.order_by(
        VendorKnowledgeSource.vendor_name.asc(),
        VendorKnowledgeSource.source_date.desc().nullslast(),
        VendorKnowledgeSource.created_at.desc(),
    ).all()
    return render_template(
        "vendor_knowledge/index.html",
        sources=sources,
        include_archived=include_archived,
        supported_extensions=", ".join(sorted(SUPPORTED_EXTENSIONS)),
        chat_context={"page": "vendor_knowledge"},
    )


@vendor_knowledge_bp.route("/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        flash("Choose a vendor price/stock file to import.", "warning")
        return redirect(url_for("vendor_knowledge.index"))
    suffix = Path(uploaded.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        flash("Vendor Knowledge currently accepts XLSX, XLSM and CSV files.", "danger")
        return redirect(url_for("vendor_knowledge.index"))

    incoming_dir = Path(current_app.config["DATA_DIR"]) / "vendor_knowledge" / "_incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    temp_path = incoming_dir / f"{uuid4().hex}_{Path(uploaded.filename).name}"
    uploaded.save(temp_path)
    try:
        source, duplicate = ingest_vendor_file(
            current_app.config["DATA_DIR"],
            temp_path,
            uploaded.filename,
            vendor_name=request.form.get("vendor_name"),
            source_name=request.form.get("source_name"),
            replace_current=request.form.get("replace_current", "1") == "1",
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not import vendor knowledge: {exc}", "danger")
        return redirect(url_for("vendor_knowledge.index", include_archived=1))
    finally:
        temp_path.unlink(missing_ok=True)

    if duplicate:
        flash(f"That file is already stored for {source.vendor_name}; the existing version was kept.", "info")
    else:
        flash(
            f"Imported {source.item_count} items for {source.vendor_name}; {source.available_item_count} are currently available. Older active versions were archived, not deleted.",
            "success",
        )
    return redirect(url_for("vendor_knowledge.view_source", source_id=source.id))


@vendor_knowledge_bp.route("/from-mailbox/<int:message_id>/<int:attachment_id>", methods=["POST"])
def import_from_mailbox(message_id: int, attachment_id: int):
    mailbox_message = MailboxMessage.query.get_or_404(message_id)
    attachment = MailboxAttachment.query.filter_by(id=attachment_id, mailbox_message_id=message_id).first_or_404()
    suffix = Path(attachment.original_filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        flash("Only XLSX, XLSM and CSV mailbox attachments can currently be pushed into Vendor Knowledge.", "danger")
        return redirect(url_for("mailbox.view_message", message_id=message_id, folder=mailbox_message.mailbox_folder))
    try:
        source_path = resolve_managed_path(current_app.config["DATA_DIR"], attachment.file_path, must_exist=True)
        source, duplicate = ingest_vendor_file(
            current_app.config["DATA_DIR"],
            source_path,
            attachment.original_filename,
            vendor_name=request.form.get("vendor_name") or mailbox_message.sender_name or mailbox_message.sender_email,
            source_name=request.form.get("source_name") or mailbox_message.subject,
            mailbox_message_id=mailbox_message.id,
            mailbox_attachment_id=attachment.id,
            fallback_source_date=mailbox_message.received_at.date() if mailbox_message.received_at else None,
            replace_current=request.form.get("replace_current", "1") == "1",
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not push that attachment into Vendor Knowledge: {exc}", "danger")
        return redirect(url_for("mailbox.view_message", message_id=message_id, folder=mailbox_message.mailbox_folder))

    if duplicate:
        flash(f"{attachment.original_filename} is already stored for {source.vendor_name}; no duplicate version was created.", "info")
    else:
        flash(
            f"Pushed {attachment.original_filename} into Vendor Knowledge for {source.vendor_name}. "
            f"{source.item_count} items were loaded and older active versions were archived, not deleted.",
            "success",
        )
    return redirect(url_for("vendor_knowledge.view_source", source_id=source.id))


@vendor_knowledge_bp.route("/<int:source_id>", methods=["GET"])
def view_source(source_id: int):
    source = VendorKnowledgeSource.query.get_or_404(source_id)
    query_text = (request.args.get("q") or "").strip().lower()
    items = source.items
    if query_text:
        items = [
            item for item in items
            if query_text in (item.search_text or "")
            or query_text in (item.part_number or "").lower()
            or query_text in item.description.lower()
        ]
    return render_template(
        "vendor_knowledge/source.html",
        source=source,
        items=items[:1000],
        query_text=query_text,
        chat_context={"page": "vendor_knowledge", "vendor_source_id": source.id},
    )


@vendor_knowledge_bp.route("/<int:source_id>/archive", methods=["POST"])
def archive(source_id: int):
    source = VendorKnowledgeSource.query.get_or_404(source_id)
    archive_source(source)
    db.session.commit()
    flash(f"Archived {source.vendor_name} source version {source.version_label or source.id}. The source and all of its items remain stored.", "success")
    return redirect(url_for("vendor_knowledge.index", include_archived=1))


@vendor_knowledge_bp.route("/<int:source_id>/activate", methods=["POST"])
def activate(source_id: int):
    source = VendorKnowledgeSource.query.get_or_404(source_id)
    set_source_active(source)
    db.session.commit()
    flash(f"Activated {source.vendor_name} source version {source.version_label or source.id}. Other active versions for that vendor were archived.", "success")
    return redirect(url_for("vendor_knowledge.view_source", source_id=source.id))


@vendor_knowledge_bp.route("/<int:source_id>/download", methods=["GET"])
def download(source_id: int):
    source = VendorKnowledgeSource.query.get_or_404(source_id)
    try:
        path = resolve_managed_path(current_app.config["DATA_DIR"], source.file_path, must_exist=True)
    except ManagedPathError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("vendor_knowledge.view_source", source_id=source.id))
    return send_file(path, as_attachment=True, download_name=source.original_filename)


@vendor_knowledge_bp.route("/api/search", methods=["GET"])
def api_search():
    query_text = (request.args.get("q") or "").strip()
    if not query_text:
        return jsonify({"ok": False, "message": "Provide q= with a product or specification search."}), 400
    results = search_vendor_knowledge(
        query_text,
        limit=request.args.get("limit", default=12, type=int) or 12,
        include_archived=request.args.get("include_archived", type=int) == 1,
        available_only=request.args.get("available_only", default=1, type=int) != 0,
    )
    return jsonify({"ok": True, "count": len(results), "results": results})
