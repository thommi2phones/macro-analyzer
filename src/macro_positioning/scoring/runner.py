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
from typing import Any, Optional

from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.market.fred_history import (
    change_over,
    incremental_refresh,
    latest_value,
)
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


def _load_lda_issue_themes_cfg() -> dict:
    """Load config/lda_issue_themes.json. Returns {} when missing so the
    score path safely no-ops when lobbying data isn't around."""
    path = settings.base_dir / "config" / "lda_issue_themes.json"
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _lda_issue_theme_signal(
    asset_themes_cfg: dict,
    lda_cfg: dict,
    *,
    window_days: int = 30,
) -> dict[str, float]:
    """Aggregate LDA filing_covers_issue edges into theme buckets.

    Each filing that mentions an issue mapped to a theme contributes
    `weight_per_filing` (default 1.0) to that theme. Window is bounded
    by `lobbying_edges.period` matching the most recent quarters.

    Returns {} when no LDA data exists, when the table doesn't exist,
    or when the mapping is empty. Safe to call.
    """
    mapping = lda_cfg.get("mapping") or {}
    weight = float(lda_cfg.get("weight_per_filing") or 1.0)
    if not mapping or weight <= 0:
        return {}

    themes_available = set(asset_themes_cfg.get("themes", {}).keys())
    out: dict[str, float] = {}
    try:
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT replace(to_node, 'issue:', '') AS issue,
                       count(DISTINCT filing_id) AS n
                FROM lobbying_edges
                WHERE edge_kind = 'filing_covers_issue'
                GROUP BY issue
                """
            ).fetchall()
    except sqlite3.OperationalError:
        # lobbying_edges table not yet created — first-boot DBs.
        return {}

    for row in rows:
        issue = row["issue"]
        n = int(row["n"] or 0)
        for theme in mapping.get(issue, []):
            if theme in themes_available:
                out[theme] = out.get(theme, 0.0) + weight * n
    return out


def _build_theme_signals(
    docs: list[dict],
    asset_themes_cfg: dict,
    *,
    window_days: int = 30,
    lda_cfg: Optional[dict] = None,
) -> tuple[dict[str, float], float]:
    """Aggregate weighted mentions per theme. Returns (signals, scale).

    Sources of theme weight:
      1. Ticker mentions in `docs` (insider conviction baked in via
         `mention_extractor.insider_source_weight`).
      2. LDA lobbying filings mapped via `config/lda_issue_themes.json`
         (the macro/sector tilt half of the signal).

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

    # Lobbying overlay — additive contribution per filing↔theme mapping.
    lda_cfg = lda_cfg if lda_cfg is not None else _load_lda_issue_themes_cfg()
    for theme_key, lda_score in _lda_issue_theme_signal(
        asset_themes_cfg, lda_cfg, window_days=window_days,
    ).items():
        theme_scores[theme_key] = theme_scores.get(theme_key, 0.0) + lda_score

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
    signal_aggregate: dict | None = None,
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
    if signal_aggregate:
        # Compact subset for the trail — the full aggregate goes in its
        # own column for the dashboard / learning loop.
        annotated_trail["signal_bias"] = {
            "direction": signal_aggregate.get("bias_direction"),
            "confidence": signal_aggregate.get("bias_confidence"),
            "alignment_score": signal_aggregate.get("alignment_score"),  # raw 0..10
            "n_signals": signal_aggregate.get("n_signals"),
            "dominant_catalyst": signal_aggregate.get("dominant_catalyst"),
            "weighted_points": score.signal_alignment_score,  # 0..15 into the total
        }

    conn.execute(
        """
        INSERT INTO trade_scores (
            score_id, setup_id, scored_at, regime_id,
            macro_alignment_score, liquidity_score, sector_theme_score,
            technical_structure_score, volume_flow_score, risk_reward_score,
            relative_strength_score, psychology_score,
            raw_total_score, adjusted_total_score,
            grade, position_size_tier,
            feature_vector_json, reasoning_trail_json,
            signal_alignment_score, signal_aggregate_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            # Weighted 0..15 signal_alignment contribution (matches the other
            # per-component columns). The raw 0..10 aggregate alignment_score
            # remains recoverable from signal_aggregate_json below.
            score.signal_alignment_score,
            json.dumps(signal_aggregate, default=str) if signal_aggregate else None,
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

        # Incremental FRED refresh (best-effort; never raises).
        # Skipped if no API key configured (e.g. test envs).
        if settings.fred_api_key:
            try:
                from macro_positioning.market.fred_provider import (
                    ALL_SERIES,
                    FREDMarketDataProvider,
                )
                provider = FREDMarketDataProvider()
                incremental_refresh(provider, conn, ALL_SERIES.keys())
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "FRED incremental refresh skipped", exc_info=True
                )

        # Liquidity snapshot from persisted NFCI history.
        regime_bullish = regime.framework_regime in _BULLISH_FRAMEWORK_REGIMES
        nfci_latest = latest_value(conn, "NFCI")
        nfci_4w_change = change_over(conn, "NFCI", days=28)
        liquidity_payload = {
            "nfci_latest": nfci_latest,
            "nfci_4w_change": nfci_4w_change,
            "regime_bullish": regime_bullish,
            "source": "fred:NFCI" if nfci_latest is not None else "missing",
        }

        # 4b. Per-ticker signal aggregation. Run once up front so the
        # composer sees a stable snapshot and we don't pay the join cost
        # per ticker inside the write transaction. Half-life = 14d so a
        # signal from two weeks ago is worth half a fresh one.
        from macro_positioning.signals.aggregation import (
            aggregate_for_tickers,
            directional_scale,
        )
        ticker_signal_aggregates = aggregate_for_tickers(
            (e.ticker for e in resolved.entries),
            since_days=90,
            half_life_days=14.0,
        )
        # Per-pass conviction scale — the signal_alignment scorer divides
        # net_bias by this to get its 0..1 tilt. Computed once so every
        # ticker is normalised against the same pass.
        signal_pass_scale = directional_scale(ticker_signal_aggregates)

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

                    sig_agg = ticker_signal_aggregates.get(entry.ticker.upper()) or {}
                    # Stamp the per-pass scale so the scorer normalises
                    # net_bias against this pass's own conviction spread.
                    sig_agg = {**sig_agg, "pass_scale": signal_pass_scale}
                    # Expose the signal aggregate to the composer via
                    # relevant_sources — designed for this purpose.
                    relevant_sources_payload = []
                    if sig_agg.get("top_signals"):
                        relevant_sources_payload = sig_agg["top_signals"]

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
                        relevant_sources=relevant_sources_payload,
                        signal_aggregate=sig_agg or {},
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
                            signal_aggregate=sig_agg or None,
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
