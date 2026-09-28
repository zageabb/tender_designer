from __future__ import annotations

import os
import socket
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


os.environ["TENDER_DESIGNER_MIGRATION_MODE"] = "1"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret"

import mailbox_daemon  # noqa: E402
from app import create_app  # noqa: E402
from database import db  # noqa: E402
from models import AppSetting, MailboxSyncJob, WorkerLease  # noqa: E402
from services import mailbox_jobs  # noqa: E402


class AsyncMailboxServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{Path(self.temp_dir.name) / 'test.db'}",
                "DATA_DIR": Path(self.temp_dir.name) / "data",
                "ADMIN_USERNAME": "admin",
                "ADMIN_PASSWORD": "test-password",
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
            }
        )
        with self.app.app_context():
            db.drop_all()
            db.create_all()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = "admin"

    def tearDown(self) -> None:
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def _set_setting(self, key: str, value: str) -> None:
        setting = AppSetting.query.filter_by(key=key).first()
        if setting is None:
            setting = AppSetting(key=key)
            db.session.add(setting)
        setting.value = value
        db.session.commit()

    def test_process_roles_start_only_their_own_workers(self) -> None:
        original_migration_mode = os.environ.pop("TENDER_DESIGNER_MIGRATION_MODE", None)
        try:
            with patch.dict(os.environ, {"TENDER_DESIGNER_PROCESS_ROLE": "web"}), patch(
                "app.start_extraction_worker"
            ) as extraction, patch("app.start_tender_monitor_worker") as monitor, patch(
                "app.start_automation_scheduler"
            ) as scheduler, patch("app.start_mailbox_sync_worker") as mailbox:
                create_app(self.app.config)
                extraction.assert_called_once()
                monitor.assert_called_once()
                scheduler.assert_called_once()
                mailbox.assert_not_called()

            with patch.dict(os.environ, {"TENDER_DESIGNER_PROCESS_ROLE": "mailbox"}), patch(
                "app.start_extraction_worker"
            ) as extraction, patch("app.start_tender_monitor_worker") as monitor, patch(
                "app.start_automation_scheduler"
            ) as scheduler, patch("app.start_mailbox_sync_worker") as mailbox:
                create_app(self.app.config)
                extraction.assert_not_called()
                monitor.assert_not_called()
                scheduler.assert_not_called()
                mailbox.assert_called_once()
        finally:
            if original_migration_mode is not None:
                os.environ["TENDER_DESIGNER_MIGRATION_MODE"] = original_migration_mode
            else:
                os.environ.pop("TENDER_DESIGNER_MIGRATION_MODE", None)

    def test_manual_sync_only_creates_database_job(self) -> None:
        with patch("services.mailbox_jobs.ensure_mailbox_sync_worker") as start_worker, patch(
            "services.mailbox_jobs.process_mailbox_sync_job"
        ) as process_job:
            response = self.client.post("/mailbox/sync", data={"folder": "INBOX"})
        self.assertEqual(response.status_code, 302)
        start_worker.assert_not_called()
        process_job.assert_not_called()
        with self.app.app_context():
            job = MailboxSyncJob.query.one()
            self.assertEqual(job.status, "queued")
            self.assertEqual(job.mailbox_folder, "INBOX")

    def test_worker_discovers_and_completes_queued_job(self) -> None:
        with self.app.app_context():
            job = mailbox_jobs.create_mailbox_sync_job("INBOX")
            job_id = job.id
        with patch("services.mailbox_jobs.sync_mailbox_folder", return_value={"created": 2, "updated": 1}):
            self.assertEqual(mailbox_jobs._next_pending_job_id(self.app), job_id)
            mailbox_jobs.process_mailbox_sync_job(self.app, job_id)
        with self.app.app_context():
            job = db.session.get(MailboxSyncJob, job_id)
            self.assertEqual(job.status, "completed")
            self.assertIn("Created 2", job.summary_message)

    def test_failed_sync_records_error_without_raising(self) -> None:
        with self.app.app_context():
            job_id = mailbox_jobs.create_mailbox_sync_job("INBOX").id
        with patch("services.mailbox_jobs.sync_mailbox_folder", side_effect=TimeoutError("IMAP timed out")):
            mailbox_jobs.process_mailbox_sync_job(self.app, job_id)
        with self.app.app_context():
            job = db.session.get(MailboxSyncJob, job_id)
            self.assertEqual(job.status, "failed")
            self.assertEqual(job.error_message, "IMAP timed out")

    def test_automatic_sync_settings_and_duplicate_protection(self) -> None:
        now = datetime.utcnow()
        with self.app.app_context():
            self._set_setting("mail_auto_sync_enabled", "false")
            self.assertEqual(mailbox_daemon._schedule_automatic_sync(now, now), now)
            self.assertEqual(MailboxSyncJob.query.count(), 0)

            self._set_setting("mail_auto_sync_enabled", "true")
            self._set_setting("mail_auto_sync_interval_minutes", " 2 ")
            next_sync = mailbox_daemon._schedule_automatic_sync(now, now)
            self.assertEqual(next_sync, now + timedelta(minutes=2))
            self.assertEqual(MailboxSyncJob.query.count(), 1)

            mailbox_daemon._schedule_automatic_sync(next_sync, next_sync)
            self.assertEqual(MailboxSyncJob.query.count(), 1)

            self._set_setting("mail_auto_sync_interval_minutes", "not-a-number")
            self.assertEqual(mailbox_daemon._sync_interval_minutes(), 10)

    def test_worker_status_uses_external_worker_lease(self) -> None:
        with self.app.app_context():
            db.session.add(
                WorkerLease(
                    name="mailbox-sync-worker",
                    owner_id="other-host:123:worker",
                    expires_at=datetime.utcnow() + timedelta(minutes=2),
                )
            )
            db.session.add(MailboxSyncJob(mailbox_folder="INBOX", status="queued"))
            db.session.commit()
            status = mailbox_jobs.get_mailbox_worker_status()
            self.assertTrue(status["alive"])
            self.assertEqual(status["queue_size"], 1)

    def test_worker_status_rejects_stale_dead_local_lease(self) -> None:
        with self.app.app_context():
            db.session.add(
                WorkerLease(
                    name="mailbox-sync-worker",
                    owner_id=f"{socket.gethostname()}:12345:dead-worker",
                    expires_at=datetime.utcnow() + timedelta(minutes=2),
                )
            )
            db.session.commit()
            with patch("services.worker_lease.os.kill", side_effect=ProcessLookupError):
                status = mailbox_jobs.get_mailbox_worker_status()
            self.assertFalse(status["alive"])


if __name__ == "__main__":
    unittest.main()
