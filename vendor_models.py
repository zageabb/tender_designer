from __future__ import annotations

from datetime import datetime

from database import db


class VendorKnowledgeSource(db.Model):
    """One immutable vendor source document/version.

    A newer source archives older versions for the same vendor rather than
    deleting them. Items are therefore historically traceable to the exact
    source document that supplied the commercial evidence.
    """

    __tablename__ = "vendor_knowledge_source"

    id = db.Column(db.Integer, primary_key=True)
    vendor_name = db.Column(db.String(255), nullable=False, index=True)
    normalized_vendor_name = db.Column(db.String(255), nullable=False, index=True)
    source_name = db.Column(db.String(500))
    source_date = db.Column(db.Date)
    version_label = db.Column(db.String(255))
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    content_sha256 = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(32), default="active", nullable=False, index=True)
    mailbox_message_id = db.Column(db.Integer, db.ForeignKey("mailbox_message.id"))
    mailbox_attachment_id = db.Column(db.Integer, db.ForeignKey("mailbox_attachment.id"))
    row_count = db.Column(db.Integer, default=0, nullable=False)
    item_count = db.Column(db.Integer, default=0, nullable=False)
    available_item_count = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.Text)
    archived_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    items = db.relationship(
        "VendorKnowledgeItem",
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="VendorKnowledgeItem.id",
    )

    __table_args__ = (
        db.Index("ix_vendor_source_vendor_status", "normalized_vendor_name", "status"),
    )


class VendorKnowledgeItem(db.Model):
    """Normalised commercial line from a vendor source document."""

    __tablename__ = "vendor_knowledge_item"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("vendor_knowledge_source.id"), nullable=False, index=True)
    source_sheet = db.Column(db.String(255))
    source_row = db.Column(db.Integer)
    source_category = db.Column(db.String(255))
    stock_type = db.Column(db.String(50), default="new", nullable=False, index=True)
    item_marker = db.Column(db.String(100))
    vendor_item_id = db.Column(db.String(100))
    description = db.Column(db.String(2000), nullable=False)
    part_number = db.Column(db.String(255), index=True)
    quantity_text = db.Column(db.String(100))
    quantity_minimum = db.Column(db.Integer)
    quantity_exact = db.Column(db.Boolean, default=True, nullable=False)
    price_qty_1_29 = db.Column(db.Numeric(14, 4))
    price_qty_30_plus = db.Column(db.Numeric(14, 4))
    unit_price = db.Column(db.Numeric(14, 4))
    currency = db.Column(db.String(10), default="GBP", nullable=False)
    condition = db.Column(db.Text)
    availability_status = db.Column(db.String(50), default="unknown", nullable=False, index=True)
    is_available = db.Column(db.Boolean, default=False, nullable=False, index=True)
    search_text = db.Column(db.Text, nullable=False)
    raw_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    source = db.relationship("VendorKnowledgeSource", back_populates="items")

    __table_args__ = (
        db.Index("ix_vendor_item_source_available", "source_id", "is_available"),
    )
