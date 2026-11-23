from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from datetime import datetime, timedelta

from flask import Flask
from sqlalchemy.exc import IntegrityError

from database import db
from models import WorkerLease


PROCESS_OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
LEASE_SECONDS = 180
HEARTBEAT_SECONDS = 60
_heartbeat_names: set[str] = set()
_heartbeat_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _owner_process_is_alive(owner_id: str) -> bool | None:
    try:
        hostname, pid_text, _ = owner_id.split(":", 2)
        pid = int(pid_text)
    except (AttributeError, ValueError):
        return None
    if hostname != socket.gethostname():
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def worker_lease_is_alive(name: str) -> bool:
    lease = db.session.get(WorkerLease, name)
    if lease is None or lease.expires_at <= datetime.utcnow():
        return False
    return _owner_process_is_alive(lease.owner_id) is not False


def acquire_worker_lease(app: Flask, name: str) -> bool:
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=LEASE_SECONDS)
    with app.app_context():
        lease = db.session.get(WorkerLease, name)
        if lease is None:
            try:
                db.session.add(WorkerLease(name=name, owner_id=PROCESS_OWNER_ID, expires_at=expires_at))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return False
        elif (
            lease.owner_id == PROCESS_OWNER_ID
            or lease.expires_at <= now
            or _owner_process_is_alive(lease.owner_id) is False
        ):
            lease.owner_id = PROCESS_OWNER_ID
            lease.expires_at = expires_at
            lease.updated_at = now
            db.session.commit()
        else:
            return False
    _start_heartbeat(app, name)
    return True


def _start_heartbeat(app: Flask, name: str) -> None:
    with _heartbeat_lock:
        if name in _heartbeat_names:
            return
        _heartbeat_names.add(name)

    threading.Thread(target=_heartbeat_loop, args=(app, name), name=f"{name}-lease-heartbeat", daemon=True).start()


def _refresh_worker_lease(app: Flask, name: str) -> bool:
    with app.app_context():
        lease = db.session.get(WorkerLease, name)
        if lease is None or lease.owner_id != PROCESS_OWNER_ID:
            return False
        lease.expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)
        lease.updated_at = datetime.utcnow()
        db.session.commit()
    return True


def _heartbeat_loop(app: Flask, name: str) -> None:
    try:
        while True:
            threading.Event().wait(HEARTBEAT_SECONDS)
            try:
                if not _refresh_worker_lease(app, name):
                    return
            except Exception:
                logger.exception("worker lease heartbeat failed; retrying lease=%s", name)
                with app.app_context():
                    db.session.rollback()
                    db.session.remove()
    finally:
        with _heartbeat_lock:
            _heartbeat_names.discard(name)
