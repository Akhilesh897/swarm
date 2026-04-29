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
        return AgentResult(response="Provide approval id to process.")
