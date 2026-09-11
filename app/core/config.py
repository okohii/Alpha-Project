from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_allowed_directories() -> list[Path]:
    """Diretórios padrão liberados quando nada é configurado em ALLOWED_DIRECTORIES."""
    home = Path.home()
    candidates = [
        Path.cwd(),
        home,
        home / "Downloads",
        home / "Documents",
        home / "Desktop",
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        result.append(resolved)
    return result


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ALPHA"
    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./alpha.db"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_vision_model: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1/models"
    gemini_model: str = "gemini-3.6-flash"
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"),
    )
    llm_mode: Literal["local", "cloud", "auto"] = "local"
    allow_cloud_llm: bool = True
    allow_web: bool = True

    stt_enabled: bool = True
    stt_model_size: str = "small"
    stt_language: str = "pt"
    stt_device: str = "auto"
    stt_compute_type: str = "auto"
    stt_initial_prompt: str = ""

    wake_word_enabled: bool = False
    wake_words: str = "alpha"

    tts_enabled: bool = True
    tts_voice: str = ""
    tts_speed: float = 1.0

    memory_min_importance: float = 0.70
    rag_top_k: int = 5
    agent_max_tool_iterations: int = 8
    # Timeout por execução de ferramenta: evita que uma tool travada
    # segure o turno do agente indefinidamente.
    agent_tool_timeout_seconds: float = 60.0

    # Seleção de ferramentas por Skill: expõe apenas as ferramentas da(s)
    # skill(s) relacionada(s) ao pedido, em vez de todo o catálogo.
    agent_tool_selection: bool = True
    # Confiança mínima (nº de keywords na descrição) para uma skill ser
    # selecionada. Abaixo do limiar, cai no fallback seguro.
    agent_tool_selection_min_confidence: int = 1
    # Autoriza por padrão ferramentas de escrita (escrever arquivos, teclado,
    # clique, automação) mesmo sem interface de confirmação interativa.
    # Por padrão, sem handler de confirmação o Agent só executa 'read'.
    agent_allow_write_default: bool = False
    # Sem interface de confirmação (ex.: API), ferramentas sensíveis ficam
    # negadas por padrão; habilite apenas se quiser autorização automática.
    agent_auto_approve_sensitive: bool = False
    agent_tool_result_strict: bool = True
    agent_require_tool_verification: bool = False

    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = 15.0

    code_exec_timeout_seconds: float = 30.0
    allow_shell_exec: bool = False

    allowed_directories_env: str = Field(
        default="",
        validation_alias=AliasChoices("ALLOWED_DIRECTORIES", "MANAGED_DIRECTORIES"),
        description="Diretórios permitidos separados por os.pathsep (; no Windows, "
        ": no Linux/macOS)",
    )

    system_prompt_path: Path = Path("app/agent/prompts/system_prompt.pt-BR.txt")

    log_level: str = "INFO"
    debug_sensitive_logging: bool = False

    offline_timeout_seconds: float = 2.5
    llm_timeout_seconds: float = 120.0
    web_timeout_seconds: float = 10.0

    use_sqlite_for_tests: bool = False

    @property
    def allowed_directories(self) -> list[Path]:
        if self.allowed_directories_env.strip():
            resolved: list[Path] = []
            seen: set[str] = set()
            for raw in self.allowed_directories_env.split(os.pathsep):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    path = Path(raw).expanduser().resolve()
                except OSError:
                    continue
                if str(path) in seen:
                    continue
                seen.add(str(path))
                resolved.append(path)
            return resolved
        return _default_allowed_directories()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
