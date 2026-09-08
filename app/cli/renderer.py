from __future__ import annotations

import asyncio
from typing import Any

from rich.console import Console
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from app.cli.events import render_event
from app.cli.panels import banner_text, welcome_panel
from app.cli.themes import Verbosity
from app.core.events import EventType, SystemEvent


class TerminalRenderer:
    """Renderiza a conversa com o ALPHA usando Rich.

    Responsável apenas por apresentar o que o agente produz (eventos) e
    coletar respostas do usuário — não contém lógica de negócio do agente.
    """

    def __init__(
        self,
        console: Console | None = None,
        verbosity: Verbosity = Verbosity.normal,
    ) -> None:
        self.console = console or Console()
        self.verbosity = verbosity
        self._stream_buffer: list[str] = []
        self._streamed = False

    @property
    def is_terminal(self) -> bool:
        return bool(self.console.is_terminal)

    def banner(self) -> None:
        if not self.is_terminal or self.verbosity is Verbosity.quiet:
            return
        self.console.print(banner_text())
        self.console.print(welcome_panel())
        self.console.print(
            "Digite [cyan]/help[/cyan] para ver os comandos. "
            "[cyan]/exit[/cyan] encerra."
        )

    def prompt_user(self) -> str:
        return Prompt.ask("[bold cyan]Você[/bold cyan]") or ""

    def print_user(self, message: str) -> None:
        self.console.print(f"[bold cyan]Você:[/bold cyan] {message}")

    def stream_token(self, token: str) -> None:
        self._streamed = True
        if self.is_terminal and self.verbosity not in (Verbosity.quiet,):
            self.console.print(token, end="", flush=True)
        else:
            self._stream_buffer.append(token)

    def finalize_alpha(self, text: str) -> None:
        if self._streamed:
            if not self.is_terminal:
                text = "".join(self._stream_buffer) or text
            self._streamed = False
            self._stream_buffer.clear()
            self.console.print()
            return
        self._stream_buffer.clear()
        self.console.print(f"[bold green]ALPHA:[/bold green] {text}")

    def info(self, message: str) -> None:
        self.console.print(message, style="dim")

    def ok(self, message: str) -> None:
        self.console.print(message, style="green")

    def warn(self, message: str) -> None:
        self.console.print(message, style="yellow")

    def error(self, message: str) -> None:
        self.console.print(f"[red]erro:[/red] {message}")

    def confirm(self, request: str) -> bool:
        answer = Prompt.ask(f"[yellow]Permitir?[/yellow] {request} [dim][s/N][/dim]", default="n")
        return answer.strip().lower() in ("s", "sim", "y", "yes", "1")

    async def confirm_async(self, request: str) -> bool:
        try:
            return await asyncio.to_thread(self.confirm, request)
        except (EOFError, KeyboardInterrupt):
            return False

    def render_event(self, event: SystemEvent) -> None:
        render_event(self, event)

    def _active_verbosity(self, event_type: EventType) -> Verbosity:
        return self.verbosity

    def _detail(self, event: SystemEvent) -> str:
        duration = ""
        if event.duration_ms is not None:
            duration = f" ({event.duration_ms}ms)"
        return duration

    def table(self, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        table = Table(title=title)
        for column in columns:
            table.add_column(column, overflow="fold")
        for row in rows:
            table.add_row(*(str(cell) for cell in row))
        self.console.print(table)

    def rule(self, title: str = "") -> None:
        self.console.print(Rule(title=title or None, style="cyan"))