from app.skills.base import Skill
from app.skills.browser import SKILL as BROWSER_SKILL
from app.skills.calendar import SKILL as CALENDAR_SKILL
from app.skills.computer import SKILL as COMPUTER_SKILL
from app.skills.documents import SKILL as DOCUMENTS_SKILL
from app.skills.files import SKILL as FILES_SKILL
from app.skills.macros import SKILL as MACROS_SKILL
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
    MACROS_SKILL,
    WEB_SKILL,
    SHELL_SKILL,
    REMINDERS_SKILL,
    TASKS_SKILL,
    CALENDAR_SKILL,
    SYSTEM_SKILL,
]


def build_default_skill_registry() -> SkillRegistry:
    """Skills padrão agrupando as ferramentas existentes no registro de tools.

    O vínculo entre skill e tools usa nomes declarados em cada ``Skill``;
    a checagem de consistência com o ``ToolRegistry`` real fica no runtime
    (``SkillRegistry.validate_tools``).
    """
    registry = SkillRegistry()
    for skill in _SKILLS:
        registry.register(skill)
    return registry