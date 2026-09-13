from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.perception.vision import verify as vision_verify
from app.security import AccessDeniedError
from app.security.api_gate import require_local_api_auth


@pytest.mark.anyio
async def test_api_gate_fails_closed_without_configured_token(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "local_api_token", "")
    gate = require_local_api_auth("execute")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await gate(authorization=None, x_alpha_token=None)
    assert exc.value.status_code == 403


def test_file_manager_rejects_traversal(tmp_path: Path):
    from app.skills.files.service import FileManager
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    manager = FileManager([allowed])
    with pytest.raises(AccessDeniedError):
        manager._resolve_input("..\\outside.txt", search=False)


def test_visual_verification_skips_when_vram_is_below_policy(monkeypatch):
    monkeypatch.setattr(vision_verify, "_vram_allows_vision", lambda: False)
    assert asyncio.run(vision_verify._vram_allows_vision_async()) is False


@pytest.mark.anyio
async def test_visual_verifier_does_not_convert_oom_to_success(monkeypatch):
    class Provider:
        def available(self): return True
        async def describe(self, *args, **kwargs): raise RuntimeError("CUDA out of memory")

    verifier = vision_verify.OllamaVisionVerifier(Provider())
    monkeypatch.setattr(vision_verify, "_vram_allows_vision_async", lambda: asyncio.sleep(0, result=True))
    result = await verifier.verify("screen.png", "abrir", max_retries=0)
    assert result["achieved"] is None
    assert result["confidence"] == 0.0
