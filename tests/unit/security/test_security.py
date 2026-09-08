from __future__ import annotations

from pathlib import Path

from app.security import (
    AccessDeniedError,
    PermissionManager,
    SecurityLevel,
    is_within_allowed_directories,
    security_level_for,
)


def test_security_level_low():
    assert security_level_for("web_search") is SecurityLevel.low
    assert security_level_for("file_read") is SecurityLevel.low


def test_security_level_medium():
    assert security_level_for("file_write") is SecurityLevel.high
    assert security_level_for("type_text") is SecurityLevel.medium


def test_security_level_high():
    assert security_level_for("run_shell") is SecurityLevel.high
    assert security_level_for("run_code") is SecurityLevel.high


def test_permission_manager_needs_confirmation():
    manager = PermissionManager()
    assert manager.needs_confirmation("run_shell") is True
    assert manager.needs_confirmation("file_write") is True
    assert manager.needs_confirmation("web_search") is False


def test_permission_manager_disabled():
    manager = PermissionManager(require_confirmation=False, high_risk_require_confirmation=False)
    assert manager.needs_confirmation("run_shell") is False
    assert manager.needs_confirmation("file_write") is False
    assert manager.needs_confirmation("web_search") is False


def test_is_within_allowed_directories():
    allowed = [Path("/data")]
    assert is_within_allowed_directories(Path("/data/a/b.txt"), allowed)
    assert not is_within_allowed_directories(Path("/etc/passwd"), allowed)


def test_access_denied_error_holds_candidate():
    error = AccessDeniedError("negado", candidate="/tmp/x")
    assert error.candidate == "/tmp/x"
