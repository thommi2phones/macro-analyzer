"""Persistent dev checklist backed by a JSON file.

Tasks can be toggled via the dashboard UI (PATCH endpoint) or
updated programmatically by code changes. The JSON file at
data/checklist.json is the single source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings


CHECKLIST_PATH = settings.base_dir / "data" / "checklist.json"


class ChecklistItem(BaseModel):
    id: str
    title: str
    detail: str = ""
    category: str = "pipeline"      # pipeline, data, integration, infra, dashboard
    priority: str = "medium"        # critical, high, medium, low
    status: str = "todo"            # todo, in_progress, done
    completed_at: str | None = None


class Checklist(BaseModel):
    items: list[ChecklistItem] = Field(default_factory=list)
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Default checklist (seeded on first run)
# ---------------------------------------------------------------------------

_DEFAULTS: list[dict] = [
    # Done
    dict(id="core-models", title="Core Pydantic data models", category="pipeline", priority="critical", status="done"),
    dict(id="sqlite-db", title="SQLite persistence layer", category="pipeline", priority="critical", status="done"),
    dict(id="heuristic-extractor", title="Heuristic thesis extractor", category="pipeline", priority="critical", status="done"),
    dict(id="fred-provider", title="FRED market data provider (50+ series)", category="data", priority="critical", status="done"),
    dict(id="market-validation", title="Market validation engine", category="pipeline", priority="critical", status="done"),
    dict(id="memo-generator", title="Positioning memo generator", category="pipeline", priority="high", status="done"),
    dict(id="markdown-renderer", title="Markdown report renderer", category="pipeline", priority="high", status="done"),
    dict(id="fastapi", title="FastAPI REST API", category="infra", priority="high", status="done"),
    dict(id="pipeline-orchestrator", title="Pipeline orchestrator (end-to-end)", category="pipeline", priority="critical", status="done"),
    dict(id="gmail-connector", title="Gmail connector (10 sources)", category="data", priority="high", status="done",
         detail="Module built, needs end-to-end wiring"),
    dict(id="trust-weights", title="Source trust weighting system", category="pipeline", priority="medium", status="done"),
    dict(id="kaoberg-discovery", title="Urban Kaoberg API discovery", category="data", priority="high", status="done"),
    dict(id="api-catalogue", title="API catalogue docs", category="infra", priority="medium", status="done"),
    dict(id="dashboard", title="Dashboard (ops + command center)", category="dashboard", priority="high", status="done"),

    # To Do — Critical / High
    dict(id="gmail-e2e", title="Wire Gmail connector end-to-end", category="integration", priority="critical", status="todo",
         detail="Connect gmail_connector.fetch_newsletters() to pipeline.run()"),
    dict(id="llm-extraction", title="LLM thesis extraction (Claude API)", category="pipeline", priority="critical", status="todo",
         detail="Upgrade heuristic keywords to model-backed extraction"),
    dict(id="scheduled-refresh", title="Scheduled refresh loop", category="infra", priority="high", status="todo",
         detail="Cron/scheduler for FRED + newsletter ingestion"),
    dict(id="z-scores", title="Indicator momentum z-scores", category="pipeline", priority="high", status="todo",
         detail="Rolling z-scores on FRED series for momentum signals"),
    dict(id="source-scoring", title="Source scoring system", category="pipeline", priority="high", status="todo",
         detail="Track accuracy over time, adjust trust weights"),

    # To Do — Medium
    dict(id="finnhub", title="Finnhub news connector", category="data", priority="medium", status="todo",
         detail="Per-ticker sentiment (60 calls/min free)"),
    dict(id="gnews-rss", title="Google News RSS connector", category="data", priority="medium", status="todo",
         detail="Broad macro headlines, no key needed"),
    dict(id="fmp-prices", title="FMP historical price connector", category="data", priority="medium", status="todo",
         detail="OHLCV data for technical overlays"),
    dict(id="alerts", title="Alert system (Discord/email)", category="infra", priority="medium", status="todo",
         detail="High-conviction thesis change notifications"),
    dict(id="multi-tf-vote", title="Multi-timeframe majority vote", category="pipeline", priority="medium", status="todo",
         detail="Combine short/medium/long signals"),

    # Low
    dict(id="vision-charts", title="Chart analysis via Gemini/Vertex Vision", category="pipeline", priority="medium", status="todo",
         detail="Screenshot charts, feed to Vertex AI for pattern recognition (unlimited API)"),
    dict(id="websocket", title="WebSocket live updates", category="dashboard", priority="low", status="todo"),
    dict(id="auth", title="Authentication & multi-user", category="infra", priority="low", status="todo"),
]


def _seed_checklist() -> Checklist:
    items = [ChecklistItem(**d) for d in _DEFAULTS]
    cl = Checklist(items=items, updated_at=datetime.now(UTC).isoformat())
    save_checklist(cl)
    return cl


def load_checklist() -> Checklist:
    if not CHECKLIST_PATH.exists():
        return _seed_checklist()
    try:
        data = json.loads(CHECKLIST_PATH.read_text())
        return Checklist.model_validate(data)
    except Exception:
        return _seed_checklist()


def save_checklist(cl: Checklist) -> None:
    CHECKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    cl.updated_at = datetime.now(UTC).isoformat()
    CHECKLIST_PATH.write_text(json.dumps(cl.model_dump(), indent=2))


def toggle_item(item_id: str, new_status: str | None = None) -> ChecklistItem | None:
    """Toggle an item's status. If new_status not given, cycles: todo → in_progress → done → todo."""
    cl = load_checklist()
    for item in cl.items:
        if item.id == item_id:
            if new_status:
                item.status = new_status
            else:
                cycle = {"todo": "in_progress", "in_progress": "done", "done": "todo"}
                item.status = cycle.get(item.status, "todo")

            item.completed_at = datetime.now(UTC).isoformat() if item.status == "done" else None
            save_checklist(cl)
            return item
    return None
