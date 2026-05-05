from src.agents.base import AgentResult, BaseAgent
from src.tools import sql


class ApprovalAgent(BaseAgent):
    name = "approval"

    def handle(self, state: dict) -> AgentResult:
        query = state.get("query", "").lower()
        if "approve" in query:
            approval_id = int(state.get("approval_id", 0))
            sql.approve_request(approval_id, state.get("user_id", ""), "approved")
            return AgentResult(response=f"Approval {approval_id} recorded.")
        if "reject" in query:
            approval_id = int(state.get("approval_id", 0))
            sql.approve_request(approval_id, state.get("user_id", ""), "rejected")
            return AgentResult(response=f"Approval {approval_id} rejected.")
        if "status" in query:
            request_id = int(state.get("request_id", 0))
            status = sql.get_approval_status("leave", request_id)
            return AgentResult(response=f"Approval status for {request_id}: {status}.")
        return AgentResult(response="Provide approval id to process.")
