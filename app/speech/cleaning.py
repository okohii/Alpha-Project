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
_VARIATION_SELECTOR_RE = re.compile("[\uFE0E\uFE0F\u200D]")
_SYMBOL_DECORATION_RE = re.compile("[\u20E3]")

# Substituições tipográficas pontuais e seguras vindas de modelos LLM.
# "qe" é um typo comum de "que" em respostas de modelos; "nva" de "na",
# "pra" de "para". Aplicados apenas à saída de voz (nunca ao texto do comando).
_COMMON_TYPO_RE = re.compile(r"\bqe\b|\bnva\b|\bpra\b", re.IGNORECASE)
_TYPO_MAP = {"qe": "que", "nva": "na", "pra": "para"}

# Marcadores de tom/emoção (ex.: "[happy]", "[calm]", "[triste]", "[sad/0.8]")
# NUNCA devem chegar ao TTS: são instruções internas, não fala. Removidos na
# origem da normalização textual, antes da síntese. Só tokens de emoção
# conhecidos são removidos — colchetes arbitrários são preservados.
_EMOTION_WORDS = (
    "happy|sad|calm|angry|excited|curious|surprised|neutral|content|"
    "triste|alegre|calmo|bravo|animado|curioso|neutro|sereno"
)
_EMOTION_TAG_RE = re.compile(
    rf"\s*\[({_EMOTION_WORDS})(?:[/_.: \t-]*\s*\d+(?:\.\d+)?)?\]\s*",
    re.IGNORECASE,
)


def _fix_common_typos(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        return _TYPO_MAP.get(match.group(0).lower(), match.group(0))

    return _COMMON_TYPO_RE.sub(_replace, text)


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
    cleaned = _EMOTION_TAG_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = _fix_common_typos(cleaned)
    return cleaned.strip()
