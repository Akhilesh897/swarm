from src.agents.base import AgentResult, BaseAgent
from src.tools.vector_store import RAGStore, RetrievedDoc

rag_store = RAGStore("./data/vector_db")


class RAGAgent(BaseAgent):
    name = "rag"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "")
        role = state.get("role", "")
        results = rag_store.query(query, k=3, role=role)
        if not results:
            return AgentResult(response="No relevant documents found.")
        summary = "\n".join(f"- {doc.content[:200]}" for doc in results)
        return AgentResult(response=f"Relevant documents:\n{summary}")


def ingest_documents(docs: list[RetrievedDoc]) -> None:
    rag_store.add_documents(docs)
