from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def add_tool(self, tool_name: str) -> None:
        if tool_name not in self.tools:
            self.tools.append(tool_name)
