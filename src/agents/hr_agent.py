import re
from datetime import date, timedelta

from src.agents.base import AgentResult, BaseAgent
from src.tools import sql


class HRAgent(BaseAgent):
    name = "hr"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "").lower()
        if "leave" in query and "apply" in query:
            dates = _extract_dates(query)
            if len(dates) >= 2:
                result = sql.apply_leave(
                    state["user_id"],
                    start_date=dates[0],
                    end_date=dates[1],
                    reason="",
                )
                response = (
                    f"Leave request submitted with id {result.request_id}."
                    f" Approval required: {result.approval_required}."
                )
                return AgentResult(response=response, approval_required=result.approval_required)
            return AgentResult(response="Please provide start and end dates in YYYY-MM-DD format.")

        if "leave balance" in query or "balance" in query:
            balance = sql.get_leave_balance(state["user_id"])
            return AgentResult(response=f"Your leave balance is {balance} days.")

        return AgentResult(response="HR request received. Provide more details for policy or leave help.")


def _extract_dates(text: str) -> list[str]:
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if dates:
        return dates
    # fallback: next week for two days
    start = date.today() + timedelta(days=7)
    end = start + timedelta(days=1)
    return [start.isoformat(), end.isoformat()]
