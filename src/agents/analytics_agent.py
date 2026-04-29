from src.agents.base import AgentResult, BaseAgent
from src.tools import sql


class AnalyticsAgent(BaseAgent):
    name = "analytics"

    def handle(self, state: dict) -> AgentResult:
        sql.log_event(state.get("user_id", ""), "analytics", state.get("query", ""))
        return AgentResult(response="Analytics event logged.")
