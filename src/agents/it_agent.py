import httpx

from src.agents.base import AgentResult, BaseAgent
from src.config import get_config
from src.tools import sql

IT_ROLE = "it"


class ITAgent(BaseAgent):
    name = "it"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "").lower()
        role = state.get("role", "employee")
        intent_type = state.get("intent_type", "other")
        user_id = state["user_id"]

        if "inventory" in query:
            if role != IT_ROLE:
                return AgentResult(response="Access denied. Inventory tools are available only to the IT team.")
            inventory = sql.get_inventory()
            if not inventory:
                return AgentResult(response="Inventory is empty.")
            lines = [f"- {item['asset_type']}: {item['quantity']} available" for item in inventory]
            return AgentResult(response="Inventory:\n" + "\n".join(lines))

        if any(k in query for k in ["assign ticket", "assign"]):
            if role != IT_ROLE:
                return AgentResult(response="Access denied. Only IT can assign tickets.")
            ticket_id = _extract_id(query)
            engineer = _extract_engineer(query) or user_id
            if not ticket_id:
                return AgentResult(response="Please provide the ticket id to assign.")
            status = sql.assign_ticket(ticket_id, engineer)
            return AgentResult(response=f"Ticket {ticket_id} assignment status: {status}.")

        if any(k in query for k in ["resolve ticket", "close ticket", "resolved"]):
            if role != IT_ROLE:
                return AgentResult(response="Access denied. Only IT can resolve tickets.")
            ticket_id = _extract_id(query)
            if not ticket_id:
                return AgentResult(response="Please provide the ticket id to resolve.")
            status = sql.resolve_ticket(ticket_id, user_id)
            return AgentResult(response=f"Ticket {ticket_id} resolution status: {status}.")

        if any(k in query for k in ["list tickets", "my tickets", "ticket status", "track ticket", "all tickets"]):
            if "all" in query and role != IT_ROLE:
                return AgentResult(response="Access denied. Employees can view only their own tickets.")
            tickets = sql.list_tickets(user_id, role)
            if not tickets:
                return AgentResult(response="No tickets found.")
            lines = [
                f"- {row['id']}: {row['issue_type']} ({row['priority']}, {row['status']}) assigned to {row['assigned_engineer'] or 'unassigned'}"
                for row in tickets[:10]
            ]
            return AgentResult(response="Tickets:\n" + "\n".join(lines))

        if intent_type == "action" and any(k in query for k in ["asset", "laptop", "monitor", "keyboard", "mouse", "vpn token", "software license"]):
            asset_type = _infer_asset_type(query)
            result = sql.request_asset(user_id, asset_type)
            _trigger_it_approval_flow(result, user_id, asset_type)
            return AgentResult(
                response=(
                    f"Asset request {result.asset_id} submitted for {asset_type}. "
                    f"Approval id: {result.approval_id}. "
                    "Approval flow: manager approval -> IT approval -> inventory validation -> fulfillment."
                ),
                approval_required=True,
            )

        if intent_type == "action" and any(k in query for k in ["ticket", "issue", "problem", "vpn", "outlook", "email", "printer", "network", "software"]):
            issue_type = _infer_issue_type(query)
            priority = _infer_priority(query)
            result = sql.create_it_ticket_with_checks(user_id, issue_type, priority, detail=state.get("query", ""))
            if result.status == "created":
                return AgentResult(response=f"{result.detail} Priority: {priority}. Status: open.")
            return AgentResult(response=result.detail)

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
    if "software" in query or "install" in query or "installation" in query:
        return "software"
    if "laptop" in query:
        return "laptop"
    return "general"


def _infer_asset_type(query: str) -> str:
    for asset in ["software license", "vpn token", "laptop", "monitor", "keyboard", "mouse"]:
        if asset in query:
            return asset
    return "laptop"


def _infer_priority(query: str) -> str:
    if any(word in query for word in ["urgent", "critical", "down", "blocked"]):
        return "high"
    if any(word in query for word in ["low", "minor"]):
        return "low"
    return "medium"


def _extract_id(query: str) -> int | None:
    import re

    match = re.search(r"\b(\d+)\b", query)
    return int(match.group(1)) if match else None


def _extract_engineer(query: str) -> str | None:
    import re

    match = re.search(r"(?:to|engineer)\s+([a-zA-Z0-9_.@-]+)", query)
    return match.group(1) if match else None


def _trigger_it_approval_flow(result: sql.AssetRequestResult, user_id: str, asset_type: str) -> None:
    config = get_config()
    if not config.power_automate_it_url:
        return
    payload = {
        "approval_id": result.approval_id,
        "asset_id": result.asset_id,
        "user_id": user_id,
        "asset_type": asset_type,
        "approval_stage": result.approval_stage,
    }
    httpx.post(config.power_automate_it_url, json=payload, timeout=10)
