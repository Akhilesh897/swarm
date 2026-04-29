from src.agents.analytics_agent import AnalyticsAgent
from src.agents.approval_agent import ApprovalAgent
from src.agents.email_agent import EmailAgent
from src.agents.finance_agent import FinanceAgent
from src.agents.hr_agent import HRAgent
from src.agents.it_agent import ITAgent
from src.agents.rag_agent import RAGAgent
from src.agents.router_agent import GeneralAgent

AGENT_REGISTRY = {
    "hr": HRAgent(),
    "it": ITAgent(),
    "finance": FinanceAgent(),
    "rag": RAGAgent(),
    "approval": ApprovalAgent(),
    "email": EmailAgent(),
    "analytics": AnalyticsAgent(),
    "general": GeneralAgent(),
}
