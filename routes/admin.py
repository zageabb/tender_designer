from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import inspect

from database import db
from models import (
    AppSetting,
    ChatAction,
    ChatMessage,
    ChatSession,
    ChatUpload,
    ExtractionJob,
    LLMRunLog,
    MailboxAttachment,
    MailboxDeletionRequest,
    MailboxMessage,
    MailboxSyncJob,
    MailboxTenderLink,
    RAGChunk,
    RAGDocument,
    RFQ,
    RFQLine,
    Specification,
    SupplierResponse,
    Tender,
    TenderDocument,
    TenderEmail,
    TenderEmailDocument,
    TenderItem,
    TenderQuestion,
    TenderSubItem,
)
from services.extraction_jobs import (
    cancel_extraction_job,
    ensure_extraction_worker,
    get_worker_status,
    pause_extraction_worker,
    resume_extraction_worker,
    retry_extraction_job,
)


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_MODELS = {
    "tenders": Tender,
    "tender-documents": TenderDocument,
    "tender-items": TenderItem,
    "tender-sub-items": TenderSubItem,
    "specifications": Specification,
    "rfqs": RFQ,
    "rfq-lines": RFQLine,
    "supplier-responses": SupplierResponse,
    "tender-questions": TenderQuestion,
    "tender-emails": TenderEmail,
    "tender-email-documents": TenderEmailDocument,
    "rag-documents": RAGDocument,
    "rag-chunks": RAGChunk,
    "llm-run-logs": LLMRunLog,
    "settings": AppSetting,
    "chat-sessions": ChatSession,
    "chat-messages": ChatMessage,
    "chat-actions": ChatAction,
    "chat-uploads": ChatUpload,
    "extraction-jobs": ExtractionJob,
    "mailbox-messages": MailboxMessage,
    "mailbox-attachments": MailboxAttachment,
    "mailbox-tender-links": MailboxTenderLink,
    "mailbox-deletion-requests": MailboxDeletionRequest,
    "mailbox-sync-jobs": MailboxSyncJob,
}

ADMIN_MODEL_META = {
    "tenders": {"label": "Tenders", "description": "Core tender header records and workflow status."},
    "tender-documents": {"label": "Tender Documents", "description": "Uploaded source files, extracted text, and processing state."},
    "tender-items": {"label": "Tender Items", "description": "Top-level commercial and delivery line items."},
    "tender-sub-items": {"label": "Tender Sub-items", "description": "Detailed spec or supplier rows beneath each tender item."},
    "specifications": {"label": "Specifications", "description": "Specification fragments linked to items or sub-items."},
    "rfqs": {"label": "RFQs", "description": "RFQ header drafts linked to each tender."},
    "rfq-lines": {"label": "RFQ Lines", "description": "Individual RFQ pricing lines sent to suppliers."},
    "supplier-responses": {"label": "Supplier Responses", "description": "Uploaded or parsed supplier quote responses."},
    "tender-questions": {"label": "Tender Questions", "description": "Tender clarification questions and answer state."},
    "tender-emails": {"label": "Tender Emails", "description": "Stored tender email drafts and send status."},
    "tender-email-documents": {"label": "Tender Email Documents", "description": "Join rows linking tender email drafts to attached tender documents."},
    "rag-documents": {"label": "RAG Documents", "description": "Reference documents loaded into retrieval workflows."},
    "rag-chunks": {"label": "RAG Chunks", "description": "Chunked retrieval records generated from RAG documents."},
    "llm-run-logs": {"label": "LLM Run Logs", "description": "Prompt, response, and status logs for extraction runs."},
    "settings": {"label": "Settings", "description": "Stored application settings and prompt configuration."},
    "chat-sessions": {"label": "Chat Sessions", "description": "Saved chat contexts per tender or page."},
    "chat-messages": {"label": "Chat Messages", "description": "Persisted user and assistant chat history."},
    "chat-actions": {"label": "Chat Actions", "description": "Proposed and confirmed AI actions awaiting execution or audit."},
    "chat-uploads": {"label": "Chat Uploads", "description": "Files uploaded into chat sessions and their extracted text."},
    "extraction-jobs": {"label": "Extraction Jobs", "description": "Queued, running, failed, and cancelled background extraction records."},
    "mailbox-messages": {"label": "Mailbox Messages", "description": "Synced Gmail inbox messages available for tender creation and linking."},
    "mailbox-attachments": {"label": "Mailbox Attachments", "description": "Stored mailbox attachment files and their extracted text."},
    "mailbox-tender-links": {"label": "Mailbox Tender Links", "description": "Links showing which mailbox messages were imported into which tenders."},
    "mailbox-deletion-requests": {"label": "Mailbox Deletion Requests", "description": "Queued Gmail deletion sync requests waiting to be applied remotely."},
    "mailbox-sync-jobs": {"label": "Mailbox Sync Jobs", "description": "Background Gmail mailbox sync jobs and their completion state."},
}


def _get_model(slug: str):
    model = ADMIN_MODELS.get(slug)
    if model is None:
        abort(404)
    return model


def _model_meta(slug: str) -> dict:
    default_model = _get_model(slug)
    return {
        "label": default_model.__name__,
        "description": "Browse, edit, and correct extracted records.",
        **ADMIN_MODEL_META.get(slug, {}),
    }


def _is_editable(column) -> bool:
    if column.primary_key:
        return False
    if column.name in {"created_at", "updated_at"}:
        return False
    return True


def _coerce_value(column, raw_value: str):
    if raw_value == "":
        return None
    python_type = getattr(column.type, "python_type", str)
    if python_type is int:
        return int(raw_value)
    if python_type is float:
        return float(raw_value)
    if python_type is Decimal:
        return Decimal(raw_value)
    if python_type is date:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    if python_type is datetime:
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(raw_value, fmt)
            except ValueError:
                continue
        raise ValueError(f"Use a valid datetime for {column.name}.")
    if python_type is bool:
        return raw_value.lower() in {"1", "true", "yes", "on"}
    return raw_value


@admin_bp.route("/")
def index():
    admin_catalog = []
    for slug, model in ADMIN_MODELS.items():
        admin_catalog.append(
            {
                "slug": slug,
                "model": model,
                "label": _model_meta(slug)["label"],
                "description": _model_meta(slug)["description"],
                "count": model.query.count(),
            }
        )
    return render_template("admin/index.html", admin_catalog=admin_catalog, chat_context={"page": "admin_index"})


@admin_bp.route("/jobs")
def job_dashboard():
    jobs = ExtractionJob.query.order_by(ExtractionJob.created_at.desc()).limit(50).all()
    for job in jobs:
        try:
            names = json.loads(job.selected_document_names_json or "[]")
        except json.JSONDecodeError:
            names = []
        job.document_names_text = ", ".join(names) if names else "-"
    worker_status = get_worker_status()
    stats = {
        "queued": ExtractionJob.query.filter_by(status="queued").count(),
        "running": ExtractionJob.query.filter(ExtractionJob.status.in_(["running", "cancelling"])).count(),
        "completed": ExtractionJob.query.filter_by(status="completed").count(),
        "failed": ExtractionJob.query.filter_by(status="failed").count(),
        "cancelled": ExtractionJob.query.filter_by(status="cancelled").count(),
    }
    return render_template(
        "admin/jobs.html",
        jobs=jobs,
        worker_status=worker_status,
        stats=stats,
        chat_context={"page": "admin_jobs"},
    )


@admin_bp.route("/jobs/worker/pause", methods=["POST"])
def pause_jobs_worker():
    pause_extraction_worker()
    flash("Background extraction worker paused. The current job may still finish first.", "warning")
    return redirect(url_for("admin.job_dashboard"))


@admin_bp.route("/jobs/worker/resume", methods=["POST"])
def resume_jobs_worker():
    ensure_extraction_worker(current_app)
    resume_extraction_worker()
    flash("Background extraction worker resumed.", "success")
    return redirect(url_for("admin.job_dashboard"))


@admin_bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel_job(job_id: int):
    job = ExtractionJob.query.get_or_404(job_id)
    success, message = cancel_extraction_job(job)
    db.session.commit()
    flash(message, "warning" if success else "secondary")
    return redirect(url_for("admin.job_dashboard"))


@admin_bp.route("/jobs/<int:job_id>/retry", methods=["POST"])
def retry_job(job_id: int):
    job = ExtractionJob.query.get_or_404(job_id)
    success, message = retry_extraction_job(job)
    db.session.commit()
    flash(message, "success" if success else "secondary")
    return redirect(url_for("admin.job_dashboard"))


@admin_bp.route("/<string:model_slug>")
def list_records(model_slug: str):
    model = _get_model(model_slug)
    records = model.query.limit(200).all()
    return render_template(
        "admin/list.html",
        model=model,
        model_label=_model_meta(model_slug)["label"],
        model_slug=model_slug,
        records=records,
        inspector=inspect(model),
        chat_context={"page": "admin_list", "table": model.__name__},
    )


@admin_bp.route("/<string:model_slug>/new", methods=["GET", "POST"])
def create_record(model_slug: str):
    model = _get_model(model_slug)
    mapper = inspect(model)
    record = model()
    if request.method == "POST":
        try:
            for column in mapper.columns:
                if _is_editable(column):
                    setattr(record, column.name, _coerce_value(column, request.form.get(column.name, "")))
            db.session.add(record)
            db.session.commit()
            flash(f"{model.__name__} created.", "success")
            return redirect(url_for("admin.view_record", model_slug=model_slug, record_id=record.id))
        except (ValueError, InvalidOperation) as exc:
            db.session.rollback()
            flash(f"Invalid value: {exc}", "danger")
    return render_template(
        "admin/form.html",
        model=model,
        model_label=_model_meta(model_slug)["label"],
        model_slug=model_slug,
        record=record,
        inspector=mapper,
        is_new=True,
        chat_context={"page": "admin_create_record", "table": model.__name__},
    )


@admin_bp.route("/<string:model_slug>/<int:record_id>")
def view_record(model_slug: str, record_id: int):
    model = _get_model(model_slug)
    record = model.query.get_or_404(record_id)
    return render_template(
        "admin/view.html",
        model=model,
        model_label=_model_meta(model_slug)["label"],
        model_slug=model_slug,
        record=record,
        inspector=inspect(model),
        chat_context={"page": "admin_view_record", "table": model.__name__, "selected_record_id": record.id},
    )


@admin_bp.route("/<string:model_slug>/<int:record_id>/edit", methods=["GET", "POST"])
def edit_record(model_slug: str, record_id: int):
    model = _get_model(model_slug)
    record = model.query.get_or_404(record_id)
    mapper = inspect(model)
    if request.method == "POST":
        try:
            for column in mapper.columns:
                if _is_editable(column):
                    setattr(record, column.name, _coerce_value(column, request.form.get(column.name, "")))
            db.session.commit()
            flash(f"{model.__name__} updated.", "success")
            return redirect(url_for("admin.view_record", model_slug=model_slug, record_id=record.id))
        except (ValueError, InvalidOperation) as exc:
            db.session.rollback()
            flash(f"Invalid value: {exc}", "danger")
    return render_template(
        "admin/form.html",
        model=model,
        model_label=_model_meta(model_slug)["label"],
        model_slug=model_slug,
        record=record,
        inspector=mapper,
        is_new=False,
        chat_context={"page": "admin_edit_record", "table": model.__name__, "selected_record_id": record.id},
    )


@admin_bp.route("/<string:model_slug>/<int:record_id>/delete", methods=["POST"])
def delete_record(model_slug: str, record_id: int):
    model = _get_model(model_slug)
    record = model.query.get_or_404(record_id)
    db.session.delete(record)
    db.session.commit()
    flash(f"{model.__name__} deleted.", "success")
    return redirect(url_for("admin.list_records", model_slug=model_slug))
