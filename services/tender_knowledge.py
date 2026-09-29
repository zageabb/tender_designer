from __future__ import annotations

import re
from collections import Counter

from models import Tender


MAX_CHUNK_CHARS = 3200
CHUNK_OVERLAP_CHARS = 300
DEFAULT_CONTEXT_CHARS = 28000
DEFAULT_MAX_CHUNKS = 10


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9._/+:-]{1,}", (text or "").casefold())


def _chunk_text(text: str) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", value) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= MAX_CHUNK_CHARS:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + MAX_CHUNK_CHARS)
            chunks.append(paragraph[start:end])
            if end >= len(paragraph):
                current = ""
                break
            start = max(start + 1, end - CHUNK_OVERLAP_CHARS)
    if current:
        chunks.append(current)
    return chunks


def _score(query: str, filename: str, chunk: str) -> float:
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return 0.0
    counts = Counter(_tokens(chunk))
    filename_tokens = set(_tokens(filename))
    matched = sum(1 for token in query_tokens if counts[token])
    weighted = sum(min(counts[token], 3) for token in query_tokens)
    filename_match = len(query_tokens & filename_tokens)
    return (matched * 3.0) + weighted + (filename_match * 4.0)


def build_tender_knowledge_context(
    tender: Tender | None,
    query: str,
    *,
    max_chars: int = DEFAULT_CONTEXT_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> tuple[str, list[dict]]:
    """Return relevant chunks from every processed document attached to a tender."""
    if tender is None:
        return "No active tender knowledge is available.", []

    candidates: list[tuple[float, int, str, str]] = []
    processed_documents = 0
    for document in tender.documents:
        text = (document.extracted_text or "").strip()
        if not text:
            continue
        processed_documents += 1
        for index, chunk in enumerate(_chunk_text(text)):
            candidates.append((_score(query, document.original_filename, chunk), index, document.original_filename, chunk))

    if not candidates:
        return "This tender has no processed document text available yet.", []

    # Relevant chunks first. If the query is very broad, preserve document coverage.
    candidates.sort(key=lambda row: (-row[0], row[2].casefold(), row[1]))
    selected: list[tuple[float, int, str, str]] = []
    seen_documents: set[str] = set()
    for row in candidates:
        if len(selected) >= max_chunks:
            break
        if row[2] not in seen_documents:
            selected.append(row)
            seen_documents.add(row[2])
    for row in candidates:
        if len(selected) >= max_chunks:
            break
        if row not in selected:
            selected.append(row)

    sections: list[str] = []
    sources: list[dict] = []
    used = 0
    for score, index, filename, chunk in selected:
        header = f"[Tender knowledge: {filename} — chunk {index + 1}]"
        section = f"{header}\n{chunk}"
        remaining = max_chars - used
        if remaining <= len(header) + 40:
            break
        if len(section) > remaining:
            section = section[:remaining].rstrip() + "\n[Knowledge chunk truncated]"
        sections.append(section)
        sources.append({"filename": filename, "chunk": index + 1, "score": round(score, 2)})
        used += len(section) + 2

    summary = (
        f"Automatic tender knowledge: {processed_documents} processed document(s) are available. "
        f"{len(sections)} relevant chunk(s) were supplied for this question.\n\n"
    )
    return summary + "\n\n---\n\n".join(sections), sources
