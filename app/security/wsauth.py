"""Autorização de WebSockets locais (Avatar / Overlay).

C1 (auditoria de segurança): o canal de comando + confirmação dos WebSockets
não pode ser alcançado por páginas arbitrárias abertas pelo usuário. Regras:

- ``Origin`` presente (browser, UI servida pelo próprio backend): só aceita
  ``http(s)://{host_local}:{porta_local}`` — host local, porta do overlay
  (ou overlay+1 usada pelo avatar nativo);
- sem ``Origin`` (cliente nativo Qt / websocket-client): aceito APENAS quando o
  endereço remoto é loopback — o próprio usuário na máquina.

Qualquer outra combinação é rejeitada antes de ``accept()``, sem que o canal
de confirmação jamais seja exposto.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.core.config import get_settings

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def allowed_ws_hosts() -> set[str]:
    settings = get_settings()
    return {settings.overlay_host, "127.0.0.1", "localhost", "::1"}


def allowed_ws_ports() -> set[int]:
    settings = get_settings()
    return {settings.overlay_port, settings.overlay_port + 1}


def ws_origin_allowed(origin: str | None) -> tuple[bool, str]:
    """Valida uma Origins explícita enviada por um browser."""
    if not origin:
        return False, "Origin ausente"
    if origin == "null":
        return False, "Origin nula (file://) não permitida"
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False, "Origin malformada"
    if parts.scheme not in ("http", "https"):
        return False, f"esquema de Origin não permitido: {parts.scheme}"
    host = (parts.hostname or "").lower()
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False, "porta de Origin inválida"
    if not host:
        return False, "Origin sem host"
    if host not in allowed_ws_hosts():
        return False, f"host de Origin não permitido: {host}"
    if port not in allowed_ws_ports():
        return False, f"porta de Origin não permitida: {port}"
    return True, ""


def ws_client_host_allowed(client_host: str | None) -> bool:
    return (client_host or "").lower() in _LOOPBACK_HOSTS


def validate_websocket_connection(
    origin: str | None,
    client_host: str | None,
) -> tuple[bool, str]:
    """Decisão final de aceite para uma conexão WebSocket local.

    Retorna ``(ok, motivo)``. Chamar ANTES de ``await websocket.accept()``.
    """
    if origin:
        return ws_origin_allowed(origin)
    # Cliente nativo não envia Origin: exige loopback (mesmo usuário).
    if ws_client_host_allowed(client_host):
        return True, ""
    return False, "conexão sem Origin de endereço não-loopback"


def ws_client_host(websocket: Any) -> str | None:
    """Extrai o host remoto do WebSocket de forma tolerante a versões."""
    client = getattr(websocket, "client", None)
    if isinstance(client, tuple):
        return client[0] if client else None
    if isinstance(client, str):
        return client
    return None


__all__ = [
    "allowed_ws_hosts",
    "allowed_ws_ports",
    "validate_websocket_connection",
    "ws_client_host",
    "ws_client_host_allowed",
    "ws_origin_allowed",
]