"""Detecção de wake word para ativação por voz (estilo Jarvis)."""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    lower = (text or "").strip().lower()
    return unicodedata.normalize("NFKD", lower).encode("ascii", "ignore").decode()


def _tokenize_words(raw_words: str | list[str] | None) -> list[str]:
    if not raw_words:
        return []
    if isinstance(raw_words, str):
        parts = [part.strip() for part in raw_words.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in raw_words if str(part).strip()]
    normalized = {normalize(part) for part in parts if normalize(part)}
    return sorted(normalized, key=len, reverse=True)


def _escape_regex(word: str) -> str:
    return re.escape(word)


def find_wake_word(text: str, raw_words: str | list[str] | None) -> str | None:
    """Devolve a wake word encontrada no texto (ignorando acentos e maiúsculas)."""
    normalized_text = normalize(text)
    if not normalized_text:
        return None
    for word in _tokenize_words(raw_words):
        if not word:
            continue
        # Palavra isolada (fronteira de palavra) para evitar casar "alpha" em "alfalfa".
        pattern = rf"(^|[^\w]){_escape_regex(word)}([^\w]|$)"
        if re.search(pattern, normalized_text):
            return word
    return None


def strip_wake_word(text: str, raw_words: str | list[str] | None) -> tuple[bool, str]:
    """Remove a wake word da fala.

    Retorna ``(achou, restante)``. Se nada restar depois da wake word, o chamador
    deve capturar o próximo trecho de fala como comando.
    """
    word = find_wake_word(text, raw_words)
    if word is None:
        return False, (text or "").strip()
    normalized = normalize(text)
    pattern = rf"(^|[^\w]){_escape_regex(word)}([^\w]|$)"
    remainder = re.sub(pattern, r"\1\2", normalized, count=1)
    remainder = re.sub(r"^[\s,]+", "", remainder)
    remainder = re.sub(r"[\s,]+$", "", remainder)
    remainder = re.sub(r"\s{2,}", " ", remainder)
    return True, remainder.strip()
