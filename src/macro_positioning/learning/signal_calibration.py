"""Trust-weight learning loop for signal authors + channels.

Closes the loop: realized trade outcomes update author and channel trust
weights so future Signals from accurate authors carry more weight in the
composer's aggregation.

Linkage model (v1, intentionally coarse):
  - For each closed trade with a realized pnl_percent, find Signal rows
    for the same asset_ticker whose extracted_at falls in the window
    [entry_date - link_window_days, entry_date]. Those signals are
    considered "in scope" for the trade.
  - Outcome direction:
        pnl_percent > +threshold → "bullish_outcome"
        pnl_percent < -threshold → "bearish_outcome"
        else                     → "neutral_outcome" (no credit)
  - Hit accounting:
        LONG/ADD signal + bullish_outcome → hit
        SHORT/HEDGE signal + bearish_outcome → hit
        EXIT/TRIM + bearish_outcome → hit (sell signal preceded a loss)
        Otherwise → miss
        WATCH / AVOID → ignored (no directional claim to credit)

Calibration update:
    precision = hits / trades_linked
    new_weight = baseline + alpha * (precision - 0.5) * 2
    clamp(new_weight, [0.4, 2.5])

`alpha` defaults to 0.5: at precision=0.75 the new weight is baseline+0.5,
at precision=0.25 the new weight is baseline-0.5. Conservative on purpose
— a few unlucky trades shouldn't tank an author.

NOT in v1:
  - per-asset-class trust differentiation
  - time-decayed precision (recent trades matter more)
  - per-catalyst trust (insider buys ≠ technical breakouts)
  - signal-side mismatch detection (signal says SHORT, user traded LONG)

Those can layer on after we have a few months of real data.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from macro_positioning.core.settings import settings


log = logging.getLogger(__name__)


# Outcome thresholds — pnl_percent below these counts as "neutral" (no
# credit for or against the signal). 0.5% is well inside the noise floor
# for daily-bar swing trades; tweak as the corpus grows.
DEFAULT_NEUTRAL_PNL_PCT = 0.5

# Side classifications. Mirrors signals.base.SignalSide.
_LONG_SIDES = {"LONG", "ADD"}
_SHORT_SIDES = {"SHORT", "HEDGE"}
_EXIT_SIDES = {"EXIT", "TRIM"}
_IGNORE_SIDES = {"WATCH", "AVOID"}


@dataclass
class CalibrationStat:
    """Per-scope (author or channel) calibration counts."""

    n_signals: int = 0
    n_trades_linked: int = 0
    n_hits: int = 0
    pnl_pct_sum: float = 0.0

    @property
    def precision(self) -> Optional[float]:
        if self.n_trades_linked <= 0:
            return None
        return self.n_hits / self.n_trades_linked

    @property
    def avg_pnl_pct(self) -> Optional[float]:
        if self.n_trades_linked <= 0:
            return None
        return self.pnl_pct_sum / self.n_trades_linked


@dataclass
class CalibrationRun:
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    n_trades_considered: int = 0
    author_stats: dict[str, CalibrationStat] = field(default_factory=dict)
    channel_stats: dict[str, CalibrationStat] = field(default_factory=dict)
    weight_updates_authors: int = 0
    weight_updates_channels: int = 0

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "n_trades_considered": self.n_trades_considered,
            "n_authors_calibrated": len(self.author_stats),
            "n_channels_calibrated": len(self.channel_stats),
            "weight_updates_authors": self.weight_updates_authors,
            "weight_updates_channels": self.weight_updates_channels,
        }


# ── Outcome classification ──────────────────────────────────────────────────


def _outcome_direction(pnl_pct: Optional[float], neutral_band: float) -> str:
    if pnl_pct is None:
        return "neutral_outcome"
    if pnl_pct > neutral_band:
        return "bullish_outcome"
    if pnl_pct < -neutral_band:
        return "bearish_outcome"
    return "neutral_outcome"


def _is_hit(side: str, outcome: str) -> Optional[bool]:
    """Return True/False if the signal is creditable; None if we ignore it."""
    side_u = (side or "").upper()
    if side_u in _IGNORE_SIDES:
        return None
    if outcome == "neutral_outcome":
        return None  # don't penalize signals when nothing moved
    if side_u in _LONG_SIDES:
        return outcome == "bullish_outcome"
    if side_u in _SHORT_SIDES:
        return outcome == "bearish_outcome"
    if side_u in _EXIT_SIDES:
        # An EXIT signal "hits" if the trade subsequently lost money.
        return outcome == "bearish_outcome"
    return None


# ── Weight update math ──────────────────────────────────────────────────────


def update_weight(
    baseline: float,
    precision: Optional[float],
    *,
    alpha: float = 0.5,
    floor: float = 0.4,
    ceiling: float = 2.5,
) -> float:
    """Map precision → trust weight using a clamped linear adjustment.

    precision=0.5 ⇒ no change. >0.5 increases, <0.5 decreases. Symmetric.
    """
    if precision is None:
        return baseline
    delta = alpha * (precision - 0.5) * 2
    return max(floor, min(ceiling, baseline + delta))


# ── DB helpers ──────────────────────────────────────────────────────────────


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or settings.sqlite_path)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _load_closed_trades_with_signals(
    conn: sqlite3.Connection,
    *,
    link_window_days: int,
    min_pnl_pct_band: float,
) -> list[dict]:
    """Closed trades + their in-scope signals.

    Returns rows of {trade_id, asset_id, ticker, entry_date, pnl_percent,
    signal_id, signal_side, author_id, source_channel}.
    """
    rows = conn.execute(
        """
        SELECT
            t.trade_id,
            t.asset_id,
            a.ticker AS ticker,
            t.entry_date,
            t.pnl_percent,
            s.signal_id,
            s.side AS signal_side,
            s.author_id,
            s.source_channel
        FROM trades t
        JOIN assets a ON a.asset_id = t.asset_id
        JOIN signals s ON s.asset_ticker = a.ticker
        WHERE t.status = 'closed'
          AND t.pnl_percent IS NOT NULL
          AND s.extracted_at <= t.entry_date
          AND s.extracted_at >= datetime(t.entry_date, '-' || ? || ' days')
        """,
        (link_window_days,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Public entry point ─────────────────────────────────────────────────────


def recompute_trust_weights(
    *,
    link_window_days: int = 30,
    neutral_band: float = DEFAULT_NEUTRAL_PNL_PCT,
    alpha: float = 0.5,
    min_signals_for_update: int = 3,
    db_path: Optional[Path] = None,
    dry_run: bool = False,
) -> CalibrationRun:
    """One calibration pass over all closed trades.

    Args:
      link_window_days: max age of a signal (vs trade entry) to count as
        "in scope" for that trade.
      neutral_band: pnl_pct inside ±band counts as no-move, no credit.
      alpha: aggressiveness of weight updates. 0.5 → ±0.5 delta at the
        precision extremes.
      min_signals_for_update: don't update a scope's weight if we've seen
        fewer than N linkable signals (avoids overreacting to a single
        trade).
      dry_run: compute but don't persist updates or history rows.
    """
    run = CalibrationRun(
        run_id=uuid.uuid4().hex,
        started_at=datetime.now(UTC).isoformat(),
    )

    with _connect(db_path) as conn:
        # Pull the joined rows up-front so we can iterate freely.
        joined = _load_closed_trades_with_signals(
            conn, link_window_days=link_window_days, min_pnl_pct_band=neutral_band,
        )
        run.n_trades_considered = len({r["trade_id"] for r in joined})

        # Per-trade, dedupe so a trade with N signals from the same author
        # doesn't get counted N times for that author.
        seen_trade_author: set[tuple[str, str]] = set()
        seen_trade_channel: set[tuple[str, str]] = set()

        for row in joined:
            trade_id = row["trade_id"]
            pnl = row["pnl_percent"]
            outcome = _outcome_direction(pnl, neutral_band)
            hit = _is_hit(row["signal_side"], outcome)

            author = row.get("author_id")
            channel = row.get("source_channel")

            if author:
                stat = run.author_stats.setdefault(author, CalibrationStat())
                stat.n_signals += 1
                key = (trade_id, author)
                if hit is not None and key not in seen_trade_author:
                    seen_trade_author.add(key)
                    stat.n_trades_linked += 1
                    stat.pnl_pct_sum += float(pnl)
                    if hit:
                        stat.n_hits += 1

            if channel:
                stat = run.channel_stats.setdefault(channel, CalibrationStat())
                stat.n_signals += 1
                key = (trade_id, channel)
                if hit is not None and key not in seen_trade_channel:
                    seen_trade_channel.add(key)
                    stat.n_trades_linked += 1
                    stat.pnl_pct_sum += float(pnl)
                    if hit:
                        stat.n_hits += 1

        # Apply updates
        recorded_at = datetime.now(UTC).isoformat()

        for author_id, stat in run.author_stats.items():
            if stat.n_signals < min_signals_for_update:
                continue
            existing = conn.execute(
                "SELECT trust_weight FROM input_authors WHERE author_id=?",
                (author_id,),
            ).fetchone()
            before = float(existing[0]) if existing and existing[0] is not None else 1.0
            after = update_weight(before, stat.precision, alpha=alpha)
            if abs(after - before) < 1e-9:
                continue
            if not dry_run:
                conn.execute(
                    "UPDATE input_authors SET trust_weight=? WHERE author_id=?",
                    (after, author_id),
                )
                conn.execute(
                    """
                    INSERT INTO signal_calibration_history (
                        history_id, run_id, recorded_at, scope_kind, scope_key,
                        trust_weight_before, trust_weight_after,
                        n_signals, n_trades_linked, n_hits, precision, avg_pnl_pct, notes
                    ) VALUES (?, ?, ?, 'author', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex, run.run_id, recorded_at, author_id,
                        before, after,
                        stat.n_signals, stat.n_trades_linked, stat.n_hits,
                        stat.precision, stat.avg_pnl_pct,
                        f"alpha={alpha}, link_window={link_window_days}d",
                    ),
                )
            run.weight_updates_authors += 1

        for channel, stat in run.channel_stats.items():
            if stat.n_signals < min_signals_for_update:
                continue
            existing = conn.execute(
                "SELECT trust_weight, baseline_weight FROM source_trust_weights WHERE source_channel=?",
                (channel,),
            ).fetchone()
            if existing:
                before = float(existing[0])
                baseline = float(existing[1])
            else:
                before = baseline = 1.0
            after = update_weight(baseline, stat.precision, alpha=alpha)
            if abs(after - before) < 1e-9 and existing:
                continue
            if not dry_run:
                conn.execute(
                    """
                    INSERT INTO source_trust_weights (
                        source_channel, trust_weight, n_signals, n_trades_linked,
                        n_hits, precision, avg_pnl_pct, last_updated_at, baseline_weight
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_channel) DO UPDATE SET
                        trust_weight    = excluded.trust_weight,
                        n_signals       = excluded.n_signals,
                        n_trades_linked = excluded.n_trades_linked,
                        n_hits          = excluded.n_hits,
                        precision       = excluded.precision,
                        avg_pnl_pct     = excluded.avg_pnl_pct,
                        last_updated_at = excluded.last_updated_at
                    """,
                    (
                        channel, after, stat.n_signals, stat.n_trades_linked,
                        stat.n_hits, stat.precision, stat.avg_pnl_pct,
                        recorded_at, baseline,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO signal_calibration_history (
                        history_id, run_id, recorded_at, scope_kind, scope_key,
                        trust_weight_before, trust_weight_after,
                        n_signals, n_trades_linked, n_hits, precision, avg_pnl_pct, notes
                    ) VALUES (?, ?, ?, 'channel', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex, run.run_id, recorded_at, channel,
                        before, after,
                        stat.n_signals, stat.n_trades_linked, stat.n_hits,
                        stat.precision, stat.avg_pnl_pct,
                        f"alpha={alpha}, link_window={link_window_days}d",
                    ),
                )
            run.weight_updates_channels += 1

        if not dry_run:
            conn.commit()

    run.finished_at = datetime.now(UTC).isoformat()
    log.info("Trust calibration complete: %s", run.summary())
    return run


def load_channel_trust_weight(channel: str, *, db_path: Optional[Path] = None) -> Optional[float]:
    """Composer-side lookup — returns None when no row exists so caller
    can fall back to the hard-coded default."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT trust_weight FROM source_trust_weights WHERE source_channel=?",
            (channel,),
        ).fetchone()
    return float(row[0]) if row else None
