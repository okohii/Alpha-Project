"""Acesso à interface gráfica via Windows UI Automation (UIA).

Permite achar elementos pelo rótulo/texto real da interface em vez de
coordenadas chutadas: clicar em "Enviar", ler os campos da janela ativa etc.
Tudo é opcional: se o pywinauto não estiver disponível, available() retorna
False e as tools retornam erro amigável (o fluxo por coordenadas continua).
"""
from __future__ import annotations

import os
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult

_PYAUTO: Any | None = None
_PYAUTO_LOADED = False


def _load_pywinauto() -> Any | None:
    global _PYAUTO, _PYAUTO_LOADED
    if _PYAUTO_LOADED:
        return _PYAUTO
    _PYAUTO_LOADED = True
    if os.name != "nt":
        return None
    try:
        from pywinauto import Desktop

        _PYAUTO = Desktop(backend="uia")
    except Exception:
        _PYAUTO = None
    return _PYAUTO


def available() -> bool:
    return _load_pywinauto() is not None


class UiaError(RuntimeError):
    pass


class ElementNotFoundError(UiaError):
    pass


def _rect_center(element: Any) -> dict[str, Any]:
    rect = element.rectangle()
    x = int((rect.left + rect.right) / 2)
    y = int((rect.top + rect.bottom) / 2)
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
        "x": x,
        "y": y,
    }


_INTERACTIVE_ORDER = {
    "Button": 0,
    "Edit": 1,
    "ComboBox": 2,
    "MenuItem": 3,
    "TabItem": 4,
    "Hyperlink": 5,
    "CheckBox": 6,
    "RadioButton": 7,
    "Text": 8,
    "Document": 9,
    "Pane": 10,
}


def _windows(desktop: Any) -> list[Any]:
    try:
        all_windows = desktop.windows()
    except Exception as exc:
        raise UiaError(f"Não foi possível enumerar janelas: {exc}") from exc
    return [
        win
        for win in all_windows
        if not _is_minimized(win) and _window_title(win)
    ]


def _window_title(win: Any) -> str:
    try:
        return (win.window_text() or "").strip()
    except Exception:
        return ""


def _is_minimized(win: Any) -> bool:
    try:
        return bool(win.is_minimized())
    except Exception:
        return False


def _search(
    text: str,
    window_hint: str | None,
    max_windows: int = 20,
) -> tuple[Any, dict[str, Any]] | None:
    desktop = _load_pywinauto()
    if desktop is None:
        raise UiaError("UI Automation indisponível neste ambiente.")
    needle = (text or "").strip().lower()
    if not needle:
        return None
    best_record: dict[str, Any] | None = None
    best_handle: Any = None
    scanned = 0
    for win in _windows(desktop):
        title = _window_title(win)
        if window_hint and window_hint.lower() not in title.lower():
            continue
        try:
            elements = win.descendants()
        except Exception:
            continue
        for element in elements:
            try:
                name = (element.window_text() or "").strip()
            except Exception:
                continue
            if not name or needle not in name.lower():
                continue
            try:
                info = _rect_center(element)
            except Exception:
                continue
            record = {
                "name": name,
                "control_type": _control_type(element),
                "window": title,
                **info,
            }
            if name.lower() == needle:
                return element, record
            if best_record is None or _prefer(best_record, record):
                best_record = record
                best_handle = element
        scanned += 1
        if scanned >= max_windows:
            break
    if best_record is not None:
        return best_handle, best_record
    return None


def find_element(
    text: str,
    window_hint: str | None = None,
    max_windows: int = 20,
) -> dict[str, Any] | None:
    """Procura um elemento por rótulo. Retorna info com centro (x, y)."""
    found = _search(text, window_hint=window_hint, max_windows=max_windows)
    return found[1] if found else None


def _control_type(element: Any) -> str:
    try:
        return str(element.element_info.control_type or "")
    except Exception:
        return ""


def _prefer(current: dict[str, Any], candidate: dict[str, Any]) -> bool:
    current_type = _INTERACTIVE_ORDER.get(current["control_type"], 99)
    candidate_type = _INTERACTIVE_ORDER.get(candidate["control_type"], 99)
    return candidate_type < current_type


def click_text(text: str, window_hint: str | None = None) -> dict[str, Any]:
    found = _search(text, window_hint=window_hint)
    if found is None:
        raise ElementNotFoundError(f"Elemento '{text}' não encontrado na interface.")
    handle, record = found
    try:
        handle.click_input()
    except Exception as exc:
        raise UiaError(f"Não foi possível clicar em '{text}': {exc}") from exc
    return {
        "clicked": text,
        "window": record["window"],
        "type": record["control_type"],
        "x": record["x"],
        "y": record["y"],
    }


def type_text_into(
    label: str,
    text: str,
    window_hint: str | None = None,
) -> dict[str, Any]:
    """Acha o campo (Edit) por rótulo e preenche com texto."""
    desktop = _load_pywinauto()
    if desktop is None:
        raise UiaError("UI Automation indisponível neste ambiente.")
    needle = (label or "").strip().lower()
    for win in _windows(desktop):
        title = _window_title(win)
        if window_hint and window_hint.lower() not in title.lower():
            continue
        try:
            edits = win.descendants(control_type="Edit")
        except Exception:
            edits = []
        for edit in edits:
            try:
                name = (edit.window_text() or "").strip().lower()
                value = _edit_value(edit)
            except Exception:
                continue
            if needle and needle not in name and needle not in value:
                continue
            try:
                edit.set_focus()
                edit.set_edit_text(text)
            except Exception as exc:
                raise UiaError(
                    f"Não foi possível preencher o campo '{label}': {exc}"
                ) from exc
            return {"field": label, "window": title, "typed": len(text)}
    raise ElementNotFoundError(f"Campo '{label}' não encontrado na interface.")


def _edit_value(edit: Any) -> str:
    try:
        return (edit.window_text() if edit.window_text() else "") or ""
    except Exception:
        try:
            return "".join(edit.texts() or [])
        except Exception:
            return ""


def read_ui_text(window_hint: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Lê a interface atual: controles visíveis com nome e centro (x, y)."""
    desktop = _load_pywinauto()
    if desktop is None:
        raise UiaError("UI Automation indisponível neste ambiente.")
    found: list[dict[str, Any]] = []
    for win in _windows(desktop):
        title = _window_title(win)
        if window_hint and window_hint.lower() not in title.lower():
            continue
        try:
            elements = win.descendants()
        except Exception:
            continue
        for element in elements:
            if len(found) >= limit:
                return found
            try:
                name = (element.window_text() or "").strip()
            except Exception:
                continue
            if not name:
                continue
            try:
                center = _rect_center(element)
            except Exception:
                continue
            found.append(
                {
                    "control_type": _control_type(element) or "Control",
                    "name": name,
                    "window": title,
                    "x": center["x"],
                    "y": center["y"],
                }
            )
    return found


class ClickTextTool(Tool):
    name = "click_text"
    description = (
        "Clica num botão/campo/abapor pelo texto/label real da tela (UI Automation), "
        "ex.: click_text text='enviar' ou text='enviar' hint='discord'. "
        "Prefira a atalhos de teclado se existirem; use screenshot apenas se UIA falhar."
    )
    permission = ToolPermission.write

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not available():
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error=(
                    "UI Automation indisponível "
                    "(pywinauto não instalado ou preciso de Windows)."
                ),
            )
        text = str(kwargs.get("text", "") or "").strip()
        hint = str(kwargs.get("hint", "") or "") or None
        if not text:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Informe o texto a clicar.",
            )
        try:
            result = click_text(text, window_hint=hint)
        except UiaError as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)
        return ToolResult(name=self.name, success=True, data=result)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Texto/label a clicar (ex.: 'enviar', 'salvar')",
                },
                "hint": {
                    "type": "string",
                    "description": "Opcional: nome do app/janela para restringir a busca",
                },
            },
            "required": ["text"],
        }


class ReadUiTool(Tool):
    name = "read_ui"
    description = (
        "Lê a interface atual: lista os controles visíveis com nome e centro (x, y). "
        "Use antes de click_text/mouse_click para saber o que está na tela."
    )
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not available():
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="UI Automation indisponível (pywinauto não instalado ou preciso de Windows).",
            )
        hint = str(kwargs.get("hint", "") or "") or None
        try:
            elements = read_ui_text(window_hint=hint)
        except UiaError as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "elements": elements,
                "count": len(elements),
                "hint": "Use esses nomes no click_text (mais confiável que coordenadas).",
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hint": {
                    "type": "string",
                    "description": "Opcional: nome do app/janela (ex.: 'discord', 'chrome')",
                },
            },
        }