from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

CANCEL_WORDS = ("pare", "para", "cancele", "cancelar", "interrompa", "stop", "halt")


class AgentRoute(StrEnum):
    general = "general"
    memory = "memory"
    documents = "documents"
    web = "web"


@dataclass(slots=True)
class FastPathRule:
    name: str
    skill: str
    tool: str
    patterns: list[re.Pattern[str]]
    extract: Any | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    confirmation: bool = False

    def match(self, text: str) -> dict[str, Any] | None:
        for pattern in self.patterns:
            match = pattern.search(text)
            if not match:
                continue
            arguments = dict(self.arguments)
            if self.extract is not None:
                result = self.extract(match, text)
                if result:
                    arguments.update(result)
            return arguments
        return None


@dataclass(slots=True)
class FastPathMatch:
    intent: str
    tool: str
    skill: str
    arguments: dict[str, Any]
    confirmation: bool = False


class FastPathRouter:
    """Roteador determinístico rápido para intenções simples e recorrentes.

    Mensagens casadas aqui NÃO passam pelo LLM: vão direto à ferramenta,
    reduzindo latência e consumo de contexto.
    """

    def __init__(self, rules: list[FastPathRule] | None = None) -> None:
        self.rules = list(rules or [])
        self._cancelled: set[str] = set()

    def register(self, rule: FastPathRule) -> None:
        self.rules.append(rule)

    def match(self, text: str) -> FastPathMatch | None:
        normalized = (text or "").strip().strip(".,!?;: ")
        if not normalized:
            return None
        for rule in self.rules:
            arguments = rule.match(normalized)
            if arguments is not None:
                return FastPathMatch(
                    intent=rule.name,
                    tool=rule.tool,
                    skill=rule.skill,
                    arguments=arguments,
                    confirmation=rule.confirmation,
                )
        return None

    @staticmethod
    def is_cancel_intent(text: str) -> bool:
        cleaned = (text or "").strip().lower().strip(".,!?;: ")
        return cleaned in CANCEL_WORDS or cleaned.startswith(("pare", "cancele", "interrompa"))


def build_default_fast_path_router() -> FastPathRouter:
    """Regras padrão em pt-BR para intenções determinísticas recorrentes."""

    def url_arg(match, text):
        url = match.group(2).strip()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            url = f"https://{url}"
        return {"url": url}

    def query_arg(match, text):
        return {"query": match.group(2).strip()}

    def file_arg(match, text):
        return {"path": match.group(2)}

    def app_name(match, text):
        return {"app": match.group(2).lower()}

    def folder_name(match, text):
        return {"path": match.group(2).lower()}

    rules: list[FastPathRule] = [
        FastPathRule(
            name="abrir_navegador",
            skill="Browser",
            tool="open_app",
            patterns=[
                re.compile(r"\b(abra|abre|abrir)\s+(?:o\s+)?(chrome|edge|firefox)\b")
            ],
            extract=app_name,
        ),
        FastPathRule(
            name="abrir_navegador_padrao",
            skill="Browser",
            tool="open_app",
            patterns=[
                re.compile(r"\b(abra|abre|abrir)\s+(?:o\s+)?(navegador|browser)\b")
            ],
            extract=lambda match, text: {"app": "chrome"},
        ),
        FastPathRule(
            name="abrir_app",
            skill="Computer",
            tool="open_app",
            patterns=[
                re.compile(
                    r"\b(abra|abre|abrir)\s+(?:o\s+)?"
                    r"(bloco de notas|notepad|calculadora|paint|explorador"
                    r"|discord|spotify|vscode|vs code|excel|word|powerpoint"
                    r"|prime video|valorant)\b"
                )
            ],
            extract=app_name,
        ),
        FastPathRule(
            name="abrir_pasta",
            skill="Files",
            tool="open_file",
            patterns=[
                re.compile(
                    r"\b(abra|abre|abrir)\s+(?:a\s+)?"
                    r"(pasta|diretorio|diretório|downloads|download"
                    r"|documentos|desktop|area de trabalho|área de trabalho"
                    r"|imagens|música|musica|vídeos|videos)\b"
                )
            ],
            extract=folder_name,
        ),
        FastPathRule(
            name="abrir_site",
            skill="Browser",
            tool="open_url",
            patterns=[
                re.compile(
                    r"\b(abra|abre|abrir|entra|entre|entrar)\s+"
                    r"(?:no\s+|no site\s+|no endereço\s+)?"
                    r"([\w.-]+\.[a-z]{2,}(?:/[^\s]*)?"
                    r"|github\.com|youtube\.com)\b"
                )
            ],
            extract=url_arg,
        ),
        FastPathRule(
            name="fechar_app",
            skill="Computer",
            tool="close_app",
            patterns=[
                re.compile(
                    r"\b(fecha|feche|fechar|encerra|encerre)\s+"
                    r"(?:o\s+|a\s+)?"
                    r"(chrome|edge|firefox|navegador|discord|spotify"
                    r"|vscode|bloco de notas)\b"
                )
            ],
            extract=app_name,
        ),
        FastPathRule(
            name="ler_arquivo",
            skill="Files",
            tool="file_read",
            patterns=[
                re.compile(
                    r"\b(leia|ler|lê|le)\s+(?:o\s+|a\s+)?"
                    r"(?:arquivo\s+)?(?:chamado\s+)?"
                    r"([\w.\-]+(?:\.\w+)?)\b"
                )
            ],
            extract=file_arg,
        ),
        FastPathRule(
            name="pesquisar_web",
            skill="Web",
            tool="web_search",
            patterns=[
                re.compile(
                    r"\b(pesquisa|pesquise|procura|procure|busca|busque"
                    r"|veja na web|google)\s+(?:por\s+|sobre\s+)?"
                    r"(.+)$"
                )
            ],
            extract=query_arg,
        ),
        FastPathRule(
            name="lembrar",
            skill="Memory",
            tool="memory_search",
            patterns=[
                re.compile(
                    r"\b(o que eu|o que você|me conta|lembra|levanta"
                    r"|recupera)\s+(?:te falei|disse|falamos"
                    r"|lembra|essa memória)?\s*(.+)$"
                )
            ],
            extract=lambda match, text: {"query": match.group(2).strip() or text},
        ),
        FastPathRule(
            name="hora",
            skill="System",
            tool="time",
            patterns=[
                re.compile(
                    r"\b(que horas são|que horas sao|que hora é"
                    r"|que hora e|hora atual|as horas)\b"
                )
            ],
        ),
        FastPathRule(
            name="print",
            skill="Computer",
            tool="screenshot",
            patterns=[
                re.compile(
                    r"\b(print|tira|tire)\s+(?:um\s+)?"
                    r"(print|print da tela|screenshot|captura de tela|captura)\b"
                )
            ],
        ),
    ]
    return FastPathRouter(rules)