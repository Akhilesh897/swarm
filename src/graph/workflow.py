import re
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from src.agents.registry import AGENT_REGISTRY
from src.core.memory import MemoryManager
from src.core.date_parser import parse_dates
from src.core.rbac import check_access, INTENT_GENERAL
from src.core.intent_classifier import classify_intent, classify_domain, is_question
from src.core.model_selector import resolve_model
from src.core.router import route_agent

memory_manager = MemoryManager()


class GraphState(TypedDict, total=False):
    user_id: str
    role: str
    query: str
    session_id: str
    intent: str
    intent_type: str
    model_preference: str | None
    model: str
    routed_agent: str
    response: str
    approval_required: bool
    trace_id: str
    workflow_state: str | None
    active_entities: dict[str, str]


def _preprocess(state: GraphState) -> GraphState:
    raw_query = state.get("query", "")
    session_id = state.get("session_id", "")
    
    session_state = memory_manager.get_state(session_id)
    state["workflow_state"] = session_state.get("workflow_state")
    state["active_entities"] = session_state.get("active_entities", {})
    
    history = memory_manager.get_context(session_id, limit=1)
    if history:
        last_response = history[0].get("response", "").lower()
        if "leave start and end dates" in last_response or "start and end dates before i can submit" in last_response:
            state["workflow_state"] = "awaiting_leave_dates"
        elif "issue type first" in last_response or "describe the issue a bit more" in last_response:
            state["workflow_state"] = "awaiting_ticket_issue"
        elif "business justification" in last_response or "create an asset request for this?" in last_response:
            state["workflow_state"] = "awaiting_asset_type"
            
        memory_manager.update_state(session_id, {"workflow_state": state.get("workflow_state")})
        
    query = _resolve_follow_up_query(session_id, raw_query)
    
    if not is_question(query):
        if state.get("workflow_state") == "awaiting_leave_dates" and "leave" not in query.lower():
            query = f"apply leave {query}"
        elif state.get("workflow_state") == "awaiting_ticket_issue" and not _contains_any(query.lower(), ["ticket", "issue"]):
            query = f"raise ticket {query}"
        elif state.get("workflow_state") == "awaiting_asset_type" and not _contains_any(query.lower(), ["asset", "request"]):
            query = f"request asset {query}"

    state["query"] = query
    query = _normalize_intent_query(query)
    state["intent_type"] = classify_intent(query)
    intent = classify_domain(query)
    state["intent"] = intent
    state["model"] = resolve_model(state.get("query", ""), intent, state.get("model_preference"))
    import logging
    logging.info(f"[INTENT DETECTION] Intent: {intent}, Type: {state['intent_type']}, WorkflowState: {state.get('workflow_state')}")
    return state


def _resolve_follow_up_query(session_id: str, query: str) -> str:
    normalized = _normalize_intent_query(query).strip()
    inferred = _infer_date_follow_up_action(session_id, normalized)
    if inferred:
        return inferred

    follow_up_phrases = {
        "explain briefly",
        "briefly explain",
        "explain in brief",
        "summarize",
        "summarise",
        "make it brief",
        "short answer",
    }
    if normalized not in follow_up_phrases:
        if normalized.isdigit():
            inferred = _infer_follow_up_action(session_id, normalized)
            if inferred:
                return inferred
        return query

    for message in reversed(memory_manager.get_context(session_id)):
        previous_query = str(message.get("query", "")).strip()
        if previous_query and previous_query.lower() != query.lower():
            return f"{previous_query} briefly"
    return query


def _infer_follow_up_action(session_id: str, token: str) -> str | None:
    for message in reversed(memory_manager.get_context(session_id)):
        response = str(message.get("response", "")).lower()
        if "leave request id to cancel" in response:
            return f"cancel leave request {token}"
        if "leave request id to check status" in response:
            return f"leave approval status {token}"
        if "ticket id to assign" in response:
            return f"assign ticket {token}"
        if "ticket id to resolve" in response:
            return f"resolve ticket {token}"
    return None


def _infer_date_follow_up_action(session_id: str, query: str) -> str | None:
    if not session_id or _contains_any(query, ["leave", "policy", "hr", "cancel", "withdraw"]):
        return None
    dates = parse_dates(query)
    if len(dates) < 2:
        return None
    for message in reversed(memory_manager.get_context(session_id)):
        response = str(message.get("response", "")).lower()
        routed_agent = str(message.get("routed_agent", ""))
        if routed_agent == "hr" and _asks_for_leave_dates(response):
            return f"apply leave from {dates[0]} to {dates[1]}"
    return None


def _asks_for_leave_dates(response: str) -> bool:
    return (
        "start and end dates" in response
        or "start date" in response and "end date" in response
        or "yyyy-mm-dd" in response and "leave" in response
    )


def _normalize_intent_query(query: str) -> str:
    lowered = query.lower()
    replacements = {
        "poicy": "policy",
        "polcy": "policy",
        "maternal": "maternity",
        "wfh": "work from home",
        "aplly": "apply",
        "aply": "apply",
        "lev": "leave",
        "leev": "leave",
        "cancle": "cancel",
        "tomorw": "tomorrow",
        "balnce": "balance",
        "req ": "request ",
    }
    for key, value in replacements.items():
        lowered = lowered.replace(key, value)
    return lowered


def _rbac(state: GraphState) -> GraphState:
    if not check_access(state["role"], state["intent"]):
        state["response"] = "Access denied for this request."
        state["approval_required"] = False
        return state
    return state


def _after_rbac(state: GraphState) -> str:
    if state.get("response"):
        return "memory"
    return "route"


def _route(state: GraphState) -> GraphState:
    import logging
    intent = state.get("intent", INTENT_GENERAL)
    intent_type = state.get("intent_type", "other")
    if _is_topic_reset(state.get("query", "")):
        state["routed_agent"] = route_agent(intent, intent_type)
        if state["routed_agent"] not in AGENT_REGISTRY:
            state["routed_agent"] = "general"
        logging.info(f"[AGENT ROUTING] Routed to: {state['routed_agent']}")
        return state
    if _should_use_rag(state.get("query", ""), intent_type):
        state["routed_agent"] = "rag"
        logging.info(f"[AGENT ROUTING] Routed to: {state['routed_agent']}")
        return state
    if intent == INTENT_GENERAL:
        last_agent = _last_routed_agent(state.get("session_id", ""))
        if last_agent:
            state["routed_agent"] = last_agent
            logging.info(f"[AGENT ROUTING] Routed to: {state['routed_agent']} (from STM)")
            return state
    state["routed_agent"] = route_agent(intent, intent_type)
    if state["routed_agent"] not in AGENT_REGISTRY:
        state["routed_agent"] = "general"
    logging.info(f"[AGENT ROUTING] Routed to: {state['routed_agent']}")
    return state


def _agent(state: GraphState) -> GraphState:
    agent = AGENT_REGISTRY.get(state["routed_agent"], AGENT_REGISTRY["general"])
    result = agent.handle(state)
    state["response"] = result.response
    state["approval_required"] = result.approval_required
    return state


def _memory(state: GraphState) -> GraphState:
    response = state.get("response", "").lower()
    active_entities = state.get("active_entities", {})
    
    import re
    if "ticket" in response:
        match = re.search(r"ticket\s*(\d+)", response)
        if match:
            active_entities["ticket"] = match.group(1)
    if "leave request" in response:
        match = re.search(r"leave request\s*(\d+)", response)
        if match:
            active_entities["leave_request"] = match.group(1)
    if "asset request" in response:
        match = re.search(r"asset request\s*(\d+)", response)
        if match:
            active_entities["asset_request"] = match.group(1)
            
    memory_manager.update_state(state.get("session_id", ""), {"active_entities": active_entities})

    if any(keyword in response for keyword in ["submitted", "created", "assigned", "resolved", "canceled"]):
        memory_manager.update_state(state.get("session_id", ""), {"workflow_state": None})
        
    memory_manager.add_message(
        state["session_id"],
        {
            "role": state["role"],
            "query": state["query"],
            "response": state["response"],
            "intent": state.get("intent"),
            "routed_agent": state.get("routed_agent"),
        },
    )
    memory_manager.save_long_term(state["user_id"], state["session_id"], state["query"])
    return state

def finalize_streaming_memory(state: GraphState, final_response: str) -> None:
    state["response"] = final_response
    _memory(state)


def _last_routed_agent(session_id: str) -> str | None:
    if not session_id:
        return None
    for message in reversed(memory_manager.get_context(session_id)):
        agent = message.get("routed_agent")
        if agent and agent in AGENT_REGISTRY and agent not in {"general", "rag"}:
            return agent
    return None


def _is_topic_reset(query: str) -> bool:
    text = query.lower().strip()
    reset_phrases = (
        "new request",
        "start over",
        "reset",
        "clear context",
        "switch topic",
        "change topic",
        "switch to hr",
        "switch to it",
        "switch to finance",
        "go to hr",
        "go to it",
        "go to finance",
    )
    return any(phrase in text for phrase in reset_phrases)


def _should_use_rag(query: str, intent_type: str) -> bool:
    if intent_type in {"action", "status"}:
        return False
    return is_question(query)


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)


def _synthesize(state: GraphState) -> GraphState:
    from src.core.generator import generate_final_response
    import logging
    logging.info(f"[BACKEND RESULT] {state.get('response', '')}")
    if state.get("response") == "Access denied for this request.":
        return state
    final = generate_final_response(state.get("query", ""), state.get("response", ""), state.get("session_id", ""), state)
    state["response"] = final
    return state


def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)
    graph.add_node("preprocess", _preprocess)
    graph.add_node("rbac", _rbac)
    graph.add_node("route", _route)
    graph.add_node("agent", _agent)
    graph.add_node("synthesize", _synthesize)
    graph.add_node("memory", _memory)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "rbac")
    graph.add_conditional_edges("rbac", _after_rbac, {"memory": "memory", "route": "route"})
    graph.add_edge("route", "agent")
    graph.add_edge("agent", "synthesize")
    graph.add_edge("synthesize", "memory")
    graph.add_edge("memory", END)

    return graph.compile()


def build_streaming_graph() -> StateGraph:
    graph = StateGraph(GraphState)
    graph.add_node("preprocess", _preprocess)
    graph.add_node("rbac", _rbac)
    graph.add_node("route", _route)
    graph.add_node("agent", _agent)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "rbac")
    
    def _after_rbac_stream(state: GraphState) -> str:
        if state.get("response") == "Access denied for this request.":
            return "end"
        return "route"
        
    graph.add_conditional_edges("rbac", _after_rbac_stream, {"end": END, "route": "route"})
    graph.add_edge("route", "agent")
    graph.add_edge("agent", END)

    return graph.compile()


def run_graph(user_id: str, role: str, query: str, session_id: str, model_preference: str | None = None, skip_synthesis: bool = False) -> GraphState:
    if skip_synthesis:
        graph = build_streaming_graph()
    else:
        graph = build_graph()
    trace_id = f"trace_{uuid4().hex[:8]}"
    initial_state: GraphState = {
        "user_id": user_id,
        "role": role,
        "query": query,
        "session_id": session_id,
        "trace_id": trace_id,
        "approval_required": False,
        "model_preference": model_preference,
    }
    result = graph.invoke(initial_state)
    result["trace_id"] = trace_id
    return result
