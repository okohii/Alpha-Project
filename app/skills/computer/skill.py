from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Computer",
    description="Automação do computador: apps, janelas, teclado, mouse, tela e UI.",
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
