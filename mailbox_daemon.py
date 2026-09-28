from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta

os.environ["TENDER_DESIGNER_PROCESS_ROLE"] = "mailbox"

from app import app
from database import db
from models import MailboxSyncJob
from services.mailbox_jobs import queue_mailbox_sync_job
from services.settings_service import get_setting
from services.worker_lease import acquire_worker_lease


SERVICE_LEASE_NAME = "mailbox-sync-scheduler"
IDLE_CHECK_SECONDS = 5
logger = logging.getLogger(__name__)


def _auto_sync_enabled() -> bool:
    return (get_setting("mail_auto_sync_enabled", "true") or "true").lower() in {"1", "true", "yes", "on"}


def _sync_interval_minutes() -> int:
    raw_value = (get_setting("mail_auto_sync_interval_minutes", "10") or "10").strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 10


def _sync_already_pending() -> bool:
    return (
        MailboxSyncJob.query.filter(MailboxSyncJob.status.in_(["queued", "running"]))
        .limit(1)
        .first()
        is not None
    )


def _schedule_automatic_sync(now: datetime, next_sync_at: datetime) -> datetime:
    enabled = _auto_sync_enabled()
    interval = _sync_interval_minutes()
    if not enabled:
        return now
    if now < next_sync_at:
        return next_sync_at
    if _sync_already_pending():
        logger.info("automatic mailbox sync skipped because a job is already queued or running")
    else:
        job = queue_mailbox_sync_job(source_label="Automatic mailbox sync")
        logger.info("automatic mailbox sync scheduled job_id=%s", job.id)
    scheduled_at = now + timedelta(minutes=interval)
    logger.info("next automatic mailbox sync scheduled for %s", scheduled_at.isoformat())
    return scheduled_at


def run() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("mailbox service starting")
    if not acquire_worker_lease(app, SERVICE_LEASE_NAME):
        raise RuntimeError("Another Tender Designer mailbox scheduler is already active.")

    next_sync_at = datetime.utcnow()

    while True:
        try:
            with app.app_context():
                now = datetime.utcnow()
                next_sync_at = _schedule_automatic_sync(now, next_sync_at)
        except Exception:
            # Keep the daemon alive through transient SQLite/configuration
            # failures. Individual IMAP failures are recorded on their jobs by
            # the worker and likewise do not terminate this loop.
            logger.exception("mailbox scheduler iteration failed; retrying")
            with app.app_context():
                db.session.rollback()
                db.session.remove()

        threading.Event().wait(IDLE_CHECK_SECONDS)


if __name__ == "__main__":
    run()
