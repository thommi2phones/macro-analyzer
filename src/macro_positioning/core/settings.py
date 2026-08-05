from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Guard against a footgun that once wiped the live DB: scripts intending
# to override settings with `MACRO_POSITIONING_SQLITE_PATH=...` were
# silently ignored (real prefix is `MPA_`), so the smoke DB fell back to
# the production path. Any env var with the wrong-but-plausible prefix
# now halts import — loudly — rather than silently doing the wrong thing.
_FORBIDDEN_ENV_PREFIXES = ("MACRO_POSITIONING_",)
_stray = [k for k in os.environ if k.startswith(_FORBIDDEN_ENV_PREFIXES)]
if _stray:
    raise RuntimeError(
        "Refusing to load settings: env vars "
        f"{sorted(_stray)!r} use a prefix that is silently ignored "
        "(real prefix is 'MPA_'). Rename them, e.g. "
        "MACRO_POSITIONING_SQLITE_PATH → MPA_DATABASE_URL='sqlite:///...'."
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MPA_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite:///data/macro_positioning.db"
    default_horizon: str = "2-12 weeks"
    enable_heuristic_extractor: bool = True
    base_dir: Path = Field(default_factory=lambda: Path.cwd())

    fred_api_key: str = ""
    finnhub_api_key: str = ""

    # Bearer auth for the public deployed API. Empty in dev = auth disabled.
    # Set in Render dashboard before exposing the URL. SPA same-origin
    # requests pick it up from a cookie set at /login (separate scaffolding).
    auth_token: str = ""

    # Telegram user-account API (Telethon). Used to read PE Deal Flow
    # chat messages directly — no screenshotting, no OCR. api_id +
    # api_hash come from https://my.telegram.org → API development tools.
    # Session file is a credentials artefact (gitignored).
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_path: Path = Field(
        default_factory=lambda: Path.cwd() / "data" / "telegram.session"
    )

    # Telegram channels + DMs the poller ingests from. Keys are stable
    # slugs used on the CLI (--channel feather_hands_trading). chat_id
    # is the numeric identifier from Telegram. author_display matches
    # one of the seeded entries in SEED_AUTHORS — that's how messages
    # get attributed downstream.
    #
    # is_dm=True for direct-message sources (Ari Gold). The poller
    # filters DMs to messages FROM the other party (skips the user's
    # own replies so they don't end up looking like trade calls).
    #
    # Stored in code (not env) because chat_ids are stable identifiers,
    # not secrets. Add new channels here as needed.
    telegram_channels: dict[str, dict] = Field(default_factory=lambda: {
        "feather_hands_trading": {
            "chat_id": -1001309918571, "author_display": "Feather Hands Trading", "is_dm": False,
            # Known authors inside this group. Keyed by Telegram user_id (int).
            # Run scripts/telegram_smoke_test.py to discover user_ids.
            "known_senders": {
                # "123456789": "MadDog31",
                # "987654321": "Big_Nuts",
            },
        },
        "gem_hunters": {
            "chat_id": -1002332468588, "author_display": "Gem Hunters 💎", "is_dm": False,
            "known_senders": {
                # "123456789": "joejoe55",  # populate after smoke test
            },
        },
        "og_whales": {
            "chat_id": -1001548106275, "author_display": "🐳 OG Whales 🐳", "is_dm": False,
            "known_senders": {
                # "123456789": "Big_Nuts",
            },
        },
        "the_wolf_pack": {
            "chat_id": -1002616207282, "author_display": "The Wolf Pack", "is_dm": False,
            "known_senders": {
                # "123456789": "Mark Wood",
                # "987654321": "MixinCrypto",
            },
        },
        "ari_gold": {
            "chat_id": 1073329886, "author_display": "Ari Gold", "is_dm": True,
            "known_senders": {},
        },
        "trading_operation_desk": {
            "chat_id": -1003855403507, "author_display": "Trading Operation Desk", "is_dm": False,
            "known_senders": {},
        },
    })

    # LLM Brain — direct APIs (multi-model)
    # Primary synthesis model
    gemini_api_key: str = ""           # Google Gemini direct API key
    gemini_model: str = "gemini-2.5-pro"

    # Escalation / alternative model
    anthropic_api_key: str = ""        # Claude API key
    claude_model: str = "claude-sonnet-4-5"

    # Manual-input chart vision. Default Sonnet (5x cheaper than Opus,
    # near-Opus quality on chart extraction). Override per-call (e.g.
    # MPA_VISION_MODEL=claude-opus-4-6 for high-conviction reprocessing
    # of past drops). Image preprocessing settings tame token cost on the
    # multimodal call without hurting chart legibility.
    vision_model: str = "claude-sonnet-4-6"
    vision_max_image_width: int = 1500       # downscale wider images before send
    vision_resize_target_width: int = 1024   # post-resize width
    vision_cache_enabled: bool = True        # hash-dedupe identical bytes
    # Backend: "cli" (default — uses Claude Code subscription via the
    # `claude -p` CLI, no API credits) or "api" (uses MPA_ANTHROPIC_API_KEY
    # with per-call billing). CLI is preferred when Claude Code is installed.
    vision_backend: str = "cli"
    vision_cli_path: str = "claude"          # falls back to PATH lookup
    vision_cli_max_turns: int = 4            # Read tool + answer typically needs 2
    vision_cli_timeout_s: int = 120

    # Routing defaults
    brain_primary_backend: str = "gemini"    # gemini | anthropic | ollama
    brain_vision_backend: str = "gemini"     # gemini | anthropic
    brain_escalation_backend: str = "anthropic"  # backup tier for high-stakes

    # Ollama local (optional, dev/testing)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"

    # N8N webhooks → Vertex/Gemini (primary production path — unlimited via N8N)
    n8n_webhook_url: str = ""          # text synthesis: Webhook → Gemini text/message
    n8n_vision_webhook_url: str = ""   # vision: Webhook → Gemini image/analyze
    n8n_audio_webhook_url: str = ""    # audio transcription: Webhook → Gemini audio/transcribe

    # Tactical-executor integration
    tactical_webhook_url: str = ""      # PUSH direction: regime-change alerts → tactical
    tactical_executor_url: str = ""     # PULL direction: dashboard reads tactical state (events, decisions, lifecycle)

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

    # ── Manual input layer ──────────────────────────────────────────────
    # Where chart screenshots and other manual attachments land. Created
    # lazily by the processor on first save.

    @property
    def upload_dir(self) -> Path:
        return self.base_dir / "uploads"

    @property
    def chart_upload_dir(self) -> Path:
        return self.upload_dir / "charts"


settings = Settings()
