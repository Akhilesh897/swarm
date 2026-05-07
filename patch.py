with open("src/graph/workflow.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)
    graph.add_node("preprocess", _preprocess)
    graph.add_node("rbac", _rbac)
    graph.add_node("route", _route)
    graph.add_node("agent", _agent)
    graph.add_node("memory", _memory)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "rbac")
    graph.add_conditional_edges("rbac", _after_rbac, {"memory": "memory", "route": "route"})
    graph.add_edge("route", "agent")
    graph.add_edge("agent", "memory")
    graph.add_edge("memory", END)

    return graph.compile()"""

target_crlf = target.replace("\n", "\r\n")

replacement = """def _synthesize(state: GraphState) -> GraphState:
    from src.core.generator import generate_final_response
    import logging
    logging.info(f"[BACKEND RESULT] {state.get('response', '')}")
    if state.get("response") == "Access denied for this request.":
        return state
    final = generate_final_response(state.get("query", ""), state.get("response", ""), state.get("session_id", ""))
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

    return graph.compile()"""

if target in content:
    content = content.replace(target, replacement)
elif target_crlf in content:
    content = content.replace(target_crlf, replacement.replace("\n", "\r\n"))
else:
    print("Could not find target content")

with open("src/graph/workflow.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Done patching workflow.py")
