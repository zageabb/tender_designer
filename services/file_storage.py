from __future__ import annotations

import uuid
from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


TENDER_SUBDIRECTORIES = (
    "original_documents",
    "extracted_text",
    "rfqs",
    "tender_emails",
    "supplier_responses",
    "exports",
)


def ensure_tender_directories(base_data_dir: Path, tender_id: int) -> Path:
    tender_dir = base_data_dir / "tenders" / str(tender_id)
    for directory in TENDER_SUBDIRECTORIES:
        (tender_dir / directory).mkdir(parents=True, exist_ok=True)
    return tender_dir


def save_tender_upload(
    base_data_dir: Path,
    tender_id: int,
    upload: FileStorage,
    stored_name: str | None = None,
) -> tuple[str, str, Path]:
    tender_dir = ensure_tender_directories(base_data_dir, tender_id)
    original_name = secure_filename(upload.filename or "upload")
    extension = Path(original_name).suffix.lower()
    stored_name = stored_name or f"{uuid.uuid4().hex}{extension}"
    destination = tender_dir / "original_documents" / stored_name
    upload.save(destination)
    return original_name, stored_name, destination


def save_chat_upload(base_data_dir: Path, session_id: int, upload: FileStorage) -> tuple[str, str, Path]:
    chat_dir = base_data_dir / "chat_uploads" / str(session_id)
    chat_dir.mkdir(parents=True, exist_ok=True)
    original_name = secure_filename(upload.filename or "upload")
    extension = Path(original_name).suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = chat_dir / stored_name
    upload.save(destination)
    return original_name, stored_name, destination
