from src.agents.base import AgentResult, BaseAgent


class GeneralAgent(BaseAgent):
    name = "general"

    def handle(self, state: dict) -> AgentResult:
        return AgentResult(response="I can help with HR, IT, or Finance requests. Please clarify your request.")
