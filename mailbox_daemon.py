from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta

os.environ["TENDER_DESIGNER_PROCESS_ROLE"] = "mailbox"

from app import app
from models import MailboxSyncJob
from services.mailbox_jobs import queue_mailbox_sync_job
from services.settings_service import get_setting
from services.worker_lease import acquire_worker_lease


SERVICE_LEASE_NAME = "mailbox-sync-scheduler"
IDLE_CHECK_SECONDS = 5


def _auto_sync_enabled() -> bool:
    return (get_setting("mail_auto_sync_enabled", "true") or "true").lower() in {"1", "true", "yes", "on"}


def _sync_interval_minutes() -> int:
    raw_value = get_setting("mail_auto_sync_interval_minutes", "10") or "10"
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


def run() -> None:
    if not acquire_worker_lease(app, SERVICE_LEASE_NAME):
        raise RuntimeError("Another Tender Designer mailbox scheduler is already active.")

    next_sync_at = datetime.utcnow()

    while True:
        with app.app_context():
            enabled = _auto_sync_enabled()
            interval = _sync_interval_minutes()

            if enabled and datetime.utcnow() >= next_sync_at:
                if not _sync_already_pending():
                    queue_mailbox_sync_job(source_label="Automatic mailbox sync")
                next_sync_at = datetime.utcnow() + timedelta(minutes=interval)
            elif not enabled:
                next_sync_at = datetime.utcnow()

        threading.Event().wait(IDLE_CHECK_SECONDS)


if __name__ == "__main__":
    run()
