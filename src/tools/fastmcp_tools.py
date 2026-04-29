from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from src.config import get_config
from src.tools import sql

router = APIRouter(prefix="/tools")


class LeaveRequest(BaseModel):
    user_id: str
    start_date: str
    end_date: str
    reason: str = ""


class TicketRequest(BaseModel):
    user_id: str
    issue_type: str
    priority: str = "medium"


class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str


@router.post("/apply_leave")
async def apply_leave(req: LeaveRequest) -> dict[str, Any]:
    result = sql.apply_leave(req.user_id, req.start_date, req.end_date, req.reason)
    return {"request_id": result.request_id, "approval_required": result.approval_required}


@router.post("/create_ticket")
async def create_ticket(req: TicketRequest) -> dict[str, Any]:
    ticket_id = sql.create_ticket(req.user_id, req.issue_type, req.priority)
    return {"ticket_id": ticket_id}


@router.get("/get_leave_balance")
async def get_leave_balance(user_id: str) -> dict[str, Any]:
    balance = sql.get_leave_balance(user_id)
    return {"user_id": user_id, "balance": balance}


@router.post("/approve_request")
async def approve_request(approval_id: int, approver_id: str, status: str) -> dict[str, Any]:
    sql.approve_request(approval_id, approver_id, status)
    return {"approval_id": approval_id, "status": status}


@router.post("/send_email")
async def send_email(req: EmailRequest) -> dict[str, Any]:
    config = get_config()
    if not config.power_automate_email_url:
        return {"status": "skipped", "detail": "POWER_AUTOMATE_EMAIL_URL not set"}

    payload = {"to": req.to, "subject": req.subject, "body": req.body}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(config.power_automate_email_url, json=payload)

    return {"status": "sent", "code": response.status_code}
