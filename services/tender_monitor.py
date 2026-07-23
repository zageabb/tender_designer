from __future__ import annotations

import threading
from datetime import datetime

from flask import Flask

from database import db
from models import Tender, TenderMonitorAlert
from services.mailbox_service import send_composed_message
from services.settings_service import get_setting, parse_email_recipients
from services.tender_health import ACTIVE_STATUSES, evaluate_tender_health


_monitor_lock = threading.Lock()
_monitor_thread: threading.Thread | None = None
_monitor_started = False
_monitor_resume_event = threading.Event()
_monitor_resume_event.set()
_monitor_scan_event = threading.Event()
_monitor_active = False
_last_scan_started_at: datetime | None = None
_last_scan_completed_at: datetime | None = None
_last_scan_summary = "Not run yet."


def _monitor_enabled() -> bool:
    return (get_setting("tender_monitor_enabled", "true") or "true").lower() in {"1", "true", "yes", "on"}


def _build_warning_subject(tender: Tender, signal) -> str:
    return f"[Tender Designer][{signal.label}] {tender.tender_number} - {tender.customer_name}"


def _build_warning_body(tender: Tender, signal) -> str:
    lines = [
        "# Tender Warning",
        "",
        f"- Tender Number: {tender.tender_number}",
        f"- Customer: {tender.customer_name}",
        f"- Status: {tender.status}",
        f"- Submission Date: {tender.submission_date.isoformat() if tender.submission_date else 'Not set'}",
        f"- Award Date: {tender.award_date.isoformat() if tender.award_date else 'Not set'}",
        f"- Current Signal: {signal.label}",
        "",
        "## Summary",
        "",
        signal.summary,
        "",
        "## Why This Was Flagged",
        "",
        signal.detail,
    ]
    if tender.notes:
        lines.extend(["", "## Tender Notes", "", tender.notes[:1200]])
    lines.extend(
        [
            "",
            "Open Tender Designer to review this tender and move it to the next workflow stage.",
        ]
    )
    return "\n".join(lines).strip()


def get_tender_monitor_status() -> dict[str, object]:
    return {
        "started": _monitor_started,
        "alive": bool(_monitor_thread and _monitor_thread.is_alive()),
        "paused": not _monitor_resume_event.is_set(),
        "active": _monitor_active,
        "enabled": _monitor_enabled(),
        "last_scan_started_at": _last_scan_started_at,
        "last_scan_completed_at": _last_scan_completed_at,
        "last_scan_summary": _last_scan_summary,
    }


def pause_tender_monitor() -> None:
    _monitor_resume_event.clear()


def resume_tender_monitor() -> None:
    _monitor_resume_event.set()


def request_tender_monitor_scan() -> None:
    _monitor_scan_event.set()


def run_tender_monitor_scan(app: Flask) -> dict[str, int]:
    global _monitor_active, _last_scan_started_at, _last_scan_completed_at, _last_scan_summary
    _monitor_active = True
    _last_scan_started_at = datetime.utcnow()
    result = {
        "checked": 0,
        "flagged": 0,
        "sent": 0,
        "skipped_existing": 0,
        "failed": 0,
    }
    with app.app_context():
        try:
            recipients = parse_email_recipients(get_setting("tender_warning_admin_emails", ""))
            active_tenders = (
                Tender.query.filter(Tender.status.in_(sorted(ACTIVE_STATUSES)))
                .order_by(Tender.submission_date.is_(None), Tender.submission_date.asc(), Tender.updated_at.desc())
                .all()
            )
            result["checked"] = len(active_tenders)
            for tender in active_tenders:
                signal = evaluate_tender_health(tender)
                if signal.monitor_level is None or signal.notification_key is None:
                    continue
                result["flagged"] += 1
                existing_alert = TenderMonitorAlert.query.filter_by(notification_key=signal.notification_key).first()
                if existing_alert is not None and existing_alert.status != "failed":
                    result["skipped_existing"] += 1
                    continue
                if not _monitor_enabled() or not recipients:
                    continue
                subject = _build_warning_subject(tender, signal)
                body = _build_warning_body(tender, signal)
                recipient_block = ", ".join(recipients)
                alert = existing_alert or TenderMonitorAlert(
                    tender=tender,
                    notification_key=signal.notification_key,
                )
                if existing_alert is None:
                    db.session.add(alert)
                    db.session.flush()
                alert.severity = signal.key
                alert.signal_label = signal.label
                alert.summary = signal.summary
                alert.recipient_emails = recipient_block
                alert.status = "queued"
                alert.last_error = None
                try:
                    mailbox_message = send_composed_message(
                        app.config["DATA_DIR"],
                        recipient_block,
                        subject,
                        body,
                        tender=tender,
                    )
                    alert.status = "sent"
                    alert.mailbox_message_id = mailbox_message.id
                    alert.sent_at = datetime.utcnow()
                    result["sent"] += 1
                except Exception as exc:
                    alert.status = "failed"
                    alert.last_error = str(exc)
                    result["failed"] += 1
                db.session.commit()
        finally:
            _monitor_active = False
            _last_scan_completed_at = datetime.utcnow()
            _last_scan_summary = (
                f"Checked {result['checked']} tender(s), flagged {result['flagged']}, "
                f"sent {result['sent']}, skipped {result['skipped_existing']}, failed {result['failed']}."
            )
    return result


def _worker_loop(app: Flask) -> None:
    while True:
        _monitor_resume_event.wait()
        _monitor_scan_event.wait(timeout=60)
        if not _monitor_resume_event.is_set():
            continue
        if not _monitor_scan_event.is_set():
            continue
        _monitor_scan_event.clear()
        run_tender_monitor_scan(app)


def start_tender_monitor_worker(app: Flask) -> None:
    global _monitor_started, _monitor_thread
    with _monitor_lock:
        if _monitor_thread and _monitor_thread.is_alive():
            return
        worker = threading.Thread(target=_worker_loop, args=(app,), name="tender-monitor-worker", daemon=True)
        worker.start()
        _monitor_thread = worker
        _monitor_started = True
