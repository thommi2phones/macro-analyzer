"""Score → outcome correlation.

Spearman ρ between `adjusted_total_score` (and each sub-score) at
entry and `pnl_percent` at close. Joins `trade_scores` ↔ `trades`
via `score_id`.

Pure stdlib. Tie-aware average ranks; two-sided p-value approximated
via the t-distribution through `statistics.NormalDist` (sufficient
for n ≥ 10; below that p_value is None).

V2 additions
────────────
- 95% confidence interval per ρ via Fisher z-transform with the
  Fieller-style SE adjustment for Spearman (1.06 / √(n − 3)). CIs
  surface uncertainty — a point estimate of ρ = 0.4 with n = 8 means
  basically nothing, and the dashboard needs to show that.
- `_meta` block at the top of the returned dict explaining what the
  correlation result represents and why it might be sparse.
- Optional `hindsight_overlay`: when feedback_writer ships its Q4
  `setup_score_hindsight` enum into either
  `data/score_calibration.jsonl` or a future `score_calibration`
  table, this module folds the overlay into the result as a separate
  `calibration` block. Today we just probe the JSONL path and noop
  if absent — non-breaking forward compatibility.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import statistics
from pathlib import Path
from typing import Iterable

from macro_positioning.core.settings import settings


log = logging.getLogger(__name__)


SUB_SCORE_COLUMNS = [
    "macro_alignment_score",
    "liquidity_score",
    "sector_theme_score",
    "technical_structure_score",
    "volume_flow_score",
    "risk_reward_score",
    "relative_strength_score",
    "psychology_score",
]

CALIBRATION_JSONL = Path(settings.base_dir) / "data" / "score_calibration.jsonl"


# ---------------------------------------------------------------------------
# Stats primitives
# ---------------------------------------------------------------------------

def _ranks(values: list[float]) -> list[float]:
    """Tie-aware average ranks (matches scipy.stats.rankdata method='average')."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-indexed
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def _fisher_ci(rho: float, n: int, conf: float = 0.95) -> tuple[float | None, float | None]:
    """95% CI on ρ via Fisher z-transform.

    Spearman variance under the null is slightly larger than Pearson;
    Fieller (1957) and others recommend SE(z) ≈ 1.06 / √(n − 3) for
    Spearman, vs 1 / √(n − 3) for Pearson. We use the Spearman form.

    Returns (lo, hi) clipped to [-1, 1]. `None` when n is too small
    (n ≤ 3) or |ρ| is exactly 1 (atanh blows up).
    """
    if n <= 3 or abs(rho) >= 1.0:
        return None, None
    z = math.atanh(rho)
    se = 1.06 / math.sqrt(n - 3)
    # Two-sided z-multiplier for `conf` confidence.
    alpha = (1.0 - conf) / 2.0
    zmult = statistics.NormalDist().inv_cdf(1.0 - alpha)
    lo_z = z - zmult * se
    hi_z = z + zmult * se
    lo = math.tanh(lo_z)
    hi = math.tanh(hi_z)
    # Clip for safety against floating-point drift.
    return max(-1.0, lo), min(1.0, hi)


def _spearman(xs: list[float], ys: list[float]) -> dict:
    """Return {spearman, p_value, n, ci_lo, ci_hi}.

    `spearman` is Pearson on ranks. `p_value` uses a two-sided
    Student-t through the normal approximation for n ≥ 10. `ci_lo`/
    `ci_hi` are Fisher-z 95% CI bounds; `None` when n ≤ 3 or |ρ| = 1.
    """
    n = len(xs)
    if n < 2:
        return {"spearman": None, "p_value": None, "n": n, "ci_lo": None, "ci_hi": None}
    rx = _ranks(xs)
    ry = _ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((r - mx) ** 2 for r in rx))
    dy = math.sqrt(sum((r - my) ** 2 for r in ry))
    if dx == 0 or dy == 0:
        return {"spearman": None, "p_value": None, "n": n, "ci_lo": None, "ci_hi": None}
    rho = max(-1.0, min(1.0, num / (dx * dy)))
    p_value: float | None = None
    if n >= 10 and abs(rho) < 1.0:
        t = rho * math.sqrt((n - 2) / (1 - rho * rho))
        p_value = 2.0 * (1.0 - statistics.NormalDist().cdf(abs(t)))
        p_value = max(0.0, min(1.0, p_value))
    ci_lo, ci_hi = _fisher_ci(rho, n)
    return {
        "spearman": rho,
        "p_value": p_value,
        "n": n,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
    }


def _empty_result(reason: str) -> dict:
    keys = ["adjusted_total"] + [c.removesuffix("_score") for c in SUB_SCORE_COLUMNS]
    out: dict = {
        "n_pairs": 0,
        "_meta": {
            "lens": "score_outcome_correlation",
            "message": reason,
        },
    }
    for k in keys:
        out[k] = {"spearman": None, "p_value": None, "n": 0, "ci_lo": None, "ci_hi": None}
    return out


# ---------------------------------------------------------------------------
# Hindsight overlay (calibration_jsonl)
# ---------------------------------------------------------------------------

def _load_calibration_overlay(path: Path | None = None) -> list[dict]:
    """Read `data/score_calibration.jsonl` if it exists. Returns [].

    Expected line shape (per the journal-feedback-loop brief, Q4):
        {"trade_id": "...", "scored_at": ISO, "score_at_entry": 80,
         "setup_score_hindsight": "over" | "right" | "under",
         "asset_ticker": "URA"}

    Tolerant of missing/extra fields; rows that can't be parsed are
    skipped with a debug log line.
    """
    p = path or CALIBRATION_JSONL
    if not p.exists():
        return []
    out: list[dict] = []
    for i, line in enumerate(p.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            log.debug("calibration jsonl line %d skipped: %s", i, e)
    return out


def _calibration_summary(overlay: list[dict]) -> dict:
    """Roll up the hindsight overlay: count over/right/under and the
    average score gap (entry score − implied 'correct' bucket center).

    Bucket centers are coarse: 'under'→+10, 'right'→0, 'over'→−10.
    Negative `avg_score_gap` means the scorer was systematically too
    bullish; positive means too conservative.
    """
    if not overlay:
        return {"n": 0}
    centers = {"under": 10.0, "right": 0.0, "over": -10.0}
    buckets = {"under": 0, "right": 0, "over": 0, "other": 0}
    gaps: list[float] = []
    for row in overlay:
        bucket = row.get("setup_score_hindsight")
        if bucket in centers:
            buckets[bucket] += 1
            gaps.append(centers[bucket])
        else:
            buckets["other"] += 1
    return {
        "n": len(overlay),
        "buckets": buckets,
        "avg_score_gap": round(sum(gaps) / len(gaps), 4) if gaps else None,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_outcome_correlation(
    conn: sqlite3.Connection,
    *,
    include_calibration: bool = True,
) -> dict:
    """Spearman ρ (with 95% Fisher-z CIs) between trade_scores fields at
    entry and trades.pnl_percent at close. Returns a dict with the
    overall `adjusted_total` plus one entry per sub-score, plus a
    `_meta` block and an optional `calibration` overlay summary.
    """
    cols = ", ".join(["ts." + c for c in SUB_SCORE_COLUMNS])
    n_total_scores = conn.execute("SELECT COUNT(*) FROM trade_scores").fetchone()[0]
    n_closed_trades = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE status = 'closed' AND pnl_percent IS NOT NULL"
    ).fetchone()[0]

    cur = conn.execute(
        f"""
        SELECT ts.adjusted_total_score, {cols}, t.pnl_percent
        FROM trade_scores ts
        JOIN trades t ON t.score_id = ts.score_id
        WHERE t.status = 'closed'
          AND t.pnl_percent IS NOT NULL
        """
    )
    rows = cur.fetchall()

    overlay = _load_calibration_overlay() if include_calibration else []
    calibration_summary = _calibration_summary(overlay)

    if not rows:
        if n_closed_trades == 0:
            reason = "no closed trades yet — correlation cannot be computed until trades close with pnl_percent set"
        elif n_total_scores == 0:
            reason = "no trade_scores rows yet — run `score run` to populate"
        else:
            reason = (
                f"{n_closed_trades} closed trades and {n_total_scores} scores "
                "exist but no rows join via score_id; check that trades.score_id is set on close"
            )
        log.info("score_outcome_correlation: %s", reason)
        result = _empty_result(reason)
        result["_meta"]["n_total_scores"] = int(n_total_scores)
        result["_meta"]["n_closed_trades"] = int(n_closed_trades)
        if calibration_summary["n"]:
            result["calibration"] = calibration_summary
        return result

    pnl = [float(r[-1]) for r in rows]
    adj = [float(r[0]) for r in rows]

    out: dict = {
        "n_pairs": len(rows),
        "_meta": {
            "lens": "score_outcome_correlation",
            "n_total_scores": int(n_total_scores),
            "n_closed_trades": int(n_closed_trades),
            "message": f"{len(rows)} (score, pnl) pairs joined via score_id",
            "ci_method": "Fisher z, Spearman SE = 1.06/√(n−3); 95% two-sided",
        },
    }
    out["adjusted_total"] = _spearman(adj, pnl)
    for idx, col in enumerate(SUB_SCORE_COLUMNS, start=1):
        xs = [float(r[idx]) for r in rows]
        out[col.removesuffix("_score")] = _spearman(xs, pnl)

    if calibration_summary["n"]:
        out["calibration"] = calibration_summary
    return out
