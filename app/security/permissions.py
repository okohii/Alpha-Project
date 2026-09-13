from __future__ import annotations

from enum import StrEnum


class PermissionError(Exception):
    pass


class AccessDeniedError(PermissionError):
    def __init__(self, message: str, candidate: str | None = None) -> None:
        super().__init__(message)
        self.candidate = candidate


class SensitiveOperationDisabledError(PermissionError):
    pass


class SecurityLevel(StrEnum):
    """Nível de risco de uma ação. A autorização NÃO é delegada ao LLM."""

    low = "low"  # leitura, pesquisa, navegação
    medium = "medium"  # criação, edição, execução de scripts, envio de mensagem
    high = "high"  # exclusão, operações destrutivas, alterações críticas