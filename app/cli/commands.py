from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.cli.renderer import TerminalRenderer
from app.cli.themes import Verbosity
from app.core.config import Settings


@dataclass
class VerbosityHolder:
    current: Verbosity = Verbosity.normal

    def set(self, value: Verbosity) -> None:
        self.current = value


@dataclass
class SlashContext:
    renderer: TerminalRenderer
    settings: Settings
    verbosity: VerbosityHolder
    cancel_event: asyncio.Event
    session_factory: Callable[[], Any]
    get_agent: Callable[[], Any | None] = lambda: None
    conversation_id: str | None = None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SlashResult:
    handled: bool
    exit: bool = False
    message: str | None = None


class SlashCommandError(Exception):
    pass


_ALIASES: dict[str, str] = {
    "q": "exit",
    "quit": "exit",
    "sair": "exit",
    "stop": "cancel",
    "help": "help",
    "?" : "help",
}
NAMES = {
    "help",
    "status",
    "skills",
    "tools",
    "memory",
    "tasks",
    "task",
    "cancel",
    "clear",
    "model",
    "config",
    "permissions",
    "verbosity",
    "debug",
    "exit",
}

HELP_BY_CATEGORY: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Sessão",
        [
            ("/help [assunto]", "mostra esta ajuda"),
            ("/exit  (/q, /sair)", "encerra a sessão"),
            ("/clear", "limpa o terminal"),
            ("/verbosity [level]", "quiet | normal | verbose | debug"),
            ("/debug", "alterna para verbosity debug"),
        ],
    ),
    (
        "Agente",
        [
            ("/status", "estado geral: modelo, modo, tarefa, skills, tools"),
            ("/model [nome]", "mostra/altera o modelo do Ollama"),
            ("/config", "mostra as configurações atuais"),
            ("/permissions", "lista diretórios permitidos e nível de permissão"),
        ],
    ),
    (
        "Recursos",
        [
            ("/skills", "lista as skills disponíveis"),
            ("/tools", "lista as ferramentas registradas"),
            ("/memory", "memórias recentes"),
            ("/tasks", "tarefas recentes"),
            ("/task <id>", "detalhes de uma tarefa"),
        ],
    ),
    (
        "Controle",
        [
            ("/cancel  (/stop)", "cancela a execução em andamento"),
        ],
    ),
]


def _print_help(ctx: SlashContext, subject: str | None = None) -> None:
    renderer = ctx.renderer
    if subject:
        subject = subject.lstrip("/").lower()
        matches = [name for name in NAMES if name.startswith(subject)]
        if matches:
            for name in matches:
                renderer.info(f"/{name}")
            return
        renderer.warn(f"Comando desconhecido: /{subject}")
        return
    for category, rows in HELP_BY_CATEGORY:
        columns = max((len(cmd) for cmd, _ in rows), default=8) + 1
        lines = [f"  {cmd:<{columns}} {desc}" for cmd, desc in rows]
        renderer.rule(category)
        for line in lines:
            renderer.console.print(line)


def _cmd_status(ctx: SlashContext) -> None:
    from app.llm.router import LLMRouter

    settings = ctx.settings
    renderer = ctx.renderer
    state = LLMRouter().describe_current()
    agent = ctx.get_agent()
    rows = [
        ["modo LLM", settings.llm_mode],
        ["provedor", state.get("provider_name") or "-"],
        ["modelo", state.get("model") or "-"],
        ["verbosity", ctx.verbosity.current.value],
        ["web", "on" if settings.allow_web else "off"],
        [
            "voz",
            f"STT={'on' if settings.stt_enabled else 'off'} "
            f"TTS={'on' if settings.tts_enabled else 'off'}",
        ],
        [
            "tarefa ativa",
            "sim"
            if agent is not None and getattr(agent, "current_task", None)
            else "não",
        ],
    ]
    if agent is not None:
        registry = getattr(agent, "tool_registry", None)
        if registry is not None:
            rows.append(["ferramentas", str(len(registry.tools))])
    renderer.table("status", ["item", "valor"], rows)


def _cmd_skills(ctx: SlashContext) -> None:
    from app.skills.catalog import build_default_skill_registry

    registry = build_default_skill_registry()
    rows = [
        [skill.name, skill.description, str(len(skill.tools))]
        for skill in registry.list()
    ]
    ctx.renderer.table("skills", ["skill", "descrição", "tools"], rows)


def _cmd_tools(ctx: SlashContext) -> None:
    agent = ctx.get_agent()
    if agent is None:
        ctx.renderer.warn("Sem agente ativo.")
        return
    registry = getattr(agent, "tool_registry", None)
    if registry is None:
        ctx.renderer.warn("Sem registro de ferramentas.")
        return
    rows = [
        [name, tool.permission.value, tool.description.splitlines()[0][:60]]
        for name, tool in sorted(registry.tools.items())
    ]
    ctx.renderer.table("ferramentas", ["nome", "permissão", "descrição"], rows)


async def _cmd_memory(ctx: SlashContext) -> None:
    from app.memory.embeddings import LocalEmbeddingProvider
    from app.memory.repository import MemoryRepository
    from app.memory.service import MemoryService

    async with ctx.session_factory() as session:
        service = MemoryService(MemoryRepository(session), LocalEmbeddingProvider())
        items = await service.list_memories(limit=10)
    rows = [
        [item.id, f"{item.importance:.2f}", (item.content or "")[:70]]
        for item in items
    ]
    ctx.renderer.table("memórias recentes", ["id", "importância", "conteúdo"], rows)


async def _cmd_tasks(ctx: SlashContext, task_id: str | None = None) -> None:
    from app.skills.files.service import FileManager
    from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository

    async with ctx.session_factory() as session:
        service = TaskExecutorService(
            TaskRepository(session), ManagedPathRepository(session), FileManager()
        )
        if task_id:
            task = await service.get_task(task_id)
            if task is None:
                ctx.renderer.warn(f"Tarefa não encontrada: {task_id}")
                return
            ctx.renderer.table(
                "tarefa",
                ["campo", "valor"],
                [
                    ["id", task.id],
                    ["título", task.title],
                    ["instrução", task.instruction],
                    ["status", task.status],
                    ["ação", task.action],
                    ["resultado", task.result],
                    ["erro", task.error],
                ],
            )
            return
        tasks = await service.list_tasks(limit=8)
    rows = [
        [task.id, task.status, (task.title or "")[:50]] for task in tasks
    ]
    ctx.renderer.table("tarefas recentes", ["id", "status", "título"], rows)


def _cmd_cancel(ctx: SlashContext) -> None:
    ctx.cancel_event.set()
    ctx.renderer.warn("Cancelamento solicitado…")


def _cmd_clear(ctx: SlashContext) -> None:
    ctx.renderer.console.clear()


def _cmd_model(ctx: SlashContext, name: str | None = None) -> None:
    from app.llm.router import LLMRouter

    state = LLMRouter().describe_current()
    if name:
        os.environ["OLLAMA_MODEL"] = name
        ctx.settings.ollama_model = name
        ctx.renderer.ok(f"Modelo definido para: {name} (próxima mensagem usa o novo provider).")
        return
    ctx.renderer.table(
        "modelo",
        ["item", "valor"],
        [
            ["provedor", state.get("provider_name") or "-"],
            ["modelo atual", state.get("model") or "-"],
            ["base_url", state.get("base_url") or "-"],
            ["modo", ctx.settings.llm_mode],
        ],
    )


def _cmd_config(ctx: SlashContext) -> None:
    settings = ctx.settings
    rows = [
        ["app", settings.app_name],
        ["ambiente", settings.app_env],
        ["modo LLM", settings.llm_mode],
        ["stt", settings.stt_enabled],
        ["tts", settings.tts_enabled],
        ["web", settings.allow_web],
        ["memória mín.", settings.memory_min_importance],
        ["rag top-k", settings.rag_top_k],
        ["iterações máx. tools", settings.agent_max_tool_iterations],
    ]
    ctx.renderer.table("config", ["chave", "valor"], rows)


def _cmd_permissions(ctx: SlashContext) -> None:
    from app.security import PermissionManager, SecurityLevel

    settings = ctx.settings
    rows = [
        ["nível", SecurityLevel.medium.value],
        [
            "confirmação obrigatória",
            "sim" if PermissionManager().needs_confirmation("run_shell") else "não",
        ],
    ]
    ctx.renderer.table("permissoes", ["item", "valor"], rows)
    ctx.renderer.rule("diretórios permitidos")
    for path in settings.allowed_directories:
        ctx.renderer.console.print(f"  • {path}")


def _cmd_verbosity(ctx: SlashContext, level: str | None = None) -> None:
    if level:
        value = Verbosity.parse(level)
        if value is None:
            ctx.renderer.warn("Use: quiet, normal, verbose ou debug.")
            return
        ctx.verbosity.set(value)
        ctx.renderer.ok(f"Verbosity: {value.value}")
        return
    ctx.renderer.info(f"Verbosity atual: {ctx.verbosity.current.value}")


def _cmd_debug(ctx: SlashContext) -> None:
    target = Verbosity.debug if ctx.verbosity.current is not Verbosity.debug else Verbosity.normal
    ctx.verbosity.set(target)
    ctx.renderer.ok(f"Verbosity: {target.value}")


async def run_slash(line: str, ctx: SlashContext) -> SlashResult:
    """Executa um comando de barra. Retorna resultado sem passar pelo LLM."""
    parts = line.strip().split(None, 1)
    raw = parts[0].lower().lstrip("/")
    rest = parts[1].strip() if len(parts) > 1 else None
    name = _ALIASES.get(raw, raw)
    if name not in NAMES:
        return SlashResult(handled=False, message=f"Comando desconhecido: /{raw}")
    if name == "help":
        _print_help(ctx, rest)
    elif name == "status":
        _cmd_status(ctx)
    elif name == "skills":
        _cmd_skills(ctx)
    elif name == "tools":
        _cmd_tools(ctx)
    elif name == "memory":
        await _cmd_memory(ctx)
    elif name == "tasks":
        await _cmd_tasks(ctx)
    elif name == "task":
        if not rest:
            ctx.renderer.warn("Uso: /task <id>")
        else:
            await _cmd_tasks(ctx, rest)
    elif name == "cancel":
        _cmd_cancel(ctx)
    elif name == "clear":
        _cmd_clear(ctx)
    elif name == "model":
        _cmd_model(ctx, rest)
    elif name == "config":
        _cmd_config(ctx)
    elif name == "permissions":
        _cmd_permissions(ctx)
    elif name == "verbosity":
        _cmd_verbosity(ctx, rest)
    elif name == "debug":
        _cmd_debug(ctx)
    elif name == "exit":
        return SlashResult(handled=True, exit=True)
    return SlashResult(handled=True)


def is_slash(text: str) -> bool:
    return text.startswith("/")


EXIT_INPUTS = {"/exit", "/q", "/quit", "/sair"}