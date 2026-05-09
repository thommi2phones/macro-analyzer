"""Desk snapshot — the unified MA_DATA payload for the new SPA dashboard.

Lives at `web/index.html` (Claude Design output). The SPA reads
`window.MA_DATA` once on mount, set by `web/data.js` which is served
dynamically by `desk_routes.py` from this module.

This module's job is to return a single dict that matches the contract
in `web/HANDOFF.md`. Where real backend data exists, use it; where it
doesn't, return a sensible empty/seeded shape so the UI still renders
without errors. Each section is a small focused builder so we can
swap stubs for real data section-by-section without restructuring.

Contract sections (16):
1. regime              — REAL via macro_brain regime classifier (stub-driven Phase 4)
2. kpis                — DERIVED from trades + brain calls + cost tracker
3. heroSignals[]       — STUB (top scored setups; needs full scoring run)
4. watchlist[]         — STUB (full scored watchlist)
5. activeTrades[]      — REAL (empty until first manual trade logged)
6. reasoning[]         — STUB (per-setup explain blob; needs scoring history)
7. closedTrades[]      — REAL (empty until first trade closed)
8. missedTrades[]      — REAL (empty until first miss logged)
9. processScorecard    — REAL (derived from logged trades; zero-state OK)
10. sourceLeaderboard[]— REAL (from source_outcomes table; empty initially)
11. thesisChangelog[]  — REAL (seeded from current thesis version)
12. brainActivity[]    — REAL via existing brain_panel (limited data Phase 4)
13. sourceHealth[]     — REAL from sources.json + freshness scoring
14. costTracker        — REAL via brain_panel cost data
15. mgmt               — REAL via existing mgmt_data builder
16. integration        — REAL via tactical_client
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from macro_positioning.core.settings import settings
from macro_positioning.dashboard.checklist import load_checklist
from macro_positioning.dashboard.mgmt_data import _git_recent_commits, _load_decisions
from macro_positioning.ingestion.freshness import (
    average_freshness,
    freshness_label,
    freshness_score,
)
from macro_positioning.ingestion.source_lifecycle import load_sources

# Brain (production agents) — local import to avoid circular imports
from macro_brain.agents.regime_classifier.classifier import classify_regime_stub


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

# Maps thesis_regime → human-readable label for display
_THESIS_REGIME_LABELS = {
    "war_escalation": "War Escalation",
    "inflation_shock": "Inflation Shock",
    "growth_scare": "Growth Scare",
    "dovish_liquidity_wave": "Dovish Liquidity Wave",
    "broad_panic": "Broad Panic",
    "sideways_churn": "Sideways Churn",
    "commodity_expansion": "Commodity Expansion",
}

_FRAMEWORK_REGIME_LABELS = {
    "risk_on_expansion": "Risk-On Expansion",
    "risk_off_contraction": "Risk-Off Contraction",
    "commodity_led_inflation": "Commodity-Led Inflation",
    "monetary_debasement_hard_asset": "Monetary Debasement / Hard Asset",
    "transitional_chop": "Transitional Chop",
}

# v1 framework macro_regimes from config/trading_framework.json
_REGIME_BIASES = {
    "risk_on_expansion": ("bullish", 1.25, 10),
    "risk_off_contraction": ("defensive", 0.5, -15),
    "commodity_led_inflation": ("real_asset_bullish", 1.1, 8),
    "monetary_debasement_hard_asset": ("scarcity_asset_bullish", 1.0, 6),
    "transitional_chop": ("neutral_to_cautious", 0.65, -8),
}


def build_regime_section() -> dict:
    """Active regime read. Phase 4: stub classifier returns
    transitional_chop unless seeded; Phase 6 will read FRED + docs."""
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
        "confidenceTrace": [round(regime.confidence, 2)] * 84,  # TODO: persist daily trace
        "transitions": [
            # TODO: read from macro_regimes table once classifications log
        ],
    }


def build_kpis_section() -> dict:
    """KPI strip aggregates. All zero/empty until trades + brain start logging."""
    return {
        "cashPosture": {"label": "Neutral", "pct": 50, "delta": 0},
        "activeTrades": {"count": 0, "exposureUsd": 0},
        "pnlToday": {"usd": 0.0, "pct": 0.0},
        "pnlWeek": {"usd": 0.0, "pct": 0.0},
        "signalsHigh": {"count": 0, "deltaVsYesterday": 0},
        "spendToday": {"usd": 0.0, "capUsd": 25.0},
    }


def build_hero_signals_section() -> list[dict]:
    """Top-scored setups today. Empty until brain runs against a watchlist."""
    return []


def build_watchlist_section() -> list[dict]:
    """Full scored watchlist. Empty until brain runs."""
    return []


def build_active_trades_section() -> list[dict]:
    """Trades user has open. Empty until first manual log."""
    # TODO: SELECT * FROM trades WHERE status='active' once trade-log endpoint ships
    return []


def build_reasoning_section() -> dict:
    """Per-setup reasoning trail. Empty until scoring history accrues.
    Keyed by signalId; the SPA looks up by id when a hero/watchlist row
    is clicked."""
    return {}


def build_closed_trades_section() -> list[dict]:
    """Closed trades for /journal. Empty until first close."""
    return []


def build_missed_trades_section() -> list[dict]:
    """Missed trades log. Empty until first miss flagged."""
    return []


def build_process_scorecard_section() -> dict:
    """Aggregated process discipline over last 30 days.
    Zero-state shape so /journal still renders."""
    return {
        "windowDays": 30,
        "tradeCount": 0,
        "items": [
            {"label": "Entry planned in advance", "pct": 0, "trend": "flat"},
            {"label": "Invalidation defined", "pct": 0, "trend": "flat"},
            {"label": "Position size predefined", "pct": 0, "trend": "flat"},
            {"label": "Setup matched playbook", "pct": 0, "trend": "flat"},
        ],
    }


def build_source_leaderboard_section() -> list[dict]:
    """Source attribution leaderboard for /journal.
    Phase 4: empty (source_outcomes table empty until trades close)."""
    # TODO: SELECT source_id, SUM(attribution_weight*outcome_pnl_percent) FROM source_outcomes
    return []


def build_thesis_changelog_section() -> list[dict]:
    """Thesis revision log. Seeded with v3 published date."""
    return [
        {
            "date": "2026-04-22",
            "version": "v3",
            "title": "Macro Thesis v3 published",
            "summary": "Capital Rotation Through a Hyper-Liquidity Cycle. 7 thesis regimes. 2-4y horizon.",
            "author": "Lindsey",
        },
    ]


def build_brain_activity_section() -> list[dict]:
    """Recent brain calls. Pulls from brain_calls SQLite table via the
    existing brain_panel module."""
    try:
        from macro_positioning.brain.observability import recent_calls
        calls = recent_calls(limit=20)
    except Exception:
        return []

    out = []
    for c in calls:
        # `recent_calls` returns BrainCallRecord pydantic models
        out.append({
            "ts": getattr(c, "timestamp", None) and c.timestamp.isoformat(),
            "agent": getattr(c, "call_type", "unknown"),
            "model": getattr(c, "model", None) or getattr(c, "backend", "—"),
            "latencyMs": getattr(c, "latency_ms", 0),
            "ok": bool(getattr(c, "success", False)),
            "tokensIn": getattr(c, "input_tokens", None),
            "tokensOut": getattr(c, "output_tokens", None),
            "costUsd": getattr(c, "estimated_cost_usd", None),
        })
    return out


def build_source_health_section() -> list[dict]:
    """Per-source freshness + last fetch + current weight.
    Fetch time + attribution are placeholders until ingestion + outcome
    tracking populate them."""
    sources = load_sources(include_archived=False)
    rows = []
    for s in sources:
        # TODO: pull last_fetched from a sources_state table once exposed
        # TODO: pull 30d attribution from source_outcomes
        sla = s.freshness_sla_hours or 0
        # Stub: assume fresh (real fetch tracking pending)
        score = 1.0 if sla else 1.0
        rows.append({
            "name": s.name,
            "kind": s.source_type,
            "lastFetch": "—",
            "freshness": round(score, 2),
            "freshnessLabel": freshness_label(score),
            "weight": s.trust_weight,
            "attrib30d": 0,
            "tags": s.routing_tags[:5],
            "priority": s.priority,
        })
    return rows


def build_cost_tracker_section() -> dict:
    """Aggregated LLM spend. Pulls from brain_calls (existing) + the
    new agent_call_log table."""
    try:
        from macro_positioning.brain.observability import call_stats
        stats = call_stats()
    except Exception:
        stats = {}
    today = stats.get("cost_usd_today", 0.0) or 0.0
    week = stats.get("cost_usd_week", 0.0) or 0.0
    month = stats.get("cost_usd_month", 0.0) or 0.0
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
    """Project mgmt: todos + decisions + commits. Pulls real data from
    data/checklist.json, data/decisions.json, and `git log`."""
    # Todos — reshape ChecklistItem to MA_DATA shape
    cl = load_checklist()
    status_map = {
        "in_progress": "in_flight",
        "todo": "todo",
        "done": "done",
    }
    # Show top 8 by status priority (in_flight, todo, done)
    items = list(cl.items)
    order = {"in_progress": 0, "todo": 1, "done": 2}
    items.sort(key=lambda i: (order.get(i.status, 9), -1 if i.priority == "critical" else 0))

    todos = []
    for it in items[:10]:
        todos.append({
            "status": status_map.get(it.status, it.status),
            "title": it.title,
            "owner": "Application Agent",  # TODO: read owner from item once schema supports it
            "age": "—",
        })

    # Decisions — reshape from data/decisions.json
    decisions = []
    for d in sorted(_load_decisions(), key=lambda x: x.decided_at, reverse=True)[:6]:
        decisions.append({
            "date": d.decided_at.split("T")[0],
            "title": d.topic,
            "who": "Operator + Application Agent",
        })

    # Commits — reuse existing helper
    commits = []
    for c in _git_recent_commits(limit=8):
        commits.append({
            "hash": c.short_sha,
            "author": c.author,
            "msg": c.subject,
        })

    return {"todos": todos, "decisions": decisions, "commits": commits}


def build_integration_section() -> dict:
    """Tactical-executor integration status."""
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
    whole dashboard. Wrap each in try/except returning the section's
    zero-state shape on failure (logs the failure for ops).
    """
    sections = [
        ("regime", build_regime_section, _empty_regime),
        ("kpis", build_kpis_section, dict),
        ("heroSignals", build_hero_signals_section, list),
        ("watchlist", build_watchlist_section, list),
        ("activeTrades", build_active_trades_section, list),
        ("reasoning", build_reasoning_section, dict),
        ("closedTrades", build_closed_trades_section, list),
        ("missedTrades", build_missed_trades_section, list),
        ("processScorecard", build_process_scorecard_section, dict),
        ("sourceLeaderboard", build_source_leaderboard_section, list),
        ("thesisChangelog", build_thesis_changelog_section, list),
        ("brainActivity", build_brain_activity_section, list),
        ("sourceHealth", build_source_health_section, list),
        ("costTracker", build_cost_tracker_section, dict),
        ("mgmt", build_mgmt_section, dict),
        ("integration", build_integration_section, dict),
    ]
    out: dict[str, Any] = {}
    for key, builder, fallback in sections:
        try:
            out[key] = builder()
        except Exception as exc:
            import sys
            print(f"[desk] section {key} failed: {exc}", file=sys.stderr)
            out[key] = fallback() if callable(fallback) else fallback
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
        "transitions": [],
    }
