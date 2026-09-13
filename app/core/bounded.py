"""Filas assíncronas com descarte controlado (P-3/backpressure).

Sessões de UI (Avatar/Overlay) não podem crescer sem limite durante bursts
de eventos (``token_stream``, execução pesada). O helper abaixo aplica
``maxsize`` real: ao encher, descarta o item mais ANTIGO e registra a perda —
preserva os eventos mais recentes sem bloquear o emissor.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


def put_dropping_oldest(
    queue: asyncio.Queue[Any],
    item: Any,
    on_drop: Callable[[], None] | None = None,
) -> None:
    """Insere ``item`` com descarte do mais antigo quando a fila está cheia."""
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover - corrida benigna
            pass
        if on_drop is not None:
            on_drop()
    queue.put_nowait(item)


__all__ = ["put_dropping_oldest"]