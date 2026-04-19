"""FastAPI routes for tactical ↔ macro integration.

Endpoints:
  GET  /positioning/view?asset={ticker}  — tactical reads macro view
  GET  /positioning/regime               — current macro regime summary
  POST /source-scoring/outcome           — tactical reports trade outcome
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from macro_positioning.core.settings import settings
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.integration.contracts import (
    CONTRACT_VERSION,
    GateSuggestion,
    MacroOutcomeAck,
    MacroOutcomeReport,
    MacroPositioningView,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["integration"])


# Ticker → asset class heuristic (extend as needed)
_TICKER_TO_CLASS = {
    "SPY": "equities", "QQQ": "equities", "IWM": "equities",
    "GLD": "commodities", "SLV": "commodities", "USO": "energy",
    "TLT": "rates", "IEF": "rates", "SHY": "rates",
    "DXY": "fx", "UUP": "fx",
    "BTC": "crypto", "ETH": "crypto",
    "HYG": "credit", "LQD": "credit",
}


def _infer_asset_class(ticker: str) -> str:
    t = ticker.upper().strip()
    if t in _TICKER_TO_CLASS:
        return _TICKER_TO_CLASS[t]
    # Default heuristic: most tickers are equities
    return "equities"


@router.get("/positioning/view", response_model=MacroPositioningView)
def positioning_view(
    asset: str = Query(..., description="Ticker symbol"),
    asset_class: str | None = Query(None, description="Override asset class inference"),
) -> MacroPositioningView:
    """Return the current macro directional view for a specific ticker.

    Consumed by the tactical-executor decision gate to align tactical
    entries with the strategic macro bias.
    """
    repo = SQLiteRepository(settings.sqlite_path)
    theses = repo.list_theses()

    effective_class = asset_class or _infer_asset_class(asset)

    # Find theses relevant to this asset or asset class
    relevant = []
    for t in theses:
        if t.status.value not in ("active",):
            continue
        # Match by explicit asset mention or theme
        asset_match = asset.lower() in [a.lower() for a in t.assets]
        class_match = effective_class.lower() in t.theme.lower() or any(
            effective_class.lower() in a.lower() for a in t.assets
        )
        if asset_match or class_match:
            relevant.append(t)

    if not relevant:
        return MacroPositioningView(
            asset=asset,
            asset_class=effective_class,
            direction="unknown",
            confidence=0.0,
            gate_suggestion=GateSuggestion(
                allow_long=True, allow_short=True,
                notes="No macro view for this asset — tactical proceeds unfiltered",
            ),
        )

    # Weight-average direction across relevant theses
    direction_scores = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0,
                        "mixed": 0.0, "watchful": 0.0}
    for t in relevant:
        direction_scores[t.direction.value] += t.confidence

    dominant = max(direction_scores, key=direction_scores.get)
    total = sum(direction_scores.values())
    dominant_confidence = direction_scores[dominant] / total if total else 0.0

    # Gate suggestion based on dominant direction
    if dominant == "bullish":
        gate = GateSuggestion(
            allow_long=True, allow_short=False,
            size_multiplier=min(1.0 + dominant_confidence * 0.5, 1.5),
            notes=f"Macro bullish on {effective_class}",
        )
    elif dominant == "bearish":
        gate = GateSuggestion(
            allow_long=False, allow_short=True,
            size_multiplier=min(1.0 + dominant_confidence * 0.5, 1.5),
            notes=f"Macro bearish on {effective_class}",
        )
    elif dominant == "watchful":
        gate = GateSuggestion(
            allow_long=True, allow_short=True, size_multiplier=0.5,
            notes="Macro watchful — reduce size",
        )
    else:
        gate = GateSuggestion(notes="Macro neutral/mixed — no gate preference")

    memo = repo.latest_memo()
    regime = ""
    if memo and memo.summary:
        regime = memo.summary[:200]

    return MacroPositioningView(
        asset=asset,
        asset_class=effective_class,
        direction=dominant,
        confidence=round(dominant_confidence, 3),
        horizon=relevant[0].horizon if relevant else "",
        source_theses=[t.thesis_id for t in relevant[:5]],
        regime=regime,
        gate_suggestion=gate,
    )


@router.get("/positioning/regime")
def positioning_regime() -> dict:
    """Return current macro regime summary from the latest memo."""
    repo = SQLiteRepository(settings.sqlite_path)
    memo = repo.latest_memo()
    if memo is None:
        return {
            "contract_version": CONTRACT_VERSION,
            "regime": "unknown",
            "summary": "No memo generated yet",
        }
    return {
        "contract_version": CONTRACT_VERSION,
        "regime": memo.summary,
        "consensus_views": memo.consensus_views,
        "divergent_views": memo.divergent_views,
        "suggested_positioning": memo.suggested_positioning,
        "generated_at": memo.generated_at.isoformat(),
    }


@router.post("/source-scoring/outcome", response_model=MacroOutcomeAck)
def source_scoring_outcome(report: MacroOutcomeReport) -> MacroOutcomeAck:
    """Accept trade outcomes from tactical-executor and update source weights.

    The feedback loop: sources whose theses led to winning trades get their
    trust weights bumped; sources behind losing trades get nudged down.
    """
    logger.info(
        "Trade outcome received: %s %s, PnL=%.2fR, direction=%s",
        report.symbol, report.direction, report.pnl_r, report.outcome,
    )

    repo = SQLiteRepository(settings.sqlite_path)
    theses = {t.thesis_id: t for t in repo.list_theses()}

    # Find source IDs behind the theses cited in the macro view
    credited_sources: set[str] = set()
    for thesis_id in report.macro_view_at_entry.source_theses:
        t = theses.get(thesis_id)
        if t:
            credited_sources.update(t.source_ids)

    # Determine if macro view was aligned with the trade direction
    macro_direction = report.macro_view_at_entry.direction.lower()
    trade_direction = report.direction.lower()
    macro_aligned = (
        (trade_direction == "long" and macro_direction == "bullish") or
        (trade_direction == "short" and macro_direction == "bearish")
    )

    # Apply outcome to each credited source's weight
    from macro_positioning.integration import source_weights as sw_module
    updates: dict[str, dict] = {}
    for source_id in credited_sources:
        old_weight = sw_module.get_weight(source_id).weight
        updated = sw_module.apply_outcome(
            source_id=source_id,
            outcome=report.outcome,
            macro_aligned=macro_aligned,
        )
        updates[source_id] = {
            "old": round(old_weight, 3),
            "new": round(updated.weight, 3),
            "wins": updated.wins,
            "losses": updated.losses,
        }

    logger.info(
        "Sources credited for outcome %s (aligned=%s): %s",
        report.outcome, macro_aligned, sorted(credited_sources),
    )

    return MacroOutcomeAck(
        recorded=True,
        sources_credited=sorted(credited_sources),
        source_weights_updated=updates,
    )
