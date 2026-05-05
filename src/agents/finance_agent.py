import re

from src.agents.base import AgentResult, BaseAgent
from src.tools import sql


class FinanceAgent(BaseAgent):
    name = "finance"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "").lower()
        intent_type = state.get("intent_type", "other")
        if intent_type in {"status", "other"} and "payslip" in query:
            return AgentResult(response="Payslip request recorded. Please specify month if needed.")

        if intent_type == "action" and ("reimbursement" in query or "claim" in query):
            amount = _extract_amount(query)
            reimb_id = sql.submit_reimbursement(state["user_id"], amount, "general")
            approval_required = amount > 5000
            return AgentResult(
                response=f"Reimbursement {reimb_id} submitted for amount {amount}.",
                approval_required=approval_required,
            )

        return AgentResult(response="Finance request received. Provide details for payslip or reimbursement.")


def _extract_amount(text: str) -> float:
    match = re.search(r"(\d+)(?:\.\d+)?", text)
    if match:
        return float(match.group(1))
    return 0.0
