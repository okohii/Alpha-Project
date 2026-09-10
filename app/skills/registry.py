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
        matches = self.skills_for_task(task_description)
        return matches[0] if matches else None

    def skills_for_task(self, task_description: str) -> list[Skill]:
        """Retorna todas as skills cujas palavras-chave casam com o pedido."""
        normalized = (task_description or "").lower()
        matches: list[Skill] = []
        seen: set[str] = set()
        for resolver in self._resolvers:
            match = resolver(normalized)
            if match and match.lower() not in seen:
                skill = self._skills.get(match.lower())
                if skill is not None:
                    matches.append(skill)
                    seen.add(skill.name.lower())
        for skill in self._skills.values():
            if skill.name.lower() in seen:
                continue
            if any(keyword in normalized for keyword in _skill_keywords(skill)):
                matches.append(skill)
                seen.add(skill.name.lower())
        return matches

    def best_skill_for_task(self, task_description: str) -> Skill | None:
        """Retorna a skill com MAIS keywords casando (desambiguação).
        
        Se houver empate entre skills, retorna None para sinalizar que o chamador
        deve usar ferramentas de TODAS as skills empatadas no topo.
        """
        skills = self.skills_for_task(task_description)
        if not skills:
            return None
        if len(skills) == 1:
            return skills[0]
        # Conta matches por skill (usa nome como chave)
        normalized = (task_description or "").lower()
        scores: dict[str, int] = {}
        for skill in skills:
            scores[skill.name] = sum(1 for kw in _skill_keywords(skill) if kw in normalized)
        max_score = max(scores.values())
        top_names = [name for name, sc in scores.items() if sc == max_score]
        if len(top_names) == 1:
            return self._skills[top_names[0].lower()]
        # Empate no topo: retorna None para o chamador combinar as top skills
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
            "navegador", "site", "url", "chrome", "edge", "firefox", "brave",
            "github", "youtube", "youtu.be", "web", "página", "pagina",
            "whatsapp", "web.whatsapp", "teams", "teams.microsoft", "teams.live",
            "slack", "discord", "telegram", "instagram", "facebook", "twitter",
            "x.com", "linkedin", "gmail", "outlook", "drive.google", "google drive",
            "netflix", "prime video", "primevideo", "spotify", "twitch",
        ],
        "files": [
            "arquivo", "pasta", "diretório", "diretorio",
            "download", "documento", "abrir arquivo", "ler arquivo",
        ],
        "documents": ["indexar", "documento", "pesquisar documento", "buscar documento"],
        "computer": [
            "abrir aplicativo", "abrir programa", "abrir app", "fechar aplicativo",
            "fechar programa", "janela", "monitor", "atalho", "instalado",
            "clicar", "teclado", "mouse", "print", "screenshot", "digitar",
            # Apps conhecidos que podem ser desktop OU web:
            "whatsapp", "teams", "slack", "discord", "telegram", "zoom", "skype",
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
        "reminders": [
            "lembrete", "lembrar", "lembra", "lembre",
            " às 1", " daqui a", "todo dia", "daqui",
            "agendar", "agenda",
        ],
        "calendar": ["agenda", "reunião", "reuniao", "compromisso", "evento"],
        "tasks": ["tarefa", "executar", "rotina", "agendar tarefa"],
        "shell": ["terminal", "comando de shell", "script", "código", "codigo"],
    }
    return keywords.get(skill.name.lower(), [skill.name.lower()])