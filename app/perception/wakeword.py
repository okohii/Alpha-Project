"""Detecção de wake word para ativação por voz (estilo Jarvis)."""

from __future__ import annotations

import re
import unicodedata

_DEFAULT_WAKE_WORDS = ("alpha", "alfa")


def normalize(text: str) -> str:
    lower = (text or "").strip().lower()
    return unicodedata.normalize("NFKD", lower).encode("ascii", "ignore").decode()


def _tokenize_words(raw_words: str | list[str] | None) -> list[str]:
    if not raw_words:
        parts = list(_DEFAULT_WAKE_WORDS)
    elif isinstance(raw_words, str):
        parts = [part.strip() for part in raw_words.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in raw_words if str(part).strip()]

    # ALPHA must always respond to both spellings, even when an older .env
    # still contains only WAKE_WORDS=alpha.
    parts.extend(_DEFAULT_WAKE_WORDS)
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


def strip_wake_prefix(text: str, raw_words: str | list[str] | None) -> tuple[bool, str]:
    """Remove a wake word SOMENTE no início, preservando o texto cru.

    Diferente de ``strip_wake_word`` (que remove acentos via NFKD e pode
    remover a palavra no meio da frase), ``strip_wake_prefix`` mantém
    maiúsculas/acentos e a maior parte do conteúdo original reconhecido pelo
    STT — nada além do prefixo do wake word é alterado.
    """
    raw = text or ""
    normalized_text = normalize(raw)
    if not normalized_text:
        return False, raw.strip()
    tokens = sorted(_tokenize_words(raw_words), key=len, reverse=True)

    for word in tokens:
        match = re.match(rf"^\W*{_escape_regex(word)}(?=\W|$)", raw, flags=re.IGNORECASE)
        if match:
            remainder = raw[match.end():]
            remainder = re.sub(r"^[\s,.!?;:)\"']+", "", remainder)
            remainder = re.sub(r"\s{2,}", " ", remainder)
            return True, remainder.strip()

    # Cobre wake word com acento no texto cru (ex.: "Álpha,"): o token
    # normalizado (NFKD) encontra a posição; o conteúdo retornado segue o
    # formato normalizado do wake detector.
    for word in tokens:
        match = re.match(rf"^\W*{_escape_regex(word)}(?=\W|$)", normalized_text)
        if match:
            remainder = normalized_text[match.end():]
            remainder = re.sub(r"^[\s,.!?;:)\"']+", "", remainder)
            remainder = re.sub(r"\s{2,}", " ", remainder)
            return True, remainder.strip()

    return False, raw.strip()
