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


class TicketCreateRequest(BaseModel):
    issue_type: str
    priority: str = "medium"
    detail: str = ""


class TicketAssignRequest(BaseModel):
    ticket_id: int
    engineer_id: str


class TicketResolveRequest(BaseModel):
    ticket_id: int


class LeaveApplyRequest(BaseModel):
    start_date: str
    end_date: str
    leave_type: str = "general"
    reason: str = ""


class LeaveCancelRequest(BaseModel):
    request_id: int


class ApprovalActionRequest(BaseModel):
    approval_id: int
    action: str


class AssetRequestCreate(BaseModel):
    asset_type: str


class TicketCreateRequest(BaseModel):
    issue_type: str
    priority: str = "medium"
    detail: str = ""


class TicketAssignRequest(BaseModel):
    ticket_id: int
    engineer_id: str


class TicketResolveRequest(BaseModel):
    ticket_id: int


class LeaveApplyRequest(BaseModel):
    start_date: str
    end_date: str
    leave_type: str = "general"
    reason: str = ""


class LeaveCancelRequest(BaseModel):
    request_id: int


class ApprovalActionRequest(BaseModel):
    approval_id: int
    action: str


class TicketCreateRequest(BaseModel):
    issue_type: str
    priority: str = "medium"
    detail: str = ""


class TicketAssignRequest(BaseModel):
    ticket_id: int
    engineer_id: str


class TicketResolveRequest(BaseModel):
    ticket_id: int


class LeaveApplyRequest(BaseModel):
    start_date: str
    end_date: str
    leave_type: str = "general"
    reason: str = ""


class LeaveCancelRequest(BaseModel):
    request_id: int


class ApprovalActionRequest(BaseModel):
    approval_id: int
    action: str


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

    ROLE_EMPLOYEE = "employee"
    ROLE_MANAGER = "manager"
    ROLE_IT_LEAD = "it_lead"
    ROLE_ADMIN = "admin"
    EMPLOYEE_PLUS = {ROLE_EMPLOYEE, ROLE_MANAGER, ROLE_IT_LEAD, ROLE_ADMIN}

    def _require_roles(current_user: AuthUser, allowed: set[str]) -> None:
        role = _normalize_role(current_user.role)
        if role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    def _notify_power_automate(url: str | None, payload: dict) -> None:
        if not url:
            return
        try:
            import httpx
            httpx.post(url, json=payload, timeout=10)
        except Exception:
            return

    @app.get("/tickets/my")
    def tickets_my(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        return sql.list_tickets(current_user.user_id, role="employee")

    @app.get("/tickets/all")
    def tickets_all(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        _require_roles(current_user, {"it_lead", "admin"})
        return sql.list_tickets(current_user.user_id, role=_normalize_role(current_user.role))

    @app.post("/tickets/create")
    def tickets_create(req: TicketCreateRequest, current_user: AuthUser = Depends(require_current_user)) -> dict:
        _require_roles(current_user, EMPLOYEE_PLUS)
        result = sql.create_it_ticket_with_checks(
            current_user.user_id,
            issue_type=req.issue_type,
            priority=req.priority,
            detail=req.detail,
        )
        if result.status == "created" and result.ticket_id and result.approval_id:
            from src.core.notifications import build_approval_notification_payload
            payload = build_approval_notification_payload(
                event="approval_pending",
                entity_type="it_ticket",
                entity_id=result.ticket_id,
                approval_id=result.approval_id,
                approval_stage=result.approval_stage or "manager_approval",
                approval_status="pending",
                requested_by_user_id=current_user.user_id,
                requested_by_email=current_user.email,
                requested_by_name=current_user.name,
                approver_role="manager",
                approver_email=get_config().manager_email,
                request_details={
                    "ticket_issue_type": req.issue_type,
                    "priority": req.priority,
                    "description": req.detail,
                }
            )
            _notify_power_automate(
                get_config().power_automate_url,
                payload,
            )
        return {
            "status": result.status,
            "detail": result.detail,
            "ticket_id": result.ticket_id,
            "approval_id": result.approval_id,
            "approval_stage": result.approval_stage,
        }

    @app.post("/tickets/assign")
    def tickets_assign(req: TicketAssignRequest, current_user: AuthUser = Depends(require_current_user)) -> dict:
        _require_roles(current_user, {"it_lead", "admin"})
        return {"status": sql.assign_ticket(req.ticket_id, req.engineer_id)}

    @app.post("/tickets/resolve")
    def tickets_resolve(req: TicketResolveRequest, current_user: AuthUser = Depends(require_current_user)) -> dict:
        _require_roles(current_user, {"it_lead", "admin"})
        return {"status": sql.resolve_ticket(req.ticket_id, current_user.user_id)}

    @app.get("/inventory")
    def inventory(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        _require_roles(current_user, {"it_lead", "admin"})
        return sql.get_inventory()

    @app.post("/assets/request")
    def assets_request(req: AssetRequestCreate, current_user: AuthUser = Depends(require_current_user)) -> dict:
        _require_roles(current_user, EMPLOYEE_PLUS)
        result = sql.request_asset(current_user.user_id, req.asset_type.strip().lower())
        _notify_power_automate(
            get_config().power_automate_it_url,
            {
                "event": "asset_request_created",
                "employee_id": current_user.user_id,
                "asset_type": req.asset_type.strip().lower(),
                "approver_email": get_config().manager_email,
            },
        )
        return {
            "asset_id": result.asset_id,
            "approval_id": result.approval_id,
            "status": result.status,
            "approval_stage": result.approval_stage,
        }

    @app.get("/assets/my")
    def assets_my(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        return sql.list_assets(current_user.user_id, role=ROLE_EMPLOYEE)

    @app.get("/leave/my")
    def leave_my(current_user: AuthUser = Depends(require_current_user)) -> dict:
        return {"balance": sql.get_leave_balance(current_user.user_id), "history": sql.list_leaves(current_user.user_id)}

    @app.get("/leave/pending")
    def leave_pending(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        _require_roles(current_user, {"manager", "admin"})
        return sql.list_pending_leave_approvals_for_manager(current_user.user_id)

    @app.post("/leave/apply")
    def leave_apply(req: LeaveApplyRequest, current_user: AuthUser = Depends(require_current_user)) -> dict:
        _require_roles(current_user, EMPLOYEE_PLUS)
        result = sql.apply_leave(
            current_user.user_id,
            start_date=req.start_date,
            end_date=req.end_date,
            reason=req.reason,
            leave_type=req.leave_type,
        )
        if result.approval_required:
            from src.core.notifications import build_approval_notification_payload
            payload = build_approval_notification_payload(
                event="approval_pending",
                entity_type="leave_request",
                entity_id=result.request_id,
                approval_id=result.approval_id,
                approval_stage="manager_approval",
                approval_status="pending",
                requested_by_user_id=current_user.user_id,
                requested_by_email=current_user.email,
                requested_by_name=current_user.name,
                approver_role="manager",
                approver_email=get_config().manager_email,
                request_details={
                    "leave_type": req.leave_type,
                    "start_date": req.start_date,
                    "end_date": req.end_date,
                    "priority": "medium"
                }
            )
            _notify_power_automate(
                get_config().power_automate_url,
                payload,
            )
        return {"request_id": result.request_id, "status": result.status, "approval_required": result.approval_required, "detail": result.detail}

    @app.post("/leave/cancel")
    def leave_cancel(req: LeaveCancelRequest, current_user: AuthUser = Depends(require_current_user)) -> dict:
        _require_roles(current_user, EMPLOYEE_PLUS)
        status_value = sql.cancel_leave(current_user.user_id, req.request_id)
        if status_value == "canceled":
            _notify_power_automate(
                get_config().power_automate_email_url,
                {
                    "event": "leave_request_canceled",
                    "employee_id": current_user.user_id,
                    "request_id": str(req.request_id),
                    "approver_email": get_config().manager_email,
                },
            )
        return {"status": status_value}

    @app.get("/approvals/pending")
    def approvals_pending(current_user: AuthUser = Depends(require_current_user)) -> dict:
        role = _normalize_role(current_user.role)
        if role == "manager":
            return {
                "leave": sql.list_pending_leave_approvals_for_manager(current_user.user_id),
                "asset": sql.list_pending_asset_approvals("manager_approval"),
                "ticket": sql.list_pending_ticket_approvals("manager_approval"),
            }
        if role == "it_lead":
            return {"leave": [], "asset": sql.list_pending_asset_approvals("it_lead_approval"), "ticket": sql.list_pending_ticket_approvals("it_lead_approval")}
        if role == "admin":
            all_history = sql.list_approval_history(limit=500)
            return {"pending": [row for row in all_history if row.get("status") == "pending"]}
        return {"leave": [], "asset": [], "ticket": []}

    @app.get("/approvals/history")
    def approvals_history(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        role = _normalize_role(current_user.role)
        if role == ROLE_ADMIN:
            return sql.list_approval_history(limit=500)
        if role == ROLE_MANAGER:
            # Manager history includes leave approvals + manager-stage asset pipeline visibility.
            return sql.list_approval_history(limit=300)
        if role == ROLE_IT_LEAD:
            return sql.list_approval_history(limit=300, request_type="asset")
        return sql.list_approval_history(limit=200, user_id=current_user.user_id)

    @app.post("/approvals/action")
    def approvals_action(req: ApprovalActionRequest, current_user: AuthUser = Depends(require_current_user)) -> dict:
        action = req.action.strip().lower()
        if action not in {"approve", "approved", "reject", "rejected"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")
        normalized = "approved" if action.startswith("approve") else "rejected"

        approval = sql.get_approval(req.approval_id)
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
        if approval["status"] != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not pending")

        role = _normalize_role(current_user.role)
        stage = (approval.get("approval_stage") or "").strip() or ("manager_approval" if approval["request_type"] == "leave" else "")
        if role != "admin":
            if stage == "manager_approval" and role != "manager":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
            if stage == "it_lead_approval" and role != "it_lead":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

        if approval["request_type"] == "leave":
            sql.update_leave_status(approval["request_id"], current_user.user_id, normalized)
            return {"status": "ok", "request_type": "leave", "request_id": approval["request_id"]}

        if approval["request_type"] == "asset":
            import sqlite3
            import time

            result = None
            for attempt in range(6):
                try:
                    result = sql.update_asset_approval(
                        approval_id=approval["id"],
                        asset_id=approval["request_id"],
                        approval_stage=stage,
                        approver_id=current_user.user_id,
                        status=normalized,
                    )
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == 5:
                        raise
                    time.sleep(0.1 * (attempt + 1))

            sql.log_event(
                current_user.user_id,
                "asset.approval.action",
                f"approval_id={approval['id']} asset_id={approval['request_id']} stage={stage} status={normalized}",
            )
            if stage == "manager_approval" and normalized == "approved" and result.next_stage == "it_lead_approval":
                _notify_power_automate(
                    get_config().power_automate_it_url,
                    {
                        "event": "asset_request_ready_for_it_approval",
                        "asset_id": str(result.asset_id),
                    },
                )
            return {
                "status": "ok",
                "request_type": "asset",
                "asset_id": result.asset_id,
                "approval_id": result.approval_id,
                "approval_stage": result.approval_stage,
                "next_stage": result.next_stage,
                "next_approval_id": result.next_approval_id,
                "detail": result.detail,
            }

        if approval["request_type"] == "ticket":
            result = sql.update_ticket_approval(
                approval_id=approval["id"],
                ticket_id=approval["request_id"],
                approval_stage=stage,
                approver_id=current_user.user_id,
                status=normalized,
            )
            if result.detail in {
                "approval_not_found",
                "approval_ticket_mismatch",
                "approval_not_pending",
                "approval_stage_mismatch",
                "approval_already_actioned",
                "ticket_not_found",
            }:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.detail)
            if stage == "manager_approval" and normalized == "approved" and result.next_stage == "it_lead_approval" and result.next_approval_id:
                from src.core.notifications import build_approval_notification_payload
                payload = build_approval_notification_payload(
                    event="approval_pending",
                    entity_type="it_ticket",
                    entity_id=result.ticket_id,
                    approval_id=result.next_approval_id,
                    approval_stage="it_lead_approval",
                    approval_status="pending",
                    requested_by_user_id=approval.get("approver_id") or "",
                    approver_role="it_lead",
                    approver_email=get_config().manager_email,
                )
                _notify_power_automate(
                    get_config().power_automate_url,
                    payload,
                )
            return {
                "status": "ok",
                "request_type": "ticket",
                "ticket_id": result.ticket_id,
                "approval_id": result.approval_id,
                "approval_stage": result.approval_stage,
                "next_stage": result.next_stage,
                "next_approval_id": result.next_approval_id,
                "detail": result.detail,
            }

        sql.approve_request(approval["id"], current_user.user_id, normalized)
        return {"status": "ok", "request_type": approval["request_type"], "request_id": approval["request_id"]}

    @app.get("/admin/users")
    def admin_users(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        _require_roles(current_user, {"admin"})
        return sql.list_users()

    @app.post("/admin/users/role")
    def admin_set_role(
        user_id: str,
        role: str,
        department: str | None = None,
        current_user: AuthUser = Depends(require_current_user),
    ) -> dict:
        _require_roles(current_user, {"admin"})
        status_value = sql.set_user_role(user_id, _normalize_role(role), department)
        return {"status": status_value}

    @app.get("/admin/audit-logs")
    def admin_audit_logs(current_user: AuthUser = Depends(require_current_user)) -> list[dict]:
        _require_roles(current_user, {"admin"})
        return sql.list_audit_logs(limit=300)

    return app


app = create_app()
