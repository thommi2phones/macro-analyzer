"""Operational dashboard data collection.

Gathers project health, component status, data source connectivity,
database stats, and task backlog into a JSON-serializable structure.
"""

from __future__ import annotations

import importlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from macro_positioning.core.models import utc_now
from macro_positioning.core.settings import settings


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class ComponentStatus(BaseModel):
    name: str
    status: str  # "ready", "partial", "not_started", "error"
    detail: str = ""
    priority: str = "medium"  # "high", "medium", "low"


class DataSourceHealth(BaseModel):
    name: str
    connected: bool
    detail: str = ""
    series_count: int | None = None
    last_checked: datetime = Field(default_factory=utc_now)


class DatabaseStats(BaseModel):
    documents: int = 0
    theses: int = 0
    memos: int = 0
    latest_memo_at: str | None = None
    latest_thesis_at: str | None = None
    db_size_kb: float = 0.0


class TaskItem(BaseModel):
    title: str
    category: str  # "data", "pipeline", "dashboard", "integration", "infra"
    priority: str  # "critical", "high", "medium", "low"
    status: str  # "done", "in_progress", "todo"
    detail: str = ""


class OpsSnapshot(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    environment: str = ""
    python_version: str = ""
    components: list[ComponentStatus] = Field(default_factory=list)
    data_sources: list[DataSourceHealth] = Field(default_factory=list)
    db_stats: DatabaseStats = Field(default_factory=DatabaseStats)
    task_backlog: list[TaskItem] = Field(default_factory=list)
    newsletter_sources: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def _check_module(module_path: str) -> bool:
    try:
        importlib.import_module(module_path)
        return True
    except Exception:
        return False


def collect_components() -> list[ComponentStatus]:
    components = []

    # Core models
    components.append(ComponentStatus(
        name="Core Data Models",
        status="ready",
        detail="Pydantic models: Thesis, MarketObservation, PositioningMemo, etc.",
    ))

    # Settings
    components.append(ComponentStatus(
        name="Settings & Configuration",
        status="ready",
        detail=f"Environment: {settings.environment}, FRED key: {'configured' if settings.fred_api_key else 'missing'}",
    ))

    # Database
    db_ok = settings.sqlite_path.exists()
    components.append(ComponentStatus(
        name="SQLite Database",
        status="ready" if db_ok else "error",
        detail=f"Path: {settings.sqlite_path}" if db_ok else "Database file not found",
    ))

    # Heuristic extractor
    components.append(ComponentStatus(
        name="Heuristic Thesis Extractor",
        status="ready",
        detail="Keyword-based extraction with confidence scoring",
    ))

    # LLM extractor
    components.append(ComponentStatus(
        name="LLM Thesis Extractor (Claude)",
        status="not_started",
        detail="Interface defined, model-backed extraction not yet implemented",
        priority="high",
    ))

    # FRED provider
    fred_ok = bool(settings.fred_api_key)
    components.append(ComponentStatus(
        name="FRED Market Data Provider",
        status="ready" if fred_ok else "partial",
        detail="50+ series across 10 categories" if fred_ok else "API key not configured",
    ))

    # Market validation
    components.append(ComponentStatus(
        name="Market Validation Engine",
        status="ready",
        detail="Polarity scoring, alias expansion, confidence blending",
    ))

    # Gmail connector
    gmail_ok = _check_module("macro_positioning.ingestion.gmail_connector")
    components.append(ComponentStatus(
        name="Gmail Newsletter Connector",
        status="partial" if gmail_ok else "error",
        detail="10 sources configured, needs end-to-end wiring to pipeline" if gmail_ok else "Module error",
        priority="high",
    ))

    # Memo generation
    components.append(ComponentStatus(
        name="Positioning Memo Generator",
        status="ready",
        detail="Consensus, divergence, positioning, risk, validation summaries",
    ))

    # Markdown renderer
    components.append(ComponentStatus(
        name="Markdown Report Renderer",
        status="ready",
        detail="Full memo rendering with thesis tracker",
    ))

    # FastAPI
    components.append(ComponentStatus(
        name="REST API (FastAPI)",
        status="ready",
        detail="7 endpoints: health, pipeline/run, theses, memos, framework, sources",
    ))

    # Pipeline orchestrator
    components.append(ComponentStatus(
        name="Pipeline Orchestrator",
        status="ready",
        detail="End-to-end: ingest → extract → validate → recommend → memo",
    ))

    # Finnhub connector
    components.append(ComponentStatus(
        name="Finnhub News Connector",
        status="not_started",
        detail="API catalogued, connector not built",
        priority="medium",
    ))

    # Google News RSS
    components.append(ComponentStatus(
        name="Google News RSS Connector",
        status="not_started",
        detail="RSS feed URL patterns documented",
        priority="medium",
    ))

    # Scheduled refresh
    components.append(ComponentStatus(
        name="Scheduled Refresh Loop",
        status="not_started",
        detail="FRED + newsletter ingestion on a cadence",
        priority="high",
    ))

    # Alerts
    components.append(ComponentStatus(
        name="Alert System (Discord/Email)",
        status="not_started",
        detail="High-conviction thesis change notifications",
        priority="medium",
    ))

    return components


def collect_data_sources() -> list[DataSourceHealth]:
    sources = []

    # FRED
    from macro_positioning.market.fred_provider import ALL_SERIES
    sources.append(DataSourceHealth(
        name="FRED (Federal Reserve Economic Data)",
        connected=bool(settings.fred_api_key),
        detail="Live macro indicators" if settings.fred_api_key else "API key not set",
        series_count=len(ALL_SERIES),
    ))

    # Gmail newsletters
    from macro_positioning.ingestion.gmail_connector import NEWSLETTER_SOURCES
    sources.append(DataSourceHealth(
        name="Gmail Newsletter Ingestion",
        connected=False,  # Not wired end-to-end yet
        detail=f"{len(NEWSLETTER_SOURCES)} sources configured, not yet wired to pipeline",
        series_count=len(NEWSLETTER_SOURCES),
    ))

    # Finnhub
    sources.append(DataSourceHealth(
        name="Finnhub (Per-Ticker News + Sentiment)",
        connected=False,
        detail="API catalogued, connector not built",
    ))

    # Google News RSS
    sources.append(DataSourceHealth(
        name="Google News RSS",
        connected=False,
        detail="Free, no key needed — connector not built",
    ))

    # FMP
    sources.append(DataSourceHealth(
        name="FMP (Financial Modeling Prep)",
        connected=False,
        detail="Historical OHLCV — 250 calls/day free tier",
    ))

    return sources


def collect_db_stats() -> DatabaseStats:
    stats = DatabaseStats()
    db_path = settings.sqlite_path
    if not db_path.exists():
        return stats

    try:
        stats.db_size_kb = db_path.stat().st_size / 1024.0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        stats.documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        stats.theses = conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0]
        stats.memos = conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]

        row = conn.execute("SELECT generated_at FROM memos ORDER BY generated_at DESC LIMIT 1").fetchone()
        if row:
            stats.latest_memo_at = row[0]

        row = conn.execute("SELECT extracted_at FROM theses ORDER BY extracted_at DESC LIMIT 1").fetchone()
        if row:
            stats.latest_thesis_at = row[0]

        conn.close()
    except Exception:
        pass

    return stats


def collect_newsletter_sources() -> list[dict]:
    from macro_positioning.ingestion.gmail_connector import NEWSLETTER_SOURCES
    return [
        {
            "source_id": s.source_id,
            "name": s.name,
            "sender_email": s.sender_email,
            "priority": s.priority,
            "market_focus": s.market_focus,
            "tags": s.tags,
        }
        for s in NEWSLETTER_SOURCES
    ]


def collect_task_backlog() -> list[TaskItem]:
    return [
        # Done
        TaskItem(title="Core Pydantic data models", category="pipeline", priority="critical", status="done"),
        TaskItem(title="SQLite persistence layer", category="pipeline", priority="critical", status="done"),
        TaskItem(title="Heuristic thesis extractor", category="pipeline", priority="critical", status="done"),
        TaskItem(title="FRED market data provider (50+ series)", category="data", priority="critical", status="done"),
        TaskItem(title="Market validation engine (polarity + alias)", category="pipeline", priority="critical", status="done"),
        TaskItem(title="Positioning memo generator", category="pipeline", priority="high", status="done"),
        TaskItem(title="Markdown report renderer", category="pipeline", priority="high", status="done"),
        TaskItem(title="FastAPI REST API (7 endpoints)", category="infra", priority="high", status="done"),
        TaskItem(title="Pipeline orchestrator (end-to-end)", category="pipeline", priority="critical", status="done"),
        TaskItem(title="Gmail connector (10 newsletter sources)", category="data", priority="high", status="done",
                 detail="Module built, needs end-to-end wiring"),
        TaskItem(title="Source trust weighting system", category="pipeline", priority="medium", status="done"),
        TaskItem(title="Urban Kaoberg API discovery (FRED series IDs)", category="data", priority="high", status="done"),
        TaskItem(title="API catalogue documentation", category="infra", priority="medium", status="done"),

        # In Progress (was: building now — done, streamlined)
        TaskItem(title="Dashboard (ops + command center)", category="dashboard", priority="high", status="done"),

        # To Do — Critical / High
        TaskItem(title="Wire Gmail connector end-to-end", category="integration", priority="critical", status="todo",
                 detail="Connect gmail_connector.fetch_newsletters() to pipeline.run()"),
        TaskItem(title="LLM thesis extraction (Claude API)", category="pipeline", priority="critical", status="todo",
                 detail="Upgrade from heuristic keywords to model-backed extraction"),
        TaskItem(title="Scheduled refresh loop", category="infra", priority="high", status="todo",
                 detail="Cron/scheduler for FRED data + newsletter ingestion"),
        TaskItem(title="Indicator momentum z-scores", category="pipeline", priority="high", status="todo",
                 detail="Port from trading_agent: rolling z-scores on FRED series for momentum signals"),
        TaskItem(title="Source scoring system", category="pipeline", priority="high", status="todo",
                 detail="Track source accuracy over time, adjust trust weights dynamically"),

        # To Do — Medium
        TaskItem(title="Finnhub news connector", category="data", priority="medium", status="todo",
                 detail="Per-ticker sentiment from Finnhub API (60 calls/min free)"),
        TaskItem(title="Google News RSS connector", category="data", priority="medium", status="todo",
                 detail="Broad macro headlines, no API key needed"),
        TaskItem(title="FMP historical price connector", category="data", priority="medium", status="todo",
                 detail="OHLCV data for technical overlays (250 calls/day free)"),
        TaskItem(title="Alert system (Discord/email)", category="infra", priority="medium", status="todo",
                 detail="Notifications for high-conviction thesis changes"),
        TaskItem(title="Multi-timeframe majority vote", category="pipeline", priority="medium", status="todo",
                 detail="Port from trading_agent: combine short/medium/long signals"),

        # To Do — Lower
        TaskItem(title="Chart analysis via Claude Vision", category="pipeline", priority="low", status="todo",
                 detail="Screenshot charts and use vision API for pattern recognition"),
        TaskItem(title="WebSocket live updates", category="dashboard", priority="low", status="todo",
                 detail="Real-time pipeline status push to dashboard"),
        TaskItem(title="Authentication & multi-user", category="infra", priority="low", status="todo"),
    ]


def build_ops_snapshot() -> OpsSnapshot:
    import platform
    return OpsSnapshot(
        environment=settings.environment,
        python_version=platform.python_version(),
        components=collect_components(),
        data_sources=collect_data_sources(),
        db_stats=collect_db_stats(),
        task_backlog=collect_task_backlog(),
        newsletter_sources=collect_newsletter_sources(),
    )
