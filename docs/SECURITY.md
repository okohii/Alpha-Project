# Superfície de Ataque — ALPHA

Documento de referência para auditoria: que operação existe, qual risco, qual
confirmação, qual timeout. A decisão NUNCA depende do LLM (prompt não é
controle de segurança).

## Gates estruturais

| Camada | Onde | Fail-closed |
|---|---|---|
| Capability | `app/security/capabilities.py` | tool sem capability é `READ`; `NON_AUTO_APPROVABLE` impede auto-aprovação de execução |
| Risco | `risk_level_for_tool` | close_app/open_app/open_file/move_app/exec* → high; rede/automation/write → medium |
| Confirmação | `AgentCore._execute_tool` | sensitive/EXECUTE sempre perguntam; sem handler → negado (exceto write não-sensitivo via flag) |
| API | `app/security/api_gate.py` | rotas de execução exigem `ALPHA_LOCAL_API_TOKEN`; vazio → 403 |
| URL | `app/security/urlpolicy.py` | schemes http/https apenas; loopback/privado/metadata bloqueados; allowlist extra por config |
| Scheduler | reminders/macros runner | ações que exigem confirmação são negadas em execução agendada |

## Matriz Capability × Tool

| Tool | Permission | Capability | Risco | Confirmação | Timeout |
|---|---|---|---|---|---|
| file_read/search/info | read | READ | low | não | — |
| file_write | sensitive | WRITE_FILE+SYSTEM_CONTROL | high | sim | agent_tool_timeout |
| open_app | write | EXECUTE+SYSTEM_CONTROL | high | sim | — |
| open_url | write | NETWORK+NAVIGATION | medium | sim | — |
| open_file | write | FILE_OPEN | high | sim | — |
| close_app | write | SYSTEM_CONTROL+EXECUTE | high | sim | — |
| type_text/press_key/click/mouse | write | AUTOMATION | medium | sim | — |
| read_ui | read | READ | low | não | — |
| screenshot/verify_screen | read | SCREEN_CAPTURE | low | não | semaf != vision |
| browser_open | write | NAVIGATION+NETWORK | medium | sim | — |
| browser_text/html | read | DOM_READ | low | não | — |
| browser_js | sensitive | JS_EXECUTION+NETWORK | high | sim | — |
| web_search | read | READ | low | não | allow_web |
| run_code | sensitive | EXECUTE_CODE | high | sim | code_exec_timeout |
| run_shell | sensitive | EXECUTE_SHELL | high | sim | code_exec_timeout |
| macro_run | sensitive | MACRO_EXECUTION | high | sim | 30s |
| macro_create/delete/schedule | sensitive | MACRO_EXECUTION+WRITE/SCHEDULE | high | sim | — |
| task_execute | sensitive | EXECUTE+GIT_LOCAL/GIT_NETWORK | high | sim | agent_tool_timeout |
| task_register_path | sensitive | SYSTEM_CONTROL | high | sim | — |
| reminder_create | write | SCHEDULE+WRITE | medium | sim* | — |
| calendar_create | write | WRITE | medium | sim** | — |

\* execução de lembrete agendado reavalia `is_auto_approvable` (fail-closed).
\** agendamento de ações no calendário não existe (modelo não suporta); skill Calendar só cria/liste/exclui eventos.

## Execução arbitrária (rotas protegidas)

- API: `POST /tasks`, `/tasks/{id}/execute`, `/tasks/paths`, macros create/update/delete/execute/schedules, `/documents/index` → `Authorization: Bearer ALPHA_LOCAL_API_TOKEN`.
  Sem token → 403. `127.0.0.1` NÃO é confiável por si só.
- Agendado: reminders e macros agendadas passam por avaliação de capability; passos ativos de macro/macro_run em agendamento → negados.

## Sandbox de código

- `run_code`/`run_shell`: confirmação obrigatória; timeout (`code_exec_timeout_seconds`); processo morto com kill da ÁRVORE (taskkill `/T /F` no Windows; `SIGKILL` no process group POSIX); **Job Object Windows `KILL_ON_JOB_CLOSE`**; **Linux: `bwrap` com `--unshare-net`, sistema read-only e `/tmp` isolado quando disponível** (degrada para kill-de-árvore se ausente).
- Descrição honesta: execução arbitrária com privilégios do usuário — **não** é sandbox OS completo sem `bwrap` (sem seccomp direto).

## Redação (secrets)

- `app/security/redact.py`: `redact_secrets`/`redact_text` — chaves (`token`, `password`, `api_key`, `authorization`, `cookie`, `secret`, `credential`…) + padrões (`sk-*`, `Bearer …`, `key=…`, JSON aninhado). Aplicado em `ToolExecution` (DB), memória e EventBus (por nome de chave + truncamento).

## Prompt injection

- Contrato único `app/llm/trust.py`: resultado de tool não confiável → delimitado `>>> INÍCIO DO CONTEÚDO NÃO CONFIÁVEL >>>` em Ollama, OpenAI-compatível e Gemini.
- `UNTRUSTED_CONTENT_TOOLS` (browser_text/html/js/click/screenshot, web_search, read_ui, file_read/search/write, verify_screen) marcam `trusted=False`.

## Verificação e evidência

- `ExecutionEvidence` com `verified`/`status` (executed/verified/executed_unverified/failed) + `session_id`/`conversation_id` (telemetria).
- `Notify: uma evidência visual NÃO promove outras ações` (correlação removida).
- `min_score`/relevância: grounding de memória corta por relevância, não pelo piso de importância.
- VRAM: verificação visual é **precedida** por guard de VRAM (`vision_min_free_vram_mb` via nvidia-smi) e limitada por semáforo (`vision_max_concurrent`) e cap por turno.

## Sessões

- Por turno do agente: sessão única e serializada (`_turn_lock`) com `expire_on_commit=False` — sem concorrência acidental entre memory/tool-execution.
- Jobs independentes (reminders, macros, purge, schedulers): sessão própria via `session_scope()`.

## Observabilidade de segurança

Eventos: `permission_decision`, `waiting_confirmation`, `honesty_gate`, `tool_failed` (com `failure_class`/`retry_strategy`), `tool_selected`. Logs não contêm secrets.