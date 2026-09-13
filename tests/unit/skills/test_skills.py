from __future__ import annotations

from app.skills.base import Skill
from app.skills.catalog import build_default_skill_registry
from app.skills.registry import SkillNotFoundError, SkillRegistry


def test_registry_register_get_list():
    registry = SkillRegistry()
    registry.register(Skill(name="Files", description="arquivos", tools=["file_read"]))
    assert registry.get("files").name == "Files"
    assert [s.name for s in registry.list()] == ["Files"]


def test_registry_get_missing_raises():
    registry = SkillRegistry()
    try:
        registry.get("nao-existe")
    except SkillNotFoundError:
        assert True
    else:
        raise AssertionError("esperava SkillNotFoundError")


def test_registry_unregister():
    registry = SkillRegistry()
    registry.register(Skill(name="Web", description="web", tools=["web_search"]))
    registry.unregister("web")
    assert registry.list() == []
    assert registry.skill_for_tool("web_search") is None


def test_registry_skill_for_tool():
    registry = SkillRegistry()
    registry.register(Skill(name="Memory", description="mem", tools=["memory_search"]))
    assert registry.skill_for_tool("memory_search") == "Memory"


def test_registry_get_tools_for_skills():
    registry = SkillRegistry()
    registry.register(
        Skill(name="Computer", description="pc", tools=["open_app", "close_app"])
    )
    registry.register(Skill(name="System", description="sys", tools=["time"]))
    tools = registry.get_tools_for_skills(["computer", "system"])
    assert set(tools) == {"open_app", "close_app", "time"}


def test_registry_find_for_task_by_keyword():
    registry = build_default_skill_registry()
    skill = registry.find_for_task("pode abrir uma pasta para mim?")
    assert skill is not None
    assert skill.name == "Files"


def test_registry_find_for_task_custom_resolver():
    registry = SkillRegistry()
    registry.register(Skill(name="X", description="x", tools=["x_tool"]))
    registry.add_resolver(lambda text: "X" if "segredo" in text else None)
    assert registry.find_for_task("qual é o segredo?") is not None
    assert registry.find_for_task("outra coisa") is None


def test_default_registry_has_expected_skills():
    registry = build_default_skill_registry()
    names = {skill.name for skill in registry.list()}
    assert {"Browser", "Files", "Documents", "Computer", "Memory", "Web", "System"} <= names


def test_default_registry_maps_known_tools_to_skills():
    registry = build_default_skill_registry()
    assert registry.skill_for_tool("web_search") == "Web"
    assert registry.skill_for_tool("file_read") == "Files"
    assert registry.skill_for_tool("open_app") == "Computer"


def test_rank_skills_for_task_sorts_by_score():
    registry = build_default_skill_registry()
    ranked = registry.rank_skills_for_task("liste os arquivos da minha pasta downloads")
    assert ranked
    top_skill, top_score = ranked[0]
    assert top_skill.name == "Files"
    assert top_score >= 3
    scores = [score for _, score in ranked]
    assert scores == sorted(scores, reverse=True)


def test_select_skills_for_task_clear_winner():
    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task("liste os arquivos da pasta downloads")
    assert [s.name for s in skills] == ["Files"]


def test_select_skills_for_task_compound_browser_web():
    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task(
        "Abra o YouTube e procure vídeos de Python."
    )
    assert {s.name for s in skills} == {"Browser", "Web"}


def test_select_skills_for_task_no_match_returns_empty():
    registry = build_default_skill_registry()
    assert registry.select_skills_for_task("conte uma piada divertida") == []


def test_select_skills_for_task_low_confidence_weak_tie():
    registry = build_default_skill_registry()
    # "documento" casa com Files e Documents num único hit cada -> ambíguo.
    assert registry.select_skills_for_task("preciso encontrar um documento") == []


def test_select_skills_for_task_min_confidence_gate():
    registry = build_default_skill_registry()
    # "hora" só casa com System (1 hit).
    assert [s.name for s in registry.select_skills_for_task("que horas são?")] == ["System"]
    # Com min_confidence=2, um único hit é tratado como baixa confiança.
    assert registry.select_skills_for_task("que horas são?", min_confidence=2) == []


def test_confidence_for_task_alta():
    registry = build_default_skill_registry()
    # "liste os arquivos da pasta downloads" → Files com múltiplos keywords.
    assert registry.confidence_for_task("liste os arquivos da pasta downloads") == "alta"


def test_confidence_for_task_alta_compound():
    registry = build_default_skill_registry()
    # Compound (browser + web) both with strong signals.
    assert registry.confidence_for_task("abra o youtube e procure videos de python") == "alta"


def test_confidence_for_task_media():
    registry = build_default_skill_registry()
    # "que horas são?" → System, 1 hit = exactly min_confidence.
    assert registry.confidence_for_task("que horas são?") == "media"


def test_confidence_for_task_baixa_weak_tie():
    registry = build_default_skill_registry()
    # "preciso encontrar um documento" → weak tie Files + Documents.
    assert registry.confidence_for_task("preciso encontrar um documento") == "baixa"


def test_confidence_for_task_nenhuma():
    registry = build_default_skill_registry()
    assert registry.confidence_for_task("conte uma piada divertida") == "nenhuma"


def test_select_skills_for_task_macro_single():
    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task("quais macros estão configuradas?")
    assert [s.name for s in skills] == ["Macros"]


def test_select_skills_for_task_memory_reminders_compound():
    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task("lembrar de comprar pão amanhã às 10")
    assert {s.name for s in skills} == {"Memory", "Reminders"}


def test_validate_tools_reports_missing():
    registry = build_default_skill_registry()
    # Provide a subset of tools (no document_search, no macro_run).
    subset = {"web_search": None, "file_read": None, "time": None}
    missing = registry.validate_tools(subset)
    # At least document_search and macro_run should appear.
    assert any("Documents" in m for m in missing)
    assert any("Macros" in m for m in missing)


def test_validate_tools_returns_empty_when_all_present():
    registry = SkillRegistry()
    registry.register(Skill(name="X", description="x", tools=["a", "b"]))
    assert registry.validate_tools({"a": None, "b": None, "c": None}) == []
