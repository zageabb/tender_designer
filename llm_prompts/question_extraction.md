# Question Extraction Prompt

You are extracting genuine tender questions and written response requirements.
Return JSON only with a `questions` array.
Each question should contain: question_number, section, question_text, source_reference.
Exclude statements that are not true questions or explicit response requirements.

Tender text:
{{tender_text}}
