from fastapi import FastAPI
from pydantic import BaseModel

from src.config import get_config
from src.core.logging import setup_logging
from src.graph.workflow import run_graph
from src.tools.fastmcp_tools import router as tools_router
from src.tools.sql import init_db


class ChatRequest(BaseModel):
    user_id: str
    role: str
    query: str
    session_id: str


class ChatResponse(BaseModel):
    response: str
    trace_id: str
    approval_required: bool


def create_app() -> FastAPI:
    setup_logging()
    init_db()
    app = FastAPI(title=get_config().app_name)
    app.include_router(tools_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        result = run_graph(
            user_id=req.user_id,
            role=req.role,
            query=req.query,
            session_id=req.session_id,
        )
        return ChatResponse(
            response=result["response"],
            trace_id=result["trace_id"],
            approval_required=result["approval_required"],
        )

    return app


app = create_app()
