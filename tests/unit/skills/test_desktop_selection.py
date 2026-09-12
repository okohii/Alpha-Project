"""Seleção de skill/tool para a tarefa desktop 'abrir bloco de notas'.

Garante que SkillRegistry selecione Computer e que apenas as ferramentas
compatíveis (skill + permissões da sessão) sejam expostas ao LLM — sem
vazar tool de browser/files/web/etc.
"""
from __future__ import annotations

from app.skills.catalog import build_default_skill_registry
from app.skills.registry import SkillRegistry


def test_desktop_task_selects_computer_skill():
    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task("abrir bloco de notas")
    assert [skill.name for skill in skills] == ["Computer"]
    assert registry.skill_for_tool("open_app") == "Computer"


def test_desktop_task_variants_select_computer_skill():
    registry = build_default_skill_registry()
    for phrase in (
        "abrir o bloco de notas",
        "abra o bloco de notas",
        "abrir o notepad",
        "abrir a calculadora",
    ):
        skills = registry.select_skills_for_task(phrase)
        assert [skill.name for skill in skills] == ["Computer"], phrase


def test_desktop_task_does_not_expose_unrelated_skills():
    registry = build_default_skill_registry()
    # Recursos das skills não relacionadas permanecem fora.
    tools = registry.get_tools_for_skills(
        [skill.name for skill in registry.select_skills_for_task("abrir bloco de notas")]
    )
    assert "open_app" in tools
    assert "close_app" in tools
    assert "web_search" not in tools
    assert "browser_open" not in tools
    assert "file_write" not in tools


def test_desktop_task_is_not_ambiguous():
    registry = build_default_skill_registry()
    assert registry.confidence_for_task("abrir bloco de notas") in ("alta", "media")
    assert registry.select_skills_for_task("abrir bloco de notas") != []


def test_single_skill_registry_desktop_resolves_open_app():
    registry = SkillRegistry()
    from app.skills.base import Skill

    registry.register(
        Skill(
            name="Computer",
            description="automação do computador",
            keywords=["bloco de notas", "notepad", "calculadora"],
            tools=["open_app", "close_app", "windows_search"],
        )
    )
    named = registry.get_tools_for_skills(
        [skill.name for skill in registry.select_skills_for_task("abrir bloco de notas")]
    )
    assert "open_app" in named