import os
import logging
from openai import OpenAI
from src.core.memory import MemoryManager

memory_manager = MemoryManager()

import os
import logging
from openai import OpenAI
from src.core.memory import MemoryManager

memory_manager = MemoryManager()

def _build_dynamic_prompt(state: dict, recent_context: list, backend_result: str, query: str) -> str:
    role = state.get("role", "employee")
    workflow_state = state.get("workflow_state", "None")
    active_entities = state.get("active_entities", {})
    
    prompt = "SYSTEM PROMPT:\n"
    prompt += "You are an internal enterprise AI copilot.\n\n"
    
    # 1. ROLE-AWARE REASONING
    prompt += f"ROLE CONTEXT: The user is an '{role}'.\n"
    if role == "it_lead" or role == "it":
        prompt += "- You have full IT access. You can view, assign, and resolve any tickets.\n"
    elif role == "hr" or role == "finance":
        prompt += "- You have department-specific access. You process approvals and view department requests.\n"
    else:
        prompt += "- You are a standard employee. You can only view and manage your OWN requests and tickets.\n"
    
    # 2. CONVERSATION STATE & ENTITIES
    prompt += f"\nWORKFLOW STATE: {workflow_state}\n"
    if active_entities:
        prompt += "ACTIVE ENTITIES:\n"
        for k, v in active_entities.items():
            prompt += f"- {k}: {v}\n"
            
    # 3. RECENT MEMORY
    prompt += "\nRECENT CONVERSATION HISTORY:\n"
    if recent_context:
        for msg in recent_context:
            prompt += f"User: {msg.get('query')}\nAssistant: {msg.get('response')}\n"
    else:
        prompt += "No recent history.\n"
        
    # 4. TOOL OUTPUTS & CONTEXT
    prompt += f"\nLATEST USER MESSAGE:\n{query}\n\n"
    prompt += "BACKEND/TOOL OUTPUT:\n"
    prompt += f"{backend_result}\n\n"
    
    # 5. SELF-CORRECTION & RULES
    prompt += "RULES & REFLECTION:\n"
    prompt += "1. TOOL-FIRST REASONING: Prioritize the provided backend output. Do NOT say 'I couldn't find information' unless the tool returned empty/failed. If the tool returned data, synthesize it conversationally.\n"
    prompt += "2. CONTINUITY: Resolve pronouns (like 'them', 'it') using the conversation history or active entities.\n"
    prompt += "3. HUMANIZATION: NEVER expose raw DB IDs or JSON. Present information clearly and naturally.\n"
    prompt += "4. STRICT FACTUALITY: NEVER claim that a request, ticket, or action has been completed, created, submitted, or assigned UNLESS the BACKEND OUTPUT explicitly states that it was created/submitted. If the backend output is a clarifying question, you MUST ask the user that question and NOT pretend the action was completed.\n"
    prompt += "5. SELF-CORRECTION: Before finalizing, ask yourself: Did I answer correctly? Am I unnecessarily asking for information the user already provided? Am I hallucinating an action that the backend didn't confirm?\n"
    prompt += "6. RESPONSE QUALITY: Be operational, concise, and enterprise-grade. Avoid repetitive apologies.\n\n"
    prompt += "Synthesize the final response based ONLY on the context and rules above."
    
    return prompt

def generate_final_response(query: str, backend_result: str, session_id: str, state: dict = None, stream: bool = False):
    state = state or {}
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        if stream:
            def fallback_gen():
                yield backend_result
            return fallback_gen()
        return backend_result # Fallback if no key

    recent_context = memory_manager.get_context(session_id, limit=6)
    
    dynamic_prompt = _build_dynamic_prompt(state, recent_context, backend_result, query)

    logging.info(f"[STM INJECTION] Included {len(recent_context)} previous turns.")
    logging.info(f"[PROMPT ASSEMBLY] Generating final response dynamically.")

    try:
        logging.info(f"[GROQ REQUEST]\n{dynamic_prompt}")
        
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": dynamic_prompt}
            ],
            temperature=0.3,
            max_tokens=600,
            stream=stream
        )
        if stream:
            def stream_gen():
                for chunk in completion:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            return stream_gen()
        else:
            final_response = completion.choices[0].message.content
            logging.info(f"[GROQ RESPONSE]\n{final_response}")
            return final_response
    except Exception as e:
        logging.error(f"Groq API error: {e}")
        if stream:
            def err_gen():
                yield backend_result
            return err_gen()
        return backend_result

def _should_return_backend_result(query: str, backend_result: str) -> bool:
    normalized_query = query.lower().strip()
    normalized_result = backend_result.lower().strip()
    if not normalized_result:
        return True

    needs_more_information = (
        "please provide" in normalized_result
        or "i need to know" in normalized_result
        or "provide more details" in normalized_result
        or "please clarify" in normalized_result
    )
    if needs_more_information:
        return True

    operational_it_response = (
        "did this resolve your issue, or would you like me to raise an it ticket?" in normalized_result
        or "would you like me to create an asset request for this?" in normalized_result
        or "raise an it support ticket" in normalized_result and "create a new asset request" in normalized_result
        or "i can raise a ticket, but i need the issue type first" in normalized_result
        or "could you describe the issue a bit more?" in normalized_result
        or "it request received. provide details for ticket or asset needs." in normalized_result
        or "please share a bit more detail so i can guide the right path." in normalized_result
        or "no ticket is confirmed yet" in normalized_result
        or "i could not confirm ticket creation in the system" in normalized_result
        or normalized_result.startswith("please try:")
        or "\nplease try:\n" in normalized_result
    )
    if operational_it_response:
        return True

    ambiguous_confirmation = normalized_query in {
        "yes",
        "y",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "sure",
        "go ahead",
    }
    successful_action = (
        " is pending" in normalized_result
        or " is approved" in normalized_result
        or " is rejected" in normalized_result
        or " created" in normalized_result
        or " submitted" in normalized_result
    )
    return ambiguous_confirmation and not successful_action
