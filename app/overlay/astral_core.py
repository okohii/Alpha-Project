from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import Property, QEasingCurve, QObject, QPointF, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget


class AstralCore(QWidget):
    """Lightweight native Qt visual core for the ALPHA overlay.

    The first implementation deliberately uses Qt's painter/animation stack instead
    of a WebView. It gives us a transparent, always-on-top friendly 3D-like core
    without introducing a browser runtime. The renderer is event driven so a future
    Qt Quick/OpenGL scene can replace it without changing the overlay contract.
    """

    stateChanged = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMinimumSize(220, 220)

        self._state = "idle"
        self._energy = 0.0
        self._phase = 0.0
        self._pulse = 0.0
        self._target_pulse = 0.0
        self._last_tick = time.monotonic()

        self._pulse_animation = QPropertyAnimation(self, b"pulse", self)
        self._pulse_animation.setDuration(240)
        self._pulse_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        self._pulse = max(0.0, min(1.0, float(value)))
        self.update()

    pulse = Property(float, _get_pulse, _set_pulse)

    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        state = (state or "idle").lower()
        if state not in {"idle", "listening", "thinking", "speaking", "executing", "success", "error"}:
            state = "idle"
        self._state = state
        targets = {
            "idle": 0.15,
            "listening": 0.65,
            "thinking": 0.45,
            "speaking": 0.85,
            "executing": 0.70,
            "success": 1.0,
            "error": 0.95,
        }
        self._animate_pulse(targets[state])
        self.stateChanged.emit(state)
        self.update()

    def _animate_pulse(self, target: float) -> None:
        self._pulse_animation.stop()
        self._pulse_animation.setStartValue(self._pulse)
        self._pulse_animation.setEndValue(target)
        self._pulse_animation.start()

    def set_audio_level(self, level: float) -> None:
        """Feed normalized microphone/TTS amplitude (0..1)."""
        self._energy = max(0.0, min(1.0, float(level)))
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.05, now - self._last_tick)
        self._last_tick = now
        self._phase = (self._phase + dt * (0.7 + self._pulse * 1.8)) % (math.tau)
        self._energy *= math.exp(-dt * 4.5)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = min(self.width(), self.height()) * 0.25
        activity = max(self._pulse, self._energy)

        # Soft outer aura.
        aura_radius = radius * (1.9 + activity * 0.65)
        gradient = QRadialGradient(center, aura_radius)
        gradient.setColorAt(0.0, QColor(80, 210, 255, int(80 + 70 * activity)))
        gradient.setColorAt(0.45, QColor(80, 120, 255, int(35 + 35 * activity)))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(center, aura_radius, aura_radius)

        # Orbiting rings create the first 3D illusion. Geometry remains native Qt.
        for index, scale in enumerate((1.0, 0.78, 0.58)):
            rect_w = radius * 2.0 * scale
            rect_h = radius * 0.82 * scale
            angle = self._phase * (1.0 if index % 2 == 0 else -0.72) + index * 1.7
            painter.save()
            painter.translate(center)
            painter.rotate(math.degrees(angle))
            pen = QPen(QColor(110, 220, 255, int(95 - index * 18)), 1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(0, 0), rect_w, rect_h)
            painter.restore()

        # Core sphere: radial gradient + highlight + inner energy ring.
        core_radius = radius * (0.78 + activity * 0.12)
        core = QRadialGradient(QPointF(center.x() - core_radius * 0.28, center.y() - core_radius * 0.30), core_radius * 1.25)
        core.setColorAt(0.0, QColor(220, 250, 255, 245))
        core.setColorAt(0.18, QColor(110, 220, 255, 235))
        core.setColorAt(0.55, QColor(65, 90, 220, 190))
        core.setColorAt(1.0, QColor(20, 20, 80, 20))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(core))
        painter.drawEllipse(center, core_radius, core_radius)

        ring_radius = core_radius * (0.65 + activity * 0.28)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(190, 245, 255, 150), 2.0))
        painter.drawEllipse(center, ring_radius, ring_radius)

        # Small orbital particles.
        for index in range(7):
            angle = self._phase * (0.8 + index * 0.06) + index * (math.tau / 7)
            distance = radius * (1.25 + 0.16 * math.sin(self._phase * 2.0 + index))
            point = QPointF(center.x() + math.cos(angle) * distance, center.y() + math.sin(angle) * distance * 0.55)
            particle = 2.0 + activity * 2.0
            painter.setBrush(QColor(150, 235, 255, int(90 + 100 * activity)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(point, particle, particle)

        painter.end()
