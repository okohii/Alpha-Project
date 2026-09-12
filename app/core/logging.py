from __future__ import annotations

import logging
import sys
from typing import Any

from app.core.config import get_settings


CATEGORIES = frozenset(
    {
        "action",
        "stt",
        "tts",
        "tools",
        "response",
        "llm",
        "memory",
        "audio",
        "avatar",
        "interaction",
        "security",
        "system",
    }
)

_CATEGORY_ALIASES = {
    "tool": "tools",
    "tool_calls": "tools",
    "speech_to_text": "stt",
    "text_to_speech": "tts",
    "agent": "action",
    "execution": "action",
    "task": "action",
    "tasks": "action",
    "server": "avatar",
    "voice": "audio",
}


def normalize_category(category: str | None) -> str:
    value = (category or "system").strip().lower().replace("-", "_")
    return _CATEGORY_ALIASES.get(value, value if value in CATEGORIES else "system")


def enabled_categories() -> set[str]:
    raw = str(get_settings().log_categories or "all").strip().lower()
    if not raw or raw in {"all", "*"}:
        return set(CATEGORIES)
    if raw in {"none", "off", "false", "0"}:
        return set()
    result: set[str] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item in {"all", "*"}:
            return set(CATEGORIES)
        if item.startswith("-"):
            result.discard(normalize_category(item[1:]))
        else:
            result.add(normalize_category(item))
    return result


def category_from_logger(name: str) -> str:
    lowered = (name or "").lower()
    if ".perception.stt" in lowered or lowered.endswith(".stt"):
        return "stt"
    if ".speech.tts" in lowered or ".speech.pipeline" in lowered:
        return "tts"
    if ".speech.audio" in lowered or ".speech.listener" in lowered:
        return "audio"
    if ".tools" in lowered or ".tool" in lowered:
        return "tools"
    if ".memory" in lowered:
        return "memory"
    if ".security" in lowered:
        return "security"
    if ".interaction" in lowered or ".wakeword" in lowered:
        return "interaction"
    if ".avatar" in lowered or ".overlay" in lowered:
        return "avatar"
    if ".llm" in lowered:
        return "llm"
    if any(part in lowered for part in (".execution", ".tasks", ".macros", ".agent")):
        return "action"
    return "system"


class CategoryFilter(logging.Filter):
    """Filters records by ALPHA's user-facing log categories.

    Records can opt into an explicit category with ``extra={"alpha_category": ...}``.
    Existing loggers are categorized from their logger name as a safe fallback.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        explicit = getattr(record, "alpha_category", None)
        category = normalize_category(explicit) if explicit else category_from_logger(record.name)
        record.alpha_category = category
        return category in enabled_categories()


class CategoryLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that tags every record with an explicit ALPHA category."""

    def __init__(self, logger: logging.Logger, category: str):
        super().__init__(logger, {"alpha_category": normalize_category(category)})

    def process(self, msg: Any, kwargs: Any):
        extra = dict(kwargs.get("extra") or {})
        extra.setdefault("alpha_category", self.extra["alpha_category"])
        kwargs["extra"] = extra
        return msg, kwargs


def get_category_logger(category: str, name: str | None = None) -> CategoryLoggerAdapter:
    return CategoryLoggerAdapter(logging.getLogger(name or f"app.{normalize_category(category)}"), category)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(CategoryFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(alpha_category)s] %(name)s %(message)s"
        )
    )
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )
