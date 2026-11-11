from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.exc import IntegrityError


os.environ["TENDER_DESIGNER_MIGRATION_MODE"] = "1"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from models import ExtractionJob, Tender, TenderDocument  # noqa: E402
from services.extraction_jobs import _mark_failed_extraction_job  # noqa: E402
from services.llm_tasks import extract_tender_metadata  # noqa: E402


class FakeMetadataClient:
    def generate_json(self, model_name: str, prompt: str):
        return (
            {
                "customer_name": "East Lancashire Learning Group",
                "tender_number": "182",
                "title": "Apple iMac Computers",
                "submission_date": "2026-11-19",
                "submission_time": "12:00",
                "submission_type": "Portal",
            },
            "{}",
            None,
        )


class ExtractionJobTestCase(unittest.TestCase):
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
            }
        )
        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self) -> None:
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def test_metadata_extraction_preserves_number_when_extracted_number_is_in_use(self) -> None:
        with self.app.app_context():
            existing = Tender(customer_name="Existing", tender_number="182")
            tender = Tender(customer_name="Imported email", tender_number="AUTO-EMAIL-1")
            document = TenderDocument(
                tender=tender,
                original_filename="invitation.txt",
                stored_filename="invitation.txt",
                file_path="tenders/2/invitation.txt",
                file_type="txt",
                extracted_text="Invitation to tender 182 for Apple iMac Computers",
            )
            db.session.add_all([existing, tender, document])
            db.session.commit()

            success, message = extract_tender_metadata(FakeMetadataClient(), tender, "test-model")
            db.session.commit()

            self.assertTrue(success)
            self.assertEqual(tender.tender_number, "AUTO-EMAIL-1")
            self.assertEqual(tender.customer_name, "East Lancashire Learning Group")
            self.assertEqual(tender.title, "Apple iMac Computers")
            self.assertIn("182 is already in use", message)

    def test_worker_failure_can_be_recorded_after_failed_flush(self) -> None:
        with self.app.app_context():
            first = Tender(customer_name="First", tender_number="182")
            second = Tender(customer_name="Second", tender_number="AUTO-EMAIL-2")
            job = ExtractionJob(
                tender=second,
                task_type="metadata",
                model_name="test-model",
                status="running",
            )
            db.session.add_all([first, second, job])
            db.session.commit()
            job_id = job.id

            second.tender_number = "182"
            with self.assertRaises(IntegrityError) as raised:
                db.session.flush()

            _mark_failed_extraction_job(job_id, raised.exception)

            recorded = db.session.get(ExtractionJob, job_id)
            self.assertEqual(recorded.status, "failed")
            self.assertIn("UNIQUE constraint failed", recorded.error_message)
            self.assertIsNotNone(recorded.completed_at)


if __name__ == "__main__":
    unittest.main()
