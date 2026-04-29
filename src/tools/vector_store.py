from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RetrievedDoc:
    content: str
    metadata: dict[str, Any]


class RAGStore:
    def __init__(self, persist_path: str) -> None:
        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self._docs: list[RetrievedDoc] = []

    def add_documents(self, docs: list[RetrievedDoc]) -> None:
        self._docs.extend(docs)

    def query(self, query: str, k: int = 3, role: str | None = None) -> list[RetrievedDoc]:
        scored: list[tuple[int, RetrievedDoc]] = []
        terms = {t.lower() for t in query.split()}
        for doc in self._docs:
            if role and doc.metadata.get("role") not in (None, role, "all"):
                continue
            score = sum(1 for t in terms if t in doc.content.lower())
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored[:k] if score > 0]
