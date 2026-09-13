"""Config compartilhada dos testes.

Windows/Python 3.11: a combinação pytest-asyncio + anyio com o loop Proactor
padrão pode abortar a sessão (``INTERNALERROR``) no teardown de loops com
sockets pendentes. Usar a política Selector no ambiente de teste elimina o
crash sem mudar o comportamento das rotinas testadas.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

if sys.platform == "win32":  # pragma: no cover - ambiente específico
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:  # noqa: BLE001 - se a política não estiver disponível, segue
        pass


@pytest.fixture(autouse=True)
def _restore_settings():
    """Isolamento do singleton de settings entre testes.

    ``get_settings()`` é cacheado (``lru_cache``); vários testes mutam campos
    (``llm_mode``, ``agent_auto_approve_sensitive``...) e a mutação vazava para
    os testes seguintes, causando falhas dependentes de ordem. A fixture tira
    um snapshot antes e restaura ao final de cada teste.
    """
    from app.core.config import get_settings

    settings = get_settings()
    try:
        snapshot = settings.model_dump()
    except Exception:  # noqa: BLE001 - versões antigas do pydantic
        snapshot = dict(vars(settings))
    yield
    for key, value in snapshot.items():
        try:
            setattr(settings, key, value)
        except Exception:  # noqa: BLE001 - campos calculados são ignorados
            pass