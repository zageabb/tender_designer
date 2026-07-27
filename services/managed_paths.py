from __future__ import annotations

from pathlib import Path


class ManagedPathError(ValueError):
    pass


def resolve_managed_path(data_dir: Path, value: str | Path, *, must_exist: bool = False) -> Path:
    root = Path(data_dir).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ManagedPathError("Stored file path is outside the managed data directory.")
    if must_exist and not resolved.is_file():
        raise ManagedPathError("The managed file is missing.")
    return resolved


def unlink_managed_file(data_dir: Path, value: str | Path | None) -> bool:
    if not value:
        return False
    path = resolve_managed_path(data_dir, value)
    if not path.exists():
        return False
    if not path.is_file():
        raise ManagedPathError("Managed path does not refer to a file.")
    path.unlink()
    return True
