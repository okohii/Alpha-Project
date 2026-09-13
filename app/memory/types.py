from __future__ import annotations

from enum import StrEnum


class MemoryType(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"


PERSISTENT_MEMORY_TYPES = frozenset({MemoryType.EPISODIC, MemoryType.SEMANTIC, MemoryType.PREFERENCE})

__all__ = ["MemoryType", "PERSISTENT_MEMORY_TYPES"]
