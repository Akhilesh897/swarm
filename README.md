# Enterprise Multi-Agent AI Copilot

This project implements an enterprise multi-agent AI copilot aligned to the provided architecture. It includes agent specs, a LangGraph-based orchestration flow, RBAC middleware, RAG hooks, and FastAPI endpoints for tools and chat.

## What is included
- Agent specs and architecture outline in [docs](docs)
- FastAPI app with LangGraph workflow
- Tool layer with placeholders for FastMCP-style execution
- SQLite persistence for leaves, tickets, approvals, reimbursements
- RAG adapter with ChromaDB fallback
- Power Automate email hook

## Quickstart
1. Create a virtual environment and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill values.
3. Run the API:
   ```bash
   uvicorn src.app:app --reload
   ```
4. Call `POST /chat` with a user query and role.

## Folder map
- `src/app.py` FastAPI entry point
- `src/graph/workflow.py` LangGraph orchestration
- `src/agents` domain agents and router
- `src/tools` tool layer (SQL, email, RAG, FastMCP stubs)
- `docs` specs and API guide
- `data` local storage (SQLite, vector DB)

## Notes
- The tool layer is written as a FastAPI router to emulate MCP calls. Replace with a real FastMCP server if needed.
- RAG ingestion expects documents under `data/docs`.

## RAG ingestion
Place `.txt` or `.md` files under `data/docs`, then run:
```bash
python -c "from src.tools.ingest import ingest_folder; print(ingest_folder('data/docs'))"
```
