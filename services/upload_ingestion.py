from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import zipfile

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


MAX_ZIP_MEMBERS = 200
MAX_ZIP_MEMBER_SIZE = 25 * 1024 * 1024
MAX_ZIP_EXPANDED_SIZE = 100 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100


@dataclass
class UploadEntry:
    original_name: str
    extension: str
    content: bytes


def _safe_name(name: str) -> str:
    cleaned = secure_filename(name.replace("\\", "/").replace("/", "_"))
    return cleaned or "upload"


def expand_upload_entries(upload: FileStorage, allowed_extensions: set[str]) -> tuple[list[UploadEntry], list[str]]:
    original_name = upload.filename or "upload"
    extension = Path(original_name).suffix.lower()
    payload = upload.read()
    upload.stream.seek(0)

    if extension != ".zip":
        safe_name = _safe_name(original_name)
        safe_ext = Path(safe_name).suffix.lower()
        if safe_ext not in allowed_extensions:
            return [], [f"Skipped unsupported file: {original_name}"]
        return [UploadEntry(original_name=safe_name, extension=safe_ext, content=payload)], []

    entries: list[UploadEntry] = []
    warnings: list[str] = []
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile:
        return [], [f"Could not read zip file: {original_name}"]

    members = [member for member in archive.infolist() if not member.is_dir()]
    if len(members) > MAX_ZIP_MEMBERS:
        return [], [f"Skipped zip file with more than {MAX_ZIP_MEMBERS} entries: {original_name}"]
    total_expanded = 0
    for member in members:
        if member.file_size > MAX_ZIP_MEMBER_SIZE:
            warnings.append(f"Skipped oversized zip entry: {member.filename}")
            continue
        total_expanded += member.file_size
        if total_expanded > MAX_ZIP_EXPANDED_SIZE:
            return [], [f"Skipped zip file exceeding the {MAX_ZIP_EXPANDED_SIZE // (1024 * 1024)} MB expanded limit: {original_name}"]
        ratio = member.file_size / max(member.compress_size, 1)
        if ratio > MAX_ZIP_COMPRESSION_RATIO:
            warnings.append(f"Skipped suspiciously compressed zip entry: {member.filename}")
            continue
        member_name = member.filename.replace("\\", "/").strip("/")
        safe_name = _safe_name(member_name)
        member_ext = Path(safe_name).suffix.lower()
        if member_ext == ".zip":
            warnings.append(f"Skipped nested zip file: {member.filename}")
            continue
        if member_ext not in allowed_extensions:
            warnings.append(f"Skipped unsupported file inside zip: {member.filename}")
            continue
        entries.append(
            UploadEntry(
                original_name=safe_name,
                extension=member_ext,
                content=archive.read(member),
            )
        )
    if not entries and not warnings:
        warnings.append(f"No supported files were found in {original_name}.")
    return entries, warnings
