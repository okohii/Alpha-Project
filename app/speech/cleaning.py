"""Limpeza de artefatos de markdown para fala e exibição natural."""

from __future__ import annotations

import re

_CODE_FENCE_RE = re.compile(r"(?s)```[a-zA-Z0-9_+\-]*\s*(.*?)```")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+?\)")
_ASTERISK_RE = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_HASH_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s+")
_BULLET_RE = re.compile(r"(?m)^\s*[•*]\s+")
_MULTI_TRAILING_SPACE_RE = re.compile(r"[ \t]{2,}")
_BEHIND_SPACE_RE = re.compile(r"(?m)^\s+")


def clean_markdown_artifacts(text: str) -> str:
    """Remove marcadores de markdown que poluem leitura (``**``, ``#``, backticks...).

    Mantém parágrafos e listas numeradas legíveis, sem asteriscos/link cru.
    """
    if not text:
        return text
    text = _CODE_FENCE_RE.sub(lambda m: m.group(1), text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _ASTERISK_RE.sub(r"\1", text)
    text = _HASH_HEADING_RE.sub("", text)
    text = _BULLET_RE.sub("- ", text)
    text = _BEHIND_SPACE_RE.sub("", text)
    text = _MULTI_TRAILING_SPACE_RE.sub(" ", text)
    return text.strip()
