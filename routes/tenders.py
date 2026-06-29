from __future__ import annotations

import json
import os
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from database import db
from models import ExtractionJob, LLMRunLog, Tender, TenderDocument, TenderItem, TenderQuestion, TenderSubItem, recalculate_tender_totals
from services.document_extraction import extract_text
from services.extraction_jobs import TASK_CONFIG, enqueue_extraction_job
from services.file_storage import ensure_tender_directories, save_tender_upload
from services.chat_service import add_chat_message, get_or_create_session
from services.settings_service import get_task_model


tenders_bp = Blueprint("tenders", __name__, url_prefix="/tenders")

TENDER_STATUS_OPTIONS = [
    "New",
    "Documents Uploaded",
    "Metadata Extracted",
    "Items Extracted",
    "Ready For Review",
    "RFQ Required",
    "Quoted",
    "Submitted",
    "Awarded",
    "Lost",
    "Cancelled",
]

ITEM_STATUS_OPTIONS = [
    "New",
    "Needs Review",
    "RFQ Required",
    "Quoted",
    "Ready To Order",
    "Ordered",
    "Complete",
    "On Hold",
    "Cancelled",
]


def _detail_redirect(tender_id: int, anchor: str | None = None):
    return redirect(
        url_for(
            "tenders.detail_tender",
            tender_id=tender_id,
            refreshed=int(time.time()),
            _anchor=anchor,
        )
    )


def _item_redirect(item_id: int, anchor: str | None = None):
    return redirect(
        url_for(
            "tenders.edit_item",
            item_id=item_id,
            refreshed=int(time.time()),
            _anchor=anchor,
        )
    )


@tenders_bp.route("/")
def list_tenders():
    tenders = (
        Tender.query.order_by(
            Tender.submission_date.is_(None),
            Tender.submission_date.asc(),
            Tender.updated_at.desc(),
        ).all()
    )
    return render_template("tenders/list.html", tenders=tenders, chat_context={"page": "tender_list"})


@tenders_bp.route("/new", methods=["GET", "POST"])
def create_tender():
    if request.method == "POST":
        tender = Tender(
            customer_name=request.form.get("customer_name", "").strip(),
            tender_number=request.form.get("tender_number", "").strip(),
            title=request.form.get("title", "").strip() or None,
            status=request.form.get("status", "New"),
            submission_date=_date_value(request.form.get("submission_date", "")),
            submission_time=request.form.get("submission_time", "").strip() or None,
            award_date=_date_value(request.form.get("award_date", "")),
            currency=request.form.get("currency", "GBP").strip() or "GBP",
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(tender)
        db.session.commit()
        ensure_tender_directories(current_app.config["DATA_DIR"], tender.id)
        flash("Tender created.", "success")
        return _detail_redirect(tender.id, anchor="top")
    return render_template(
        "tenders/form.html",
        tender=None,
        tender_status_options=TENDER_STATUS_OPTIONS,
        chat_context={"page": "tender_create"},
    )


@tenders_bp.route("/<int:tender_id>")
def detail_tender(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    extraction_runs = LLMRunLog.query.filter_by(tender_id=tender.id).order_by(LLMRunLog.created_at.desc()).limit(6).all()
    extraction_jobs = (
        ExtractionJob.query.filter_by(tender_id=tender.id)
        .order_by(ExtractionJob.created_at.desc())
        .limit(10)
        .all()
    )
    for job in extraction_jobs:
        try:
            job.document_names_text = ", ".join(json.loads(job.selected_document_names_json or "[]"))
        except json.JSONDecodeError:
            job.document_names_text = ""
    chat_context = {
        "page": "tender_detail",
        "tender_id": tender.id,
        "tender_number": tender.tender_number,
        "customer_name": tender.customer_name,
        "visible_item_ids": [item.id for item in tender.items],
        "visible_question_ids": [question.id for question in tender.questions],
        "visible_rfq_ids": [rfq.id for rfq in tender.rfqs],
    }
    return render_template(
        "tenders/detail.html",
        tender=tender,
        extraction_runs=extraction_runs,
        extraction_jobs=extraction_jobs,
        item_status_options=ITEM_STATUS_OPTIONS,
        chat_context=chat_context,
    )


def _decimal_value(raw: str, default: str = "0") -> Decimal:
    try:
        return Decimal(raw.strip() or default)
    except (InvalidOperation, AttributeError):
        return Decimal(default)


def _date_value(raw: str):
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        return None


@tenders_bp.route("/<int:tender_id>/edit", methods=["GET", "POST"])
def edit_tender(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    if request.method == "POST":
        tender.customer_name = request.form.get("customer_name", "").strip()
        tender.tender_number = request.form.get("tender_number", "").strip()
        tender.title = request.form.get("title", "").strip() or None
        tender.status = request.form.get("status", "New")
        tender.submission_date = _date_value(request.form.get("submission_date", ""))
        tender.submission_time = request.form.get("submission_time", "").strip() or None
        tender.award_date = _date_value(request.form.get("award_date", ""))
        tender.currency = request.form.get("currency", "GBP").strip() or "GBP"
        tender.notes = request.form.get("notes", "").strip() or None
        db.session.commit()
        flash("Tender updated.", "success")
        return _detail_redirect(tender.id, anchor="top")
    return render_template(
        "tenders/form.html",
        tender=tender,
        tender_status_options=TENDER_STATUS_OPTIONS,
        chat_context={"page": "tender_edit", "tender_id": tender.id},
    )


@tenders_bp.route("/<int:tender_id>/delete", methods=["POST"])
def delete_tender(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    tender_number = tender.tender_number
    db.session.delete(tender)
    db.session.commit()
    flash(f"Tender {tender_number} deleted.", "success")
    return redirect(url_for("tenders.list_tenders"))


@tenders_bp.route("/<int:tender_id>/items/add", methods=["POST"])
def add_item(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    item = TenderItem(
        tender=tender,
        description=request.form.get("description", "").strip() or "New item",
        quantity_required=_decimal_value(request.form.get("quantity_required", "0")),
        unit_price=_decimal_value(request.form.get("unit_price", "0")) if request.form.get("unit_price") else None,
        status=request.form.get("status", "New"),
        specification_summary=request.form.get("specification_summary", "").strip() or None,
    )
    db.session.add(item)
    db.session.commit()
    flash("Tender item added.", "success")
    return _detail_redirect(tender.id, anchor="items")


@tenders_bp.route("/items/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id: int):
    item = TenderItem.query.get_or_404(item_id)
    tender_id = item.tender_id
    description = item.description
    db.session.delete(item)
    db.session.commit()
    flash(f"Deleted item: {description}.", "success")
    return _detail_redirect(tender_id, anchor="items")


@tenders_bp.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
def edit_item(item_id: int):
    item = TenderItem.query.get_or_404(item_id)
    if request.method == "POST":
        item.description = request.form.get("description", "").strip() or item.description
        item.quantity_required = _decimal_value(request.form.get("quantity_required", str(item.quantity_required or 0)))
        item.unit_price = _decimal_value(request.form.get("unit_price", "0")) if request.form.get("unit_price", "").strip() else None
        item.status = request.form.get("status", item.status).strip() or item.status
        item.specification_summary = request.form.get("specification_summary", "").strip() or None
        item.source_reference = request.form.get("source_reference", "").strip() or None
        db.session.commit()
        flash("Tender item updated.", "success")
        return _detail_redirect(item.tender_id, anchor="items")
    return render_template(
        "tenders/item_form.html",
        item=item,
        item_status_options=ITEM_STATUS_OPTIONS,
        chat_context={
            "page": "tender_item_edit",
            "tender_id": item.tender_id,
            "selected_record_type": "TenderItem",
            "selected_record_id": item.id,
        },
    )


@tenders_bp.route("/items/<int:item_id>/sub-items/add", methods=["POST"])
def add_sub_item(item_id: int):
    item = TenderItem.query.get_or_404(item_id)
    sub_item = TenderSubItem(
        tender_item=item,
        description=request.form.get("description", "").strip() or "New sub-item",
        quantity=_decimal_value(request.form.get("quantity", "0")),
        unit_price=_decimal_value(request.form.get("unit_price", "0")) if request.form.get("unit_price") else None,
        status=request.form.get("status", "New"),
        notes=request.form.get("notes", "").strip() or None,
    )
    db.session.add(sub_item)
    db.session.commit()
    flash("Sub-item added.", "success")
    if request.form.get("return_to") == "item_edit":
        return _item_redirect(item.id, anchor="sub-items")
    return _detail_redirect(item.tender_id, anchor="items")


@tenders_bp.route("/sub-items/<int:sub_item_id>/edit", methods=["POST"])
def edit_sub_item(sub_item_id: int):
    sub_item = TenderSubItem.query.get_or_404(sub_item_id)
    sub_item.description = request.form.get("description", "").strip() or sub_item.description
    sub_item.quantity = _decimal_value(request.form.get("quantity", str(sub_item.quantity or 0)))
    sub_item.unit_price = _decimal_value(request.form.get("unit_price", "0")) if request.form.get("unit_price", "").strip() else None
    sub_item.status = request.form.get("status", sub_item.status).strip() or sub_item.status
    sub_item.supplier_name = request.form.get("supplier_name", "").strip() or None
    sub_item.supplier_reference = request.form.get("supplier_reference", "").strip() or None
    sub_item.notes = request.form.get("notes", "").strip() or None
    db.session.commit()
    flash("Sub-item updated.", "success")
    if request.form.get("return_to") == "item_edit":
        return _item_redirect(sub_item.tender_item_id, anchor="sub-items")
    return _detail_redirect(sub_item.tender_item.tender_id, anchor="items")


@tenders_bp.route("/sub-items/<int:sub_item_id>/delete", methods=["POST"])
def delete_sub_item(sub_item_id: int):
    sub_item = TenderSubItem.query.get_or_404(sub_item_id)
    tender_id = sub_item.tender_item.tender_id
    item_id = sub_item.tender_item_id
    description = sub_item.description
    db.session.delete(sub_item)
    db.session.commit()
    flash(f"Deleted sub-item: {description}.", "success")
    if request.form.get("return_to") == "item_edit":
        return _item_redirect(item_id, anchor="sub-items")
    return _detail_redirect(tender_id, anchor="items")


@tenders_bp.route("/<int:tender_id>/questions/add", methods=["POST"])
def add_question(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    question = TenderQuestion(
        tender=tender,
        question_number=request.form.get("question_number", "").strip() or None,
        section=request.form.get("section", "").strip() or None,
        question_text=request.form.get("question_text", "").strip() or "New question",
        answer_status=request.form.get("answer_status", "Unanswered"),
    )
    db.session.add(question)
    db.session.commit()
    flash("Question added.", "success")
    return _detail_redirect(tender.id, anchor="questions")


@tenders_bp.route("/questions/<int:question_id>/delete", methods=["POST"])
def delete_question(question_id: int):
    question = TenderQuestion.query.get_or_404(question_id)
    tender_id = question.tender_id
    label = question.question_number or "Question"
    db.session.delete(question)
    db.session.commit()
    flash(f"Deleted {label}.", "success")
    return _detail_redirect(tender_id, anchor="questions")


@tenders_bp.route("/questions/<int:question_id>/edit", methods=["GET", "POST"])
def edit_question(question_id: int):
    question = TenderQuestion.query.get_or_404(question_id)
    if request.method == "POST":
        question.question_number = request.form.get("question_number", "").strip() or None
        question.section = request.form.get("section", "").strip() or None
        question.question_text = request.form.get("question_text", "").strip() or question.question_text
        question.answer_text = request.form.get("answer_text", "").strip() or None
        question.suggested_answer = request.form.get("suggested_answer", "").strip() or None
        question.answer_status = request.form.get("answer_status", "Unanswered").strip() or "Unanswered"
        question.source_reference = request.form.get("source_reference", "").strip() or None
        db.session.commit()
        flash("Question updated.", "success")
        return _detail_redirect(question.tender_id, anchor="questions")
    return render_template(
        "tenders/question_form.html",
        question=question,
        chat_context={
            "page": "tender_question_edit",
            "tender_id": question.tender_id,
            "selected_record_type": "TenderQuestion",
            "selected_record_id": question.id,
        },
    )


@tenders_bp.route("/<int:tender_id>/recalculate", methods=["POST"])
def recalculate_tender(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    recalculate_tender_totals(tender)
    db.session.commit()
    flash("Tender totals recalculated.", "success")
    return _detail_redirect(tender.id, anchor="top")


@tenders_bp.route("/<int:tender_id>/upload", methods=["POST"])
def upload_document(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    uploads = request.files.getlist("documents")
    if not uploads or not uploads[0].filename:
        flash("Select at least one file to upload.", "warning")
        return redirect(url_for("tenders.detail_tender", tender_id=tender.id))
    for upload in uploads:
        extension = Path(upload.filename or "").suffix.lower()
        if extension not in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]:
            flash(f"Skipped unsupported file: {upload.filename}", "warning")
            continue
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
        if existing_document is not None:
            if existing_document.extracted_text_path and os.path.exists(existing_document.extracted_text_path):
                try:
                    os.remove(existing_document.extracted_text_path)
                except OSError:
                    pass
            existing_document.stored_filename = stored_name
            existing_document.file_path = str(saved_path)
            existing_document.file_type = extension.lstrip(".")
            existing_document.extracted_text_path = None
            existing_document.extracted_text = None
            existing_document.processed = False
            existing_document.processing_notes = "Re-uploaded and awaiting processing."
        else:
            db.session.add(
                TenderDocument(
                    tender=tender,
                    original_filename=original_name,
                    stored_filename=stored_name,
                    file_path=str(saved_path),
                    file_type=extension.lstrip("."),
                )
            )
    tender.status = "Documents Uploaded"
    db.session.commit()
    flash("Document upload complete.", "success")
    return _detail_redirect(tender.id, anchor="documents")


@tenders_bp.route("/documents/<int:document_id>/process", methods=["POST"])
def process_document(document_id: int):
    document = TenderDocument.query.get_or_404(document_id)
    text, error = extract_text(document.file_path)
    extracted_dir = current_app.config["DATA_DIR"] / "tenders" / str(document.tender_id) / "extracted_text"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    text_path = extracted_dir / f"{document.stored_filename}.txt"
    if text:
        text_path.write_text(text, encoding="utf-8")
        document.extracted_text = text
        document.extracted_text_path = str(text_path)
        document.processed = True
        document.processing_notes = "Processed successfully."
        flash(f"Processed {document.original_filename}.", "success")
    else:
        document.processed = False
        document.processing_notes = error
        flash(f"Could not process {document.original_filename}: {error}", "danger")
    db.session.commit()
    return _detail_redirect(document.tender_id, anchor="documents")


@tenders_bp.route("/documents/<int:document_id>/delete", methods=["POST"])
def delete_document(document_id: int):
    document = TenderDocument.query.get_or_404(document_id)
    tender_id = document.tender_id
    filename = document.original_filename
    for path_value in (document.file_path, document.extracted_text_path):
        if path_value and os.path.exists(path_value):
            try:
                os.remove(path_value)
            except OSError:
                pass
    db.session.delete(document)
    db.session.commit()
    flash(f"Deleted document: {filename}.", "success")
    return _detail_redirect(tender_id, anchor="documents")


@tenders_bp.route("/documents/<int:document_id>/text")
def view_document_text(document_id: int):
    document = TenderDocument.query.get_or_404(document_id)
    return render_template(
        "tenders/document_text.html",
        document=document,
        chat_context={
            "page": "tender_document_text",
            "tender_id": document.tender_id,
        },
    )


@tenders_bp.route("/documents/<int:document_id>/download")
def download_document(document_id: int):
    document = TenderDocument.query.get_or_404(document_id)
    path = Path(document.file_path or "")
    if not path.exists():
        flash("The uploaded document file is missing.", "danger")
        return _detail_redirect(document.tender_id, anchor="documents")
    return send_file(path, as_attachment=True, download_name=document.original_filename)


@tenders_bp.route("/<int:tender_id>/extract/<string:task_name>", methods=["POST"])
def run_extraction_task(tender_id: int, task_name: str):
    tender = Tender.query.get_or_404(tender_id)
    if task_name not in TASK_CONFIG:
        flash("Unknown extraction task.", "danger")
        return _detail_redirect(tender.id, anchor="runs")
    selected_document_ids = request.form.getlist("document_ids", type=int)
    if not selected_document_ids:
        flash("Select at least one document before running extraction.", "warning")
        return _detail_redirect(tender.id, anchor="documents")
    selected_documents = [document for document in tender.documents if document.id in set(selected_document_ids)]
    if not selected_documents:
        flash("The selected documents were not valid for this tender.", "danger")
        return _detail_redirect(tender.id, anchor="documents")
    page_context = {
        "page": "tender_detail",
        "tender_id": tender.id,
        "tender_number": tender.tender_number,
        "customer_name": tender.customer_name,
    }
    model_key = TASK_CONFIG[task_name]["setting_key"]
    model_name = get_task_model(model_key, current_app.config["LLM_MODELS"][model_key])
    job = ExtractionJob(
        tender_id=tender.id,
        task_type=task_name,
        model_name=model_name,
        status="queued",
        selected_document_ids_json=json.dumps([document.id for document in selected_documents]),
        selected_document_names_json=json.dumps([document.original_filename for document in selected_documents]),
        summary_message=f"{task_name.title()} extraction queued.",
    )
    db.session.add(job)
    db.session.commit()
    enqueue_extraction_job(job.id)
    try:
        chat_session = get_or_create_session(db, tender.id, page_context)
        add_chat_message(
            db,
            chat_session,
            "system",
            f"Queued {task_name} extraction for tender {tender.tender_number}.",
            intermediate_steps=[
                f"Job #{job.id}",
                f"Task: {task_name}",
                f"Model: {model_name}",
                f"Selected documents: {len(selected_documents)}",
                "Document names: " + ", ".join(document.original_filename for document in selected_documents[:5]),
                "The extraction will continue in the background while you navigate the app.",
            ],
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
    flash(f"{task_name.title()} extraction queued and running in the background.", "success")
    return _detail_redirect(tender.id, anchor="jobs")


@tenders_bp.route("/<int:tender_id>/jobs/status")
def extraction_job_status(tender_id: int):
    Tender.query.get_or_404(tender_id)
    jobs = (
        ExtractionJob.query.filter_by(tender_id=tender_id)
        .order_by(ExtractionJob.created_at.desc())
        .limit(10)
        .all()
    )
    payload = []
    for job in jobs:
        payload.append(
            {
                "id": job.id,
                "task_type": job.task_type,
                "model_name": job.model_name,
                "status": job.status,
                "summary_message": job.summary_message,
                "error_message": job.error_message,
                "selected_document_names": json.loads(job.selected_document_names_json or "[]"),
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
        )
    return jsonify({"jobs": payload})
