from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal

from pathlib import Path

from database import db
from models import ChatAction, ChatMessage, ChatSession, ChatUpload, MailboxMessage, Tender, TenderDocument, TenderItem, TenderQuestion, TenderSubItem
from services.file_storage import ensure_tender_directories, save_tender_bytes
from services.markdown_tools import extracted_text_suffix
from services.ollama_client import OllamaClient
from services.prompt_service import render_prompt
from services.settings_service import get_setting, get_task_model

MAX_CHAT_DOCUMENT_CONTEXT_CHARS = 20000


ALLOWED_UPDATE_FIELDS = {
    "Tender": {"customer_name", "title", "status", "submission_time", "currency", "notes"},
    "TenderItem": {"description", "quantity_required", "unit_price", "status", "specification_summary"},
    "TenderSubItem": {"description", "quantity", "unit_price", "status", "notes"},
    "RFQ": {"supplier_name", "supplier_email", "status", "subject", "notes"},
    "TenderQuestion": {"answer_text", "suggested_answer", "answer_status"},
}


def _session_scope_context(page_context: dict | None, tender_id: int | None) -> dict:
    if tender_id is not None:
        return {"tender_id": tender_id}
    context = page_context or {}
    return {
        "page": context.get("page"),
        "table": context.get("table"),
        "selected_record_id": context.get("selected_record_id"),
    }


def get_or_create_session(db, tender_id: int | None, page_context: dict | None) -> ChatSession:
    scope_context = _session_scope_context(page_context, tender_id)
    scope_json = json.dumps(scope_context, sort_keys=True)
    query = ChatSession.query
    if tender_id is None:
        query = query.filter(ChatSession.tender_id.is_(None), ChatSession.page_context_json == scope_json)
    else:
        query = query.filter_by(tender_id=tender_id)
    session = query.order_by(ChatSession.updated_at.desc()).first()
    if session is None:
        session = ChatSession(tender_id=tender_id, page_context_json=scope_json)
        db.session.add(session)
        db.session.flush()
    return session


def add_chat_message(
    db,
    chat_session: ChatSession,
    role: str,
    message_text: str,
    intermediate_steps: list[str] | None = None,
    actions: list[dict] | None = None,
) -> ChatMessage:
    chat_session.updated_at = datetime.utcnow()
    message = ChatMessage(
        chat_session=chat_session,
        role=role,
        message_text=message_text,
        intermediate_steps_json=json.dumps(intermediate_steps or []),
        proposed_actions_json=json.dumps(actions or []),
    )
    db.session.add(message)
    return message


def get_recent_messages(chat_session: ChatSession | None, limit: int = 24) -> list[dict]:
    if chat_session is None:
        return []
    messages = (
        ChatMessage.query.filter_by(chat_session_id=chat_session.id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .all()
    )
    payload = []
    for message in messages:
        try:
            steps = json.loads(message.intermediate_steps_json) if message.intermediate_steps_json else []
        except json.JSONDecodeError:
            steps = []
        payload.append(
            {
                "role": message.role,
                "message_text": message.message_text,
                "intermediate_steps": steps,
                "created_at": message.created_at.isoformat(),
            }
        )
    return payload


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _heuristic_create_tender_request(normalized: str) -> bool:
    verb_match = any(word in normalized for word in {"create", "make", "start", "open", "build", "initiate"})
    noun_match = any(word in normalized for word in {"tender", "bid", "opportunity"})
    reference_match = any(
        phrase in normalized
        for phrase in {"this", "document", "file", "upload", "from this", "from it"}
    )
    return ("create tender" in normalized) or (verb_match and noun_match and reference_match) or (verb_match and noun_match)


def _heuristic_create_tender_from_text_request(normalized: str, raw_message: str) -> bool:
    if not _heuristic_create_tender_request(normalized):
        return False
    stripped = raw_message.strip()
    if len(stripped) < 80:
        return False
    return stripped.count("\n") >= 2 or ":" in stripped or "-" in stripped


def _heuristic_add_items_request(normalized: str, raw_message: str) -> bool:
    action_match = any(
        phrase in normalized
        for phrase in {
            "make items from this list",
            "create items from this list",
            "add items from this list",
            "make items",
            "create items",
            "add items",
        }
    )
    line_match = bool(re.search(r"(?m)^\s*\d+\s*x\s+.+", raw_message))
    return action_match and line_match


def _heuristic_answer_questions_request(normalized: str) -> bool:
    action_match = any(
        phrase in normalized
        for phrase in {
            "answer the questions",
            "fill the questions",
            "fill in the questions",
            "fill in the answers",
            "fill answers",
            "update the answers",
            "update answers",
            "provide the answers",
            "these are the answers",
            "use this file to fill answers",
            "use this file to update answers",
            "use this document to fill answers",
            "use this document to update answers",
            "draft answers",
            "draft the answers",
            "use this file to answer",
            "use this document to answer",
            "populate answers",
            "add answers only",
        }
    )
    question_match = "question" in normalized or "questions" in normalized or "answers" in normalized
    return action_match and question_match


def _question_answer_mode(normalized: str) -> str:
    if any(
        phrase in normalized
        for phrase in {
            "answers only",
            "final answers",
            "answer only",
            "fill final answers",
            "update the answers",
            "update answers",
            "provide the answers",
            "these are the answers",
            "fill in the answers",
            "use this file to update answers",
            "use this document to update answers",
            "add answers only",
        }
    ):
        return "final_only"
    return "draft"


def _parse_item_request_lines(message: str) -> list[dict]:
    items: list[dict] = []
    current_item: dict | None = None
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(\d+(?:\.\d+)?)\s*x\s+(.+)$", line, flags=re.IGNORECASE)
        if match:
            quantity = Decimal(match.group(1))
            details = match.group(2).strip()
            description = re.split(r"\s+[–-]\s+", details, maxsplit=1)[0].strip(" .")
            if not description:
                description = details[:120]
            current_item = {
                "description": description[:255],
                "quantity_required": str(quantity.normalize() if quantity == quantity.to_integral() else quantity),
                "specification_summary": details,
                "status": "Needs Review",
                "source_reference": "Added from AI chat request.",
                "sub_items": [],
            }
            items.append(current_item)
            continue
        if current_item is None:
            continue
        bullet_match = re.match(r"^(?:[-*]\s+|sub[- ]?item[: ]+)(.+)$", line, flags=re.IGNORECASE)
        if not bullet_match and raw_line[:1].isspace():
            bullet_match = re.match(r"^(.+)$", line)
        if not bullet_match:
            continue
        sub_details = bullet_match.group(1).strip(" .")
        if not sub_details:
            continue
        sub_quantity_match = re.match(r"^(\d+(?:\.\d+)?)\s*x\s+(.+)$", sub_details, flags=re.IGNORECASE)
        if sub_quantity_match:
            sub_quantity = Decimal(sub_quantity_match.group(1))
            sub_description = sub_quantity_match.group(2).strip()
        else:
            sub_quantity = Decimal("1")
            sub_description = sub_details
        current_item["sub_items"].append(
            {
                "description": sub_description[:255],
                "quantity": str(sub_quantity.normalize() if sub_quantity == sub_quantity.to_integral() else sub_quantity),
                "status": "Needs Review",
                "notes": sub_details,
            }
        )
    return items


def _currency(value: Decimal | int | float | None, code: str) -> str:
    if value is None:
        return f"{code} 0.00"
    return f"{code} {Decimal(value):,.2f}"


def _markdown_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _question_list_context(tender: Tender) -> str:
    if not tender.questions:
        return "No tender questions are currently stored."
    lines = []
    for question in tender.questions:
        lines.append(
            f"- Question Number: {question.question_number or '-'}\n"
            f"  Section: {question.section or '-'}\n"
            f"  Status: {question.answer_status or '-'}\n"
            f"  Question: {question.question_text}"
        )
    return "\n".join(lines)


def _documents_for_question_answering(tender: Tender, selected_document_ids: list[int] | None = None) -> list[TenderDocument]:
    if selected_document_ids:
        selected_ids = {int(document_id) for document_id in selected_document_ids}
        documents = [document for document in tender.documents if document.id in selected_ids]
        if documents:
            return documents
    if tender.documents:
        latest = max(tender.documents, key=lambda document: document.uploaded_at or datetime.min)
        return [latest]
    return []


def _top_missing_areas(tender: Tender) -> list[str]:
    missing: list[str] = []
    if not tender.documents:
        missing.append("No tender documents have been uploaded.")
    if not tender.items:
        missing.append("No tender items have been extracted or added yet.")
    if any(item.status in {"New", "Needs Review", "RFQ Required", "RFI Required"} for item in tender.items):
        missing.append("Some tender items still need review or supplier pricing.")
    unanswered = [question for question in tender.questions if question.answer_status != "Answered"]
    if unanswered:
        missing.append(f"{len(unanswered)} tender questions are still not marked as answered.")
    pending_rfqs = [rfq for rfq in tender.rfqs if rfq.status in {"Draft", "Downloaded", "Sent Manually"}]
    if pending_rfqs:
        missing.append(f"{len(pending_rfqs)} RFIs are still awaiting response or completion.")
    return missing


def _summarize_items(tender: Tender) -> tuple[str, list[str]]:
    if not tender.items:
        return "There are no tender items on this tender yet.", [
            "Checked the current tender context.",
            "No TenderItem records were found.",
        ]
    lines = []
    for item in tender.items[:8]:
        sub_count = len(item.sub_items)
        sub_text = f", {sub_count} sub-items" if sub_count else ""
        lines.append(
            f"- {item.description}: qty {item.quantity_required}, status {item.status}{sub_text}, "
            f"total {_currency(item.total_price, tender.currency)}"
        )
    message = "Here is the current item summary:\n" + "\n".join(lines)
    return message, [
        "Read the tender's item list from the database.",
        "Included quantity, status, sub-item count, and current totals.",
    ]


def _summarize_questions(tender: Tender, unanswered_only: bool = False) -> tuple[str, list[str]]:
    questions = tender.questions
    if unanswered_only:
        questions = [question for question in questions if question.answer_status != "Answered"]
    if not questions:
        if unanswered_only:
            return "All tender questions are currently marked as answered.", [
                "Checked the current tender's question list.",
                "No unanswered questions remained.",
            ]
        return "There are no tender questions on this tender yet.", [
            "Checked the current tender's question list.",
            "No TenderQuestion records were found.",
        ]
    lines = [
        f"- {question.question_number or 'Question'}: {question.question_text[:110]}"
        f" ({question.answer_status})"
        for question in questions[:8]
    ]
    intro = "These questions are still open:" if unanswered_only else "Here are the current tender questions:"
    return intro + "\n" + "\n".join(lines), [
        "Checked the current tender's question list.",
        "Filtered by answer status where relevant.",
    ]


def _summarize_rfqs(tender: Tender, awaiting_only: bool = False) -> tuple[str, list[str]]:
    rfqs = tender.rfqs
    if awaiting_only:
        rfqs = [rfq for rfq in rfqs if rfq.status in {"Draft", "Downloaded", "Sent Manually"}]
    if not rfqs:
        if awaiting_only:
            return "There are no RFIs currently awaiting a supplier response.", [
                "Checked the current tender's RFI records.",
                "No RFIs matched the pending-response statuses.",
            ]
        return "There are no RFIs on this tender yet.", [
            "Checked the current tender's RFI records.",
            "No RFI entries were found.",
        ]
    lines = [
        f"- RFI #{rfq.id}: {rfq.subject} ({rfq.status})"
        + (f", supplier {rfq.supplier_name}" if rfq.supplier_name else "")
        for rfq in rfqs[:8]
    ]
    intro = "These RFIs are still awaiting response or completion:\n" if awaiting_only else "Here is the RFI status summary:\n"
    return intro + "\n".join(lines), [
        "Read the tender's RFI list from the database.",
        "Included supplier and current workflow status.",
    ]


def _summarize_documents(tender: Tender) -> tuple[str, list[str]]:
    if not tender.documents:
        return "No documents are linked to this tender yet.", [
            "Checked the tender's document list.",
            "No TenderDocument records were found.",
        ]
    lines = [
        f"- {document.original_filename}: {'Processed' if document.processed else 'Pending'}"
        for document in tender.documents[:8]
    ]
    return "These documents are currently attached:\n" + "\n".join(lines), [
        "Read the tender's uploaded documents.",
        "Included processed state for each visible document.",
    ]


def _best_price_response(tender: Tender) -> tuple[str, list[str]]:
    parsed_candidates: list[tuple[str, Decimal]] = []
    for response in tender.supplier_responses:
        if not response.parsed_json:
            continue
        try:
            payload = json.loads(response.parsed_json)
        except json.JSONDecodeError:
            continue
        total = Decimal("0.00")
        for line in payload.get("lines", []):
            value = line.get("total_price")
            if value is not None:
                total += Decimal(str(value))
        if total > 0:
            parsed_candidates.append((response.supplier_name or "Unknown supplier", total))
    if not parsed_candidates:
        return "I don't have enough parsed supplier pricing yet to compare quotes.", [
            "Checked supplier responses for parsed pricing JSON.",
            "No usable totals were available for comparison.",
        ]
    supplier_name, total = min(parsed_candidates, key=lambda pair: pair[1])
    return f"The best parsed supplier total so far is from {supplier_name} at {_currency(total, tender.currency)}.", [
        "Read parsed supplier response totals from the database.",
        "Compared the available totals and selected the lowest one.",
    ]


def _suggest_next_actions(tender: Tender) -> tuple[str, list[str]]:
    missing = _top_missing_areas(tender)
    if not missing:
        return "This tender looks well populated. The next step is likely final review and submission prep.", [
            "Checked documents, items, questions, and RFQs.",
            "No obvious data gaps were found.",
        ]
    return "The main gaps I can see are:\n" + "\n".join(f"- {entry}" for entry in missing[:6]), [
        "Reviewed the tender's documents, items, RFQs, and questions.",
        "Summarised the most obvious workflow gaps.",
    ]


def _serialize_page_context(page_context: dict | None) -> str:
    if not page_context:
        return "No explicit page context was supplied."
    lines = [f"- {key}: {value}" for key, value in page_context.items()]
    return "\n".join(lines)


def _serialize_mailbox_context(page_context: dict | None, limit: int = 8) -> str:
    context = page_context or {}
    selected_message_id = context.get("selected_mailbox_message_id")
    visible_ids = context.get("visible_mailbox_message_ids") or []
    message_ids: list[int] = []
    if selected_message_id:
        message_ids.append(int(selected_message_id))
    for value in visible_ids:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed not in message_ids:
            message_ids.append(parsed)
    if not message_ids:
        return "No mailbox context was supplied."
    messages = MailboxMessage.query.filter(MailboxMessage.id.in_(message_ids[:limit])).order_by(MailboxMessage.received_at.desc().nullslast()).all()
    if not messages:
        return "No mailbox messages were found for the supplied context."
    lines = ["Mailbox Messages:"]
    for message in messages[:limit]:
        lines.append(
            f"- Message #{message.id} | {message.received_at.isoformat() if message.received_at else '-'} | "
            f"from {message.sender_email or message.sender_name or '-'} | subject {message.subject or '-'}"
        )
        if message.body_text:
            lines.append(f"  Body: {message.body_text[:500]}")
        if message.attachments:
            lines.append("  Attachments: " + ", ".join(attachment.original_filename for attachment in message.attachments[:6]))
    return "\n".join(lines)


def _serialize_tender_context(tender: Tender | None) -> str:
    if tender is None:
        return "No active tender context is available."
    lines = [
        f"Tender Number: {tender.tender_number}",
        f"Customer: {tender.customer_name}",
        f"Title: {tender.title or '-'}",
        f"Status: {tender.status}",
        f"Submission Date: {tender.submission_date.isoformat() if tender.submission_date else '-'}",
        f"Submission Time: {tender.submission_time or '-'}",
        f"Award Date: {tender.award_date.isoformat() if tender.award_date else '-'}",
        f"Currency: {tender.currency}",
        f"Tender Value: {_currency(tender.tender_value, tender.currency)}",
        f"Document Count: {len(tender.documents)}",
        f"Item Count: {len(tender.items)}",
        f"Question Count: {len(tender.questions)}",
        f"RFQ Count: {len(tender.rfqs)}",
        f"Mailbox Email Count: {len(tender.mailbox_links)}",
        "Top Items:",
    ]
    for item in tender.items[:8]:
        lines.append(
            f"- {item.description} | qty {item.quantity_required} | status {item.status} | total {_currency(item.total_price, tender.currency)}"
        )
    lines.append("Open Questions:")
    for question in [question for question in tender.questions if question.answer_status != "Answered"][:8]:
        lines.append(f"- {question.question_number or 'Question'} | {question.answer_status} | {question.question_text[:140]}")
    lines.append("Documents:")
    for document in tender.documents[:8]:
        lines.append(f"- {document.original_filename} | {'Processed' if document.processed else 'Pending'}")
    if tender.mailbox_links:
        lines.append("Linked Mailbox Messages:")
        for link in tender.mailbox_links[:8]:
            message = link.mailbox_message
            lines.append(
                f"- Email #{message.id} | {message.subject or '-'} | from {message.sender_email or message.sender_name or '-'} | "
                f"attachments {len(message.attachments)}"
            )
    return "\n".join(lines)


def _serialize_document_text_context(
    tender: Tender | None,
    selected_document_ids: list[int] | None = None,
    limit: int = MAX_CHAT_DOCUMENT_CONTEXT_CHARS,
) -> str:
    if tender is None:
        return "No active tender document text is available."
    if not selected_document_ids:
        return "No tender documents were selected for chat context."
    selected_ids = {int(document_id) for document_id in selected_document_ids}
    sections: list[str] = []
    total_length = 0
    processed_count = 0
    for document in tender.documents:
        if document.id not in selected_ids:
            continue
        text = (document.extracted_text or "").strip()
        if not text:
            continue
        processed_count += 1
        section = f"Document: {document.original_filename}\n{text}"
        remaining = limit - total_length
        if remaining <= 0:
            break
        if len(section) > remaining:
            section = section[:remaining].rstrip() + "\n[Document text truncated]"
        sections.append(section)
        total_length += len(section) + 2
        if total_length >= limit:
            break
    if not sections:
        return "Selected tender documents do not currently have extracted text available."
    header = (
        f"Extracted text from {len(sections)} document(s)"
        + (" (truncated for chat context):" if total_length >= limit else ":")
    )
    if processed_count > len(sections):
        header += f"\nAdditional processed documents were omitted after the {limit}-character context limit."
    return header + "\n\n" + "\n\n---\n\n".join(sections)


def _list_tenders() -> list[Tender]:
    return (
        Tender.query.order_by(
            Tender.submission_date.is_(None),
            Tender.submission_date.asc(),
            Tender.updated_at.desc(),
        ).all()
    )


def _serialize_tender_list_context(limit: int = 24) -> str:
    tenders = _list_tenders()
    if not tenders:
        return "There are no tenders in the system yet."
    status_counts: dict[str, int] = {}
    for tender in tenders:
        status_counts[tender.status] = status_counts.get(tender.status, 0) + 1
    lines = [
        f"Total tenders: {len(tenders)}",
        "Status counts:",
    ]
    for status, count in sorted(status_counts.items(), key=lambda pair: (-pair[1], pair[0])):
        lines.append(f"- {status}: {count}")
    lines.append("Visible tenders:")
    for tender in tenders[:limit]:
        lines.append(
            f"- {tender.tender_number} | {tender.customer_name} | {tender.title or '-'} | "
            f"status {tender.status} | submission {tender.submission_date.isoformat() if tender.submission_date else '-'} | "
            f"award {tender.award_date.isoformat() if tender.award_date else '-'} | "
            f"value {_currency(tender.tender_value, tender.currency)}"
        )
    if len(tenders) > limit:
        lines.append(f"Additional tenders omitted: {len(tenders) - limit}")
    return "\n".join(lines)


def _summarize_tender_list() -> tuple[str, list[str]]:
    tenders = _list_tenders()
    if not tenders:
        return "There are no tenders in the system yet.", [
            "Checked the tender list page context.",
            "No Tender records were found in the database.",
        ]
    lines = [
        f"- {tender.tender_number}: {tender.customer_name}, {tender.status}, submission {tender.submission_date.isoformat() if tender.submission_date else '-'}"
        for tender in tenders[:10]
    ]
    return f"There are currently {len(tenders)} tenders in the system.\n" + "\n".join(lines), [
        "Read the tender list from the database using the same ordering as the list page.",
        "Included the first visible tenders with customer, status, and submission date.",
    ]


def _summarize_submission_schedule() -> tuple[str, list[str]]:
    tenders = [tender for tender in _list_tenders() if tender.submission_date]
    if not tenders:
        return "None of the current tenders have a submission date set yet.", [
            "Checked the tender list for submission dates.",
            "No tenders had a populated submission_date.",
        ]
    lines = [
        f"- {tender.submission_date.isoformat()}: {tender.tender_number} for {tender.customer_name} ({tender.status})"
        for tender in tenders[:10]
    ]
    return "Here are the upcoming tender submissions:\n" + "\n".join(lines), [
        "Read the tender list ordered by submission date.",
        "Returned the earliest tenders with submission dates set.",
    ]


def _summarize_tender_statuses() -> tuple[str, list[str]]:
    tenders = _list_tenders()
    if not tenders:
        return "There are no tenders in the system yet.", [
            "Checked the tender list page context.",
            "No Tender records were found in the database.",
        ]
    status_counts: dict[str, int] = {}
    for tender in tenders:
        status_counts[tender.status] = status_counts.get(tender.status, 0) + 1
    lines = [f"- {status}: {count}" for status, count in sorted(status_counts.items(), key=lambda pair: (-pair[1], pair[0]))]
    return "Tender status summary:\n" + "\n".join(lines), [
        "Counted all tender records by their current status.",
        "Sorted the summary by largest status groups first.",
    ]


def _summarize_tenders_needing_attention() -> tuple[str, list[str]]:
    tenders = _list_tenders()
    if not tenders:
        return "There are no tenders in the system yet.", [
            "Checked the tender list page context.",
            "No Tender records were found in the database.",
        ]
    flagged: list[str] = []
    for tender in tenders:
        reasons: list[str] = []
        if not tender.submission_date:
            reasons.append("no submission date")
        if not tender.documents:
            reasons.append("no documents")
        if not tender.items:
            reasons.append("no items")
        unanswered = sum(1 for question in tender.questions if question.answer_status != "Answered")
        if unanswered:
            reasons.append(f"{unanswered} unanswered questions")
        if reasons:
            flagged.append(f"- {tender.tender_number}: {', '.join(reasons)}")
    if not flagged:
        return "The current tender list does not show any obvious gaps from documents, items, or unanswered questions.", [
            "Reviewed each tender for missing dates, documents, items, and unanswered questions.",
            "No obvious attention flags were found.",
        ]
    return "These tenders look like they need attention:\n" + "\n".join(flagged[:10]), [
        "Reviewed each tender for missing submission dates, documents, items, and unanswered questions.",
        "Returned the first tenders with visible gaps.",
    ]


def _computer_finder_context_response(page_context: dict | None) -> tuple[str, list[str]]:
    context = page_context or {}
    spec = _markdown_text(context.get("computer_spec"))
    status = _markdown_text(context.get("computer_finder_status"))
    result = _markdown_text(context.get("computer_finder_result"))
    diagnostics = _markdown_text(context.get("computer_finder_diagnostics"))
    sources = _markdown_text(context.get("computer_finder_sources"))
    allowed_domains = _markdown_text(context.get("computer_finder_allowed_domains"))
    searxng_url = _markdown_text(context.get("computer_finder_searxng_url"))
    searxng_engines = _markdown_text(context.get("computer_finder_searxng_engines"))

    if not spec and not result and not diagnostics:
        return (
            "I’m on the Computer Finder page. Paste a machine specification into the finder panel, run **Search And Match**, "
            "then ask me to explain the fit, refine the spec, or interpret the search diagnostics.",
            [
                "Read the current Computer Finder page context from the UI.",
                "No spec, search result, or diagnostics were present in the page context yet.",
            ],
        )

    lines = ["I’m reading the current Computer Finder page context."]
    if spec:
        lines.append(f"\n**Current spec:**\n{spec}")
    if status:
        lines.append(f"\n**Finder status:** {status}")
    if result:
        lines.append(f"\n**Current result:**\n{result[:1200]}")
    elif diagnostics:
        lines.append(f"\n**Current search diagnostics:**\n{diagnostics[:1600]}")
    if sources:
        lines.append(f"\n**Visible sources:**\n{sources[:1000]}")
    if searxng_url or allowed_domains:
        lines.append("\n**Search setup:**")
        if searxng_url:
            lines.append(f"- SearXNG: {searxng_url}")
        if searxng_engines:
            lines.append(f"- SearXNG engines: {searxng_engines}")
        if allowed_domains:
            lines.append(f"- Allowed domains: {', '.join(allowed_domains.splitlines()[:12])}")
    lines.append("\nAsk me what to change in the spec, why a search failed, or how to compare a returned model against the requirement.")
    return "\n".join(lines), [
        "Read the current Computer Finder page context from the UI.",
        "Used the spec, finder status, result text, source list, and diagnostics available on the page.",
    ]


def _general_llm_chat_response(message: str, page_context: dict | None, tender: Tender | None, client, model_name: str) -> tuple[str, list[str]]:
    selected_document_ids = page_context.get("selected_document_ids") if page_context else None
    tender_context = _serialize_tender_context(tender)
    if tender is None and (page_context or {}).get("page") == "tender_list":
        tender_context = _serialize_tender_list_context()
    prompt = render_prompt(
        "chat_general_answer",
        page_context=_serialize_page_context(page_context) + "\n\n" + _serialize_mailbox_context(page_context),
        tender_context=tender_context,
        document_text_context=_serialize_document_text_context(tender, selected_document_ids=selected_document_ids),
        user_message=message,
    )
    answer = client.generate_text(model_name, prompt)
    if not answer:
        raise ValueError("The chat model returned an empty response.")
    return answer, [
        f"General chat model: {model_name}",
        "Used the general chat prompt file with page, tender, and extracted document text context.",
        "Returned an LLM-generated answer because no higher-priority action was triggered.",
    ]


def build_chat_response(
    message: str,
    page_context: dict | None,
    tender: Tender | None,
    selected_document_ids: list[int] | None = None,
    intent_hint: str | None = None,
    answer_client=None,
    answer_model_name: str | None = None,
    latest_upload: ChatUpload | None = None,
    session_uploads: list[ChatUpload] | None = None,
) -> dict:
    normalized = _normalize(message)
    current_page = (page_context or {}).get("page")

    if tender is None:
        if _heuristic_create_tender_from_text_request(normalized, message):
            title_source = message.strip().splitlines()[0][:80] or "Pasted Tender Text"
            return {
                "response_type": "proposed_action",
                "message": (
                    "I can create a new tender from the pasted text in this chat. "
                    "Reply with 'confirm' and I will create the tender and attach the pasted content as a document."
                ),
                "intermediate_steps": [
                    "Detected a create-tender request with substantial pasted text in the chat message.",
                    "Prepared a create-tender action that will store the pasted text as a tender document for later extraction.",
                ],
                "actions": [
                    {
                        "action_type": "create_tender_from_text",
                        "title_hint": title_source,
                        "source_text": message.strip(),
                        "requires_confirmation": True,
                    }
                ],
            }
        if current_page == "tender_list":
            if any(phrase in normalized for phrase in {"show tenders", "list tenders", "what tenders", "which tenders", "summarise tenders", "summarize tenders"}):
                message_text, steps = _summarize_tender_list()
                return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}
        if current_page in {"mailbox", "mailbox_message"} and any(phrase in normalized for phrase in {"show mailbox", "list emails", "show emails", "what emails", "summarise mailbox", "summarize mailbox"}):
            mailbox_text = _serialize_mailbox_context(page_context)
            return {
                "response_type": "answer",
                "message": mailbox_text,
                "intermediate_steps": [
                    "Read the current mailbox page context from the UI.",
                    "Summarised the synced mailbox messages visible in this context.",
                ],
                "actions": [],
            }
            if any(phrase in normalized for phrase in {"submission dates", "upcoming submissions", "submission schedule", "due dates", "which tenders are due", "what is due"}):
                message_text, steps = _summarize_submission_schedule()
                return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}
            if any(phrase in normalized for phrase in {"status summary", "tender statuses", "status breakdown", "how many tenders", "count tenders"}):
                message_text, steps = _summarize_tender_statuses()
                return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}
            if any(phrase in normalized for phrase in {"what is missing", "what's missing", "needs attention", "which tenders need attention", "what needs doing"}):
                message_text, steps = _summarize_tenders_needing_attention()
                return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}
        if session_uploads and (intent_hint == "create_tender_from_upload" or _heuristic_create_tender_request(normalized)):
            upload_ids = [upload.id for upload in session_uploads]
            upload_names = [upload.original_filename for upload in session_uploads[:5]]
            return {
                "response_type": "proposed_action",
                "message": (
                    "I can create a new tender from the uploaded document"
                    + ("s" if len(upload_ids) != 1 else "")
                    + f": {', '.join(upload_names)}. Reply with 'confirm' and I will create the tender and attach "
                    + ("them." if len(upload_ids) != 1 else "it.")
                ),
                "intermediate_steps": [
                    "Found uploaded chat document(s) without a tender context.",
                    "Prepared a create-tender action that will move the uploaded document set into a new tender record.",
                ],
                "actions": [
                    {
                        "action_type": "create_tender_from_uploads",
                        "chat_upload_ids": upload_ids,
                        "requires_confirmation": True,
                    }
                ],
            }
        context_label = page_context.get("page") if page_context else "this screen"
        if answer_client is not None and answer_model_name:
            try:
                effective_page_context = dict(page_context or {})
                if selected_document_ids:
                    effective_page_context["selected_document_ids"] = selected_document_ids
                message_text, steps = _general_llm_chat_response(message, effective_page_context, tender, answer_client, answer_model_name)
                return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}
            except Exception as exc:
                llm_steps = [f"General chat answer fell back to the simple response: {exc}"]
            else:
                llm_steps = []
        if current_page == "computer_finder":
            message_text, steps = _computer_finder_context_response(page_context)
            return {
                "response_type": "answer",
                "message": message_text,
                "intermediate_steps": [*steps, *llm_steps] if "llm_steps" in locals() else steps,
                "actions": [],
            }
        return {
            "response_type": "answer",
            "message": (
                "I can help with the tender list. Ask for upcoming submission dates, a status summary, or which tenders need attention."
                if current_page == "tender_list"
                else (
                    "I can help with the mailbox. Ask me to summarise the visible emails, compare their content, or create a tender from a selected email."
                    if current_page in {"mailbox", "mailbox_message"}
                    else f"I can help with {context_label}. If you upload a document here, I can summarise it or prepare a new tender from it."
                )
            ),
            "intermediate_steps": [
                "Used the current page context from the UI.",
                "No tender ID was available for database-backed analysis.",
                *llm_steps,
            ] if 'llm_steps' in locals() else [
                "Used the current page context from the UI.",
                "No tender ID was available for database-backed analysis.",
            ],
            "actions": [],
        }

    if any(phrase in normalized for phrase in {"current tender value", "tender value", "current value", "how much is this tender"}):
        return {
            "response_type": "answer",
            "message": f"The current tender value is {_currency(tender.tender_value, tender.currency)}.",
            "intermediate_steps": [
                "Used the current tender context supplied by the page.",
                "Read the latest calculated tender_value from the database.",
            ],
            "actions": [],
        }

    if any(phrase in normalized for phrase in {"what is still missing", "what's still missing", "what is missing", "what's missing", "next steps", "what still needs", "what needs doing"}):
        message_text, steps = _suggest_next_actions(tender)
        return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}

    if any(phrase in normalized for phrase in {"summarise the items", "summarize the items", "items we need to price", "show items", "list items", "summarise items", "summarize items"}):
        message_text, steps = _summarize_items(tender)
        return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}

    if any(phrase in normalized for phrase in {"which questions are unanswered", "unanswered questions", "open questions", "questions unanswered"}):
        message_text, steps = _summarize_questions(tender, unanswered_only=True)
        return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}

    if any(phrase in normalized for phrase in {"show questions", "list questions", "summarise questions", "summarize questions"}):
        message_text, steps = _summarize_questions(tender, unanswered_only=False)
        return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}

    if any(phrase in normalized for phrase in {"which rfqs have not had a response", "rfqs have not had a response", "rfqs awaiting response", "show rfqs", "list rfqs"}):
        awaiting_only = any(phrase in normalized for phrase in {"which rfqs have not had a response", "rfqs have not had a response", "rfqs awaiting response"})
        message_text, steps = _summarize_rfqs(tender, awaiting_only=awaiting_only)
        return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}

    if any(phrase in normalized for phrase in {"show documents", "list documents", "uploaded documents", "what documents"}):
        message_text, steps = _summarize_documents(tender)
        return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}

    if any(phrase in normalized for phrase in {"best price", "best quote", "lowest quote", "which supplier response gave the best price"}):
        message_text, steps = _best_price_response(tender)
        return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}

    if intent_hint == "answer_questions_from_documents" or _heuristic_answer_questions_request(normalized):
        if not tender.questions:
            return {
                "response_type": "answer",
                "message": "There are no stored tender questions yet. Run question extraction first, then I can fill draft or final answers from a supporting document.",
                "intermediate_steps": [
                    "Detected a request to fill tender question answers from document text.",
                    "No TenderQuestion records exist yet for this tender.",
                ],
                "actions": [],
            }
        answer_documents = _documents_for_question_answering(tender, selected_document_ids=selected_document_ids)
        if not answer_documents:
            return {
                "response_type": "answer",
                "message": "Upload or select at least one tender document first, then ask me to fill the question answers from that file.",
                "intermediate_steps": [
                    "Detected a request to fill tender question answers from document text.",
                    "No suitable tender documents were selected or available.",
                ],
                "actions": [],
            }
        answer_mode = _question_answer_mode(normalized)
        document_names = [document.original_filename for document in answer_documents]
        mode_label = "final answers only" if answer_mode == "final_only" else "draft answers"
        return {
            "response_type": "proposed_action",
            "message": (
                f"I can use {', '.join(document_names[:3])} to fill {mode_label} for the current tender questions. "
                "Reply with 'confirm' and I will update the question records."
            ),
            "intermediate_steps": [
                "Detected a tender question-answering request in the current tender context.",
                f"Prepared a {mode_label} update using the selected or most recent tender document text.",
                f"Questions available: {len(tender.questions)}.",
            ],
            "actions": [
                {
                    "action_type": "answer_questions_from_documents",
                    "tender_id": tender.id,
                    "document_ids": [document.id for document in answer_documents],
                    "answer_mode": answer_mode,
                    "requires_confirmation": True,
                }
            ],
        }

    if intent_hint == "add_items_from_message" or _heuristic_add_items_request(normalized, message):
        parsed_items = _parse_item_request_lines(message)
        if not parsed_items:
            return {
                "response_type": "answer",
                "message": "I could see that you wanted to add items, but I could not parse any `quantity x item` lines from that message yet.",
                "intermediate_steps": [
                    "Detected an item-creation style request in the tender chat.",
                    "Tried to parse lines that start with a quantity followed by `x`.",
                    "No valid item rows were found to propose.",
                ],
                "actions": [],
            }
        preview_lines = [
            f"- {item['quantity_required']} x {item['description']}"
            + (f" ({len(item.get('sub_items') or [])} sub-items)" if item.get("sub_items") else "")
            for item in parsed_items[:8]
        ]
        return {
            "response_type": "proposed_action",
            "message": (
                "I’ve prepared these tender items from your list:\n"
                + "\n".join(preview_lines)
                + "\n\nReply with 'confirm' and I will add them to this tender as editable items."
            ),
            "intermediate_steps": [
                "Detected a tender item creation request in the current tender context.",
                "Parsed lines using the local `quantity x description` item format.",
                f"Prepared {len(parsed_items)} TenderItem records with full line text stored in the specification summary.",
            ],
            "actions": [
                {
                    "action_type": "add_items_from_message",
                    "tender_id": tender.id,
                    "items": parsed_items,
                    "requires_confirmation": True,
                }
            ],
        }

    if "status" in normalized:
        return {
            "response_type": "answer",
            "message": (
                f"Tender {tender.tender_number} for {tender.customer_name} is currently "
                f"'{tender.status}'. It has {len(tender.documents)} documents, {len(tender.items)} items, "
                f"{len(tender.rfqs)} RFIs, and {len(tender.questions)} questions."
            ),
            "intermediate_steps": [
                "Used the current tender header record.",
                "Counted linked documents, items, RFIs, and questions for context.",
            ],
            "actions": [],
        }

    if "change the quantity" in normalized:
        return {
            "response_type": "proposed_action",
            "message": "I can prepare a quantity update once you specify the item ID and new value.",
            "intermediate_steps": [
                "Detected a data change request.",
                "This version still requires a specific record target before proposing the update.",
            ],
            "actions": [],
        }

    if answer_client is not None and answer_model_name:
        try:
            effective_page_context = dict(page_context or {})
            if selected_document_ids:
                effective_page_context["selected_document_ids"] = selected_document_ids
            message_text, steps = _general_llm_chat_response(message, effective_page_context, tender, answer_client, answer_model_name)
            return {"response_type": "answer", "message": message_text, "intermediate_steps": steps, "actions": []}
        except Exception as exc:
            fallback_steps = [f"General chat answer fell back to the built-in summary: {exc}"]
    else:
        fallback_steps = []

    return {
        "response_type": "answer",
        "message": (
            f"I’m using tender {tender.tender_number} for {tender.customer_name}. "
            "I can answer broader questions from the tender context, or help you trigger actions like creating items or processing documents."
        ),
        "intermediate_steps": [
            "Used the current tender context from the page.",
            "No specific built-in shortcut matched, so the response fell back to the generic assistant summary.",
            *fallback_steps,
        ],
        "actions": [],
    }


def apply_confirmed_action(action: ChatAction, data_dir: Path) -> str:
    payload = json.loads(action.payload_json)
    if action.action_type == "create_tender_from_uploads":
        upload_ids = payload.get("chat_upload_ids") or []
        uploads = [upload for upload in (ChatUpload.query.get(upload_id) for upload_id in upload_ids) if upload is not None]
        if not uploads:
            raise ValueError("The uploaded chat documents could not be found.")
        filename_stem = Path(uploads[0].original_filename).stem.replace("_", " ").replace("-", " ").strip() or "New Tender"
        tender = Tender(
            customer_name="Needs Review",
            tender_number=f"AUTO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            title=filename_stem.title(),
            status="Documents Uploaded",
            notes="Created from chat upload. Review metadata and run extraction.",
        )
        db.session.add(tender)
        db.session.flush()
        tender_dir = ensure_tender_directories(data_dir, tender.id)
        for upload in uploads:
            original_path = Path(upload.file_path)
            destination = tender_dir / "original_documents" / upload.stored_filename
            destination.write_bytes(original_path.read_bytes())
            extracted_path = tender_dir / "extracted_text" / f"{upload.stored_filename}{extracted_text_suffix(upload.extracted_text)}"
            if upload.extracted_text:
                extracted_path.write_text(upload.extracted_text, encoding="utf-8")
            db.session.add(
                TenderDocument(
                    tender=tender,
                    original_filename=upload.original_filename,
                    stored_filename=upload.stored_filename,
                    file_path=str(destination),
                    file_type=upload.file_type,
                    extracted_text_path=str(extracted_path) if upload.extracted_text else None,
                    extracted_text=upload.extracted_text,
                    processed=bool(upload.extracted_text),
                    processing_notes=upload.processing_notes or "Created from chat upload.",
                )
            )
        action.status = "applied"
        action.result_json = json.dumps({"tender_id": tender.id, "redirect_path": f"/tenders/{tender.id}?refreshed={int(datetime.utcnow().timestamp())}#top"})
        return f"Created tender {tender.tender_number} for review and attached {len(uploads)} uploaded document(s)."
    if action.action_type == "create_tender_from_text":
        source_text = (payload.get("source_text") or "").strip()
        if not source_text:
            raise ValueError("The pasted tender text was empty.")
        title_hint = (payload.get("title_hint") or "Pasted Tender Text").strip()
        tender = Tender(
            customer_name="Needs Review",
            tender_number=f"AUTO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            title=title_hint[:255],
            status="Documents Uploaded",
            notes="Created from pasted AI chat text. Review metadata and run extraction.",
        )
        db.session.add(tender)
        db.session.flush()
        original_name, stored_name, saved_path = save_tender_bytes(
            data_dir,
            tender.id,
            "chat_pasted_tender.md",
            source_text.encode("utf-8"),
        )
        action.status = "applied"
        action.result_json = json.dumps({"tender_id": tender.id, "redirect_path": f"/tenders/{tender.id}?refreshed={int(datetime.utcnow().timestamp())}#top"})
        db.session.add(
            TenderDocument(
                tender=tender,
                original_filename=original_name,
                stored_filename=stored_name,
                file_path=str(saved_path),
                file_type="md",
                extracted_text_path=str(saved_path),
                extracted_text=source_text,
                processed=True,
                processing_notes="Created from pasted AI chat text.",
            )
        )
        return f"Created tender {tender.tender_number} from the pasted text and attached it as a markdown document."
    if action.action_type == "add_items_from_message":
        tender = Tender.query.get(payload.get("tender_id"))
        if tender is None:
            raise ValueError("The target tender could not be found.")
        items = payload.get("items") or []
        created = 0
        for item_payload in items:
            item = TenderItem(
                tender=tender,
                description=(item_payload.get("description") or "New item")[:255],
                quantity_required=Decimal(str(item_payload.get("quantity_required") or "0")),
                status=item_payload.get("status") or "Needs Review",
                specification_summary=item_payload.get("specification_summary") or None,
                source_reference=item_payload.get("source_reference") or "Added from AI chat request.",
            )
            for sub_payload in item_payload.get("sub_items") or []:
                item.sub_items.append(
                    TenderSubItem(
                        description=(sub_payload.get("description") or "New sub-item")[:255],
                        quantity=Decimal(str(sub_payload.get("quantity") or "1")),
                        status=sub_payload.get("status") or "Needs Review",
                        notes=sub_payload.get("notes") or None,
                    )
                )
            db.session.add(item)
            created += 1
        action.status = "applied"
        action.result_json = json.dumps(
            {
                "tender_id": tender.id,
                "redirect_path": f"/tenders/{tender.id}?refreshed={int(datetime.utcnow().timestamp())}#items",
                "items_created": created,
            }
        )
        return f"Added {created} tender items to {tender.tender_number}. They are ready for review and manual editing."
    if action.action_type == "answer_questions_from_documents":
        tender = Tender.query.get(payload.get("tender_id"))
        if tender is None:
            raise ValueError("The target tender could not be found.")
        document_ids = payload.get("document_ids") or []
        answer_mode = payload.get("answer_mode") or "draft"
        documents = [document for document in tender.documents if document.id in {int(document_id) for document_id in document_ids}]
        if not documents:
            raise ValueError("No supporting tender documents were available for question answering.")
        if not tender.questions:
            raise ValueError("There are no tender questions to update.")
        combined_document_text = "\n\n---\n\n".join(
            f"Document: {document.original_filename}\n{document.extracted_text.strip()}"
            for document in documents
            if document.extracted_text and document.extracted_text.strip()
        )
        if not combined_document_text:
            raise ValueError("The selected tender documents do not contain extracted text yet.")
        question_prompt = render_prompt(
            "question_answer_drafting",
            answer_mode=answer_mode,
            question_list=_question_list_context(tender),
            document_text=combined_document_text[:24000],
        )
        ollama_url = get_setting("ollama_url")
        model_name = get_task_model("chat_answering")
        if not ollama_url or not model_name:
            raise ValueError("The Ollama URL or chat model is not configured.")
        client = OllamaClient(ollama_url)
        parsed, raw_response, error = client.generate_json(model_name, question_prompt)
        if parsed is None or error is not None:
            raise ValueError(error or raw_response or "The question-answer drafting model returned invalid JSON.")

        question_index: dict[tuple[str | None, str], TenderQuestion] = {}
        for question in tender.questions:
            key = (question.question_number or None, _normalize(question.question_text or ""))
            question_index[key] = question

        updated = 0
        for answer_payload in parsed.get("answers", []):
            question_number = answer_payload.get("question_number") or None
            question_text = _markdown_text(answer_payload.get("question_text")) or ""
            question = question_index.get((question_number, _normalize(question_text)))
            if question is None and question_number:
                question = next((item for item in tender.questions if (item.question_number or None) == question_number), None)
            if question is None and question_text:
                question = next((item for item in tender.questions if _normalize(item.question_text or "") == _normalize(question_text)), None)
            if question is None:
                continue
            suggested_answer = _markdown_text(answer_payload.get("suggested_answer"))
            answer_text = _markdown_text(answer_payload.get("answer_text"))
            if answer_mode == "final_only":
                answer_value = answer_text or suggested_answer
                if answer_value:
                    question.answer_text = answer_value
                    question.answer_status = answer_payload.get("answer_status") or "Answered"
                    updated += 1
            else:
                if suggested_answer:
                    question.suggested_answer = suggested_answer
                    updated += 1
                if answer_text:
                    question.answer_text = answer_text
                    question.answer_status = answer_payload.get("answer_status") or "Answered"
                elif suggested_answer:
                    question.answer_status = answer_payload.get("answer_status") or "Draft Generated"
            source_reference = _markdown_text(answer_payload.get("source_reference"))
            if source_reference:
                question.source_reference = source_reference
        action.status = "applied"
        action.result_json = json.dumps(
            {
                "tender_id": tender.id,
                "redirect_path": f"/tenders/{tender.id}?refreshed={int(datetime.utcnow().timestamp())}#questions",
                "questions_updated": updated,
            }
        )
        if updated == 0:
            return f"I checked {len(documents)} document(s), but I could not confidently fill any tender question answers for {tender.tender_number}."
        return f"Updated {updated} tender question answer field(s) for {tender.tender_number} using {len(documents)} supporting document(s)."
    raise ValueError(f"Unsupported action type: {action.action_type}")


def classify_message_intent(client, model_name: str, message: str, has_upload: bool, has_tender_context: bool) -> tuple[str | None, list[str]]:
    normalized = _normalize(message)
    steps = []
    if has_upload and not has_tender_context and _heuristic_create_tender_request(normalized):
        return "create_tender_from_upload", [
            "Matched the message against the local create-tender fallback rules.",
            "A recent uploaded file is available and no tender context is active.",
        ]
    if not has_upload and not has_tender_context and _heuristic_create_tender_from_text_request(normalized, message):
        return "create_tender_from_text", [
            "Matched the message against the local pasted-text create-tender fallback rules.",
            "No upload is active, but the chat message contains substantial tender source text.",
        ]
    if has_tender_context and _heuristic_add_items_request(normalized, message):
        return "add_items_from_message", [
            "Matched the message against the local add-items fallback rules.",
            "A tender context is active and item-style lines were found in the message.",
        ]
    if has_tender_context and _heuristic_answer_questions_request(normalized):
        return "answer_questions_from_documents", [
            "Matched the message against the local question-answering fallback rules.",
            "A tender context is active and the message asks to fill question answers from document content.",
        ]
    prompt = render_prompt(
        "chat_action_orchestrator",
        user_message=message,
        has_upload=str(has_upload),
        has_tender_context=str(has_tender_context),
    )
    try:
        parsed, raw_response, error = client.generate_json(model_name, prompt)
    except Exception as exc:
        return None, [f"Intent classification via LLM was unavailable: {exc}"]
    if parsed is None or error is not None:
        return None, [f"Intent classification returned invalid JSON: {error or raw_response}"]
    intent = parsed.get("intent")
    confidence = str(parsed.get("confidence") or "").lower()
    reason = parsed.get("reason") or "No reason supplied."
    steps = [
        f"Intent classifier model: {model_name}",
        f"Classifier reason: {reason}",
        f"Classifier confidence: {confidence or 'unknown'}",
    ]
    if intent == "create_tender_from_upload" and has_upload and not has_tender_context and confidence in {"high", "medium"}:
        return intent, steps
    if intent == "create_tender_from_text" and not has_upload and not has_tender_context and confidence in {"high", "medium"}:
        return intent, steps
    if intent == "add_items_from_message" and has_tender_context and confidence in {"high", "medium"}:
        return intent, steps
    if intent == "answer_questions_from_documents" and has_tender_context and confidence in {"high", "medium"}:
        return intent, steps
    if intent == "confirm_action" and confidence in {"high", "medium"}:
        return intent, steps
    return None, steps


def log_chat_exchange(db, chat_session: ChatSession, user_message: str, response_payload: dict) -> None:
    add_chat_message(db, chat_session, "user", user_message)
    add_chat_message(
        db,
        chat_session,
        "assistant",
        response_payload.get("message", ""),
        intermediate_steps=response_payload.get("intermediate_steps", []),
        actions=response_payload.get("actions", []),
    )
    for action in response_payload.get("actions", []):
        db.session.add(
            ChatAction(
                chat_session=chat_session,
                action_type=action.get("action_type", "unknown"),
                status="proposed",
                payload_json=json.dumps(action),
            )
        )
