from __future__ import annotations

import json
import logging
import threading
from html import escape
from queue import Empty, Queue
from typing import Any

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.config import get_settings
from app.overlay.astral_core import AstralCore

logger = logging.getLogger(__name__)
_STATE_LABELS = {"idle":"Repouso","listening":"Escutando","thinking":"Pensando","planning":"Planejando","executing":"Executando","verifying":"Verificando","speaking":"Falando","success":"Concluído","error":"Erro"}
_STATE_ICONS = {"idle":"✦","listening":"◉","thinking":"◌","planning":"⌁","executing":"⚙","verifying":"✓","speaking":"◖","success":"✓","error":"!"}
_STATE_COLORS = {"idle":"#66dfff","listening":"#62a8ff","thinking":"#9b7cff","planning":"#c995ff","executing":"#ffb35c","verifying":"#ff6bd6","speaking":"#63f2c2","success":"#72ffad","error":"#ff5d86"}


class _WebSocketThread(threading.Thread):
    def __init__(self, url: str, incoming: Queue[dict[str, Any]]) -> None:
        super().__init__(name="alpha-native-ws", daemon=True)
        self.url = url; self.incoming = incoming; self._outgoing: Queue[dict[str, Any]] = Queue(); self._stop_event = threading.Event(); self._ws: Any = None
    def send(self, payload: dict[str, Any]) -> None:
        if not self._stop_event.is_set(): self._outgoing.put(payload)
    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._ws is not None:
            try: self._ws.close()
            except Exception: pass
        if self.is_alive() and threading.current_thread() is not self: self.join(max(0.0, timeout))
    def run(self) -> None:
        try:
            import websocket
        except ImportError:
            self.incoming.put({"type":"error","message":"websocket-client não instalado"})
            return
        while not self._stop_event.is_set():
            try:
                ws = websocket.create_connection(self.url, timeout=1.0); ws.settimeout(0.1); self._ws = ws; self.incoming.put({"type":"connected"})
                while not self._stop_event.is_set():
                    try:
                        while True: ws.send(json.dumps(self._outgoing.get_nowait(), ensure_ascii=False))
                    except Empty: pass
                    try: raw = ws.recv()
                    except Exception as exc:
                        if exc.__class__.__name__ in {"WebSocketTimeoutException","timeout"}: continue
                        break
                    if raw:
                        try: self.incoming.put(json.loads(raw))
                        except json.JSONDecodeError: logger.debug("[DESKTOP] mensagem WS inválida ignorada")
            except Exception as exc:
                if not self._stop_event.is_set(): self.incoming.put({"type":"connection_error","message":str(exc)}); self._stop_event.wait(0.6)
            finally:
                ws = self._ws; self._ws = None
                if ws is not None:
                    try: ws.close()
                    except Exception: pass


class NativeAlphaWindow(QWidget):
    def __init__(self, *, mode: str, ws_url: str, width: int, height: int) -> None:
        super().__init__()
        self.mode = mode; self.incoming: Queue[dict[str, Any]] = Queue(); self.ws = _WebSocketThread(ws_url, self.incoming)
        self.conversation_id = None; self._drag_origin = None; self._closing = False; self._chat_history: list[tuple[str,str]] = []
        self._startup_done = False; self._avatar_visible = mode != "avatar"; self._execution_timer = QTimer(self); self._execution_timer.setSingleShot(True); self._execution_timer.timeout.connect(self._clear_execution)
        self._confirmation_box: QFrame | None = None
        settings = get_settings(); self._avatar_size = max(220, int(settings.avatar_size)); self._screen_mode = settings.avatar_screen_mode; self._screen_index = int(settings.avatar_screen_index); self._margin = max(8, int(settings.avatar_margin))
        self.setWindowTitle("ALPHA"); self.resize(width if mode == "chat" else self._avatar_size, height if mode == "chat" else self._avatar_size); self.setMinimumSize(420,520) if mode == "chat" else self.setMinimumSize(self._avatar_size, self._avatar_size)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        if mode == "avatar": self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True); self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True); self.setStyleSheet("QWidget { background: transparent; border: none; }")
        else: self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False); self.setStyleSheet("QWidget { background: #080a18; color: #e8f7ff; }")
        self._build_ui(); self._setup_opacity(); self._timer = QTimer(self); self._timer.setInterval(30); self._timer.timeout.connect(self._drain_events); self._timer.start(); self.ws.start()

    def _setup_opacity(self) -> None:
        self._opacity = QGraphicsOpacityEffect(self); self._opacity.setOpacity(1.0); self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self); self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _build_ui(self) -> None:
        self._build_avatar_ui() if self.mode == "avatar" else self._build_chat_ui()

    def _build_avatar_ui(self) -> None:
        root = QWidget(self); root.setObjectName("avatarRoot"); root.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True); root.setStyleSheet("QWidget#avatarRoot { background: transparent; border: none; }"); root.setGeometry(self.rect()); self.root = root
        layout = QVBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0); self.core = AstralCore(root); self.core.setStyleSheet("background: transparent; border: none;"); layout.addWidget(self.core,1)
        self.status_overlay = QLabel(root); self.status_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter); self.status_overlay.setStyleSheet("QLabel { background: transparent; border: none; font-size: 12px; font-weight: bold; }"); self.status_overlay.raise_()
        self.activity = QLabel(root); self.activity.setAlignment(Qt.AlignmentFlag.AlignCenter); self.activity.setWordWrap(True); self.activity.setStyleSheet("QLabel { background: transparent; border: none; color: #e8f7ff; font-size: 10px; }"); self.activity.raise_(); self._update_avatar_hud("idle","Pronto"); self.log_area = None

    def _build_chat_ui(self) -> None:
        root=QWidget(self); root.setObjectName("chatRoot"); root.setGeometry(self.rect()); root.setStyleSheet("QWidget#chatRoot { background: #080a18; color: #e8f7ff; }"); self.root=root; outer=QVBoxLayout(root); outer.setContentsMargins(18,14,18,16); outer.setSpacing(8); header=QHBoxLayout(); title=QLabel("ALPHA"); title.setFont(QFont("Segoe UI",13,QFont.Weight.DemiBold)); subtitle=QLabel("ASSISTENTE"); subtitle.setStyleSheet("color:#71899a;font-size:9px;"); self.state=QLabel("✦ Repouso"); self.state.setStyleSheet("color:#66dfff;font-size:11px;"); copy=QPushButton("Copiar chat"); copy.setFixedHeight(28); copy.clicked.connect(self._copy_chat); close=QPushButton("×"); close.setFixedSize(30,28); close.clicked.connect(self.close); header.addWidget(title); header.addWidget(subtitle); header.addStretch(1); header.addWidget(copy); header.addWidget(self.state); header.addWidget(close); outer.addLayout(header); self.activity=QLabel("Pronto"); self.activity.setStyleSheet("color:#9db8c8;font-size:10px;background:#080a18;"); self.activity.setWordWrap(True); outer.addWidget(self.activity); self.log_area=QScrollArea(); self.log_area.setWidgetResizable(True); self.log_area.setFrameShape(QFrame.Shape.NoFrame); self.log_area.setStyleSheet("QScrollArea{background:#080a18;border:none;}"); self.log_container=QWidget(); self.log_container.setStyleSheet("background:#080a18;"); self.log_layout=QVBoxLayout(self.log_container); self.log_layout.setContentsMargins(2,6,2,6); self.log_layout.setSpacing(8); self.log_layout.addStretch(1); self.log_area.setWidget(self.log_container); outer.addWidget(self.log_area,1); row=QHBoxLayout(); self.input=QLineEdit(); self.input.setPlaceholderText("Fale com o ALPHA…"); self.input.setMinimumHeight(38); self.input.returnPressed.connect(self._send_chat); send=QPushButton("Enviar"); send.setMinimumHeight(38); send.clicked.connect(self._send_chat); row.addWidget(self.input,1); row.addWidget(send); outer.addLayout(row)

    def resizeEvent(self,event:Any)->None:
        if hasattr(self,"root"): self.root.setGeometry(self.rect())
        if self.mode=="avatar" and hasattr(self,"status_overlay"): self.status_overlay.setGeometry(12,max(0,self.height()-54),self.width()-24,24); self.activity.setGeometry(16,max(0,self.height()-34),self.width()-32,30)
        super().resizeEvent(event)

    def mousePressEvent(self,event:Any)->None:
        if event.button()==Qt.MouseButton.LeftButton: self._drag_origin=event.globalPosition().toPoint()-self.frameGeometry().topLeft()
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event:Any)->None:
        if self._drag_origin is not None and event.buttons()&Qt.MouseButton.LeftButton: self.move(event.globalPosition().toPoint()-self._drag_origin)
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event:Any)->None: self._drag_origin=None; super().mouseReleaseEvent(event)

    def _send_chat(self)->None:
        if self.mode!="chat" or self._closing:return
        text=self.input.text().strip()
        if not text:return
        self.input.clear(); self._append_log("Você",text); payload={"action":"chat_stream","message":text}
        if self.conversation_id: payload["conversation_id"]=self.conversation_id
        self.ws.send(payload)
    def _send(self,payload:dict[str,Any])->None:
        if not self._closing:self.ws.send(payload)
    def _append_log(self,author:str,text:str)->None:
        if self.mode!="chat":return
        self._chat_history.append((author,text)); label=QLabel(f"<b>{escape(author)}</b>  {escape(text)}"); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse|Qt.TextInteractionFlag.TextSelectableByKeyboard); label.setStyleSheet("padding:8px 10px;color:#ebf5fa;background:#10152a;border-radius:8px;"); self.log_layout.insertWidget(max(0,self.log_layout.count()-1),label); QTimer.singleShot(0,lambda:self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum()))
    def _copy_chat(self)->None:
        if self.mode!="chat":return
        if not self._chat_history:self.activity.setText("Não há mensagens para copiar"); return
        QApplication.clipboard().setText("\n\n".join(f"{a}: {t}" for a,t in self._chat_history)); self.activity.setText("Chat copiado para a área de transferência"); QTimer.singleShot(2200,lambda:self.activity.setText("Pronto"))

    def _set_state(self,state:str)->None:
        state=state if state in _STATE_LABELS else "idle"
        if self.mode=="chat": self.state.setStyleSheet(f"color:{_STATE_COLORS[state]};font-size:11px;"); self.state.setText(f"{_STATE_ICONS[state]} {_STATE_LABELS[state]}")
        else: self.core.set_state(state); self._update_avatar_hud(state,self.activity.text() or _STATE_LABELS[state])
    def _update_avatar_hud(self,state:str,activity:str)->None:
        if self.mode!="avatar":return
        state=state if state in _STATE_LABELS else "idle"; self.status_overlay.setText(f"{_STATE_ICONS[state]}  {_STATE_LABELS[state]}"); self.status_overlay.setStyleSheet(f"QLabel{{background:transparent;border:none;color:{_STATE_COLORS[state]};font-size:12px;font-weight:bold;}}"); self.activity.setText(activity)

    def _execution(self,message:dict[str,Any])->None:
        target=message.get("target") or "sistema"; label=message.get("label") or message.get("event") or "execução"; detail=str(message.get("detail") or "").strip(); success=message.get("success"); suffix=" ✓" if success is True else "" if success is None else " ✕"; activity=f"{label}: {target}{suffix}"; activity=f"{activity} · {detail[:110]}" if detail and success is not True else activity
        if self.mode=="chat": self.activity.setText(activity); self._append_log("ALPHA",activity)
        else: self._update_avatar_hud("error" if success is False else "executing",activity)
        self._execution_timer.start(900)
    def _clear_execution(self)->None:
        if self.mode=="avatar": self._update_avatar_hud("idle","Pronto")
        elif hasattr(self,"activity"): self.activity.setText("Pronto")

    def _show_avatar(self,fast:bool=False)->None:
        if self.mode!="avatar":return
        self._position_on_target_screen(); self.show(); self.raise_(); self._fade.stop(); self._fade.setDuration(300 if fast else 800); self._fade.setStartValue(0.0); self._fade.setEndValue(1.0); self._fade.start(); self._avatar_visible=True
    def _hide_avatar(self)->None:
        if self.mode!="avatar" or not self._avatar_visible:return
        self._fade.stop(); self._fade.setDuration(420); self._fade.setStartValue(self._opacity.opacity()); self._fade.setEndValue(0.0); self._fade.finished.connect(self._finish_hide); self._fade.start()
    def _finish_hide(self)->None:
        try:self._fade.finished.disconnect(self._finish_hide)
        except (RuntimeError,TypeError):pass
        self.hide(); self._avatar_visible=False; self._opacity.setOpacity(1.0)

    def _target_screen(self):
        app=QApplication.instance()
        if self._screen_mode=="fixed":
            screens=app.screens()
            if 0 <= self._screen_index < len(screens): return screens[self._screen_index]
        if self._screen_mode=="primary": return app.primaryScreen()
        return app.screenAt(QCursor.pos()) or app.primaryScreen()
    def _position_on_target_screen(self)->None:
        screen=self._target_screen()
        if screen is None:return
        geo=screen.availableGeometry(); self.move(geo.left()+self._margin, geo.top()+self._margin)

    def _drain_events(self)->None:
        processed=0
        while processed<60:
            try: message=self.incoming.get_nowait()
            except Empty:break
            processed+=1; kind=message.get("type")
            if kind=="state": self._set_state(str(message.get("state","idle")))
            elif kind=="execution": self._execution(message)
            elif kind=="speech_energy" and self.mode=="avatar": self.core.animate_energy(float(message.get("level",0.0)),float(message.get("peak",0.0)))
            elif kind=="interaction":
                if message.get("state")=="active": self._show_avatar(fast=True); self._set_state("listening")
                else: self._hide_avatar()
            elif kind=="avatar_show": self._show_avatar(fast=True)
            elif kind=="avatar_hide": self._hide_avatar()
            elif kind=="execution_clear": self._clear_execution()
            elif kind=="caption":
                author="Você" if message.get("from")=="user" else "ALPHA"; text=str(message.get("text",""))
                if text and self.mode=="chat": self._append_log(author,text)
                elif text: self._update_avatar_hud("speaking" if author=="ALPHA" else "listening",text[:180])
            elif kind=="confirmation":
                tool=message.get("tool","ação"); args=message.get("arguments","")
                if self.mode=="chat": self.activity.setText(f"Confirmação: {tool} {args}".strip()); self._append_confirmation(tool,args)
                else: self._show_avatar_confirmation(tool,args)
            elif kind=="done":
                self.conversation_id=message.get("conversation_id") or self.conversation_id
                if self.mode=="chat": self._set_state("idle")
            elif kind=="error":
                self._set_state("error")
                if self.mode=="chat": self.activity.setText(str(message.get("message","erro")))
                elif self.mode=="avatar": self._update_avatar_hud("error",str(message.get("message","erro"))[:180])
            elif kind=="connected":
                if self.mode=="chat": self.activity.setText("Conectado ao ALPHA Core")
                else: self._send({"action":"start"}); QTimer.singleShot(900,self._hide_avatar)
            elif kind=="connection_error":
                if self.mode=="chat": self.activity.setText("Conectando ao ALPHA Core…")
                else: self._update_avatar_hud("error","Conectando ao ALPHA Core…")

    def _show_avatar_confirmation(self,tool:str,args:str)->None:
        if self.mode!="avatar":return
        if self._confirmation_box is not None:
            self._confirmation_box.deleteLater(); self._confirmation_box=None
        box=QFrame(self); box.setObjectName("avatarConfirmation"); box.setStyleSheet("QFrame#avatarConfirmation{background:#0b1020;border:2px solid #ffb35c;border-radius:14px;} QLabel{background:transparent;color:#f5fbff;font-size:10px;font-weight:600;} QPushButton{background:#18233a;color:#ffffff;border:1px solid #5f7690;border-radius:8px;padding:5px 9px;font-size:10px;font-weight:700;} QPushButton:hover{background:#243653;} QPushButton#allow{background:#6b4a16;border-color:#ffc15f;} QPushButton#allow:hover{background:#8a611d;}")
        box.setGeometry(6, max(6,self.height()-112), self.width()-12, 106); layout=QVBoxLayout(box); layout.setContentsMargins(9,7,9,7); layout.setSpacing(5)
        label=QLabel(f"Permitir: {escape(tool)}\n{escape(args)[:100]}",box); label.setWordWrap(True); layout.addWidget(label,1)
        row=QHBoxLayout(); row.setSpacing(6); deny=QPushButton("Negar",box); allow=QPushButton("Permitir",box); allow.setObjectName("allow"); row.addWidget(deny,1); row.addWidget(allow,1); layout.addLayout(row)
        deny.clicked.connect(lambda:self._resolve_avatar_confirmation(False,box)); allow.clicked.connect(lambda:self._resolve_avatar_confirmation(True,box)); box.show(); box.raise_(); self._confirmation_box=box; self._update_avatar_hud("verifying","Aguardando permissão…")

    def _resolve_avatar_confirmation(self,approved:bool,box:QFrame)->None:
        self._send({"action":"confirm","approved":approved})
        if self._confirmation_box is box:self._confirmation_box=None
        box.deleteLater(); self._update_avatar_hud("listening","Pronto")

    def _append_confirmation(self,tool:str,args:str)->None:
        box=QFrame(); box.setStyleSheet("QFrame{background:#332a18;border:1px solid #8a6a2d;border-radius:12px;}"); row=QHBoxLayout(box); text=QLabel(f"Permitir <b>{escape(tool)}</b><br>{escape(args)}"); text.setWordWrap(True); deny=QPushButton("Negar"); allow=QPushButton("Permitir"); row.addWidget(text,1); row.addWidget(deny); row.addWidget(allow); deny.clicked.connect(lambda:(self._send({"action":"confirm","approved":False}),box.deleteLater())); allow.clicked.connect(lambda:(self._send({"action":"confirm","approved":True}),box.deleteLater())); self.log_layout.insertWidget(max(0,self.log_layout.count()-1),box)

    def closeEvent(self,event:Any)->None:
        if self._closing:event.accept();return
        self._closing=True; self._timer.stop()
        try:self.ws.send({"action":"close"})
        except Exception:pass
        finally:self.ws.stop(timeout=2.0); event.accept()


def start_backend(host:str,port:int)->tuple[Any,threading.Thread]:
    import uvicorn
    config=uvicorn.Config("app.main:app",host=host,port=port,log_level="warning",access_log=False); server=uvicorn.Server(config); thread=threading.Thread(target=server.run,name="alpha-native-backend",daemon=True); thread.start(); return server,thread


def run_native(*,mode:str,host:str,port:int,width:int,height:int)->int:
    server,backend_thread=start_backend(host,port); ws_path="avatar" if mode=="avatar" else "overlay"; ws_url=f"ws://{host}:{port}/{ws_path}/ws"; app=QApplication.instance() or QApplication([]); app.setApplicationName("ALPHA"); window=NativeAlphaWindow(mode=mode,ws_url=ws_url,width=width,height=height)
    if mode=="avatar": window._show_avatar(fast=False)
    else: window.show()
    try:return int(app.exec())
    finally:
        try:
            if not window._closing:window.close()
        except Exception:pass
        server.should_exit=True
        if backend_thread.is_alive():backend_thread.join(timeout=3.0)
        logger.info("[DESKTOP] native shutdown complete")


__all__=["NativeAlphaWindow","run_native"]