from __future__ import annotations

from enum import StrEnum


class Verbosity(StrEnum):
    quiet = "quiet"
    normal = "normal"
    verbose = "verbose"
    debug = "debug"

    @classmethod
    def parse(cls, value: str) -> Verbosity | None:
        try:
            return cls(value.strip().lower())
        except ValueError:
            return None


def describes_tool_details(verbosity: Verbosity) -> bool:
    return verbosity in (Verbosity.verbose, Verbosity.debug)