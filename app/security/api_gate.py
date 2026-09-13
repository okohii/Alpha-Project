"""Gate de autorização para a API local do ALPHA.

Princípio: loopback não é uma fronteira de confiança. Operações sensíveis
exigem token local e, quando o cliente é um browser, uma Origin local que
corresponda ao Host da API. Isso reduz CSRF e ataques de DNS rebinding que
tentem alcançar a API a partir de uma página arbitrária.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import Header, HTTPException

from app.core.config import get_settings

EXECUTE_ACTION = "execute"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _origin_matches_local_api(origin: str | None, host: str | None) -> bool:
    if not origin:
        # Clientes nativos não têm Origin; continuam protegidos pelo token.
        return True
    if origin == "null":
        return False
    try:
        parts = urlsplit(origin)
        origin_host = (parts.hostname or "").lower()
        origin_port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or origin_host not in _LOOPBACK_HOSTS:
        return False
    request_host = (host or "").split(":", 1)[0].strip("[]").lower()
    if request_host not in _LOOPBACK_HOSTS:
        return False
    # Se o Host traz porta, a Origin deve usar a mesma porta. Sem porta,
    # aceitamos a porta padrão correspondente ao esquema.
    host_port: int | None = None
    raw_host = (host or "").strip()
    if raw_host.startswith("[") and "]" in raw_host:
        tail = raw_host.split("]", 1)[1]
        if tail.startswith(":") and tail[1:].isdigit():
            host_port = int(tail[1:])
    elif raw_host.count(":") == 1 and raw_host.rsplit(":", 1)[1].isdigit():
        host_port = int(raw_host.rsplit(":", 1)[1])
    if host_port is not None and origin_port != host_port:
        return False
    settings = get_settings()
    configured_port = getattr(settings, "overlay_port", 8000)
    if host_port is not None and host_port not in {8000, int(configured_port)}:
        return False
    return True


def require_local_api_auth(action: str):
    """Factory de dependência FastAPI para operações sensíveis (fail-closed)."""

    async def _gate(
        authorization: str | None = Header(default=None),
        x_alpha_token: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        host: str | None = Header(default=None),
    ) -> None:
        # Fora de invocação pelo FastAPI (dep. injetada), os parâmetros podem
        # carregar o sentinela `Header(...)` do Starlette em vez de string.
        # Falha segura: trata como ausente (native client) e segue exigindo
        # token — nunca passa a crashar no parse de Origin.
        if not isinstance(origin, str):
            origin = None
        if not isinstance(host, str):
            host = None
        if not _origin_matches_local_api(origin, host):
            raise HTTPException(
                status_code=403,
                detail="origem não permitida para a API local",
            )
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

    return _gate
