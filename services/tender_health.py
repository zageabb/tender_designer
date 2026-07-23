from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Tender


ACTIVE_STATUSES = {
    "New",
    "Documents Uploaded",
    "Metadata Extracted",
    "Items Extracted",
    "Ready For Review",
    "RFI Required",
    "Quoted",
}

COMPLETE_STATUSES = {"Submitted", "Awarded"}
INACTIVE_STATUSES = {"Lost", "Cancelled"}
EARLY_STAGE_STATUSES = {"New", "Documents Uploaded", "Metadata Extracted", "Items Extracted"}

SEVERITY_ORDER = {
    "critical": 0,
    "warning": 1,
    "watch": 2,
    "healthy": 3,
    "completed": 4,
    "inactive": 5,
}

SIGNAL_LEGEND = [
    {
        "key": "critical",
        "label": "Critical",
        "description": "Submission is overdue or dangerously close for an active tender.",
        "colour": "Rose",
        "monitor": "Immediate admin warning email",
    },
    {
        "key": "warning",
        "label": "Warning",
        "description": "Date pressure or workflow risk means this tender needs attention soon.",
        "colour": "Amber",
        "monitor": "Admin warning email",
    },
    {
        "key": "watch",
        "label": "Watch",
        "description": "Tender is active but not yet in a danger zone.",
        "colour": "Blue",
        "monitor": "No automatic email",
    },
    {
        "key": "healthy",
        "label": "Healthy",
        "description": "Tender is progressing with enough time left to work.",
        "colour": "Green",
        "monitor": "No automatic email",
    },
    {
        "key": "completed",
        "label": "Completed",
        "description": "Tender has already been submitted or awarded.",
        "colour": "Deep green",
        "monitor": "No automatic email",
    },
    {
        "key": "inactive",
        "label": "Inactive",
        "description": "Tender is lost or cancelled and should fade into the background.",
        "colour": "Slate",
        "monitor": "No automatic email",
    },
]


@dataclass(frozen=True)
class TenderHealthSignal:
    key: str
    label: str
    summary: str
    detail: str
    css_modifier: str
    days_until_submission: int | None
    submission_bucket: str
    monitor_level: str | None
    notification_key: str | None
    active: bool
    rank: int


def get_signal_legend() -> list[dict[str, str]]:
    return SIGNAL_LEGEND


def evaluate_tender_health(tender: Tender, today: date | None = None) -> TenderHealthSignal:
    today = today or date.today()
    status = (tender.status or "New").strip() or "New"
    submission_date = tender.submission_date
    days_until_submission = None if submission_date is None else (submission_date - today).days

    if status in INACTIVE_STATUSES:
        return TenderHealthSignal(
            key="inactive",
            label="Inactive",
            summary=f"{status} tender.",
            detail="This tender is no longer active, so it should stay visually muted.",
            css_modifier="inactive",
            days_until_submission=days_until_submission,
            submission_bucket="inactive",
            monitor_level=None,
            notification_key=None,
            active=False,
            rank=SEVERITY_ORDER["inactive"],
        )

    if status in COMPLETE_STATUSES:
        completion_label = "Completed" if status == "Submitted" else "Awarded"
        detail = (
            "Submission has been recorded."
            if status == "Submitted"
            else "The tender has been awarded and can stay in the completed state."
        )
        return TenderHealthSignal(
            key="completed",
            label=completion_label,
            summary=f"{status} tender.",
            detail=detail,
            css_modifier="completed",
            days_until_submission=days_until_submission,
            submission_bucket="completed",
            monitor_level=None,
            notification_key=None,
            active=False,
            rank=SEVERITY_ORDER["completed"],
        )

    if submission_date is None:
        severity = "warning" if status in EARLY_STAGE_STATUSES or status == "RFI Required" else "watch"
        return TenderHealthSignal(
            key=severity,
            label="Missing Submission Date",
            summary="Active tender has no submission date yet.",
            detail="Add a submission date so the workflow and alerting can judge urgency correctly.",
            css_modifier=severity,
            days_until_submission=None,
            submission_bucket="missing-date",
            monitor_level="warning" if severity == "warning" else None,
            notification_key=f"{tender.id}|missing-date|{status}" if severity == "warning" else None,
            active=True,
            rank=SEVERITY_ORDER[severity],
        )

    if days_until_submission is not None and days_until_submission < 0:
        return TenderHealthSignal(
            key="critical",
            label="Overdue",
            summary=f"Submission date passed {abs(days_until_submission)} day(s) ago.",
            detail=f"Tender is still marked {status}, but the submission date {submission_date.isoformat()} is already in the past.",
            css_modifier="critical",
            days_until_submission=days_until_submission,
            submission_bucket="overdue",
            monitor_level="critical",
            notification_key=f"{tender.id}|overdue|{submission_date.isoformat()}|{status}",
            active=True,
            rank=SEVERITY_ORDER["critical"],
        )

    if days_until_submission is not None and days_until_submission <= 2 and status in EARLY_STAGE_STATUSES.union({"RFI Required"}):
        return TenderHealthSignal(
            key="critical",
            label="Submission Imminent",
            summary=f"Due in {days_until_submission} day(s) while still in {status}.",
            detail="The tender is close to deadline and still needs substantial work before submission.",
            css_modifier="critical",
            days_until_submission=days_until_submission,
            submission_bucket="due-2",
            monitor_level="critical",
            notification_key=f"{tender.id}|due-2|{submission_date.isoformat()}|{status}",
            active=True,
            rank=SEVERITY_ORDER["critical"],
        )

    if days_until_submission is not None and days_until_submission <= 7 and status in EARLY_STAGE_STATUSES.union({"RFI Required", "Ready For Review"}):
        return TenderHealthSignal(
            key="warning",
            label="Attention Needed",
            summary=f"Due in {days_until_submission} day(s) and still at {status}.",
            detail="This tender is approaching deadline and should be pushed forward soon.",
            css_modifier="warning",
            days_until_submission=days_until_submission,
            submission_bucket="due-7",
            monitor_level="warning",
            notification_key=f"{tender.id}|due-7|{submission_date.isoformat()}|{status}",
            active=True,
            rank=SEVERITY_ORDER["warning"],
        )

    if status == "RFI Required":
        return TenderHealthSignal(
            key="warning",
            label="Waiting On Supplier Input",
            summary="RFI work is still open.",
            detail="The tender depends on supplier clarification or pricing before it can move forward safely.",
            css_modifier="warning",
            days_until_submission=days_until_submission,
            submission_bucket="rfi-open",
            monitor_level="warning" if days_until_submission is not None and days_until_submission <= 14 else None,
            notification_key=f"{tender.id}|rfi-open|{submission_date.isoformat()}|{status}" if days_until_submission is not None and days_until_submission <= 14 else None,
            active=True,
            rank=SEVERITY_ORDER["warning"],
        )

    if status == "Ready For Review":
        return TenderHealthSignal(
            key="watch",
            label="Needs Review",
            summary="Tender is ready for human review before final submission work.",
            detail="The workflow is progressing, but review should happen before the deadline window tightens.",
            css_modifier="watch",
            days_until_submission=days_until_submission,
            submission_bucket="review",
            monitor_level=None,
            notification_key=None,
            active=True,
            rank=SEVERITY_ORDER["watch"],
        )

    if status == "Quoted":
        return TenderHealthSignal(
            key="healthy",
            label="Commercially Progressing",
            summary="Quoted tender with time left before submission.",
            detail="Pricing is underway and there is still reasonable space before the submission date.",
            css_modifier="healthy",
            days_until_submission=days_until_submission,
            submission_bucket="quoted",
            monitor_level=None,
            notification_key=None,
            active=True,
            rank=SEVERITY_ORDER["healthy"],
        )

    return TenderHealthSignal(
        key="healthy",
        label="Healthy",
        summary=(
            f"Due in {days_until_submission} day(s)."
            if days_until_submission is not None
            else "Active tender with no immediate risk."
        ),
        detail="This tender is active and currently outside the warning thresholds.",
        css_modifier="healthy",
        days_until_submission=days_until_submission,
        submission_bucket="healthy",
        monitor_level=None,
        notification_key=None,
        active=True,
        rank=SEVERITY_ORDER["healthy"],
    )
