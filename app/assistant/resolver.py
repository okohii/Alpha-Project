from __future__ import annotations

import re

from app.assistant.context import ConversationContext
from app.assistant.entities import Entity

# Palavras que indicam que o usuário está RESPONDENDO a um esclarecimento
# pendente ("para Maria", "é o relatório", etc.), deixando de ser um novo
# intent.
_RESPONSE_MARKERS = re.compile(
    r"^\s*(é|e|para|pra|pro|pra|ao|à|seria|pode ser|certo|sim|o|a)\s+", re.IGNORECASE
)


class EntityResolver:
    """Preenche entidades usando contexto estruturado e respostas pendentes.

    NUNCA inventa valores: preenche apenas a partir de (1) entidades já
    confirmadas na conversa, ou (2) a resposta literal do usuário a uma
    pergunta de esclarecimento pendente.
    """

    def __init__(self, context: ConversationContext) -> None:
        self.context = context

    def resolve(
        self,
        text: str,
        detected: dict[str, Entity],
        conversation_id: str,
    ) -> tuple[dict[str, Entity], dict[str, str]]:
        """Retorna (entidades resolvidas, entidades ainda não resolvidas)."""
        resolved: dict[str, Entity] = {}
        unresolved: dict[str, str] = {}

        pending = self.context.pending(conversation_id)
        if pending is not None and self.looks_like_answer(text):
            self._fill_from_answer(text, pending.missing, resolved)
            self.context.clear_pending(conversation_id)

        context_entities = self.context.entities(conversation_id)

        for name, entity in detected.items():
            if entity.resolved:
                resolved[name] = entity
                continue
            # Referente não resolvido: tenta preencher a partir do que a
            # conversa já estabeleceu (ex.: "isso" -> último objeto/quem).
            if name == "referent" and context_entities:
                candidate = self._resolve_referent_from_context(context_entities)
                if candidate is not None:
                    resolved["referent"] = candidate
                    continue
            unresolved[name] = entity.value

        for name, entity in context_entities.items():
            if entity.resolved and name not in resolved:
                resolved.setdefault(name, entity)

        # Um contato citado é tratado como não-resolvido até ser confirmado;
        # se já existe confirmado na conversa, usa esse.
        if "contact" in resolved and not resolved["contact"].resolved:
            known = self._known_contact(conversation_id, resolved["contact"].value)
            if known is not None:
                resolved["contact"] = known

        return resolved, unresolved

    @staticmethod
    def looks_like_answer(text: str) -> bool:
        """Distingue resposta a um esclarecimento pendente de novo intent."""
        return bool(_RESPONSE_MARKERS.match(text.strip()))

    def _fill_from_answer(
        self, text: str, missing: dict[str, str], resolved: dict[str, Entity]
    ) -> None:
        cleaned = text.strip()
        prev = None
        while cleaned != prev:
            prev = cleaned
            cleaned = _RESPONSE_MARKERS.sub("", cleaned).strip()
        cleaned = cleaned.strip(".,!?")
        if not cleaned:
            return
        # Resposta genérica preenche o primeiro slot pendente; se houver
        # múltiplos, o texto literal vira o valor do slot mais genérico
        # ("refere-se ao quê").
        slot = next(iter(missing)) if missing else "referent"
        resolved[slot] = Entity(slot, cleaned, source="resposta")

    @staticmethod
    def _resolve_referent_from_context(context_entities: dict[str, Entity]) -> Entity | None:
        # Prioridade: slot mais recente que não seja idêntico ao referente.
        for name in ("query", "app", "browser", "path", "command", "contact", "object"):
            entity = context_entities.get(name)
            if entity is not None and entity.resolved:
                return entity
        return None

    def _known_contact(self, conversation_id: str, value: str) -> Entity | None:
        prior = self.context.entities(conversation_id).get("contact")
        if prior is not None and prior.resolved and prior.value.lower() == value.lower():
            return prior
        return None