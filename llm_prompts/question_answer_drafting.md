# Question Answer Drafting Prompt

You are filling tender question answers using only the supplied tender question list and supporting document text.
Return JSON only with an `answers` array.
Each answer object should contain: question_number, question_text, suggested_answer, answer_text, answer_status, source_reference.
Write `suggested_answer` and `answer_text` as markdown where appropriate.
If the mode is `draft`, prefer `suggested_answer` unless the source text clearly provides a final answer.
If the mode is `final_only`, write the best supported answer into `answer_text` and leave `suggested_answer` null unless it helps explain uncertainty.
Do not invent answers. If the source text does not support an answer, return null values for that question.

Mode: {{answer_mode}}

Questions:
{{question_list}}

Supporting document text:
{{document_text}}
