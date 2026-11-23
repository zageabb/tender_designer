"""Extract monthly delivery quantities from selected tender items or documents."""
from __future__ import annotations

import re

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MONTH_RE = "|".join(MONTHS)
ENTRY_RE = re.compile(
    rf"\b(?P<month>{MONTH_RE})\s+(?P<year>20\d{{2}})\s*"
    rf"[:\-–]\s*(?P<quantity>\d{{1,3}}(?:,\d{{3}})*|\d+)\s*"
    rf"(?P<unit>sets?|units?|pcs?|pieces?|items?|laptops?)\b",
    re.IGNORECASE,
)
HEADING_RE = re.compile(
    r"\b(?:tentative\s+)?delivery\s+schedule\s*:\s*", re.IGNORECASE
)
DESCRIPTION_RE = re.compile(r"\bdescription\s*:\s*", re.IGNORECASE)
MONTH_YEAR_RE = re.compile(rf"\b(?:{MONTH_RE})\s+20\d{{2}}\b", re.IGNORECASE)
SEPARATOR_RE = re.compile(r"^[\s|•,;.*_\-–]*$")


def parse_delivery_schedule(text: str) -> tuple[str, list[dict]]:
    """Parse a schedule in multiline extracted text, without swallowing later document content.

    Fail closed on incomplete month entries, overlapping records or duplicate months.
    """
    source = (text or "").replace("\u00a0", " ")
    heading = HEADING_RE.search(source)
    if not heading:
        return "", []

    # Extracted PDF/docx text often separates Description, specification and
    # delivery entries across lines. Pick the closest Description field.
    before = source[:heading.start()]
    description_markers = list(DESCRIPTION_RE.finditer(before))
    specification = (before[description_markers[-1].end():] if description_markers else before).strip(" \n\t|•;*-")
    if not specification:
        return "", []

    after = source[heading.end():]
    matches = list(ENTRY_RE.finditer(after))
    if not matches:
        return "", []

    # The first entry must follow the heading directly. Subsequent entries
    # must be separated only by punctuation / whitespace, otherwise a
    # subsequent unrelated table row might be consumed.
    if not SEPARATOR_RE.fullmatch(after[:matches[0].start()]):
        return "", []
    accepted = [matches[0]]
    for match in matches[1:]:
        gap = after[accepted[-1].end():match.start()]
        if not SEPARATOR_RE.fullmatch(gap):
            break
        accepted.append(match)
    if len(accepted) > 36:
        return "", []

    # If the next token after the last parsed quantity is an incomplete month
    # entry, reject rather than silently generating a partial delivery plan.
    remainder = after[accepted[-1].end():]
    next_month = MONTH_YEAR_RE.search(remainder)
    end_boundary = re.search(r"\n\s*(?:description\s*:|item\s*\d+|[A-Z][A-Za-z ]{2,35}:)", remainder, re.I)
    relevant_remainder = remainder[:end_boundary.start()] if end_boundary else remainder
    if next_month and next_month.start() < len(relevant_remainder):
        return "", []

    seen = set()
    entries = []
    for match in accepted:
        month = match.group("month").capitalize()
        year = int(match.group("year"))
        key = (year, MONTHS.index(month))
        quantity = int(match.group("quantity").replace(",", ""))
        if key in seen or quantity <= 0:
            return "", []
        seen.add(key)
        entries.append({
            "month": month,
            "year": year,
            "quantity": quantity,
            "unit": match.group("unit").lower(),
        })
    return specification, entries


def build_delivery_items(text: str, source_reference: str) -> list[dict]:
    specification, schedule = parse_delivery_schedule(text)
    if not schedule:
        return []
    title = specification.split("•", 1)[0].splitlines()[0].strip(" .|*-")
    if not title:
        return []
    return [
        {
            "description": f"{title} - {row['month']} {row['year']}"[:500],
            "quantity_required": str(row["quantity"]),
            "specification_summary": specification,
            "status": "Needs Review",
            "source_reference": f"{source_reference}; delivery {row['month']} {row['year']} ({row['unit']})",
            "sub_items": [],
            "delivery_month": f"{row['month']} {row['year']}",
            "delivery_unit": row["unit"],
        }
        for row in schedule
    ]
