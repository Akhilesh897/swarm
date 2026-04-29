import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    app_env: str
    ollama_base_url: str
    ollama_model_fast: str
    ollama_model_balanced: str
    ollama_model_strong: str
    power_automate_email_url: str
    app_db_path: str
    vector_db_path: str
    jwt_secret: str


def get_config() -> AppConfig:
    return AppConfig(
        app_name=os.getenv("APP_NAME", "Enterprise Multi-Agent Copilot"),
        app_env=os.getenv("APP_ENV", "dev"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model_fast=os.getenv("OLLAMA_MODEL_FAST", "llama3:8b"),
        ollama_model_balanced=os.getenv("OLLAMA_MODEL_BALANCED", "mistral:7b"),
        ollama_model_strong=os.getenv("OLLAMA_MODEL_STRONG", "deepseek-coder:6.7b"),
        power_automate_email_url=os.getenv("POWER_AUTOMATE_EMAIL_URL", ""),
        app_db_path=os.getenv("APP_DB_PATH", "./data/app.db"),
        vector_db_path=os.getenv("VECTOR_DB_PATH", "./data/vector_db"),
        jwt_secret=os.getenv("JWT_SECRET", "replace_me"),
    )
