from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MPA_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite:///data/macro_positioning.db"
    default_horizon: str = "2-12 weeks"
    enable_heuristic_extractor: bool = True
    base_dir: Path = Field(default_factory=lambda: Path.cwd())

    fred_api_key: str = ""

    # LLM Brain — direct APIs (multi-model)
    # Primary synthesis model
    gemini_api_key: str = ""           # Google Gemini direct API key
    gemini_model: str = "gemini-2.5-pro"

    # Escalation / alternative model
    anthropic_api_key: str = ""        # Claude API key
    claude_model: str = "claude-sonnet-4-5"

    # Routing defaults
    brain_primary_backend: str = "gemini"    # gemini | anthropic | ollama
    brain_vision_backend: str = "gemini"     # gemini | anthropic
    brain_escalation_backend: str = "anthropic"  # backup tier for high-stakes

    # Ollama local (optional, dev/testing)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"

    # Legacy / optional N8N (kept for advanced workflows, not primary)
    n8n_webhook_url: str = ""
    n8n_vision_webhook_url: str = ""

    # Personal Gmail (separate from any shared project Gmail credentials)
    personal_gmail_client_id: str = ""
    personal_gmail_client_secret: str = ""
    personal_gmail_refresh_token: str = ""
    personal_gmail_token_path: str = "data/personal_gmail_token.json"

    @property
    def sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite URLs are supported in the current scaffold.")
        return self.base_dir / self.database_url.removeprefix(prefix)


settings = Settings()
