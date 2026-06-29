from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from models import RFQ, RFQLine, Tender, TenderItem, TenderSubItem
from services.file_storage import ensure_tender_directories
from services.prompt_service import render_prompt, render_template_text
from services.settings_service import get_setting


def _clean_rendered_block(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def _format_optional_date(value) -> str:
    return value.isoformat() if value else "Not set"


def _format_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _line_template_context(item: TenderItem | None, sub_item: TenderSubItem | None) -> dict[str, str]:
    line_quantity = sub_item.quantity if sub_item is not None else (item.quantity_required if item is not None else "")
    line_description = ""
    if sub_item is not None:
        line_description = item.specification_summary if item is not None and item.specification_summary else sub_item.description
    elif item is not None:
        line_description = item.specification_summary or item.description
    context = {
        "line_quantity": _format_value(line_quantity),
        "line_description": _format_value(line_description),
        "line_status": _format_value(sub_item.status if sub_item is not None else (item.status if item is not None else "")),
        "line_currency": _format_value(item.tender.currency if item is not None and item.tender is not None else ""),
    }
    if item is not None:
        context.update(
            {
                "item_id": _format_value(item.id),
                "item_tender_id": _format_value(item.tender_id),
                "item_description": _format_value(item.description),
                "item_quantity_required": _format_value(item.quantity_required),
                "item_unit_price": _format_value(item.unit_price),
                "item_total_price": _format_value(item.total_price),
                "item_status": _format_value(item.status),
                "item_specification_summary": _format_value(item.specification_summary),
                "item_source_reference": _format_value(item.source_reference),
                "item_created_at": _format_value(item.created_at),
                "item_updated_at": _format_value(item.updated_at),
            }
        )
    else:
        context.update(
            {
                "item_id": "",
                "item_tender_id": "",
                "item_description": "",
                "item_quantity_required": "",
                "item_unit_price": "",
                "item_total_price": "",
                "item_status": "",
                "item_specification_summary": "",
                "item_source_reference": "",
                "item_created_at": "",
                "item_updated_at": "",
            }
        )
    if sub_item is not None:
        context.update(
            {
                "sub_item_id": _format_value(sub_item.id),
                "sub_item_tender_item_id": _format_value(sub_item.tender_item_id),
                "sub_item_description": _format_value(sub_item.description),
                "sub_item_quantity": _format_value(sub_item.quantity),
                "sub_item_unit_price": _format_value(sub_item.unit_price),
                "sub_item_total_price": _format_value(sub_item.total_price),
                "sub_item_supplier_name": _format_value(sub_item.supplier_name),
                "sub_item_supplier_reference": _format_value(sub_item.supplier_reference),
                "sub_item_status": _format_value(sub_item.status),
                "sub_item_notes": _format_value(sub_item.notes),
                "sub_item_created_at": _format_value(sub_item.created_at),
                "sub_item_updated_at": _format_value(sub_item.updated_at),
            }
        )
    else:
        context.update(
            {
                "sub_item_id": "",
                "sub_item_tender_item_id": "",
                "sub_item_description": "",
                "sub_item_quantity": "",
                "sub_item_unit_price": "",
                "sub_item_total_price": "",
                "sub_item_supplier_name": "",
                "sub_item_supplier_reference": "",
                "sub_item_status": "",
                "sub_item_notes": "",
                "sub_item_created_at": "",
                "sub_item_updated_at": "",
            }
        )
    return context


def _render_line_items_table(lines: list[dict]) -> str:
    row_template = render_prompt("rfq_line_item_row")
    rows = []
    for line in lines:
        rows.append(
            _clean_rendered_block(
                render_template_text(row_template, **line["template_context"])
            )
        )
    table_block = render_prompt(
        "rfq_line_items_table",
        line_items_rows="\n".join(filter(None, rows)),
    )
    return _clean_rendered_block(table_block)


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
        line_items_table=_render_line_items_table(lines),
        email_signature=signature,
    )
    body = _clean_rendered_block(body)
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
                    "description": item.specification_summary or item.description,
                    "quantity": item.quantity_required,
                    "tender_item_id": item.id,
                    "tender_sub_item_id": None,
                    "template_context": _line_template_context(item, None),
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
                "description": (
                    sub_item.tender_item.specification_summary
                    if sub_item.tender_item and sub_item.tender_item.specification_summary
                    else sub_item.description
                ),
                "quantity": sub_item.quantity,
                "tender_item_id": sub_item.tender_item_id,
                "tender_sub_item_id": sub_item.id,
                "template_context": _line_template_context(sub_item.tender_item, sub_item),
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
