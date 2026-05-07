# Enterprise Multi-Agent AI Copilot

This project implements an enterprise multi-agent AI copilot aligned to the provided architecture. It includes agent specs, a LangGraph-based orchestration flow, RBAC middleware, RAG hooks, and FastAPI endpoints for tools and chat.

## What is included
- Agent specs and architecture outline in [docs](docs)
- FastAPI app with LangGraph workflow
- Secure login with JWT-backed identity
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
4. Open `http://127.0.0.1:8000/` for login or `http://127.0.0.1:8000/signup` to create an account. After successful auth, the UI redirects by role to `/employee`, `/manager`, or `/it-lead`.
5. API clients can login with `POST /auth/login` or sign up with `POST /auth/signup`, then call `POST /chat` with `Authorization: Bearer <token>`.

Seeded local demo users use password `ChangeMe123!`:
- `employee@company.com` -> `employee`
- `manager@company.com` -> `manager`
- `itlead@company.com` -> `it_lead`

## Folder map
- `src/app.py` FastAPI entry point
- `src/graph/workflow.py` LangGraph orchestration
- `src/agents` domain agents and router
- `src/tools` tool layer (SQL, email, RAG, FastMCP stubs)
- `docs` specs and API guide
- `data` local storage (SQLite, vector DB)
- `scripts` local maintenance scripts

This repository uses a compact `src/` backend layout. The clean structure maps as:
- backend: `src/app.py`, `src/core`, `src/tools`
- agents: `src/agents`
- rag: `src/tools/ingest.py`, `src/tools/vector_store.py`
- workflows: `src/graph`
- scripts: `scripts`

## Git and CI workflow
Enable the local pre-commit hook once per clone:
```powershell
.\scripts\install-git-hooks.ps1
```

The hook blocks staged `.env` files, `.db` files, and files larger than 5MB.

Before pushing:
```bash
git status
git add .
git commit -m "chore: add git hygiene and ci workflow"
git push origin main
```

Use meaningful commit messages, for example:
- `feat: add finance agent`
- `fix: correct approval flow bug`
- `refactor: improve rag pipeline`
- `chore: update config`

Avoid vague messages such as `latest`, `final`, or `update`.

## Notes
- The tool layer is written as a FastAPI router to emulate MCP calls. Replace with a real FastMCP server if needed.
- RAG ingestion expects documents under `data/docs`.
- Set a strong `JWT_SECRET` outside local development.

## RAG ingestion
Place `.txt` or `.md` files under `data/docs`, then run:
```bash
python -c "from src.tools.ingest import ingest_folder; print(ingest_folder('data/docs'))"
```
