# ALPHA — Arquitetura

Mapa dos módulos de `app/` e princípios que guiam a estrutura.

## Visão geral

`app/` é organizado por **domínio**, com provedores plugáveis e serviços transversais isolados.

## Fluxo principal (User → Result)

```
User (texto/voz)
   → Facilitator: Request → Intent → Goal
   → Complexity Gate
   → Planner: Goal → Plan
   → Skill/Tool: seleção + permissão determinística
   → Perception: UIA → DOM/CDP → OCR/Tesseract → Vision
   → Evidence/Verification
   → Done / Recover
```

## Mapa de módulos

| Pacote | Responsabilidade | Destaques |
| --- | --- | --- |
| `app/agent/` | Núcleo do agente | `AgentCore`, `SerializedAgentCore`, `ReliableAgentCore`, `Planner` |
| `app/api/` | REST FastAPI | rotas protegidas por token local quando sensíveis |
| `app/assistant/` | Camada COMPREENDER | Facilitator, Intent, entidades, resolução e ambiguidade |
| `app/avatar/` | Reflexo visual e sessão de voz | `AvatarController`, `AvatarSession`, WS local |
| `app/calendar/` | Agenda declarativa | eventos persistentes; não executa ações arbitrárias |
| `app/cli/` | Launcher | `alpha`, `alpha chat`, `alpha macros` |
| `app/core/` | Infra transversal | config, EventBus, filas limitadas, presentation helpers |
| `app/db/` | Persistência | sessão e modelos |
| `app/documents/` | Documentos | parsing e indexação |
| `app/llm/` | Provedores de LLM | router, fallback e trust boundary |
| `app/memory/` | Memória e episódios | repository + serviço + retenção |
| `app/perception/` | Entrada sensorial | STT, UIA, DOM/CDP adapter, OCR real opcional, Vision |
| `app/reminders/` | Lembretes acionáveis | scheduler + ações explicitamente permitidas |
| `app/runtime/` | Composição | `build_agent` → `ReliableAgentCore` |
| `app/security/` | Autorização | permissões, path policy, URL/SSRF, API/WS auth, redaction |
| `app/services/` | Serviços transversais | connectivity, web search, health/metrics |
| `app/skills/` | Skills = domínios | cada domínio possui metadados, service e tools |
| `app/speech/` | Áudio | captura VAD, STT, pipeline, Kokoro TTS |
| `app/tasks/` | Execução persistente | executor + repositories |
| `app/tools/` | Infra de tools | contratos e registry |

## Decisões arquiteturais

- **Skills = domínios** — `app/tools` guarda infraestrutura; ferramentas específicas vivem em `app/skills/<domínio>/tools`.
- **Segurança nunca depende do LLM** — permissão, confirmação, path policy e URL policy são determinísticos.
- **Evidência é hierárquica** — UIA/DOM são preferidos quando existem; OCR só é usado quando há motor real; Vision é fallback caro; ausência de evidência nunca vira sucesso.
- **DOM real** — `DOMPerceptor.perceive_from_browser()` consome o contexto CDP real do `BrowserDriver`; sem CDP retorna indisponível, não uma árvore inventada.
- **OCR real opcional** — `OCRPerceptor` usa Tesseract quando disponível e expõe confiança/caixas; sem motor real permanece indisponível.
- **Fonte única de apresentação** — `core/presentation.py` concentra confirmation/execution payloads compartilhados pelas UIs.
- **EventBus** — `emit()` mantém compatibilidade síncrona; `emit_async()` move sanitização para thread e permite handlers assíncronos. Handlers async recebidos pelo caminho síncrono são agendados, nunca aguardados.
- **Execução não bloqueia o event loop** — subprocessos, COM, captura de áudio, STT/TTS e I/O pesado usam threads quando necessário; filas são limitadas.
- **Avatar/Overlay não decidem segurança** — são projeções de eventos e interfaces de confirmação; o AgentCore continua sendo o gate.
- **Calendar vs Reminder** — Calendar representa compromissos; Reminder representa agenda acionável. Não compartilhar estado de execução reduz acoplamento e evita que um evento de calendário vire ação automaticamente.
- **Cancelamento** — o cancel event é propagado até o agente e as sessões de voz interrompem captura pendente via eventos de abort.

## Validação

A suíte deve cobrir: tool-call causal, falha e recuperação por estratégia alternativa, verificação positiva/negativa, cancelamento, claims sem execução, prompt injection, path traversal, SSRF/DNS rebinding, confirmação, VRAM insuficiente, DOM/CDP e OCR sem motor.

Comandos locais/CI: `python -m pytest tests -q` e `python -m ruff check app tests`.
