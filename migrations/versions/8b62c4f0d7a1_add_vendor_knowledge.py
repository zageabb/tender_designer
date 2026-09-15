"""Add versioned vendor knowledge tables

Revision ID: 8b62c4f0d7a1
Revises: 39d988e8d221
Create Date: 2026-09-15 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "8b62c4f0d7a1"
down_revision = "39d988e8d221"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vendor_knowledge_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_vendor_name", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("version_label", sa.String(length=255), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mailbox_message_id", sa.Integer(), nullable=True),
        sa.Column("mailbox_attachment_id", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("available_item_count", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["mailbox_attachment_id"], ["mailbox_attachment.id"]),
        sa.ForeignKeyConstraint(["mailbox_message_id"], ["mailbox_message.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vendor_knowledge_source_vendor_name", "vendor_knowledge_source", ["vendor_name"], unique=False)
    op.create_index("ix_vendor_knowledge_source_normalized_vendor_name", "vendor_knowledge_source", ["normalized_vendor_name"], unique=False)
    op.create_index("ix_vendor_knowledge_source_content_sha256", "vendor_knowledge_source", ["content_sha256"], unique=False)
    op.create_index("ix_vendor_knowledge_source_status", "vendor_knowledge_source", ["status"], unique=False)
    op.create_index("ix_vendor_source_vendor_status", "vendor_knowledge_source", ["normalized_vendor_name", "status"], unique=False)

    op.create_table(
        "vendor_knowledge_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_sheet", sa.String(length=255), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("source_category", sa.String(length=255), nullable=True),
        sa.Column("stock_type", sa.String(length=50), nullable=False),
        sa.Column("item_marker", sa.String(length=100), nullable=True),
        sa.Column("vendor_item_id", sa.String(length=100), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("part_number", sa.String(length=255), nullable=True),
        sa.Column("quantity_text", sa.String(length=100), nullable=True),
        sa.Column("quantity_minimum", sa.Integer(), nullable=True),
        sa.Column("quantity_exact", sa.Boolean(), nullable=False),
        sa.Column("price_qty_1_29", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("price_qty_30_plus", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("availability_status", sa.String(length=50), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["vendor_knowledge_source.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vendor_knowledge_item_source_id", "vendor_knowledge_item", ["source_id"], unique=False)
    op.create_index("ix_vendor_knowledge_item_stock_type", "vendor_knowledge_item", ["stock_type"], unique=False)
    op.create_index("ix_vendor_knowledge_item_part_number", "vendor_knowledge_item", ["part_number"], unique=False)
    op.create_index("ix_vendor_knowledge_item_availability_status", "vendor_knowledge_item", ["availability_status"], unique=False)
    op.create_index("ix_vendor_knowledge_item_is_available", "vendor_knowledge_item", ["is_available"], unique=False)
    op.create_index("ix_vendor_item_source_available", "vendor_knowledge_item", ["source_id", "is_available"], unique=False)


def downgrade():
    op.drop_index("ix_vendor_item_source_available", table_name="vendor_knowledge_item")
    op.drop_index("ix_vendor_knowledge_item_is_available", table_name="vendor_knowledge_item")
    op.drop_index("ix_vendor_knowledge_item_availability_status", table_name="vendor_knowledge_item")
    op.drop_index("ix_vendor_knowledge_item_part_number", table_name="vendor_knowledge_item")
    op.drop_index("ix_vendor_knowledge_item_stock_type", table_name="vendor_knowledge_item")
    op.drop_index("ix_vendor_knowledge_item_source_id", table_name="vendor_knowledge_item")
    op.drop_table("vendor_knowledge_item")
    op.drop_index("ix_vendor_source_vendor_status", table_name="vendor_knowledge_source")
    op.drop_index("ix_vendor_knowledge_source_status", table_name="vendor_knowledge_source")
    op.drop_index("ix_vendor_knowledge_source_content_sha256", table_name="vendor_knowledge_source")
    op.drop_index("ix_vendor_knowledge_source_normalized_vendor_name", table_name="vendor_knowledge_source")
    op.drop_index("ix_vendor_knowledge_source_vendor_name", table_name="vendor_knowledge_source")
    op.drop_table("vendor_knowledge_source")
