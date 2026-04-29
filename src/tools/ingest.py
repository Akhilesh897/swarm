from pathlib import Path

from src.agents.rag_agent import ingest_documents
from src.tools.vector_store import RetrievedDoc


def ingest_folder(path: str, role: str = "all") -> int:
    base = Path(path)
    docs: list[RetrievedDoc] = []
    for file_path in base.rglob("*"):
        if file_path.suffix.lower() not in {".txt", ".md"}:
            continue
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        docs.append(RetrievedDoc(content=content, metadata={"path": str(file_path), "role": role}))

    ingest_documents(docs)
    return len(docs)
