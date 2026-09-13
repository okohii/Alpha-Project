"""Autorização de WebSockets locais (C1) — Avatar e Overlay."""
from __future__ import annotations

from app.security.wsauth import (
    validate_websocket_connection,
    ws_client_host,
    ws_client_host_allowed,
    ws_origin_allowed,
)


def test_origin_same_overlay_port_allowed():
    ok, reason = ws_origin_allowed("http://127.0.0.1:18080")
    assert ok, reason
    ok, reason = ws_origin_allowed("http://localhost:18080")
    assert ok, reason


def test_origin_avatar_port_allowed():
    ok, reason = ws_origin_allowed("http://127.0.0.1:18081")
    assert ok, reason


def test_origin_scheme_not_http_rejected():
    ok, _ = ws_origin_allowed("file:///etc/passwd")
    assert ok is False


def test_origin_foreign_host_rejected():
    ok, _ = ws_origin_allowed("http://evil.example.com:18080")
    assert ok is False
    ok, _ = ws_origin_allowed("http://127.0.0.2:18080")
    assert ok is False


def test_origin_foreign_port_rejected():
    ok, _ = ws_origin_allowed("http://127.0.0.1:9999")
    assert ok is False


def test_origin_null_rejected():
    ok, _ = ws_origin_allowed("null")
    assert ok is False


def test_native_loopback_without_origin_allowed():
    ok, reason = validate_websocket_connection(None, "127.0.0.1")
    assert ok, reason
    ok, _ = validate_websocket_connection(None, "::1")
    assert ok


def test_native_remote_without_origin_rejected():
    ok, _ = validate_websocket_connection(None, "10.0.0.5")
    assert ok is False
    ok, _ = validate_websocket_connection(None, None)
    assert ok is False


def test_browser_origin_allowed_via_validate():
    ok, reason = validate_websocket_connection("http://127.0.0.1:18080", "192.168.1.10")
    assert ok, reason


def test_client_host_loopback():
    assert ws_client_host_allowed("127.0.0.1")
    assert ws_client_host_allowed("::1")
    assert ws_client_host_allowed("192.168.1.10") is False


def test_ws_client_host_tolerates_shapes():
    class _Fake:
        client = ("127.0.0.1", 5555)

    assert ws_client_host(_Fake()) == "127.0.0.1"

    class _FakeStr:
        client = "127.0.0.1"

    assert ws_client_host(_FakeStr()) == "127.0.0.1"

    class _FakeNone:
        client = None

    assert ws_client_host(_FakeNone()) is None