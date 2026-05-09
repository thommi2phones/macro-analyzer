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
from macro_positioning.prices.fetcher import load_recent_prices
from macro_positioning.prices.technicals import (
    compute_technical_features,
    compute_volume_features,
)
from macro_positioning.scoring.mention_extractor import count_mentions
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


# ---------------------------------------------------------------------------
# Heuristic-scorer feature preloaders (one network/disk read per pass,
# results cached on the runner object so each ticker's SetupContext can
# pull instantly).
# ---------------------------------------------------------------------------

_BULLISH_FRAMEWORK_REGIMES = {
    "risk_on_expansion",
    "commodity_led_inflation",
    "monetary_debasement_hard_asset",
}


def _load_benchmarks_config() -> dict:
    """Load config/benchmarks.json. Falls back to a default mapping
    if the file is missing (keeps tests/dev environments quiet)."""
    cfg_path = settings.base_dir / "config" / "benchmarks.json"
    try:
        with cfg_path.open() as f:
            return json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"default": "SPY", "by_asset_class": {}}


def _load_asset_themes_config() -> dict:
    cfg_path = settings.base_dir / "config" / "asset_themes.json"
    try:
        with cfg_path.open() as f:
            return json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"themes": {}}


def _build_ticker_to_themes(asset_themes_cfg: dict) -> dict[str, list[str]]:
    """Reverse-index theme config so we can ask 'what themes is URA in?'"""
    out: dict[str, list[str]] = {}
    themes = asset_themes_cfg.get("themes", {})
    for theme_key, theme_def in themes.items():
        for ticker in theme_def.get("watchlist_tickers", []) or []:
            out.setdefault(ticker.upper(), []).append(theme_key)
    return out


def _build_theme_signals(
    docs: list[dict],
    asset_themes_cfg: dict,
    *,
    window_days: int = 30,
) -> tuple[dict[str, float], float]:
    """Aggregate weighted mentions per theme. Returns (signals, scale).

    `scale` = 75th percentile of theme scores so the sector_theme scorer
    can normalize. Falls back to max(scores) when only a few themes are
    populated.
    """
    try:
        wm = count_mentions(docs, window_days=window_days)
    except Exception:
        return {}, 0.0

    weighted_by_ticker: dict[str, float] = {
        c.ticker.upper(): float(c.weighted_score)
        for c in getattr(wm, "counts", [])
    }

    theme_scores: dict[str, float] = {}
    for theme_key, theme_def in asset_themes_cfg.get("themes", {}).items():
        s = 0.0
        for tk in theme_def.get("watchlist_tickers", []) or []:
            s += weighted_by_ticker.get(tk.upper(), 0.0)
        theme_scores[theme_key] = s

    scores_sorted = sorted(theme_scores.values())
    if not scores_sorted or all(v == 0 for v in scores_sorted):
        scale = 0.0
    else:
        # 75th percentile
        idx = int(0.75 * (len(scores_sorted) - 1))
        scale = scores_sorted[idx] or max(scores_sorted)
    return theme_scores, scale


def _benchmark_for(asset_class: str, benchmarks_cfg: dict) -> str:
    by_class = benchmarks_cfg.get("by_asset_class", {})
    return by_class.get(asset_class) or benchmarks_cfg.get("default") or "SPY"


def _preload_benchmark_returns(
    benchmark_tickers: set[str],
    conn: sqlite3.Connection,
) -> dict[str, float]:
    """Fetch each benchmark's 20d % return once. Missing data → omitted."""
    out: dict[str, float] = {}
    for bt in benchmark_tickers:
        try:
            bars = load_recent_prices(bt, days=60, conn=conn)
            if len(bars) >= 21:
                last = bars[-1].close
                prior = bars[-21].close
                if prior:
                    out[bt] = (last - prior) / prior
        except Exception:
            continue
    return out


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

        # 4. Pre-load all prices BEFORE opening a write transaction.
        # Mixing reads + writes inside a single BEGIN can deadlock when
        # helpers open their own connections (see prices/fetcher.py).
        ticker_features: dict[str, dict] = {}
        ticker_volume_features: dict[str, dict] = {}
        ticker_returns_20d: dict[str, float] = {}
        for entry in resolved.entries:
            try:
                bars = load_recent_prices(entry.ticker, days=200, conn=conn)
                ticker_features[entry.ticker] = compute_technical_features(bars)
                ticker_volume_features[entry.ticker] = compute_volume_features(bars)
                if len(bars) >= 21 and bars[-21].close:
                    ticker_returns_20d[entry.ticker] = (
                        bars[-1].close - bars[-21].close
                    ) / bars[-21].close
            except Exception:
                ticker_features[entry.ticker] = {"n_bars": 0}
                ticker_volume_features[entry.ticker] = {"n_volume_bars": 0}

        # Theme rollup (one pass over docs)
        asset_themes_cfg = _load_asset_themes_config()
        theme_signals, theme_scale = _build_theme_signals(recent_docs, asset_themes_cfg)
        ticker_to_themes = _build_ticker_to_themes(asset_themes_cfg)

        # Benchmarks (preload returns once per benchmark ticker)
        benchmarks_cfg = _load_benchmarks_config()
        needed_benchmarks = {
            _benchmark_for(e.asset_class or "equity", benchmarks_cfg)
            for e in resolved.entries
        }
        benchmark_returns = _preload_benchmark_returns(needed_benchmarks, conn)

        # Liquidity snapshot — FCI series not persisted in this repo's
        # SQLite yet (fred_provider returns latest-only, no history).
        # Pass a "missing" payload; scorer falls back to 0.5 with note.
        regime_bullish = regime.framework_regime in _BULLISH_FRAMEWORK_REGIMES
        liquidity_payload = {
            "nfci_latest": None,
            "nfci_4w_change": None,
            "regime_bullish": regime_bullish,
            "source": "missing",
        }

        # 5. Score each + persist
        errors: list[dict] = []
        scored_count = 0
        persisted_count = 0

        if persist:
            conn.execute("BEGIN")

        try:
            for entry in resolved.entries:
                try:
                    feats = ticker_features.get(entry.ticker, {"n_bars": 0})
                    last_close = feats.get("close")
                    atr14 = feats.get("atr14")

                    # Synthesize entry/stop/target from price + ATR
                    # Convention: entry = current close; stop = 2x ATR
                    # below; target = entry + 3R (for a 3:1 R/R prior).
                    # Once we add side-aware logic (LONG vs SHORT), this
                    # heuristic gets directionally specific.
                    if last_close and atr14 and atr14 > 0:
                        entry_zone = float(last_close)
                        stop_loss = float(last_close - 2 * atr14)
                        risk = entry_zone - stop_loss
                        target = float(entry_zone + 3 * risk)
                    else:
                        entry_zone = None
                        stop_loss = None
                        target = None

                    bench_ticker = _benchmark_for(
                        entry.asset_class or "equity", benchmarks_cfg
                    )
                    rs_features = {
                        "ticker_pct20d": ticker_returns_20d.get(entry.ticker),
                        "benchmark_pct20d": benchmark_returns.get(bench_ticker),
                        "benchmark_ticker": bench_ticker,
                    }
                    asset_themes = ticker_to_themes.get(entry.ticker.upper(), [])
                    theme_payload = {
                        "theme_signals": theme_signals,
                        "asset_themes": asset_themes,
                        "scale": theme_scale,
                    }

                    setup = SetupContext(
                        setup_id=f"setup-{entry.ticker.lower()}-{run_id[:8]}",
                        asset_ticker=entry.ticker,
                        asset_class=entry.asset_class or "equity",
                        setup_type="",
                        active_regime=regime,
                        entry_zone=entry_zone,
                        stop_loss=stop_loss,
                        target=target,
                        psychology_state={},
                        technical_features=feats,
                        volume_features=ticker_volume_features.get(
                            entry.ticker, {"n_volume_bars": 0}
                        ),
                        theme_signals=theme_payload,
                        relative_strength_features=rs_features,
                        liquidity_features=liquidity_payload,
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
