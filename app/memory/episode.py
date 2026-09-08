from __future__ import annotations

from collections.abc import Iterable

PROFILE_MARKERS = (
    "eu sou",
    "meu nome",
    "me chamo",
    "sou o",
    "sou a",
    "trabalho com",
    "sou desenvolvedor",
    "sou dev",
    "sou programador",
    "eu trabalho",
    "meu computador",
    "minha máquina",
    "uso windows",
    "sistema operacional",
    "me apresento",
)

PREFERENCE_MARKERS = (
    "sempre",
    "nunca",
    "prefiro",
    "preferência",
    "preferencia",
    "gosto de",
    "costumo",
    "não quero",
    "nao quero",
    "não gosto",
    "quando eu",
    "toda vez que",
    "todo dia",
    "meu padrão",
    "minha regra",
)

PROCEDURE_MARKERS = (
    "rotina",
    "procedimento",
    "fluxo de",
    "passo a passo",
    "sempre que eu",
    "automatiza",
    "automatize",
    "script de",
)


def detect_kind(content: str) -> str:
    """Classifica o texto em perfil, procedimento, preferencia ou semantic."""
    lowered = content.lower()
    if any(marker in lowered for marker in PROCEDURE_MARKERS):
        return "procedimento"
    if any(marker in lowered for marker in PROFILE_MARKERS):
        return "perfil"
    if any(marker in lowered for marker in PREFERENCE_MARKERS):
        return "preferencia"
    return "semantic"


def build_episode_memory(
    user_message: str,
    response: str,
    tool_names: Iterable[str],
    max_len: int = 220,
) -> str:
    """Constrói um episódio com fatos verificáveis: pedido e ferramentas executadas.

    A resposta do modelo NÃO é gravada: ela pode conter alegações não confirmadas
    de ações (ex.: "perfil aberto"), que voltariam ao contexto como se fossem
    fatos e alimentariam alucinações.
    """
    tools = ", ".join(tool_names) if tool_names else "sem ferramentas"
    episode = (
        f"Episódio: usuário pediu \u201c{user_message[:max_len]}\u201d | "
        f"ações executadas: {tools}"
    )
    return episode