from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent.agent import AgentCore
from app.cli.commands import SlashContext, VerbosityHolder, run_slash
from app.cli.renderer import TerminalRenderer
from app.cli.themes import Verbosity
from app.core.config import get_settings
from app.core.events import EventBus, EventType
from app.core.logging import configure_logging
from app.db.models import Conversation, ManagedPathRecord
from app.db.session import AsyncSessionLocal, initialize_database
from app.memory.embeddings import LocalEmbeddingProvider
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.perception.stt import FasterWhisperSTT
from app.runtime import build_agent
from app.skills.files.service import FileManager
from app.speech import audio_io
from app.speech.cleaning import clean_markdown_artifacts
from app.speech.pipeline import VoicePipeline
from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository

EXIT_COMMANDS = {"/sair", "/quit", "/exit", "/q"}
EXIT_WORDS = {"sair", "encerrar", "parar", "fechar"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha",
        description="ALPHA - agente pessoal de IA local-first via CLI",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="saída em JSON")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
        help="saída em JSON",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMANDO")

    chat = subparsers.add_parser(
        "chat",
        parents=[common],
        help="conversar com o ALPHA (interativo se sem mensagem)",
    )
    chat.add_argument(
        "message",
        nargs="?",
        help="mensagem única; sem mensagem abre conversa interativa",
    )
    chat.add_argument("--conversation-id", default=None, help="identificador de conversa existente")
    chat.add_argument(
        "--voice",
        dest="voice_mode",
        action="store_true",
        default=None,
        help="modo voz contínuo: ouve, transcreve e responde falando (estilo Alexa/assistente)",
    )
    chat.add_argument(
        "--no-voice",
        dest="voice_mode",
        action="store_false",
        help="desativa âudio e mantém conversa por texto",
    )
    chat.add_argument(
        "--wake",
        dest="wake_mode",
        action="store_true",
        default=None,
        help="modo viva-voz: ouve em silêncio e só te atende quando você diz a wake word "
        "(configurável; padrão: 'alpha')",
    )

    subparsers.add_parser(
        "health",
        parents=[common],
        help="status dos serviços (banco, Ollama, voz, web)",
    )

    subparsers.add_parser("settings", parents=[common], help="mostra configurações atuais do ALPHA")

    conversations = subparsers.add_parser(
        "conversations",
        parents=[common],
        help="gerencia conversas",
    )
    conv_sub = conversations.add_subparsers(dest="conv_cmd", metavar="SUBCOMANDO")
    conv_sub.add_parser("list", parents=[common], help="lista conversas")
    conv_create = conv_sub.add_parser("create", parents=[common], help="cria uma conversa")
    conv_create.add_argument("--title", default="Nova conversa", help="título da conversa")

    memories = subparsers.add_parser(
        "memories",
        parents=[common],
        help="gerencia memórias do agente",
    )
    mem_sub = memories.add_subparsers(dest="mem_cmd", metavar="SUBCOMANDO")
    mem_sub.add_parser("list", parents=[common], help="lista memórias")
    mem_add = mem_sub.add_parser("add", parents=[common], help="adiciona uma memória")
    mem_add.add_argument("content", help="conteúdo da memória")
    mem_add.add_argument(
        "--importance",
        type=float,
        default=1.0,
        help="importância em [0, 1] (padrão 1.0)",
    )
    mem_add.add_argument("--memory-type", default="semantic")
    mem_add.add_argument("--source", default="manual")
    mem_del = mem_sub.add_parser("delete", parents=[common], help="remove uma memória")
    mem_del.add_argument("memory_id", help="identificador da memória")

    profile = subparsers.add_parser(
        "profile",
        parents=[common],
        help="gerencia o perfil estável do usuário (identidade e ambiente)",
    )
    profile_sub = profile.add_subparsers(dest="profile_cmd", metavar="SUBCOMANDO")
    profile_sub.add_parser("show", parents=[common], help="mostra o perfil salvo")
    profile_add = profile_sub.add_parser("add", parents=[common], help="adiciona um fato ao perfil")
    profile_add.add_argument(
        "content",
        help="fato sobre o usuário/ambiente (ex.: 'Meu nome é Gustavo e uso Windows 11')",
    )
    profile_del = profile_sub.add_parser(
        "delete", parents=[common], help="remove um item do perfil"
    )
    profile_del.add_argument("profile_id", help="identificador do item")

    documents = subparsers.add_parser("documents", parents=[common], help="indexação de documentos")
    doc_sub = documents.add_subparsers(dest="doc_cmd", metavar="SUBCOMANDO")
    doc_sub.add_parser("index", parents=[common], help="indexa os diretórios permitidos")

    tasks = subparsers.add_parser("tasks", parents=[common], help="gerencia tarefas do executor")
    task_sub = tasks.add_subparsers(dest="task_cmd", metavar="SUBCOMANDO")
    task_list = task_sub.add_parser("list", parents=[common], help="lista tarefas")
    task_list.add_argument("--limit", type=int, default=50)
    task_create = task_sub.add_parser("create", parents=[common], help="cria uma tarefa")
    task_create.add_argument("--title", required=True)
    task_create.add_argument(
        "--action",
        required=True,
        help=(
            "create_file, create_directory, create_method, persist_repo_changes, "
            "open_browser, search_web, list_directory"
        ),
    )
    task_create.add_argument("--instruction", default="")
    task_create.add_argument("--params", default=None, help="JSON com parâmetros da ação")
    task_exec = task_sub.add_parser(
        "execute",
        parents=[common],
        help="executa uma tarefa",
    )
    task_exec.add_argument("task_id")
    task_sub.add_parser(
        "paths",
        parents=[common],
        help="lista diretórios/arquivos permitidos",
    )
    task_reg = task_sub.add_parser(
        "register-path",
        parents=[common],
        help="registra um diretório/arquivo permitido",
    )
    task_reg.add_argument("path", help="caminho a liberar")
    task_reg.add_argument("--entry-type", default="directory")
    task_reg.add_argument("--source", default="task_executor")
    task_reg.add_argument(
        "--force",
        action="store_true",
        help="registra mesmo sem diretório permitido prévio",
    )

    voice = subparsers.add_parser("voice", parents=[common], help="transcrição de áudio")
    voice_sub = voice.add_subparsers(dest="voice_cmd", metavar="SUBCOMANDO")
    voice_trans = voice_sub.add_parser(
        "transcribe",
        parents=[common],
        help="transcreve um arquivo de áudio",
    )
    voice_trans.add_argument("audio", help="caminho do arquivo de áudio")

    listen = subparsers.add_parser(
        "listen",
        parents=[common],
        help="grava o microfone e transcreve (STT direto na CLI)",
    )
    listen.add_argument(
        "--duration",
        type=float,
        default=None,
        help="grava por N segundos; sem isso, para ao apertar Enter",
    )
    listen.add_argument(
        "--device",
        default=None,
        help="nome/índice do dispositivo de entrada (padrão: dispositivo do sistema)",
    )

    speak = subparsers.add_parser("speak", parents=[common], help="sintetiza texto em voz (TTS)")
    speak.add_argument("text", help="texto a falar")
    speak.add_argument("--output", default=None, help="caminho do arquivo WAV de saída")
    speak.add_argument(
        "--no-play",
        dest="play",
        action="store_false",
        default=True,
        help="não reproduz o áudio automaticamente",
    )

    db = subparsers.add_parser("db", parents=[common], help="utilitários de banco de dados")
    db_sub = db.add_subparsers(dest="db_cmd", metavar="SUBCOMANDO")
    db_sub.add_parser("init", parents=[common], help="cria as tabelas do banco")

    reminders = subparsers.add_parser(
        "reminders",
        parents=[common],
        help="gerencia lembretes agendados",
    )
    rem_sub = reminders.add_subparsers(dest="rem_cmd", metavar="SUBCOMANDO")
    rem_sub.add_parser("list", parents=[common], help="lista lembretes")
    rem_create = rem_sub.add_parser("create", parents=[common], help="cria um lembrete")
    rem_create.add_argument("--title", required=True)
    rem_create.add_argument(
        "--schedule",
        required=True,
        help="'17:30', 'todo dia 09:00', '2026-09-07 09:00', 'em 30 minutos' ou cron de 5 campos",
    )
    rem_create.add_argument(
        "--action",
        default="notify",
        help="notify, open_app, open_url, open_file ou task_execute",
    )
    rem_create.add_argument("--params", default=None, help="JSON com parâmetros da ação")
    rem_del = rem_sub.add_parser("delete", parents=[common], help="remove um lembrete")
    rem_del.add_argument("reminder_id", help="identificador do lembrete")

    calendar = subparsers.add_parser(
        "calendar",
        parents=[common],
        help="gerencia eventos da agenda",
    )
    cal_sub = calendar.add_subparsers(dest="cal_cmd", metavar="SUBCOMANDO")
    cal_sub.add_parser("list", parents=[common], help="lista os próximos eventos")
    cal_create = cal_sub.add_parser("create", parents=[common], help="cria um evento")
    cal_create.add_argument("--title", required=True)
    cal_create.add_argument(
        "--start",
        required=True,
        help="'17:30', 'amanhã 10:00', 'segunda 09:00', '2026-09-07 09:00' ou 'em 2 horas'",
    )
    cal_create.add_argument(
        "--end", default=None, help="duração ('1 hora') ou fim ('18:00') — padrão: 1 hora"
    )
    cal_create.add_argument("--description", default=None)
    cal_create.add_argument("--location", default=None)
    cal_del = cal_sub.add_parser("delete", parents=[common], help="remove um evento")
    cal_del.add_argument("event_id", help="identificador do evento")

    return parser


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _emit(data: Any, as_json: bool) -> None:
    if isinstance(data, str):
        print(data)
        return
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    _render(data)


def _summarize_list(items: list[Any]) -> str:
    preview = ", ".join(str(item) for item in items[:3])
    return f"[{preview}, ...] ({len(items)} itens)"


def _render(data: Any, indent: int = 0) -> None:
    spaces = " " * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                print(f"{spaces}{key}:")
                _render(value, indent + 2)
            elif isinstance(value, list):
                print(f"{spaces}{key}: {_summarize_list(value)}")
            else:
                print(f"{spaces}{key}: {value}")
    elif isinstance(data, list):
        if not data:
            print(f"{spaces}(vazio)")
            return
        if len(data) > 12:
            print(f"{spaces}{_summarize_list(data)}")
            return
        for item in data:
            _render(item, indent)
            print()
    else:
        print(f"{spaces}{data}")


def _print_agent_tools(agent: AgentCore) -> None:

    for event in agent.events:
        if event.type == EventType.tool_started:
            tool = event.payload.get("tool", "")
            args = event.payload.get("arguments")
            detail = ""
            if isinstance(args, dict) and args:
                detail = " -> " + json.dumps(args, ensure_ascii=False, default=str)
            print(f"[ferramenta] {tool} ...{detail}")
        elif event.type == EventType.tool_finished and not event.payload.get("success", True):
            print(f"[erro na ferramenta] {event.payload.get('tool', '')}")


def _conversation_dict(conversation: object) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _task_dict(task: object) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "instruction": task.instruction,
        "action": task.action,
        "status": task.status,
        "params": task.params,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


async def _make_task_service(session) -> tuple[TaskExecutorService, ManagedPathRepository]:
    path_repo = ManagedPathRepository(session)
    file_manager = FileManager()
    records = await path_repo.list()
    file_manager.allowed_directories = [
        Path(record.path).expanduser().resolve()
        for record in records
        if getattr(record, "is_allowed", 1)
    ]
    return TaskExecutorService(TaskRepository(session), path_repo, file_manager), path_repo


def _voice_mode(args: argparse.Namespace) -> bool:
    mode = getattr(args, "voice_mode", None)
    if mode is not None:
        return mode
    settings = get_settings()
    return settings.stt_enabled and settings.tts_enabled


async def _speak_reply(pipeline: VoicePipeline, text: str) -> None:
    result = await pipeline.speak(clean_markdown_artifacts(text))
    if result.get("status") == "ok":
        await asyncio.to_thread(audio_io.play_wav, Path(result["audio_path"]))
    else:
        print(f"[tts indisponível] {result.get('detail')}", file=sys.stderr)


async def _capture_transcription(pipeline: VoicePipeline, as_json: bool = False) -> str | None:
    try:
        print("▶ Ouvindo... fale agora.", flush=True)
        path = await asyncio.to_thread(audio_io.record_microphone_vad)
    except audio_io.MicrophoneRecordingError as exc:
        print(f"[erro] {exc!r}", file=sys.stderr)
        return None
    if path is None:
        if not as_json:
            print("[nenhum áudio detectado; continuo ouvindo...]")
        return None
    result = await pipeline.process(path)
    text = result.get("transcription", "").strip()
    if not text:
        print("[não ouvi bem; tente de novo]", file=sys.stderr)
        return None
    print(f"Você (voz): {text}")
    return text


def _confirm_permission(request: str) -> bool:
    print(f"\n[permissão] O ALPHA deseja acessar: {request}")
    while True:
        answer = input("Permitir acesso? (s/n): ").strip().lower()
        if answer in ("s", "sim", "y", "yes", "1"):
            print("[permitido]")
            return True
        if answer in ("n", "não", "nao", "no", "0"):
            print("[negado]")
            return False
        print("Responda 's' (sim) ou 'n' (não).")


async def permission_prompt(request: str) -> bool:
    try:
        return await asyncio.to_thread(_confirm_permission, request)
    except EOFError:
        return False


async def _chat_once(
    message: str,
    conversation_id: str | None,
    as_json: bool,
    voice_enabled: bool,
) -> int:
    async with AsyncSessionLocal() as session:
        agent = await build_agent(session, permission_prompt=permission_prompt)
        try:
            result = await agent.chat(message, conversation_id=conversation_id)
        except Exception as exc:
            print(f"[erro] {exc!r}", file=sys.stderr)
            return 1
        _print_agent_tools(agent)
        if as_json:
            _emit(result, True)
        else:
            response_text = clean_markdown_artifacts(result["response"])
            print(f"ALPHA: {response_text}")
            if result.get("memory_created"):
                print("[memória criada]")
            if voice_enabled:
                await _speak_reply(VoicePipeline(), response_text)
    return 0


def _is_exit(text: str) -> bool:
    cleaned = text.strip(".,!?;: ") or text
    return cleaned in EXIT_COMMANDS or cleaned.lower() in EXIT_WORDS


async def _capture_speech_onset(
    pipeline: VoicePipeline,
    speech_started: asyncio.Event,
    abort_event: threading.Event,
) -> str | None:
    """Grava durante a reprodução sinalizando o início da fala e transcreve o que foi dito."""
    loop = asyncio.get_running_loop()

    def _signal_onset() -> None:
        loop.call_soon_threadsafe(speech_started.set)

    path = await asyncio.to_thread(
        audio_io.record_microphone_vad, on_speech_start=_signal_onset, abort_event=abort_event
    )
    if path is None:
        return None
    result = await pipeline.process(path)
    text = result.get("transcription", "").strip()
    if not text:
        return None
    print(f"Você (voz): {text}")
    return text


async def _speak_interruptible(pipeline: VoicePipeline, text: str) -> str | None:
    """Fala a resposta; interrompe a reprodução assim que o usuário começa a falar.

    O gravador é iniciado durante a reprodução, então seu limiar de ruído é
    calibrado no eco do próprio áudio — apenas a voz do usuário (mais alta no
    microfone) dispara a interrupção.
    """
    result = await pipeline.speak(clean_markdown_artifacts(text))
    if result.get("status") != "ok":
        print(f"[tts indisponível] {result.get('detail')}", file=sys.stderr)
        return None
    audio_path = Path(result["audio_path"])
    try:
        player, frame_rate, n_frames = await asyncio.to_thread(audio_io.play_wav_async, audio_path)
    except audio_io.AudioPlaybackError as exc:
        print(f"[erro de áudio] {exc}", file=sys.stderr)
        return None

    speech_started = asyncio.Event()
    abort_event = threading.Event()
    recorder = asyncio.create_task(_capture_speech_onset(pipeline, speech_started, abort_event))
    duration = n_frames / frame_rate if frame_rate else 0.0
    playback_done = asyncio.create_task(asyncio.sleep(duration + 0.25))
    started_wait = asyncio.create_task(speech_started.wait())

    done, _ = await asyncio.wait({playback_done, started_wait}, return_when=asyncio.FIRST_COMPLETED)
    if speech_started.is_set():
        await asyncio.to_thread(audio_io.stop_wav_async, player)
        playback_done.cancel()
        print("[interrompido]")
        try:
            return await recorder
        except Exception:
            return None

    started_wait.cancel()
    abort_event.set()
    try:
        await recorder
    except Exception:
        pass
    await asyncio.to_thread(audio_io.stop_wav_async, player)
    return None


async def _chat_voice_interactive(
    agent: AgentCore,
    conversation_id: str | None,
    as_json: bool,
) -> str | None:
    current_id = conversation_id
    pipeline = VoicePipeline()
    carry: str | None = None

    async def next_utterance() -> str | None:
        nonlocal carry
        text = carry
        carry = None
        if text is not None:
            return text
        return await _capture_transcription(pipeline, as_json)

    while True:
        text = await next_utterance()
        if text is None:
            continue
        if _is_exit(text):
            print("Até logo!")
            return current_id
        try:
            result = await agent.chat(text, conversation_id=current_id)
        except Exception as exc:
            print(f"[erro] {exc!r}", file=sys.stderr)
            continue

        current_id = result.get("conversation_id") or current_id
        _print_agent_tools(agent)
        print(f"ALPHA: {clean_markdown_artifacts(result['response'])}")
        if result.get("memory_created") and not as_json:
            print("[memória criada]")
        if result["response"]:
            barge = await _speak_interruptible(pipeline, result["response"])
            if barge:
                carry = barge
        else:
            carry = None


def _wake_words() -> list[str]:
    from app.perception.wakeword import _tokenize_words

    settings = get_settings()
    return _tokenize_words(settings.wake_words) or ["alpha"]


async def _capture_wake_phrase(pipeline: VoicePipeline, as_json: bool = False) -> str | None:
    """Escuta em silêncio por uma frase e devolve sua transcrição (ou ``None``)."""
    try:
        path = await asyncio.to_thread(
            audio_io.record_microphone_vad,
            max_wait=1800.0,
        )
    except audio_io.MicrophoneRecordingError as exc:
        print(f"[erro] {exc!r}", file=sys.stderr)
        return None
    if path is None:
        return None
    result = await pipeline.process(path)
    text = result.get("transcription", "").strip()
    if not text:
        print("[não ouvi bem; sigo escutando...]", file=sys.stderr)
        return None
    return text


async def _chat_wake_interactive(
    agent: AgentCore,
    conversation_id: str | None,
    as_json: bool,
) -> str | None:
    """Viva-voz: fica em silêncio e só atende quando a wake word é dita."""
    from app.perception.wakeword import strip_wake_word

    pipeline = VoicePipeline()
    current_id = conversation_id
    words = _wake_words()
    print("[viva-voz] escutando em silêncio...", flush=True)
    while True:
        spoken = await _capture_wake_phrase(pipeline, as_json)
        if not spoken:
            continue
        found, remainder = strip_wake_word(spoken, words)
        if not found:
            continue
        print(f"[wake word detectada] {spoken!r}")
        if remainder:
            text = remainder
        else:
            print("▶ Diga seu comando...", flush=True)
            text = await _capture_transcription(pipeline, as_json)
        if not text:
            continue
        if _is_exit(text):
            print("Até logo!")
            return current_id
        try:
            result = await agent.chat(text, conversation_id=current_id)
        except Exception as exc:
            print(f"[erro] {exc!r}", file=sys.stderr)
            continue
        current_id = result.get("conversation_id") or current_id
        _print_agent_tools(agent)
        print(f"ALPHA: {clean_markdown_artifacts(result['response'])}")
        if result.get("memory_created") and not as_json:
            print("[memória criada]")
        if result["response"]:
            barge = await _speak_interruptible(pipeline, result["response"])
            if barge:
                carry = barge
                if not _is_exit(carry):
                    # O usuário interrompeu falando um novo comando: atende direto.
                    try:
                        result2 = await agent.chat(carry, conversation_id=current_id)
                    except Exception as exc:
                        print(f"[erro] {exc!r}", file=sys.stderr)
                        continue
                    current_id = result2.get("conversation_id") or current_id
                    _print_agent_tools(agent)
                    print(f"ALPHA: {clean_markdown_artifacts(result2['response'])}")
                    if result2["response"]:
                        await _speak_interruptible(pipeline, result2["response"])


async def _chat_interactive(
    conversation_id: str | None,
    as_json: bool,
    voice_enabled: bool,
    wake_enabled: bool = False,
) -> int:
    scheduler = await _start_scheduler_or_none()
    try:
        return await _chat_interactive_loop(conversation_id, as_json, voice_enabled, wake_enabled)
    finally:
        if scheduler is not None:
            await scheduler.stop()


async def _start_scheduler_or_none():
    from app.reminders.runner import SchedulerRunner

    settings = get_settings()
    if not settings.scheduler_enabled:
        return None
    runner = SchedulerRunner(
        AsyncSessionLocal,
        interval_seconds=settings.scheduler_interval_seconds,
        on_notify=lambda message: print(f"\n[lembrete] {message}\n", flush=True),
    )
    await runner.start()
    print(f"[agendador ativo] verificação a cada {settings.scheduler_interval_seconds:.0f}s")
    return runner


async def _chat_interactive_loop(
    conversation_id: str | None,
    as_json: bool,
    voice_enabled: bool,
    wake_enabled: bool = False,
) -> int:
    async with AsyncSessionLocal() as session:
        agent = await build_agent(session, permission_prompt=permission_prompt)
        if voice_enabled:
            if wake_enabled:
                print(
                    f"ALPHA {get_settings().app_name} - modo viva-voz (wake word). "
                    f'Diga "{" / ".join(_wake_words())}" para me chamar; '
                    "diga 'sair' ou use Ctrl+C para encerrar."
                )
                await _chat_wake_interactive(agent, conversation_id, as_json)
            else:
                print(
                    f"ALPHA {get_settings().app_name} - modo de voz ativo. "
                    "Fale para conversar; diga 'sair' ou use Ctrl+C para encerrar."
                )
                await _chat_voice_interactive(agent, conversation_id, as_json)
            return 0

        current_id = conversation_id
        print(f"ALPHA {get_settings().app_name} - conversa interativa. Comandos: /sair, /q")
        while True:
            try:
                raw = input("Você: ")
            except EOFError:
                print()
                break
            message = raw.strip()
            if message in EXIT_COMMANDS:
                break
            if not message:
                continue
            try:
                result = await agent.chat(message, conversation_id=current_id)
            except Exception as exc:
                print(f"[erro] {exc!r}", file=sys.stderr)
                continue
            current_id = result.get("conversation_id") or current_id
            _print_agent_tools(agent)
            print(f"ALPHA: {result['response']}")
            if result.get("memory_created") and not as_json:
                print("[memória criada]")
    return 0


async def _chat_terminal(
    conversation_id: str | None,
    as_json: bool,
    verbosity: Verbosity = Verbosity.normal,
) -> int:
    """Loop interativo principal (terminal-first) com renderer Rich e slash commands."""
    from app.cli.commands import EXIT_INPUTS

    scheduler = await _start_scheduler_or_none()
    event_bus = EventBus()
    cancel_event = asyncio.Event()
    verbosity_holder = VerbosityHolder(verbosity)
    renderer = TerminalRenderer(verbosity=verbosity)
    current_id = conversation_id

    def _resolve_agent() -> AgentCore | None:
        return None

    ctx = SlashContext(
        renderer=renderer,
        settings=get_settings(),
        verbosity=verbosity_holder,
        cancel_event=cancel_event,
        session_factory=AsyncSessionLocal,
        get_agent=_resolve_agent,
    )

    try:
        renderer.banner()
        renderer.rule("conversa")
        while True:
            try:
                raw = renderer.prompt_user()
            except (EOFError, KeyboardInterrupt):
                renderer.console.print()
                break
            message = raw.strip()
            if not message:
                continue
            if message in EXIT_INPUTS:
                break
            if message.startswith("/"):
                cancel_event.clear()
                result = await run_slash(message, ctx)
                if result.exit:
                    break
                if not result.handled:
                    renderer.error(result.message or f"Comando desconhecido: {message}")
                continue

            cancel_event.clear()
            async with AsyncSessionLocal() as session:
                agent = await build_agent(
                    session,
                    permission_prompt=renderer.confirm_async,
                    event_bus=event_bus,
                    cancel_event=cancel_event,
                )
                try:
                    async for event in agent.chat_stream(message, conversation_id=current_id):
                        renderer.render_event(event)
                except asyncio.CancelledError:
                    renderer.warn("Cancelado pelo usuário.")
                    cancel_event.clear()
                except Exception as exc:
                    renderer.error(f"{exc!r}")
                current_id = current_id or None
    finally:
        if scheduler is not None:
            await scheduler.stop()
    renderer.rule("Até logo!")
    return 0


async def _cmd_chat(args: argparse.Namespace) -> int:
    message = getattr(args, "message", None)
    conversation_id = getattr(args, "conversation_id", None)
    as_json = getattr(args, "as_json", False)
    voice_enabled = _voice_mode(args)
    wake_mode = getattr(args, "wake_mode", None)
    wake_enabled = wake_mode if wake_mode is not None else get_settings().wake_word_enabled
    if message is None:
        if voice_enabled:
            return await _chat_interactive(conversation_id, as_json, voice_enabled, wake_enabled)
        return await _chat_terminal(conversation_id, as_json)
    return await _chat_once(message, conversation_id, as_json, voice_enabled)


async def _cmd_health(args: argparse.Namespace) -> int:
    from app.services.health import collect_health

    _emit(await collect_health(), args.as_json)
    return 0


async def _cmd_settings(args: argparse.Namespace) -> int:
    from app.llm.router import LLMRouter

    config = get_settings()
    async with AsyncSessionLocal() as session:
        records = await ManagedPathRepository(session).list()
        allowed_directories = [
            record.path for record in records if getattr(record, "is_allowed", 1)
        ]
    if not allowed_directories:
        allowed_directories = [str(path) for path in config.allowed_directories]
    state = LLMRouter().describe_current()
    _emit(
        {
            "app_name": config.app_name,
            "app_env": config.app_env,
            "llm_mode": config.llm_mode,
            "provider_name": state.get("provider_name"),
            "model": state.get("model"),
            "base_url": state.get("base_url"),
            "allow_web": config.allow_web,
            "stt_enabled": config.stt_enabled,
            "tts_enabled": config.tts_enabled,
            "memory_min_importance": config.memory_min_importance,
            "rag_top_k": config.rag_top_k,
            "agent_max_tool_iterations": config.agent_max_tool_iterations,
            "allowed_directories": allowed_directories,
            "allow_cloud_llm": config.allow_cloud_llm,
        },
        args.as_json,
    )
    return 0


async def _cmd_conversations(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        if getattr(args, "conv_cmd", None) == "create":
            conversation = Conversation(title=args.title)
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
            _emit(_conversation_dict(conversation), args.as_json)
            return 0

        from sqlalchemy import select

        result = await session.execute(
            select(Conversation).order_by(Conversation.created_at.desc())
        )
        conversations = [_conversation_dict(item) for item in result.scalars().all()]
    _emit(conversations, args.as_json)
    return 0


async def _cmd_profile(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        service = MemoryService(MemoryRepository(session), LocalEmbeddingProvider())
        command = getattr(args, "profile_cmd", None) or "show"
        if command == "add":
            item = await service.save_profile(args.content)
            if item is None:
                print("Perfil não salvo.", file=sys.stderr)
                return 1
            _emit(item.model_dump(), args.as_json)
            return 0
        if command == "delete":
            await service.delete_memory(args.profile_id)
            print(f"Item do perfil removido: {args.profile_id}")
            return 0
        items = [item.model_dump() for item in await service.load_profile()]
    _emit(items, args.as_json)
    return 0


async def _cmd_memories(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        service = MemoryService(MemoryRepository(session), LocalEmbeddingProvider())
        command = getattr(args, "mem_cmd", None) or "list"
        if command == "add":
            memory = await service.save_memory(
                content=args.content,
                memory_type=args.memory_type,
                source=args.source,
                importance=args.importance,
            )
            if memory is None:
                print("Memória não salva (abaixo do limiar de importância).", file=sys.stderr)
                return 1
            _emit(memory.model_dump(), args.as_json)
            return 0
        if command == "delete":
            await service.delete_memory(args.memory_id)
            print(f"Memória removida: {args.memory_id}")
            return 0
        memories = [memory.model_dump() for memory in await service.list_memories()]
    _emit(memories, args.as_json)
    return 0


async def _cmd_documents(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        from app.documents.indexer import DocumentIndexer, DocumentRepository
        from app.memory.embeddings import LocalEmbeddingProvider

        records = await ManagedPathRepository(session).list()
        file_manager = FileManager()
        file_manager.allowed_directories = [
            Path(record.path).expanduser().resolve()
            for record in records
            if getattr(record, "is_allowed", 1)
        ]
        indexer = DocumentIndexer(
            file_manager,
            DocumentRepository(session),
            LocalEmbeddingProvider(),
        )
        result = await indexer.index_allowed_directories()
    _emit(result, args.as_json)
    return 0


async def _cmd_tasks(args: argparse.Namespace) -> int:
    command = getattr(args, "task_cmd", None) or "list"
    async with AsyncSessionLocal() as session:
        service, _ = await _make_task_service(session)
        if command == "create":
            params = json.loads(args.params) if args.params else {}
            task = await service.create_task(
                title=args.title,
                instruction=args.instruction,
                action=args.action,
                params=params,
            )
            _emit({"task": _task_dict(task)}, args.as_json)
            return 0
        if command == "execute":
            result = await service.execute_task(args.task_id)
            if not result.success:
                print(f"[erro] {result.error}", file=sys.stderr)
                return 1
            _emit(
                {
                    "success": result.success,
                    "task_id": result.task_id,
                    "result": result.result,
                    "error": result.error,
                },
                args.as_json,
            )
            return 0
        if command == "register-path":
            record = await _register_path(session, service, args)
            _emit(
                {
                    "id": record.id,
                    "path": record.path,
                    "entry_type": record.entry_type,
                    "is_allowed": bool(record.is_allowed),
                },
                args.as_json,
            )
            return 0
        if command == "paths":
            _emit(await service.list_allowed_paths(), args.as_json)
            return 0
        tasks = await service.list_tasks(limit=args.limit)
    _emit([_task_dict(task) for task in tasks], args.as_json)
    return 0


async def _register_path(session, service: TaskExecutorService, args: argparse.Namespace):
    if args.force:
        normalized = Path(args.path).expanduser().resolve()
        record = ManagedPathRecord(
            path=str(normalized),
            entry_type=args.entry_type,
            is_allowed=1,
            source=args.source,
            metadata_={"registered_at": datetime.now(UTC).isoformat()},
            last_seen_at=datetime.now(UTC),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record
    return await service.register_allowed_path(
        args.path, entry_type=args.entry_type, source=args.source
    )


async def _cmd_voice(args: argparse.Namespace) -> int:
    if getattr(args, "voice_cmd", None) != "transcribe" or not hasattr(args, "audio"):
        print("uso: alpha voice transcribe <caminho-do-audio>", file=sys.stderr)
        return 1
    audio = Path(args.audio)
    if not audio.exists():
        print(f"Arquivo não encontrado: {audio}", file=sys.stderr)
        return 1
    pipeline = VoicePipeline()
    result = await pipeline.process(audio)
    if args.as_json:
        _emit(result, True)
    else:
        print(result.get("transcription", ""))
    return 0


async def _cmd_listen(args: argparse.Namespace) -> int:
    try:
        path = await asyncio.to_thread(
            audio_io.record_microphone,
            duration=getattr(args, "duration", None),
            device=getattr(args, "device", None),
        )
    except audio_io.MicrophoneRecordingError as exc:
        print(f"[erro] {exc!r}", file=sys.stderr)
        return 1
    result = await FasterWhisperSTT().transcribe(path)
    if args.as_json:
        _emit(
            {
                "transcription": result.text,
                "language": result.language,
                "segments": result.segments,
            },
            True,
        )
    else:
        print(result.text)
    return 0


async def _cmd_speak(args: argparse.Namespace) -> int:
    pipeline = VoicePipeline()
    result = await pipeline.speak(args.text)
    if result.get("status") != "ok":
        _emit(result, args.as_json)
        return 1
    audio_path = Path(result["audio_path"])
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(audio_path, target)
        audio_path = target
    if args.play:
        try:
            await asyncio.to_thread(audio_io.play_wav, audio_path)
        except audio_io.AudioPlaybackError as exc:
            print(f"[erro] {exc!r}", file=sys.stderr)
    print(f"Áudio gerado em: {audio_path}")
    return 0


async def _cmd_db(args: argparse.Namespace) -> int:
    await initialize_database()
    print("Banco de dados inicializado.")
    return 0


def _reminder_dict(view: object) -> dict[str, Any]:
    return {
        "id": view.id,
        "title": view.title,
        "schedule_type": view.schedule_type,
        "schedule": view.schedule,
        "action": view.action,
        "params": view.params,
        "enabled": view.enabled,
        "last_run_at": view.last_run_at.isoformat() if view.last_run_at else None,
        "next_run_at": view.next_run_at.isoformat() if view.next_run_at else None,
        "error": view.error,
    }


async def _cmd_reminders(args: argparse.Namespace) -> int:
    from app.reminders.service import ReminderRepository, ReminderService

    command = getattr(args, "rem_cmd", None) or "list"
    async with AsyncSessionLocal() as session:
        service = ReminderService(ReminderRepository(session))
        if command == "create":
            params = json.loads(args.params) if args.params else {}
            view = await service.create_reminder(
                title=args.title,
                schedule_text=args.schedule,
                action=args.action,
                params=params,
            )
            _emit({"reminder": _reminder_dict(view)}, args.as_json)
            return 0
        if command == "delete":
            await service.delete_reminder(args.reminder_id)
            print(f"Lembrete removido: {args.reminder_id}")
            return 0
        reminders = await service.list_reminders()
    _emit([_reminder_dict(view) for view in reminders], args.as_json)
    return 0


def _event_dict(view: object) -> dict[str, Any]:
    return {
        "id": view.id,
        "title": view.title,
        "start_at": view.start_at.isoformat() if view.start_at else None,
        "end_at": view.end_at.isoformat() if view.end_at else None,
        "description": view.description,
        "location": view.location,
    }


async def _cmd_calendar(args: argparse.Namespace) -> int:
    from app.calendar.service import CalendarRepository, CalendarService

    command = getattr(args, "cal_cmd", None) or "list"
    async with AsyncSessionLocal() as session:
        service = CalendarService(CalendarRepository(session))
        if command == "create":
            view = await service.create_event(
                title=args.title,
                start_text=args.start,
                end_text=args.end,
                description=args.description,
                location=args.location,
            )
            _emit({"event": _event_dict(view)}, args.as_json)
            return 0
        if command == "delete":
            await service.delete_event(args.event_id)
            print(f"Evento removido: {args.event_id}")
            return 0
        views = await service.upcoming(limit=100)
    _emit([_event_dict(view) for view in views], args.as_json)
    return 0


async def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    command = getattr(args, "command", None)
    if command is None:
        await initialize_database()
        return await _cmd_chat(args)
    if command != "db":
        await initialize_database()
    if command == "chat":
        return await _cmd_chat(args)
    if command == "health":
        return await _cmd_health(args)
    if command == "settings":
        return await _cmd_settings(args)
    if command == "conversations":
        return await _cmd_conversations(args)
    if command == "memories":
        return await _cmd_memories(args)
    if command == "profile":
        return await _cmd_profile(args)
    if command == "documents":
        return await _cmd_documents(args)
    if command == "tasks":
        return await _cmd_tasks(args)
    if command == "reminders":
        return await _cmd_reminders(args)
    if command == "calendar":
        return await _cmd_calendar(args)
    if command == "voice":
        return await _cmd_voice(args)
    if command == "listen":
        return await _cmd_listen(args)
    if command == "speak":
        return await _cmd_speak(args)
    parser.print_help()
    return 1


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging()
    try:
        return asyncio.run(_dispatch(args, parser))
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
