from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtQuickWidgets import QQuickWidget


class AstralCore(QQuickWidget):
    """Native Qt Quick 3D Astral Core shared by avatar and chat overlay."""

    stateChanged = Signal(str)
    _STATES = {"idle", "listening", "thinking", "planning", "executing", "verifying", "speaking", "success", "error"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setClearColor(QColor(0, 0, 0, 0))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMinimumSize(220, 220)
        qml_path = Path(__file__).with_name("AstralCore.qml")
        self.setSource(QUrl.fromLocalFile(str(qml_path)))
        if self.status() == QQuickWidget.Status.Error:
            errors = "\n".join(str(error) for error in self.errors())
            raise RuntimeError(f"Falha ao carregar Astral Core QML:\n{errors}")

    def _root(self) -> QObject | None:
        return self.rootObject()

    def set_state(self, state: str) -> None:
        normalized = (state or "idle").lower()
        if normalized not in self._STATES: normalized = "idle"
        root = self._root()
        if root is not None: root.setProperty("state", normalized)
        self.stateChanged.emit(normalized)

    def set_audio_level(self, level: float, peak: float | None = None) -> None:
        root = self._root()
        if root is not None:
            root.setProperty("energy", max(0.0, min(1.0, float(level))))
            root.setProperty("peak", max(0.0, min(1.0, float(peak if peak is not None else level))))

    def animate_energy(self, level: float, peak: float = 0.0) -> None:
        self.set_audio_level(level, peak)


__all__ = ["AstralCore"]
