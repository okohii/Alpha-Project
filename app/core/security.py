from __future__ import annotations

from pathlib import Path


class PermissionError(Exception):
    pass


class AccessDeniedError(PermissionError):
    def __init__(self, message: str, candidate: str | None = None) -> None:
        super().__init__(message)
        self.candidate = candidate


class SensitiveOperationDisabledError(PermissionError):
    pass


def is_within_allowed_directories(candidate: Path, allowed_directories: list[Path]) -> bool:
    resolved_candidate = candidate.expanduser().resolve()
    for allowed in allowed_directories:
        try:
            resolved_candidate.relative_to(allowed.expanduser().resolve())
            return True
        except ValueError:
            continue
    return False
