from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import get_config
from src.core.auth import (
    AuthUser,
    authenticate_user,
    create_access_token,
    register_user,
    require_current_user,
    require_pa_callback,
)
from src.core.logging import setup_logging
from src.graph.workflow import run_graph
from src.tools.fastmcp_tools import router as tools_router
from src.tools.ingest import ingest_folder
from src.tools import sql
from src.tools.sql import init_db


class ChatRequest(BaseModel):
    user_id: str | None = None
    role: str | None = None
    query: str
    session_id: str
    model_preference: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    department: str | None = None


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


def _normalize_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "it":
        return "it_lead"
    return normalized


def _resolve_identity(req: ChatRequest, user: AuthUser | None) -> tuple[str, str]:
    if user:
        return user.user_id, _normalize_role(user.role)
    user_id = (req.user_id or "").strip()
    role = _normalize_role(req.role or "")
    if not user_id or not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication context.")
    return user_id, role


def _role_page(role: str) -> str:
    normalized = _normalize_role(role)
    if normalized == "it_lead":
        return "/it-lead"
    if normalized == "manager":
        return "/manager"
    return "/employee"


def create_app() -> FastAPI:
    setup_logging()
    init_db()
    import logging
    logging.getLogger(__name__).info(
        "[STARTUP] create_app() executed — auth.py revision: require_pa_callback wired"
    )
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

    @app.get("/signup")
    def signup_page() -> FileResponse:
        return FileResponse(static_dir / "signup.html")

    @app.get("/employee")
    def employee_page() -> FileResponse:
        return FileResponse(static_dir / "console.html")

    @app.get("/manager")
    def manager_page() -> FileResponse:
        return FileResponse(static_dir / "console.html")

    @app.get("/it-lead")
    def it_lead_page() -> FileResponse:
        return FileResponse(static_dir / "console.html")

    @app.get("/chat-ui")
    def chat_page() -> FileResponse:
        return FileResponse(static_dir / "console.html")

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest, current_user: AuthUser = Depends(require_current_user)) -> ChatResponse:
        user_id, role = _resolve_identity(req, current_user)
        try:
            result = run_graph(
                user_id=user_id,
                role=role,
                query=req.query,
                session_id=req.session_id,
                model_preference=req.model_preference,
            )
        except Exception as exc:
            import traceback
            import logging
            logging.error(f"[DEBUG FLOW] ERROR: Exception during chat processing:\n{traceback.format_exc()}")
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

    @app.post("/auth/login", response_model=AuthResponse)
    def login(req: LoginRequest) -> AuthResponse:
        user = authenticate_user(req.email, req.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        token = create_access_token(user)
        return AuthResponse(
            access_token=token,
            user_id=user.user_id,
            role=user.role,
            department=user.department,
        )

    @app.post("/auth/signup", response_model=AuthResponse)
    def signup(req: SignupRequest) -> AuthResponse:
        user, error = register_user(req.email, req.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error or "Unable to create account",
            )
        token = create_access_token(user)
        return AuthResponse(
            access_token=token,
            user_id=user.user_id,
            role=user.role,
            department=user.department,
        )

    @app.get("/auth/next")
    def auth_next(current_user: AuthUser = Depends(require_current_user)) -> dict[str, str]:
        return {"path": _role_page(current_user.role), "role": current_user.role}

    @app.post("/approvals/it", response_model=ITApprovalResponse)
    def update_it_approval(
        req: ITApprovalUpdate,
        _: None = Depends(require_pa_callback),
    ) -> ITApprovalResponse:
        import logging
        logging.getLogger(__name__).info(
            "[PA-CALLBACK] /approvals/it HIT — approval_id=%s stage=%s status=%s",
            req.approval_id, req.approval_stage, req.status,
        )
        print("[PA-CALLBACK] APPROVAL ENDPOINT HIT", req.approval_id, req.approval_stage)
        stage_role_map = {
            "manager_approval": "manager",
            "it_lead_approval": "it_lead",
        }
        if req.approval_stage not in stage_role_map:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported approval stage",
            )
        result = sql.update_asset_approval(
            approval_id=req.approval_id,
            asset_id=req.asset_id,
            approval_stage=req.approval_stage,
            approver_id=req.approver_id,
            status=req.status.lower(),
            fulfilled_by=req.fulfilled_by,
        )
        if result.detail in {
            "approval_not_found",
            "approval_asset_mismatch",
            "approval_not_pending",
            "approval_stage_mismatch",
            "approval_already_actioned",
            "asset_stage_mismatch",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.detail,
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

    @app.get('/api/context/leaves')
    def get_context_leaves(current_user: AuthUser = Depends(require_current_user)):
        return sql.list_leaves(current_user.user_id)

    @app.get('/api/context/tickets')
    def get_context_tickets(current_user: AuthUser = Depends(require_current_user)):
        role = _normalize_role(current_user.role)
        return sql.list_tickets(current_user.user_id, role)

    @app.get('/api/context/assets')
    def get_context_assets(current_user: AuthUser = Depends(require_current_user)):
        role = _normalize_role(current_user.role)
        return sql.list_assets(current_user.user_id, role)

    return app


app = create_app()
