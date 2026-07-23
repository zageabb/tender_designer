from __future__ import annotations

import threading
from datetime import datetime, time, timedelta

from flask import Flask

from services.mailbox_jobs import queue_mailbox_sync_job
from services.settings_service import get_setting
from services.tender_monitor import request_tender_monitor_scan


_scheduler_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None
_scheduler_started = False


def _auto_mail_sync_enabled() -> bool:
    return (get_setting("mail_auto_sync_enabled", "true") or "true").lower() in {"1", "true", "yes", "on"}


def _mail_sync_interval_minutes() -> int:
    raw_value = get_setting("mail_auto_sync_interval_minutes", "10") or "10"
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 10


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


def _next_mail_sync_run(now: datetime) -> datetime:
    return now + timedelta(minutes=_mail_sync_interval_minutes())


def _worker_loop(app: Flask) -> None:
    with app.app_context():
        next_monitor_run = _next_monitor_run(datetime.now())
        next_mail_sync_run = _next_mail_sync_run(datetime.now())
        while True:
            now = datetime.now()
            if now >= next_monitor_run:
                request_tender_monitor_scan()
                next_monitor_run = _next_monitor_run(now + timedelta(seconds=1))
            if _auto_mail_sync_enabled() and now >= next_mail_sync_run:
                queue_mailbox_sync_job(source_label="Scheduled mailbox sync")
                next_mail_sync_run = _next_mail_sync_run(now + timedelta(seconds=1))
            sleep_until = min(next_monitor_run, next_mail_sync_run if _auto_mail_sync_enabled() else next_monitor_run)
            delay = max(5, min(60, int((sleep_until - now).total_seconds())))
            threading.Event().wait(delay)


def start_automation_scheduler(app: Flask) -> None:
    global _scheduler_started, _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        worker = threading.Thread(target=_worker_loop, args=(app,), name="automation-scheduler", daemon=True)
        worker.start()
        _scheduler_thread = worker
        _scheduler_started = True
