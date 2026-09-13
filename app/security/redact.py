"""Redactor central de segredos.

Detecta segredos por NOME de chave e por PADRÃO (chaves API, bearer tokens,
credenciais embutidas) — não depende apenas de convenção de campo. Usado
antes da persistência de ToolExecution / memória / eventos.
"""
from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = {
    "password", "passwd", "token", "api_key", "apikey", "auth", "authorization",
    "cookie", "cookies", "secret", "credentials", "credential", "x-api-key",
    "access_token", "refresh_token", "session", "private_key", "client_secret",
}
# Padrões comuns de credenciais no conteúdo (mesmo se a chave não for óbvia).
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE)
_APIKEY_RE = re.compile(r"\b(?:(?:sk|pk|ghp|gho|AKIA)[A-Za-z0-9_\-]{8,})\b")
_AUTHORIZATION_RE = re.compile(
    r"(?i)\b(?:authorization|cookie|x-api-key|api[-_]?key|token|secret|password|credential)"
    r"\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"']{4,}"
)
_REDACTED = "[REDACTED]"

# Chaves/paths que podem indicar um secret persistido (ex.: run_shell com chave).
_SENSITIVE_ARG_KEYWORDS = ("password", "auth", "token", "secret", "key", "credential")


def redact_secrets(value: Any, key: str | None = None) -> Any:
    """Redige segredos recursivamente (por nome de chave e padrão de conteúdo)."""
    if key is not None and _is_secret_key(key):
        return _REDACTED
    if isinstance(value, dict):
        return {str(k): redact_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    if not text:
        return text
    redacted = _BEARER_RE.sub(_REDACTED, text)
    redacted = _APIKEY_RE.sub(_REDACTED, redacted)
    redacted = _AUTHORIZATION_RE.sub(_REDACTED, redacted)
    return redacted


def _is_secret_key(key: str) -> bool:
    lowered = (key or "").lower()
    return any(term in lowered for term in _SECRET_KEYS)


__all__ = ["redact_secrets", "redact_text"]