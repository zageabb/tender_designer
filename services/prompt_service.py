from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "llm_prompts"

PROMPT_FILES = {
    "metadata_extraction": {
        "filename": "metadata_extraction.md",
        "title": "Metadata Extraction",
        "description": "Instruction file used to extract core tender metadata as JSON.",
        "default_content": (
            "# Metadata Extraction Prompt\n\n"
            "You are extracting tender metadata from tender documents.\n"
            "Return JSON only with keys: customer_name, tender_number, title, status, "
            "submission_date, submission_time, award_date, currency, notes.\n"
            "Use null for values that are not clearly supported by the text.\n"
            "Prefer ISO dates when possible.\n"
            "Keep notes concise and factual.\n\n"
            "Tender text:\n{{tender_text}}\n"
        ),
    },
    "item_extraction": {
        "filename": "item_extraction.md",
        "title": "Item Extraction",
        "description": "Instruction file used to extract tender items and sub-items as JSON.",
        "default_content": (
            "# Item Extraction Prompt\n\n"
            "You are extracting tender items from tender documents.\n"
            "Return JSON only with an `items` array.\n"
            "Each item should contain: description, quantity_required, specification_summary, "
            "source_reference, sub_items, specifications.\n"
            "Sub-items should be included only when clearly present.\n"
            "Do not invent pricing.\n\n"
            "Tender text:\n{{tender_text}}\n"
        ),
    },
    "question_extraction": {
        "filename": "question_extraction.md",
        "title": "Question Extraction",
        "description": "Instruction file used to extract tender questions and response requirements as JSON.",
        "default_content": (
            "# Question Extraction Prompt\n\n"
            "You are extracting genuine tender questions and written response requirements.\n"
            "Return JSON only with a `questions` array.\n"
            "Each question should contain: question_number, section, question_text, suggested_answer, answer_text, source_reference.\n"
            "Store `question_text`, `suggested_answer`, and `answer_text` as markdown strings where appropriate.\n"
            "Use `suggested_answer` for a draft response when the tender provides enough context to prepare one.\n"
            "Use `answer_text` only when the document already contains a final answer; otherwise return null.\n"
            "Exclude statements that are not true questions or explicit response requirements.\n\n"
            "Tender text:\n{{tender_text}}\n"
        ),
    },
    "question_answer_drafting": {
        "filename": "question_answer_drafting.md",
        "title": "Question Answer Drafting",
        "description": "Instruction file used to draft or fill tender question answers from selected tender document text.",
        "default_content": (
            "# Question Answer Drafting Prompt\n\n"
            "You are filling tender question answers using only the supplied tender question list and supporting document text.\n"
            "Return JSON only with an `answers` array.\n"
            "Each answer object should contain: question_number, question_text, suggested_answer, answer_text, answer_status, source_reference.\n"
            "Write `suggested_answer` and `answer_text` as markdown where appropriate.\n"
            "If the mode is `draft`, prefer `suggested_answer` unless the source text clearly provides a final answer.\n"
            "If the mode is `final_only`, write the best supported answer into `answer_text` and leave `suggested_answer` null unless it helps explain uncertainty.\n"
            "Do not invent answers. If the source text does not support an answer, return null values for that question.\n\n"
            "Mode: {{answer_mode}}\n\n"
            "Questions:\n{{question_list}}\n\n"
            "Supporting document text:\n{{document_text}}\n"
        ),
    },
    "chat_action_orchestrator": {
        "filename": "chat_action_orchestrator.md",
        "title": "Chat Action Orchestrator",
        "description": "Instruction file used to decide whether the chat should propose an action instead of answering normally.",
        "default_content": (
            "# Chat Action Orchestrator Prompt\n\n"
            "Classify the user's message into one of these intents and return JSON only with keys "
            "`intent`, `confidence`, and `reason`.\n"
            "Allowed intents: create_tender_from_upload, create_tender_from_text, add_items_from_message, answer_questions_from_documents, confirm_action, none.\n"
            "Use `create_tender_from_upload` only if the user appears to want a new tender created from an uploaded document.\n"
            "Use `create_tender_from_text` only if the user appears to want a new tender created from pasted text in the chat itself.\n"
            "Use `add_items_from_message` only if the user is asking to turn a typed list of items into tender items on the current tender.\n"
            "Use `answer_questions_from_documents` only if the user is asking to fill tender question answers from the uploaded or selected supporting document text.\n"
            "Use `confirm_action` only if the user is clearly confirming a previously proposed action.\n\n"
            "User message: {{user_message}}\n"
            "Has upload available: {{has_upload}}\n"
            "Has tender context: {{has_tender_context}}\n"
        ),
    },
    "chat_general_answer": {
        "filename": "chat_general_answer.md",
        "title": "General Chat Answer",
        "description": "Instruction file used to answer broader tender questions with the current page and tender context.",
        "default_content": (
            "# General Chat Answer Prompt\n\n"
            "You are Tender Designer's AI assistant.\n"
            "Answer the user's question using the provided screen and tender context.\n"
            "Be practical, specific, and concise.\n"
            "If the answer is not supported by the current data, say what is missing and what the user can do next.\n"
            "Do not invent facts, dates, pricing, or supplier details.\n"
            "If the user appears to be asking for a data-changing action, do not perform it here; instead explain that the action flow should be used.\n\n"
            "Page context:\n{{page_context}}\n\n"
            "Tender context:\n{{tender_context}}\n\n"
            "Extracted document text:\n{{document_text_context}}\n\n"
            "User question:\n{{user_message}}\n"
        ),
    },
    "computer_finder_query_planning": {
        "filename": "computer_finder_query_planning.md",
        "title": "Computer Finder Query Planning",
        "description": "Instruction file used by Ollama to turn a computer specification into concise web search queries.",
        "default_content": (
            "# Computer Finder Query Planning Prompt\n\n"
            "You are planning web searches for a hardware procurement assistant.\n"
            "Return JSON only with a `queries` array containing 2 to 4 concise search queries.\n"
            "Do not include `site:` filters; the application adds those for each configured website.\n"
            "Do not include configured domain names such as `dell.com`, `hp.com`, or `lenovo.com` in the query text.\n"
            "Do not use words like `search` or `site`.\n"
            "Prefer product family, business model, workstation, laptop, desktop, datasheet, configurable, and warranty terms when useful.\n\n"
            "Procurement market: {{market_context}}\n\n"
            "Search websites configured for this workflow:\n{{allowed_domains}}\n\n"
            "User specification:\n{{computer_spec}}\n"
        ),
    },
    "computer_finder_search": {
        "filename": "computer_finder_search.md",
        "title": "Computer Finder Recommendation",
        "description": "Instruction file used by Ollama to match hardware specs to brands and machine types from sourced web results.",
        "default_content": (
            "# Computer Finder Recommendation Prompt\n\n"
            "You are a hardware procurement assistant. The user provided a computer specification and the application has collected "
            "site-restricted web results from the configured websites. Use only the supplied search results as evidence.\n\n"
            "Current date: {{current_date}}\n"
            "Default procurement market: {{market_context}}\n\n"
            "Search websites configured for this workflow:\n{{allowed_domains}}\n\n"
            "Blocked websites:\n{{blocked_domains}}\n\n"
            "User specification:\n{{computer_spec}}\n\n"
            "Collected search results and readable page text:\n{{search_results}}\n\n"
            "Workflow:\n"
            "1. Parse the required specification into concrete requirements: form factor, CPU class, memory, storage, GPU, display, ports, OS, warranty, budget, and any compliance constraints.\n"
            "2. Prefer manufacturer product pages, datasheets, configurable models, or business procurement pages when they are present in the results.\n"
            "3. Recommend one best-fit brand and machine type/model family. Include exact model or part number only when the source text supports it.\n"
            "4. Compare the recommendation against the supplied spec in a compact table using source numbers like [1] or [2].\n"
            "5. Include up to two suitable alternatives when the supplied results support them.\n"
            "6. State gaps, assumptions, and risks clearly. Do not invent availability, pricing, warranty, or part numbers.\n"
            "7. Cite sources inline with the bracket number from the collected result.\n\n"
            "Return markdown with these sections:\n"
            "- Best match\n"
            "- Spec fit\n"
            "- Alternatives\n"
            "- Gaps and assumptions\n"
            "- Sources\n"
        ),
    },
    "rfq_email_body": {
        "filename": "rfq_email_body.md",
        "title": "RFQ Email Body Template",
        "description": "Template file used to build the RFQ email body from tender and supplier context.",
        "default_content": (
            "# RFQ Email Body Template\n\n"
            "Dear {{supplier_display_name}},\n\n"
            "We are currently preparing a tender response for {{tender_reference}} and would like to request pricing and availability "
            "for the lines below.\n\n"
            "Customer: {{customer_name}}\n"
            "Tender status: {{tender_status}}\n"
            "Submission date: {{submission_date}}\n\n"
            "Please provide:\n"
            "- Unit pricing\n"
            "- Lead time\n"
            "- Warranty details\n"
            "- Any assumptions or exclusions\n"
            "- Product references or datasheets where applicable\n\n"
            "Items:\n{{line_items_table}}\n\n"
            "{{email_signature}}\n"
        ),
    },
    "rfq_line_items_table": {
        "filename": "rfq_line_items_table.md",
        "title": "RFQ Line Items Table Template",
        "description": "Template file used to wrap the rendered RFQ line rows into the final inserted table block.",
        "default_content": (
            "# RFQ Line Items Table Template\n\n"
            "| Qty | General Item | Specification / Sub-item |\n"
            "| --- | --- | --- |\n"
            "{{line_items_rows}}\n"
        ),
    },
    "rfq_line_item_row": {
        "filename": "rfq_line_item_row.md",
        "title": "RFQ Line Item Row Template",
        "description": "Template file used to render each individual RFQ line row with item and sub-item fields.",
        "default_content": (
            "# RFQ Line Item Row Template\n\n"
            "| {{line_quantity}} | {{item_description}} | {{line_description}} |\n"
        ),
    },
    "tender_email_body": {
        "filename": "tender_email_body.md",
        "title": "Tender Email Body Template",
        "description": "Template file used to build tender document email drafts from tender and selected-document context.",
        "default_content": (
            "# Tender Email Body Template\n\n"
            "Hello,\n\n"
            "Please find the selected tender documents attached for {{tender_reference}}.\n\n"
            "Customer: {{customer_name}}\n"
            "Tender status: {{tender_status}}\n"
            "Submission date: {{submission_date}}\n\n"
            "Attached documents:\n"
            "{{selected_documents_list}}\n\n"
            "{{email_signature}}\n"
        ),
    },
}


def ensure_prompt_files() -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for prompt_key, payload in PROMPT_FILES.items():
        prompt_path = PROMPTS_DIR / payload["filename"]
        if not prompt_path.exists():
            prompt_path.write_text(payload["default_content"], encoding="utf-8")


def get_prompt_content(prompt_key: str) -> str:
    ensure_prompt_files()
    payload = PROMPT_FILES[prompt_key]
    prompt_path = PROMPTS_DIR / payload["filename"]
    return prompt_path.read_text(encoding="utf-8")


def save_prompt_content(prompt_key: str, content: str) -> None:
    ensure_prompt_files()
    payload = PROMPT_FILES[prompt_key]
    prompt_path = PROMPTS_DIR / payload["filename"]
    prompt_path.write_text(content.rstrip() + "\n", encoding="utf-8")


def render_prompt(prompt_key: str, **kwargs: str) -> str:
    content = get_prompt_content(prompt_key)
    return render_template_text(content, **kwargs)


def render_template_text(content: str, **kwargs: str) -> str:
    rendered = content
    for key, value in kwargs.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered
