import httpx

from src.config import get_config


def choose_model(query: str, intent: str) -> str:
    text = query.lower().strip()
    tokens = text.split()
    short_query = len(text) <= 60 or len(tokens) <= 6

    rag_markers = (
        "policy",
        "handbook",
        "faq",
        "benefits",
        "leave",
        "rules",
        "eligibility",
    )
    action_markers = (
        "apply",
        "request",
        "create",
        "submit",
        "raise",
        "approve",
        "reject",
        "cancel",
        "withdraw",
        "ticket",
        "workflow",
        "approval",
    )
    reasoning_markers = (
        "why",
        "explain",
        "compare",
        "tradeoff",
        "pros",
        "cons",
        "root cause",
        "analyze",
        "analysis",
    )

    if any(marker in text for marker in reasoning_markers):
        return "grok"
    if any(marker in text for marker in action_markers):
        return "grok"
    if short_query:
        return "gemini"
    if any(marker in text for marker in rag_markers):
        return "gemini"
    if intent in {"hr", "finance", "it"}:
        return "gemini"
    return "gemini"


def resolve_model(query: str, intent: str, preference: str | None) -> str:
    if preference in {"grok", "gemini"}:
        return preference
    return choose_model(query, intent)


def call_model(model: str, prompt: str, timeout: float = 12.0) -> str | None:
    if model == "grok":
        response = _call_grok(prompt, timeout)
        if response:
            return response
        return _call_gemini(prompt, timeout)
    if model == "gemini":
        return _call_gemini(prompt, timeout)
    return _call_gemini(prompt, timeout)


def _call_grok(prompt: str, timeout: float) -> str | None:
    config = get_config()
    if not config.grok_api_url or not config.grok_api_key:
        return None
    payload = {
        "model": config.grok_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    return _call_endpoint(config.grok_api_url, config.grok_api_key, payload, timeout, provider="grok")


def _call_gemini(prompt: str, timeout: float) -> str | None:
    config = get_config()
    if not config.gemini_api_url or not config.gemini_api_key:
        return None
    url = config.gemini_api_url.format(model=config.gemini_model)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }
    return _call_endpoint(url, config.gemini_api_key, payload, timeout, provider="gemini")


def _call_endpoint(url: str, api_key: str, payload: dict, timeout: float, provider: str) -> str | None:
    headers = _headers(provider, api_key)
    params = {"key": api_key} if provider == "gemini" and "key=" not in url else None
    try:
        response = httpx.post(url, json=payload, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None
    return _extract_text(data)


def _headers(provider: str, api_key: str) -> dict[str, str]:
    if provider == "gemini":
        return {"x-goog-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _extract_text(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    if data.get("response") or data.get("text") or data.get("output"):
        return data.get("response") or data.get("text") or data.get("output")
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content:
            return content
    candidates = data.get("candidates") or []
    if candidates:
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        text = "\n".join(part for part in texts if part).strip()
        return text or None
    return None
