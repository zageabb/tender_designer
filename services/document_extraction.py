from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path


def extract_text(file_path: str | Path) -> tuple[str, str | None]:
    path = Path(file_path)
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".csv"}:
            return path.read_text(encoding="utf-8", errors="ignore"), None
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text, None
        if suffix == ".docx":
            from docx import Document

            document = Document(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs), None
        if suffix == ".xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(filename=str(path), data_only=True)
            lines: list[str] = []
            for sheet in workbook.worksheets:
                lines.append(f"[Sheet: {sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                    if values:
                        lines.append(" | ".join(values))
            return "\n".join(lines), None
        if suffix == ".eml":
            with path.open("rb") as handle:
                message = BytesParser(policy=policy.default).parse(handle)
            parts = [f"Subject: {message.get('subject', '')}", f"From: {message.get('from', '')}"]
            body = message.get_body(preferencelist=("plain", "html"))
            if body:
                parts.append(body.get_content())
            return "\n\n".join(parts), None
        if suffix == ".msg":
            return "", "MSG extraction is not yet configured in this initial version."
        return "", f"Unsupported file type: {suffix}"
    except Exception as exc:
        return "", str(exc)

