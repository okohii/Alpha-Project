from __future__ import annotations

import asyncio
from unittest import mock

from rich.console import Console

from app.cli.commands import SlashContext, VerbosityHolder, run_slash
from app.cli.renderer import TerminalRenderer
from app.cli.themes import Verbosity


class _SessionCM:
    def __init__(self) -> None:
        self.session = mock.Mock()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


class _Factory:
    def __call__(self):
        return _SessionCM()


def _ctx() -> SlashContext:
    return SlashContext(
        renderer=TerminalRenderer(console=Console()),
        settings=mock.Mock(),
        verbosity=VerbosityHolder(Verbosity.normal),
        cancel_event=asyncio.Event(),
        session_factory=_Factory(),
        get_agent=lambda: None,
    )


def test_run_slash_exit():
    ctx = _ctx()
    result = asyncio.run(run_slash("/exit", ctx))
    assert result.handled is True
    assert result.exit is True


async def _run(text: str) -> SlashContext:
    ctx = _ctx()
    await run_slash(text, ctx)
    return ctx


def test_run_slash_unknown_not_handled():
    ctx = _ctx()
    result = asyncio.run(run_slash("/xyz", ctx))
    assert result.handled is False


def test_run_slash_cancel_sets_event():
    ctx = _ctx()
    asyncio.run(run_slash("/cancel", ctx))
    assert ctx.cancel_event.is_set()


def test_run_slash_verbosity():
    ctx = _ctx()
    asyncio.run(run_slash("/verbosity debug", ctx))
    assert ctx.verbosity.current is Verbosity.debug
    asyncio.run(run_slash("/verbosity quiet", ctx))
    assert ctx.verbosity.current is Verbosity.quiet


def test_run_slash_verbosity_invalid():
    ctx = _ctx()
    result = asyncio.run(run_slash("/verbosity banana", ctx))
    assert result.handled is True


def test_run_slash_debug_toggles():
    ctx = _ctx()
    asyncio.run(run_slash("/debug", ctx))
    assert ctx.verbosity.current is Verbosity.debug
    asyncio.run(run_slash("/debug", ctx))
    assert ctx.verbosity.current is Verbosity.normal


def test_is_slash_helper():
    from app.cli.commands import is_slash

    assert is_slash("/help")
    assert not is_slash("olá")


def test_help_alias_handled():
    ctx = _ctx()
    result = asyncio.run(run_slash("/?", ctx))
    assert result.handled is True
