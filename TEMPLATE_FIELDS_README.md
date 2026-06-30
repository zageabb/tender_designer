# Template Fields Reference

This document lists the placeholder fields currently supported by Tender Designer's configurable prompt and template files.

The replacement system is simple text substitution. Use placeholders exactly in the form `{{field_name}}`.

## Important Notes

- Placeholder names are case-sensitive.
- Unsupported placeholders are not expanded automatically.
- These fields are based on the current live code paths, not planned future fields.
- Prompt/template files are edited from the Settings screen and stored under `llm_prompts/`.

## Prompt Files And Supported Fields

### `metadata_extraction.md`

Supported placeholders:

- `{{tender_text}}`

Source:

- Combined extracted text from the selected tender documents.

### `item_extraction.md`

Supported placeholders:

- `{{tender_text}}`

Source:

- Combined extracted text from the selected tender documents.

### `question_extraction.md`

Supported placeholders:

- `{{tender_text}}`

Source:

- Combined extracted text from the selected tender documents.

### `chat_action_orchestrator.md`

Supported placeholders:

- `{{user_message}}`
- `{{has_upload}}`
- `{{has_tender_context}}`

Source:

- `user_message`: the message typed by the user into chat
- `has_upload`: `True` or `False`
- `has_tender_context`: `True` or `False`

### `chat_general_answer.md`

Supported placeholders:

- `{{page_context}}`
- `{{tender_context}}`
- `{{user_message}}`

Source:

- `page_context`: serialized summary of the current screen context
- `tender_context`: serialized summary of the active tender, if one is open
- `user_message`: the message typed by the user into chat

## RFQ Template

### `rfq_email_body.md`

Supported placeholders:

- `{{supplier_display_name}}`
- `{{supplier_name}}`
- `{{customer_name}}`
- `{{tender_number}}`
- `{{tender_title}}`
- `{{tender_reference}}`
- `{{tender_status}}`
- `{{submission_date}}`
- `{{award_date}}`
- `{{tender_currency}}`
- `{{line_items_table}}`
- `{{email_signature}}`

Source:

- `supplier_display_name`: supplier name if entered, otherwise `Supplier`
- `supplier_name`: raw supplier name field from the RFQ form
- `customer_name`: tender customer name
- `tender_number`: tender number only
- `tender_title`: tender title only
- `tender_reference`: tender number plus title when a title exists
- `tender_status`: current tender status
- `submission_date`: tender submission date in ISO format, or `Not set`
- `award_date`: tender award date in ISO format, or `Not set`
- `tender_currency`: tender currency
- `line_items_table`: generated markdown-style table of the selected RFQ lines
- `email_signature`: value from the Default Email Signature setting

### `tender_email_body.md`

Supported placeholders:

- `{{recipient_email}}`
- `{{tender_number}}`
- `{{tender_title}}`
- `{{tender_reference}}`
- `{{customer_name}}`
- `{{tender_status}}`
- `{{submission_date}}`
- `{{selected_documents_list}}`
- `{{email_signature}}`

Source:

- `recipient_email`: value entered in the create-email form
- `tender_number`: tender number only
- `tender_title`: tender title only
- `tender_reference`: tender number plus title when a title exists
- `customer_name`: tender customer name
- `tender_status`: current tender status
- `submission_date`: tender submission date in ISO format, or `Not set`
- `selected_documents_list`: rendered list of the selected tender document filenames
- `email_signature`: value from the Default Email Signature setting

### `rfq_line_items_table.md`

Supported placeholders:

- `{{line_items_rows}}`

Source:

- `line_items_rows`: the fully rendered collection of row blocks from `rfq_line_item_row.md`

### `rfq_line_item_row.md`

Supported placeholders:

- `{{line_quantity}}`
- `{{line_description}}`
- `{{line_status}}`
- `{{line_currency}}`
- `{{item_id}}`
- `{{item_tender_id}}`
- `{{item_description}}`
- `{{item_quantity_required}}`
- `{{item_unit_price}}`
- `{{item_total_price}}`
- `{{item_status}}`
- `{{item_specification_summary}}`
- `{{item_source_reference}}`
- `{{item_created_at}}`
- `{{item_updated_at}}`
- `{{sub_item_id}}`
- `{{sub_item_tender_item_id}}`
- `{{sub_item_description}}`
- `{{sub_item_quantity}}`
- `{{sub_item_unit_price}}`
- `{{sub_item_total_price}}`
- `{{sub_item_supplier_name}}`
- `{{sub_item_supplier_reference}}`
- `{{sub_item_status}}`
- `{{sub_item_notes}}`
- `{{sub_item_created_at}}`
- `{{sub_item_updated_at}}`

Source:

- `line_quantity`: quantity used for the RFQ line
- `line_description`: resolved specification text used for the RFQ line
- `line_status`: resolved status used for the RFQ line
- `line_currency`: tender currency for the line
- `item_*`: direct fields from the linked tender item
- `sub_item_*`: direct fields from the linked tender sub-item, blank when the row comes from a main item without a sub-item

## `{{line_items_table}}` Generation

Behavior:

- `{{line_items_table}}` is rendered by first expanding `rfq_line_item_row.md` for each selected RFQ line, then inserting the combined result into `rfq_line_items_table.md`.
- If a sub-item is selected, `line_description` comes from the parent item's `specification_summary` when available, falling back to the sub-item description.
- If a main item without sub-items is selected, `line_description` comes from the item specification summary when available, otherwise the item description.

## Where These Are Used In Code

- [services/prompt_service.py](/Users/geraldabbot/Documents/Codex/2026-06-26/ini/tender_designer/services/prompt_service.py)
- [services/rfq_service.py](/Users/geraldabbot/Documents/Codex/2026-06-26/ini/tender_designer/services/rfq_service.py)
- [services/llm_tasks.py](/Users/geraldabbot/Documents/Codex/2026-06-26/ini/tender_designer/services/llm_tasks.py)
- [services/chat_service.py](/Users/geraldabbot/Documents/Codex/2026-06-26/ini/tender_designer/services/chat_service.py)
