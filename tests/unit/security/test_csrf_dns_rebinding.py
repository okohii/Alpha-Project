from __future__ import annotations

import asyncio
import socket

import pytest

from app.security.api_gate import _origin_matches_local_api
from app.security.urlpolicy import blocked_url_reason
from app.security.wsauth import validate_websocket_connection


def test_api_origin_rejects_cross_origin_browser_request():
    assert _origin_matches_local_api("https://evil.example", "127.0.0.1:8000") is False
    assert _origin_matches_local_api("http://127.0.0.1:8000", "127.0.0.1:8000") is True


def test_api_origin_rejects_port_mismatch():
    assert _origin_matches_local_api("http://127.0.0.1:9000", "127.0.0.1:8000") is False


def test_websocket_origin_rejects_dns_rebinding_style_external_origin():
    ok, _ = validate_websocket_connection("http://evil.example:8000", "127.0.0.1")
    assert ok is False


def test_url_policy_rejects_hostname_that_resolves_to_private(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    reason = blocked_url_reason("https://rebind.example/path")
    assert reason is not None
    assert "192.168.1.10" in reason


def test_url_policy_rejects_numeric_ipv4_alias():
    assert blocked_url_reason("http://2130706433/") is not None


@pytest.mark.anyio
async def test_url_policy_dns_failure_is_not_promoted_to_private(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("DNS indisponível")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    # Falha de DNS não é evidência de segurança nem de perigo; o consumidor
    # deve falhar no próprio request, não tratar como URL privada permitida.
    assert blocked_url_reason("https://example.invalid/") is None
