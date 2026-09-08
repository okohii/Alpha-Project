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
