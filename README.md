# ALPHA MVP

ALPHA é um agente pessoal de IA local-first com foco em privacidade, execução offline e arquitetura modular. O projeto foi estruturado para evoluir sem acoplar o núcleo a um único provedor de LLM, banco, STT/TTS ou ferramentas.

## Interfaces do ALPHA

O produto expõe somente duas formas de conversar com o agente, além da tela dedicada de macros:

- **`alpha`** — abre diretamente o **Astral Avatar**, com voz contínua, captions, estado visual e timeline de execução.
- **`alpha chat`** — abre o **Chat Overlay**, com texto, microfone opcional, streaming e timeline de execução.
- **`alpha macros`** — abre a tela nativa de macros, gravação e agendamentos.

Avatar e Chat Overlay usam o **mesmo AgentCore, EventBus, skills, tools, memória, tarefas, permissões e verificação**. A interface apenas apresenta o que o agente está fazendo. Logs técnicos continuam no terminal.

Não há mais um modo de produto separado para CLI de voz, CLI de chat, task runner ou automation: essas capacidades são usadas pelo agente através das duas interfaces principais.

## Visão geral

O MVP inclui:

- API REST em FastAPI
- Agente com loop de conversa e tool calling
- LLM local com abstração para Ollama e mock
- Memória persistente
- Busca semântica por embeddings
- Gerenciamento de arquivos com diretórios autorizados
- Sistema de documentos e indexação básica
- Pipeline de voz com STT/TTS abstratos
- **Astral Avatar** (`alpha`): voz contínua + presença visual + eventos de execução
- **Chat Overlay** (`alpha chat`): conversa textual/voz + eventos de execução
- **Macro UI** (`alpha macros`): criação, gravação, execução e agendamento de macros
- Testes automatizados em pytest

## Comandos principais

```text
alpha          # Avatar + voz
alpha chat     # Chat Overlay
alpha macros   # Tela de macros
```

## Requisitos

### Necessários

- Python 3.11+
- pip
- Git

### Opcionais

- PostgreSQL + pgvector
- Ollama para LLM local
- Docker + Docker Compose
- Microfone e saída de áudio para uso de voz
- Kokoro/Piper conforme a configuração do ambiente

## Estrutura principal

```text
ALPHA/
├── app/
│   ├── agent/        # AgentCore, TaskEngine, router (fast path)
│   ├── api/          # rotas FastAPI
│   ├── avatar/       # Astral Avatar + voz + eventos de execução
│   ├── calendar/
│   ├── cli/          # launcher mínimo: avatar, chat overlay e macros
│   ├── core/         # config, eventos (EventBus), logging
│   ├── db/           # session + models
│   ├── documents/
│   ├── llm/          # provedores + router/fallback
│   ├── macros/        # automação, gravação e agendamento
│   ├── memory/
│   ├── overlay/      # Chat Overlay + WebSocket + UI
│   ├── perception/   # stt, wakeword, vision
│   ├── reminders/
│   ├── runtime/      # build_agent + contexto de execução
│   ├── security/     # permissões e path policy
│   ├── services/
│   ├── skills/       # catálogo de skills por domínio
│   ├── speech/       # áudio, STT/TTS e pipeline
│   ├── tasks/        # TaskExecutorService + repositórios
│   ├── tools/        # ferramentas por domínio
│   └── main.py       # app FastAPI
├── tests/
├── docs/
├── .env.example
├── pyproject.toml
├── alembic.ini
└── README.md
```

## Arquitetura resumida

```text
                 ALPHA
                   |
        +----------+----------+
        |                     |
   alpha (Avatar)       alpha chat (Overlay)
        |                     |
        +----------+----------+
                   |
               AgentCore
                   |
       +-----------+-----------+
       |           |           |
     Skills      Tasks       Memory
       |           |           |
     Tools      Macros     Documents
       |           |
       +----- EventBus -------+
                   |
        Execute -> Observe -> Verify
                   |
             Local LLM / STT / TTS

              alpha macros
                   |
             Macro UI + Scheduler
```

### EventBus como contrato de UI

O `EventBus` desacopla o agente da apresentação. O Core emite eventos como `tool_started`, `tool_finished`, `verification_started`, `verification_completed`, `task_step_completed` e `agent_finished`. Avatar e Overlay refletem esses eventos; nenhum deles decide o fluxo, segurança ou seleção de ferramentas.

## 1) Clonar e preparar o ambiente

### Windows PowerShell

```powershell
git clone <seu-repositorio>
cd "D:\Projects\teste agente llm"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

### Windows CMD

```cmd
git clone <seu-repositorio>
cd /d D:\Projects\teste agente llm
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
```

### Linux / macOS

```bash
git clone <seu-repositorio>
cd /caminho/para/ALPHA
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

## 2) Configuração das variáveis de ambiente

Crie um arquivo `.env` a partir do exemplo:

```bash
cp .env.example .env
```

No Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

### Configuração mínima recomendada

```env
APP_NAME=ALPHA
APP_ENV=development
DATABASE_URL=sqlite+aiosqlite:///./alpha.db

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=
LLM_MODE=local
ALLOW_CLOUD_LLM=false
ALLOW_WEB=true

MEMORY_MIN_IMPORTANCE=0.70
RAG_TOP_K=5
AGENT_MAX_TOOL_ITERATIONS=8
```

### Se quiser usar PostgreSQL

```env
DATABASE_URL=postgresql+asyncpg://ALPHA:ALPHA@localhost:5432/ALPHA
```

> O projeto foi construído para funcionar com SQLite em desenvolvimento, e usa PostgreSQL quando configurado.
