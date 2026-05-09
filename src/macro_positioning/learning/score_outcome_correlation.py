"""Score → outcome correlation.

Spearman ρ between adjusted_total_score (and each sub-score) at entry
and pnl_percent at close. Joins trade_scores ↔ trades via score_id.

Pure stdlib. Tie-aware average ranks; two-sided p-value approximated
via the t-distribution with `statistics.NormalDist` (sufficient for
n ≥ 10; below that, p_value is None).
"""

from __future__ import annotations

import math
import sqlite3
import statistics


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


def _ranks(values: list[float]) -> list[float]:
    """Tie-aware average ranks (same convention as scipy.stats.rankdata
    with method='average')."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # ranks are 1-indexed
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> tuple[float | None, float | None, int]:
    """Return (rho, p_value, n). rho = Pearson on ranks. p_value via
    Student-t approximation through NormalDist for n ≥ 10."""
    n = len(xs)
    if n < 2:
        return None, None, n
    rx = _ranks(xs)
    ry = _ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((r - mx) ** 2 for r in rx))
    dy = math.sqrt(sum((r - my) ** 2 for r in ry))
    if dx == 0 or dy == 0:
        return None, None, n
    rho = num / (dx * dy)
    rho = max(-1.0, min(1.0, rho))
    p_value: float | None = None
    if n >= 10 and abs(rho) < 1.0:
        t = rho * math.sqrt((n - 2) / (1 - rho * rho))
        # Two-sided via normal approx (good enough for surfaces, not for stats papers).
        p_value = 2.0 * (1.0 - statistics.NormalDist().cdf(abs(t)))
        p_value = max(0.0, min(1.0, p_value))
    return rho, p_value, n


def _empty_result() -> dict:
    keys = ["adjusted_total"] + [c.removesuffix("_score") for c in SUB_SCORE_COLUMNS]
    out: dict = {"n_pairs": 0}
    for k in keys:
        out[k] = {"spearman": None, "p_value": None, "n": 0}
    return out


def score_outcome_correlation(conn: sqlite3.Connection) -> dict:
    """Spearman ρ between trade_scores fields at entry and trades.pnl_percent
    at close. Returns a dict with the overall `adjusted_total` plus one entry
    per sub-score. Empty (`n_pairs=0`) if no closed trades have a linked score.
    """
    cols = ", ".join(["ts." + c for c in SUB_SCORE_COLUMNS])
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
    if not rows:
        return _empty_result()

    # Column order: adjusted_total, *sub-scores, pnl_percent
    pnl = [float(r[-1]) for r in rows]
    adj = [float(r[0]) for r in rows]

    out: dict = {"n_pairs": len(rows)}
    rho, p, n = _spearman(adj, pnl)
    out["adjusted_total"] = {"spearman": rho, "p_value": p, "n": n}

    for idx, col in enumerate(SUB_SCORE_COLUMNS, start=1):
        xs = [float(r[idx]) for r in rows]
        rho, p, n = _spearman(xs, pnl)
        out[col.removesuffix("_score")] = {"spearman": rho, "p_value": p, "n": n}

    return out
