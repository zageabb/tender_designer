from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from database import db
from models import (
    ChatAction,
    ChatMessage,
    ChatSession,
    LLMRunLog,
    RAGChunk,
    RAGDocument,
    RFQ,
    RFQLine,
    SupplierResponse,
    Tender,
    TenderDocument,
    TenderItem,
    TenderQuestion,
    TenderSubItem,
)
from services.file_storage import ensure_tender_directories
from services.rfq_service import write_rfq_eml


SAMPLE_TENDER_NUMBERS = ["SAMPLE-EDU-001", "SAMPLE-NHS-002"]
SAMPLE_RAG_TITLES = ["Sample - Laptop Delivery Playbook", "Sample - Historic Clarifications"]


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def _add_document(tender: Tender, filename: str, body: str, note: str = "Processed successfully.") -> TenderDocument:
    tender_dir = ensure_tender_directories(Path(tender.documents[0].file_path).parents[2] if tender.documents else Path("data"), tender.id)
    raise RuntimeError("Internal helper should not be called without a data_dir argument.")


def seed_sample_data(data_dir: Path) -> dict:
    sample_tenders = Tender.query.filter(Tender.tender_number.in_(SAMPLE_TENDER_NUMBERS)).all()
    for tender in sample_tenders:
        db.session.delete(tender)

    for rag_doc in RAGDocument.query.filter(RAGDocument.title.in_(SAMPLE_RAG_TITLES)).all():
        db.session.delete(rag_doc)

    db.session.commit()

    created = {"tenders": 0, "documents": 0, "items": 0, "questions": 0, "rfqs": 0, "responses": 0, "rag_documents": 0}

    tenders_payload = [
        {
            "customer_name": "Northbridge College",
            "tender_number": "SAMPLE-EDU-001",
            "title": "Student Device Refresh and Deployment",
            "status": "Pricing In Progress",
            "currency": "GBP",
            "notes": "High-priority education refresh with deployment and warranty uplift.",
            "documents": [
                (
                    "itt_overview.txt",
                    dedent(
                        """
                        Northbridge College seeks pricing for a refresh of 120 student laptops, 12 lecturer laptops,
                        white glove deployment, imaging, onsite handover and three-year warranty coverage.
                        Submission date: 2026-08-14 at 12:00.
                        """
                    ),
                ),
                (
                    "questions_schedule.txt",
                    dedent(
                        """
                        Clarification questions:
                        Q1. Confirm the maximum lead time for all end-user devices.
                        Q2. Describe your white glove deployment and asset-tagging process.
                        Q3. Provide warranty escalation and swap-out arrangements.
                        """
                    ),
                ),
            ],
            "items": [
                {
                    "description": "14-inch Student Laptop Bundle",
                    "quantity_required": 120,
                    "unit_price": 698,
                    "status": "Priced",
                    "specification_summary": "Intel i5, 16GB RAM, 256GB SSD, classroom-ready imaging.",
                    "sub_items": [
                        {"description": "14-inch Student Laptop", "quantity": 120, "unit_price": 640, "status": "Priced"},
                        {"description": "3 Year Warranty", "quantity": 120, "unit_price": 38, "status": "Priced"},
                        {"description": "White Glove Deployment", "quantity": 120, "unit_price": 20, "status": "RFQ Received"},
                    ],
                },
                {
                    "description": "Lecturer Performance Laptop Bundle",
                    "quantity_required": 12,
                    "unit_price": 1095,
                    "status": "RFQ Sent",
                    "specification_summary": "Higher spec lecturer device with USB-C dock support.",
                    "sub_items": [
                        {"description": "15-inch Lecturer Laptop", "quantity": 12, "unit_price": 990, "status": "RFQ Sent"},
                        {"description": "3 Year Warranty", "quantity": 12, "unit_price": 55, "status": "RFQ Sent"},
                    ],
                },
            ],
            "questions": [
                {
                    "question_number": "Q1",
                    "section": "Commercial",
                    "question_text": "Confirm the maximum lead time for all end-user devices.",
                    "suggested_answer": "Standard lead time is 10 working days from order confirmation, subject to final stock allocation.",
                    "answer_status": "Draft Generated",
                },
                {
                    "question_number": "Q2",
                    "section": "Implementation",
                    "question_text": "Describe your white glove deployment and asset-tagging process.",
                    "answer_status": "Unanswered",
                },
                {
                    "question_number": "Q3",
                    "section": "Support",
                    "question_text": "Provide warranty escalation and swap-out arrangements.",
                    "suggested_answer": "Faults are triaged through the service desk with next-business-day replacement for covered devices.",
                    "answer_status": "In Review",
                },
            ],
            "rfq": {
                "supplier_name": "Northwind Supplies",
                "supplier_email": "sales@northwind.example",
                "status": "Response Uploaded",
                "response": {
                    "supplier_name": "Northwind Supplies",
                    "supplier_email": "sales@northwind.example",
                    "source_type": "paste",
                    "raw_text": "Quote for student laptop bundle and deployment service attached. Lead time 2 weeks.",
                    "parsed_json": {
                        "currency": "GBP",
                        "lines": [
                            {"description": "14-inch Student Laptop", "quantity": 120, "unit_price": 640, "total_price": 76800},
                            {"description": "3 Year Warranty", "quantity": 120, "unit_price": 38, "total_price": 4560},
                            {"description": "White Glove Deployment", "quantity": 120, "unit_price": 20, "total_price": 2400},
                        ],
                    },
                },
            },
        },
        {
            "customer_name": "South City NHS Trust",
            "tender_number": "SAMPLE-NHS-002",
            "title": "Endpoint Replacement and Support Extension",
            "status": "Ready For Review",
            "currency": "GBP",
            "notes": "Mixed hardware and support opportunity with several clarification questions already drafted.",
            "documents": [
                (
                    "specification.txt",
                    dedent(
                        """
                        Tender scope includes 80 clinical workstation devices, 25 admin laptops,
                        24/7 support extension and onsite rollout support across three hospital sites.
                        Award date targeted for 2026-09-10.
                        """
                    ),
                ),
            ],
            "items": [
                {
                    "description": "Clinical Workstation Package",
                    "quantity_required": 80,
                    "unit_price": 845,
                    "status": "Needs Review",
                    "specification_summary": "Compact desktop or AIO endpoint with locked-down image.",
                    "sub_items": [
                        {"description": "Clinical Workstation Device", "quantity": 80, "unit_price": 790, "status": "Needs Review"},
                        {"description": "24/7 Support Extension", "quantity": 80, "unit_price": 55, "status": "Needs Review"},
                    ],
                },
                {
                    "description": "Admin Laptop Package",
                    "quantity_required": 25,
                    "unit_price": 0,
                    "status": "RFQ Required",
                    "specification_summary": "Standard mobile user laptop with docking support.",
                    "sub_items": [],
                },
            ],
            "questions": [
                {
                    "question_number": "Q4",
                    "section": "Service",
                    "question_text": "Explain your major incident escalation approach for hospital sites.",
                    "suggested_answer": "Major incidents are triaged immediately to the service manager with hourly stakeholder updates until resolution.",
                    "answer_status": "Draft Generated",
                },
                {
                    "question_number": "Q5",
                    "section": "Transition",
                    "question_text": "What onboarding activities are included during mobilisation?",
                    "answer_status": "Unanswered",
                },
            ],
            "rfq": None,
        },
    ]

    for tender_payload in tenders_payload:
        tender = Tender(
            customer_name=tender_payload["customer_name"],
            tender_number=tender_payload["tender_number"],
            title=tender_payload["title"],
            status=tender_payload["status"],
            currency=tender_payload["currency"],
            notes=tender_payload["notes"],
        )
        db.session.add(tender)
        db.session.flush()
        created["tenders"] += 1

        tender_dir = ensure_tender_directories(data_dir, tender.id)

        for filename, content in tender_payload["documents"]:
            original_path = _write_text(tender_dir / "original_documents" / filename, content)
            extracted_path = _write_text(tender_dir / "extracted_text" / f"{filename}.txt", content)
            db.session.add(
                TenderDocument(
                    tender=tender,
                    original_filename=filename,
                    stored_filename=filename,
                    file_path=str(original_path),
                    file_type=Path(filename).suffix.lstrip(".") or "txt",
                    extracted_text_path=str(extracted_path),
                    extracted_text=content.strip(),
                    processed=True,
                    processing_notes="Seeded sample document.",
                )
            )
            created["documents"] += 1

        item_lookup: list[TenderItem] = []
        for item_payload in tender_payload["items"]:
            item = TenderItem(
                tender=tender,
                description=item_payload["description"],
                quantity_required=item_payload["quantity_required"],
                unit_price=item_payload["unit_price"] or None,
                status=item_payload["status"],
                specification_summary=item_payload["specification_summary"],
            )
            db.session.add(item)
            db.session.flush()
            created["items"] += 1
            item_lookup.append(item)

            for sub_payload in item_payload["sub_items"]:
                db.session.add(
                    TenderSubItem(
                        tender_item=item,
                        description=sub_payload["description"],
                        quantity=sub_payload["quantity"],
                        unit_price=sub_payload["unit_price"],
                        status=sub_payload["status"],
                        notes="Seeded sample sub-item.",
                    )
                )

        for question_payload in tender_payload["questions"]:
            db.session.add(
                TenderQuestion(
                    tender=tender,
                    question_number=question_payload["question_number"],
                    section=question_payload["section"],
                    question_text=question_payload["question_text"],
                    suggested_answer=question_payload.get("suggested_answer"),
                    answer_status=question_payload["answer_status"],
                )
            )
            created["questions"] += 1

        rfq_payload = tender_payload["rfq"]
        if rfq_payload:
            rfq = RFQ(
                tender=tender,
                supplier_name=rfq_payload["supplier_name"],
                supplier_email=rfq_payload["supplier_email"],
                subject=f"RFQ - {tender.tender_number} - {tender.customer_name}",
                introduction_text="Seeded sample RFQ for screen verification.",
                status=rfq_payload["status"],
            )
            db.session.add(rfq)
            db.session.flush()
            created["rfqs"] += 1

            first_item = item_lookup[0]
            for sub_item in first_item.sub_items:
                db.session.add(
                    RFQLine(
                        rfq=rfq,
                        tender_item_id=first_item.id,
                        tender_sub_item_id=sub_item.id,
                        description=sub_item.description,
                        quantity=sub_item.quantity,
                        quoted_unit_price=sub_item.unit_price,
                        quoted_total_price=(sub_item.quantity or 0) * (sub_item.unit_price or 0),
                        currency=tender.currency,
                        lead_time="2 weeks",
                        supplier_part_number=f"NW-{sub_item.id}",
                    )
                )
            rfq.eml_file_path = str(write_rfq_eml(data_dir, tender, rfq, "Seeded sample RFQ for screen verification."))

            response_payload = rfq_payload["response"]
            db.session.add(
                SupplierResponse(
                    tender=tender,
                    rfq_id=rfq.id,
                    supplier_name=response_payload["supplier_name"],
                    supplier_email=response_payload["supplier_email"],
                    source_type=response_payload["source_type"],
                    raw_text=response_payload["raw_text"],
                    parsed_json=json.dumps(response_payload["parsed_json"], indent=2),
                    processed=True,
                    processing_notes="Seeded sample supplier response.",
                )
            )
            created["responses"] += 1

        chat_session = ChatSession(
            tender_id=tender.id,
            page_context_json=json.dumps(
                {
                    "page": "tender_detail",
                    "tender_id": tender.id,
                    "tender_number": tender.tender_number,
                    "customer_name": tender.customer_name,
                }
            ),
        )
        db.session.add(chat_session)
        db.session.flush()
        db.session.add(
            ChatMessage(
                chat_session=chat_session,
                role="user",
                message_text="What is still missing from this tender?",
            )
        )
        db.session.add(
            ChatMessage(
                chat_session=chat_session,
                role="assistant",
                message_text="Pricing review and unanswered questions are still open.",
                intermediate_steps_json=json.dumps(
                    [
                        "Checked the current tender status and question list.",
                        "Reviewed which items still need supplier confirmation.",
                    ]
                ),
            )
        )
        db.session.add(
            ChatAction(
                chat_session=chat_session,
                action_type="update_record",
                status="proposed",
                payload_json=json.dumps(
                    {
                        "table": "TenderQuestion",
                        "record_id": 1,
                        "changes": {"answer_status": "Answered"},
                    }
                ),
            )
        )

        db.session.add(
            LLMRunLog(
                tender_id=tender.id,
                task_type="item_extraction",
                model_name="llama3.2",
                prompt="Seeded prompt for UI testing.",
                response="Seeded item extraction output.",
                success=True,
            )
        )

    rag_payloads = [
        (
            "Sample - Laptop Delivery Playbook",
            "company_standard",
            dedent(
                """
                Device rollout includes imaging, asset tagging, classroom-ready staging,
                site delivery coordination and post-deployment snagging.
                """
            ),
        ),
        (
            "Sample - Historic Clarifications",
            "historic_qa",
            dedent(
                """
                Historic clarification responses reference warranty handling,
                lead-time commitments and onsite support cover.
                """
            ),
        ),
    ]

    for title, source_type, content in rag_payloads:
        rag_doc = RAGDocument(
            title=title,
            source_type=source_type,
            raw_text=content.strip(),
            processed=True,
            notes="Seeded sample RAG document.",
        )
        db.session.add(rag_doc)
        db.session.flush()
        created["rag_documents"] += 1
        for index, chunk in enumerate(content.strip().split(",")):
            db.session.add(
                RAGChunk(
                    rag_document=rag_doc,
                    chunk_index=index,
                    chunk_text=chunk.strip(),
                    embedding_id=f"sample-{rag_doc.id}-{index}",
                    metadata_json=json.dumps({"title": title, "source_type": source_type}),
                )
            )

    db.session.commit()
    return created
