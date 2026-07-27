# Tender Field Update Prompt

Convert the user's request into updates for the current Tender record.
Return JSON only in this form: {"updates": {"field_name": "new value"}}.
Only use fields from this allowed list: {{tender_fields}}.
Dates must use YYYY-MM-DD. tender_value must be numeric.
submission_type must be one of: Email, Portal, Postal, Hand delivered.
Use null only when the user explicitly asks to clear an optional field.
Do not infer changes the user did not request. Do not include IDs or timestamps.

Current Tender fields:
{{tender_context}}

User request:
{{user_message}}
