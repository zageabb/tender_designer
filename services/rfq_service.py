from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from models import RFQ, RFQLine, Tender, TenderItem, TenderSubItem
from services.file_storage import ensure_tender_directories
from services.prompt_service import render_prompt
from services.settings_service import get_setting


def _format_item_rows(lines: list[dict]) -> str:
    formatted = ["Qty | General Item | Specification / Sub-item", "--- | --- | ---"]
    for line in lines:
        formatted.append(
            f"{line['quantity']} | {line['parent_description']} | {line['description']}"
        )
    return "\n".join(formatted)


def _format_optional_date(value) -> str:
    return value.isoformat() if value else "Not set"


def _clean_rfq_body(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def build_rfq_email_text(tender: Tender, supplier_name: str, lines: list[dict]) -> tuple[str, str]:
    signature = get_setting("default_email_signature", "") or ""
    subject = f"RFQ - {tender.tender_number} - {tender.customer_name}"
    tender_reference = tender.tender_number
    if tender.title:
        tender_reference = f"{tender_reference} - {tender.title}"
    body = render_prompt(
        "rfq_email_body",
        supplier_display_name=supplier_name or "Supplier",
        supplier_name=supplier_name or "",
        customer_name=tender.customer_name or "",
        tender_number=tender.tender_number or "",
        tender_title=tender.title or "",
        tender_reference=tender_reference,
        tender_status=tender.status or "",
        submission_date=_format_optional_date(tender.submission_date),
        award_date=_format_optional_date(tender.award_date),
        tender_currency=tender.currency or "",
        line_items_table=_format_item_rows(lines),
        email_signature=signature,
    )
    body = _clean_rfq_body(body)
    return subject, body


def create_rfq_for_selection(
    db,
    data_dir: Path,
    tender: Tender,
    supplier_name: str,
    supplier_email: str,
    selected_item_ids: list[int],
    selected_sub_item_ids: list[int],
) -> RFQ:
    lines: list[dict] = []
    item_lookup = {item.id: item for item in tender.items}
    selected_sub_items: list[TenderSubItem] = []

    for item_id in selected_item_ids:
        item = item_lookup.get(item_id)
        if item is None:
            continue
        if item.sub_items:
            for sub_item in item.sub_items:
                if sub_item.id not in selected_sub_item_ids:
                    selected_sub_items.append(sub_item)
        else:
            lines.append(
                {
                    "parent_description": item.description,
                    "description": item.specification_summary or item.description,
                    "quantity": item.quantity_required,
                    "tender_item_id": item.id,
                    "tender_sub_item_id": None,
                }
            )

    for sub_item in tender_sub_items_for_ids(tender, selected_sub_item_ids):
        selected_sub_items.append(sub_item)

    seen_sub_item_ids = set()
    for sub_item in selected_sub_items:
        if sub_item.id in seen_sub_item_ids:
            continue
        seen_sub_item_ids.add(sub_item.id)
        lines.append(
            {
                "parent_description": sub_item.tender_item.description if sub_item.tender_item else sub_item.description,
                "description": sub_item.description,
                "quantity": sub_item.quantity,
                "tender_item_id": sub_item.tender_item_id,
                "tender_sub_item_id": sub_item.id,
            }
        )

    subject, body = build_rfq_email_text(tender, supplier_name, lines)
    rfq = RFQ(
        tender=tender,
        supplier_name=supplier_name or None,
        supplier_email=supplier_email or None,
        subject=subject,
        introduction_text=body,
        status="Draft",
    )
    for line in lines:
        rfq.lines.append(
            RFQLine(
                description=line["description"],
                quantity=line["quantity"],
                tender_item_id=line["tender_item_id"],
                tender_sub_item_id=line["tender_sub_item_id"],
            )
        )
    db.session.add(rfq)
    db.session.flush()
    rfq_path = write_rfq_eml(data_dir, tender, rfq, body)
    rfq.eml_file_path = str(rfq_path)
    return rfq


def write_rfq_eml(data_dir: Path, tender: Tender, rfq: RFQ, body: str) -> Path:
    tender_dir = ensure_tender_directories(data_dir, tender.id)
    rfq_dir = tender_dir / "rfqs"
    rfq_dir.mkdir(parents=True, exist_ok=True)
    message = EmailMessage()
    message["Subject"] = rfq.subject
    if rfq.supplier_email:
        message["To"] = rfq.supplier_email
    message["From"] = "noreply@tenderdesigner.local"
    message.set_content(body)
    destination = rfq_dir / f"rfq_{rfq.id}.eml"
    destination.write_bytes(message.as_bytes())
    return destination


def tender_sub_items_for_ids(tender: Tender, selected_sub_item_ids: list[int]) -> list[TenderSubItem]:
    selected = set(selected_sub_item_ids)
    return [
        sub_item
        for item in tender.items
        for sub_item in item.sub_items
        if sub_item.id in selected
    ]
