from __future__ import annotations

import threading
from datetime import datetime, time, timedelta

from flask import Flask

from services.settings_service import get_setting
from services.tender_monitor import request_tender_monitor_scan
from services.worker_lease import acquire_worker_lease


_scheduler_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None
_scheduler_started = False


def _monitor_schedule_time() -> time:
    raw_value = (get_setting("tender_monitor_schedule_time", "00:00") or "00:00").strip()
    try:
        hour_text, minute_text = raw_value.split(":", 1)
        hour = min(23, max(0, int(hour_text)))
        minute = min(59, max(0, int(minute_text)))
        return time(hour=hour, minute=minute)
    except (ValueError, AttributeError):
        return time(hour=0, minute=0)


def _next_monitor_run(now: datetime) -> datetime:
    scheduled_time = _monitor_schedule_time()
    candidate = datetime.combine(now.date(), scheduled_time)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _worker_loop(app: Flask) -> None:
    with app.app_context():
        next_monitor_run = _next_monitor_run(datetime.now())
        while True:
            now = datetime.now()
            if now >= next_monitor_run:
                request_tender_monitor_scan()
                next_monitor_run = _next_monitor_run(now + timedelta(seconds=1))
            delay = max(5, min(60, int((next_monitor_run - now).total_seconds())))
            threading.Event().wait(delay)


def start_automation_scheduler(app: Flask) -> None:
    global _scheduler_started, _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        if not acquire_worker_lease(app, "automation-scheduler"):
            return
        worker = threading.Thread(target=_worker_loop, args=(app,), name="automation-scheduler", daemon=True)
        worker.start()
        _scheduler_thread = worker
        _scheduler_started = True
