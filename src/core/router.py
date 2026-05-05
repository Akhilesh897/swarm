from src.core.rbac import INTENT_GENERAL


def route_agent(domain_intent: str, intent_type: str) -> str:
    if intent_type == "policy":
        return "rag"
    if domain_intent:
        return domain_intent
    return INTENT_GENERAL
