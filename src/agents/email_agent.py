import httpx

from src.agents.base import AgentResult, BaseAgent
from src.config import get_config


class EmailAgent(BaseAgent):
    name = "email"

    def handle(self, state: dict) -> AgentResult:
        config = get_config()
        if not config.power_automate_email_url:
            return AgentResult(response="Email service not configured.")

        payload = {
            "to": state.get("to", ""),
            "subject": state.get("subject", ""),
            "body": state.get("body", ""),
        }
        httpx.post(config.power_automate_email_url, json=payload, timeout=10)
        return AgentResult(response="Email sent.")
