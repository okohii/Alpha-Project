from __future__ import annotations

import asyncio

from app.perception.vision.verify import _parse_verdict


def test_visual_verdict_requires_explicit_boolean_and_clamps_confidence() -> None:
    result = _parse_verdict('{"achieved": true, "confidence": 2, "feedback": "ok"}')
    assert result["achieved"] is True
    assert result["confidence"] == 1.0


def test_visual_verdict_does_not_promote_unknown_to_success() -> None:
    result = _parse_verdict('{"confidence": 0.99, "feedback": "parece correto"}')
    assert result["achieved"] is None


def test_shared_runtime_infrastructure_is_reused() -> None:
    from app.runtime import application

    application._shared_llm_router = None
    application._shared_skill_registry = None
    first_router = application.get_shared_llm_router()
    second_router = application.get_shared_llm_router()
    first_skills = application.get_shared_skill_registry()
    second_skills = application.get_shared_skill_registry()
    assert first_router is second_router
    assert first_skills is second_skills


def test_asyncio_thread_offload_is_available() -> None:
    async def _run() -> str:
        return await asyncio.to_thread(lambda: "ok")

    assert asyncio.run(_run()) == "ok"
