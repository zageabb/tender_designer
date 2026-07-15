# Chat Action Orchestrator Prompt

Classify the user's message into one of these intents and return JSON only with keys `intent`, `confidence`, and `reason`.
Allowed intents: create_tender_from_upload, create_tender_from_text, add_items_from_message, answer_questions_from_documents, confirm_action, none.
Use `create_tender_from_upload` only if the user appears to want a new tender created from an uploaded document.
Use `create_tender_from_text` only if the user appears to want a new tender created from pasted text in the chat itself.
Use `add_items_from_message` only if the user is asking to turn a typed list of items into tender items on the current tender.
Use `answer_questions_from_documents` only if the user is asking to fill tender question answers from uploaded or selected supporting document text.
Use `confirm_action` only if the user is clearly confirming a previously proposed action.

User message: {{user_message}}
Has upload available: {{has_upload}}
Has tender context: {{has_tender_context}}
