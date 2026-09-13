from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.skills.base import Skill

logger = logging.getLogger("app.skills.registry")


class SkillNotFoundError(KeyError):
    pass


class SkillRegistry:
    """Registra skills (grupos de ferramentas) e resolve a skill adequada para uma tarefa.

    Separa as fases:
      1. **Descoberta** — ``discover_skills_for_task()`` encontra candidatas
         amplas (keywords + resolvers custom).
      2. **Seleção** — ``select_skills_for_task()`` filtra por confiança e
         desempate, devolvendo apenas as que realmente devem ser expostas ao LLM.

    Cada Skill define seus próprios ``keywords`` — a lista não é mais
    hardcodada neste módulo.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._resolvers: list[Callable[[str], str | None]] = []
        self._tool_to_skill: dict[str, str] = {}

    # ── cadastro ────────────────────────────────────────────────────────

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

    # ── validação ───────────────────────────────────────────────────────

    def validate_tools(self, available_tools: dict[str, Any]) -> list[str]:
        """Verifica se todas as tools referenciadas pelas skills existem.

        Retorna lista de nomes de tools ausentes (vazia = tudo ok).
        """
        missing: list[str] = []
        for skill in self._skills.values():
            for tool_name in skill.tools:
                if tool_name not in available_tools:
                    missing.append(f"{skill.name} → {tool_name}")
        return missing

    # ── descoberta ──────────────────────────────────────────────────────

    def discover_skills_for_task(self, task_description: str) -> list[Skill]:
        """Encontra TODAS as skills potencialmente relevantes (fase ampla).

        Combina resolvers custom e keywords da própria skill.
        Retorna todas as que pontuaram ≥ 1, sem filtro de confiança.
        """
        ranked = self.rank_skills_for_task(task_description)
        return [skill for skill, score in ranked if score >= 1]

    # ── seleção ─────────────────────────────────────────────────────────

    def find_for_task(self, task_description: str) -> Skill | None:
        matches = self.skills_for_task(task_description)
        return matches[0] if matches else None

    def skills_for_task(self, task_description: str) -> list[Skill]:
        """Retorna TODAS as skills cujas keywords casam, por relevância."""
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
            hits = sum(1 for kw in skill.keywords if kw in normalized)
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

    # ── ferramentas ─────────────────────────────────────────────────────

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

    # ── confiança ───────────────────────────────────────────────────────

    def confidence_for_task(
        self,
        task_description: str,
        min_confidence: int = 1,
    ) -> str:
        """Classifica a confiança da seleção de skills para a tarefa.

        Retorna:
          "alta"   – forte sinal (score ≥ 2) ou múltiplas skills com bom score;
          "media"  – skill única com exatamente min_confidence;
          "baixa"  – piso fraco (empate no score 1) ou nenhum sinal;
          "nenhuma"– nenhum skill casou.
        """
        ranked = self.rank_skills_for_task(task_description)
        if not ranked:
            return "nenhuma"
        top_score = ranked[0][1]
        if top_score < min_confidence:
            return "baixa"
        matched = [skill for skill, score in ranked if score >= 1]
        if len(matched) == 1 and top_score == min_confidence:
            return "media"
        if len(matched) > 1 and all(score == 1 for _, score in ranked):
            return "baixa"
        return "alta"

    def as_dict(self) -> dict[str, Any]:
        return {skill.name: list(skill.tools) for skill in self._skills.values()}
