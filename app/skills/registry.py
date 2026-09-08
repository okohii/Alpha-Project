from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.skills.base import Skill


class SkillNotFoundError(KeyError):
    pass


class SkillRegistry:
    """Registra skills (grupos de ferramentas) e resolve a skill adequada para uma tarefa."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._resolvers: list[Callable[[str], str | None]] = []
        self._tool_to_skill: dict[str, str] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name.lower()] = skill
        for tool in skill.tools:
            self._tool_to_skill[tool] = skill.name

    def unregister(self, name: str) -> None:
        skill = self._skills.pop(name.lower(), None)
        if skill is None:
            raise SkillNotFoundError(name)
        for tool in skill.tools:
            self._tool_to_skill.pop(tool, None)

    def get(self, name: str) -> Skill:
        skill = self._skills.get(name.lower())
        if skill is None:
            raise SkillNotFoundError(name)
        return skill

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def add_resolver(self, resolver: Callable[[str], str | None]) -> None:
        self._resolvers.append(resolver)

    def find_for_task(self, task_description: str) -> Skill | None:
        normalized = (task_description or "").lower()
        for resolver in self._resolvers:
            match = resolver(normalized)
            if match:
                return self._skills.get(match.lower())
        for skill in self._skills.values():
            if any(keyword in normalized for keyword in _skill_keywords(skill)):
                return skill
        return None

    def skill_for_tool(self, tool_name: str) -> str | None:
        return self._tool_to_skill.get(tool_name)

    def get_tools_for_skills(self, skills: list[str]) -> list[str]:
        tools: list[str] = []
        seen: set[str] = set()
        for name in skills:
            skill = self._skills.get(name.lower())
            if skill is None:
                continue
            for tool in skill.tools:
                if tool not in seen:
                    seen.add(tool)
                    tools.append(tool)
        return tools

    def as_dict(self) -> dict[str, Any]:
        return {skill.name: list(skill.tools) for skill in self._skills.values()}


def _skill_keywords(skill: Skill) -> list[str]:
    keywords: dict[str, list[str]] = {
        "browser": [
            "navegador", "site", "url", "chrome", "edge",
            "github", "youtube", "web", "página", "pagina",
        ],
        "files": [
            "arquivo", "pasta", "diretório", "diretorio",
            "download", "documento", "abrir arquivo", "ler arquivo",
        ],
        "documents": ["indexar", "documento", "pesquisar documento", "buscar documento"],
        "computer": [
            "abrir", "fechar", "aplicativo", "app", "janela",
            "clicar", "teclado", "mouse", "print", "screenshot",
        ],
        "memory": [
            "memória", "memoria", "lembrar", "lembra",
            "preferência", "preferencia", "esquecer", "perfil",
        ],
        "web": [
            "pesquisar", "pesquisa", "buscar na internet",
            "notícia", "noticia", "google", "web",
        ],
        "system": ["hora", "status", "sistema", "configuração", "configuracao", "tempo"],
    }
    return keywords.get(skill.name.lower(), [skill.name.lower()])