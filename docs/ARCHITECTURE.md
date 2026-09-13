# ALPHA — Arquitetura

Mapa dos módulos de `app/` e princípios que guiam a estrutura.

## Fluxo principal

```text
User (texto/voz)
   → Facilitator: Request → Intent → Goal
   → Complexity Gate → Planner
   → Skill/Tool: seleção + permissão determinística
   → Perception: UIA → DOM/CDP → OCR/Tesseract → Vision
   → Evidence/Verification
   → Done / Recover
```

## Fronteiras de responsabilidade

- `app/agent/`: decisão, plano, execução e evidência.
- `app/skills/`: domínios; ferramentas específicas vivem no domínio.
- `app/tools/`: contratos e infraestrutura compartilhada.
- `app/perception/`: fontes de observação. DOM usa CDP real; OCR usa Tesseract quando disponível; ausência de fonte nunca vira sucesso.
- `app/avatar/controller.py`: estado visual/animação.
- `app/avatar/voice_runtime.py`: STT, VAD, agente, TTS e interrupção.
- `app/avatar/server.py`: somente WebSocket, fila, sessão e lifecycle.
- `app/overlay/`: projeção de eventos para a UI compacta.
- `app/core/interaction_state.py`: fonte única de fases de interação derivadas do EventBus; Avatar e Overlay só fazem adaptações visuais.
- `app/core/presentation.py`: payloads de confirmação e execução compartilhados pelas UIs.
- `app/core/scheduling.py`: relógio UTC/local e normalização temporal compartilhados por domínios de agenda.
- `app/calendar/`: compromissos declarativos; não executa ações arbitrárias.
- `app/reminders/`: agenda acionável com allowlist de ações seguras.

## Segurança local

- Operações sensíveis da API exigem `ALPHA_LOCAL_API_TOKEN`.
- Quando uma requisição sensível vem de browser, `Origin` deve ser loopback e compatível com o `Host` da API; `Origin: null` e origens externas são rejeitadas.
- WebSockets sensíveis exigem Origin local ou cliente sem Origin exclusivamente em loopback.
- A política de URL bloqueia loopback, private/link-local/metadata, formas numéricas alternativas de IPv4 e hostnames que resolvem para endereços privados.
- Path policy é determinística e bloqueia traversal/saída de `ALLOWED_DIRECTORIES`.
- Nenhum desses gates depende do LLM.

## Performance

- I/O bloqueante, captura de áudio, STT/TTS e embeddings pesados devem sair do event loop.
- `EventBus.emit_async()` sanitiza payload em thread e aguarda handlers assíncronos; `emit()` permanece compatível e agenda handlers async sem bloquear o emissor.
- Filas de UI são limitadas e usam descarte do item mais antigo para impedir crescimento infinito.

## Validação

A suíte deve cobrir: tool-call causal, falha e recuperação por estratégia alternativa, verificação positiva/negativa, cancelamento, claims sem execução, prompt injection, path traversal, CSRF/DNS rebinding, confirmação, VRAM insuficiente, DOM/CDP e OCR sem motor.

Comandos locais/CI: `python -m pytest tests -q` e `python -m ruff check app tests`.
