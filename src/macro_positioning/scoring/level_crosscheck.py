"""Cross-check agent levels against trusted-KOL levels — incremental validation.

Operator direction (2026-08-02): before building a full replay backtest,
validate the level synthesizer per-pass against what the manual-test work
already proved trustworthy — levels drawn by KOLs whose accuracy is
backtested (`learning.call_accuracy.source_accuracy`, `setup_win_rate`,
`meaningful` = enough priceable calls).

For every ticker in the latest scoring pass that carries agent levels AND
has recent KOL signals with drawn levels, report the divergence:

  entry / stop / target percent distance, side agreement,
  split by trusted (meaningful-accuracy) vs unproven authors.

This is a *sanity lens*, not a scorer: big systematic divergence from
high-setup-win-rate authors on the same ticker means the agent's placement
logic needs a look; small divergence is confidence the mechanical/structural
reads are in the same universe as proven human reads. It also becomes the
skeleton of v2's KOL cross-check (brief: technical-agent.md).

Run:  uv run python -m macro_positioning.scoring.level_crosscheck
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Optional

from macro_positioning.core.settings import settings

# Sides that express a directional opinion comparable to agent rails.
_DIRECTIONAL_SIDES = {"LONG", "SHORT"}

# Any single divergence beyond this is a unit/scale mismatch (e.g. a BTC
# level extracted in the wrong denomination), not a placement disagreement.
# Such rows are flagged and excluded from the medians.
_SCALE_OUTLIER_DIV = 0.75


# ---------------------------------------------------------------------------
# Pure comparison helpers (unit-tested without a DB)
# ---------------------------------------------------------------------------

def kol_entry_mid(entry_low: float | None, entry_high: float | None) -> float | None:
    """Midpoint of the drawn entry zone; single-sided zones use that side."""
    vals = [v for v in (entry_low, entry_high) if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def pct_divergence(agent_value: float | None, kol_value: float | None) -> float | None:
    """|agent − kol| / kol — how far the agent sits from the human level."""
    if not agent_value or not kol_value:
        return None
    return abs(agent_value - kol_value) / abs(kol_value)


def compare_levels(agent: dict, kol: dict) -> dict:
    """Compare one agent LevelSet dict vs one KOL signal's drawn levels.

    `agent` is reasoning_trail_json["levels"]; `kol` needs
    side / entry_zone_low / entry_zone_high / stop_loss / target_1.
    """
    entry_mid = kol_entry_mid(kol.get("entry_zone_low"), kol.get("entry_zone_high"))
    kol_side = (kol.get("side") or "").upper()
    side_comparable = kol_side in _DIRECTIONAL_SIDES
    return {
        "entry_div": pct_divergence(agent.get("entry"), entry_mid),
        "stop_div": pct_divergence(agent.get("stop"), kol.get("stop_loss")),
        "target_div": pct_divergence(agent.get("target"), kol.get("target_1")),
        "side_comparable": side_comparable,
        "side_agrees": side_comparable and kol_side == agent.get("side"),
    }


def is_scale_outlier(cmp_row: dict) -> bool:
    """True when any divergence is so large it must be a unit mismatch."""
    return any(
        cmp_row.get(k) is not None and cmp_row[k] > _SCALE_OUTLIER_DIV
        for k in ("entry_div", "stop_div", "target_div")
    )


def summarize(comparisons: list[dict]) -> dict:
    """Median divergences + side agreement over a list of compare_levels rows."""
    def med(key: str) -> float | None:
        vals = [c[key] for c in comparisons if c.get(key) is not None]
        return round(median(vals), 4) if vals else None

    directional = [c for c in comparisons if c.get("side_comparable")]
    return {
        "n": len(comparisons),
        "median_entry_div": med("entry_div"),
        "median_stop_div": med("stop_div"),
        "median_target_div": med("target_div"),
        "n_directional": len(directional),
        "side_agreement": (
            round(sum(1 for c in directional if c["side_agrees"]) / len(directional), 4)
            if directional else None
        ),
    }


# ---------------------------------------------------------------------------
# DB-facing report
# ---------------------------------------------------------------------------

def _load_agent_levels(conn: sqlite3.Connection) -> dict[str, dict]:
    """Latest pass's agent levels per ticker (rn=1 per asset)."""
    rows = conn.execute(
        """
        SELECT t.ticker, s.reasoning_trail_json
        FROM (
            SELECT ts.*, ROW_NUMBER() OVER (
                PARTITION BY tsu.asset_id ORDER BY ts.scored_at DESC
            ) AS rn, tsu.asset_id
            FROM trade_scores ts
            JOIN technical_setups tsu ON tsu.setup_id = ts.setup_id
        ) s
        JOIN assets t ON t.asset_id = s.asset_id
        WHERE s.rn = 1
        """
    ).fetchall()
    out: dict[str, dict] = {}
    for ticker, trail_json in rows:
        try:
            levels = (json.loads(trail_json) or {}).get("levels")
        except (TypeError, json.JSONDecodeError):
            levels = None
        if levels:
            out[ticker.upper()] = levels
    return out


def _load_kol_signals(
    conn: sqlite3.Connection, tickers: set[str], window_days: int
) -> list[sqlite3.Row]:
    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in tickers)
    return conn.execute(
        f"""
        SELECT asset_ticker, side, author_id, source_slug, extracted_at,
               entry_zone_low, entry_zone_high, stop_loss, target_1
        FROM signals
        WHERE status = 'active'
          AND extracted_at >= ?
          AND UPPER(asset_ticker) IN ({placeholders})
          AND (stop_loss IS NOT NULL
               OR entry_zone_low IS NOT NULL OR entry_zone_high IS NOT NULL
               OR target_1 IS NOT NULL)
        ORDER BY extracted_at DESC
        """,
        (cutoff, *tickers),
    ).fetchall()


def crosscheck_levels(
    *, window_days: int = 45, db_path: Optional[Path] = None
) -> dict:
    """Build the cross-check report. Returns
    {per_ticker: [...], summary: {...}, trusted_summary: {...}}.
    """
    from macro_positioning.learning.call_accuracy import source_accuracy

    db_path = db_path or settings.sqlite_path
    accuracy = {
        a["author_id"]: a
        for a in source_accuracy()
    }

    with sqlite3.connect(db_path) as conn:
        agent_levels = _load_agent_levels(conn)
        if not agent_levels:
            return {"per_ticker": [], "summary": summarize([]),
                    "trusted_summary": summarize([]),
                    "note": "no agent levels in latest pass"}
        signals = _load_kol_signals(conn, set(agent_levels), window_days)

    per_ticker: list[dict] = []
    all_cmp: list[dict] = []
    trusted_cmp: list[dict] = []
    n_outliers = 0
    for sig in signals:
        ticker = sig["asset_ticker"].upper()
        agent = agent_levels[ticker]
        cmp_row = compare_levels(agent, dict(sig))
        outlier = is_scale_outlier(cmp_row)
        acc = accuracy.get(sig["author_id"]) or {}
        trusted = bool(acc.get("meaningful"))
        row = {
            "ticker": ticker,
            "author": acc.get("display_name") or sig["author_id"] or sig["source_slug"],
            "author_setup_win_rate": acc.get("setup_win_rate"),
            "author_trusted": trusted,
            "kol_side": sig["side"],
            "kol_extracted_at": sig["extracted_at"],
            "agent_side": agent.get("side"),
            "agent_method": agent.get("method"),
            "scale_outlier": outlier,
            **cmp_row,
        }
        per_ticker.append(row)
        if outlier:
            n_outliers += 1
            continue
        all_cmp.append(cmp_row)
        if trusted:
            trusted_cmp.append(cmp_row)

    return {
        "per_ticker": per_ticker,
        "summary": summarize(all_cmp),
        "trusted_summary": summarize(trusted_cmp),
        "n_scale_outliers": n_outliers,
        "window_days": window_days,
        "n_agent_tickers": len(agent_levels),
    }


def _fmt_pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


def main() -> None:
    report = crosscheck_levels()
    print(f"agent tickers with levels: {report['n_agent_tickers']}"
          f" | KOL signals compared: {report['summary']['n']}"
          f" | scale outliers excluded: {report['n_scale_outliers']}"
          f" (window {report.get('window_days')}d)")
    for label in ("summary", "trusted_summary"):
        s = report[label]
        print(f"  {label}: n={s['n']}"
              f" entry±{_fmt_pct(s['median_entry_div'])}"
              f" stop±{_fmt_pct(s['median_stop_div'])}"
              f" target±{_fmt_pct(s['median_target_div'])}"
              f" side-agree={_fmt_pct(s['side_agreement'])}"
              f" ({s['n_directional']} directional)")
    for r in report["per_ticker"]:
        trust = "TRUSTED" if r["author_trusted"] else "unproven"
        wr = (f"{r['author_setup_win_rate'] * 100:.0f}%"
              if r["author_setup_win_rate"] is not None else "—")
        print(f"  {r['ticker']:<6} {r['author']:<22} [{trust} · setup {wr}]"
              f" kol {r['kol_side']:<5} vs agent {r['agent_side']}/{r['agent_method']:<16}"
              f" entry±{_fmt_pct(r['entry_div'])}"
              f" stop±{_fmt_pct(r['stop_div'])}"
              f" target±{_fmt_pct(r['target_div'])}")


if __name__ == "__main__":
    main()
