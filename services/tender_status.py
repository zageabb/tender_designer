from __future__ import annotations

from typing import Protocol


TENDER_STATUS_ORDER = [
    "New",
    "Documents Uploaded",
    "Metadata Extracted",
    "Items Extracted",
    "Ready For Review",
    "RFI Required",
    "Quoted",
    "Submitted",
    "Awarded",
    "No Bid",
    "Lost",
    "Cancelled",
]

_STATUS_RANK = {status: index for index, status in enumerate(TENDER_STATUS_ORDER)}


class TenderWithStatus(Protocol):
    status: str


def advance_tender_status(tender: TenderWithStatus, candidate_status: str) -> bool:
    """Advance an automatic workflow status without overwriting a later state."""
    current_rank = _STATUS_RANK.get(tender.status)
    candidate_rank = _STATUS_RANK.get(candidate_status)
    if current_rank is None or candidate_rank is None or candidate_rank <= current_rank:
        return False
    tender.status = candidate_status
    return True
