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

    # Gemini via N8N — the synthesis brain
    n8n_webhook_url: str = ""          # Text analysis webhook (Gemini text/message)
    n8n_vision_webhook_url: str = ""   # Chart/image analysis webhook (Gemini image/analyze)

    @property
    def sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite URLs are supported in the current scaffold.")
        return self.base_dir / self.database_url.removeprefix(prefix)


settings = Settings()
