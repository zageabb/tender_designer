from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

from services.rfq_service import write_rfq_eml


def test_rfq_eml_contains_html_table_and_plain_text_fallback(tmp_path: Path):
    tender = SimpleNamespace(id=42)
    rfq = SimpleNamespace(
        id=7,
        subject="RFI - TEST-001 - Example Customer",
        supplier_email="supplier@example.com",
    )
    body = (
        "Dear Supplier,\n\n"
        "Please review the following items.\n\n"
        "| Qty | General Item | Specification / Sub-item |\n"
        "| --- | --- | --- |\n"
        "| 2 | 11kV switchgear | 3150A, 31.5kA, IEC 62271 |\n\n"
        "Kind regards,\nTender Designer Team"
    )

    path = write_rfq_eml(tmp_path, tender, rfq, body)
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())

    assert message.is_multipart()

    plain_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))

    assert plain_part is not None
    assert html_part is not None
    assert "| Qty | General Item | Specification / Sub-item |" in plain_part.get_content()

    html = html_part.get_content()
    assert "<table" in html
    assert "border-collapse:collapse" in html
    assert "border:1px solid #b8c2cc" in html
    assert "11kV switchgear" in html
    assert "3150A, 31.5kA, IEC 62271" in html
