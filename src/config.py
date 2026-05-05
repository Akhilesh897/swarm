import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    app_env: str
  
    power_automate_email_url: str
    power_automate_it_url: str
    manager_email: str
    app_db_path: str
    vector_db_path: str
    hr_docs_path: str
    holiday_calendar_path: str
    openai_api_key: str
    openai_embed_model: str
    embedding_provider: str
    embedding_model: str
    reranker_model: str
    reranker_enabled: bool
    semantic_cache_threshold: float
    semantic_cache_size: int
    grok_api_url: str
    grok_api_key: str
    grok_model: str
    gemini_api_url: str
    gemini_api_key: str
    gemini_model: str
    jwt_secret: str
    inventory_min_stock: int


def get_config() -> AppConfig:
    legacy_grok_model = os.getenv("Grok_MODEL", "")
    legacy_gemini_model = os.getenv("Gemini_MODEL", "")
    grok_api_key = os.getenv("GROK_API_KEY", "")
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    if not grok_api_key and legacy_grok_model.startswith(("gsk_", "xai-")):
        grok_api_key = legacy_grok_model
    if not gemini_api_key and legacy_gemini_model.startswith("AIza"):
        gemini_api_key = legacy_gemini_model

    return AppConfig(
        app_name=os.getenv("APP_NAME", "Enterprise Multi-Agent Copilot"),
        app_env=os.getenv("APP_ENV", "dev"),
    
     
        power_automate_email_url=os.getenv("POWER_AUTOMATE_EMAIL_URL", ""),
        power_automate_it_url=os.getenv("POWER_AUTOMATE_IT_URL", ""),
        manager_email=os.getenv("MANAGER_EMAIL", ""),
        app_db_path=os.getenv("APP_DB_PATH", "./data/app.db"),
        vector_db_path=os.getenv("VECTOR_DB_PATH", "./data/vector_db"),
        hr_docs_path=os.getenv("HR_DOCS_PATH", "./data/docs"),
        holiday_calendar_path=os.getenv("HOLIDAY_CALENDAR_PATH", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "sentence_transformers"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        reranker_model=os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
        reranker_enabled=os.getenv("RERANKER_ENABLED", "true").lower() in {"1", "true", "yes"},
        semantic_cache_threshold=float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.9")),
        semantic_cache_size=int(os.getenv("SEMANTIC_CACHE_SIZE", "200")),
        grok_api_url=os.getenv("GROK_API_URL", "https://api.x.ai/v1/chat/completions"),
        grok_api_key=grok_api_key,
        grok_model=os.getenv("GROK_MODEL", "grok-2"),
        gemini_api_url=os.getenv(
            "GEMINI_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        ),
        gemini_api_key=gemini_api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        jwt_secret=os.getenv("JWT_SECRET", "replace_me"),
        inventory_min_stock=int(os.getenv("INVENTORY_MIN_STOCK", "1")),
    )
