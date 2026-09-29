from __future__ import annotations

import re

import markdown
import nh3
from markupsafe import Markup


_MARKDOWN_EXTENSIONS = [
    "extra",
    "sane_lists",
    "nl2br",
]

_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "strong", "table",
    "tbody", "td", "th", "thead", "tr", "ul",
}

_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "code": {"class"},
    "pre": {"class"},
    "td": {"align"},
    "th": {"align"},
    "table": {"class"},
}

def looks_like_markdown(text: str | None) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    lines = value.splitlines()
    for line in lines[:100]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("~~~", "```", "#", "> ", "- ", "* ", "+ ", "| ")):
            return True
        if re.match(r"^\d+[.)]\s+", stripped):
            return True
        if re.match(r"^\|.+\|$", stripped):
            return True
    return bool(
        re.search(r"\[[^\]]+\]\([^\s)]+\)", value)
        or re.search(r"\*\*[^*]+\*\*", value)
        or re.search(r"~~[^~]+~~", value)
        or re.search(r"`[^`]+`", value)
    )


def extracted_text_suffix(text: str | None) -> str:
    return ".md" if looks_like_markdown(text) else ".txt"


def render_markdown_html(text: str | None) -> Markup:
    """Render modern Markdown and return sanitised HTML safe for Jinja templates.

    Python-Markdown handles nested lists, fenced code, tables, footnotes and the
    rest of the Extra syntax. nh3 then strips unsafe HTML/URLs while preserving
    the generated formatting used by Tender Designer.
    """
    source = (text or "").replace("\r\n", "\n").strip()
    if not source:
        return Markup("")

    # Python-Markdown requires a blank line before a table; legacy Tender
    # Designer content did not. Normalise that case for backwards compatibility.
    normalised_lines: list[str] = []
    previous_was_table = False
    for line in source.split("\n"):
        is_table = bool(re.match(r"^\s*\|.+\|\s*$", line))
        if is_table and normalised_lines and normalised_lines[-1].strip() and not previous_was_table:
            normalised_lines.append("")
        normalised_lines.append(line)
        previous_was_table = is_table
    source = "\n".join(normalised_lines)

    rendered = markdown.markdown(
        source,
        extensions=_MARKDOWN_EXTENSIONS,
        output_format="html",
    )
    rendered = rendered.replace(
        "<table>",
        '<table class="table table-sm table-bordered markdown-table">',
    )
    cleaned = nh3.clean(
        rendered,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        clean_content_tags={"script", "style"},
    )
    return Markup(cleaned)
