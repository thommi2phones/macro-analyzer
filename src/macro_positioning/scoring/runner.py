"""Scoring runner — loops the resolved watchlist through the brain
orchestrator and persists results to the `trade_scores` table.

Triggered manually via `macro-positioning score run` or scheduled
(future: midday + post-close cron entries).

Flow:
  1. Load active regime (macro_brain regime_classifier — currently stub)
  2. Pull recent documents from SQLite
  3. resolve_watchlist(regime, documents) → list of WatchlistEntry
  4. For each entry, build a SetupContext + call compose()
  5. Persist each TradeScore as a row in `trade_scores`
  6. Return a summary the caller can render

Design note: the SetupContext we build here is intentionally light.
The brain returns mostly stub sub-scores. Once the LLM agents land
in Phase 6c, the same SetupContext schema gets richer — no caller
changes needed.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.scoring.watchlist_resolver import (
    ResolvedWatchlist,
    WatchlistEntry,
    resolve_watchlist,
)

from macro_brain.agents.regime_classifier.classifier import classify_regime_stub
from macro_brain.orchestrator.composer import compose
from macro_brain.types import SetupContext, TradeScore


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ScoringRunSummary(BaseModel):
    run_id: str
    started_at: str
    finished_at: str
    framework_regime: str
    thesis_regime: str
    watchlist_size: int
    scored: int
    persisted: int
    errors: list[dict] = Field(default_factory=list)
    mention_summary: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    initialize_database(settings.sqlite_path)
    return sqlite3.connect(settings.sqlite_path)


def _load_recent_documents(conn: sqlite3.Connection, since_days: int = 90) -> list[dict]:
    """Pull documents from the last `since_days` days. Light projection."""
    cutoff = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()
    cur = conn.execute(
        """
        SELECT source_id, title, cleaned_text, published_at
        FROM documents
        WHERE published_at >= ?
        ORDER BY published_at DESC
        """,
        (cutoff,),
    )
    rows = cur.fetchall()
    return [
        {
            "source_id": r[0],
            "title": r[1],
            "cleaned_text": r[2],
            "published_at": r[3],
        }
        for r in rows
    ]


def _persist_trade_score(
    conn: sqlite3.Connection,
    *,
    score: TradeScore,
    asset_id: str,
    asset_ticker: str,
    asset_class: str,
    origins: list[str],
) -> None:
    """Insert one row into trade_scores. Caller wraps in a transaction.

    Notes:
    - We need an `assets` row to satisfy the FK; upsert via INSERT OR IGNORE.
    - We need a `technical_setups` row to satisfy the FK on trade_scores.setup_id;
      synthesize a placeholder row keyed by setup_id (orchestrator already
      generated one).
    - reasoning_trail_json captures the watchlist origins so the dashboard
      can show *why* each ticker is here.
    """
    now_iso = datetime.now(UTC).isoformat()

    # Upsert asset
    conn.execute(
        """
        INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class)
        VALUES (?, ?, ?, ?)
        """,
        (asset_id, asset_ticker, asset_ticker, asset_class or "equity"),
    )

    # Synthesize a placeholder technical_setup row so the FK is valid.
    setup_id = score.setup_id or f"setup-{asset_id}-{uuid.uuid4().hex[:8]}"
    conn.execute(
        """
        INSERT OR IGNORE INTO technical_setups (
            setup_id, asset_id, observed_at, timeframe, setup_type,
            market_structure, technical_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            setup_id,
            asset_id,
            now_iso,
            "1D",
            "watchlist_scoring_pass",
            "neutral",
            score.technical_structure_score,
        ),
    )

    # Annotate reasoning_trail with the watchlist origins so the dashboard
    # can render a "why this ticker?" pill.
    annotated_trail = dict(score.reasoning_trail or {})
    annotated_trail["watchlist_origins"] = origins

    conn.execute(
        """
        INSERT INTO trade_scores (
            score_id, setup_id, scored_at, regime_id,
            macro_alignment_score, liquidity_score, sector_theme_score,
            technical_structure_score, volume_flow_score, risk_reward_score,
            relative_strength_score, psychology_score,
            raw_total_score, adjusted_total_score,
            grade, position_size_tier,
            feature_vector_json, reasoning_trail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            score.score_id,
            setup_id,
            score.scored_at.isoformat() if hasattr(score.scored_at, "isoformat") else str(score.scored_at),
            score.regime_id,
            score.macro_alignment_score,
            score.liquidity_score,
            score.sector_theme_score,
            score.technical_structure_score,
            score.volume_flow_score,
            score.risk_reward_score,
            score.relative_strength_score,
            score.psychology_score,
            score.raw_total_score,
            score.adjusted_total_score,
            score.grade,
            score.position_size_tier,
            None,  # feature_vector_json — TODO once feature_vector helper persisted
            json.dumps(annotated_trail, default=str),
        ),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_scoring_pass(
    *,
    framework_regime_hint: str | None = None,
    persist: bool = True,
    docs_window_days: int = 90,
) -> ScoringRunSummary:
    """End-to-end scoring pass.

    Args:
      framework_regime_hint: optional override for the regime classifier.
        Use this to backtest "what would the dashboard look like in
        risk_off_contraction?" without changing the classifier state.
      persist: if False, run + return the summary but don't write to DB
        (useful for testing). Default True.
      docs_window_days: how far back to pull documents for mention
        extraction. 90d covers the longest mention window by default.
    """
    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)

    # 1. Active regime (real call — currently stub but interface stable)
    regime = classify_regime_stub(hint_thesis_regime=framework_regime_hint or "commodity_expansion")

    # 2. Load recent docs (for mention extraction)
    conn = _connect()
    try:
        recent_docs = _load_recent_documents(conn, since_days=docs_window_days)

        # 3. Resolve active watchlist
        resolved = resolve_watchlist(
            framework_regime=regime.framework_regime,
            documents=recent_docs,
        )

        # 4 + 5. Score each + persist
        errors: list[dict] = []
        scored_count = 0
        persisted_count = 0

        if persist:
            conn.execute("BEGIN")

        try:
            for entry in resolved.entries:
                try:
                    setup = SetupContext(
                        setup_id=f"setup-{entry.ticker.lower()}-{run_id[:8]}",
                        asset_ticker=entry.ticker,
                        asset_class=entry.asset_class or "equity",
                        setup_type="",  # leave blank; brain will treat as neutral
                        active_regime=regime,
                        # Light defaults — the brain stubs the components we
                        # don't have data for. Once we add live price fetch,
                        # these become real.
                        entry_zone=None,
                        stop_loss=None,
                        target=None,
                        psychology_state={},
                    )
                    score = compose(setup)
                    scored_count += 1

                    if persist:
                        _persist_trade_score(
                            conn,
                            score=score,
                            asset_id=f"asset-{entry.ticker.lower()}",
                            asset_ticker=entry.ticker,
                            asset_class=entry.asset_class or "equity",
                            origins=entry.origins,
                        )
                        persisted_count += 1
                except Exception as exc:
                    errors.append({"ticker": entry.ticker, "error": f"{type(exc).__name__}: {exc}"})

            if persist:
                conn.execute("COMMIT")
        except Exception:
            if persist:
                conn.execute("ROLLBACK")
            raise

        finished_at = datetime.now(UTC)
        return ScoringRunSummary(
            run_id=run_id,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            framework_regime=regime.framework_regime,
            thesis_regime=regime.thesis_regime,
            watchlist_size=resolved.total_count,
            scored=scored_count,
            persisted=persisted_count,
            errors=errors,
            mention_summary=resolved.mention_summary,
        )
    finally:
        conn.close()
