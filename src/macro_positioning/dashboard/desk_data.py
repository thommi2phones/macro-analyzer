"""Desk snapshot — the unified MA_DATA payload for the new SPA dashboard.

Lives at `web/index.html` (Claude Design output). The SPA reads
`window.MA_DATA` once on mount, set by `web/data.js` which is served
dynamically by `desk_routes.py` from this module.

This module's job is to return a single dict that matches the contract
in `web/HANDOFF.md` AND the actual JSX field accesses in
`web/{positioning,journal,dev,reasoning,mobile,app}.jsx` — the mock
in `web/data.mock.js` is the canonical schema reference. The shapes
here MUST match the mock's keys precisely or React renders blank.

Where real backend data exists, use it; where it doesn't, return an
empty-but-structurally-valid shape so the UI still renders without
errors. Each section is its own focused builder so we can swap stubs
for real data section-by-section.

Contract sections (16 — see HANDOFF.md):
1. regime              — REAL via macro_brain regime classifier
2. kpis                — STUB (zero-state until trades + brain log)
3. heroSignals[]       — STUB (top scored setups; needs scoring run)
4. watchlist[]         — STUB (full scored watchlist)
5. activeTrades[]      — REAL (empty until first manual trade logged)
6. reasoning{}         — STUB (per-setup explain blob; keyed by signalId)
7. closedTrades[]      — REAL (empty until first trade closed)
8. missedTrades[]      — REAL (empty until first miss logged)
9. processScorecard    — STUB shape (days/score/metrics)
10. sourceLeaderboard[]— REAL (from source_outcomes table; empty initially)
11. thesisChangelog[]  — REAL (seeded from current thesis version)
12. brainActivity[]    — REAL via existing brain_panel
13. sourceHealth[]     — REAL from sources.json + freshness scoring
14. costTracker        — REAL via brain_panel cost data
15. mgmt               — REAL via existing mgmt_data builder
16. integration        — REAL via tactical_client
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from macro_positioning.core.settings import settings
from macro_positioning.dashboard.checklist import load_checklist
from macro_positioning.dashboard.mgmt_data import _git_recent_commits, _load_decisions
from macro_positioning.ingestion.freshness import freshness_label
from macro_positioning.ingestion.source_lifecycle import load_sources

from macro_brain.agents.regime_classifier.classifier import classify_regime_stub


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

_FRAMEWORK_REGIME_LABELS = {
    "risk_on_expansion": "Risk-On Expansion",
    "risk_off_contraction": "Risk-Off Contraction",
    "commodity_led_inflation": "Commodity-Led Inflation",
    "monetary_debasement_hard_asset": "Monetary Debasement / Hard Asset",
    "transitional_chop": "Transitional Chop",
}

_REGIME_BIASES = {
    "risk_on_expansion": ("bullish", 1.25, 10),
    "risk_off_contraction": ("defensive", 0.5, -15),
    "commodity_led_inflation": ("real_asset_bullish", 1.1, 8),
    "monetary_debasement_hard_asset": ("scarcity_asset_bullish", 1.0, 6),
    "transitional_chop": ("neutral_to_cautious", 0.65, -8),
}

# Map source_type → human-readable "kind" displayed in the UI
_SOURCE_TYPE_DISPLAY = {
    "newsletter": "Newsletter",
    "podcast": "Podcast",
    "rss": "RSS",
    "api": "API",
    "gmail": "Gmail",
    "manual_notes": "Notes",
    "chart": "Chart",
}


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_regime_section() -> dict:
    """Active regime read with seeded transition + confidenceTrace."""
    regime = classify_regime_stub(hint_thesis_regime="commodity_expansion")
    bias, sizing, score_mod = _REGIME_BIASES.get(
        regime.framework_regime,
        ("neutral", 1.0, 0),
    )
    return {
        "framework": {
            "label": _FRAMEWORK_REGIME_LABELS.get(regime.framework_regime, regime.framework_regime),
            "slug": regime.framework_regime,
            "confidence": round(regime.confidence, 2),
            "bias": bias,
            "sizingModifier": sizing,
            "scoreModifier": score_mod,
            "sinceDays": 14,  # TODO: compute from regime transition history
        },
        "thesis": {
            "label": "Two-Speed · Liquidity ↔ Structural",
            "narrative": (
                "Liquidity sets the pace, structural energy / resource stress sets "
                "leadership. Capital rotating from index beta into real assets faster "
                "than fundamentals are repaired."
            ),
            "version": "v3",
            "author": "Lindsey",
            "lastRevised": "2026-04-22",
        },
        # 90-day daily regime confidence trace. Seeded as flat at the
        # current confidence; will become real once we persist daily
        # classification snapshots.
        "confidenceTrace": [round(regime.confidence, 2)] * 84,
        "transitions": [
            {
                "date": "2026-04-22",
                "from": "Transitional Chop",
                "to": "Commodity-Led Inflation",
            },
        ],
    }


def build_kpis_section() -> dict:
    """KPI strip aggregates. Zero-state until trades + brain start logging."""
    return {
        "cashPosture": {"label": "Neutral", "pct": 50, "delta": 0},
        "activeTrades": {"count": 0, "exposureUsd": 0},
        "pnlToday": {"usd": 0.0, "pct": 0.0},
        "pnlWeek": {"usd": 0.0, "pct": 0.0},
        "signalsHigh": {"count": 0, "deltaVsYesterday": 0},
        "spendToday": {"usd": 0.0, "capUsd": 25.0},
    }


def build_hero_signals_section() -> list[dict]:
    """Top-scored setups today.

    Schema (per data.mock.js heroSignals[]):
      id, asset, name, side, score, scorePrev, tier, setup,
      regimeFit, entry, stop, target, rr, whyNow[], sources[],
      lastUpdate

    Empty until brain runs against a watchlist.
    """
    return []


def build_watchlist_section() -> list[dict]:
    """Full scored watchlist.

    Schema (per data.mock.js watchlist[]):
      asset, side, score, dScore, tier, regime, tech, vol, rr, last
    """
    return []


def build_active_trades_section() -> list[dict]:
    """Trades user has open.

    Schema (per data.mock.js activeTrades[]):
      id, asset, side, entry, stop, target, sizeUsd, ageDays,
      pnlPct, pnlUsd, regimeAtOpen, scoreAtOpen, scoreNow, status
    """
    # TODO: SELECT * FROM trades WHERE status='active'
    return []


def build_reasoning_section() -> dict:
    """Per-setup reasoning trail keyed by signalId.

    Schema (per data.mock.js reasoning[id]):
      total, tier, components[{label,score,max,color}],
      modifiers[{label,value}], sources[{name,weight,freshness,contrib,tags}],
      theses[{theme,direction,confidence}],
      agentBreakdown[{agent,model,latencyMs,costUsd,ok}]
    """
    return {}


def build_closed_trades_section() -> list[dict]:
    """Closed trades for /journal.

    Schema (per data.mock.js closedTrades[]):
      id, asset, side, entry, exit, pnlPct, holdDays, scoreEntry,
      regimeEntry, thesis, planClean, lesson
    """
    return []


def build_missed_trades_section() -> list[dict]:
    """Missed trades log.

    Schema (per data.mock.js missedTrades[]):
      asset, scoreAtTime, reason, validReal, hindsightRisk, lesson
    """
    return []


def build_process_scorecard_section() -> dict:
    """Process discipline scorecard.

    Schema (per data.mock.js processScorecard):
      days: int
      score: int (overall)
      metrics: [{label, value, of}]

    Zero-state shape so /journal still renders.
    """
    return {
        "days": 30,
        "score": 0,
        "metrics": [
            {"label": "Entry planned in advance", "value": 0, "of": 100},
            {"label": "Invalidation defined", "value": 0, "of": 100},
            {"label": "Size predefined", "value": 0, "of": 100},
            {"label": "Setup matched playbook", "value": 0, "of": 100},
            {"label": "Outcome logged within 24h", "value": 0, "of": 100},
            {"label": "Lesson written", "value": 0, "of": 100},
        ],
    }


def build_source_leaderboard_section() -> list[dict]:
    """Source attribution leaderboard for /journal.

    Schema (per data.mock.js sourceLeaderboard[]):
      name, weight, dWeight, attribUsd, trades, tags
    """
    return []


def build_thesis_changelog_section() -> list[dict]:
    """Thesis revision log.

    Schema (per data.mock.js thesisChangelog[]):
      date, from, to, title, summary, regimes[]
    """
    return [
        {
            "date": "2026-04-22",
            "from": "v2.4",
            "to": "v3.0",
            "title": "Capital Rotation Through Hyper-Liquidity Cycle",
            "summary": (
                "Reframed as two-speed market. Energy + AI explicitly linked. "
                "Cash treated as strategic, not residual."
            ),
            "regimes": [
                "+commodity_expansion",
                "+monetary_debasement_hard_asset",
            ],
        },
    ]


def build_brain_activity_section() -> list[dict]:
    """Recent brain calls.

    Schema (per data.mock.js brainActivity[]):
      ts (HH:MM:SS), agent, model, latencyMs, tokensIn, tokensOut, costUsd, ok
    """
    try:
        from macro_positioning.brain.observability import recent_calls
        calls = recent_calls(limit=10)
    except Exception:
        return []

    out = []
    for c in calls:
        ts_iso = getattr(c, "timestamp", None)
        ts_short = "—"
        if ts_iso:
            try:
                if hasattr(ts_iso, "strftime"):
                    ts_short = ts_iso.strftime("%H:%M:%S")
                else:
                    ts_short = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00")).strftime("%H:%M:%S")
            except Exception:
                ts_short = str(ts_iso)[:8]

        out.append({
            "ts": ts_short,
            "agent": getattr(c, "call_type", "unknown"),
            "model": getattr(c, "model", None) or getattr(c, "backend", "—"),
            "latencyMs": int(getattr(c, "latency_ms", 0) or 0),
            "tokensIn": getattr(c, "input_tokens", 0) or 0,
            "tokensOut": getattr(c, "output_tokens", 0) or 0,
            "costUsd": float(getattr(c, "estimated_cost_usd", 0.0) or 0.0),
            "ok": bool(getattr(c, "success", False)),
        })
    return out


def build_source_health_section() -> list[dict]:
    """Per-source freshness + last fetch + current weight.

    Schema (per data.mock.js sourceHealth[]):
      name, kind, lastFetch (HH:MM), freshness (0..1), weight, attrib30d, tags
    """
    sources = load_sources(include_archived=False)
    rows = []
    for s in sources:
        # TODO: pull last_fetched + 30d attribution from real tables
        sla = s.freshness_sla_hours or 0
        score = 1.0 if sla else 1.0  # placeholder until fetch tracking
        rows.append({
            "name": s.name,
            "kind": _SOURCE_TYPE_DISPLAY.get(s.source_type, s.source_type),
            "lastFetch": "—",
            "freshness": round(score, 2),
            "weight": s.trust_weight,
            "attrib30d": 0,
            "tags": s.routing_tags[:5],
        })
    return rows


def build_cost_tracker_section() -> dict:
    """Aggregated LLM spend.

    Schema (per data.mock.js costTracker):
      today, week, month, capDaily, capMonthly,
      byAgent[{agent, usd}], byBackend[{backend, usd}], spike (bool)
    """
    try:
        from macro_positioning.brain.observability import call_stats
        stats = call_stats()
    except Exception:
        stats = {}
    today = float(stats.get("cost_usd_today", 0.0) or 0.0)
    week = float(stats.get("cost_usd_week", 0.0) or 0.0)
    month = float(stats.get("cost_usd_month", 0.0) or 0.0)
    return {
        "today": round(today, 2),
        "week": round(week, 2),
        "month": round(month, 2),
        "capDaily": 25.0,
        "capMonthly": 600.0,
        "byAgent": [],
        "byBackend": [],
        "spike": today > 25.0,
    }


def build_mgmt_section() -> dict:
    """Project mgmt: todos + decisions + commits.

    Schema (per data.mock.js mgmt):
      todos: [{status, title, owner, age}]
      decisions: [{date, title, who}]
      commits: [{hash, author, msg}]

    `status` in todos: "in_flight" | "todo" | "done" | "blocked"
    """
    cl = load_checklist()
    status_map = {"in_progress": "in_flight", "todo": "todo", "done": "done"}
    items = list(cl.items)
    order = {"in_progress": 0, "todo": 1, "done": 2}
    items.sort(key=lambda i: (order.get(i.status, 9), -1 if i.priority == "critical" else 0))

    todos = []
    for it in items[:10]:
        todos.append({
            "status": status_map.get(it.status, it.status),
            "title": it.title,
            "owner": "Application Agent",
            "age": "—",
        })

    decisions = []
    for d in sorted(_load_decisions(), key=lambda x: x.decided_at, reverse=True)[:6]:
        decisions.append({
            "date": d.decided_at.split("T")[0],
            "title": d.topic,
            "who": "Operator + Application Agent",
        })

    commits = []
    for c in _git_recent_commits(limit=8):
        commits.append({
            "hash": c.short_sha,
            "author": c.author,
            "msg": c.subject,
        })

    return {"todos": todos, "decisions": decisions, "commits": commits}


def build_integration_section() -> dict:
    """Tactical-executor integration status.

    Schema (per data.mock.js integration):
      tactical: {connected, lastPoll, contractVersion, schemaDrift, mode}
    """
    try:
        from macro_positioning.integration import tactical_client
        snap = tactical_client.fetch_tactical_snapshot()
    except Exception:
        snap = {}
    return {
        "tactical": {
            "connected": bool(snap.get("connected", False)),
            "lastPoll": snap.get("last_poll", "—"),
            "contractVersion": snap.get("contract_version", "v3"),
            "schemaDrift": bool(snap.get("schema_drift", False)),
            "mode": "manual",  # per D-2026-05-08-009
        }
    }


# ---------------------------------------------------------------------------
# Top-level snapshot
# ---------------------------------------------------------------------------

def build_desk_snapshot() -> dict:
    """Assemble the full MA_DATA dict the SPA expects.

    Each section is independent — failure in one shouldn't blank the
    whole dashboard. On exception, return that section's zero-state shape.
    """
    sections = [
        ("regime", build_regime_section, _empty_regime),
        ("kpis", build_kpis_section, build_kpis_section),
        ("heroSignals", build_hero_signals_section, list),
        ("watchlist", build_watchlist_section, list),
        ("activeTrades", build_active_trades_section, list),
        ("reasoning", build_reasoning_section, dict),
        ("closedTrades", build_closed_trades_section, list),
        ("missedTrades", build_missed_trades_section, list),
        ("processScorecard", build_process_scorecard_section, build_process_scorecard_section),
        ("sourceLeaderboard", build_source_leaderboard_section, list),
        ("thesisChangelog", build_thesis_changelog_section, list),
        ("brainActivity", build_brain_activity_section, list),
        ("sourceHealth", build_source_health_section, list),
        ("costTracker", build_cost_tracker_section, _empty_cost_tracker),
        ("mgmt", build_mgmt_section, _empty_mgmt),
        ("integration", build_integration_section, _empty_integration),
    ]
    out: dict[str, Any] = {}
    for key, builder, fallback in sections:
        try:
            out[key] = builder()
        except Exception as exc:
            import sys
            print(f"[desk] section {key} failed: {exc}", file=sys.stderr)
            try:
                out[key] = fallback()
            except Exception:
                out[key] = [] if "[]" in str(builder.__doc__ or "") else {}
    return out


def _empty_regime() -> dict:
    return {
        "framework": {
            "label": "Unknown", "slug": "unknown", "confidence": 0.0,
            "bias": "neutral", "sizingModifier": 1.0, "scoreModifier": 0,
            "sinceDays": 0,
        },
        "thesis": {"label": "—", "narrative": "—", "version": "—", "author": "—", "lastRevised": "—"},
        "confidenceTrace": [],
        "transitions": [{"date": "—", "from": "—", "to": "—"}],
    }


def _empty_cost_tracker() -> dict:
    return {
        "today": 0.0, "week": 0.0, "month": 0.0,
        "capDaily": 25.0, "capMonthly": 600.0,
        "byAgent": [], "byBackend": [], "spike": False,
    }


def _empty_mgmt() -> dict:
    return {"todos": [], "decisions": [], "commits": []}


def _empty_integration() -> dict:
    return {"tactical": {"connected": False, "lastPoll": "—", "contractVersion": "—", "schemaDrift": False, "mode": "manual"}}
