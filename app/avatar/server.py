from __future__ import annotations

import asyncio
import logging
import struct
import threading
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.avatar.controller import AvatarController
from app.avatar.mapping import AnimationMapping
from app.avatar.renderer import AvatarCommand
from app.core.config import get_settings
from app.core.events import EventBus, EventType, SystemEvent
from app.db.session import AsyncSessionLocal
from app.interaction import InteractionManager
from app.perception.wakeword import normalize
from app.runtime import build_agent
from app.security import SENSITIVE_PREFIX
from app.speech import audio_io
from app.speech.cleaning import clean_markdown_artifacts
from app.speech.emotion import EmotionState
from app.speech.pipeline import VoicePipeline

router = APIRouter(prefix="/avatar", tags=["avatar"])
logger = logging.getLogger("app.avatar.server")
UI_DIR = Path(__file__).parent / "ui"
_CONFIRM_TIMEOUT = 180.0
_EXECUTION_EVENTS = {EventType.tool_started, EventType.tool_finished, EventType.tool_failed, EventType.skill_started, EventType.skill_finished, EventType.verification_started, EventType.verification_completed, EventType.task_step_completed, EventType.task_completed, EventType.task_failed, EventType.honesty_gate, EventType.textual_tool_call_blocked}
_EXIT_WORDS = {"sair", "encerrar", "parar", "fechar"}


class AvatarWSRenderer:
    def __init__(self, out: asyncio.Queue[dict[str, Any]]) -> None: self._out = out
    def show(self, command: AvatarCommand) -> None: self._out.put_nowait({"type":"state","state":command.state.value,"animation":command.animation,"expression":command.expression,"emotion":command.emotion,"idle_after_ms":command.idle_after_ms})


def _parse_confirmation_candidate(candidate: str) -> dict[str, str]:
    if candidate.startswith(SENSITIVE_PREFIX):
        rest=candidate[len(SENSITIVE_PREFIX):]; tool_name,sep,args=rest.partition(": ")
        return {"kind":"action","tool":tool_name.strip() if sep else rest.strip(),"arguments":args.strip() if sep else ""}
    return {"kind":"path","tool":"permissão de acesso","arguments":candidate}


def _is_exit(text: str) -> bool:
    """Backward-compatible exact exit-word check used by older callers/tests."""
    return normalize(text).strip(" .,!?;:") in _EXIT_WORDS


def _execution_payload(event: SystemEvent) -> dict[str, Any]:
    payload=dict(event.payload or {}); tool=payload.get("tool") or payload.get("skill") or payload.get("task_id")
    labels={EventType.tool_started:"ferramenta executando",EventType.tool_finished:"ferramenta concluída",EventType.tool_failed:"ferramenta falhou",EventType.skill_started:"skill executando",EventType.skill_finished:"skill concluída",EventType.verification_started:"verificando",EventType.verification_completed:"verificação concluída",EventType.task_step_completed:"passo concluído",EventType.task_completed:"tarefa concluída",EventType.task_failed:"tarefa falhou",EventType.honesty_gate:"controle de evidência",EventType.textual_tool_call_blocked:"tool call bloqueada"}
    return {"type":"execution","event":event.type.value,"label":labels.get(event.type,event.type.value),"target":str(tool or ""),"success":payload.get("success"),"duration_ms":event.duration_ms,"detail":payload.get("error") or payload.get("message") or payload.get("preview") or ""}


class AvatarSession:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket=websocket; self.event_bus=EventBus(); self._out:asyncio.Queue[dict[str,Any]]=asyncio.Queue(); self.avatar=AvatarController(renderer=AvatarWSRenderer(self._out),mapping=AnimationMapping()); self.avatar.subscribe(self.event_bus); self.event_bus.subscribe_all(self._forward_agent_event); self._confirm_queue:asyncio.Queue[bool]=asyncio.Queue(); self.cancel_event=asyncio.Event(); self._voice_task:asyncio.Task[Any]|None=None; self.conversation_id:str|None=None; self._interaction:InteractionManager|None=None
    @property
    def state(self)->str:return self.avatar.state.value
    def _forward_agent_event(self,event:SystemEvent)->None:
        if event.type in _EXECUTION_EVENTS:
            try:self._out.put_nowait(_execution_payload(event))
            except Exception:pass
    async def push(self,payload:dict[str,Any])->None:
        try:await self.websocket.send_json(payload)
        except (WebSocketDisconnect,RuntimeError):pass
    async def pump(self)->None:
        while not self.cancel_event.is_set():
            payload=await self._out.get()
            try:await self.websocket.send_json(payload)
            except (WebSocketDisconnect,RuntimeError):return
    async def permission_request(self,candidate:str)->bool:
        display=_parse_confirmation_candidate(candidate);await self.push({"type":"confirmation","kind":display["kind"],"tool":display["tool"],"arguments":display["arguments"]})
        try:return await asyncio.wait_for(self._confirm_queue.get(),timeout=_CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:return False
    async def receive_loop(self)->None:
        while not self.cancel_event.is_set():
            try:raw=await self.websocket.receive_json()
            except (WebSocketDisconnect,RuntimeError):return
            action=raw.get("action")
            if action=="start":await self._start_voice()
            elif action=="confirm":await self._confirm_queue.put(bool(raw.get("approved",False)))
            elif action=="close":self.cancel_event.set()
            elif action=="ping":await self.push({"type":"pong"})
    async def _start_voice(self)->None:
        if self._voice_task is None or self._voice_task.done():self._voice_task=asyncio.create_task(self._run_voice())
    async def _set_interaction(self,active:bool,reason:str="")->None:
        await self.push({"type":"interaction","state":"active" if active else "dormant","reason":reason})
        if active:await self.push({"type":"avatar_show","animation":"wake","duration_ms":320})
        else:await self.push({"type":"execution_clear"});await self.push({"type":"avatar_hide","animation":"fade","duration_ms":420})
    async def _run_voice(self)->None:
        settings=get_settings()
        if not (settings.stt_enabled and settings.tts_enabled):await self.push({"type":"error","message":"voz desativada: habilite stt_enabled e tts_enabled"});return
        self._interaction=InteractionManager(enabled=settings.wake_word_enabled,wake_words=settings.wake_words,timeout_seconds=settings.interaction_timeout_seconds,end_words=settings.interaction_end_words)
        await self.push({"type":"ready","state":self.state,"voice":"on","wake_word_enabled":settings.wake_word_enabled})
        if not settings.wake_word_enabled:await self._set_interaction(True,"wake_word_disabled")
        else:await self._set_interaction(False,"waiting_for_wake_word")
        async with AsyncSessionLocal() as session:
            agent=await build_agent(session,permission_prompt=self.permission_request,event_bus=self.event_bus,cancel_event=self.cancel_event);pipeline=VoicePipeline(event_bus=self.event_bus);carry:str|None=None
            while not self.cancel_event.is_set():
                if self._interaction and self._interaction.expired():self._interaction.expire();await self._set_interaction(False,"timeout")
                text=carry;carry=None
                if text is None:
                    self.event_bus.emit(EventType.assistant_listening)
                    try:path=await asyncio.to_thread(audio_io.record_microphone_vad,max_wait=60.0)
                    except audio_io.MicrophoneRecordingError as exc:await self.push({"type":"error","message":f"microfone indisponível: {exc}"});return
                    if path is None:continue
                    result=await pipeline.process(path);text=(result.get("transcription") or "").strip()
                if not text:continue
                decision=self._interaction.decide(text) if self._interaction else None
                if decision is None or not decision.accepted:
                    if decision and decision.ended:await self.push({"type":"caption","from":"user","text":text});await self._set_interaction(False,"end_word")
                    continue
                if decision.activated:await self._set_interaction(True,"wake_word")
                await self.push({"type":"caption","from":"user","text":text})
                if not decision.command:continue
                try:answer=await agent.chat(decision.command,conversation_id=self.conversation_id)
                except asyncio.CancelledError:raise
                except Exception as exc:logger.exception("[avatar] turno falhou");await self.push({"type":"error","message":f"falha no turno: {exc}"});continue
                self.conversation_id=answer.get("conversation_id") or self.conversation_id;response=clean_markdown_artifacts(answer["response"]);await self.push({"type":"caption","from":"alpha","text":response})
                if response:carry=await self._speak_interruptible(pipeline,response,emotion=self._emotion(answer))
    @staticmethod
    def _emotion(answer:dict[str,Any])->EmotionState|None:
        payload=answer.get("emotion");return EmotionState.from_dict(payload) if isinstance(payload,dict) else None
    async def _speak_interruptible(self,pipeline:VoicePipeline,text:str,emotion:EmotionState|None)->str|None:
        result=await pipeline.speak_expressive(text,emotion=emotion)
        if result.get("status")!="ok":await self.push({"type":"error","message":str(result.get("detail") or "tts indisponível")});return None
        audio_path=Path(result["audio_path"])
        try:player,frame_rate,n_frames=await asyncio.to_thread(audio_io.play_wav_async,audio_path)
        except audio_io.AudioPlaybackError as exc:await self.push({"type":"error","message":f"áudio indisponível: {exc}"});return None
        speech_started=asyncio.Event();abort=threading.Event();loop=asyncio.get_running_loop();recorder=asyncio.create_task(self._capture_onset(pipeline,speech_started,abort,loop));energy_task=asyncio.create_task(self._emit_speech_energy(audio_path));duration=n_frames/frame_rate if frame_rate else 0.0;playback_done=asyncio.create_task(asyncio.sleep(duration+0.25));started_wait=asyncio.create_task(speech_started.wait())
        await asyncio.wait({playback_done,started_wait},return_when=asyncio.FIRST_COMPLETED)
        if speech_started.is_set():await asyncio.to_thread(audio_io.stop_wav_async,player);playback_done.cancel();energy_task.cancel()
        else:started_wait.cancel();abort.set();energy_task.cancel()
        if speech_started.is_set():
            try:return await recorder
            except Exception:return None
        try:await recorder
        except Exception:pass
        await asyncio.to_thread(audio_io.stop_wav_async,player);return None
    async def _emit_speech_energy(self,audio_path:Path)->None:
        try:
            with wave.open(str(audio_path),"rb") as wav:
                rate=wav.getframerate();width=wav.getsampwidth();channels=wav.getnchannels();chunk=max(1,int(rate*0.04))
                if width not in (1,2,4):return
                fmt={1:"b",2:"h",4:"i"}[width]
                while not self.cancel_event.is_set():
                    raw=wav.readframes(chunk)
                    if not raw:break
                    sample_count=len(raw)//width; samples=struct.unpack("<"+fmt*sample_count,raw)
                    if channels>1:samples=samples[::channels]
                    abs_values=[abs(x) for x in samples];peak=max(abs_values,default=0);rms=(sum(x*x for x in samples)/len(samples))**0.5 if samples else 0.0;max_sample=float((1<<(8*width-1))-1);level=min(1.0,rms/max_sample*2.2);peak_level=min(1.0,peak/max_sample)
                    self._out.put_nowait({"type":"speech_energy","level":level,"peak":peak_level});await asyncio.sleep(min(0.04,max(0.01,chunk/rate)))
        except Exception:logger.debug("[avatar] speech energy indisponível",exc_info=True)
        finally:
            try:self._out.put_nowait({"type":"speech_energy","level":0.0,"peak":0.0})
            except Exception:pass
    async def _capture_onset(self,pipeline:VoicePipeline,speech_started:asyncio.Event,abort:threading.Event,loop:asyncio.AbstractEventLoop)->str|None:
        def _signal()->None:loop.call_soon_threadsafe(speech_started.set)
        path=await asyncio.to_thread(audio_io.record_microphone_vad,on_speech_start=_signal,abort_event=abort)
        if path is None:return None
        result=await pipeline.process(path);return (result.get("transcription") or "").strip() or None


@router.websocket("/ws")
async def avatar_ws(websocket:WebSocket)->None:
    await websocket.accept();logger.debug("[avatar] ws connected");session=AvatarSession(websocket);pump=asyncio.create_task(session.pump());receive=asyncio.create_task(session.receive_loop())
    try:await asyncio.wait({receive,pump},return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect,RuntimeError):pass
    finally:
        session.cancel_event.set()
        if session._voice_task is not None:session._voice_task.cancel()
        for task in (receive,pump):task.cancel()
        await asyncio.gather(receive,pump,return_exceptions=True)
        if session._voice_task is not None:await asyncio.gather(session._voice_task,return_exceptions=True)

@router.get("/health")
async def avatar_health()->dict[str,str]:return {"status":"ok","service":"avatar"}

@router.get("/",include_in_schema=False)
async def avatar_index()->FileResponse:return FileResponse(UI_DIR/"index.html")

@router.get("/ui/{file_path}",include_in_schema=False)
async def avatar_asset(file_path:str)->FileResponse:
    candidate=(UI_DIR/file_path).resolve()
    if candidate.parent!=UI_DIR.resolve() or not candidate.is_file():return FileResponse(UI_DIR/"index.html")
    return FileResponse(candidate)
