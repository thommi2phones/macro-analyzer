"""Item 6 — Retraining trigger signals.

Doesn't actually retrain anything. Just signals when an agent has
accumulated enough new data, drifted in accuracy, or aged out since
its last training pass.

Inputs (all already in the DB):
  - corpus depth: `agent_call_log` row count per agent_name
  - elapsed time: `last_seen` per (agent, model_version) from
    `version_stats`; combined with the in-code defaults below
  - accuracy degradation: item-4 `quality_summary` (per-agent avg)
    + item-5 `regime_accuracy.overall.confirmed_rate` (regime only)

Decision rule (simple-on-purpose; tune via DEFAULT_THRESHOLDS):
  - flag=True if ANY of:
      a. corpus depth >= MIN_CORPUS_FOR_TRAIN[agent]
         AND last training rev is older than MAX_AGE_DAYS
      b. avg quality dropped below QUALITY_FLOOR over the last
         WINDOW_DAYS of calls (compared against the prior window)
      c. (regime_classifier only) confirmed_rate < REGIME_CONFIRM_FLOOR
         over the lookback window

Output: dict with flag + reason + evidence — caller decides what to
do with it (CLI just prints).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from macro_positioning.learning.quality_scorer import quality_summary
from macro_positioning.learning.regime_accuracy import regime_accuracy


log = logging.getLogger(__name__)


# Heuristic thresholds. Tunable here as more data accumulates; future
# work can move these into a `config/retraining_thresholds.json`.
DEFAULT_THRESHOLDS: dict = {
    "min_corpus": {
        "regime_classifier": 200,
        "narrative_synthesizer": 200,
        "technical_scorer": 500,
        "orchestrator": 500,
        "chart_vision": 200,
        "mention_extractor": 1000,
        "_default": 500,
    },
    "max_age_days": 90,
    "quality_floor": 0.55,
    "quality_window_days": 30,
    "regime_confirm_floor": 0.55,
    "regime_lookback_months": 6,
}


KNOWN_AGENTS = (
    "regime_classifier",
    "narrative_synthesizer",
    "technical_scorer",
    "orchestrator",
    "chart_vision",
    "mention_extractor",
)


def _corpus_depth(conn: sqlite3.Connection, agent_name: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM agent_call_log WHERE agent_name = ?",
        (agent_name,),
    ).fetchone()[0]


def _last_seen(conn: sqlite3.Connection, agent_name: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(called_at) FROM agent_call_log WHERE agent_name = ?",
        (agent_name,),
    ).fetchone()
    return row[0] if row else None


def _quality_recent_vs_prior(
    conn: sqlite3.Connection,
    agent_name: str,
    window_days: int,
    now: datetime,
) -> dict:
    """Avg quality_score in the last `window_days` vs the prior window."""
    recent_cut = (now - timedelta(days=window_days)).isoformat()
    prior_cut = (now - timedelta(days=2 * window_days)).isoformat()
    cur = conn.execute(
        """
        SELECT
          AVG(CASE WHEN called_at >= ? THEN quality_score END) AS recent_q,
          SUM(CASE WHEN called_at >= ? AND quality_score IS NOT NULL THEN 1 ELSE 0 END) AS recent_n,
          AVG(CASE WHEN called_at < ? AND called_at >= ? THEN quality_score END) AS prior_q,
          SUM(CASE WHEN called_at < ? AND called_at >= ? AND quality_score IS NOT NULL THEN 1 ELSE 0 END) AS prior_n
        FROM agent_call_log
        WHERE agent_name = ?
        """,
        (recent_cut, recent_cut, recent_cut, prior_cut, recent_cut, prior_cut, agent_name),
    )
    r = cur.fetchone()
    if r is None:
        return {"recent": None, "recent_n": 0, "prior": None, "prior_n": 0}
    return {
        "recent": float(r[0]) if r[0] is not None else None,
        "recent_n": int(r[1] or 0),
        "prior": float(r[2]) if r[2] is not None else None,
        "prior_n": int(r[3] or 0),
    }


def should_retrain(
    conn: sqlite3.Connection,
    agent_name: str,
    *,
    thresholds: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Return {flag, reason, evidence} for one agent.

    `reason` is a short human-readable explanation. `evidence` carries
    the numbers behind the decision so a UI can render "training due
    because corpus=412/200 + last train 120d ago".
    """
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    now = now or datetime.now(timezone.utc)

    corpus = _corpus_depth(conn, agent_name)
    last_seen = _last_seen(conn, agent_name)
    last_seen_dt = None
    age_days = None
    if last_seen:
        try:
            last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            if last_seen_dt.tzinfo is None:
                last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)
            age_days = (now - last_seen_dt).total_seconds() / 86400.0
        except ValueError:
            age_days = None

    min_corpus = t["min_corpus"].get(agent_name, t["min_corpus"].get("_default", 500))
    max_age = t["max_age_days"]
    qfloor = t["quality_floor"]
    qwin = t["quality_window_days"]

    # Quality trend
    qtrend = _quality_recent_vs_prior(conn, agent_name, qwin, now)

    # Regime-specific accuracy (only for regime_classifier)
    regime_overall = None
    if agent_name == "regime_classifier":
        try:
            ra = regime_accuracy(conn, lookback_months=t["regime_lookback_months"], now=now)
            regime_overall = ra.get("overall")
        except Exception as e:
            log.debug("regime_accuracy call failed: %s", e)

    reasons: list[str] = []

    # a. corpus depth + age
    if corpus >= min_corpus and age_days is not None and age_days >= max_age:
        reasons.append(
            f"corpus depth {corpus} >= {min_corpus} AND last call {round(age_days, 1)}d ago "
            f">= {max_age}d threshold"
        )

    # b. quality degradation
    if (
        qtrend["recent"] is not None
        and qtrend["recent_n"] >= 10
        and qtrend["recent"] < qfloor
    ):
        reasons.append(
            f"avg quality_score over last {qwin}d is {round(qtrend['recent'], 3)} "
            f"(n={qtrend['recent_n']}) < floor {qfloor}"
        )
    # b2. quality drop relative to prior window (only when both have signal)
    if (
        qtrend["recent"] is not None and qtrend["prior"] is not None
        and qtrend["recent_n"] >= 10 and qtrend["prior_n"] >= 10
        and qtrend["prior"] - qtrend["recent"] >= 0.10
    ):
        reasons.append(
            f"quality dropped {round(qtrend['prior'] - qtrend['recent'], 3)} "
            f"({round(qtrend['prior'], 3)} → {round(qtrend['recent'], 3)}) "
            f"vs prior {qwin}d window"
        )

    # c. regime accuracy floor
    if regime_overall is not None and (
        regime_overall.get("n_confirmed", 0) + regime_overall.get("n_violated", 0)
        + regime_overall.get("n_partial", 0)
    ) >= 10:
        confirmed_rate = regime_overall.get("confirmed_rate", 0.0)
        if confirmed_rate < t["regime_confirm_floor"]:
            reasons.append(
                f"regime confirmed_rate {confirmed_rate} < floor "
                f"{t['regime_confirm_floor']} over {t['regime_lookback_months']}mo lookback"
            )

    evidence = {
        "corpus_depth": int(corpus),
        "min_corpus": int(min_corpus),
        "last_seen_at": last_seen,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "max_age_days": max_age,
        "quality_recent": qtrend["recent"],
        "quality_recent_n": qtrend["recent_n"],
        "quality_prior": qtrend["prior"],
        "quality_prior_n": qtrend["prior_n"],
        "quality_floor": qfloor,
    }
    if regime_overall is not None:
        evidence["regime_overall"] = regime_overall

    if reasons:
        return {
            "agent_name": agent_name,
            "flag": True,
            "reason": "; ".join(reasons),
            "evidence": evidence,
        }
    return {
        "agent_name": agent_name,
        "flag": False,
        "reason": _no_trigger_reason(
            corpus=corpus, min_corpus=min_corpus,
            age_days=age_days, max_age=max_age,
            qtrend=qtrend, qfloor=qfloor,
        ),
        "evidence": evidence,
    }


def _no_trigger_reason(
    *, corpus, min_corpus, age_days, max_age, qtrend, qfloor,
) -> str:
    """Short explanation for the dashboard when no triggers fire."""
    if corpus == 0:
        return "no logged calls yet — nothing to retrain on"
    parts: list[str] = []
    if corpus < min_corpus:
        parts.append(f"corpus {corpus}/{min_corpus}")
    if age_days is None or age_days < max_age:
        parts.append(
            "fresh" if age_days is not None and age_days < max_age
            else "no age data"
        )
    if qtrend["recent"] is not None and qtrend["recent"] >= qfloor:
        parts.append(f"quality {round(qtrend['recent'], 3)} ≥ {qfloor}")
    return "no triggers fired — " + (", ".join(parts) if parts else "all checks passed")


def retrain_status(
    conn: sqlite3.Connection,
    *,
    agents: tuple[str, ...] = KNOWN_AGENTS,
    thresholds: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Roll up `should_retrain` across all known agents.

    Empty-table-safe — each agent returns a no-trigger row when there
    are no calls.
    """
    rows = [should_retrain(conn, a, thresholds=thresholds, now=now) for a in agents]
    n_flagged = sum(1 for r in rows if r["flag"])
    n_total_calls = conn.execute("SELECT COUNT(*) FROM agent_call_log").fetchone()[0]
    return {
        "_meta": {
            "lens": "retraining_triggers",
            "n_agents_checked": len(rows),
            "n_flagged": n_flagged,
            "n_total_calls": int(n_total_calls),
            "message": (
                f"{n_flagged} of {len(rows)} agents flagged for retraining"
                if n_total_calls > 0 else
                "agent_call_log is empty — no triggers fire (returning baseline rows for shape)"
            ),
        },
        "agents": rows,
    }
