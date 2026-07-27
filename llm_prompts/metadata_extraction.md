# Metadata Extraction Prompt

You are extracting tender metadata from tender documents.
Return JSON only with keys: customer_name, tender_number, title, status, submission_date, submission_time, submission_type, award_date, currency, notes.
submission_type must be one of: Email, Portal, Postal, Hand delivered.
Use null for values that are not clearly supported by the text.
Prefer ISO dates when possible.
Keep notes concise and factual.
Return deadline dates and times supersede submission date and submission times.
Summarised Specification supersedes generic title.

Tender text:
{{tender_text}}
