import os
import logging
from openai import OpenAI
from src.core.memory import MemoryManager

memory_manager = MemoryManager()

SYSTEM_PROMPT = """You are an internal enterprise AI assistant.
Your goal is to provide conversational, natural, and helpful responses to employees.
You have access to backend systems for HR, IT, and Finance.

RULES:
1. You will be provided with either RETRIEVED CONTEXT or a BACKEND ACTION RESULT. Use this to answer the user's query.
2. NEVER expose raw database IDs, boolean flags, or JSON directly. Humanize them.
3. If a request is rejected or overlaps, explain it gently and clearly.
4. DO NOT use markdown bullet dumps unless explicitly asked for a list. Keep it conversational.
5. Do not hallucinate policies or actions. ONLY rely on the provided context/result.
6. If the backend result says "No relevant information found", politely inform the user.
7. Maintain continuity with the RECENT CONVERSATION HISTORY.

Remember: Be conversational, helpful, and concise."""

def generate_final_response(query: str, backend_result: str, session_id: str) -> str:
    if _should_return_backend_result(query, backend_result):
        return backend_result

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return backend_result # Fallback if no key

    recent_context = memory_manager.get_context(session_id, limit=10)
    
    memory_str = ""
    if recent_context:
        memory_str = "RECENT CONVERSATION HISTORY:\n"
        for msg in recent_context:
            memory_str += f"User: {msg['query']}\nAssistant: {msg['response']}\n"
    
    prompt = f"{memory_str}\n"
    
    # Check if the result looks like RAG context or a backend result
    if "[1]" in backend_result or "source:" in backend_result:
        prompt += f"RETRIEVED CONTEXT:\n{backend_result}\n\n"
    else:
        prompt += f"BACKEND ACTION RESULT:\n{backend_result}\n\n"
        
    prompt += f"USER QUERY:\n{query}\n\nPlease provide a natural, conversational response based ONLY on the context/result above."

    logging.info(f"[STM INJECTION] Included {len(recent_context)} previous turns.")
    logging.info(f"[PROMPT ASSEMBLY] Generating final response.")

    try:
        logging.info(f"[GROQ REQUEST]\nSYSTEM: {SYSTEM_PROMPT}\nUSER: {prompt}")
        
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        final_response = completion.choices[0].message.content
        logging.info(f"[GROQ RESPONSE]\n{final_response}")
        logging.info(f"[FINAL LLM GENERATION] {final_response[:100]}...")
        return final_response
    except Exception as e:
        logging.error(f"Groq API error: {e}")
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

    deterministic_action_result = normalized_result.startswith(
        (
            "leave request ",
            "approval status ",
            "pending leave requests:",
            "no pending leave requests",
            "your leave balance ",
        )
    )
    if deterministic_action_result:
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
