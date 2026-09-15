from __future__ import annotations

import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Callable

from flask import Flask

from services.computer_finder_service import ComputerFinderConfigError, find_computer_for_spec
from services.research_core_adapter import install_research_core_equipment
from services.vendor_knowledge import build_vendor_search_context


_jobs: dict[str, dict] = {}
_lock = threading.Lock()
VENDOR_KNOWLEDGE_ONLY_MARKER = "[VENDOR_KNOWLEDGE_ONLY]"
_VENDOR_ONLY_PHRASES = (
    "vendor knowledge only",
    "only from vendor knowledge",
    "only use vendor knowledge",
    "only vendor knowledge",
    "only respond from vendor knowledge",
    "only consider vendor knowledge",
)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _equipment_allowed_sites_only() -> bool:
    value = os.environ.get("TENDER_RESEARCH_ALLOWED_SITES_ONLY", "0")
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _vendor_only_requested(computer_spec: str, mode: str) -> bool:
    if mode == "general":
        return False
    lowered = computer_spec.lower()
    return VENDOR_KNOWLEDGE_ONLY_MARKER.lower() in lowered or any(phrase in lowered for phrase in _VENDOR_ONLY_PHRASES)


def _strip_vendor_only_marker(computer_spec: str) -> str:
    return computer_spec.replace(VENDOR_KNOWLEDGE_ONLY_MARKER, "").strip()


def create_computer_finder_job(
    app: Flask,
    computer_spec: str,
    mode: str = "computer",
    use_allowed_websites: bool = True,
    model: str | None = None,
) -> dict:
    if mode != "general":
        # The legacy Computer Finder route forces its supplier-domain allowlist.
        # Equipment Research is broader by design, so use the open web unless
        # the deployment explicitly opts back into configured-sites-only mode.
        use_allowed_websites = _equipment_allowed_sites_only()

    vendor_knowledge_only = _vendor_only_requested(computer_spec, mode)
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
        "model": model,
        "vendor_knowledge_only": vendor_knowledge_only,
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
        args=(app, job_id, computer_spec, mode, use_allowed_websites, model),
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
    model: str | None,
) -> None:
    vendor_knowledge_only = _vendor_only_requested(computer_spec, mode)
    clean_spec = _strip_vendor_only_marker(computer_spec)
    _update(job_id, status="running", phase="Planning research", started_at=_now_iso())
    progress = _progress_recorder(job_id)
    progress({"kind": "phase", "status": "running", "label": "Planning targeted searches", "phase": "Planning research"})
    try:
        with app.app_context():
            install_research_core_equipment()
            research_spec = clean_spec
            vendor_match_count = 0
            result = None
            if mode != "general":
                progress(
                    {
                        "kind": "vendor_knowledge",
                        "status": "running",
                        "label": (
                            "Finding Vendor Knowledge candidates for internet verification"
                            if vendor_knowledge_only
                            else "Checking current Vendor Knowledge stock"
                        ),
                        "phase": "Checking vendor knowledge",
                    }
                )
                vendor_context, vendor_match_count = build_vendor_search_context(clean_spec, limit=14)
                if vendor_context:
                    if vendor_knowledge_only:
                        research_spec = (
                            f"{clean_spec}\n\n"
                            "=== VENDOR KNOWLEDGE CANDIDATES ONLY MODE ===\n"
                            "The candidate set is CLOSED. Only products listed in the Vendor Knowledge section below may appear in the answer.\n"
                            "Internet research is permitted only to verify technical specifications, standards, compatibility, warranty or other facts for those listed candidates.\n"
                            "Do NOT discover, recommend, compare or mention alternative products that are not in Vendor Knowledge.\n"
                            "If a listed candidate cannot be technically verified, mark the relevant requirements Unknown or Fail rather than substituting another product.\n"
                            "=== END MODE INSTRUCTION ===\n\n"
                            "--- NON-AUTHORITATIVE COMMERCIAL EVIDENCE ---\n"
                            f"{vendor_context}\n"
                            "--- END COMMERCIAL EVIDENCE ---\n\n"
                            "Research instruction: preserve the original tender requirements above as authoritative. "
                            "Use the web only to confirm how the listed Vendor Knowledge candidates match those requirements."
                        )
                    else:
                        research_spec = (
                            f"{clean_spec}\n\n"
                            "--- NON-AUTHORITATIVE COMMERCIAL EVIDENCE ---\n"
                            f"{vendor_context}\n"
                            "--- END COMMERCIAL EVIDENCE ---\n\n"
                            "Research instruction: preserve the original tender requirements above as authoritative. "
                            "Use Vendor Knowledge only to identify currently available candidate products and commercial facts. "
                            "Verify technical compliance from appropriate technical evidence."
                        )
                    progress(
                        {
                            "kind": "vendor_knowledge",
                            "status": "returned",
                            "label": (
                                f"Found {vendor_match_count} Vendor Knowledge candidate(s); verifying those candidates only"
                                if vendor_knowledge_only
                                else f"Found {vendor_match_count} current Vendor Knowledge candidate(s)"
                            ),
                            "phase": "Planning research",
                        }
                    )
                else:
                    progress(
                        {
                            "kind": "vendor_knowledge",
                            "status": "returned",
                            "label": "No current Vendor Knowledge candidates matched this request",
                            "phase": "Checking vendor knowledge",
                        }
                    )
                    if vendor_knowledge_only:
                        result = {
                            "answer": (
                                "## Vendor Knowledge result\n\n"
                                "No currently active and available Vendor Knowledge products matched the requested specification.\n\n"
                                "Because **Vendor Knowledge only** mode was requested, no internet product discovery was performed and no outside alternatives are being suggested."
                            ),
                            "sources": [],
                            "steps": [
                                "Vendor Knowledge only mode was active.",
                                "No current available Vendor Knowledge candidates matched the request.",
                                "Internet product discovery was skipped because only Vendor Knowledge products are permitted in this mode.",
                            ],
                        }
            if result is None:
                result = find_computer_for_spec(
                    research_spec,
                    progress_callback=progress,
                    mode=mode,
                    use_allowed_websites=use_allowed_websites,
                    model=model,
                )
        progress({"kind": "phase", "status": "returned", "label": "Research answer completed", "phase": "Complete"})
        steps = list(result.get("steps", []))
        if mode != "general":
            if vendor_knowledge_only:
                if vendor_match_count:
                    steps.insert(
                        0,
                        f"Vendor Knowledge only mode restricted the candidate set to {vendor_match_count} current available product(s); internet research was used only for technical verification.",
                    )
                elif not steps:
                    steps.insert(0, "Vendor Knowledge only mode found no current available candidates.")
            elif vendor_match_count:
                steps.insert(0, f"Vendor Knowledge supplied {vendor_match_count} current available candidate(s) as commercial evidence.")
            else:
                steps.insert(0, "Vendor Knowledge had no current available candidates matching the request.")
        _update(
            job_id,
            status="completed",
            phase="Complete",
            message=result["answer"],
            sources=result.get("sources", []),
            steps=steps,
            completed_at=_now_iso(),
        )
    except ComputerFinderConfigError as exc:
        progress({"kind": "phase", "status": "failed", "label": str(exc), "phase": "Failed"})
        _update(job_id, status="failed", phase="Failed", error=str(exc), steps=getattr(exc, "steps", []), completed_at=_now_iso())
    except Exception as exc:
        progress({"kind": "phase", "status": "failed", "label": f"Search failed: {exc}", "phase": "Failed"})
        _update(job_id, status="failed", phase="Failed", error=f"Research search failed: {exc}", completed_at=_now_iso())