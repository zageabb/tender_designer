from __future__ import annotations

import email
import imaplib
import mimetypes
import re
import smtplib
import uuid
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from pathlib import Path

from database import db
from models import MailboxAttachment, MailboxMessage, MailboxTenderLink, Tender, TenderDocument
from services.document_extraction import extract_text
from services.file_storage import ensure_tender_directories, save_tender_bytes
from services.settings_service import get_setting


def mailbox_is_configured() -> bool:
    return bool(get_setting("mail_username")) and bool(get_setting("mail_app_password"))


def _mailbox_root(data_dir: Path) -> Path:
    root = data_dir / "mailbox"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _message_storage_dir(data_dir: Path, message: MailboxMessage) -> Path:
    directory = _mailbox_root(data_dir) / str(message.id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sanitize_text(value: str | None) -> str:
    return (value or "").replace("\r\n", "\n").strip()


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", value)
    cleaned = re.sub(r"(?is)<br\\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p>", "\n\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def _message_body(message: email.message.EmailMessage) -> str:
    plain_part = message.get_body(preferencelist=("plain",))
    if plain_part is not None:
        return _sanitize_text(plain_part.get_content())
    html_part = message.get_body(preferencelist=("html",))
    if html_part is not None:
        return _strip_html(html_part.get_content())
    if message.is_multipart():
        parts: list[str] = []
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                parts.append(_sanitize_text(part.get_content()))
        return "\n\n".join(part for part in parts if part).strip()
    try:
        return _sanitize_text(message.get_content())
    except Exception:
        return ""


def _comma_joined_addresses(header_value: str | None) -> str:
    addresses = [address for _, address in getaddresses([header_value or ""]) if address]
    return ", ".join(addresses)


def _message_identifier(message: email.message.EmailMessage, uid: str) -> str:
    message_id = (message.get("message-id") or "").strip()
    return message_id or f"imap-uid:{uid}"


def _save_message_payload(data_dir: Path, mailbox_message: MailboxMessage, raw_bytes: bytes) -> None:
    message_dir = _message_storage_dir(data_dir, mailbox_message)
    raw_path = message_dir / "message.eml"
    raw_path.write_bytes(raw_bytes)
    mailbox_message.raw_eml_path = str(raw_path)


def _save_attachment(data_dir: Path, mailbox_message: MailboxMessage, part) -> None:
    filename = part.get_filename()
    if not filename:
        return
    payload = part.get_payload(decode=True) or b""
    message_dir = _message_storage_dir(data_dir, mailbox_message) / "attachments"
    message_dir.mkdir(parents=True, exist_ok=True)
    original_name = Path(filename).name
    extension = Path(original_name).suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = message_dir / stored_name
    destination.write_bytes(payload)
    extracted_text, error = extract_text(destination)
    mailbox_message.attachments.append(
        MailboxAttachment(
            original_filename=original_name,
            stored_filename=stored_name,
            file_path=str(destination),
            file_type=extension.lstrip("."),
            extracted_text=extracted_text or None,
            processing_notes=error,
        )
    )


def _sync_message_record(data_dir: Path, uid: str, raw_bytes: bytes, folder: str) -> MailboxMessage:
    parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    identifier = _message_identifier(parsed, uid)
    sender_name, sender_email = parseaddr(parsed.get("from", ""))
    mailbox_message = MailboxMessage.query.filter_by(provider_message_id=identifier).first()
    is_new = mailbox_message is None
    if mailbox_message is None:
        mailbox_message = MailboxMessage(provider_message_id=identifier)
        db.session.add(mailbox_message)
        db.session.flush()
    mailbox_message.mailbox_folder = folder
    mailbox_message.subject = (parsed.get("subject") or "").strip() or "(No subject)"
    mailbox_message.sender_name = sender_name or None
    mailbox_message.sender_email = sender_email or None
    mailbox_message.recipient_emails = _comma_joined_addresses(parsed.get("to"))
    mailbox_message.cc_emails = _comma_joined_addresses(parsed.get("cc"))
    mailbox_message.received_at = parsed.get("date").datetime if parsed.get("date") and parsed.get("date").datetime else mailbox_message.received_at
    mailbox_message.body_text = _message_body(parsed)
    mailbox_message.snippet = (mailbox_message.body_text or "")[:240] or mailbox_message.subject
    mailbox_message.is_read = "Seen" in (parsed.get("flags") or "")
    _save_message_payload(data_dir, mailbox_message, raw_bytes)
    if is_new:
        for part in parsed.iter_attachments():
            _save_attachment(data_dir, mailbox_message, part)
    return mailbox_message


def sync_mailbox(data_dir: Path) -> dict[str, int]:
    if not mailbox_is_configured():
        raise ValueError("Mailbox settings are incomplete. Add the Gmail username and app password in Settings first.")
    host = get_setting("mail_imap_host", "imap.gmail.com") or "imap.gmail.com"
    port = int(get_setting("mail_imap_port", "993") or "993")
    username = get_setting("mail_username", "")
    password = get_setting("mail_app_password", "")
    folder = get_setting("mail_inbox_folder", "INBOX") or "INBOX"
    limit = int(get_setting("mail_sync_limit", "20") or "20")
    created = 0
    updated = 0
    mailbox = imaplib.IMAP4_SSL(host, port)
    try:
        mailbox.login(username, password)
        status, _ = mailbox.select(folder, readonly=True)
        if status != "OK":
            raise ValueError(f"Could not open mailbox folder {folder}.")
        status, data = mailbox.uid("search", None, "ALL")
        if status != "OK":
            raise ValueError("Could not search the mailbox.")
        uids = [value for value in (data[0] or b"").split() if value][-limit:]
        for uid_bytes in reversed(uids):
            uid = uid_bytes.decode("utf-8", errors="ignore")
            status, fetch_data = mailbox.uid("fetch", uid_bytes, "(RFC822)")
            if status != "OK":
                continue
            raw_bytes = b""
            for part in fetch_data:
                if isinstance(part, tuple):
                    raw_bytes = part[1]
                    break
            if not raw_bytes:
                continue
            existing = MailboxMessage.query.filter_by(provider_message_id=_message_identifier(BytesParser(policy=policy.default).parsebytes(raw_bytes), uid)).first()
            _sync_message_record(data_dir, uid, raw_bytes, folder)
            if existing is None:
                created += 1
            else:
                updated += 1
        db.session.commit()
    finally:
        try:
            mailbox.close()
        except Exception:
            pass
        try:
            mailbox.logout()
        except Exception:
            pass
    return {"created": created, "updated": updated}


def send_eml_file(file_path: str | Path) -> None:
    if not mailbox_is_configured():
        raise ValueError("Mailbox settings are incomplete. Add the Gmail username and app password in Settings first.")
    path = Path(file_path)
    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    _send_message(message)


def _send_message(message: EmailMessage) -> None:
    host = get_setting("mail_smtp_host", "smtp.gmail.com") or "smtp.gmail.com"
    port = int(get_setting("mail_smtp_port", "587") or "587")
    username = get_setting("mail_username", "")
    password = get_setting("mail_app_password", "")
    account_email = get_setting("mail_account_email", username) or username
    from_name = get_setting("mail_from_name", "Tender Designer") or "Tender Designer"
    use_starttls = (get_setting("mail_use_starttls", "true") or "true").lower() in {"1", "true", "yes", "on"}
    if not message.get("From"):
        message["From"] = f"{from_name} <{account_email}>"
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        if use_starttls:
            server.starttls()
            server.ehlo()
        server.login(username, password)
        server.send_message(message)


def _build_body_document_name(mailbox_message: MailboxMessage) -> str:
    timestamp = mailbox_message.received_at.strftime("%Y%m%d%H%M%S") if mailbox_message.received_at else datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"email_{timestamp}_body.md"


def _mailbox_message_body_markdown(mailbox_message: MailboxMessage) -> str:
    lines = [
        "# Email",
        "",
        f"- Subject: {mailbox_message.subject or ''}",
        f"- From: {mailbox_message.sender_email or ''}",
        f"- To: {mailbox_message.recipient_emails or ''}",
    ]
    if mailbox_message.cc_emails:
        lines.append(f"- Cc: {mailbox_message.cc_emails}")
    lines.extend(["", "## Body", "", mailbox_message.body_text or ""])
    return "\n".join(lines).strip()


def _create_body_document(data_dir: Path, tender: Tender, mailbox_message: MailboxMessage) -> None:
    content = _mailbox_message_body_markdown(mailbox_message).encode("utf-8")
    original_name, stored_name, saved_path = save_tender_bytes(
        data_dir,
        tender.id,
        _build_body_document_name(mailbox_message),
        content,
    )
    db.session.add(
        TenderDocument(
            tender=tender,
            original_filename=original_name,
            stored_filename=stored_name,
            file_path=str(saved_path),
            file_type="md",
            extracted_text=content.decode("utf-8"),
            processed=True,
            processing_notes="Created from mailbox email body.",
        )
    )


def _import_mailbox_attachments(data_dir: Path, tender: Tender, mailbox_message: MailboxMessage) -> None:
    for attachment in mailbox_message.attachments:
        path = Path(attachment.file_path or "")
        if not path.exists():
            continue
        original_name, stored_name, saved_path = save_tender_bytes(
            data_dir,
            tender.id,
            attachment.original_filename,
            path.read_bytes(),
        )
        extracted_text, error = extract_text(saved_path)
        db.session.add(
            TenderDocument(
                tender=tender,
                original_filename=original_name,
                stored_filename=stored_name,
                file_path=str(saved_path),
                file_type=attachment.file_type,
                extracted_text=extracted_text or None,
                processed=bool(extracted_text),
                processing_notes=error or "Imported from mailbox attachment.",
            )
        )


def import_mailbox_message_to_tender(data_dir: Path, mailbox_message: MailboxMessage, tender: Tender) -> MailboxTenderLink:
    existing_link = MailboxTenderLink.query.filter_by(mailbox_message_id=mailbox_message.id, tender_id=tender.id).first()
    if existing_link is not None:
        return existing_link
    ensure_tender_directories(data_dir, tender.id)
    tender.notes = "\n\n".join(part for part in [tender.notes, mailbox_message.body_text] if part).strip() or None
    _create_body_document(data_dir, tender, mailbox_message)
    _import_mailbox_attachments(data_dir, tender, mailbox_message)
    link = MailboxTenderLink(mailbox_message=mailbox_message, tender=tender, notes="Imported from mailbox.")
    db.session.add(link)
    return link


def create_tender_from_mailbox_message(data_dir: Path, mailbox_message: MailboxMessage) -> Tender:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    sender_label = mailbox_message.sender_name or mailbox_message.sender_email or "Mailbox Sender"
    tender = Tender(
        customer_name=sender_label[:255],
        tender_number=f"AUTO-EMAIL-{timestamp}",
        title=(mailbox_message.subject or "Mailbox Email")[:255],
        status="Documents Uploaded",
    )
    db.session.add(tender)
    db.session.flush()
    import_mailbox_message_to_tender(data_dir, mailbox_message, tender)
    return tender
