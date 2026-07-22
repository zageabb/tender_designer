from __future__ import annotations

import json
import os
import queue
import threading
from datetime import datetime

from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

from database import db
from models import ExtractionJob, LLMRunLog, Tender
from services.chat_service import add_chat_message, get_or_create_session
from services.document_extraction import extract_text
from services.llm_tasks import extract_tender_items, extract_tender_metadata, extract_tender_questions
from services.markdown_tools import extracted_text_suffix
from services.ollama_client import OllamaClient
from services.settings_service import get_setting, get_task_model


_job_queue: queue.Queue[int] = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False
_worker_thread: threading.Thread | None = None
_worker_resume_event = threading.Event()
_worker_resume_event.set()
_active_job_id: int | None = None
_queued_job_ids: set[int] = set()


TASK_CONFIG = {
    "metadata": {
        "setting_key": "metadata_extraction",
        "default_status": "Metadata Extracted",
        "runner": extract_tender_metadata,
    },
    "items": {
        "setting_key": "item_extraction",
        "default_status": "Items Extracted",
        "runner": extract_tender_items,
    },
    "questions": {
        "setting_key": "question_extraction",
        "default_status": "Ready For Review",
        "runner": extract_tender_questions,
    },
}


def _selected_document_names(job: ExtractionJob) -> list[str]:
    try:
        return json.loads(job.selected_document_names_json or "[]")
    except json.JSONDecodeError:
        return []


def _selected_document_ids(job: ExtractionJob) -> list[int]:
    try:
        values = json.loads(job.selected_document_ids_json or "[]")
    except json.JSONDecodeError:
        return []
    return [int(value) for value in values if str(value).isdigit()]


def _pending_job_ids(app: Flask) -> list[int]:
    with app.app_context():
        pending_jobs = (
            ExtractionJob.query.filter(ExtractionJob.status.in_(["queued", "running"]))
            .order_by(ExtractionJob.created_at.asc())
            .all()
        )
    return [job.id for job in pending_jobs]


def ensure_extraction_worker(app: Flask) -> bool:
    global _worker_started, _worker_thread
    started_now = False
    with _worker_lock:
        worker_alive = bool(_worker_thread and _worker_thread.is_alive())
        if not worker_alive:
            worker = threading.Thread(target=_worker_loop, args=(app,), name="extraction-worker", daemon=True)
            worker.start()
            _worker_thread = worker
            _worker_started = True
            started_now = True
    if started_now:
        for pending_job_id in _pending_job_ids(app):
            enqueue_extraction_job(pending_job_id)
    return started_now


def enqueue_extraction_job(job_id: int) -> bool:
    with _worker_lock:
        if job_id in _queued_job_ids or _active_job_id == job_id:
            return False
        _queued_job_ids.add(job_id)
    _job_queue.put(job_id)
    return True


def pause_extraction_worker() -> None:
    _worker_resume_event.clear()


def resume_extraction_worker() -> None:
    _worker_resume_event.set()


def get_worker_status() -> dict[str, object]:
    return {
        "started": _worker_started,
        "alive": bool(_worker_thread and _worker_thread.is_alive()),
        "paused": not _worker_resume_event.is_set(),
        "queue_size": _job_queue.qsize(),
        "active_job_id": _active_job_id,
    }


def cancel_extraction_job(job: ExtractionJob) -> tuple[bool, str]:
    if job.status == "queued":
        job.status = "cancelled"
        job.summary_message = None
        job.error_message = "Cancelled manually before processing started."
        job.completed_at = datetime.utcnow()
        return True, f"Job #{job.id} cancelled."
    if job.status == "running":
        job.status = "cancelling"
        job.error_message = "Cancellation requested. The current LLM call may need to finish first."
        return True, f"Cancellation requested for job #{job.id}."
    if job.status == "cancelling":
        return False, f"Job #{job.id} is already being cancelled."
    if job.status == "cancelled":
        return False, f"Job #{job.id} is already cancelled."
    return False, f"Job #{job.id} cannot be cancelled once it is {job.status}."


def retry_extraction_job(job: ExtractionJob) -> tuple[bool, str]:
    if job.status not in {"failed", "cancelled"}:
        return False, f"Job #{job.id} can only be retried from failed or cancelled."
    job.status = "queued"
    job.summary_message = f"{job.task_type.title()} extraction queued again."
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    enqueue_extraction_job(job.id)
    return True, f"Job #{job.id} queued again."


def _refresh_job(job: ExtractionJob) -> ExtractionJob:
    db.session.refresh(job)
    return job


def _finish_cancelled_job(job: ExtractionJob, message: str) -> None:
    job.status = "cancelled"
    job.summary_message = None
    job.error_message = message
    job.completed_at = datetime.utcnow()
    db.session.commit()


def _cancellation_requested(job: ExtractionJob) -> bool:
    refreshed = _refresh_job(job)
    return refreshed.status in {"cancelling", "cancelled"}


def _process_selected_documents(app: Flask, tender: Tender, selected_document_ids: set[int]) -> tuple[list, list[str]]:
    processed_notes: list[str] = []
    selected_documents = [document for document in tender.documents if document.id in selected_document_ids]
    for document in selected_documents:
        if document.extracted_text:
            continue
        text, error = extract_text(document.file_path)
        if text:
            extracted_dir = app.config["DATA_DIR"] / "tenders" / str(document.tender_id) / "extracted_text"
            extracted_dir.mkdir(parents=True, exist_ok=True)
            text_path = extracted_dir / f"{document.stored_filename}{extracted_text_suffix(text)}"
            if document.extracted_text_path and document.extracted_text_path != str(text_path) and os.path.exists(document.extracted_text_path):
                try:
                    os.remove(document.extracted_text_path)
                except OSError:
                    pass
            text_path.write_text(text, encoding="utf-8")
            document.extracted_text = text
            document.extracted_text_path = str(text_path)
            document.processed = True
            document.processing_notes = "Processed automatically before extraction."
            processed_notes.append(f"Processed {document.original_filename} automatically before extraction.")
        elif error:
            document.processing_notes = error
            processed_notes.append(f"Could not process {document.original_filename}: {error}")
    return selected_documents, processed_notes


def _chat_steps(job: ExtractionJob, ollama_url: str, selected_documents, processed_notes: list[str]) -> list[str]:
    names = _selected_document_names(job)
    return [
        f"Job #{job.id}",
        f"Task: {job.task_type}",
        f"Model: {job.model_name}",
        f"Ollama URL: {ollama_url}",
        f"Selected documents: {len(selected_documents)}",
        "Document names: " + ", ".join(names[:5]) if names else "Document names unavailable.",
        f"Processed selected docs with text: {len([doc for doc in selected_documents if doc.extracted_text])}",
        *processed_notes[:6],
    ]


def _log_chat_update(job: ExtractionJob, role: str, message: str, steps: list[str]) -> None:
    page_context = {
        "page": "tender_detail",
        "tender_id": job.tender_id,
    }
    chat_session = get_or_create_session(db, job.tender_id, page_context)
    add_chat_message(db, chat_session, role, message, intermediate_steps=steps)


def process_extraction_job(app: Flask, job_id: int) -> None:
    global _active_job_id
    with app.app_context():
        try:
            job = ExtractionJob.query.get(job_id)
            if job is None or job.status not in {"queued", "running"}:
                return
            config = TASK_CONFIG.get(job.task_type)
            if config is None:
                job.status = "failed"
                job.error_message = "Unknown extraction task."
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return
            tender = Tender.query.get(job.tender_id)
            if tender is None:
                job.status = "failed"
                job.error_message = "Tender no longer exists."
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return
            job.status = "running"
            job.started_at = job.started_at or datetime.utcnow()
            db.session.commit()
            _active_job_id = job.id

            if _cancellation_requested(job):
                _finish_cancelled_job(job, "Cancelled manually before extraction started.")
                return

            selected_ids = set(_selected_document_ids(job))
            ollama_url = get_setting("ollama_url", app.config["OLLAMA_URL"])
            client = OllamaClient(ollama_url)
            selected_documents, processed_notes = _process_selected_documents(app, tender, selected_ids)
            if _cancellation_requested(job):
                _finish_cancelled_job(job, "Cancelled manually after document preparation.")
                return
            start_steps = _chat_steps(job, ollama_url, selected_documents, processed_notes)
            try:
                _log_chat_update(
                    job,
                    "system",
                    f"Background extraction started for {job.task_type} on tender {tender.tender_number}.",
                    start_steps,
                )
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()

            success_status = config["default_status"]
            task_func = config["runner"]
            try:
                success, message = task_func(client, tender, job.model_name, documents=selected_documents)
            except Exception as exc:
                success, message = False, str(exc)

            if _cancellation_requested(job):
                _finish_cancelled_job(job, "Cancelled manually after the current LLM call completed.")
                return

            db.session.add(
                LLMRunLog(
                    tender_id=tender.id,
                    task_type=job.task_type,
                    model_name=job.model_name,
                    prompt=f"Task: {job.task_type}",
                    response=message,
                    success=success,
                    error_message=None if success else message,
                )
            )
            if success:
                tender.status = success_status
                job.status = "completed"
                job.summary_message = message
                job.error_message = None
            else:
                job.status = "failed"
                job.summary_message = None
                job.error_message = message
            job.completed_at = datetime.utcnow()
            db.session.commit()

            try:
                if success:
                    _log_chat_update(
                        job,
                        "assistant",
                        f"{job.task_type.title()} extraction finished in the background.",
                        [
                            f"Tender status set to: {success_status}",
                            f"Result: {message}",
                            "Refresh the tender view to see the newest records if they are not visible yet.",
                        ],
                    )
                else:
                    _log_chat_update(
                        job,
                        "assistant",
                        f"{job.task_type.title()} extraction failed in the background.",
                        [
                            f"Model: {job.model_name}",
                            f"Ollama URL: {ollama_url}",
                            f"Error: {message}",
                        ],
                    )
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
        finally:
            _active_job_id = None


def _worker_loop(app: Flask) -> None:
    while True:
        job_id = _job_queue.get()
        try:
            _worker_resume_event.wait()
            process_extraction_job(app, job_id)
        except Exception as exc:
            app.logger.exception("Extraction worker failed while processing job %s", job_id)
            with app.app_context():
                job = ExtractionJob.query.get(job_id)
                if job and job.status in {"queued", "running", "cancelling"}:
                    job.status = "failed"
                    job.summary_message = None
                    job.error_message = f"Background worker error: {exc}"
                    job.completed_at = datetime.utcnow()
                    db.session.commit()
        finally:
            with _worker_lock:
                _queued_job_ids.discard(job_id)
            _job_queue.task_done()


def start_extraction_worker(app: Flask) -> None:
    ensure_extraction_worker(app)
