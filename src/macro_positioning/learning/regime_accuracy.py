"""Item 5 — Regime classifier accuracy backtest.

Reads every row in `regime_classifications` (written by macro_brain's
regime_classifier agent each pass) and checks whether the regime
label's `config/regime_outcomes.json` expectations played out within
the configured horizon window.

Different from item 4
─────────────────────
Item 4 (quality_scorer) writes a per-call score to agent_call_log so
training data carries a label. Item 5 is the time-series rollup:
how does the classifier perform month-by-month? That answers "is the
classifier degrading?", which feeds item 6's retraining trigger.

Empty-state behaviour
─────────────────────
`regime_classifications` is populated by the LLM-agents chat
(committed-pending-merge). Today the table will be empty. We return
the v3-pattern `_meta` block explaining that, so the dashboard's
"awaiting first run" state is informative.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from macro_positioning.learning.quality_scorer import (
    _check_expectation,
    _load_regime_outcomes,
)
from macro_positioning.learning.source_attribution import (
    _load_close_lookup,
    _parse_iso,
)


log = logging.getLogger(__name__)


def _classify_row(
    label: str,
    called_at: datetime,
    closes: dict,
    regimes_cfg: dict,
) -> dict:
    """Return a per-call verdict dict.

    verdict ∈ {'confirmed', 'partial', 'violated', 'pending', 'no_config'}
      - confirmed: all primary expectations met
      - partial:   some met, none violated, some pending price data
      - violated:  any primary expectation violated
      - pending:   all expectations lack forward price data yet
      - no_config: no expectations defined for this regime label
    """
    cfg = regimes_cfg.get(label)
    if not cfg:
        return {"label": label, "verdict": "no_config", "expectations": []}
    expectations = cfg.get("expectations", []) or []
    if not expectations:
        return {"label": label, "verdict": "no_config", "expectations": []}

    results = []
    n_met = n_violated = n_unknown = 0
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

    if n_violated >= 1:
        verdict = "violated"
    elif n_unknown == len(expectations):
        verdict = "pending"
    elif n_met == len(expectations):
        verdict = "confirmed"
    else:
        verdict = "partial"
    return {
        "label": label,
        "verdict": verdict,
        "n_met": n_met,
        "n_violated": n_violated,
        "n_unknown": n_unknown,
        "expectations": results,
    }


def regime_accuracy(
    conn: sqlite3.Connection,
    *,
    lookback_months: int = 12,
    now: datetime | None = None,
) -> dict:
    """Monthly rollup of regime_classifier verdicts over the last
    `lookback_months`.

    Returns:
      {
        "_meta": {lens, n_classifications, n_in_window, lookback_months, message},
        "by_month": [{"bucket": "YYYY-MM", "n_total", "n_confirmed",
                      "n_partial", "n_violated", "n_pending", "n_no_config",
                      "confirmed_rate", "violated_rate"}],
        "by_label": [{"label", "n_total", "n_confirmed", "n_violated",
                      "n_pending", "confirmed_rate"}],
        "overall": {n_confirmed, n_partial, n_violated, n_pending,
                    confirmed_rate, violated_rate}
      }
    """
    now = now or datetime.now(timezone.utc)
    # naive lookback: 30-day approx months. Good enough for monthly buckets;
    # we filter on the called_at year-month rather than exact day.
    from datetime import timedelta
    cutoff = (now - timedelta(days=30 * lookback_months)).isoformat()

    n_total = conn.execute("SELECT COUNT(*) FROM regime_classifications").fetchone()[0]
    cur = conn.execute(
        """
        SELECT classification_id, asof, label
        FROM regime_classifications
        WHERE asof >= ?
        ORDER BY asof ASC
        """,
        (cutoff,),
    )
    rows = cur.fetchall()

    if not rows:
        msg = (
            "regime_classifications table is empty — LLM-agents chat hasn't merged yet"
            if n_total == 0 else
            f"{n_total} classifications exist but none within the last {lookback_months}mo"
        )
        log.info("regime_accuracy: %s", msg)
        return {
            "_meta": {
                "lens": "regime_accuracy",
                "n_classifications": int(n_total),
                "n_in_window": 0,
                "lookback_months": lookback_months,
                "message": msg,
            },
            "by_month": [],
            "by_label": [],
            "overall": {
                "n_confirmed": 0, "n_partial": 0, "n_violated": 0,
                "n_pending": 0, "n_no_config": 0,
                "confirmed_rate": 0.0, "violated_rate": 0.0,
            },
        }

    regimes_cfg = (_load_regime_outcomes() or {}).get("regimes", {})
    # Preload price closes for every ticker mentioned in any expectation.
    tickers: set[str] = set()
    for cfg in regimes_cfg.values():
        for e in cfg.get("expectations", []) + cfg.get("negation_expectations", []):
            if e.get("ticker"):
                tickers.add(e["ticker"].upper())
    closes = _load_close_lookup(conn, tickers) if tickers else {}

    by_month: dict[str, dict] = defaultdict(
        lambda: {
            "n_total": 0, "n_confirmed": 0, "n_partial": 0,
            "n_violated": 0, "n_pending": 0, "n_no_config": 0,
        }
    )
    by_label: dict[str, dict] = defaultdict(
        lambda: {
            "n_total": 0, "n_confirmed": 0, "n_partial": 0,
            "n_violated": 0, "n_pending": 0, "n_no_config": 0,
        }
    )
    overall = {
        "n_confirmed": 0, "n_partial": 0, "n_violated": 0,
        "n_pending": 0, "n_no_config": 0,
    }

    for _cid, asof, label in rows:
        dt = _parse_iso(asof)
        if dt is None:
            continue
        verdict_row = _classify_row(label or "", dt, closes, regimes_cfg)
        verdict = verdict_row["verdict"]
        bucket_key = dt.strftime("%Y-%m")
        m = by_month[bucket_key]
        l = by_label[label or "<empty>"]
        for store in (m, l):
            store["n_total"] += 1
            store[f"n_{verdict}"] = store.get(f"n_{verdict}", 0) + 1
        overall[f"n_{verdict}"] = overall.get(f"n_{verdict}", 0) + 1

    def _rates(store: dict) -> dict:
        n = store["n_total"] if "n_total" in store else (
            store["n_confirmed"] + store["n_partial"] + store["n_violated"]
            + store["n_pending"] + store["n_no_config"]
        )
        # Confirmed / violated rates are over only the rows where we
        # had enough data to judge (exclude pending + no_config).
        judged = store["n_confirmed"] + store["n_partial"] + store["n_violated"]
        out = dict(store)
        out["confirmed_rate"] = round(store["n_confirmed"] / judged, 4) if judged else 0.0
        out["violated_rate"] = round(store["n_violated"] / judged, 4) if judged else 0.0
        return out

    by_month_out = [
        {"bucket": k, **_rates(v)}
        for k, v in sorted(by_month.items())
    ]
    by_label_out = [
        {"label": k, **_rates(v)}
        for k, v in sorted(by_label.items())
    ]
    overall_out = _rates({**overall, "n_total": len(rows)})
    overall_out.pop("n_total", None)

    return {
        "_meta": {
            "lens": "regime_accuracy",
            "n_classifications": int(n_total),
            "n_in_window": len(rows),
            "lookback_months": lookback_months,
            "message": f"{len(rows)} classifications across {len(by_month_out)} months",
        },
        "by_month": by_month_out,
        "by_label": by_label_out,
        "overall": overall_out,
    }
