def generate_final_response(query: str, backend_result: str, session_id: str) -> str:
    import os
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return backend_result

    prompt = f"USER QUERY:\n{query}\n\n"
    prompt += f"RESULT OF EXECUTING BACKEND ACTION FOR THIS QUERY:\n{backend_result}\n\n"
    prompt += "Please provide a natural, conversational response based ONLY on the result above. Explain the result to the user gently. The action has ALREADY been performed, do not say you will process it."

    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are an internal enterprise AI assistant.\nYour goal is to provide conversational, natural, and helpful responses to employees.\n\nRULES:\n1. NEVER expose raw database IDs, boolean flags, or JSON directly. Humanize them.\n2. If a request is rejected, explain it gently and clearly.\n3. Do not hallucinate policies or actions. ONLY rely on the provided result."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=500
    )
    return completion.choices[0].message.content

query = "apply leave from jan 12,2026 to jan 13,2026"
backend_result = "Leave request 43 is rejected. Approval required: False. Start date cannot be in the past."

response = generate_final_response(query, backend_result, "test_session_id")
print("---------")
print("Response:")
print(response)
print("---------")
