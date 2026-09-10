from __future__ import annotations

from collections import defaultdict
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
        """Retorna TODAS as skills cujas palavras-chave casam, por relevância.

        A ordem é decrescente de pontuação: skills com mais keywords na
        descrição vêm primeiro (resolvers custom têm prioridade em empates).
        """
        return [skill for skill, _ in self.rank_skills_for_task(task_description)]

    def rank_skills_for_task(self, task_description: str) -> list[tuple[Skill, int]]:
        """Skills com pontuação de casamento, ordenada da mais provável.

        Cada resolver custom que casa soma +1; cada keyword presente na
        descrição soma +1. Resolvers são avaliados primeiro (desempate).
        """
        normalized = (task_description or "").lower()
        scores: dict[str, int] = defaultdict(int)
        for resolver in self._resolvers:
            match = resolver(normalized)
            if match and match.lower() in self._skills:
                scores[match.lower()] += 1
        for name, skill in self._skills.items():
            hits = sum(1 for kw in _skill_keywords(skill) if kw in normalized)
            if hits:
                scores[name] += hits
        return sorted(
            ((self._skills[name], score) for name, score in scores.items()),
            key=lambda item: item[1],
            reverse=True,
        )

    def select_skills_for_task(
        self,
        task_description: str,
        min_confidence: int = 1,
    ) -> list[Skill]:
        """Seleção determinística de skills relevantes para a tarefa.

        Retorna as skills que devem ter suas ferramentas expostas ao modelo,
        ou lista vazia quando o fallback seguro deve ser usado:

        - nenhuma skill casou (tarefa genérica/desconhecida);
        - nenhuma skill atingiu ``min_confidence`` (baixa confiança);
        - empate fraco no piso (várias skills com um único hit genérico).
        """
        ranked = self.rank_skills_for_task(task_description)
        if not ranked:
            return []
        if ranked[0][1] < min_confidence:
            return []
        matched = [skill for skill, score in ranked if score >= 1]
        # Empate no piso com várias skills distintas e nenhum sinal forte
        # (score > 1) = baixa confiança -> fallback seguro.
        if len(matched) > 1 and all(score == 1 for _, score in ranked):
            return []
        return matched

    def best_skill_for_task(self, task_description: str) -> Skill | None:
        """Retorna a skill com MAIS keywords casando (desambiguação).
        
        Se houver empate entre skills, retorna None para sinalizar que o chamador
        deve usar ferramentas de TODAS as skills empatadas no topo.
        """
        ranked = self.rank_skills_for_task(task_description)
        if not ranked:
            return None
        top_score = ranked[0][1]
        top = [skill for skill, score in ranked if score == top_score]
        return top[0] if len(top) == 1 else None

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
            "vídeo", "videos", "assistir", "pesquisar no site", "pesquisar no google",
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
            "pesquisar", "pesquisa", "buscar na internet", "procurar", "procura",
            "procure", "busque", "notícia", "noticia", "google", "web",
            "vídeo", "videos", "assistir",
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