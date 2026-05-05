from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from src.config import get_config
from src.tools import sql

router = APIRouter(prefix="/tools")


class LeaveRequest(BaseModel):
    user_id: str
    employee_name: str | None = None
    employee_email: str | None = None
    leave_type: str = "general"
    start_date: str
    end_date: str
    reason: str = ""


class TicketRequest(BaseModel):
    user_id: str
    issue_type: str
    priority: str = "medium"
    detail: str = ""


class AssetRequest(BaseModel):
    user_id: str
    asset_type: str


class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str


class LeaveStatusUpdate(BaseModel):
    request_id: str
    status: str
    approver_email: str = ""


@router.post("/apply_leave")
async def apply_leave(req: LeaveRequest) -> dict[str, Any]:
    result = sql.apply_leave(req.user_id, req.start_date, req.end_date, req.reason, leave_type=req.leave_type)
    if result.approval_required:
        _notify_manager(req, result.request_id)
    return {
        "request_id": result.request_id,
        "approval_required": result.approval_required,
        "status": result.status,
        "detail": result.detail,
    }



@router.post("/create_ticket")
async def create_ticket(req: TicketRequest) -> dict[str, Any]:
    result = sql.create_it_ticket_with_checks(req.user_id, req.issue_type, req.priority, detail=req.detail)
    return {
        "ticket_id": result.ticket_id,
        "status": result.status,
        "detail": result.detail,
        "matched_record": result.matched_record,
    }


@router.get("/list_tickets")
async def list_tickets(user_id: str, role: str = "employee") -> dict[str, Any]:
    return {"user_id": user_id, "tickets": sql.list_tickets(user_id, role)}


@router.post("/assign_ticket")
async def assign_ticket(ticket_id: int, engineer_id: str, role: str = "employee") -> dict[str, Any]:
    if role != "it":
        return {"ticket_id": ticket_id, "status": "access_denied"}
    return {"ticket_id": ticket_id, "status": sql.assign_ticket(ticket_id, engineer_id)}


@router.post("/resolve_ticket")
async def resolve_ticket(ticket_id: int, engineer_id: str, role: str = "employee") -> dict[str, Any]:
    if role != "it":
        return {"ticket_id": ticket_id, "status": "access_denied"}
    return {"ticket_id": ticket_id, "status": sql.resolve_ticket(ticket_id, engineer_id)}


@router.post("/request_asset")
async def request_asset(req: AssetRequest) -> dict[str, Any]:
    asset_id = sql.request_asset(req.user_id, req.asset_type)
    return {
        "asset_id": asset_id,
        "status": "pending_manager_approval",
        "approval_flow": ["manager_approval", "it_approval", "inventory_validation", "fulfillment"],
    }


@router.get("/list_assets")
async def list_assets(user_id: str, role: str = "employee") -> dict[str, Any]:
    return {"user_id": user_id, "assets": sql.list_assets(user_id, role)}


@router.get("/inventory")
async def inventory(role: str = "employee") -> dict[str, Any]:
    if role != "it":
        return {"status": "access_denied", "inventory": []}
    return {"status": "ok", "inventory": sql.get_inventory()}


@router.get("/get_leave_balance")
async def get_leave_balance(user_id: str) -> dict[str, Any]:
    balance = sql.get_leave_balance(user_id)
    return {"user_id": user_id, "balance": balance}


@router.get("/list_leave_history")
async def list_leave_history(user_id: str) -> dict[str, Any]:
    return {"user_id": user_id, "history": sql.list_leaves(user_id)}


@router.get("/list_pending_leaves")
async def list_pending_leaves(user_id: str) -> dict[str, Any]:
    return {"user_id": user_id, "pending": sql.list_leaves(user_id, status="pending")}


@router.post("/cancel_leave")
async def cancel_leave(user_id: str, request_id: int) -> dict[str, Any]:
    status = sql.cancel_leave(user_id, request_id)
    return {"user_id": user_id, "request_id": request_id, "status": status}


@router.post("/approve_request")
async def approve_request(approval_id: int, approver_id: str, status: str) -> dict[str, Any]:
    sql.approve_request(approval_id, approver_id, status)
    return {"approval_id": approval_id, "status": status}


@router.post("/update_leave_status")
async def update_leave_status(req: LeaveStatusUpdate) -> dict[str, Any]:
    status_map = {"approve": "approved", "approved": "approved", "reject": "rejected", "rejected": "rejected"}
    status = status_map.get(req.status.lower())
    if not status:
        return {"request_id": req.request_id, "status": "invalid"}
    try:
        request_id = int(req.request_id)
    except ValueError:
        return {"request_id": req.request_id, "status": "invalid"}
    sql.update_leave_status(request_id, req.approver_email, status)
    return {"request_id": req.request_id, "status": status}


@router.get("/get_approval_status")
async def get_approval_status(request_type: str, request_id: int) -> dict[str, Any]:
    return {"request_type": request_type, "request_id": request_id, "status": sql.get_approval_status(request_type, request_id)}


@router.post("/send_email")
async def send_email(req: EmailRequest) -> dict[str, Any]:
    config = get_config()
    if not config.power_automate_email_url:
        return {"status": "skipped", "detail": "POWER_AUTOMATE_EMAIL_URL not set"}

    payload = {"to": req.to, "subject": req.subject, "body": req.body}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(config.power_automate_email_url, json=payload)

    return {"status": "sent", "code": response.status_code}




def _notify_manager(req: LeaveRequest, request_id: str) -> None:
    config = get_config()
    if not config.power_automate_email_url or not config.manager_email:
        return

    payload = {
        "request_id": str(request_id),
        "employee_name": req.employee_name or req.user_id,
        "employee_email": req.employee_email or req.user_id,
        "leave_type": req.leave_type,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "reason": req.reason,
        "approver_email": config.manager_email,
    }

    try:
        response = httpx.post(
            config.power_automate_email_url,
            json=payload,
            timeout=10
        )
        print("PA status:", response.status_code)
        print("PA response:", response.text)

    except Exception as e:
        print("Power Automate call failed:", str(e))
