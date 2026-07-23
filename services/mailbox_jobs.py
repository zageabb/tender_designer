from __future__ import annotations

import queue
import threading
from datetime import datetime

from flask import Flask

from database import db
from models import MailboxSyncJob
from services.mailbox_service import sync_mailbox, sync_mailbox_folder
from services.settings_service import get_setting


_job_queue: queue.Queue[int] = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False
_worker_thread: threading.Thread | None = None
_active_job_id: int | None = None


def enqueue_mailbox_sync_job(job_id: int) -> None:
    _job_queue.put(job_id)


def queue_mailbox_sync_job(mailbox_folder: str | None = None, source_label: str = "Mailbox sync") -> MailboxSyncJob:
    label = (mailbox_folder or get_setting("mail_inbox_folder", "INBOX") or "INBOX").strip() or "INBOX"
    job = MailboxSyncJob(
        mailbox_folder=label,
        status="queued",
        summary_message=f"{source_label} queued for {label}.",
    )
    db.session.add(job)
    db.session.commit()
    enqueue_mailbox_sync_job(job.id)
    return job


def get_mailbox_worker_status() -> dict[str, object]:
    return {
        "started": _worker_started,
        "alive": bool(_worker_thread and _worker_thread.is_alive()),
        "queue_size": _job_queue.qsize(),
        "active_job_id": _active_job_id,
    }


def process_mailbox_sync_job(app: Flask, job_id: int) -> None:
    global _active_job_id
    with app.app_context():
        job = MailboxSyncJob.query.get(job_id)
        if job is None or job.status not in {"queued", "running"}:
            return
        try:
            job.status = "running"
            job.started_at = job.started_at or datetime.utcnow()
            job.error_message = None
            db.session.commit()
            _active_job_id = job.id

            folder = (job.mailbox_folder or "").strip()
            result = sync_mailbox_folder(app.config["DATA_DIR"], folder) if folder and folder.lower() != "default" else sync_mailbox(app.config["DATA_DIR"])
            processed = result.get("remote_deletions_processed", 0)
            failed = result.get("remote_deletions_failed", 0)
            deletion_summary = ""
            if processed or failed:
                deletion_summary = f" Remote deletions synced: {processed} processed, {failed} still pending."
            job.status = "completed"
            job.summary_message = (
                f"Mailbox sync completed for {folder or 'default folder'}. "
                f"Created {result['created']} message(s), updated {result['updated']}.{deletion_summary}"
            )
            job.completed_at = datetime.utcnow()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            job = MailboxSyncJob.query.get(job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.utcnow()
                db.session.commit()
        finally:
            _active_job_id = None


def _worker_loop(app: Flask) -> None:
    while True:
        job_id = _job_queue.get()
        try:
            process_mailbox_sync_job(app, job_id)
        finally:
            _job_queue.task_done()


def start_mailbox_sync_worker(app: Flask) -> None:
    global _worker_started, _worker_thread
    with _worker_lock:
        if _worker_started:
            return
        worker = threading.Thread(target=_worker_loop, args=(app,), name="mailbox-sync-worker", daemon=True)
        worker.start()
        _worker_thread = worker
        _worker_started = True

    with app.app_context():
        queued_jobs = (
            MailboxSyncJob.query.filter(MailboxSyncJob.status.in_(["queued", "running"]))
            .order_by(MailboxSyncJob.created_at.asc())
            .all()
        )
    for job in queued_jobs:
        enqueue_mailbox_sync_job(job.id)
