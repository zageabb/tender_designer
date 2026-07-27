from __future__ import annotations

from sqlalchemy import inspect, text

from database import db


def apply_schema_migrations() -> None:
    """Apply small additive schema upgrades for existing installations."""
    inspector = inspect(db.engine)
    if "tender" not in inspector.get_table_names():
        return
    tender_columns = {column["name"] for column in inspector.get_columns("tender")}
    if "submission_type" not in tender_columns:
        db.session.execute(text("ALTER TABLE tender ADD COLUMN submission_type VARCHAR(50)"))
        db.session.commit()
