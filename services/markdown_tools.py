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
}

_ALLOWED_CLASSES = {
    "code": {"language-python", "language-json", "language-sql", "language-bash", "language-shell",
             "language-javascript", "language-js", "language-html", "language-css", "language-text"},
    "pre": {"codehilite"},
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

    rendered = markdown.markdown(
        source,
        extensions=_MARKDOWN_EXTENSIONS,
        output_format="html",
    )
    cleaned = nh3.clean(
        rendered,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        allowed_classes=_ALLOWED_CLASSES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        clean_content_tags={"script", "style"},
    )
    return Markup(cleaned)
