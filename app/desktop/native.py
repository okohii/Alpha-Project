from __future__ import annotations

import json
import logging
import threading
import time
from queue import Empty, Queue
from typing import Any

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.overlay.astral_core import AstralCore

logger = logging.getLogger(__name__)

_STATE_LABELS = {
    "idle": "Repouso",
    "listening": "Escutando",
    "thinking": "Pensando",
    "planning": "Planejando",
    "executing": "Executando",
    "verifying": "Verificando",
    "speaking": "Falando",
    "success": "Concluído",
    "error": "Erro",
}


class _WebSocketThread(threading.Thread):
    def __init__(self, url: str, incoming: Queue[dict[str, Any]]) -> None:
        super().__init__(name="alpha-native-ws", daemon=True)
        self.url = url
        self.incoming = incoming
        self._outgoing: Queue[dict[str, Any]] = Queue()
        self._stop_event = threading.Event()
        self._ws: Any = None

    def send(self, payload: dict[str, Any]) -> None:
        self._outgoing.put(payload)

    def stop(self) -> None:
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def run(self) -> None:
        try:
            import websocket
        except ImportError:
            self.incoming.put({"type": "error", "message": "websocket-client não instalado"})
            return

        while not self._stop_event.is_set():
            try:
                ws = websocket.create_connection(self.url, timeout=1.0)
                ws.settimeout(0.1)
                self._ws = ws
                self.incoming.put({"type": "connected"})
                while not self._stop_event.is_set():
                    try:
                        while True:
                            payload = self._outgoing.get_nowait()
                            ws.send(json.dumps(payload, ensure_ascii=False))
                    except Empty:
                        pass
                    try:
                        raw = ws.recv()
                    except Exception as exc:
                        if exc.__class__.__name__ in {"WebSocketTimeoutException", "timeout"}:
                            continue
                        break
                    if raw:
                        try:
                            self.incoming.put(json.loads(raw))
                        except json.JSONDecodeError:
                            logger.debug("[DESKTOP] mensagem WS inválida ignorada")
            except Exception as exc:  # noqa: BLE001 - reconexão do shell
                self.incoming.put({"type": "connection_error", "message": str(exc)})
                self._stop_event.wait(0.6)
            finally:
                ws = self._ws
                self._ws = None
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass


class NativeAlphaWindow(QWidget):
    """Janela nativa compartilhada pelo chat overlay e pelo avatar."""

    def __init__(self, *, mode: str, ws_url: str, width: int, height: int) -> None:
        super().__init__()
        self.mode = mode
        self.incoming: Queue[dict[str, Any]] = Queue()
        self.ws = _WebSocketThread(ws_url, self.incoming)
        self.conversation_id: str | None = None
        self._drag_origin: QPoint | None = None

        self.setWindowTitle("ALPHA")
        self.resize(width, height)
        self.setMinimumSize(280, 300)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("""
            QWidget#root { background: rgba(8, 10, 24, 235); border: 1px solid rgba(120, 210, 255, 70); border-radius: 22px; }
            QLabel { color: #e8f7ff; }
            QLineEdit { color: #e8f7ff; background: rgba(255,255,255,16); border: 1px solid rgba(150,220,255,55); border-radius: 14px; padding: 9px 12px; }
            QPushButton { color: #e8f7ff; background: rgba(90,170,255,45); border: 1px solid rgba(150,220,255,55); border-radius: 12px; padding: 7px 11px; }
            QPushButton:hover { background: rgba(90,170,255,75); }
        """)

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._drain_events)
        self._timer.start()
        self.ws.start()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        root.setGeometry(self.rect())
        self.root = root

        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 10, 14, 14)
        outer.setSpacing(5)

        header = QHBoxLayout()
        title = QLabel("ALPHA  ·  ASTRAL CORE")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.state = QLabel("● Repouso")
        self.state.setStyleSheet("color: #79dcff; font-size: 11px;")
        close = QPushButton("×")
        close.setFixedSize(30, 28)
        close.clicked.connect(self.close)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.state)
        header.addWidget(close)
        outer.addLayout(header)

        self.core = AstralCore(root)
        self.core.setMinimumSize(240, 240)
        outer.addWidget(self.core, 1, Qt.AlignmentFlag.AlignCenter)

        self.activity = QLabel("Pronto")
        self.activity.setStyleSheet("color: rgba(220,240,250,180); font-size: 11px;")
        outer.addWidget(self.activity)

        self.log_area = QScrollArea()
        self.log_area.setWidgetResizable(True)
        self.log_area.setFrameShape(QFrame.Shape.NoFrame)
        self.log_container = QWidget()
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setContentsMargins(2, 2, 2, 2)
        self.log_layout.addStretch(1)
        self.log_area.setWidget(self.log_container)
        self.log_area.setMaximumHeight(150 if self.mode == "chat" else 105)
        outer.addWidget(self.log_area)

        if self.mode == "chat":
            row = QHBoxLayout()
            self.input = QLineEdit()
            self.input.setPlaceholderText("Fale com o ALPHA…")
            self.input.returnPressed.connect(self._send_chat)
            send = QPushButton("Enviar")
            send.clicked.connect(self._send_chat)
            row.addWidget(self.input, 1)
            row.addWidget(send)
            outer.addLayout(row)

        self.setMouseTracking(True)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        self.root.setGeometry(self.rect())
        super().resizeEvent(event)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def _send_chat(self) -> None:
        if self.mode != "chat":
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append_log("Você", text)
        payload: dict[str, Any] = {"action": "chat_stream", "message": text}
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id
        self.ws.send(payload)

    def _send(self, payload: dict[str, Any]) -> None:
        self.ws.send(payload)

    def _append_log(self, author: str, text: str) -> None:
        label = QLabel(f"<b>{author}</b>  {text}")
        label.setWordWrap(True)
        label.setStyleSheet("padding: 5px 7px; color: rgba(235,245,250,205);")
        self.log_layout.insertWidget(max(0, self.log_layout.count() - 1), label)
        QTimer.singleShot(0, lambda: self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum()))

    def _set_state(self, state: str) -> None:
        self.core.set_state(state)
        self.state.setText(f"● {_STATE_LABELS.get(state, state.title())}")

    def _execution(self, message: dict[str, Any]) -> None:
        target = message.get("target") or "sistema"
        label = message.get("label") or message.get("event") or "execução"
        success = message.get("success")
        suffix = " ✓" if success is True else "" if success is None else " ✕"
        self.activity.setText(f"{label}: {target}{suffix}")
        self._append_log("ALPHA", self.activity.text())

    def _drain_events(self) -> None:
        processed = 0
        while processed < 40:
            try:
                message = self.incoming.get_nowait()
            except Empty:
                break
            processed += 1
            kind = message.get("type")
            if kind == "state":
                self._set_state(str(message.get("state", "idle")))
            elif kind == "execution":
                self._execution(message)
            elif kind == "caption":
                author = "Você" if message.get("from") == "user" else "ALPHA"
                self._append_log(author, str(message.get("text", "")))
            elif kind == "confirmation":
                tool = message.get("tool", "ação")
                args = message.get("arguments", "")
                self.activity.setText(f"Confirmação: {tool} {args}".strip())
                self._append_confirmation(tool, args)
            elif kind == "done":
                self.conversation_id = message.get("conversation_id") or self.conversation_id
                if self.mode == "chat":
                    self._set_state("idle")
            elif kind == "error":
                self._set_state("error")
                self.activity.setText(str(message.get("message", "erro")))
            elif kind == "connected":
                self.activity.setText("Conectado ao ALPHA Core")
                if self.mode == "avatar":
                    self._send({"action": "start"})
            elif kind == "connection_error":
                self.activity.setText("Conectando ao ALPHA Core…")

    def _append_confirmation(self, tool: str, args: str) -> None:
        box = QFrame()
        box.setStyleSheet("QFrame { background: rgba(255,190,80,22); border: 1px solid rgba(255,190,80,90); border-radius: 12px; }")
        row = QHBoxLayout(box)
        text = QLabel(f"Permitir <b>{tool}</b><br>{args}")
        text.setWordWrap(True)
        deny = QPushButton("Negar")
        allow = QPushButton("Permitir")
        row.addWidget(text, 1)
        row.addWidget(deny)
        row.addWidget(allow)
        deny.clicked.connect(lambda: (self._send({"action": "confirm", "approved": False}), box.deleteLater()))
        allow.clicked.connect(lambda: (self._send({"action": "confirm", "approved": True}), box.deleteLater()))
        self.log_layout.insertWidget(max(0, self.log_layout.count() - 1), box)

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        try:
            self._send({"action": "close"})
            self.ws.stop()
        finally:
            event.accept()


def start_backend(host: str, port: int) -> tuple[Any, threading.Thread]:
    import uvicorn

    config = uvicorn.Config("app.main:app", host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="alpha-native-backend", daemon=True)
    thread.start()
    return server, thread


def run_native(*, mode: str, host: str, port: int, width: int, height: int) -> int:
    """Abre uma UI Qt nativa; FastAPI continua apenas como backend local."""
    from PySide6.QtWidgets import QApplication

    server, _thread = start_backend(host, port)
    ws_path = "avatar" if mode == "avatar" else "overlay"
    ws_url = f"ws://{host}:{port}/{ws_path}/ws"

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ALPHA")
    window = NativeAlphaWindow(mode=mode, ws_url=ws_url, width=width, height=height)
    window.show()
    try:
        return int(app.exec())
    finally:
        server.should_exit = True


__all__ = ["NativeAlphaWindow", "run_native", "start_backend"]
