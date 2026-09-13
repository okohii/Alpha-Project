from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.assistant.entities import SITE_MARKERS
from app.security.permissions import SecurityLevel
from app.skills.registry import SkillRegistry

DIRECT_INTENTS = frozenset(
    {"greeting", "thanks", "farewell", "direct_question", "direct_info"}
)

_OUI_SIMPLE = (
    "oi", "olá", "ola", "opa", "e ai", "e aí", "bom dia", "boa tarde",
    "boa noite", "salve", "hey",
)
_THANK_SIMPLE = ("obrigado", "obrigada", "valeu", "grato", "agradeço")
_FAREWELL_SIMPLE = ("tchau", "adeus", "até logo", "ate logo", "até mais", "ate mais")
_QUESTION_SIMPLE = (
    "o que é", "o que significa", "qual é", "como funciona", "quem é",
    "onde fica", "quando é",
)
_STOP_WORDS = {"oi", "olá", "ola", "obrigado", "obrigada", "tchau", "adeus"}
_ACTION_VERBS = (
    "pesquisar", "procurar", "abra", "abrir", "abre", "enviar", "manda",
    "criar", "agendar", "lembrar", "abrir o",
)


@dataclass(slots=True)
class Request:
    """A entrada bruta do usuário + identificação de conversa."""

    text: str
    conversation_id: str | None = None


@dataclass(slots=True)
class Intent:
    """Representação interna estruturada para a etapa de compreensão."""

    name: str
    entities: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_reason: str | None = None
    risk_level: SecurityLevel = SecurityLevel.low
    suggested_skill: str | None = None
    direct_response: str | None = None

    def copy_base(self) -> Intent:
        return Intent(
            name=self.name,
            confidence=max(self.confidence, 0.9),
            risk_level=self.risk_level,
            suggested_skill=self.suggested_skill,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entities": dict(self.entities),
            "confidence": self.confidence,
            "needs_clarification": self.needs_clarification,
            "clarification_reason": self.clarification_reason,
            "risk_level": self.risk_level.value,
            "suggested_skill": self.suggested_skill,
            "direct_response": self.direct_response,
        }


@dataclass(slots=True)
class Task:
    """Etapa de execução derivada do Goal — hint + entidades + permissão."""

    tool_hint: str
    entities: dict[str, str] = field(default_factory=dict)
    required_permission: str = "read"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_hint": self.tool_hint,
            "entities": dict(self.entities),
            "required_permission": self.required_permission,
        }


@dataclass(slots=True)
class Goal:
    """Objetivo estruturado entregue à camada de planejamento/execução."""

    intent: Intent
    tasks: list[Task] = field(default_factory=list)
    original_text: str = ""
    priority: str = "normal"
    state: str = "pending"
    expected_result: str | None = None
    id: str = field(default_factory=lambda: f"goal-{uuid4().hex[:12]}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "intent": self.intent.to_dict(),
            "tasks": [task.to_dict() for task in self.tasks],
            "original_text": self.original_text,
            "priority": self.priority,
            "state": self.state,
            "expected_result": self.expected_result,
        }


_RISK_BY_SKILL: dict[str, SecurityLevel] = {
    "shell": SecurityLevel.high,
    "tasks": SecurityLevel.medium,
    "documents": SecurityLevel.medium,
}


class IntentDetector:
    """Detecta Intent determinístico sem executar tools ou decidir segurança."""

    def __init__(self, skill_registry: SkillRegistry | None = None) -> None:
        self.skill_registry = skill_registry

    def detect(self, request: Request) -> Intent:
        text = request.text.strip()
        lowered = text.lower()
        directive = self._detect_direct(lowered)
        if directive is not None:
            return directive

        intent_name, score, skill_name = self._detect_via_skill(text)
        confidence = self._confidence(score)
        if skill_name is not None and self._is_weak_selection(text):
            confidence = 0.2
        return Intent(
            name=intent_name,
            confidence=confidence,
            suggested_skill=skill_name,
            risk_level=_RISK_BY_SKILL.get(skill_name or "", SecurityLevel.low),
        )

    def _detect_direct(self, lowered: str) -> Intent | None:
        if _matches_any(lowered, _OUI_SIMPLE):
            return Intent(
                name="greeting", confidence=0.99, direct_response="Oi! No que posso ajudar?"
            )
        if _matches_any(lowered, _THANK_SIMPLE):
            return Intent(
                name="thanks",
                confidence=0.99,
                direct_response="De nada! Sempre que precisar, é só chamar.",
            )
        if _matches_any(lowered, _FAREWELL_SIMPLE):
            return Intent(name="farewell", confidence=0.99, direct_response="Até logo!")
        if any(q in lowered for q in _QUESTION_SIMPLE):
            return Intent(name="direct_question", confidence=0.9)
        if _is_direct_info(lowered):
            return Intent(name="direct_info", confidence=0.85)
        return None

    def _detect_via_skill(self, text: str) -> tuple[str, int, str | None]:
        if self.skill_registry is None:
            return "generic", 0, None
        ranked = self.skill_registry.rank_skills_for_task(text)
        if not ranked:
            return "generic", 0, None
        top_skill, score = ranked[0]
        skill_name = top_skill.name.lower()
        return _intent_for_skill(skill_name, text), score, skill_name

    @staticmethod
    def _confidence(score: int) -> float:
        return round(min(1.0, 0.45 + score * 0.18), 2)

    def _is_weak_selection(self, text: str) -> bool:
        if self.skill_registry is None:
            return False
        return not self.skill_registry.select_skills_for_task(text, 1)


def _intent_for_skill(skill: str, text: str) -> str:
    lowered = text.lower()
    if skill == "web":
        return "web_search"
    if skill == "browser":
        return "browser_navigate" if any(site in lowered for site in SITE_MARKERS) else "browser_web"
    if skill == "files":
        return "file_read" if any(
            token in lowered for token in ("ler", "leia", "mostrar", "mostre", "abrir arquivo")
        ) else "file_access"
    if skill == "documents":
        return "document_search"
    if skill == "computer":
        return "gui_action" if any(
            token in lowered for token in ("clicar", "clique", "teclado", "digit", "mouse")
        ) else "app_open"
    if skill == "memory":
        return "memory_delete" if any(
            token in lowered for token in ("esqueç", "esque", "apague", "remova")
        ) else "memory_save"
    if skill == "macros":
        return "macro_execute"
    if skill == "shell":
        return "shell_run"
    if skill == "reminders":
        return "reminder_create"
    if skill == "calendar":
        return "calendar_schedule"
    if skill == "tasks":
        return "task_execute"
    if skill == "system":
        return "system_status"
    return "generic"


def _matches_any(lowered: str, terms: tuple[str, ...]) -> bool:
    return any(term in lowered for term in terms)


def _is_direct_info(lowered: str) -> bool:
    if lowered in _STOP_WORDS:
        return True
    compact = lowered.strip().rstrip("?!.")
    if not compact or " " not in compact:
        return not any(verb in lowered for verb in _ACTION_VERBS)
    return False
