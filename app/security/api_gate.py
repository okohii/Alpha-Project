"""Gate de autorização para a API local do ALPHA.

Princípio (Parte 2): ``127.0.0.1`` NÃO é tratado como confiável. Operações
sensíveis exigem autorização explícita (token local). Sem token configurado,
a operação é RECUSADA (fail-closed) — superfície reduzida, nunca permissiva.
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from app.core.config import get_settings

# Tipos de operação protegidos.
EXECUTE_ACTION = "execute"


def require_local_api_auth(action: str):
    """Factory de dependência FastAPI (fail-closed) para operações sensíveis.

    Header aceito: ``X-Alpha-Token: <token>`` ou ``Authorization: Bearer <token>``.
    Token vem de ``ALPHA_LOCAL_API_TOKEN``. Vazio → operação bloqueada.
    """

    async def _gate(
        authorization: str | None = Header(default=None),
        x_alpha_token: str | None = Header(default=None),
    ) -> None:
        token = get_settings().local_api_token.strip()
        if not token:
            raise HTTPException(
                status_code=403,
                detail="execução via API desabilitada: configure ALPHA_LOCAL_API_TOKEN",
            )
        provided = (x_alpha_token or "").strip()
        if not provided and authorization and authorization.lower().startswith("bearer "):
            provided = authorization[len("Bearer ") :].strip()
        if not provided or not secrets.compare_digest(provided, token):
            raise HTTPException(
                status_code=403,
                detail="autorização local necessária para esta operação",
            )
        return None

    return _gate