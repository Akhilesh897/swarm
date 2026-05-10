import re
import logging

import httpx
from src.core.date_parser import parse_dates

from src.agents.base import AgentResult, BaseAgent
from src.core.notifications import build_approval_notification_payload, send_power_automate_notification
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
        user_id = state["user_id"]

        if _is_ambiguous_confirmation(query):
            return AgentResult(response="I still need the start and end dates before I can submit a leave request. Please provide them in YYYY-MM-DD format, for example 2026-05-07 to 2026-05-09.")

        if intent_type == "policy" or _is_policy_query(query):
            response = build_rag_response(query, role=role, k=3)
            return AgentResult(response=response)

        if _is_cancel_request(query):
            request_id = _extract_request_id(query)
            if not request_id and _contains_any(query, ["pending", "upcoming", "tomorrow"]):
                request_id = _latest_leave_id(user_id, status="pending")
            if not request_id:
                return AgentResult(response="Please provide the leave request id to cancel.")
            status = sql.cancel_leave(user_id, request_id)
            return AgentResult(response=f"Leave request {request_id} is now {status}.")

        if _is_leave_apply_request(query, intent_type):
            if _contains_any(query, ["half day", "half-day", "morning", "afternoon", "evening"]):
                return AgentResult(
                    response="Half-day leave needs a session selection (morning or afternoon) in the leave form. Please provide the exact date  and session."
                )
            threshold = _extract_balance_threshold(query)
            if threshold is not None:
                current_balance = sql.get_leave_balance(user_id)
                if current_balance <= threshold:
                    return AgentResult(
                        response=f"Leave was not submitted because your current balance is {current_balance} days, which is not greater than {threshold}."
                    )
            dates = _extract_dates(query)
            if len(dates) >= 2:
                leave_type = _extract_leave_type(query)
                result = sql.apply_leave(
                    user_id,
                    start_date=dates[0],
                    end_date=dates[1],
                    reason=_extract_reason(query),
                    leave_type=leave_type,
                )
                if result.approval_required:
                    _notify_manager_if_needed(
                        result.request_id,
                        result.approval_id,
                        user_id,
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
                if _contains_any(query, ["excluding holidays", "excluding weekends", "working days"]):
                    response = (
                        f"{response} Weekend/holiday exclusion is policy-driven; "
                        "I submitted this using the requested calendar dates."
                    )
                if _contains_any(query, ["and check balance", "also check balance"]):
                    balance = sql.get_leave_balance(user_id)
                    response = f"{response} Current leave balance: {balance} days."
                return AgentResult(response=response, approval_required=result.approval_required)
            return AgentResult(response="Please provide start and end dates.")

        if _is_leave_balance_request(query):
            balance = sql.get_leave_balance(user_id)
            return AgentResult(response=f"Your leave balance is {balance} days.")

        if _is_enough_leave_request(query):
            balance = sql.get_leave_balance(user_id)
            required_days = _extract_required_days(query)
            if required_days is None:
                return AgentResult(response=f"Your leave balance is {balance} days. Please tell me the number of days you want to check.")
            if balance >= required_days:
                return AgentResult(response=f"Yes, you have enough leave. Balance: {balance} days, requested: {required_days} days.")
            return AgentResult(response=f"No, you do not have enough leave. Balance: {balance} days, requested: {required_days} days.")

        if _is_leave_history_request(query):
            history = sql.list_leaves(user_id)
            if "rejected" in query:
                history = [row for row in history if row["status"] == "rejected"]
            elif "approved" in query:
                history = [row for row in history if row["status"] == "approved"]
            elif "canceled" in query or "cancelled" in query:
                history = [row for row in history if row["status"] == "canceled"]
            if not history:
                return AgentResult(response="No leave history found.")
            lines = [f"- {row['id']}: {row['start_date']} to {row['end_date']} ({row['status']})" for row in history]
            return AgentResult(response="Leave history:\n" + "\n".join(lines))

        if _is_pending_request(query):
            pending = sql.list_leaves(user_id, status="pending")
            if not pending:
                return AgentResult(response="No pending leave requests.")
            lines = [f"- {row['id']}: {row['start_date']} to {row['end_date']}" for row in pending]
            return AgentResult(response="Pending leave requests:\n" + "\n".join(lines))

        if _is_approval_status_request(query):
            request_id = _extract_request_id(query)
            if not request_id:
                request_id = _latest_leave_id(user_id)
                if not request_id:
                    return AgentResult(response="No leave request found yet.")
            status = sql.get_approval_status("leave", request_id)
            return AgentResult(response=f"Approval status for {request_id}: {status}.")


        return AgentResult(response="HR request received. Provide more details for policy or leave help.")


def _extract_dates(text: str) -> list[str]:
    return parse_dates(text)


def _extract_leave_type(text: str) -> str:
    if "sick leave" in text or "medical" in text or "not feeling well" in text:
        return "sick"
    if "maternity" in text:
        return "maternity"
    if "paternity" in text:
        return "paternity"
    if "sick" in text:
        return "sick"
    if "casual" in text:
        return "casual"
    if "vacation" in text or "pto" in text:
        return "vacation"
    if "personal" in text:
        return "personal"
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
        "wfh",
        "maternity",
        "maternal",
        "casual leave",
        "manager available",
        "approval workflow",
    ]
    return any(keyword in text for keyword in keywords)


def _normalize_query(text: str) -> str:
    lowered = text.lower()
    replacements = {
        "poicy": "policy",
        "polcy": "policy",
        "maternal": "maternity",
        "wfh": "work from home",
        "aplly": "apply",
        "aply": "apply",
        "lev": "leave",
        "leev": "leave",
        "cancle": "cancel",
        "tomorw": "tomorrow",
        "balnce": "balance",
        "req ": "request ",
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


def _is_cancel_request(query: str) -> bool:
    return _contains_any(query, ["cancel", "withdraw", "revoke", "abort", "undo", "take back"])


def _is_leave_apply_request(query: str, intent_type: str) -> bool:
    if _contains_any(query, ["work from home instead", "convert", "wfh instead"]):
        return False
    explicit_action = _contains_any(query, ["apply", "request", "raise", "book", "submit", "schedule", "put", "mark"])
    implicit_action = _contains_any(
        query,
        [
            "i need",
            "need leave",
            "want leave",
            "take leave",
            "leave tomorrow",
            "cannot come tomorrow",
            "can't come tomorrow",
            "not available",
            "out of office",
            "need off",
            "mark me absent",
            "i won't come",
        ],
    )
    leave_signal = _contains_any(query, ["leave", "vacation", "pto", "absent", "off"])
    return (intent_type == "action" and leave_signal and explicit_action) or (leave_signal and implicit_action)


def _is_leave_signal_query(query: str) -> bool:
    leave_signal = _contains_any(query, ["leave", "vacation", "pto", "absent", "off"])
    status_signal = _contains_any(
        query,
        ["balance", "history", "summary", "quota", "remaining", "pending", "status", "approved", "rejected", "cancel", "withdraw", "enough"],
    )
    return leave_signal and not status_signal


def _is_leave_balance_request(query: str) -> bool:
    return _contains_any(
        query,
        [
            "leave balance",
            "balance",
            "remaining",
            "available leave",
            "leave quota",
            "available pto",
            "how many leaves",
            "leave stats",
        ],
    )


def _is_leave_history_request(query: str) -> bool:
    return _contains_any(query, ["leave history", "history", "leave summary", "summary", "past leave", "leave report", "leave records", "transactions", "logs"])


def _is_pending_request(query: str) -> bool:
    return _contains_any(query, ["pending", "awaiting", "open request", "under review", "waiting"]) and _contains_any(query, ["leave", "approval", "request"])


def _is_approval_status_request(query: str) -> bool:
    return _contains_any(query, ["approval status", "status", "approved yet", "manager approve", "track", "progress", "workflow"])


def _latest_leave_id(user_id: str, status: str | None = None) -> int | None:
    leaves = sql.list_leaves(user_id, status=status)
    if not leaves:
        return None
    return int(leaves[-1]["id"])


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _extract_balance_threshold(query: str) -> int | None:
    match = re.search(r"balance\s*(?:is\s*)?(?:>|greater than)\s*(\d+)", query)
    if match:
        return int(match.group(1))
    if "if balance is available" in query or "only if balance is available" in query:
        return 0
    return None


def _extract_reason(query: str) -> str:
    reason_signals = {
        "family function": "family function",
        "medical": "medical reasons",
        "not feeling well": "not feeling well",
        "emergency": "emergency",
        "exam": "exams",
        "marriage": "marriage function",
        "personal": "personal reasons",
    }
    for signal, reason in reason_signals.items():
        if signal in query:
            return reason
    return ""


def _is_enough_leave_request(query: str) -> bool:
    return ("enough" in query and "leave" in query) or bool(re.search(r"\b\d+\s*days?\b", query) and "leave" in query)


def _extract_required_days(query: str) -> int | None:
    match = re.search(r"\b(\d+)\s*days?\b", query)
    if not match:
        return None
    return int(match.group(1))


def _notify_manager_if_needed(
    request_id: int,
    approval_id: int | None,
    user_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
) -> None:
    config = get_config()
    if not config.power_automate_url or not config.manager_email:
        return
    payload = build_approval_notification_payload(
        event="approval_pending",
        entity_type="leave_request",
        entity_id=request_id,
        approval_id=approval_id,
        approval_stage="manager_approval",
        approval_status="pending",
        requested_by_user_id=user_id,
        approver_role="manager",
        approver_email=config.manager_email,
        request_details={
            "leave_type": leave_type,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    send_power_automate_notification(config.power_automate_url, payload)
