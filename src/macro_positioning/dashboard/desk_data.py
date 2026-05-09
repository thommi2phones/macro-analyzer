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

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from macro_positioning.core.settings import settings
from macro_positioning.dashboard.checklist import load_checklist
from macro_positioning.dashboard.mgmt_data import _git_recent_commits, _load_decisions
from macro_positioning.ingestion.freshness import freshness_label
from macro_positioning.ingestion.source_lifecycle import load_sources

from macro_brain.agents.regime_classifier.classifier import classify_regime_stub


# ---------------------------------------------------------------------------
# Macro indicator strip — 1-hour in-process cache
# ---------------------------------------------------------------------------

_INDICATORS_CACHE: dict = {"ts": 0.0, "data": None}
_INDICATORS_TTL_S = 3600

# Minimal FRED series needed for the three classifiers (avoids fetching all 50+)
_INDICATOR_FRED_SERIES = {
    "A191RL1Q225SBEA": ("growth", "Real GDP QoQ Annualised", "%"),
    "INDPRO":          ("growth", "Industrial Production Index", "index"),
    "T10YIE":          ("rates", "10Y Breakeven Inflation", "%"),
    "CPIAUCSL":        ("inflation", "CPI All Urban Consumers", "index"),
    "NFCI":            ("financial_conditions", "Chicago Fed NFCI", "index"),
    "ANFCI":           ("financial_conditions", "Adjusted NFCI", "index"),
    "VIXCLS":          ("financial_conditions", "VIX", "index"),
    "TEDRATE":         ("financial_conditions", "TED Spread", "%"),
    "BAMLH0A0HYM2":    ("financial_conditions", "HY OAS Spread", "%"),
    "USEPUINDXD":      ("geopolitics", "US EPU (daily)", "index"),
    "GEPUCURRENT":     ("geopolitics", "Global EPU", "index"),
    "EPUTRADE":        ("geopolitics", "Trade Policy Uncertainty", "index"),
    "EPUFISCAL":       ("geopolitics", "Fiscal Policy Uncertainty", "index"),
    "EPUMONETARY":     ("geopolitics", "Monetary Policy Uncertainty", "index"),
    "EMVNATSEC":       ("geopolitics", "Equity Vol: National Security", "index"),
}


def _build_macro_indicators() -> dict | None:
    """Fetch FRED + COT data, run classifiers, return indicator strip dict.

    Caches result for 1 hour to avoid FRED round-trips on every dashboard load.
    Returns None on any failure so the strip silently hides itself.
    """
    now = datetime.now(UTC).timestamp()
    if _INDICATORS_CACHE["ts"] > now - _INDICATORS_TTL_S and _INDICATORS_CACHE["data"] is not None:
        return _INDICATORS_CACHE["data"]

    try:
        from macro_positioning.market.fred_provider import FREDMarketDataProvider
        from macro_positioning.market.macro_indicators import (
            classify_growth_inflation_quadrant,
            compute_fci,
            compute_geopolitical_risk,
            compute_cot_positioning,
        )
        from macro_positioning.market.cot_provider import fetch_cot_readings

        provider = FREDMarketDataProvider(series=_INDICATOR_FRED_SERIES, timeout=10.0)
        obs = provider.gather(theses=[])

        quadrant = classify_growth_inflation_quadrant(obs)
        fci = compute_fci(obs)
        epu = compute_geopolitical_risk(obs)

        cot_readings = fetch_cot_readings()
        cot = compute_cot_positioning(cot_readings)

        top_extreme = cot.extremes[0] if cot.extremes else None

        result: dict = {
            "quadrant":         quadrant.quadrant,
            "growthSignal":     quadrant.growth_signal,
            "inflationSignal":  quadrant.inflation_signal,
            "quadrantConf":     quadrant.confidence,
            "fciLabel":         fci.label,
            "fciScore":         fci.score,
            "epuLevel":         epu.level,
            "epuComposite":     epu.composite_score,
            "epuDriver":        epu.dominant_driver,
            "cotTopSignal":     top_extreme.signal if top_extreme else "neutral",
            "cotTopMarket":     top_extreme.market if top_extreme else None,
            "cotTopNetPctOi":   top_extreme.net_pct_oi if top_extreme else None,
            "cotExtremesCount": len(cot.extremes),
            "cotAsOf":          cot.as_of.isoformat() if cot.as_of else None,
        }

        _INDICATORS_CACHE["ts"] = now
        _INDICATORS_CACHE["data"] = result
        return result

    except Exception as exc:
        import sys
        print(f"[desk] macro indicators build failed: {exc}", file=sys.stderr)
        return None


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
    """Active regime read with seeded transition + confidenceTrace + indicator strip."""
    regime = classify_regime_stub(hint_thesis_regime="commodity_expansion")
    bias, sizing, score_mod = _REGIME_BIASES.get(
        regime.framework_regime,
        ("neutral", 1.0, 0),
    )
    out = {
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
    out["indicators"] = _build_macro_indicators()  # None = strip hides itself
    return out


def build_kpis_section() -> dict:
    """KPI strip aggregates. Zero-state until trades log; signalsHigh
    pulls from latest scoring pass."""
    rows = _load_latest_scores()
    high = sum(1 for r in rows if r["score"] >= 75)
    return {
        "cashPosture": {"label": "Neutral", "pct": 50, "delta": 0},
        "activeTrades": {"count": 0, "exposureUsd": 0},
        "pnlToday": {"usd": 0.0, "pct": 0.0},
        "pnlWeek": {"usd": 0.0, "pct": 0.0},
        "signalsHigh": {"count": high, "deltaVsYesterday": 0},
        "spendToday": {"usd": 0.0, "capUsd": 25.0},
    }


# ---------------------------------------------------------------------------
# Scored signals — pulled from trade_scores (populated by `score run`)
# ---------------------------------------------------------------------------

_TIER_LOOKUP = {"tier_1": 1, "tier_2": 2, "tier_3": 3, "avoid": 4}


def _load_latest_scores() -> list[dict]:
    """Pull the most-recent + previous trade_score per asset, joining
    technical_setups + assets, so we can compute dScore (today vs prior
    pass) without a second query.

    The window function ranks scores by scored_at DESC; rn=1 is current,
    rn=2 is prior. Outer LEFT JOIN brings rn=2 onto the rn=1 row.
    """
    if not settings.sqlite_path.exists():
        return []
    with sqlite3.connect(settings.sqlite_path) as conn:
        cur = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    ts.score_id,
                    ts.scored_at,
                    ts.adjusted_total_score,
                    ts.raw_total_score,
                    ts.macro_alignment_score,
                    ts.liquidity_score,
                    ts.sector_theme_score,
                    ts.technical_structure_score,
                    ts.volume_flow_score,
                    ts.risk_reward_score,
                    ts.relative_strength_score,
                    ts.psychology_score,
                    ts.grade,
                    ts.position_size_tier,
                    ts.reasoning_trail_json,
                    tset.asset_id AS asset_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY tset.asset_id
                        ORDER BY ts.scored_at DESC
                    ) AS rn
                FROM trade_scores ts
                JOIN technical_setups tset ON tset.setup_id = ts.setup_id
            ),
            current AS (
                SELECT * FROM ranked WHERE rn = 1
            ),
            prior AS (
                SELECT asset_id,
                       adjusted_total_score AS prior_score,
                       scored_at AS prior_scored_at
                FROM ranked WHERE rn = 2
            )
            SELECT
                c.score_id, c.scored_at, c.adjusted_total_score, c.raw_total_score,
                c.macro_alignment_score, c.liquidity_score, c.sector_theme_score,
                c.technical_structure_score, c.volume_flow_score, c.risk_reward_score,
                c.relative_strength_score, c.psychology_score,
                c.grade, c.position_size_tier, c.reasoning_trail_json,
                a.ticker, a.asset_name, a.asset_class,
                p.prior_score, p.prior_scored_at
            FROM current c
            JOIN assets a ON a.asset_id = c.asset_id
            LEFT JOIN prior p ON p.asset_id = c.asset_id
            ORDER BY c.adjusted_total_score DESC
            """
        )
        rows = cur.fetchall()

    out = []
    for r in rows:
        try:
            trail = json.loads(r[14]) if r[14] else {}
        except Exception:
            trail = {}
        prior_score = r[18]
        d_score = (r[2] - prior_score) if prior_score is not None else 0
        out.append({
            "score_id": r[0],
            "scored_at": r[1],
            "score": r[2],
            "raw_score": r[3],
            "macro": r[4],
            "liquidity": r[5],
            "sector_theme": r[6],
            "tech": r[7],
            "vol": r[8],
            "rr": r[9],
            "rs": r[10],
            "psych": r[11],
            "grade": r[12],
            "tier": r[13],
            "trail": trail,
            "ticker": r[15],
            "name": r[16],
            "asset_class": r[17],
            "prior_score": prior_score,
            "prior_scored_at": r[19],
            "d_score": d_score,
        })
    return out


def _origins_to_pretty(origins: list[str]) -> list[str]:
    """Render watchlist origins for display:
       'anchor'             → 'anchor'
       'theme:uranium'      → 'uranium'
       'mentions:7d:12'     → '7d · 12 mentions'
    """
    out = []
    for o in origins or []:
        if o == "anchor":
            out.append("anchor")
        elif o.startswith("theme:"):
            out.append(o.split(":", 1)[1])
        elif o.startswith("mentions:"):
            parts = o.split(":")
            window = parts[1] if len(parts) > 1 else "?"
            count = parts[2] if len(parts) > 2 else "?"
            out.append(f"{window} · {count} mentions")
        else:
            out.append(o)
    return out


def _tier_str(tier_str: str) -> int:
    return _TIER_LOOKUP.get(tier_str, 4)


def _side_from_tier(tier_str: str) -> str:
    """Coarse heuristic until brain emits side: T1/T2 = LONG, T3 = WATCH, avoid = AVOID."""
    if tier_str == "avoid":
        return "AVOID"
    if tier_str == "tier_3":
        return "WATCH"
    return "LONG"


def build_hero_signals_section() -> list[dict]:
    """Top 5 scored setups (from trade_scores).

    Schema (per data.mock.js heroSignals[]):
      id, asset, name, side, score, scorePrev, tier, setup,
      regimeFit, entry, stop, target, rr, whyNow[], sources[], lastUpdate
    """
    rows = _load_latest_scores()
    top = rows[:5]
    out = []
    for r in top:
        origins = r["trail"].get("watchlist_origins", []) if r["trail"] else []
        why = []
        # Translate trail bits into bullets the user can scan
        if r["trail"].get("active_thesis_regime"):
            why.append(f"Regime fit: {r['trail']['active_thesis_regime']} ({r['trail'].get('active_framework_regime', '—')})")
        if r["trail"].get("regime_modifier"):
            why.append(f"Regime modifier: {r['trail']['regime_modifier']:+d}")
        if origins:
            why.append("Watchlist source: " + ", ".join(_origins_to_pretty(origins)))

        out.append({
            "id": r["score_id"],
            "asset": r["ticker"],
            "name": r["name"] or r["ticker"],
            "side": _side_from_tier(r["tier"]),
            "score": r["score"],
            "scorePrev": r["prior_score"] if r["prior_score"] is not None else r["score"],
            "tier": _tier_str(r["tier"]),
            "setup": "watchlist scoring pass",
            "regimeFit": r["trail"].get("active_framework_regime", "unknown"),
            # Entry/stop/target/RR are 0 until live price + technical agent
            # populate them. SPA uses .toFixed() so null would crash; we
            # send numeric zero and the operator sees 0.00 placeholders.
            "entry": 0.0,
            "stop": 0.0,
            "target": 0.0,
            "rr": 0.0,
            "whyNow": why,
            "sources": _origins_to_pretty(origins),
            "lastUpdate": (r["scored_at"] or "")[11:16],  # HH:MM slice
        })
    return out


def build_watchlist_section() -> list[dict]:
    """Full scored watchlist (every ticker scored in the most recent pass).

    Schema (per data.mock.js watchlist[]):
      asset, side, score, dScore, tier, regime, tech, vol, rr, last
    Plus extras the SPA may use later: name, origins[], assetClass.
    """
    rows = _load_latest_scores()
    out = []
    for r in rows:
        origins = r["trail"].get("watchlist_origins", []) if r["trail"] else []
        out.append({
            "asset": r["ticker"],
            "name": r["name"] or r["ticker"],
            "assetClass": r["asset_class"],
            "side": _side_from_tier(r["tier"]),
            "score": r["score"],
            "dScore": r["d_score"],
            "tier": _tier_str(r["tier"]),
            "regime": "fit" if r["macro"] >= 12 else ("mix" if r["macro"] >= 6 else "off"),
            "tech": _grade_letter(r["tech"], 20),
            "vol": _grade_letter(r["vol"], 15),
            "rr": r["rr"] / 10.0 * 4 if r["rr"] else 0,  # rough display
            "last": (r["scored_at"] or "")[11:16],
            "origins": _origins_to_pretty(origins),
        })
    return out


def _grade_letter(score: int, max_score: int) -> str:
    """Convert 0..max sub-score to A/B/C letter grade for compact display."""
    if max_score <= 0:
        return "—"
    pct = score / max_score
    if pct >= 0.9: return "A"
    if pct >= 0.8: return "A-"
    if pct >= 0.7: return "B+"
    if pct >= 0.6: return "B"
    if pct >= 0.5: return "B-"
    if pct >= 0.4: return "C+"
    if pct >= 0.3: return "C"
    return "D"


def build_active_trades_section() -> list[dict]:
    """Trades user has open.

    Schema (per data.mock.js activeTrades[]):
      id, asset, side, entry, stop, target, sizeUsd, ageDays,
      pnlPct, pnlUsd, regimeAtOpen, scoreAtOpen, scoreNow, status
    """
    # TODO: SELECT * FROM trades WHERE status='active'
    return []


def build_reasoning_section() -> dict:
    """Per-score reasoning trail keyed by score_id (matches heroSignals.id).

    Schema (per data.mock.js reasoning[id]):
      total, tier, components[{label,score,max,color}],
      modifiers[{label,value}], sources[{name,weight,freshness,contrib,tags}],
      theses[{theme,direction,confidence}],
      agentBreakdown[{agent,model,latencyMs,costUsd,ok}]
    """
    rows = _load_latest_scores()
    out: dict[str, dict] = {}

    component_specs = [
        ("Macro alignment", "macro", 20),
        ("Liquidity", "liquidity", 15),
        ("Sector strength", "sector_theme", 10),
        ("Technical structure", "tech", 20),
        ("Volume confirm", "vol", 15),
        ("Risk / Reward", "rr", 10),
        ("Relative strength", "rs", 5),
        ("Psychology · clean", "psych", 5),
    ]

    for r in rows:
        comps = []
        for label, key, max_v in component_specs:
            score = r.get(key, 0)
            color = "green" if (score / max_v) >= 0.7 else "amber" if (score / max_v) >= 0.5 else "red"
            comps.append({"label": label, "score": score, "max": max_v, "color": color})

        modifiers = []
        trail = r.get("trail", {}) or {}
        if trail.get("regime_modifier") is not None:
            modifiers.append({
                "label": f"Regime fit · {trail.get('active_framework_regime', '—')}",
                "value": f"{trail['regime_modifier']:+d}",
            })
        for adj in trail.get("conservative_adjustments_applied", []) or []:
            modifiers.append({"label": adj.replace("_", " "), "value": "applied"})

        origins = trail.get("watchlist_origins", []) or []
        sources_pretty = [
            {
                "name": o,
                "weight": 1.0 if o == "anchor" else 0.7,
                "freshness": "fresh",
                "contrib": 0,
                "tags": [],
            }
            for o in _origins_to_pretty(origins)
        ]

        out[r["score_id"]] = {
            "total": r["score"],
            "tier": _tier_str(r["tier"]),
            "components": comps,
            "modifiers": modifiers,
            "sources": sources_pretty,
            "theses": [],
            "agentBreakdown": [
                {"agent": "regime_classifier", "model": "stub@v0", "latencyMs": 0, "costUsd": 0.0, "ok": True},
                {"agent": "psychology_evaluator", "model": "heuristic", "latencyMs": 0, "costUsd": 0.0, "ok": True},
                {"agent": "score_composer", "model": "heuristic+stubs", "latencyMs": 0, "costUsd": 0.0, "ok": True},
            ],
        }
    return out


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

    Dual-lens fed from learning/source_attribution.py:
      - closed-trade P&L attribution (attribution_30d) → real attribUsd / trades
      - per-mention forward-return tracking (signal_attribution) → weight from
        30d hit_rate when no closed trades yet (so the panel fills before the
        first close)

    Schema (per data.mock.js sourceLeaderboard[]):
      name, weight, dWeight, attribUsd, trades, tags
    """
    if not settings.sqlite_path.exists():
        return []

    try:
        from macro_positioning.learning.source_attribution import (
            attribution_30d,
            signal_attribution,
        )
    except Exception:
        return []

    with sqlite3.connect(settings.sqlite_path) as conn:
        try:
            closed = attribution_30d(conn)
            signals = signal_attribution(conn)
        except Exception:
            return []

        sources = {s.source_id: s for s in load_sources(include_archived=False)}

    def _name(source_id: str) -> str:
        s = sources.get(source_id)
        return s.name if s else source_id

    def _tags(source_id: str, fallback: list[str]) -> list[str]:
        s = sources.get(source_id)
        if s and s.routing_tags:
            return list(s.routing_tags)
        return fallback or []

    by_source: dict[str, dict] = {}

    for row in signals:
        sid = row["source_id"]
        h30 = row.get("horizons", {}).get(30) or {}
        h7 = row.get("horizons", {}).get(7) or {}
        # Prefer 30d hit_rate; fall back to 7d when 30d has no price data yet.
        hr = h30.get("hit_rate") if h30.get("n_with_price_data") else h7.get("hit_rate") or 0.0
        weight = max(0.0, min(1.0, float(hr or 0.0)))
        by_source[sid] = {
            "name": _name(sid),
            "weight": round(weight, 2),
            "dWeight": 0.0,
            "attribUsd": 0,
            "trades": 0,
            "tags": _tags(sid, row.get("verticals", [])),
        }

    for row in closed:
        sid = row["source_id"]
        entry = by_source.setdefault(
            sid,
            {
                "name": _name(sid),
                "weight": 0.0,
                "dWeight": 0.0,
                "attribUsd": 0,
                "trades": 0,
                "tags": _tags(sid, []),
            },
        )
        # source_outcomes rows expose pnl % only (no per-trade notional yet);
        # surface weighted_pnl_pct in basis-points-ish units so the column has
        # signed magnitude. Replace with real USD once outcome notional lands.
        entry["attribUsd"] = int(round(float(row.get("weighted_pnl_pct", 0) or 0) * 100))
        entry["trades"] = int(row.get("n_outcomes", 0) or 0)
        # Closed-trade hit rate trumps signal-derived weight when available:
        # positive weighted_pnl_pct → 0.5..1, negative → 0..0.5.
        wpp = float(row.get("weighted_pnl_pct", 0) or 0)
        entry["weight"] = round(max(0.0, min(1.0, 0.5 + wpp / 200.0)), 2)

    rows = list(by_source.values())
    rows.sort(key=lambda r: (r["attribUsd"], r["weight"]), reverse=True)
    return rows[:20]


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
