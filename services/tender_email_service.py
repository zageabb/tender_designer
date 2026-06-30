from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from pathlib import Path

from models import Tender, TenderDocument, TenderEmail, TenderEmailDocument
from services.file_storage import ensure_tender_directories
from services.prompt_service import render_prompt
from services.settings_service import get_setting


def _format_optional_date(value) -> str:
    return value.isoformat() if value else "Not set"


def _clean_rendered_block(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def _selected_documents_list(documents: list[TenderDocument]) -> str:
    return "\n".join(f"- {document.original_filename}" for document in documents) or "- No documents selected"


def build_tender_email_defaults(
    tender: Tender,
    documents: list[TenderDocument],
    recipient_email: str = "",
) -> tuple[str, str]:
    signature = get_setting("default_email_signature", "") or ""
    tender_reference = tender.tender_number
    if tender.title:
        tender_reference = f"{tender_reference} - {tender.title}"
    subject = f"Selected Tender Files - {tender_reference}"
    body = render_prompt(
        "tender_email_body",
        recipient_email=recipient_email,
        tender_number=tender.tender_number or "",
        tender_title=tender.title or "",
        tender_reference=tender_reference,
        customer_name=tender.customer_name or "",
        tender_status=tender.status or "",
        submission_date=_format_optional_date(tender.submission_date),
        selected_documents_list=_selected_documents_list(documents),
        email_signature=signature,
    )
    return subject, _clean_rendered_block(body)


def create_tender_email_draft(
    db,
    data_dir: Path,
    tender: Tender,
    documents: list[TenderDocument],
    recipient_email: str,
    subject: str,
    body_text: str,
) -> TenderEmail:
    for document in documents:
        path = Path(document.file_path or "")
        if not path.exists():
            raise FileNotFoundError(f"The file {document.original_filename} is missing and could not be attached.")
    tender_email = TenderEmail(
        tender=tender,
        recipient_email=recipient_email or None,
        subject=subject,
        body_text=body_text,
        status="Draft",
    )
    for document in documents:
        tender_email.documents.append(TenderEmailDocument(tender_document=document))
    db.session.add(tender_email)
    db.session.flush()
    email_path = write_tender_email_eml(data_dir, tender, tender_email, documents)
    tender_email.eml_file_path = str(email_path)
    return tender_email


def write_tender_email_eml(
    data_dir: Path,
    tender: Tender,
    tender_email: TenderEmail,
    documents: list[TenderDocument],
) -> Path:
    tender_dir = ensure_tender_directories(data_dir, tender.id)
    email_dir = tender_dir / "tender_emails"
    email_dir.mkdir(parents=True, exist_ok=True)
    message = EmailMessage()
    message["Subject"] = tender_email.subject
    if tender_email.recipient_email:
        message["To"] = tender_email.recipient_email
    message["From"] = "noreply@tenderdesigner.local"
    message.set_content(tender_email.body_text or "")
    for document in documents:
        path = Path(document.file_path)
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=document.original_filename,
        )
    destination = email_dir / f"tender_email_{tender_email.id}.eml"
    destination.write_bytes(message.as_bytes())
    return destination
