from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import event

from database import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Tender(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(255), nullable=False)
    tender_number = db.Column(db.String(255), nullable=False, unique=True)
    title = db.Column(db.String(255))
    status = db.Column(db.String(100), default="New", nullable=False)
    submission_date = db.Column(db.Date)
    submission_time = db.Column(db.String(50))
    award_date = db.Column(db.Date)
    tender_value = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    currency = db.Column(db.String(10), default="GBP", nullable=False)
    notes = db.Column(db.Text)

    documents = db.relationship("TenderDocument", back_populates="tender", cascade="all, delete-orphan")
    items = db.relationship("TenderItem", back_populates="tender", cascade="all, delete-orphan")
    rfqs = db.relationship("RFQ", back_populates="tender", cascade="all, delete-orphan")
    tender_emails = db.relationship("TenderEmail", back_populates="tender", cascade="all, delete-orphan")
    supplier_responses = db.relationship("SupplierResponse", back_populates="tender", cascade="all, delete-orphan")
    questions = db.relationship("TenderQuestion", back_populates="tender", cascade="all, delete-orphan")
    llm_runs = db.relationship("LLMRunLog", cascade="all, delete-orphan")
    extraction_jobs = db.relationship("ExtractionJob", back_populates="tender", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Tender {self.tender_number}>"


class TenderDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    extracted_text_path = db.Column(db.String(500))
    extracted_text = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed = db.Column(db.Boolean, default=False, nullable=False)
    processing_notes = db.Column(db.Text)

    tender = db.relationship("Tender", back_populates="documents")


class TenderItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    quantity_required = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    unit_price = db.Column(db.Numeric(12, 2))
    total_price = db.Column(db.Numeric(12, 2))
    status = db.Column(db.String(100), default="New", nullable=False)
    specification_summary = db.Column(db.Text)
    source_reference = db.Column(db.Text)

    tender = db.relationship("Tender", back_populates="items")
    sub_items = db.relationship("TenderSubItem", back_populates="tender_item", cascade="all, delete-orphan")
    specifications = db.relationship("Specification", back_populates="tender_item", cascade="all, delete-orphan")


class TenderSubItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_item_id = db.Column(db.Integer, db.ForeignKey("tender_item.id"), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    unit_price = db.Column(db.Numeric(12, 2))
    total_price = db.Column(db.Numeric(12, 2))
    supplier_name = db.Column(db.String(255))
    supplier_reference = db.Column(db.String(255))
    status = db.Column(db.String(100), default="New", nullable=False)
    notes = db.Column(db.Text)

    tender_item = db.relationship("TenderItem", back_populates="sub_items")
    specifications = db.relationship("Specification", back_populates="tender_sub_item")


class Specification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_item_id = db.Column(db.Integer, db.ForeignKey("tender_item.id"))
    tender_sub_item_id = db.Column(db.Integer, db.ForeignKey("tender_sub_item.id"))
    specification_text = db.Column(db.Text, nullable=False)
    source_document_id = db.Column(db.Integer, db.ForeignKey("tender_document.id"))
    source_reference = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    tender_item = db.relationship("TenderItem", back_populates="specifications")
    tender_sub_item = db.relationship("TenderSubItem", back_populates="specifications")


class RFQ(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"), nullable=False)
    supplier_name = db.Column(db.String(255))
    supplier_email = db.Column(db.String(255))
    subject = db.Column(db.String(255), nullable=False)
    introduction_text = db.Column(db.Text)
    status = db.Column(db.String(100), default="Draft", nullable=False)
    eml_file_path = db.Column(db.String(500))
    sent_at = db.Column(db.DateTime)
    response_received_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)

    tender = db.relationship("Tender", back_populates="rfqs")
    lines = db.relationship("RFQLine", back_populates="rfq", cascade="all, delete-orphan")


class RFQLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rfq_id = db.Column(db.Integer, db.ForeignKey("rfq.id"), nullable=False)
    tender_item_id = db.Column(db.Integer, db.ForeignKey("tender_item.id"))
    tender_sub_item_id = db.Column(db.Integer, db.ForeignKey("tender_sub_item.id"))
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    quoted_unit_price = db.Column(db.Numeric(12, 2))
    quoted_total_price = db.Column(db.Numeric(12, 2))
    currency = db.Column(db.String(10), default="GBP", nullable=False)
    lead_time = db.Column(db.String(255))
    supplier_part_number = db.Column(db.String(255))
    notes = db.Column(db.Text)

    rfq = db.relationship("RFQ", back_populates="lines")


class TenderEmail(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"), nullable=False)
    recipient_email = db.Column(db.String(255))
    subject = db.Column(db.String(255), nullable=False)
    body_text = db.Column(db.Text)
    status = db.Column(db.String(100), default="Draft", nullable=False)
    eml_file_path = db.Column(db.String(500))
    notes = db.Column(db.Text)

    tender = db.relationship("Tender", back_populates="tender_emails")
    documents = db.relationship("TenderEmailDocument", back_populates="tender_email", cascade="all, delete-orphan")


class TenderEmailDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_email_id = db.Column(db.Integer, db.ForeignKey("tender_email.id"), nullable=False)
    tender_document_id = db.Column(db.Integer, db.ForeignKey("tender_document.id"), nullable=False)

    tender_email = db.relationship("TenderEmail", back_populates="documents")
    tender_document = db.relationship("TenderDocument")


class SupplierResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rfq_id = db.Column(db.Integer, db.ForeignKey("rfq.id"))
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"), nullable=False)
    supplier_name = db.Column(db.String(255))
    supplier_email = db.Column(db.String(255))
    source_type = db.Column(db.String(50), nullable=False)
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    raw_text = db.Column(db.Text, nullable=False)
    parsed_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed = db.Column(db.Boolean, default=False, nullable=False)
    processing_notes = db.Column(db.Text)

    tender = db.relationship("Tender", back_populates="supplier_responses")


class TenderQuestion(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"), nullable=False)
    question_number = db.Column(db.String(100))
    section = db.Column(db.String(255))
    question_text = db.Column(db.Text, nullable=False)
    answer_text = db.Column(db.Text)
    suggested_answer = db.Column(db.Text)
    answer_status = db.Column(db.String(100), default="Unanswered", nullable=False)
    source_document_id = db.Column(db.Integer, db.ForeignKey("tender_document.id"))
    source_reference = db.Column(db.Text)

    tender = db.relationship("Tender", back_populates="questions")


class RAGDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    source_type = db.Column(db.String(100), nullable=False)
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    raw_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)

    chunks = db.relationship("RAGChunk", back_populates="rag_document", cascade="all, delete-orphan")


class RAGChunk(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rag_document_id = db.Column(db.Integer, db.ForeignKey("rag_document.id"), nullable=False)
    chunk_index = db.Column(db.Integer, nullable=False)
    chunk_text = db.Column(db.Text, nullable=False)
    embedding_id = db.Column(db.String(255))
    metadata_json = db.Column(db.Text)

    rag_document = db.relationship("RAGDocument", back_populates="chunks")


class LLMRunLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"))
    task_type = db.Column(db.String(100), nullable=False)
    model_name = db.Column(db.String(255), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text)
    success = db.Column(db.Boolean, default=False, nullable=False)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ExtractionJob(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"), nullable=False)
    task_type = db.Column(db.String(100), nullable=False)
    model_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default="queued", nullable=False)
    selected_document_ids_json = db.Column(db.Text, nullable=False, default="[]")
    selected_document_names_json = db.Column(db.Text, nullable=False, default="[]")
    summary_message = db.Column(db.Text)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    tender = db.relationship("Tender", back_populates="extraction_jobs")


class AppSetting(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.Text)


class ChatSession(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tender.id"))
    page_context_json = db.Column(db.Text)

    messages = db.relationship("ChatMessage", back_populates="chat_session", cascade="all, delete-orphan")
    actions = db.relationship("ChatAction", back_populates="chat_session", cascade="all, delete-orphan")
    uploads = db.relationship("ChatUpload", back_populates="chat_session", cascade="all, delete-orphan")


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_session_id = db.Column(db.Integer, db.ForeignKey("chat_session.id"), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    intermediate_steps_json = db.Column(db.Text)
    proposed_actions_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    chat_session = db.relationship("ChatSession", back_populates="messages")


class ChatAction(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_session_id = db.Column(db.Integer, db.ForeignKey("chat_session.id"), nullable=False)
    action_type = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="proposed")
    payload_json = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.Text)

    chat_session = db.relationship("ChatSession", back_populates="actions")


class ChatUpload(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_session_id = db.Column(db.Integer, db.ForeignKey("chat_session.id"), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    extracted_text = db.Column(db.Text)
    processing_notes = db.Column(db.Text)

    chat_session = db.relationship("ChatSession", back_populates="uploads")


def _money(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0.00")


def recalculate_item_totals(item: TenderItem) -> None:
    if item.sub_items:
        total = sum((_money(sub.total_price) for sub in item.sub_items), Decimal("0.00"))
        item.total_price = total
        qty = _money(item.quantity_required)
        item.unit_price = (total / qty) if qty else None
    elif item.unit_price is not None and item.quantity_required is not None:
        item.total_price = _money(item.unit_price) * _money(item.quantity_required)


def recalculate_tender_totals(tender: Tender) -> None:
    total = Decimal("0.00")
    for item in tender.items:
        recalculate_item_totals(item)
        total += _money(item.total_price)
    tender.tender_value = total


@event.listens_for(db.session, "before_flush")
def _before_flush(session, flush_context, instances) -> None:
    touched_tenders = set()
    for obj in session.new.union(session.dirty):
        if isinstance(obj, TenderSubItem):
            if obj.quantity is not None and obj.unit_price is not None:
                obj.total_price = _money(obj.quantity) * _money(obj.unit_price)
            if obj.tender_item and obj.tender_item.tender:
                touched_tenders.add(obj.tender_item.tender)
        elif isinstance(obj, TenderItem):
            if obj.tender:
                touched_tenders.add(obj.tender)
        elif isinstance(obj, RFQLine):
            if obj.quantity is not None and obj.quoted_unit_price is not None:
                obj.quoted_total_price = _money(obj.quantity) * _money(obj.quoted_unit_price)
    for tender in touched_tenders:
        recalculate_tender_totals(tender)
