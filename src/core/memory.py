from collections import defaultdict
from typing import Any

from src.tools import sql


class MemoryManager:
    def __init__(self) -> None:
        self._short_term: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_message(self, session_id: str, message: dict[str, Any]) -> None:
        self._short_term[session_id].append(message)

    def get_context(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
        return self._short_term.get(session_id, [])[-limit:]

    def save_long_term(self, user_id: str, session_id: str, content: str) -> None:
        sql.save_memory(user_id, session_id, content)

    def load_long_term(self, user_id: str, limit: int = 10) -> list[str]:
        return sql.load_memory(user_id, limit=limit)
