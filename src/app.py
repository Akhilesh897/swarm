from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import get_config
from src.core.logging import setup_logging
from src.graph.workflow import run_graph
from src.tools.fastmcp_tools import router as tools_router
from src.tools.ingest import ingest_folder
from src.tools import sql
from src.tools.sql import init_db


class ChatRequest(BaseModel):
    user_id: str
    role: str
    query: str
    session_id: str
    model_preference: str | None = None


class ChatResponse(BaseModel):
    response: str
    trace_id: str
    approval_required: bool


class ITApprovalUpdate(BaseModel):
    approval_id: int
    asset_id: int
    approval_stage: str
    status: str
    approver_id: str
    fulfilled_by: str | None = None


class ITApprovalResponse(BaseModel):
    asset_id: int
    approval_id: int
    status: str
    approval_stage: str
    next_stage: str | None
    next_approval_id: int | None = None
    detail: str | None = None


def create_app() -> FastAPI:
    setup_logging()
    init_db()
    app = FastAPI(title=get_config().app_name)
    app.include_router(tools_router)

    config = get_config()
    try:
        ingest_folder(config.hr_docs_path, role="general")
    except Exception:
        pass

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def ui_root() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/ui")
    def ui_page() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        try:
            result = run_graph(
                user_id=req.user_id,
                role=req.role,
                query=req.query,
                session_id=req.session_id,
                model_preference=req.model_preference,
            )
        except Exception as exc:
            return ChatResponse(
                response=f"Sorry, I could not complete that request. {type(exc).__name__}: {exc}",
                trace_id="trace_error",
                approval_required=False,
            )
        return ChatResponse(
            response=result["response"],
            trace_id=result["trace_id"],
            approval_required=result["approval_required"],
        )

    @app.post("/approvals/it", response_model=ITApprovalResponse)
    def update_it_approval(req: ITApprovalUpdate) -> ITApprovalResponse:
        result = sql.update_asset_approval(
            approval_id=req.approval_id,
            asset_id=req.asset_id,
            approval_stage=req.approval_stage,
            approver_id=req.approver_id,
            status=req.status.lower(),
            fulfilled_by=req.fulfilled_by,
        )
        return ITApprovalResponse(
            asset_id=result.asset_id,
            approval_id=result.approval_id,
            status=result.status,
            approval_stage=result.approval_stage,
            next_stage=result.next_stage,
            next_approval_id=result.next_approval_id,
            detail=result.detail,
        )

    return app


app = create_app()
