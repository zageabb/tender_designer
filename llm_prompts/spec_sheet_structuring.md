# Machine Specification Sheet Structuring Prompt

Turn the Computer Finder research below into factual machine-specification rows for a Word document.

Return JSON only in this exact shape:

{
  "sections": {
    "system": [{"label": "Manufacturer and model", "value": "..."}],
    "connectivity": [{"label": "Wired networking", "value": "..."}],
    "warranty": [{"label": "Warranty", "value": "..."}]
  }
}

Rules:

- Use only facts supported by the research answer and its cited sources.
- The result is dynamic: include rows appropriate to the actual product and omit unsupported fields.
- Put core hardware, dimensions, power/battery, security, display and physical details in `system`.
- Put networking, ports, wireless, audio, expansion and included peripherals in `connectivity`.
- Put software, warranty, compliance, identifiers and other product information in `warranty`.
- Never include price, cost, RRP, MSRP, discounts, totals or commercial pricing fields.
- Do not include source-link rows; the application adds those separately.
- Keep labels short and values concise, but retain exact model numbers, capacities, standards and units.
- Do not invent values or turn requirements into claimed product facts.

Requested specification:
{{computer_spec}}

Computer Finder research answer:
{{research_answer}}

Available sources:
{{sources}}
