from __future__ import annotations

import email
import imaplib
import mimetypes
import re
import shutil
import smtplib
import time
import uuid
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from pathlib import Path

from database import db
from models import MailboxAttachment, MailboxDeletionRequest, MailboxMessage, MailboxTenderLink, Tender, TenderDocument
from sqlalchemy.exc import OperationalError
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


def _message_uid_from_identifier(provider_message_id: str | None) -> str | None:
    value = (provider_message_id or "").strip()
    if value.startswith("imap-uid:"):
        return value.split(":", 1)[1].strip() or None
    return None


def _connect_mailbox() -> imaplib.IMAP4_SSL:
    host = get_setting("mail_imap_host", "imap.gmail.com") or "imap.gmail.com"
    port = int(get_setting("mail_imap_port", "993") or "993")
    username = get_setting("mail_username", "")
    password = get_setting("mail_app_password", "")
    mailbox = imaplib.IMAP4_SSL(host, port)
    mailbox.login(username, password)
    return mailbox


def _close_mailbox(mailbox: imaplib.IMAP4_SSL) -> None:
    try:
        mailbox.close()
    except Exception:
        pass
    try:
        mailbox.logout()
    except Exception:
        pass


def _decode_folder_name(raw_folder: bytes | str) -> str:
    if isinstance(raw_folder, bytes):
        return raw_folder.decode("utf-8", errors="ignore")
    return raw_folder


def _parse_folder_line(raw_line: bytes | str) -> str:
    line = _decode_folder_name(raw_line).strip()
    if ' "/" ' in line:
        return line.split(' "/" ', 1)[1].strip('"')
    if ' "." ' in line:
        return line.split(' "." ', 1)[1].strip('"')
    return line.rsplit(" ", 1)[-1].strip('"')


def _trash_folder_name(folders: list[str]) -> str | None:
    lowered = {folder.lower(): folder for folder in folders}
    for candidate in ["[gmail]/trash", "[googlemail]/trash", "[gmail]/bin", "[googlemail]/bin", "trash", "deleted messages", "bin"]:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _all_mail_folder_name(folders: list[str]) -> str | None:
    lowered = {folder.lower(): folder for folder in folders}
    for candidate in ["[gmail]/all mail", "[googlemail]/all mail", "all mail"]:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _is_locked_database_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _commit_with_retry(max_attempts: int = 3, delay_seconds: float = 0.35) -> None:
    last_error: OperationalError | None = None
    for attempt in range(max_attempts):
        try:
            db.session.commit()
            return
        except OperationalError as exc:
            db.session.rollback()
            if not _is_locked_database_error(exc) or attempt == max_attempts - 1:
                raise
            last_error = exc
            time.sleep(delay_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error


def _queued_deletion_for(provider_message_id: str | None) -> MailboxDeletionRequest | None:
    value = (provider_message_id or "").strip()
    if not value:
        return None
    return MailboxDeletionRequest.query.filter_by(provider_message_id=value).first()


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
    deletion_request = _queued_deletion_for(identifier)
    if deletion_request is not None:
        deletion_request.mailbox_folder = deletion_request.mailbox_folder or folder
        deletion_request.subject = deletion_request.subject or ((parsed.get("subject") or "").strip() or "(No subject)")
        return None
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


def _candidate_message_locations(mailbox: imaplib.IMAP4_SSL, provider_message_id: str, preferred_folder: str | None = None) -> list[tuple[str, str]]:
    folders = list_mailbox_folders()
    search_folders: list[str] = []
    if preferred_folder:
        search_folders.append(preferred_folder)
    all_mail_folder = _all_mail_folder_name(folders)
    if all_mail_folder:
        search_folders.append(all_mail_folder)
    for folder in folders:
        if folder not in search_folders and not folder.endswith("]/Bin") and folder.lower() not in {"[gmail]", "[googlemail]"}:
            search_folders.append(folder)

    locations: list[tuple[str, str]] = []
    fallback_uid = _message_uid_from_identifier(provider_message_id)
    if fallback_uid and preferred_folder:
        return [(preferred_folder, fallback_uid)]

    for folder in search_folders:
        status, _ = mailbox.select(folder)
        if status != "OK":
            continue
        status, data = mailbox.uid("search", None, "HEADER", "Message-ID", f'"{provider_message_id}"')
        if status != "OK":
            continue
        for uid in (data[0] or b"").split():
            parsed_uid = uid.decode("utf-8", errors="ignore")
            candidate = (folder, parsed_uid)
            if parsed_uid and candidate not in locations:
                locations.append(candidate)
    return locations


def _apply_remote_delete(mailbox: imaplib.IMAP4_SSL, provider_message_id: str, preferred_folder: str | None = None) -> str:
    folders = list_mailbox_folders()
    trash_folder = _trash_folder_name(folders)
    locations = _candidate_message_locations(mailbox, provider_message_id, preferred_folder=preferred_folder)
    if not locations:
        return "message not found remotely"

    ordered_locations = sorted(
        locations,
        key=lambda value: (
            0 if value[0] == _all_mail_folder_name(folders) else 1,
            0 if value[0] == preferred_folder else 1,
            value[0].lower(),
        ),
    )
    for folder, uid in ordered_locations:
        status, _ = mailbox.select(folder)
        if status != "OK":
            continue
        if trash_folder and trash_folder != folder:
            move_status, _ = mailbox.uid("COPY", uid, trash_folder)
            if move_status == "OK":
                mailbox.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
                mailbox.expunge()
                return f"moved to {trash_folder}"
        store_status, _ = mailbox.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
        if store_status == "OK":
            mailbox.expunge()
            return "marked deleted on mailbox"
    return "remote delete could not be completed"


def process_pending_mailbox_deletions() -> dict[str, int]:
    pending = MailboxDeletionRequest.query.filter(MailboxDeletionRequest.status.in_(["queued", "failed"])).order_by(MailboxDeletionRequest.created_at.asc()).all()
    if not pending:
        return {"processed": 0, "failed": 0}
    mailbox = _connect_mailbox()
    processed = 0
    failed = 0
    try:
        for request in pending:
            try:
                remote_status = _apply_remote_delete(mailbox, request.provider_message_id, preferred_folder=request.mailbox_folder)
                if remote_status == "message not found remotely":
                    request.status = "synced"
                    request.last_error = None
                    request.processed_at = datetime.utcnow()
                    db.session.delete(request)
                    processed += 1
                elif remote_status in {"marked deleted on mailbox"} or remote_status.startswith("moved to "):
                    request.status = "synced"
                    request.last_error = None
                    request.processed_at = datetime.utcnow()
                    db.session.delete(request)
                    processed += 1
                else:
                    request.status = "failed"
                    request.last_error = remote_status
                    failed += 1
                _commit_with_retry()
            except Exception as exc:
                request.status = "failed"
                request.last_error = str(exc)
                failed += 1
                _commit_with_retry()
    finally:
        _close_mailbox(mailbox)
    return {"processed": processed, "failed": failed}


def sync_mailbox(data_dir: Path) -> dict[str, int]:
    if not mailbox_is_configured():
        raise ValueError("Mailbox settings are incomplete. Add the Gmail username and app password in Settings first.")
    folder = get_setting("mail_inbox_folder", "INBOX") or "INBOX"
    return sync_mailbox_folder(data_dir, folder)


def list_mailbox_folders() -> list[str]:
    if not mailbox_is_configured():
        return []
    mailbox = _connect_mailbox()
    try:
        status, data = mailbox.list()
        if status != "OK":
            raise ValueError("Could not read mailbox folders.")
        folders = [_parse_folder_line(line) for line in data or [] if line]
        folders = [folder for folder in folders if folder]
        return sorted(dict.fromkeys(folders), key=str.lower)
    finally:
        _close_mailbox(mailbox)


def sync_mailbox_folder(data_dir: Path, folder: str) -> dict[str, int]:
    if not mailbox_is_configured():
        raise ValueError("Mailbox settings are incomplete. Add the Gmail username and app password in Settings first.")
    limit = int(get_setting("mail_sync_limit", "20") or "20")
    created = 0
    updated = 0
    try:
        deletion_result = process_pending_mailbox_deletions()
    except Exception as exc:
        deletion_result = {"processed": 0, "failed": 1, "error": str(exc)}
    mailbox = _connect_mailbox()
    try:
        status, _ = mailbox.select(folder, readonly=True)
        if status != "OK":
            raise ValueError(f"Could not open mailbox folder {folder}.")
        status, data = mailbox.uid("search", None, "ALL")
        if status != "OK":
            raise ValueError("Could not search the mailbox.")
        uids = [value for value in (data[0] or b"").split() if value]
        normalized_folder = folder.strip().lower()
        if normalized_folder not in {"inbox"} and limit > 0:
            uids = uids[-limit:]
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
            synced_message = _sync_message_record(data_dir, uid, raw_bytes, folder)
            if synced_message is None:
                _commit_with_retry()
                continue
            if existing is None:
                created += 1
            else:
                updated += 1
            _commit_with_retry()
    finally:
        _close_mailbox(mailbox)
    return {
        "created": created,
        "updated": updated,
        "remote_deletions_processed": deletion_result["processed"],
        "remote_deletions_failed": deletion_result["failed"],
    }


def delete_mailbox_message(data_dir: Path, mailbox_message: MailboxMessage) -> str:
    if not mailbox_is_configured():
        raise ValueError("Mailbox settings are incomplete. Add the Gmail username and app password in Settings first.")
    folder = mailbox_message.mailbox_folder or (get_setting("mail_inbox_folder", "INBOX") or "INBOX")
    message_id = mailbox_message.provider_message_id or ""
    deletion_request = _queued_deletion_for(message_id)
    if deletion_request is None and message_id:
        deletion_request = MailboxDeletionRequest(
            provider_message_id=message_id,
            mailbox_folder=folder,
            subject=mailbox_message.subject,
            status="queued",
        )
        db.session.add(deletion_request)
    elif deletion_request is not None:
        deletion_request.mailbox_folder = folder
        deletion_request.subject = mailbox_message.subject or deletion_request.subject
        deletion_request.status = "queued"
    remote_status = "queued for Gmail deletion"
    mailbox = None
    try:
        mailbox = _connect_mailbox()
        if message_id:
            remote_status = _apply_remote_delete(mailbox, message_id, preferred_folder=folder)
    except Exception as exc:
        remote_status = f"queued for Gmail deletion ({exc})"
    finally:
        if mailbox is not None:
            _close_mailbox(mailbox)

    if deletion_request is not None:
        if remote_status == "message not found remotely" or remote_status == "marked deleted on mailbox" or remote_status.startswith("moved to "):
            db.session.delete(deletion_request)
        else:
            deletion_request.status = "queued"
            deletion_request.last_error = remote_status
            deletion_request.processed_at = None

    message_dir = _mailbox_root(data_dir) / str(mailbox_message.id)
    if message_dir.exists():
        shutil.rmtree(message_dir, ignore_errors=True)
    db.session.delete(mailbox_message)
    return remote_status


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
