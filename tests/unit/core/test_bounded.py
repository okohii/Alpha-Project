"""Filas assíncronas limitadas (P-3): descarte controlado sem bloquear o emissor."""
from __future__ import annotations

import asyncio

from app.core.bounded import put_dropping_oldest


def test_bounded_drops_oldest_on_overflow():
    queue: asyncio.Queue[int] = asyncio.Queue(maxsize=3)
    for value in range(5):
        put_dropping_oldest(queue, value)

    assert queue.qsize() == 3
    # os 2 mais antigos foram descartados; restam 2, 3, 4.
    assert queue.get_nowait() == 2
    assert queue.get_nowait() == 3
    assert queue.get_nowait() == 4


def test_bounded_reports_drop():
    dropped = 0
    queue: asyncio.Queue[int] = asyncio.Queue(maxsize=2)

    def _on_drop() -> None:
        nonlocal dropped
        dropped += 1

    for value in range(4):
        put_dropping_oldest(queue, value, on_drop=_on_drop)

    assert dropped == 2


def test_bounded_keeps_all_within_limit():
    queue: asyncio.Queue[int] = asyncio.Queue(maxsize=10)
    for value in range(5):
        put_dropping_oldest(queue, value)
    assert queue.qsize() == 5
    assert queue.get_nowait() == 0