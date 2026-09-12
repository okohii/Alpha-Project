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
from app.speech.cleaning import clean_for_voice
from app.speech.emotion import EmotionState
from app.speech.pipeline import VoicePipeline

router = APIRouter(prefix="/avatar", tags=["avatar"])
logger = logging.getLogger("app.avatar.server")
UI_DIR = Path(__file__).parent / "ui"
_CONFIRM_TIMEOUT = 180.0
_CONFIRM_YES = {"sim", "sima", "pode", "permitir", "permite", "confirmo", "confirmar", "ok", "okay", "certo", "pode fazer", "pode clicar"}
_CONFIRM_NO = {"nao", "não", "nega", "negar", "cancelar", "cancela", "não pode", "nao pode", "pare", "parar"}
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


def _is_exit(text: str) -> bool: return normalize(text).strip(" .,!?;:") in _EXIT_WORDS


def _execution_payload(event: SystemEvent) -> dict[str, Any]:
    payload=dict(event.payload or {}); tool=payload.get("tool") or payload.get("skill") or payload.get("task_id")
    labels={EventType.tool_started:"ferramenta executando",EventType.tool_finished:"ferramenta concluída",EventType.tool_failed:"ferramenta falhou",EventType.skill_started:"skill executando",EventType.skill_finished:"skill concluída",EventType.verification_started:"verificando",EventType.verification_completed:"verificação concluída",EventType.task_step_completed:"passo concluído",EventType.task_completed:"tarefa concluída",EventType.task_failed:"tarefa falhou",EventType.honesty_gate:"controle de evidência",EventType.textual_tool_call_blocked:"tool call bloqueada"}
    return {"type":"execution","event":event.type.value,"label":labels.get(event.type,event.type.value),"target":str(tool or ""),"success":payload.get("success"),"duration_ms":event.duration_ms,"detail":payload.get("error") or payload.get("message") or payload.get("preview") or ""}


class AvatarSession:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket=websocket; self.event_bus=EventBus(); self._out:asyncio.Queue[dict[str,Any]]=asyncio.Queue(); self.avatar=AvatarController(renderer=AvatarWSRenderer(self._out),mapping=AnimationMapping()); self.avatar.subscribe(self.event_bus); self.event_bus.subscribe_all(self._forward_agent_event); self._confirm_queue:asyncio.Queue[bool]=asyncio.Queue(); self.cancel_event=asyncio.Event(); self._voice_task:asyncio.Task[Any]|None=None; self._confirmation_voice_task:asyncio.Task[Any]|None=None; self.conversation_id:str|None=None; self._interaction:InteractionManager|None=None; self._confirmation_pending=False
    @property
    def state(self)->str:return self.avatar.state.value
    def _forward_agent_event(self,event:SystemEvent)->None:
        if event.type in _EXECUTION_EVENTS:
            logger.info("[avatar:event] type=%s payload=%s duration_ms=%s",event.type.value,event.payload,event.duration_ms)
            try:self._out.put_nowait(_execution_payload(event))
            except Exception:logger.debug("[avatar:event] output queue failed",exc_info=True)
    async def push(self,payload:dict[str,Any])->None:
        logger.debug("[avatar:ws->ui] %s",payload)
        try:await self.websocket.send_json(payload)
        except (WebSocketDisconnect,RuntimeError):pass
    async def pump(self)->None:
        while not self.cancel_event.is_set():
            payload=await self._out.get(); logger.debug("[avatar:pump] %s",payload)
            try:await self.websocket.send_json(payload)
            except (WebSocketDisconnect,RuntimeError):return
    async def _listen_confirmation_voice(self,pipeline:VoicePipeline)->None:
        logger.info("[confirm] voice_listener_start timeout=%ss",_CONFIRM_TIMEOUT)
        deadline=asyncio.get_running_loop().time()+_CONFIRM_TIMEOUT
        try:
            while not self.cancel_event.is_set() and asyncio.get_running_loop().time()<deadline and self._confirmation_pending:
                try:
                    path=await asyncio.to_thread(audio_io.record_microphone_vad,max_wait=8.0,silence_pad=0.80,min_speech_duration=0.25,abort_event=threading.Event())
                except audio_io.MicrophoneRecordingError as exc:
                    logger.exception("[confirm] microphone_error: %s",exc); return
                if path is None:
                    logger.debug("[confirm] no_speech; continuing")
                    continue
                logger.info("[confirm] audio=%s",path)
                try: result=await pipeline.process(path)
                except Exception as exc:
                    logger.exception("[confirm] stt_error: %s",exc); continue
                text=normalize(str(result.get("transcription") or "")).strip(" .,!?;:")
                logger.info("[confirm] transcription=%r confidence=%s suspicious=%s",text,result.get("confidence"),result.get("is_suspicious"))
                if not text: continue
                if text in _CONFIRM_YES or any(text.startswith(word+" ") for word in _CONFIRM_YES):
                    logger.info("[confirm] approved by voice: %r",text); await self._confirm_queue.put(True); return
                if text in _CONFIRM_NO or any(text.startswith(word+" ") for word in _CONFIRM_NO):
                    logger.info("[confirm] denied by voice: %r",text); await self._confirm_queue.put(False); return
                logger.debug("[confirm] unrelated transcription=%r",text)
        finally:
            logger.info("[confirm] voice_listener_end pending=%s",self._confirmation_pending)
    async def permission_request(self,candidate:str)->bool:
        display=_parse_confirmation_candidate(candidate); self._confirmation_pending=True
        logger.info("[confirm] request candidate=%r display=%s",candidate,display)
        await self.push({"type":"confirmation","kind":display["kind"],"tool":display["tool"],"arguments":display["arguments"]})
        if self._confirmation_voice_task is not None and not self._confirmation_voice_task.done(): self._confirmation_voice_task.cancel()
        pipeline=getattr(self,"_pipeline",None)
        if pipeline is not None: self._confirmation_voice_task=asyncio.create_task(self._listen_confirmation_voice(pipeline))
        try:
            approved=await asyncio.wait_for(self._confirm_queue.get(),timeout=_CONFIRM_TIMEOUT)
            logger.info("[confirm] resolved approved=%s",approved); return approved
        except asyncio.TimeoutError:
            logger.warning("[confirm] timeout after %ss",_CONFIRM_TIMEOUT); return False
        finally:
            self._confirmation_pending=False
            task=self._confirmation_voice_task
            if task is not None and not task.done(): task.cancel()
            logger.info("[confirm] request_end")
    async def receive_loop(self)->None:
        logger.info("[avatar] websocket receive_loop_start")
        while not self.cancel_event.is_set():
            try: raw=await self.websocket.receive_json()
            except (WebSocketDisconnect,RuntimeError):return
            logger.debug("[avatar:ui->server] %s",raw)
            action=raw.get("action")
            if action=="start":await self._start_voice()
            elif action=="confirm":
                approved=bool(raw.get("approved",False)); logger.info("[confirm] resolved by UI approved=%s",approved); await self._confirm_queue.put(approved)
            elif action=="close":self.cancel_event.set()
            elif action=="ping":await self.push({"type":"pong"})
    async def _start_voice(self)->None:
        if self._voice_task is None or self._voice_task.done(): logger.info("[avatar] starting voice task"); self._voice_task=asyncio.create_task(self._run_voice())
        else: logger.debug("[avatar] voice task already running")
    async def _set_interaction(self,active:bool,reason:str="")->None:
        logger.info("[interaction] state=%s reason=%s", "active" if active else "dormant",reason); await self.push({"type":"interaction","state":"active" if active else "dormant","reason":reason})
        if active:await self.push({"type":"avatar_show","animation":"wake","duration_ms":320})
        else:await self.push({"type":"execution_clear"});await self.push({"type":"avatar_hide","animation":"fade","duration_ms":420})
    async def _run_voice(self)->None:
        settings=get_settings(); logger.info("[voice] start stt=%s tts=%s wake=%s timeout=%s",settings.stt_enabled,settings.tts_enabled,settings.wake_word_enabled,settings.interaction_timeout_seconds)
        if not (settings.stt_enabled and settings.tts_enabled): await self.push({"type":"error","message":"voz desativada: habilite stt_enabled e tts_enabled"}); return
        self._interaction=InteractionManager(enabled=settings.wake_word_enabled,wake_words=settings.wake_words,timeout_seconds=settings.interaction_timeout_seconds,end_words=settings.interaction_end_words)
        await self.push({"type":"ready","state":self.state,"voice":"on","wake_word_enabled":settings.wake_word_enabled})
        if not settings.wake_word_enabled:await self._set_interaction(True,"wake_word_disabled")
        else:await self._set_interaction(False,"waiting_for_wake_word")
        async with AsyncSessionLocal() as session:
            logger.info("[voice] building agent")
            agent=await build_agent(session,permission_prompt=self.permission_request,event_bus=self.event_bus,cancel_event=self.cancel_event);pipeline=VoicePipeline(event_bus=self.event_bus);self._pipeline=pipeline;carry:str|None=None
            logger.info("[voice] ready listening")
            while not self.cancel_event.is_set():
                if self._interaction and self._interaction.expired():self._interaction.expire();await self._set_interaction(False,"timeout")
                text=carry;carry=None
                if text is None:
                    self.event_bus.emit(EventType.assistant_listening); logger.info("[voice] capture_wait")
                    try:path=await asyncio.to_thread(audio_io.record_microphone_vad,max_wait=60.0,abort_event=threading.Event())
                    except audio_io.MicrophoneRecordingError as exc:logger.exception("[voice] microphone_error");await self.push({"type":"error","message":f"microfone indisponível: {exc}"});return
                    if path is None:logger.debug("[voice] capture_no_speech");continue
                    logger.info("[voice] capture_audio=%s",path)
                    result=await pipeline.process(path);text=(result.get("transcription") or "").strip();confidence=float(result.get("confidence") or 1.0);suspicious=bool(result.get("is_suspicious"));normalized=normalize(text).strip(" .,!?;:")
                    logger.info("[voice] stt_result raw=%r normalized=%r confidence=%.3f suspicious=%s",text,normalized,confidence,suspicious)
                    if suspicious or not normalized or normalized in {".","..","...","?","!"}:
                        logger.warning("[voice] transcription_rejected raw=%r",text);continue
                if not text:continue
                decision=self._interaction.decide(text) if self._interaction else None
                logger.info("[interaction] input=%r decision=%s",text,decision)
                if decision is None or not decision.accepted:
                    if decision and decision.ended:await self.push({"type":"caption","from":"user","text":text});await self._set_interaction(False,"end_word")
                    continue
                if decision.activated:await self._set_interaction(True,"wake_word")
                await self.push({"type":"caption","from":"user","text":text})
                if not decision.command:continue
                logger.info("[agent] command=%r",decision.command)
                try:answer=await agent.chat(decision.command,conversation_id=self.conversation_id)
                except asyncio.CancelledError:raise
                except Exception as exc:logger.exception("[avatar] turn_failed");await self.push({"type":"error","message":f"falha no turno: {exc}"});continue
                self.conversation_id=answer.get("conversation_id") or self.conversation_id
                response=clean_for_voice(answer.get("response") or "")
                logger.info("[agent] response len=%d text=%r",len(response),response)
                await self.push({"type":"caption","from":"alpha","text":response})
                if response:await self._speak_interruptible(pipeline,response,emotion=self._emotion(answer))
    @staticmethod
    def _emotion(answer:dict[str,Any])->EmotionState|None:
        payload=answer.get("emotion");return EmotionState.from_dict(payload) if isinstance(payload,dict) else None
    async def _speak_interruptible(self,pipeline:VoicePipeline,text:str,emotion:EmotionState|None)->None:
        logger.info("[voice] tts_prepare len=%d",len(text or "")); result=await pipeline.speak_expressive(text,emotion=emotion)
        if result.get("status")!="ok":logger.warning("[voice] tts_unavailable detail=%s",result.get("detail"));await self.push({"type":"error","message":str(result.get("detail") or "tts indisponível")});return
        audio_path=Path(result["audio_path"]); logger.info("[voice] playback_prepare path=%s",audio_path)
        try:player,frame_rate,n_frames=await asyncio.to_thread(audio_io.play_wav_async,audio_path)
        except audio_io.AudioPlaybackError as exc:logger.exception("[voice] playback_error");await self.push({"type":"error","message":f"áudio indisponível: {exc}"});return
        duration=n_frames/frame_rate if frame_rate else 0.0; logger.info("[voice] playback_running duration=%.2fs rate=%d frames=%d player=%s",duration,frame_rate,n_frames,player)
        await self.push({"type":"avatar_show","animation":"speak","duration_ms":max(1,int(duration*1000))})
        await self.push({"type":"state","state":"speaking","animation":"speak","expression":"speaking","emotion":None,"idle_after_ms":0})
        energy_task=asyncio.create_task(self._emit_speech_energy(audio_path))
        try: await asyncio.sleep(duration + 0.35)
        finally:
            energy_task.cancel(); await asyncio.to_thread(audio_io.stop_wav_async,player); logger.info("[voice] playback_end path=%s",audio_path)
            if not self.cancel_event.is_set():
                next_state="listening" if self._interaction is not None and self._interaction.active else "idle"
                await self.push({"type":"state","state":next_state,"animation":"idle","expression":"neutral","emotion":None,"idle_after_ms":0})
    async def _emit_speech_energy(self,audio_path:Path)->None:
        try:
            with wave.open(str(audio_path),"rb") as wav:
                rate=wav.getframerate();width=wav.getsampwidth();channels=wav.getnchannels();chunk=max(1,int(rate*0.04))
                if width not in (1,2,4):return
                fmt={1:"b",2:"h",4:"i"}[width]
                while not self.cancel_event.is_set():
                    raw=wav.readframes(chunk)
                    if not raw:break
                    sample_count=len(raw)//width;samples=struct.unpack("<"+fmt*sample_count,raw)
                    if channels>1:samples=samples[::channels]
                    abs_values=[abs(x) for x in samples];peak=max(abs_values,default=0);rms=(sum(x*x for x in samples)/len(samples))**0.5 if samples else 0.0;max_sample=float((1<<(8*width-1))-1);level=min(1.0,rms/max_sample*2.2);peak_level=min(1.0,peak/max_sample)
                    self._out.put_nowait({"type":"speech_energy","level":level,"peak":peak_level});await asyncio.sleep(min(0.04,max(0.01,chunk/rate)))
        except Exception:logger.debug("[avatar] speech energy indisponível",exc_info=True)
        finally:
            try:self._out.put_nowait({"type":"speech_energy","level":0.0,"peak":0.0})
            except Exception:pass


@router.websocket("/ws")
async def avatar_ws(websocket:WebSocket)->None:
    await websocket.accept();logger.info("[avatar] websocket_connected");session=AvatarSession(websocket);pump=asyncio.create_task(session.pump());receive=asyncio.create_task(session.receive_loop())
    try:await asyncio.wait({receive,pump},return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect,RuntimeError):pass
    finally:
        session.cancel_event.set(); logger.info("[avatar] websocket_closing")
        if session._voice_task is not None:session._voice_task.cancel()
        confirmation_task=session._confirmation_voice_task
        if confirmation_task is not None:confirmation_task.cancel()
        for task in (receive,pump):task.cancel()
        await asyncio.gather(receive,pump,return_exceptions=True)
        if session._voice_task is not None:await asyncio.gather(session._voice_task,return_exceptions=True)
        if confirmation_task is not None:await asyncio.gather(confirmation_task,return_exceptions=True)
        logger.info("[avatar] websocket_closed")


@router.get("/health")
async def avatar_health()->dict[str,str]:return {"status":"ok","service":"avatar"}

@router.get("/",include_in_schema=False)
async def avatar_index()->FileResponse:return FileResponse(UI_DIR/"index.html")

@router.get("/ui/{file_path}",include_in_schema=False)
async def avatar_asset(file_path:str)->FileResponse: