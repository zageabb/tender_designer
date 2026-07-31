from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Callable

from flask import Flask

from services.computer_finder_service import ComputerFinderConfigError, find_computer_for_spec


_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def create_computer_finder_job(
    app: Flask,
    computer_spec: str,
    mode: str = "computer",
    use_allowed_websites: bool = True,
) -> dict:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",
        "phase": "Queued",
        "message": None,
        "error": None,
        "sources": [],
        "steps": [],
        "events": [],
        "mode": mode,
        "created_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
    }
    with _lock:
        _jobs[job_id] = job
        finished = sorted(
            ((key, value) for key, value in _jobs.items() if value["status"] in {"completed", "failed"}),
            key=lambda row: row[1]["created_at"],
        )
        for old_id, _old_job in finished[:-50]:
            _jobs.pop(old_id, None)
    threading.Thread(
        target=_run_job,
        args=(app, job_id, computer_spec, mode, use_allowed_websites),
        name=f"computer-finder-{job_id[:8]}",
        daemon=True,
    ).start()
    return deepcopy(job)


def get_computer_finder_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return deepcopy(job) if job else None


def _update(job_id: str, **changes) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(changes)


def _progress_recorder(job_id: str) -> Callable[[dict], None]:
    def record(event: dict) -> None:
        payload = {
            "sequence": 0,
            "timestamp": _now_iso(),
            "kind": str(event.get("kind") or "activity"),
            "status": str(event.get("status") or "running"),
            "label": str(event.get("label") or "Research activity")[:500],
            "url": str(event.get("url") or "")[:2000],
            "detail": str(event.get("detail") or "")[:1000],
        }
        with _lock:
            job = _jobs.get(job_id)
            if not job:
                return
            payload["sequence"] = len(job["events"]) + 1
            job["events"].append(payload)
            job["events"] = job["events"][-250:]
            if event.get("phase"):
                job["phase"] = str(event["phase"])[:100]

    return record


def _run_job(
    app: Flask,
    job_id: str,
    computer_spec: str,
    mode: str,
    use_allowed_websites: bool,
) -> None:
    _update(job_id, status="running", phase="Planning research", started_at=_now_iso())
    progress = _progress_recorder(job_id)
    progress({"kind": "phase", "status": "running", "label": "Planning targeted searches", "phase": "Planning research"})
    try:
        with app.app_context():
            result = find_computer_for_spec(
                computer_spec,
                progress_callback=progress,
                mode=mode,
                use_allowed_websites=use_allowed_websites,
            )
        progress({"kind": "phase", "status": "returned", "label": "Research answer completed", "phase": "Complete"})
        _update(
            job_id,
            status="completed",
            phase="Complete",
            message=result["answer"],
            sources=result.get("sources", []),
            steps=result.get("steps", []),
            completed_at=_now_iso(),
        )
    except ComputerFinderConfigError as exc:
        progress({"kind": "phase", "status": "failed", "label": str(exc), "phase": "Failed"})
        _update(job_id, status="failed", phase="Failed", error=str(exc), steps=getattr(exc, "steps", []), completed_at=_now_iso())
    except Exception as exc:
        progress({"kind": "phase", "status": "failed", "label": f"Search failed: {exc}", "phase": "Failed"})
        _update(job_id, status="failed", phase="Failed", error=f"Research search failed: {exc}", completed_at=_now_iso())
