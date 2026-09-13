# ALPHA — Arquitetura

Mapa dos módulos de `app/` e princípios que guiam a estrutura.

## Visão geral

`app/` é organizado por **domínio** (responsabilidade única por pacote), com

- `__init__.py` agregadores que preservam a superfície pública de imports;
- provedores plugáveis (LLM, STT/TTS, vision, web search) atrás de abstrações;
- serviços transversais isolados (conectividade/offline, busca web, health/metrics) em `services/`.

## Fluxo principal (User → Result)

```
User (texto/voz)
   → Facilitator (app/assistant): Request → Intent → Goal
        • fast path direto (cumprimentos) sem LLM/tools
        • perguntas simples → turno LLM sem tools (llm_answer)
        • multi-step: frases com conectores viram Goal com N Tasks
   → Complexity Gate (app/agent/reliable): determinístico, barato
   → Planner (app/agent/planner): Goal → Plan com steps verificáveis
   → Skill/Tool (app/skills, app/tools): seleção por skill + permissão
   → Perception/Evidence/Verification (app/perception, app/evidence)
   → Done / Recover (retry com estratégia por classe de falha)
```

## Mapa de módulos

| Pacote | Responsabilidade | Destaques |
| --- | --- | --- |
| `app/agent/` | Núcleo do agente | `AgentCore` (`agent.py`), `SerializedAgentCore` (`serialized.py`), `ReliableAgentCore` (`reliable.py`, complexidade + verificação), `Planner` (`planner.py`), `Task`/`Goal` (`assistant/intent.py`) |
| `app/api/` | REST FastAPI | rotas: health(+metrics), chat, voice, memory, documents, tasks, macros, conversations, settings; `/chat` exige `ALPHA_LOCAL_API_TOKEN` |
| `app/assistant/` | Camada COMPREENDER | `AssistantFacilitator` (`facilitator.py`), `IntentDetector` (`intent.py`), `entities.py`, `resolver.py`, `ambiguity.py`, `context.py` |
| `app/avatar/` | Reflexo visual do sistema (voz contínua) | `AvatarSession`, WS autenticado por origem, streaming TTS por segmentos |
| `app/calendar/` | Agenda | service + modelos |
| `app/cli/` | Launcher mínimo | `alpha` / `alpha chat` / `alpha macros` (`launcher.py`) |
| `app/core/` | Infra transversal | `config.py` (Settings), `events.py` (EventBus), `logging.py` (categorias, redação, JSON), `bounded.py` (filas limitadas), `presentation.py` (helpers compartilhados avatar/overlay) |
| `app/db/` | Persistência | `session.py`, `models/` |
| `app/documents/` | Documentos | parse + indexação |
| `app/llm/` | Provedores de LLM | `router.py` (`LLMRouter` + `FaultTolerantProvider` com streaming tolerante a falhas), `trust.py` (contrato de conteúdo não confiável) |
| `app/memory/` | Memória e episódios | service + repositório SQLite |
| `app/perception/` | Entrada sensorial | `stt.py`, `wakeword.py`, `vision/` (provider + verificação conservadora) |
| `app/reminders/` | Lembretes | service + runner (notificação off-thread) |
| `app/runtime/` | Composição | `application.py` (`build_agent` → `ReliableAgentCore`), `session.py` |
| `app/security/` | Autorização | `permissions.py`, `policy.py`, `capabilities.py` (nunca auto-aprova SYSTEM_CONTROL/execução), `path_policy.py`, `urlpolicy.py` (SSRF + IPv4 alternativo + DNS rebinding), `api_gate.py` (token fail-closed), `wsauth.py` (origem de WebSocket local), `redact.py` |
| `app/services/` | Serviços transversais | `system/connectivity.py`, `browser/search.py`, `health/` (`checks.py`, `metrics.py`) |
| `app/skills/` | Skills = domínios | `base.py`, `registry.py`, `catalog.py`, e por domínio com `skill.py` + `service.py` + `tools/` |
| `app/speech/` | Áudio | `audio_io.py`, `listener.py`, `pipeline.py`, `tts.py` (Kokoro com lock de engine e streaming), `emotion.py` |
| `app/tasks/` | Execução persistente | `TaskExecutorService`, repositórios |
| `app/tools/` | Infraestrutura transversal de tools | `base.py`, `registry.py` (detecção de duplicatas), `errors.py` |

## Decisões

- **Skills = domínios** — cada domínio em `app/skills/<domínio>/` com `skill.py` (metadado `SKILL`), `service.py` (lógica reutilizável) e `tools/*.py`. `app/tools/` guarda apenas a infraestrutura transversal.
- **Segurança nunca depende do LLM**: permissão/confirmação são gates determinísticos (`policy.py`, `capabilities.py`); conteúdo não confiável (tools, memória, perfil, evidências) é delimitado como DADO (`llm/trust.py`); WebSockets locais validam origem (`security/wsauth.py`); REST sensível exige token (`api_gate.py`).
- **Fonte única**: ferramentas de verificação estrita em `app/execution/models.py::STRICT_VERIFICATION_TOOLS`; coerção de URL em `security/urlpolicy.py`; parsing de confirmação em `core/presentation.py`.
- **Execução nunca bloqueia o event loop**: I/O pesado/COM/subprocessos/áudio off-thread (`asyncio.to_thread`); filas de UI limitadas com descarte controlado (`core/bounded.py`).
- **Testes**: `pytest tests` cobre unit + integração; `tests/conftest.py` fixa política Selector no Windows e isola o singleton de settings. Verificação: `python -m pytest tests -q` e `python -m ruff check app tests`.