from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import inspect

from database import db
from models import (
    AppSetting,
    ChatAction,
    ChatMessage,
    ChatSession,
    LLMRunLog,
    RAGChunk,
    RAGDocument,
    RFQ,
    RFQLine,
    Specification,
    SupplierResponse,
    Tender,
    TenderDocument,
    TenderItem,
    TenderQuestion,
    TenderSubItem,
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
    "rag-documents": RAGDocument,
    "rag-chunks": RAGChunk,
    "llm-run-logs": LLMRunLog,
    "settings": AppSetting,
    "chat-sessions": ChatSession,
    "chat-messages": ChatMessage,
    "chat-actions": ChatAction,
}


def _get_model(slug: str):
    model = ADMIN_MODELS.get(slug)
    if model is None:
        abort(404)
    return model


def _is_editable(column) -> bool:
    return not column.primary_key


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
    if python_type is bool:
        return raw_value.lower() in {"1", "true", "yes", "on"}
    return raw_value


@admin_bp.route("/")
def index():
    return render_template("admin/index.html", admin_models=ADMIN_MODELS, chat_context={"page": "admin_index"})


@admin_bp.route("/<string:model_slug>")
def list_records(model_slug: str):
    model = _get_model(model_slug)
    records = model.query.limit(200).all()
    return render_template(
        "admin/list.html",
        model=model,
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

