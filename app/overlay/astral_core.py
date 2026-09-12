from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtQml import QQmlError


class AstralCore(QQuickWidget):
    """Native Qt Quick 3D Astral Core used by the desktop overlay."""

    stateChanged = Signal(str)

    _STATES = {
        "idle",
        "listening",
        "thinking",
        "planning",
        "executing",
        "verifying",
        "speaking",
        "success",
        "error",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setClearColor(QtColor.transparent)
        self.setAttribute(QtAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtAttribute.WA_NoSystemBackground, True)
        self.setMinimumSize(240, 240)

        qml_path = Path(__file__).with_name("AstralCore.qml")
        self.setSource(QUrl.fromLocalFile(str(qml_path)))
        if self.status() == QQuickWidget.Status.Error:
            errors = "\n".join(str(error) for error in self.errors())
            raise RuntimeError(f"Falha ao carregar Astral Core QML:\n{errors}")

    def _root(self) -> QObject | None:
        return self.rootObject()

    def set_state(self, state: str) -> None:
        normalized = (state or "idle").lower()
        if normalized not in self._STATES:
            normalized = "idle"
        root = self._root()
        if root is not None:
            root.setProperty("state", normalized)
        self.stateChanged.emit(normalized)

    def set_audio_level(self, level: float) -> None:
        root = self._root()
        if root is not None:
            root.setProperty("energy", max(0.0, min(1.0, float(level))))


# Imports kept local to make the module importable only when the desktop extra is installed.
from PySide6.QtCore import Qt as _Qt

QtColor = _Qt.GlobalColor
QtAttribute = _Qt.WidgetAttribute
