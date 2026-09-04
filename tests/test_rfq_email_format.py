from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

from services.markdown_tools import render_markdown_html
from services.rfq_service import _render_line_items_table, write_rfq_eml


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


def test_multiline_specification_stays_in_third_column(tmp_path: Path):
    specification = (
        "3.1 Item A: Student Laptops\n"
        "The proposed student laptop must meet or exceed the following minimum requirements:\n"
        "14-inch display;\n"
        "8 GB RAM;\n"
        "128 GB SSD;\n"
        "Windows 11 Education;\n"
        "TPM 2.0;\n"
        "Wi-Fi 6 or better."
    )
    table = _render_line_items_table(
        [
            {
                "template_context": {
                    "line_quantity": "1278.00",
                    "item_description": "Student laptop",
                    "line_description": specification,
                }
            }
        ]
    )

    data_rows = [line for line in table.splitlines() if line.startswith("| 1278.00")]
    assert len(data_rows) == 1
    assert data_rows[0].count("|") == 4
    assert "Student laptop" in data_rows[0]
    assert "3.1 Item A: Student Laptops<br>" in data_rows[0]
    assert "14-inch display;<br>8 GB RAM;<br>128 GB SSD;" in data_rows[0]

    preview_html = str(render_markdown_html(table))
    assert "<td>Student laptop</td>" in preview_html
    assert "Student Laptops<br>The proposed student laptop" in preview_html
    assert "14-inch display;<br>8 GB RAM;<br>128 GB SSD;" in preview_html

    tender = SimpleNamespace(id=42)
    rfq = SimpleNamespace(
        id=8,
        subject="RFI - TEST-002 - Example Trust",
        supplier_email="supplier@example.com",
    )
    body = f"Dear Supplier,\n\nItems:\n{table}\n\nKind regards,\nTender Designer Team"
    path = write_rfq_eml(tmp_path, tender, rfq, body)
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())

    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()

    assert "<br>" not in plain
    assert "| 1278.00 | Student laptop | 3.1 Item A: Student Laptops / The proposed student laptop" in plain
    assert "<td style=" in html
    assert "Student Laptops<br>The proposed student laptop" in html
    assert "14-inch display;<br>8 GB RAM;<br>128 GB SSD;" in html
