"""Deterministic extraction of monthly delivery quantities from tender descriptions."""
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
HEADING_RE = re.compile(r"\b(?:tentative\s+)?delivery\s+schedule\s*:\s*", re.IGNORECASE)


def parse_delivery_schedule(text: str) -> tuple[str, list[dict]]:
    """Return unchanged product specifications and monthly schedule; reject partial parses."""
    source = (text or "").strip()
    heading = HEADING_RE.search(source)
    if not heading:
        return "", []
    specification = re.sub(r"^\s*description\s*:\s*", "", source[:heading.start()], flags=re.I).strip(" \n\t•;-")
    schedule_text = source[heading.end():]
    matches = list(ENTRY_RE.finditer(schedule_text))
    if not specification or not matches or len(matches) > 36:
        return "", []
    # Do not silently discard unparsed quantities or month text.
    gaps = [schedule_text[:matches[0].start()]]
    gaps.extend(schedule_text[a.end():b.start()] for a, b in zip(matches, matches[1:]))
    gaps.append(schedule_text[matches[-1].end():])
    if any(gap.strip(" \n\t•,;.-") for gap in gaps):
        return "", []
    entries = []
    seen = set()
    for match in matches:
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
    title = specification.split("•", 1)[0].strip(" .")
    # Keep the complete specification as the item summary, not in its 500-char description.
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
