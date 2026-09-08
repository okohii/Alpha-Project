# ALPHA MVP

ALPHA é um agente pessoal de IA local-first com foco em privacidade, execução offline e arquitetura modular. O projeto foi estruturado para evoluir sem acoplar o núcleo a um único provedor de LLM, banco, STT/TTS ou ferramentas.

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
- **CLI terminal-first** (`alpha`): interface principal, com Rich, slash commands, streaming e eventos em tempo real
- Testes automatizados em pytest

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
- Piper TTS (`piper-tts`) para síntese de voz local

## Estrutura principal

```text
ALPHA/
├── app/
│   ├── agent/        # AgentCore, TaskEngine, router (fast path)
│   ├── api/          # rotas FastAPI (chat, health, task, conversas, docs, memory)
│   ├── calendar/
│   ├── cli/          # interface `alpha` (app, renderer, commands, events, panels, themes)
│   ├── core/         # config, eventos (EventBus), logging
│   ├── db/           # session + models (users, conversations, memory, documents, tasks, ...)
│   ├── documents/
│   ├── llm/          # base + provedores (Gemini, Ollama, mock) + router/fallback
│   ├── memory/
│   ├── perception/   # stt, wakeword, vision
│   ├── reminders/
│   ├── runtime/      # build_agent (application) + AgentContext (session)
│   ├── security/     # PermissionManager + path policy
│   ├── services/     # system (connectivity), browser (web search), health
│   ├── skills/       # base + catálogo de skills por domínio
│   ├── speech/       # audio I/O, cleaning, listener, pipeline, tts
│   ├── tasks/        # TaskExecutorService + repositórios
│   ├── tools/        # ferramentas por domínio (computer, files, web, ...)
│   └── main.py       # app FastAPI (lifespan, rotas, health)
├── scripts/
├── tests/
│   ├── unit/         # organizados por domínio (agent, cli, perception, tools, ...)
│   └── integration/
├── docs/
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
└── README.md
```

## Arquitetura resumida

```text
[Terminal / CLI (alpha) ou API REST]
                |
                v
[FastAPI API]
  |--- AgentCore
  |--- EventBus
  |--- Skills + Tool Registry
  |--- Task Engine
  |--- Fast Path (intenções determinísticas sem LLM)
  |--- Memory Service
  |--- File Manager
  |--- Speech Pipeline
  |--- Web Search
        |
   +---- Local LLM / Ollama
   +---- SQLite local (fallback)
   +---- PostgreSQL + pgvector (produção / Docker)
```

## Camadas novas (terminal-first)

- **`app/core/events.py`** — `EventBus` em processo: desacopla agente, task engine e código executável do que apenas observa (terminal, TTS, logs). Todos os eventos têm `type`, `payload` e `duration_ms`.
- **`app/agent/task.py` / `app/agent/state.py`** — `TaskEngine` e `Task` com estados explícitos (`running`, `waiting_confirmation`, `waiting_input`, `completed`, `failed`, `cancelled`), passos medidos e token de cancelamento.
- **`app/agent/router.py`** — `FastPathRouter`: intenções simples e recorrentes (abrir app/navegador/pasta, fechar app, ler arquivo, pesquisar web, lembrar, hora, print) resolvidas por regex, sem passar pelo LLM.
- **`app/security/`** — níveis `low`/`medium`/`high`, `PermissionManager` e path policy; autorização não é delegada ao LLM.
- **`app/skills/`** — `SkillRegistry` + catálogo (Browser, Files, Documents, Computer, Memory, Web, Tasks, System): as ferramentas são carregadas por skill sob demanda, em vez de todas irem sempre ao LLM.
- **`app/cli/`** — `TerminalRenderer` (Rich) e slash commands tratados localmente jamais passados ao LLM.

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
python -m pip install -e .
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

## 3) Usar a CLI `alpha`

Depois de instalar o pacote (`python -m pip install -e .`), o comando `alpha` fica disponível e é a **interface principal** do agente. Use `--json` em qualquer nível para saída estruturada.

```bash
alpha                             # inicia direto na conversa interativa (terminal-first)
alpha --help                      # lista os comandos
alpha health                      # status dos serviços (banco, Ollama, STT/TTS, web)
alpha settings --json             # configurações ativas
alpha db init                     # cria as tabelas do banco

alpha chat                        # conversa interativa (também é o comportamento padrão do `alpha`)
alpha chat "Olá ALPHA."           # mensagem única
alpha chat --no-voice "procurando"# mensagem única sem falar a resposta
alpha chat --conversation-id <id> "continuação"
```

### Comandos de barra na conversa interativa

Todos os comandos com `/` são tratados localmente (nunca enviados ao LLM):

| Comando | Efeito |
| --- | --- |
| `/help` | ajuda por categoria |
| `/exit` (`/q`, `/sair`) | encerra a sessão |
| `/clear` | limpa o terminal |
| `/status` | modelo, modo, verbosity, tarefa ativa, tools |
| `/model [nome]` | mostra/altera o modelo do Ollama |
| `/config` | mostra as configurações ativas |
| `/permissions` | lista diretórios permitidos e política |
| `/skills` | lista skills disponíveis |
| `/tools` | lista ferramentas registradas |
| `/memory` | memórias recentes |
| `/tasks` / `/task <id>` | tarefas recentes / detalhe |
| `/cancel` (`/stop`) | cancela a execução em andamento |
| `/verbosity [level]` | `quiet` \| `normal` \| `verbose` \| `debug` |
| `/debug` | alterna para verbosity `debug` |

A resposta do agente é transmitida **token a token** no terminal (quando o provider suporta streaming), e cada ferramenta/skill emite eventos reais de progresso — sem indicadores falsos. `quiet` suprime progresso; `verbose`/`debug` mostram detalhes e durações.

No modo de voz padrão, o ALPHA fica em escuta contínua e conversa de forma fluida (Estilo assistente): você fala, ele transcreve (ao notar silêncio), responde em voz e continua ouvindo. Para encerrar, diga "sair" ou pressione `Ctrl+C`.

A voz é ativada por padrão quando `STT_ENABLED` e `TTS_ENABLED` estão ligados. Use `alpha chat --no-voice` para uma sessão só de texto.

### STT direto na CLI

```bash
alpha listen                      # grava até apertar Enter e transcreve
alpha listen --duration 5         # grava 5 segundos e transcreve
alpha listen --device "Microfone" # escolhe o dispositivo de entrada
alpha voice transcribe audio.wav  # transcreve um arquivo de áudio existente
```

### TTS direto na CLI

```bash
alpha speak "texto a falar"                 # sintetiza e reproduz o áudio
alpha speak "texto" --output saida.wav       # salva em arquivo e reproduz
alpha speak "texto" --no-play --output x.wav # só salva (não reproduz)
```

### Demais comandos

```bash
alpha conversations list
alpha conversations create --title "Minha conversa"

alpha memories list
alpha memories add "fato importante" --importance 0.9
alpha memories delete <memory_id>

alpha documents index             # indexa os diretórios permitidos (managed_paths)

alpha tasks list
alpha tasks create --title "Criar arquivo" --action create_file --params '{"path": "exemplo.txt", "content": "oi"}'
alpha tasks execute <task_id>
alpha paths                       # atalho para tasks paths
alpha tasks register-path "D:\meu\dir" --source manual

python -m app.cli --help          # alternativa sem entry point instalado
```

> Em PowerShell, aspas duplas embutidas em JSON podem ser removidas ao passar para programas nativos. Prefira usar um script Python com `sys.argv` ou arquivos temporários.

## 4) Executar o backend de diferentes formas

### Forma A — via uvicorn direto

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

No Windows:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Depois, use a CLI como interface principal (`alpha`) ou acesse a API diretamente:

- http://127.0.0.1:8000/docs (OpenAPI)
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/settings

### Forma B — via python -m uvicorn

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Forma C — modo sem hot reload

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Forma D — usando Docker Compose

Primeiro, confirme que o Docker está instalado:

```bash
docker --version
docker compose version
```

Então rode:

```bash
docker compose up --build
```

A API estará em:

```text
http://localhost:8000
```

Banco PostgreSQL estará em:

```text
localhost:5432
```

Para parar:

```bash
docker compose down
```

## 5) Verificações rápidas do backend

### Teste de health

```bash
curl http://127.0.0.1:8000/health
```

Exemplo de resposta:

```json
{
  "status": "ok",
  "services": {
    "database": "ok",
    "ollama": "down",
    "stt": "ok",
    "tts": "ok",
    "web": "available"
  }
}
```

### Teste de settings

```bash
curl http://127.0.0.1:8000/settings
```

### Teste de chat

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Olá ALPHA."}'
```

### Teste de voz

Antes de chamar a rota de voz, confirme que o modelo do Piper existe no caminho configurado em `TTS_VOICE`.

Se você estiver usando o pacote Python do Piper, garanta também que ele foi instalado no mesmo ambiente virtual do projeto:

```bash
python -m pip install piper-tts
```

No Windows PowerShell:

```powershell
Test-Path "C:\piper\models\pt_BR\cadu\medium\pt_BR-cadu-medium.onnx"
```

Se o resultado for `False`, ajuste `TTS_VOICE` no `.env` para o caminho real do arquivo `.onnx` e reinicie o backend antes de testar:

```bash
curl -X POST http://127.0.0.1:8000/voice/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"teste de voz"}'
```

### Teste via Python

```bash
python - <<'PY'
import httpx
r = httpx.post('http://127.0.0.1:8000/chat', json={'message': 'Olá ALPHA.'}, timeout=20)
print(r.status_code)
print(r.text)
PY
```

## 6) Testes do projeto

### Rodar todos os testes

```bash
source .venv/bin/activate
pytest
```

ou

```bash
python -m pytest
```

### Rodar somente testes unitários

```bash
pytest tests/unit -q
```

### Rodar somente testes de integração

```bash
pytest tests/integration -q
```

### Rodar teste específico

```bash
pytest tests/unit/memory/test_memory.py -q
```

### Rodar com relatório mais detalhado

```bash
pytest -vv
```

### Rodar em modo quiet

```bash
pytest -q
```

## 7) Teste manual do fluxo principal

### 1. Health

```bash
curl http://127.0.0.1:8000/health
```

### 2. Chat simples

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Olá ALPHA."}'
```

### 3. Health do LLM

```bash
curl http://127.0.0.1:8000/health/llm
```

### 4. Verificar banco

```bash
python - <<'PY'
import asyncio
from app.db.session import initialize_database

async def main():
    await initialize_database()
    print('DB ok')

asyncio.run(main())
PY
```

## 8) Ollama (opcional)

O projeto usa a abstração `LLMProvider` e permite um provedor local via Ollama.

### Instalar Ollama

- Linux: siga a documentação oficial do Ollama
- macOS: instalação via site oficial
- Windows: usar a distribuição oficial do Ollama

### Iniciar Ollama

```bash
ollama serve
```

### Baixar um modelo

```bash
ollama pull llama3.2
```

ou outro modelo disponível no seu ambiente.

### Configurar variável de ambiente

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
LLM_MODE=local
```

### Testar health do Ollama

```bash
curl http://localhost:11434/api/tags
```

> Se o Ollama não estiver disponível, o backend continua funcionando em modo degradado com mock/local fallback.

## 9) PostgreSQL (opcional)

### Rodar PostgreSQL local manualmente

Com o PostgreSQL instalado localmente:

```sql
CREATE DATABASE ALPHA;
CREATE USER ALPHA WITH PASSWORD 'ALPHA';
GRANT ALL PRIVILEGES ON DATABASE ALPHA TO ALPHA;
```

Depois configure no `.env`:

```env
DATABASE_URL=postgresql+asyncpg://ALPHA:ALPHA@localhost:5432/ALPHA
```

### Rodar com Docker Compose

```bash
docker compose up postgres
```

## 10) Banco e migrações

O projeto usa Alembic e carregamento local de schema em desenvolvimento.

### Criar schema local em SQLite

O app já tenta criar tabelas na inicialização quando o ambiente não é `production` e o banco é SQLite.

### Migrações Alembic

```bash
alembic upgrade head
```

### Verificar status do Alembic

```bash
alembic current
```

## 11) Fluxos de desenvolvimento útil

### Iniciar com o backend ativo e testar em outra aba

Terminal 1:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Terminal 2:

```bash
curl http://127.0.0.1:8000/health
```

### Executar testes sem reiniciar backend

```bash
pytest -q
```

### Validar funcionamento do mock LLM

```bash
curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' -d '{"message":"Olá ALPHA."}'
```

## 12) Troubleshooting

### Erro: `No module named pytest`

```bash
python -m pip install -e .
```

### Erro: `Connection refused` no backend

- Verifique se o uvicorn está rodando
- Verifique se a porta 8000 está livre
- Verifique se o app subiu sem erro no terminal

### Erro: `sqlite3.OperationalError: no such table`

Isso normalmente acontece quando o ambiente local ainda não criou as tabelas. O app tenta corrigir isso na inicialização em SQLite, mas se quiser reforçar:

```bash
python - <<'PY'
import asyncio
from app.database.session import initialize_database

asyncio.run(initialize_database())
print('schema ok')
PY
```

### Erro: `Modelo de voz do Piper não encontrado`

Esse erro significa que `TTS_VOICE` aponta para um arquivo `.onnx` que não existe no disco. Verifique o caminho configurado no `.env`, confirme se o arquivo foi baixado corretamente e reinicie o backend depois da correção.

Exemplo de validação no PowerShell:

```powershell
Test-Path $env:TTS_VOICE
```

### Erro: `Falha no Piper`

Esse erro normalmente aparece quando o pacote `piper-tts` não está instalado no mesmo ambiente virtual do backend, ou quando o modelo não consegue ser carregado no processo em execução. Reinstale o pacote na `.venv`, confirme o `TTS_VOICE` e reinicie o Uvicorn.

### Erro: Ollama indisponível

O sistema continua funcionando com o provedor mock; nesse caso, o health pode mostrar `ollama: down` e o chat ainda funciona em modo local/fallback.

### Erro: Banco PostgreSQL indisponível

Use o SQLite local como fallback para desenvolvimento, ou suba o container.

## 13) Dicas de uso rápido

### Ambiente virtual

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Instalar dependências do projeto

```bash
python -m pip install -e .
```

### Executar a API

```bash
uvicorn app.main:app --reload
```

### Executar testes

```bash
pytest -q
```

## 14) Roadmap de evolução

- Descoberta/skills sob demanda já em andamento (carga de tools por skill)
- Executor multi-etapas com foco em verificação (OBSERVE → DECIDE → ACT → VERIFY)
- Percepção de GUI estruturada (access tree > DOM > OCR > visão) e fallback visão
- Otimização de contexto (memória e tools relevantes por turno)
- Streaming/confirmação/cancelamento são a base atual já funcional
- Wake word
- Streaming de TTS
- Automação local e remota