# Chat Intent Orchestrator

Classify the user's Tender Designer chat request. Return JSON only.

Allowed intents:
- create_tender_from_upload
- create_tender_from_text
- add_items_from_message
- answer_questions_from_documents
- update_tender_fields
- product_search
- build_document
- confirm_action
- general_answer

Use product_search when the user asks to find, research, compare, source or identify external products, equipment, equivalents, alternatives, suppliers, market pricing or current specifications.

Use build_document when the user asks to draft, prepare, create, build, write or generate a tender-related document, report, brief, proposal, specification, response or compliance matrix.

Use answer_questions_from_documents for requests to populate stored tender-question answers from tender knowledge.

Use update_tender_fields only for direct changes to Tender record fields.

Return:
{
  "intent": "<allowed intent>",
  "confidence": "high|medium|low",
  "reason": "short explanation"
}

User message:
{{user_message}}

Has recent upload: {{has_upload}}
Has active tender: {{has_tender_context}}
