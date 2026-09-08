from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

ALPHA_ASCII = r"""
                _      
         /\ /\ / _ \  ___
        / _ \/ /_)/ /_/ _ \ 
ALPHA   /_/ /_ |_| \_/\e/_/   
"""

STYLE = "bold cyan"


def banner_text() -> Text:
    return Text(ALPHA_ASCII, style=STYLE)


def welcome_panel() -> Panel:
    return Panel(
        "Agente local-first • memória persistente • tarefas e automação real",
        border_style="cyan",
        title="[bold]bem-vindo[/bold]",
    )