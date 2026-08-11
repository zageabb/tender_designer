from types import SimpleNamespace

from services.tender_status import advance_tender_status


def test_automatic_status_can_advance():
    tender = SimpleNamespace(status="New")

    assert advance_tender_status(tender, "Documents Uploaded") is True
    assert tender.status == "Documents Uploaded"


def test_document_upload_cannot_regress_submitted_tender():
    tender = SimpleNamespace(status="Submitted")

    assert advance_tender_status(tender, "Documents Uploaded") is False
    assert tender.status == "Submitted"


def test_extraction_cannot_regress_later_workflow_stage():
    tender = SimpleNamespace(status="Quoted")

    assert advance_tender_status(tender, "Metadata Extracted") is False
    assert tender.status == "Quoted"


def test_unknown_automatic_status_is_ignored():
    tender = SimpleNamespace(status="Submitted")

    assert advance_tender_status(tender, "Unexpected") is False
    assert tender.status == "Submitted"
