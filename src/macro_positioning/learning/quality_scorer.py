"""Item 4 — Per-call quality scoring on agent_call_log.

Populates `agent_call_log.quality_score` ∈ [0,1] via conservative
heuristics that key off observable downstream confirmation:

  regime_classifier
    Confirmed if the regime label's expectations in
    `config/regime_outcomes.json` hold within the horizon window
    after `called_at`. Two-tier:
      - All primary expectations hold     → quality = 1.0
      - Some primary hold, none violate   → quality = 0.5 (partial)
      - Any primary violates              → quality = 0.0
      - Not enough price data yet         → leave NULL (don't guess)

  technical_scorer / score_composer / orchestrator
    Confirmed if attributed_trade_id is set and attributed_outcome_pnl
    is non-negative (positive P&L). Negative P&L → quality 0.0.
    No attribution yet → leave NULL.

  mention_extractor / chart_vision / narrative_synthesizer
    No clean closed-loop signal today. The journal-feedback-loop chat's
    Q1 (thesis_validity) + Q4 (setup_score_hindsight) will provide
    that — when score_hindsight_overlay starts filling, we incorporate
    it here. Today: leave quality_score NULL.

Cross-chat respect
─────────────────
Never overwrites a non-NULL quality_score (LLM-agents or any future
chat may write it directly). Returns NULL when uncertain — false
positives pollute the training corpus per the brief's lock.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from macro_positioning.core.settings import settings
from macro_positioning.learning.source_attribution import (
    _close_at_or_after,
    _close_at_or_before,
    _load_close_lookup,
    _parse_iso,
)


log = logging.getLogger(__name__)


REGIME_OUTCOMES_PATH = Path(settings.base_dir) / "config" / "regime_outcomes.json"


_REGIME_AGENTS = {"regime_classifier"}
_TRADE_OUTCOME_AGENTS = {
    "technical_scorer",
    "score_composer",
    "scorer",
    "orchestrator",
}
# Agents where we explicitly DON'T heuristic-score (per the brief's
# conservative bar). The default branch returns NULL for anything not
# in the two sets above; this set is for documentation + future
# integration with journal-feedback Q1/Q4.
_NULL_AGENTS = {"mention_extractor", "chart_vision", "narrative_synthesizer"}


def _load_regime_outcomes() -> dict:
    if not REGIME_OUTCOMES_PATH.exists():
        log.debug("regime_outcomes.json missing at %s", REGIME_OUTCOMES_PATH)
        return {"regimes": {}}
    try:
        return json.loads(REGIME_OUTCOMES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("regime_outcomes.json read failed: %s", e)
        return {"regimes": {}}


def _check_expectation(
    closes: dict[str, list[tuple[datetime, float]]],
    *,
    called_at: datetime,
    ticker: str,
    direction: str,
    threshold_pct: float,
    horizon_days: int,
) -> str | None:
    """Return one of: 'met', 'violated', 'unknown' (no price data)."""
    bars = closes.get(ticker.upper(), [])
    entry = _close_at_or_before(bars, called_at)
    if entry is None or entry == 0:
        return None
    target = called_at + timedelta(days=horizon_days)
    exit_close = _close_at_or_after(bars, target)
    if exit_close is None:
        return None
    pct = (exit_close / entry - 1.0) * 100.0
    if direction == "up":
        return "met" if pct >= threshold_pct else "violated"
    if direction == "down":
        return "met" if pct <= -threshold_pct else "violated"
    if direction == "flat":
        return "met" if abs(pct) <= threshold_pct else "violated"
    log.debug("unknown direction %r for %s", direction, ticker)
    return None


def _score_regime_call(
    output_payload_json: str | None,
    called_at: datetime,
    closes: dict[str, list[tuple[datetime, float]]],
    regimes_cfg: dict,
) -> tuple[float | None, dict]:
    """Return (quality_score, evidence) for a regime_classifier row.

    Quality is NULL when:
      - output_payload doesn't carry a parseable regime label
      - we have no expectations for that regime
      - none of the expectations have enough price data yet
    """
    if not output_payload_json:
        return None, {"reason": "no output_payload_json"}
    try:
        payload = json.loads(output_payload_json)
    except json.JSONDecodeError:
        return None, {"reason": "output_payload_json unparseable"}
    label = None
    if isinstance(payload, dict):
        # Common shapes: {"parsed": {"regime": "..."}}, {"regime": "..."},
        # {"label": "..."}, {"raw": "...", "parsed": {...}}.
        parsed = payload.get("parsed") if isinstance(payload.get("parsed"), dict) else payload
        label = parsed.get("regime") or parsed.get("label") or parsed.get("framework_regime")
    if not label:
        return None, {"reason": "no regime label in output"}

    cfg = regimes_cfg.get(label)
    if not cfg:
        return None, {"reason": f"no expectations defined for regime {label!r}"}
    expectations = cfg.get("expectations", []) or []
    if not expectations:
        return None, {"reason": f"empty expectations list for regime {label!r}"}

    results = []
    n_met = 0
    n_violated = 0
    n_unknown = 0
    for e in expectations:
        outcome = _check_expectation(
            closes,
            called_at=called_at,
            ticker=e.get("ticker", ""),
            direction=e.get("direction", "up"),
            threshold_pct=float(e.get("threshold_pct", 0.0)),
            horizon_days=int(e.get("horizon_days", 30)),
        )
        results.append({**e, "outcome": outcome})
        if outcome == "met":
            n_met += 1
        elif outcome == "violated":
            n_violated += 1
        else:
            n_unknown += 1

    evidence = {
        "regime": label,
        "expectations": results,
        "n_met": n_met,
        "n_violated": n_violated,
        "n_unknown": n_unknown,
    }
    if n_unknown == len(expectations):
        return None, {**evidence, "reason": "no expectations have enough price data yet"}
    if n_violated >= 1:
        return 0.0, evidence
    if n_met == len(expectations):
        return 1.0, evidence
    # Some met, some unknown, none violated → partial credit. Conservative
    # 0.5 — we don't have enough signal to claim full confirmation.
    return 0.5, evidence


def _score_trade_outcome_call(
    attributed_trade_id: str | None,
    attributed_outcome_pnl: float | None,
) -> tuple[float | None, dict]:
    """Trade-attribution agents: confirmed iff a trade closed positive."""
    if not attributed_trade_id:
        return None, {"reason": "no attributed_trade_id yet"}
    if attributed_outcome_pnl is None:
        return None, {"reason": "trade attributed but outcome_pnl not yet recorded"}
    if attributed_outcome_pnl >= 0:
        return 1.0, {"attributed_trade_id": attributed_trade_id, "pnl": attributed_outcome_pnl}
    return 0.0, {"attributed_trade_id": attributed_trade_id, "pnl": attributed_outcome_pnl}


def backfill_quality_scores(
    conn: sqlite3.Connection,
    *,
    since_days: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Compute and write `quality_score` for every row where it's NULL.

    Conservative: each row gets a score only when the heuristic for its
    `agent_name` returns a confident value. Otherwise we leave it NULL
    rather than guess.
    """
    now = now or datetime.now(timezone.utc)
    where = ["(quality_score IS NULL)"]
    params: list = []
    if since_days is not None:
        cutoff = (now - timedelta(days=since_days)).isoformat()
        where.append("called_at >= ?")
        params.append(cutoff)

    cur = conn.execute(
        f"""
        SELECT call_id, agent_name, called_at, output_payload_json,
               attributed_trade_id, attributed_outcome_pnl
        FROM agent_call_log
        WHERE {' AND '.join(where)}
        """,
        tuple(params),
    )
    rows = cur.fetchall()
    if not rows:
        n_total = conn.execute("SELECT COUNT(*) FROM agent_call_log").fetchone()[0]
        n_with = conn.execute(
            "SELECT COUNT(*) FROM agent_call_log WHERE quality_score IS NOT NULL"
        ).fetchone()[0]
        return {
            "examined": 0,
            "updated": 0,
            "left_null": 0,
            "by_agent": {},
            "dry_run": dry_run,
            "_meta": {
                "lens": "quality_backfill",
                "n_total": int(n_total),
                "n_already_scored": int(n_with),
                "message": (
                    "no rows to score (table empty)" if n_total == 0
                    else f"all {n_with}/{n_total} rows already have quality_score"
                ),
            },
        }

    # Preload prices for any regime calls in scope.
    regimes_cfg = (_load_regime_outcomes() or {}).get("regimes", {})
    regime_tickers: set[str] = set()
    for cfg in regimes_cfg.values():
        for e in cfg.get("expectations", []) + cfg.get("negation_expectations", []):
            if e.get("ticker"):
                regime_tickers.add(e["ticker"].upper())
    closes = _load_close_lookup(conn, regime_tickers) if regime_tickers else {}

    examined = 0
    updated = 0
    left_null = 0
    by_agent: dict[str, dict] = defaultdict(
        lambda: {"examined": 0, "scored": 0, "left_null": 0, "sum_quality": 0.0}
    )

    for call_id, agent_name, called_at, output_payload_json, att_trade, att_pnl in rows:
        examined += 1
        a = by_agent[agent_name]
        a["examined"] += 1
        dt = _parse_iso(called_at) or now
        score: float | None = None
        evidence: dict = {}
        if agent_name in _REGIME_AGENTS:
            score, evidence = _score_regime_call(output_payload_json, dt, closes, regimes_cfg)
        elif agent_name in _TRADE_OUTCOME_AGENTS:
            score, evidence = _score_trade_outcome_call(att_trade, att_pnl)
        else:
            evidence = {"reason": f"no heuristic for agent {agent_name!r}"}

        if score is None:
            left_null += 1
            a["left_null"] += 1
            continue
        a["scored"] += 1
        a["sum_quality"] += score
        updated += 1
        if not dry_run:
            conn.execute(
                "UPDATE agent_call_log SET quality_score = ? WHERE call_id = ?",
                (score, call_id),
            )

    if not dry_run and updated:
        conn.commit()

    by_agent_out = {}
    for name, stats in by_agent.items():
        n_scored = stats["scored"]
        by_agent_out[name] = {
            "examined": stats["examined"],
            "scored": n_scored,
            "left_null": stats["left_null"],
            "avg_quality": round(stats["sum_quality"] / n_scored, 4) if n_scored else None,
        }
    log.info(
        "backfill_quality_scores examined=%d updated=%d left_null=%d dry_run=%s",
        examined, updated, left_null, dry_run,
    )
    return {
        "examined": examined,
        "updated": updated,
        "left_null": left_null,
        "by_agent": by_agent_out,
        "dry_run": dry_run,
    }


def quality_summary(conn: sqlite3.Connection) -> dict:
    """Average quality_score per agent_name AND per (agent_name, model_version).

    The per-model_version stratification lets the chat answer "did v2
    of the regime prompt outperform v1?" once the corpus is deep enough.
    """
    n_total = conn.execute("SELECT COUNT(*) FROM agent_call_log").fetchone()[0]
    if n_total == 0:
        return {
            "_meta": {
                "lens": "quality_summary",
                "n_total": 0,
                "message": "no agent_call_log rows yet — no LLM calls have been logged",
            },
            "by_agent": [],
            "by_agent_and_version": [],
        }

    by_agent = []
    cur = conn.execute(
        """
        SELECT agent_name,
               COUNT(*) AS n_calls,
               SUM(CASE WHEN quality_score IS NOT NULL THEN 1 ELSE 0 END) AS n_scored,
               AVG(quality_score) AS avg_q
        FROM agent_call_log
        GROUP BY agent_name
        ORDER BY agent_name
        """
    )
    for agent_name, n_calls, n_scored, avg_q in cur.fetchall():
        by_agent.append(
            {
                "agent_name": agent_name,
                "n_calls": int(n_calls),
                "n_scored": int(n_scored or 0),
                "avg_quality": round(float(avg_q), 4) if avg_q is not None else None,
            }
        )

    by_version = []
    cur = conn.execute(
        """
        SELECT agent_name,
               COALESCE(NULLIF(model_version, ''), '<unversioned>') AS mv,
               COALESCE(call_type, '<unset>') AS ct,
               COUNT(*) AS n_calls,
               SUM(CASE WHEN quality_score IS NOT NULL THEN 1 ELSE 0 END) AS n_scored,
               AVG(quality_score) AS avg_q
        FROM agent_call_log
        GROUP BY agent_name, mv, ct
        ORDER BY agent_name, mv, ct
        """
    )
    for agent_name, mv, ct, n_calls, n_scored, avg_q in cur.fetchall():
        by_version.append(
            {
                "agent_name": agent_name,
                "model_version": mv,
                "call_type": ct,
                "n_calls": int(n_calls),
                "n_scored": int(n_scored or 0),
                "avg_quality": round(float(avg_q), 4) if avg_q is not None else None,
            }
        )

    n_scored_total = sum(r["n_scored"] for r in by_agent)
    return {
        "_meta": {
            "lens": "quality_summary",
            "n_total": int(n_total),
            "n_scored": int(n_scored_total),
            "coverage_pct": round(n_scored_total / n_total * 100, 2) if n_total else 0.0,
            "message": (
                f"{n_scored_total}/{n_total} rows have quality_score "
                f"({round(n_scored_total / n_total * 100, 1)}% coverage)"
            ),
        },
        "by_agent": by_agent,
        "by_agent_and_version": by_version,
    }
