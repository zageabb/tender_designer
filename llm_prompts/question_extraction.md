# Question Extraction Prompt

You are extracting genuine tender questions and written response requirements.
Return JSON only with a `questions` array.
Each question should contain: question_number, section, question_text, suggested_answer, answer_text, source_reference.
Store `question_text`, `suggested_answer`, and `answer_text` as markdown strings where appropriate.
Use `suggested_answer` for a draft response when the tender provides enough context to prepare one.
Use `answer_text` only when the document already contains a final answer; otherwise return null.
Exclude statements that are not true questions or explicit response requirements.

Tender text:
{{tender_text}}
