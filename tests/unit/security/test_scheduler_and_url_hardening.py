"""Hardening de URLs (SSRF), agendamento e redator — Parte 7/16/33.

Nenhuma decisão desses bloqueios depende do LLM: política de URL, avaliação de
capabilities de execução agendada e redação são estruturais.
"""
from __future__ import annotations

import pytest

import app.perception.vision.verify as _verify  # noqa: E402
import app.security.urlpolicy as _urlpolicy  # noqa: E402
from app.macros.service import SCHEDULED_SAFE_STEPS, macro_requires_confirmation
from app.security.capabilities import is_auto_approvable
from app.security.redact import redact_secrets, redact_text
from app.security.urlpolicy import (
    UnsafeUrlError,
    blocked_url_reason,
    coerce_safe_url,
    normalize_url,
)

# ---- URL policy (Parte 7/39) ----

def test_urlpolicy_blocks_dangerous_schemes():
    blocked = (
        "file:///etc/passwd",
        "data:text/html,<script>",
        "javascript:alert(1)",
        "chrome://settings",
        "about:blank",
    )
    for url in blocked:
        assert blocked_url_reason(url) is not None, url


def test_urlpolicy_blocks_loopback_and_private():
    for url in (
        "http://localhost:9222/json",
        "http://127.0.0.1:9222/json",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://172.16.0.7/",
        "http://192.168.1.10/",
        "http://169.254.169.254/latest/meta-data",
    ):
        assert blocked_url_reason(url) is not None, url


def test_urlpolicy_blocks_alternative_ipv4_forms():
    # 2130706433, 0x7f000001 e 017700000001 são tudo 127.0.0.1.
    for url in (
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0x7F000001/",
        "http://017700000001/",
        "http://127.1/",
        "http://127.0.1/",
    ):
        assert blocked_url_reason(url) is not None, url


def test_urlpolicy_allows_public_numeric_hosts():
    # 8.8.8.8 e 1.2.3.4 são públicos e devem passar.
    assert blocked_url_reason("http://8.8.8.8/") is None
    assert blocked_url_reason("http://1.2.3.4/") is None


def test_urlpolicy_allows_public_https_http():
    assert blocked_url_reason("https://github.com/foo") is None
    assert blocked_url_reason("http://example.com") is None
    assert blocked_url_reason("github.com") is None  # ganha https://


def test_normalize_url_adds_https():
    assert normalize_url("github.com") == "https://github.com"


def test_coerce_safe_url_raises_on_blocked():
    with pytest.raises(UnsafeUrlError):
        coerce_safe_url("file:///etc/passwd")
    with pytest.raises(UnsafeUrlError):
        coerce_safe_url("http://localhost/")
    with pytest.raises(UnsafeUrlError):
        coerce_safe_url("http://2130706433/")


def test_js_scan_blocks_static_private_urls():
    from app.security.urlpolicy import scan_js_for_blocked_urls

    assert (
        scan_js_for_blocked_urls(
            'fetch("http://127.0.0.1:9222/json").then(r => r.json())'
        )
        is not None
    )
    assert (
        scan_js_for_blocked_urls(
            'location.href = "http://169.254.169.254/latest/meta-data";'
        )
        is not None
    )
    # URL pública em fetch passa no scan (defesa heurística).
    assert scan_js_for_blocked_urls('fetch("https://api.github.com")') is None
    # Sem keyword de rede → sem scan.
    assert scan_js_for_blocked_urls("1 + 1") is None


def test_dns_rebinding_to_private_blocked(monkeypatch):
    import socket

    from app.security import urlpolicy

    def fake_addrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(urlpolicy.socket, "getaddrinfo", fake_addrinfo)
    assert blocked_url_reason("http://evil-rebinding.com/") is not None

    def fake_addrinfo_public(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(urlpolicy.socket, "getaddrinfo", fake_addrinfo_public)
    assert blocked_url_reason("http://example.com/") is None


def test_url_allowlist_via_config(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        _urlpolicy,
        "get_settings",
        lambda: SimpleNamespace(
            url_extra_blocked_hosts="evil.example.com",
            url_allowed_hosts="meuteste.localhost",
            url_blocked_ports="",
            url_blocked_host_suffixes="",
        ),
    )
    assert blocked_url_reason("http://evil.example.com/") is not None
    assert blocked_url_reason("http://meuteste.localhost/pagina") is None


def test_vision_semaphore_respects_config(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(_verify, "get_settings", lambda: SimpleNamespace(vision_max_concurrent=1))
    sem = _verify._acquire_vision_slot()
    assert sem._value == 1
    assert sem.locked() is False  # criado disponível


def test_url_ports_and_suffix_config(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        _urlpolicy,
        "get_settings",
        lambda: SimpleNamespace(
            url_extra_blocked_hosts="",
            url_allowed_hosts="",
            url_blocked_ports="9222,9999",
            url_blocked_host_suffixes=".example.com,.corp",
        ),
    )
    assert blocked_url_reason("http://host.example.com/") is not None
    assert blocked_url_reason("http://intra.corp/x") is not None
    assert blocked_url_reason("http://public.example.org:9222/") is not None
    assert blocked_url_reason("http://public.example.org/") is None


def test_vram_guard_blocks_vision_when_pressure(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        _verify, "get_settings", lambda: SimpleNamespace(vision_min_free_vram_mb=512)
    )
    monkeypatch.setattr(_verify, "_nvidia_free_vram_mb", lambda: 100)
    assert _verify._vram_allows_vision() is False


def test_vram_guard_allows_vision_with_free_vram(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        _verify, "get_settings", lambda: SimpleNamespace(vision_min_free_vram_mb=512)
    )
    monkeypatch.setattr(_verify, "_nvidia_free_vram_mb", lambda: 4096)
    assert _verify._vram_allows_vision() is True


def test_bwrap_sandbox_prefix_degrades_gracefully(monkeypatch):
    import shutil

    from app.skills.shell.service import _sandbox_prefix

    # bwrap ausente → fallback (sem prefixo).
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert _sandbox_prefix() is None

    # Windows nunca usa bwrap.
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/bwrap")
    assert _sandbox_prefix() is None

    # Linux com bwrap → prefixo contém bwrap + unshare-net.
    monkeypatch.setattr("os.name", "posix")
    prefix = _sandbox_prefix()
    assert prefix is not None and "bwrap" in prefix and "--unshare-net" in prefix


@pytest.mark.anyio
async def test_open_url_tool_blocks_unsafe_destinations():
    from app.skills.computer.service import ApplicationLauncher
    from app.skills.computer.tools.application import OpenUrlTool

    tool = OpenUrlTool(ApplicationLauncher())
    result = await tool.execute(url="http://127.0.0.1:9222/json")
    assert result.success is False
    assert "bloqueado" in (result.error or "")


@pytest.mark.anyio
async def test_browser_open_tool_blocks_unsafe_destinations():
    from app.skills.browser.tools.open import BrowserOpenTool

    result = await BrowserOpenTool().execute(url="file:///etc/passwd")
    assert result.success is False
    assert "bloqueado" in (result.error or "")


# ---- Scheduler re-eval (Parte 16) ----

def test_scheduled_actions_require_confirmation_fail_closed():
    # Ações de execução/estado/abertura-de-software nunca são auto-aprováveis
    # → agendador recusa. Navegação de URL simples (sem código) permanece
    # permitida ao agendar (não é execução arbitrária).
    for action in ("open_app", "open_file", "task_execute"):
        assert is_auto_approvable(action) is False, action
    assert is_auto_approvable("open_url") is True


def test_macro_steps_classification():
    class Step:
        def __init__(self, step_type):
            self.step_type = step_type

    assert macro_requires_confirmation([Step("type"), Step("press_key")]) is True
    assert macro_requires_confirmation([Step("open_app")]) is True
    assert macro_requires_confirmation([Step("message")]) is False
    assert macro_requires_confirmation([Step("wait")]) is False


def test_scheduled_safe_steps_only_passive():
    assert SCHEDULED_SAFE_STEPS == {"message", "wait", "screenshot", "verify_screen"}


# ---- Redator (Parte 33) ----

def test_redact_tool_arguments_with_embedded_secrets():
    args = {"command": "curl -H 'Authorization: Bearer abcdefghijklmn'", "url": "https://x"}
    scrubbed = redact_secrets(args)
    assert "abcdefghijklmn" not in scrubbed["command"]


def test_redact_nested_credentials():
    data = {"meta": {"aws_access_key_id": "AKIA1234567890", "safe": 1}}
    redacted = redact_secrets(data)
    assert "AKIA1234567890" not in str(redacted["meta"])
    assert redacted["meta"]["safe"] == 1


def test_redact_text_catches_common_forms():
    assert "sk-live-1234567890abcdef" not in redact_text("api_key=sk-live-1234567890abcdef")
    assert "abcdefghij" not in redact_text("Authorization Bearer abcdefghij")