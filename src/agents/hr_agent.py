import re
import logging

import httpx
from src.core.date_parser import parse_dates

from src.agents.base import AgentResult, BaseAgent
from src.agents.rag_agent import build_rag_response
from src.config import get_config
from src.tools import sql

logger = logging.getLogger(__name__)


class HRAgent(BaseAgent):
    name = "hr"

    def handle(self, state: dict) -> AgentResult:
        query = _normalize_query(state.get("query", ""))
        role = state.get("role", "employee")
        intent_type = state.get("intent_type", "other")

        if _is_ambiguous_confirmation(query):
            return AgentResult(response="I still need the start and end dates before I can submit a leave request. Please provide them in YYYY-MM-DD format, for example 2026-05-07 to 2026-05-09.")

        if intent_type == "policy" or _is_policy_query(query):
            response = build_rag_response(query, role=role, k=3)
            return AgentResult(response=response)

        if intent_type == "action" and ("cancel" in query or "withdraw" in query):
            request_id = _extract_request_id(query)
            if not request_id:
                return AgentResult(response="Please provide the leave request id to cancel.")
            status = sql.cancel_leave(state["user_id"], request_id)
            return AgentResult(response=f"Leave request {request_id} is now {status}.")

        if intent_type == "action" and "leave" in query and ("apply" in query or "request" in query):
            dates = _extract_dates(query)
            if len(dates) >= 2:
                leave_type = _extract_leave_type(query)
                result = sql.apply_leave(
                    state["user_id"],
                    start_date=dates[0],
                    end_date=dates[1],
                    reason="",
                    leave_type=leave_type,
                )
                if result.approval_required:
                    _notify_manager_if_needed(
                        result.request_id,
                        state["user_id"],
                        leave_type,
                        dates[0],
                        dates[1],
                    )
                response = (
                    f"Leave request {result.request_id} is {result.status}."
                    f" Approval required: {result.approval_required}."
                )
                if result.approval_required:
                    response = f"{response} Sent to manager for approval."
                if result.detail:
                    response = f"{response} {result.detail}"
                return AgentResult(response=response, approval_required=result.approval_required)
            return AgentResult(response="Please provide start and end dates in YYYY-MM-DD format.")

        if intent_type in {"status", "other"} and ("leave balance" in query or "balance" in query):
            balance = sql.get_leave_balance(state["user_id"])
            return AgentResult(response=f"Your leave balance is {balance} days.")

        if intent_type in {"status", "other"} and ("leave history" in query or "history" in query):
            history = sql.list_leaves(state["user_id"])
            if not history:
                return AgentResult(response="No leave history found.")
            lines = [f"- {row['id']}: {row['start_date']} to {row['end_date']} ({row['status']})" for row in history]
            return AgentResult(response="Leave history:\n" + "\n".join(lines))

        if intent_type in {"status", "other"} and "pending" in query and "leave" in query:
            pending = sql.list_leaves(state["user_id"], status="pending")
            if not pending:
                return AgentResult(response="No pending leave requests.")
            lines = [f"- {row['id']}: {row['start_date']} to {row['end_date']}" for row in pending]
            return AgentResult(response="Pending leave requests:\n" + "\n".join(lines))

        if intent_type in {"status", "other"} and "approval" in query and "status" in query:
            request_id = _extract_request_id(query)
            if not request_id:
                return AgentResult(response="Please provide the leave request id to check status.")
            status = sql.get_approval_status("leave", request_id)
            return AgentResult(response=f"Approval status for {request_id}: {status}.")

        return AgentResult(response="HR request received. Provide more details for policy or leave help.")


def _extract_dates(text: str) -> list[str]:
    return parse_dates(text)


def _extract_leave_type(text: str) -> str:
    if "maternity" in text:
        return "maternity"
    if "sick" in text:
        return "sick"
    if "casual" in text:
        return "casual"
    return "general"


def _extract_request_id(text: str) -> int | None:
    match = re.search(r"\b(\d+)\b", text)
    return int(match.group(1)) if match else None


def _is_policy_query(text: str) -> bool:
    keywords = [
        "policy",
        "handbook",
        "notice period",
        "work from home",
        "maternity",
        "maternal",
        "casual leave",
    ]
    return any(keyword in text for keyword in keywords)


def _normalize_query(text: str) -> str:
    lowered = text.lower()
    replacements = {
        "poicy": "policy",
        "polcy": "policy",
        "maternal": "maternity",
        "wfh": "work from home",
    }
    for key, value in replacements.items():
        lowered = lowered.replace(key, value)
    return lowered


def _is_ambiguous_confirmation(text: str) -> bool:
    return text.strip() in {
        "yes",
        "y",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "sure",
        "go ahead",
    }


def _notify_manager_if_needed(
    request_id: int,
    user_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
) -> None:
    config = get_config()
    if not config.power_automate_email_url or not config.manager_email:
        return
    payload = {
        "request_id": str(request_id),
        "employee_name": user_id,
        "employee_email": user_id,
        "leave_type": leave_type,
        "start_date": start_date,
        "end_date": end_date,
        "reason": "",
        "approver_email": config.manager_email,
    }
    try:
        httpx.post(config.power_automate_email_url, json=payload, timeout=10)
    except httpx.HTTPError as exc:
        logger.warning("Manager leave notification failed for request %s: %s", request_id, exc)
