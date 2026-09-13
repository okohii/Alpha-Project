from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.assistant.ambiguity import AmbiguityDetector, AmbiguityIssue
from app.assistant.context import ConversationContext, PendingClarification
from app.assistant.entities import Entity, EntityExtractor
from app.assistant.intent import Goal, Intent, IntentDetector, Request, Task
from app.assistant.resolver import EntityResolver
from app.skills.registry import SkillRegistry

# Intents de pergunta simples: NÃO são respondidas com resposta pronta — vão
# ao LLM para gerar resposta real (Fase 4.1), sem expor ferramentas.
LLM_ANSWER_INTENTS = frozenset({"direct_question", "direct_info"})

# Conectores de passos para decomposição multi-step (Fase 4.2). Ao dividir,
# cada segmento vira uma Task; se qualquer segmento for irresolvível, cai para
# o Goal de um passo (comportamento seguro anterior).
_CONNECTOR_RE = re.compile(
    r"\s+(?:e\s+depois|em\s+seguida|e\s+tamb[ée]m|ent[aã]o|na\s+sequ[êe]ncia|e)\s+",
    re.IGNORECASE,
)

# Mapa intent -> (tool_hint, permissão sugerida). A permissão é INFORMATIVA;
# a autorização real continua no gate do AgentCore.
_TASK_HINT: dict[str, tuple[str, str]] = {
    "web_search": ("web_search", "read"),
    "browser_navigate": ("open_url", "read"),
    "browser_web": ("browser_open", "read"),
    "file_read": ("file_read", "read"),
    "file_access": ("file_search", "read"),
    "document_search": ("document_search", "read"),
    "app_open": ("open_app", "write"),
    "gui_action": ("type_text", "write"),
    "memory_save": ("memory_save", "write"),
    "memory_delete": ("memory_delete", "write"),
    "macro_execute": ("macro_run", "sensitive"),
    "shell_run": ("run_shell", "sensitive"),
    "reminder_create": ("reminder_create", "write"),
    "calendar_schedule": ("calendar_create", "write"),
    "task_execute": ("task_execute", "write"),
    "system_status": ("system_info", "read"),
}

OutcomeKind = Literal["direct", "clarification", "goal", "llm_answer"]


@dataclass(slots=True)
class FacilitatorOutcome:
    """Resultado do Facilitator: resposta direta, pergunta ou Goal p/ Agent."""

    kind: OutcomeKind
    response: str | None = None
    intent: Intent | None = None
    goal: Goal | None = None


class AssistantFacilitator:
    """Camada COMPREENDER: separa entendimento de execução.

    Responsabilidades:
    - CONVERTE ``Request -> Intent -> Goal -> Task`` (representação estruturada,
      nunca linguagem natural como artefato interno);
    - responde direto a cumprimentos/perguntas simples (fast path, sem LLM e
      sem tools);
    - detecta ambiguidades e pede esclarecimento humano.

    NUNCA executa tools, NUNCA decide segurança e NUNCA substitui o Agent:
    todo trabalho real é entregue como ``Goal`` para a camada EXECUTA.
    """

    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        context: ConversationContext | None = None,
    ) -> None:
        self.skill_registry = skill_registry
        self.context = context or ConversationContext()
        self.intent_detector = IntentDetector(skill_registry=skill_registry)
        self.extractor = EntityExtractor()
        self.resolver = EntityResolver(self.context)
        self.ambiguity = AmbiguityDetector()

    async def process(self, request: Request) -> FacilitatorOutcome:
        conversation_id = request.conversation_id
        pending = self.context.pending(conversation_id)
        is_answer = pending is not None and self.resolver.looks_like_answer(request.text)

        if is_answer:
            # Continuidade: a resposta preenche o slot pendente do INTENT
            # anterior (não cria intent novo a partir da resposta). Quem limpa
            # a pendência é o resolver, após consumir a resposta.
            intent = pending.previous_intent.copy_base()
        else:
            if pending is not None:
                self.context.clear_pending(conversation_id)  # novo tópico
            intent = self.intent_detector.detect(request)

        if intent.direct_response is not None:
            # Fast path: cumprimentos/despedidas — sem LLM, sem tools.
            return FacilitatorOutcome(kind="direct", response=intent.direct_response, intent=intent)

        detected = self.extractor.extract(request.text)
        resolved, unresolved = self.resolver.resolve(
            request.text, detected, conversation_id
        )
        intent.entities = {name: entity.value for name, entity in resolved.items()}
        # Um referente resolvido entrega o alvo do intent (ex.: a query da busca).
        if intent.name == "web_search" and "referent" in intent.entities:
            intent.entities["query"] = intent.entities["referent"]

        # Multi-step (Fase 4.2): se a frase tem conectores, tenta decompor em
        # Tasks ANTES da ambiguidade do texto inteiro — cada segmento é avaliado
        # isoladamente; qualquer falha cai no fluxo de um passo.
        if _CONNECTOR_RE.search(request.text):
            multi = self._try_multi(request, intent)
            if multi is not None:
                self.context.remember(conversation_id, intent, resolved)
                return FacilitatorOutcome(kind="goal", intent=intent, goal=multi)

        # Avalia a ambiguidade sobre o estado COMPLETO (resolvido + pendente).
        all_entities = dict(resolved)
        all_entities.update(
            {name: Entity(name, value, resolved=False) for name, value in unresolved.items()}
        )
        issue = self.ambiguity.evaluate(intent, all_entities, self.context, conversation_id)
        if issue is not None:
            return self._clarify(request, intent, issue)

        if intent.name in LLM_ANSWER_INTENTS:
            # Pergunta factual ("qual é a capital do Brasil?"): resposta REAL
            # do LLM, sem tools e sem planejamento (Fase 4.1).
            self.context.remember(conversation_id, intent, resolved)
            return FacilitatorOutcome(kind="llm_answer", intent=intent)

        if intent.name == "generic" or intent.suggested_skill is None:
            # Sem skill: conversa simples sem tool — responde direto (sem
            # planejamento), mantendo o fluxo rápido.
            self.context.remember(conversation_id, intent, resolved)
            return FacilitatorOutcome(
                kind="direct",
                response=_generic_response(intent.name),
                intent=intent,
            )

        goal = self._build_goal(intent)
        self.context.remember(conversation_id, intent, resolved)
        return FacilitatorOutcome(kind="goal", intent=intent, goal=goal)

    def _clarify(
        self, request: Request, intent: Intent, issue: AmbiguityIssue
    ) -> FacilitatorOutcome:
        intent.needs_clarification = True
        intent.clarification_reason = issue.reason
        question = f"{issue.reason.rstrip('.?!; ')}. Pode esclarecer?"
        self.context.set_pending(
            request.conversation_id,
            PendingClarification(
                question=question,
                reason=issue.reason,
                missing={issue.missing: issue.reason},
                previous_intent=intent,
            ),
        )
        return FacilitatorOutcome(
            kind="clarification", response=question, intent=intent
        )

    def _build_goal(self, intent: Intent) -> Goal:
        hint, permission = _TASK_HINT.get(intent.name, (intent.name, "read"))
        task = Task(
            tool_hint=hint,
            entities=dict(intent.entities),
            required_permission=permission,
        )
        return Goal(intent=intent, tasks=[task])

    def _try_multi(self, request: Request, intent: Intent) -> Goal | None:
        """Decomposição multi-step com verificação de ambiguidade POR segmento.

        Só retorna Goal multi-task quando TODOS os segmentos mapeiam para um
        intent acionável, com entidades resolvidas e sem ambiguidade; caso
        contrário ``None`` (fallback seguro para o Goal de um passo).
        """
        parts = [part.strip() for part in _CONNECTOR_RE.split(request.text) if part.strip()]
        if len(parts) < 2:
            return None
        tasks: list[Task] = []
        for part in parts:
            segment = self.intent_detector.detect(Request(text=part, conversation_id=request.conversation_id))
            if segment.name == "generic" or segment.suggested_skill is None or segment.name in LLM_ANSWER_INTENTS:
                return None
            detected = self.extractor.extract(part)
            try:
                resolved, unresolved_map = self.resolver.resolve(part, detected, request.conversation_id)
            except Exception:  # noqa: BLE001 - preserva fallback conservador
                return None
            all_entities = dict(resolved)
            all_entities.update(
                {
                    name: Entity(name, value, resolved=False)
                    for name, value in unresolved_map.items()
                }
            )
            if self.ambiguity.evaluate(segment, all_entities, self.context, request.conversation_id) is not None:
                return None
            hint, permission = _TASK_HINT.get(segment.name, (segment.name, "read"))
            tasks.append(
                Task(
                    tool_hint=hint,
                    entities={name: entity.value for name, entity in resolved.items() if entity.resolved},
                    required_permission=permission,
                )
            )
        if not tasks:
            return None
        return Goal(intent=intent, tasks=tasks, original_text=request.text)


def _generic_response(intent_name: str) -> str:
    if intent_name == "generic":
        return "Entendi. Em que mais posso ajudar?"
    return "Certo. Continue, por favor."


def format_goal_context(goal: Goal) -> str:
    """Serializa o Goal como bloco estruturado para o Agent.

    Mantém a representação estruturada (não linguagem natural livre): o modelo
    recebe os fatos resolvidos, mas a decisão de execução continua no gate.
    """
    intent = goal.intent
    lines = [
        "PLANO ESTRUTURADO DO FACILITADOR (fatos autorizados, não suposições):",
        f"- intent: {intent.name}",
        f"- confiança: {intent.confidence}",
        f"- skill sugerida: {intent.suggested_skill or 'nenhuma'}",
    ]
    if intent.entities:
        lines.append("- entidades resolvidas:")
        for name, value in intent.entities.items():
            lines.append(f"    {name}: {value}")
    for task in goal.tasks:
        lines.append(f"- etapa: {task.tool_hint} (permissão {task.required_permission})")
    return "\n".join(lines)