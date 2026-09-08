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
| `app/skills/` | Catálogo de habilidades | `base.py`, `registry.py`, `catalog.py`, domínios (browser, computer, documents, files, memory, system, tasks, web) |
| `app/speech/` | Áudio | `audio_io.py`, `cleaning.py`, `listener.py`, `pipeline.py`, `tts.py` |
| `app/tasks/` | Execução persistente | `TaskExecutorService`, repositórios, actions (create_file, persist_repo_changes, ...) |
| `app/tools/` | Ferramentas por domínio | `base.py`, `registry.py`, e `browser/`, `calendar/`, `computer/` (keyboard, mouse, screenshot, process, window, uia, application), `documents/`, `files/`, `memory/`, `reminders/`, `shell/`, `system/`, `tasks/`, `web/` |

## Decisões

- **Packages agregadores** — `from app.tools.web import ...`, `from app.tools.files import FileManager` etc. continuam válidos porque o `__init__.py` de cada pacote re-exporta os nomes do submódulo definidor.
- **Testes** são organizados por domínio em `tests/unit/<domínio>/` e `tests/integration/`; alias de módulo em monkeypatch deve apontar ao **submódulo definidor** (patch em pacote não rebinda o global do submódulo).
- **Estado de verificação**: integridade via `python -m pytest tests -q` (291 testes) e `python -m ruff check .`.