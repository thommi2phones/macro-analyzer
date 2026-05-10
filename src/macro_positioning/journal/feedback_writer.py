"""Fan-out from a submitted review into the learning machinery.

When a review lands we derive two side-effects:

1. **source_outcomes** — one row per credited source (Q2). Drives
   `learning/source_attribution`, which in turn powers the
   `sourceLeaderboard` panel on /journal.
2. **score_calibration.jsonl** — one entry per Q4 hindsight score.
   `learning/score_outcome_correlation` reads this overlay so the
   scorer can see "I said 80, hindsight said over" patterns.

Q1 (thesis_validity) and Q5 (surprise_factor) are left in
`trade_reviews` for downstream PM-side consumers (regime_accuracy,
regime_instability indicator).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from macro_positioning.core.settings import settings


def _calibration_log_path() -> Path:
    return settings.base_dir / "data" / "score_calibration.jsonl"


def apply_review_feedback(
    conn: sqlite3.Connection,
    trade_id: str,
    review: dict,
    *,
    now: datetime | None = None,
    calibration_path: Path | None = None,
) -> dict:
    """Emit derived rows from a review.

    Caller owns the connection's transaction. Pure beyond the two
    documented side-effects (source_outcomes insert + jsonl append).

    Returns `{source_outcomes_written: N, calibration_appended: bool}`.
    """
    now = now or datetime.now(timezone.utc)
    n_sources = _write_source_outcomes(conn, trade_id, review, now=now)
    appended = _append_calibration_entry(
        conn,
        trade_id,
        review,
        now=now,
        path=calibration_path or _calibration_log_path(),
    )
    return {
        "source_outcomes_written": n_sources,
        "calibration_appended": appended,
    }


# ---------------------------------------------------------------------------
# Q2 → source_outcomes
# ---------------------------------------------------------------------------


def _write_source_outcomes(
    conn: sqlite3.Connection,
    trade_id: str,
    review: dict,
    *,
    now: datetime,
) -> int:
    sources: Iterable[str] = review.get("sources_credited") or []
    sources = [s for s in sources if s]
    if not sources:
        return 0

    trade_row = conn.execute(
        "SELECT pnl, pnl_percent FROM trades WHERE trade_id = ?",
        (trade_id,),
    ).fetchone()
    if trade_row is None:
        return 0
    pnl, pnl_percent = trade_row

    # Equal split for v1 — see refinement queue (smart attribution_weight v2).
    weight = 1.0 / len(sources)
    recorded_at = now.isoformat()

    rows = [
        (
            f"o-{uuid.uuid4().hex[:12]}",
            source_id,
            trade_id,
            None,  # thesis_id — not tracked at review time
            weight,
            pnl,
            pnl_percent,
            "review_credited",
            recorded_at,
        )
        for source_id in sources
    ]
    conn.executemany(
        """
        INSERT INTO source_outcomes (
            outcome_id, source_id, trade_id, thesis_id,
            attribution_weight, outcome_pnl, outcome_pnl_percent,
            contribution_type, recorded_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Q4 → score_calibration.jsonl
# ---------------------------------------------------------------------------


def _append_calibration_entry(
    conn: sqlite3.Connection,
    trade_id: str,
    review: dict,
    *,
    now: datetime,
    path: Path,
) -> bool:
    hindsight = review.get("setup_score_hindsight")
    if hindsight not in {"over", "right", "under"}:
        return False

    # Best-effort lookup of score-at-entry; absence is fine (logged as None).
    score_at_entry: int | None = None
    score_id: str | None = None
    row = conn.execute(
        """
        SELECT t.score_id, ts.adjusted_total_score
        FROM trades t
        LEFT JOIN trade_scores ts ON ts.score_id = t.score_id
        WHERE t.trade_id = ?
        """,
        (trade_id,),
    ).fetchone()
    if row is not None:
        score_id = row[0]
        if row[1] is not None:
            score_at_entry = int(row[1])

    entry = {
        "trade_id": trade_id,
        "score_id": score_id,
        "score_at_entry": score_at_entry,
        "hindsight": hindsight,
        "recorded_at": now.isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return True
