# Item Extraction Prompt

You are extracting tender items from tender documents.
Return JSON only with an `items` array.
Each item should contain: description, quantity_required, specification_summary, source_reference, sub_items, specifications.
Sub-items should be included only when clearly present. If none, then add a single Sub-item for price capture.
Do not invent pricing.

Tender text:
{{tender_text}}
