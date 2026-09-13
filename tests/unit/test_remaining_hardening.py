from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.events import EventBus, EventType
from app.perception.dom import DOMPerceptor, DOMTree
from app.perception.ocr import OCRPerceptor


def _node(node_id: str, text: str, *, visible: bool = True) -> dict:
    return {
        "tag": "button", "id": node_id, "class_name": "", "classes": [],
        "attributes": {"id": node_id}, "text_content": text, "inner_html": None,
        "xpath": f"/html/body/button[@id='{node_id}']", "aria_role": "button",
        "aria_attributes": {}, "visible": visible, "focusable": True,
        "rect": {"left": 0, "top": 0, "width": 80, "height": 24},
    }


@pytest.mark.anyio
async def test_dom_adapter_consumes_real_browser_evaluation() -> None:
    class Browser:
        async def evaluate(self, expression: str):
            assert "querySelectorAll" in expression
            return {"url": "https://example.test", "title": "Example", "nodes": [_node("send", "Enviar")]}

    tree = await DOMPerceptor().perceive_from_browser(Browser())
    assert tree.available is True
    assert tree.root is not None
    assert tree.nodes[0]["text_content"] == "Enviar"


@pytest.mark.anyio
async def test_dom_adapter_fails_closed_when_browser_unavailable() -> None:
    class Browser:
        async def evaluate(self, expression: str):
            raise RuntimeError("CDP caiu")

    tree = await DOMPerceptor().perceive_from_browser(Browser())
    assert tree.available is False
    assert tree.root is None


def test_ocr_never_claims_image_text_without_engine(tmp_path: Path) -> None:
    image = tmp_path / "screen.png"
    image.write_bytes(b"not-a-real-png")
    ocr = OCRPerceptor(executable="")
    result = ocr.perceive(str(image))
    assert result.success is False
    assert result.result is None


@pytest.mark.anyio
async def test_event_bus_async_path_redacts_payload_off_loop() -> None:
    bus = EventBus()
    received: list[dict] = []

    async def handler(event):
        await asyncio.sleep(0)
        received.append(event.payload)

    bus.subscribe(EventType.tool_finished, handler)
    await bus.emit_async(EventType.tool_finished, {"token": "secret", "nested": {"password": "pw"}})
    assert received == [{"token": "[REDACTED]", "nested": {"password": "[REDACTED]"}}]


@pytest.mark.anyio
async def test_event_bus_sync_path_does_not_create_async_handler_task() -> None:
    bus = EventBus()
    called = False

    async def handler(event):
        nonlocal called
        called = True

    bus.subscribe(EventType.agent_progress, handler)
    bus.emit(EventType.agent_progress, {"message": "ok"})
    # emit remains synchronous by contract; async consumers use emit_async.
    assert called is False
