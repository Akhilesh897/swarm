import re
import json
from src.core.model_selector import call_model

def _analyze_with_llm(query: str) -> dict:
    prompt = f"""Analyze the following user query and classify it.
Query: "{query}"

You must respond in valid JSON format with exactly these three keys:
1. "is_question": true if the user is asking for information, clarification, guidance, or policies (e.g., "what is the procedure", "which leave should I put", "how do I..."). false if they are issuing a direct command or action (e.g., "apply for leave", "create a ticket").
2. "intent_type": strictly ONE of ["policy", "action", "status", "other"].
   - "policy": Asking about rules, procedures, onboarding, handbooks, guidelines (e.g., "onboarding procedures", "which leave applies for biriyani").
   - "action": Requesting to DO something and modifying state (e.g., "apply for leave", "raise ticket", "cancel request").
   - "status": Checking existing balance, history, or ticket status.
   - "other": Greetings or unrecognized.
3. "domain": strictly ONE of ["hr", "it", "finance", "general"].
   - "hr": Leaves, HR policies, onboarding, employee benefits.
   - "it": Tickets, laptops, VPN, assets, software.
   - "finance": Expenses, reimbursements, payslips, taxes.
   - "general": Greetings or unclear.

JSON Output:"""
    
    response = call_model("grok", prompt, timeout=5.0)
    if not response:
        return {"is_question": "?" in query, "intent_type": "other", "domain": "general"}
        
    try:
        # Extract JSON from potential markdown block
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
            
        data = json.loads(json_str.strip())
        return {
            "is_question": bool(data.get("is_question")),
            "intent_type": str(data.get("intent_type", "other")).lower(),
            "domain": str(data.get("domain", "general")).lower()
        }
    except Exception:
        # Fallback to simple heuristics if parsing fails
        is_q = "?" in query or any(query.lower().strip().startswith(w) for w in ["what", "how", "when", "where", "who", "why", "which"])
        return {"is_question": is_q, "intent_type": "other", "domain": "general"}

def is_question(query: str) -> bool:
    # Use cached result if possible to avoid double LLM calls in the same flow, 
    # but for simplicity we will just rely on the LLM.
    # Actually, to avoid 2 calls, workflow.py calls classify_intent then is_question.
    # Let's just do a fast heuristic here, OR wait, _should_use_rag uses is_question.
    pass

# We will cache the analysis per query to avoid hitting the LLM twice for the same query
_cache = {}

def classify_intent(query: str) -> str:
    text = query.lower().strip()
    if text not in _cache:
        _cache[text] = _analyze_with_llm(query)
    return _cache[text]["intent_type"]

def classify_domain(query: str) -> str:
    text = query.lower().strip()
    if text not in _cache:
        _cache[text] = _analyze_with_llm(query)
    return _cache[text]["domain"]

def is_question(query: str) -> bool:
    text = query.lower().strip()
    if text not in _cache:
        _cache[text] = _analyze_with_llm(query)
    return _cache[text]["is_question"]

