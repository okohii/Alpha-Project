# ALPHA — Arquitetura

Mapa dos módulos de `app/` e princípios que guiam a estrutura.

## Visão geral

`app/` é organizado por **domínio** (responsabilidade única por pacote), com

- `__init__.py` agregadores que preservam a superfície pública de imports;
- provedores plugáveis (LLM, STT/TTS, vision, web search) atrás de abstrações;
- serviços transversais isolados (conectividade/offline, busca web, health) em `services/`.

## Mapa de módulos

| Pacote | Responsabilidade | Destaques |
| --- | --- | --- |
| `app/agent/` | Núcleo do agente | `AgentCore` (`agent.py`), `FastPathRouter` (`router.py`, intenções regex sem LLM), `Task`/`TaskEngine` (`task.py`, `state.py`) |
| `app/api/` | REST FastAPI | rotas: chat, health, conversations, documents, memory, tasks |
| `app/avatar/` | Reflexo visual do sistema | `AvatarState`/`state_for_event` (`state.py`), `AnimationMapping` (`mapping.py`), `AvatarController` (`controller.py`, assinante do EventBus), `AvatarRenderer`/`NullRenderer` (`renderer.py`); renderers Live2D/2D/3D são substituíveis via `AvatarCommand`. Janela overlay transparente/sem moldura (`desktop.py`) + sessão de voz contínua com mic ligado (`server.py`, WS + voice loop)` |
| `app/calendar/` | Agenda | service + modelos |
| `app/cli/` | Interface `alpha` | `app.py` (main), `renderer.py`, `commands.py` (slash), `events.py` (render handlers), `panels.py`, `themes.py` (Verbosity); entry point `app.cli:main` e `python -m app.cli` |
| `app/core/` | Infra transversal | `config.py` (Settings), `events.py` (EventBus), `logging.py` |
| `app/db/` | Persistência | `session.py` (engine, `get_session`, `initialize_database`), `models/` (users, conversations, memory, documents, tasks, events, calendar, reminders) |
| `app/documents/` | Documentos | parse + indexação |
| `app/llm/` | Provedores de LLM | `base.py` (Protocol/ToolCall), `gemini.py`, `ollama.py`, `mock.py`, `router.py` (`LLMRouter` + `FaultTolerantProvider` fallback) |
| `app/memory/` | Memória e episódios | service + `build_episode_memory`/`detect_kind` |
| `app/perception/` | Entrada sensorial | `stt.py`, `wakeword.py`, `vision/` (provider + verificação) |
| `app/reminders/` | Lembretes | service + modelos |
| `app/runtime/` | Composição | `application.py` (`build_agent`), `session.py` (`AgentContext`) |
| `app/security/` | Autorização | `PermissionManager`/níveis, `path_policy` (resolução de caminhos) |
| `app/services/` | Serviços transversais | `system/connectivity.py` (offline → `detect_connectivity`), `browser/search.py` (provider de busca web), `health/checks.py` (`collect_health`) |
| `app/skills/` | Skills = domínios | `base.py`, `registry.py`, `catalog.py`, e por domínio: `skill.py` (metadado), `service.py` (lógica reutilizável) e `tools/` (Tools chamáveis). Domínios: browser, calendar, computer, documents, files, memory, reminders, shell, system, tasks, web |
| `app/speech/` | Áudio | `audio_io.py`, `cleaning.py`, `listener.py`, `pipeline.py`, `tts.py` |
| `app/tasks/` | Execução persistente | `TaskExecutorService`, repositórios, actions (create_file, persist_repo_changes, ...) |
| `app/tools/` | Infraestrutura transversal de tools | `base.py`, `registry.py`, `errors.py` (sem tools concretas) |

## Decisões

- **Skills = domínios** — cada domínio em `app/skills/<domínio>/` com `skill.py` (metadado `SKILL`), `service.py` (lógica reutilizável: ex. `FileManager`, `ApplicationLauncher`, `BrowserDriver`, `SandboxRunner`) e `tools/*.py` (classes `Tool`). `app/tools/` guarda apenas a infraestrutura transversal (`base.py`, `registry.py`, `errors.py`).
- **Testes** são organizados por domínio em `tests/unit/<domínio>/` e `tests/integration/`; alias de módulo em monkeypatch deve apontar ao **submódulo definidor** (patch em pacote não rebinda o global do submódulo).
- **Estado de verificação**: integridade via `python -m pytest tests -q` (291 testes) e `python -m ruff check .`.