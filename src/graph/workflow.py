from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from src.agents.registry import AGENT_REGISTRY
from src.core.memory import MemoryManager
from src.core.rbac import check_access, INTENT_GENERAL

memory_manager = MemoryManager()


class GraphState(TypedDict, total=False):
    user_id: str
    role: str
    query: str
    session_id: str
    intent: str
    routed_agent: str
    response: str
    approval_required: bool
    trace_id: str


def _preprocess(state: GraphState) -> GraphState:
    query = state.get("query", "").lower()
    if any(k in query for k in ["leave", "policy", "maternity", "hr"]):
        intent = "hr"
    elif any(k in query for k in ["ticket", "vpn", "laptop", "it", "asset"]):
        intent = "it"
    elif any(k in query for k in ["payslip", "reimbursement", "tax", "finance"]):
        intent = "finance"
    else:
        intent = INTENT_GENERAL
    state["intent"] = intent
    return state


def _rbac(state: GraphState) -> GraphState:
    if not check_access(state["role"], state["intent"]):
        state["response"] = "Access denied for this request."
        state["approval_required"] = False
        return state
    return state


def _route(state: GraphState) -> GraphState:
    intent = state.get("intent", INTENT_GENERAL)
    if intent in AGENT_REGISTRY:
        state["routed_agent"] = intent
    else:
        state["routed_agent"] = "general"
    return state


def _agent(state: GraphState) -> GraphState:
    agent = AGENT_REGISTRY.get(state["routed_agent"], AGENT_REGISTRY["general"])
    result = agent.handle(state)
    state["response"] = result.response
    state["approval_required"] = result.approval_required
    return state


def _memory(state: GraphState) -> GraphState:
    memory_manager.add_message(
        state["session_id"],
        {"role": state["role"], "query": state["query"], "response": state["response"]},
    )
    memory_manager.save_long_term(state["user_id"], state["session_id"], state["query"])
    return state


def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)
    graph.add_node("preprocess", _preprocess)
    graph.add_node("rbac", _rbac)
    graph.add_node("route", _route)
    graph.add_node("agent", _agent)
    graph.add_node("memory", _memory)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "rbac")
    graph.add_edge("rbac", "route")
    graph.add_edge("route", "agent")
    graph.add_edge("agent", "memory")
    graph.add_edge("memory", END)

    return graph.compile()


def run_graph(user_id: str, role: str, query: str, session_id: str) -> GraphState:
    graph = build_graph()
    trace_id = f"trace_{uuid4().hex[:8]}"
    initial_state: GraphState = {
        "user_id": user_id,
        "role": role,
        "query": query,
        "session_id": session_id,
        "trace_id": trace_id,
        "approval_required": False,
    }
    result = graph.invoke(initial_state)
    result["trace_id"] = trace_id
    return result
