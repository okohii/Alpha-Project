"""Limpeza de artefatos de markdown e texto decorativo para voz."""

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
_EMOJI_RE = re.compile(
    "["
    "\\U0001F1E6-\\U0001F1FF"  # flags
    "\\U0001F300-\\U0001F5FF"  # symbols/pictographs
    "\\U0001F600-\\U0001F64F"  # emoticons
    "\\U0001F680-\\U0001F6FF"  # transport/maps
    "\\U0001F700-\\U0001F77F"
    "\\U0001F780-\\U0001F7FF"
    "\\U0001F800-\\U0001F8FF"
    "\\U0001F900-\\U0001F9FF"  # supplemental symbols
    "\\U0001FA00-\\U0001FAFF"  # symbols
    "\\u2600-\\u26FF"          # misc symbols
    "\\u2700-\\u27BF"          # dingbats
    "]+",
    re.UNICODE,
)
_VARIATION_SELECTOR_RE = re.compile(r"[\\uFE0E\\uFE0F\\u200D]")
_SYMBOL_DECORATION_RE = re.compile(r"[\\u20E3]")


def clean_markdown_artifacts(text: str) -> str:
    """Remove marcadores de markdown sem alterar o conteúdo textual principal."""
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


def clean_for_voice(text: str) -> str:
    """Prepara a resposta para TTS, removendo emojis e decoração visual."""
    cleaned = clean_markdown_artifacts(text)
    if not cleaned:
        return cleaned
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = _VARIATION_SELECTOR_RE.sub("", cleaned)
    cleaned = _SYMBOL_DECORATION_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
