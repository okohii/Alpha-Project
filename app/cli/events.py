from __future__ import annotations

from typing import Any

from app.cli.themes import Verbosity
from app.core.events import EventType, SystemEvent


def _on_progress(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    if verbosity is Verbosity.quiet:
        return
    renderer.console.print(f"[dim]… {event.payload.get('message', '')}[/dim]")


def _on_tool_started(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    if verbosity is Verbosity.quiet:
        return
    tool = (event.payload or {}).get("tool", "?")
    renderer.console.print(f"[dim]⚙ {tool}…[/dim]", style=None)


def _on_tool_finished(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    if verbosity is Verbosity.quiet:
        return
    tool = (event.payload or {}).get("tool", "?")
    success = (event.payload or {}).get("success", True)
    detail = renderer._detail(event)
    if success:
        renderer.console.print(f"[green]✓ {tool}[/green]{detail}")
    else:
        renderer.console.print(f"[red]✗ {tool}[/red]{detail}")


def _on_waiting_confirmation(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    if verbosity is Verbosity.quiet:
        return
    message = (event.payload or {}).get("message") or "Confirmação necessária."
    renderer.console.print(f"[yellow]? {message}[/yellow]")


def _on_memory_created(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    if verbosity is Verbosity.quiet:
        return
    renderer.info("[memória registrada]")


def _on_agent_finished(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    if verbosity in (Verbosity.verbose, Verbosity.debug):
        renderer.info(f"[ok] resposta em {renderer._detail(event).strip('() ')}")


def _on_agent_failed(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    renderer.error((event.payload or {}).get("error", "falha desconhecida"))


def _on_agent_cancelled(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    renderer.warn("Operação cancelada.")


def _on_waiting_input(renderer: Any, event: SystemEvent, verbosity: Verbosity) -> None:
    if verbosity is Verbosity.quiet:
        return
    renderer.console.print(f"[cyan]? {event.payload.get('prompt', 'Digite algo:')}[/cyan]")


HANDLERS: dict[EventType, Any] = {
    EventType.agent_progress: _on_progress,
    EventType.tool_started: _on_tool_started,
    EventType.tool_finished: _on_tool_finished,
    EventType.waiting_confirmation: _on_waiting_confirmation,
    EventType.waiting_input: _on_waiting_input,
    EventType.memory_created: _on_memory_created,
    EventType.agent_finished: _on_agent_finished,
    EventType.agent_failed: _on_agent_failed,
    EventType.agent_cancelled: _on_agent_cancelled,
}


def render_event(renderer: Any, event: SystemEvent) -> None:
    """Renderiza um SystemEvent no renderer fornecido."""
    event_type = event.type
    if event_type is EventType.user_message:
        return
    if event_type is EventType.assistant_message:
        payload = event.payload or {}
        renderer.finalize_alpha(payload.get("content", payload.get("preview", "")))
        return
    if event_type is EventType.token_stream:
        token = (event.payload or {}).get("token", "")
        if token:
            renderer.stream_token(token)
        return
    handler = HANDLERS.get(event_type)
    if handler is None:
        if renderer.verbosity is Verbosity.debug:
            renderer.info(f"[{event_type.value}] {event.payload}")
        return
    active = renderer._active_verbosity(event_type)
    handler(renderer, event, active)