from __future__ import annotations

from app.skills.base import Skill

SKILL = Skill(
    name="Memory",
    description="Memória persistente: procurar, salvar, deletar memórias e procedimentos.",
    keywords=[
        "memória", "memoria", "lembrar", "lembra",
        "preferência", "preferencia", "esquecer", "perfil",
        "guardar", "guarde", "guarda", "guardado",
        "registrar", "registre", "anotar", "anote", "memorizar", "memorize",
        "quem é", "quem e", "quem foi",
    ],
    tools=[
        "memory_search",
        "memory_save",
        "memory_delete",
        "procedure_save",
        "procedure_run",
    ],
)

__all__ = ["SKILL"]
