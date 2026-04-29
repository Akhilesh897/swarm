from src.agents.base import AgentResult, BaseAgent
from src.tools import sql


class ITAgent(BaseAgent):
    name = "it"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "").lower()
        if any(k in query for k in ["ticket", "issue", "problem"]):
            issue_type = _infer_issue_type(query)
            ticket_id = sql.create_ticket(state["user_id"], issue_type, "medium")
            return AgentResult(response=f"Ticket created with id {ticket_id} for {issue_type}.")

        if any(k in query for k in ["asset", "laptop", "monitor", "keyboard", "mouse"]):
            asset_type = _infer_asset_type(query)
            asset_id = sql.request_asset(state["user_id"], asset_type)
            return AgentResult(
                response=f"Asset request {asset_id} submitted for {asset_type}. Approval required.",
                approval_required=True,
            )

        return AgentResult(response="IT request received. Provide details for ticket or asset needs.")


def _infer_issue_type(query: str) -> str:
    if "vpn" in query:
        return "vpn"
    if "email" in query or "outlook" in query:
        return "email"
    if "printer" in query:
        return "printer"
    if "network" in query:
        return "network"
    return "general"


def _infer_asset_type(query: str) -> str:
    for asset in ["laptop", "monitor", "keyboard", "mouse", "vpn token"]:
        if asset in query:
            return asset
    return "laptop"
