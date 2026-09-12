from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Computer",
    description="Automação do computador: apps, janelas, teclado, mouse, tela, UI e pesquisa do Windows.",
    keywords=[
        "abrir aplicativo", "abrir programa", "abrir app", "fechar aplicativo",
        "fechar programa", "janela", "monitor", "atalho", "instalado",
        "clicar", "teclado", "mouse", "print", "screenshot", "digitar",
        "pesquisar no windows", "pesquisa do windows", "menu iniciar", "menu do windows",
        "windows search", "win+s", "procurar aplicativo", "buscar aplicativo",
        "whatsapp", "teams", "slack", "discord", "telegram", "zoom", "skype",
        "bloco de notas", "notepad", "notepad++", "notepadpp", "calculadora",
        "paint", "paint do windows", "explorador de arquivos", "windows explorer",
        "gerenciador de arquivos", "prompt de comando", "windows terminal",
        "vscode", "visual studio code", "steam", "obs studio",
    ],
    tools=[
        "open_app", "close_app", "list_apps", "list_monitors", "move_app",
        "type_text", "press_key", "mouse_click", "mouse_scroll", "click_text",
        "read_ui", "screenshot", "verify_screen", "detect_camera", "windows_search",
    ],
)

__all__ = ["SKILL"]
