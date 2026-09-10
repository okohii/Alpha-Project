from __future__ import annotations

from dataclasses import dataclass

from app.assistant.context import ConversationContext
from app.assistant.entities import Entity
from app.assistant.intent import DIRECT_INTENTS, Intent

# Slots que EXIGEM valor preenchido para o intent ser executável sem
# esclarecimento.
_REQUIRED_ENTITIES: dict[str, tuple[str, ...]] = {
    "web_search": ("query",),
    "browser_navigate": ("browser",),
    "files_read": ("path",),
    "file_read": ("path",),
    "browser_web": ("browser",),
    "app_open": ("app",),
    "macro_execute": ("macro",),
    "shell_run": ("command",),
    "reminder_create": ("when",),
}

_LOW_CONFIDENCE = 0.55

# Slots que um referente resolvido preenche (o valor qui é o objeto da ação).
_REFERENT_TARGET = "query"


@dataclass(slots=True)
class AmbiguityIssue:
    reason: str
    missing: str | None = None


class AmbiguityDetector:
    """Detecta quando o Intent não pode ser executado com segurança.

    Regras (conservadoras): referente não resolvido ("isso", "aí"), contato
    não localizável, entidade obrigatória ausente e baixa confiança. O
    Facilitator pede esclarecimento — nunca chuta valor.
    """

    def evaluate(
        self,
        intent: Intent,
        entities: dict[str, Entity],
        context: ConversationContext,
        conversation_id: str,
    ) -> AmbiguityIssue | None:
        if intent.name in DIRECT_INTENTS:
            return None

        referent = entities.get("referent")
        if referent is not None and not referent.resolved:
            return AmbiguityIssue(
                reason=f"não consigo identificar o que é '{referent.value}': "
                "preciso que você esclareça o que quer dizer.",
                missing="referent",
            )

        contact = entities.get("contact")
        if contact is not None and not contact.resolved:
            return AmbiguityIssue(
                reason=f"não consigo localizar o contato '{contact.value}' com "
                "segurança; confirme para quem devo entregar.",
                missing="contact",
            )

        for entity in entities.values():
            if not entity.resolved and entity.name not in ("referent", "contact"):
                return AmbiguityIssue(
                    reason=f"o valor de '{entity.name}' não pôde ser resolvido.",
                    missing=entity.name,
                )

        required = _REQUIRED_ENTITIES.get(intent.name, ())
        if required:
            present = {entity.name for entity in entities.values() if entity.resolved}
            # Referente resolvido cobre o alvo do intent (ex.: "query" da busca).
            if "referent" in present:
                present.add(_REFERENT_TARGET)
            missing_slots = [slot for slot in required if slot not in present]
            if missing_slots:
                return AmbiguityIssue(
                    reason="faltam informações para executar: "
                    + ", ".join(missing_slots)
                    + ".",
                    missing=missing_slots[0],
                )

        if intent.confidence < _LOW_CONFIDENCE and intent.suggested_skill is not None:
            return AmbiguityIssue(
                reason="não tenho certeza suficiente sobre o que você pediu; "
                "por favor, reformule."
            )

        if intent.name == "generic":
            return AmbiguityIssue(
                reason="não entendi bem o que fazer; pode me explicar melhor?"
            )

        return None