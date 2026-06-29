from __future__ import annotations

import json
import re
from datetime import date, datetime

from database import db
from models import LLMRunLog, Tender, TenderDocument, TenderItem, TenderQuestion, TenderSubItem
from services.ollama_client import OllamaClient
from services.prompt_service import render_prompt


def _combined_document_text(documents: list[TenderDocument]) -> str:
    return "\n\n".join(
        doc.extracted_text.strip()
        for doc in documents
        if doc.extracted_text and doc.extracted_text.strip()
    )


def _log_run(tender_id: int, task_type: str, model_name: str, prompt: str, response: str, success: bool, error: str | None):
    return LLMRunLog(
        tender_id=tender_id,
        task_type=task_type,
        model_name=model_name,
        prompt=prompt,
        response=response,
        success=success,
        error_message=error,
    )


def _parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    match = re.search(r"(20\d{2}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", cleaned)
    if match:
        return _parse_date_value(match.group(1))
    return None


def _parse_time_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    match = re.search(r"\b(\d{1,2}:\d{2})(?::\d{2})?\s*([AaPp][Mm])?\b", cleaned)
    if not match:
        return cleaned[:50]
    time_value = match.group(1)
    meridiem = match.group(2)
    return f"{time_value} {meridiem.upper()}".strip() if meridiem else time_value


def extract_tender_metadata(
    client: OllamaClient,
    tender: Tender,
    model_name: str,
    documents: list[TenderDocument] | None = None,
) -> tuple[bool, str]:
    selected_documents = documents or list(tender.documents)
    text = _combined_document_text(selected_documents)
    if not text:
        return False, "No extracted document text is available yet."
    prompt = render_prompt("metadata_extraction", tender_text=text[:15000])
    try:
        parsed, raw_response, error = client.generate_json(model_name, prompt)
    except Exception as exc:
        parsed, raw_response, error = None, "", str(exc)
    success = parsed is not None and error is None
    if not success:
        parsed = _fallback_metadata(text)
        raw_response = json.dumps(parsed, indent=2)
        error = None
        success = True
    if success:
        tender.customer_name = parsed.get("customer_name") or tender.customer_name
        tender.tender_number = parsed.get("tender_number") or tender.tender_number
        tender.title = parsed.get("title") or tender.title
        tender.status = parsed.get("status") or tender.status
        tender.submission_date = _parse_date_value(parsed.get("submission_date")) or tender.submission_date
        tender.submission_time = _parse_time_value(parsed.get("submission_time")) or tender.submission_time
        tender.award_date = _parse_date_value(parsed.get("award_date")) or tender.award_date
        tender.currency = parsed.get("currency") or tender.currency
        tender.notes = "\n".join(filter(None, [tender.notes, parsed.get("notes")])).strip() or None
    return success, "Metadata extracted." if success else error or raw_response


def extract_tender_items(
    client: OllamaClient,
    tender: Tender,
    model_name: str,
    documents: list[TenderDocument] | None = None,
) -> tuple[bool, str]:
    selected_documents = documents or list(tender.documents)
    text = _combined_document_text(selected_documents)
    if not text:
        return False, "No extracted document text is available yet."
    prompt = render_prompt("item_extraction", tender_text=text[:20000])
    try:
        parsed, raw_response, error = client.generate_json(model_name, prompt)
    except Exception as exc:
        parsed, raw_response, error = None, "", str(exc)
    if parsed is None or error is not None:
        parsed = _fallback_items(text)
        if not parsed.get("items"):
            return False, error or raw_response
    created = 0
    for item_payload in parsed.get("items", []):
        item = TenderItem(
            tender=tender,
            description=item_payload.get("description") or "Unnamed item",
            quantity_required=item_payload.get("quantity_required") or 0,
            specification_summary=item_payload.get("specification_summary"),
            source_reference=item_payload.get("source_reference"),
            status="Needs Review",
        )
        for sub_payload in item_payload.get("sub_items", []):
            item.sub_items.append(
                TenderSubItem(
                    description=sub_payload.get("description") or "Unnamed sub-item",
                    quantity=sub_payload.get("quantity") or item.quantity_required or 0,
                    notes=sub_payload.get("notes"),
                    status="Needs Review",
                )
            )
        db.session.add(item)
        created += 1
    return True, f"Created {created} items."


def extract_tender_questions(
    client: OllamaClient,
    tender: Tender,
    model_name: str,
    documents: list[TenderDocument] | None = None,
) -> tuple[bool, str]:
    selected_documents = documents or list(tender.documents)
    text = _combined_document_text(selected_documents)
    if not text:
        return False, "No extracted document text is available yet."
    prompt = render_prompt("question_extraction", tender_text=text[:20000])
    try:
        parsed, raw_response, error = client.generate_json(model_name, prompt)
    except Exception as exc:
        parsed, raw_response, error = None, "", str(exc)
    if parsed is None or error is not None:
        parsed = _fallback_questions(text)
        if not parsed.get("questions"):
            return False, error or raw_response
    created = 0
    for question_payload in parsed.get("questions", []):
        db.session.add(
            TenderQuestion(
                tender=tender,
                question_number=question_payload.get("question_number"),
                section=question_payload.get("section"),
                question_text=question_payload.get("question_text") or "",
                source_reference=question_payload.get("source_reference"),
                answer_status="Draft Generated",
            )
        )
        created += 1
    return True, f"Created {created} questions."


def serialize_run_log_payload(message: str, success: bool) -> str:
    return json.dumps({"success": success, "message": message}, indent=2)


def _fallback_metadata(text: str) -> dict:
    first_lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = first_lines[0][:120] if first_lines else "Extracted Tender"
    customer_name = "Needs Review"
    for line in first_lines[:8]:
        if "college" in line.lower() or "trust" in line.lower() or "council" in line.lower():
            customer_name = line[:120]
            break
    submission_time_match = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    submission_date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text)
    return {
        "customer_name": customer_name,
        "tender_number": None,
        "title": title,
        "status": "Metadata Extracted",
        "submission_date": submission_date_match.group(1) if submission_date_match else None,
        "submission_time": submission_time_match.group(1) if submission_time_match else None,
        "award_date": None,
        "currency": "GBP",
        "notes": "Fallback metadata extraction used.",
    }


def _fallback_items(text: str) -> dict:
    items = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        quantity_match = re.search(r"\b(\d{1,4})\b", clean)
        if quantity_match and any(keyword in clean.lower() for keyword in ["laptop", "device", "workstation", "deployment", "warranty", "support"]):
            qty = int(quantity_match.group(1))
            items.append(
                {
                    "description": clean[:180],
                    "quantity_required": qty,
                    "specification_summary": clean[:240],
                    "source_reference": "Fallback extraction",
                    "sub_items": [],
                }
            )
    return {"items": items[:12]}


def _fallback_questions(text: str) -> dict:
    questions = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        q_match = re.match(r"^(Q[\dA-Za-z]+)[\.\): -]+(.+)$", clean)
        if q_match:
            questions.append(
                {
                    "question_number": q_match.group(1),
                    "section": None,
                    "question_text": q_match.group(2).strip(),
                    "source_reference": "Fallback extraction",
                }
            )
            continue
        if clean.endswith("?"):
            questions.append(
                {
                    "question_number": None,
                    "section": None,
                    "question_text": clean,
                    "source_reference": "Fallback extraction",
                }
            )
    return {"questions": questions[:20]}
