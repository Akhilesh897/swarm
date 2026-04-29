from dataclasses import dataclass
from typing import Any


@dataclass
class AgentResult:
    response: str
    approval_required: bool = False
    tool_calls: list[dict[str, Any]] | None = None


class BaseAgent:
    name: str = "base"

    def handle(self, state: dict[str, Any]) -> AgentResult:
        raise NotImplementedError
