"""Política de URLs para navegação (SSRF hardening — Parte 7/39).

Bloqueia por padrão (fail-closed):

- schemes fora de http/https (``file:``, ``data:``, ``javascript:``, ``chrome:``,
  ``about:``, '' etc.);
- hosts loopback/localhost e IPs privados/link-local/metadata — incluindo
  formas numéricas alternativas de IPv4 (inteiro decimal/hex/octal e dotted
  curto, ex.: ``http://2130706433/`` = 127.0.0.1);
- hostnames que RESOLVEM para IP privado/loopback (mitigação de DNS rebinding);
- destinos sem host.

O LLM não decide: a decisão é estrutural e aplicada em qualquer entrada
(browser_open, open_url, navegação via CDP).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from app.core.config import get_settings

ALLOWED_SCHEMES = ("http", "https")

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}

_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_INTEGER_HOST_RE = re.compile(r"^(0[xX][0-9a-fA-F]{1,8}|0[0-7]{1,11}|\d{1,10})$")
_SHORT_DOTTED_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){1,2}$")
_HTTP_URL_IN_JS_RE = re.compile(r"""["'](https?://[^"'\s]+)["']""", re.IGNORECASE)
_JS_NETWORK_KEYWORDS = (
    "fetch(",
    "XMLHttpRequest",
    "WebSocket(",
    "navigator.sendBeacon",
    "location.href",
    "location.replace",
    "location.assign",
    "window.open",
)


def normalize_url(value: str) -> str:
    """Normaliza para https:// quando não há scheme explícito.

    Exige ``://`` para reconhecer um scheme (evita tratar ``localhost:8080``
    como scheme ``localhost``). Fonte única de coerção de URL do projeto.
    """
    url = (value or "").strip()
    if not url:
        return url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def _numeric_ipv4(host: str) -> str | None:
    """Converte formas numéricas alternativas de IPv4 (``2130706433``,
    ``0x7f000001``, ``017700000001``, ``127.1``) no dotted-decimal canônico."""
    match = _INTEGER_HOST_RE.match(host)
    if match:
        raw = match.group(0)
        try:
            if raw.lower().startswith("0x"):
                value = int(raw, 16)
            elif raw.startswith("0") and len(raw) > 1:
                # Python 3 não aceita octal em int(..., 0): base explícita.
                value = int(raw, 8)
            else:
                value = int(raw, 10)
        except ValueError:
            return None
        if 0 <= value <= 0xFFFFFFFF:
            return str(ipaddress.ip_address(value))
        return None
    if _SHORT_DOTTED_RE.match(host):
        parts = [int(part) for part in host.split(".")]
        if any(part > 255 for part in parts[:-1]):
            return None
        if len(parts) == 2:
            octets = [parts[0], 0, (parts[1] >> 8) & 0xFF, parts[1] & 0xFF]
        elif len(parts) == 3:
            octets = [parts[0], parts[1], (parts[2] >> 8) & 0xFF, parts[2] & 0xFF]
        else:
            return None
        return ".".join(str(octet) for octet in octets)
    return None


def _private_ip_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if ip.is_loopback or ip.is_link_local:
        return "IP de loopback/link-local"
    if ip.is_private:
        return "IP privado"
    if ip.is_multicast or ip.is_unspecified:
        return "IP multicast/unspecified"
    return "IP reservado"


def _resolved_private_ip(hostname: str) -> str | None:
    """Resolve um hostname e retorna o primeiro IP privado/loopback (DNS rebinding)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return None
    for info in infos[:8]:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_private
            or address.is_multicast
            or address.is_unspecified
        ):
            return str(address)
    return None


def blocked_url_reason(value: str) -> str | None:
    """Retorna o motivo do bloqueio ou ``None`` se a URL for permitida."""
    url = normalize_url(value)
    if not url:
        return "URL vazia"
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return f"scheme proibido: '{scheme or 'nenhum'}'"
    host = parsed.hostname
    if not host:
        return "URL sem host"
    host = host.lower().rstrip(".")
    # Allowlist/extra de bloqueio configurável (Parte 10-step 6).
    extra = _extra_blocked_hosts()
    allowed = _extra_allowed_hosts()
    blocked_ports = _blocked_ports()
    host_suffixes = _blocked_host_suffixes()
    try:
        port = parsed.port
    except ValueError:
        return f"porta inválida na URL: {host}"
    if port is not None and port in blocked_ports:
        return f"porta proibida por config: {port}"
    if any(host.endswith(suffix) for suffix in host_suffixes):
        return f"sufixo de host bloqueado por config: {host}"
    if host in extra:
        return f"host bloqueado por config: {host}"
    if host in allowed:
        return None
    if host in LOOPBACK_HOSTS or host in _METADATA_HOSTS:
        return f"host proibido: {host}"
    if host.endswith(".local") or host.endswith(".internal"):
        return f"host interno proibido: {host}"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Hostname normal → pode ser forma numérica alternativa ou resolver
        # para IP privado (DNS rebinding).
        numeric = _numeric_ipv4(host)
        if numeric is not None:
            try:
                address = ipaddress.ip_address(numeric)
            except ValueError:
                return None
            if (
                address.is_loopback
                or address.is_link_local
                or address.is_private
                or address.is_multicast
                or address.is_unspecified
            ):
                return f"{_private_ip_reason(address)}: {host}"
            return None
        private = _resolved_private_ip(host)
        if private is not None:
            return f"hostname resolve para {private} ({_private_ip_reason(ipaddress.ip_address(private))})"
        return None
    if address.is_loopback or address.is_link_local or address.is_private or address.is_multicast or address.is_unspecified:
        return f"{_private_ip_reason(address)}: {host}"
    return None


def scan_js_for_blocked_urls(code: str) -> str | None:
    """Varre expressões JS por URLs estáticas proibidas (defesa em profundidade).

    Heurístico, NÃO substitui o gate de confirmação de ``browser_js``: um script
    pode montar a URL dinamicamente. Bloqueia apenas URLs literais detectáveis.
    """
    source = (code or "").strip()
    if not source:
        return None
    lowered = source.lower()
    if not any(keyword in lowered for keyword in _JS_NETWORK_KEYWORDS):
        return None
    for match in _HTTP_URL_IN_JS_RE.finditer(source):
        reason = blocked_url_reason(match.group(1))
        if reason:
            return f"URL proibida detectada no script: {reason}"
    return None


def _extra_blocked_hosts() -> set[str]:
    raw = get_settings().url_extra_blocked_hosts or ""
    return {h.strip().lower() for h in str(raw).split(",") if h.strip()}


def _extra_allowed_hosts() -> set[str]:
    raw = get_settings().url_allowed_hosts or ""
    return {h.strip().lower() for h in str(raw).split(",") if h.strip()}


def _blocked_ports() -> set[int]:
    raw = get_settings().url_blocked_ports or ""
    ports: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            ports.add(int(part))
    return ports


def _blocked_host_suffixes() -> list[str]:
    raw = get_settings().url_blocked_host_suffixes or ""
    return [s.strip().lower().lstrip(".") for s in str(raw).split(",") if s.strip()]


def assert_navigable_url(value: str) -> str | None:
    """normaliza e valida; retorna URL normalizada ou None se bloqueada."""
    reason = blocked_url_reason(value)
    if reason:
        return None
    return normalize_url(value)


class UnsafeUrlError(ValueError):
    pass


def coerce_safe_url(value: str) -> str:
    """Normaliza e valida; lança UnsafeUrlError se o destino for proibido."""
    reason = blocked_url_reason(value)
    if reason:
        raise UnsafeUrlError(reason)
    return normalize_url(value)


__all__ = [
    "ALLOWED_SCHEMES",
    "normalize_url",
    "blocked_url_reason",
    "assert_navigable_url",
    "UnsafeUrlError",
    "coerce_safe_url",
    "scan_js_for_blocked_urls",
]