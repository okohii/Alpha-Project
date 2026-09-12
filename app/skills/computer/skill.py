from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Computer",
    description="Automação do computador: apps, janelas, teclado, mouse, tela e UI.",
    keywords=[
        "abrir aplicativo", "abrir programa", "abrir app", "fechar aplicativo",
        "fechar programa", "janela", "monitor", "atalho", "instalado",
        "clicar", "teclado", "mouse", "print", "screenshot", "digitar",
        "whatsapp", "teams", "slack", "discord", "telegram", "zoom", "skype",
    ],
    tools=[
        "open_app",
        "close_app",
        "list_apps",
        "list_monitors",
        "move_app",
        "type_text",
        "press_key",
        "mouse_click",
        "mouse_scroll",
        "click_text",
        "read_ui",
        "screenshot",
        "verify_screen",
        "detect_camera",
    ],
)

__all__ = ["SKILL"]
