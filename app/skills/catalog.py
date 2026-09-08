from app.skills.base import Skill
from app.skills.browser import SKILL as BROWSER_SKILL
from app.skills.calendar import SKILL as CALENDAR_SKILL
from app.skills.computer import SKILL as COMPUTER_SKILL
from app.skills.documents import SKILL as DOCUMENTS_SKILL
from app.skills.files import SKILL as FILES_SKILL
from app.skills.memory import SKILL as MEMORY_SKILL
from app.skills.registry import SkillRegistry
from app.skills.reminders import SKILL as REMINDERS_SKILL
from app.skills.shell import SKILL as SHELL_SKILL
from app.skills.system import SKILL as SYSTEM_SKILL
from app.skills.tasks import SKILL as TASKS_SKILL
from app.skills.web import SKILL as WEB_SKILL

_SKILLS: list[Skill] = [
    BROWSER_SKILL,
    FILES_SKILL,
    DOCUMENTS_SKILL,
    COMPUTER_SKILL,
    MEMORY_SKILL,
    WEB_SKILL,
    SHELL_SKILL,
    CALENDAR_SKILL,
    REMINDERS_SKILL,
    TASKS_SKILL,
    SYSTEM_SKILL,
]


def build_default_skill_registry(
    tools_in_registry: dict[str, object] | None = None,
) -> SkillRegistry:
    """Skills padrão agrupando as ferramentas já existentes no registro de tools.

    ``tools_in_registry`` é opcional e usado apenas ao inspecionar quais tools o
    registro possui; as skills aqui definem os grupos conceituais.
    """
    registry = SkillRegistry()
    for skill in _SKILLS:
        registry.register(skill)
    return registry