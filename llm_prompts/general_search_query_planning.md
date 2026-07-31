# General Search Query Planning Prompt

Plan focused web searches that answer the user's research request. Return JSON only with keys `requirements`, `expanded_terms`, `queries`, and `negative_terms`.

Return 3 to 6 concise, complementary queries. Cover the main question, important subquestions, and primary or authoritative sources where useful. Do not include `site:` filters or domain names. Do not assume the request is about computers or procurement.

Market context: {{market_context}}

Website scope: {{website_scope}}

Research request:
{{search_request}}
