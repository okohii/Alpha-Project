from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ToolPermission(StrEnum):
    read = "read"
    write = "write"
    sensitive = "sensitive"


@dataclass(slots=True)
class ToolResult:
    name: str
    success: bool
    data: dict[str, Any]
    error: str | None = None


class Tool(ABC):
    name: str
    description: str
    permission: ToolPermission = ToolPermission.read

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            },
        }

    def parameters_schema(self) -> dict[str, Any]:
        # Default: empty object parameters (no additionalProperties field)
        return {"type": "object", "properties": {}}
