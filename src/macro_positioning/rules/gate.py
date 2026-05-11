"""Trade-check gate — composes confluence + risk + portfolio into one decision.

Pure function, importable in-process. The HTTP wrapper in
api/rules_routes.py is a thin shell — same evaluator, two boundaries:

  - external trading agent → POSTs to /api/integration/trade-check
  - future native execution → imports `evaluate_trade_proposal` directly

v1 default mode is "advisory": violations are returned but `approved`
always = True. Flipping to "enforce" makes any `hard` violation force
`approved=False`. The flip is a single argument; no architectural
rework needed when a consumer earns the gate's trust.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Literal, Optional

from macro_positioning.rules import load_caps
from macro_positioning.rules.confluence import (
    ConfluenceBreakdown,
    score_confluence,
)
from macro_positioning.rules.portfolio import (
    ExposureSnapshot,
    check_portfolio_caps,
    current_exposure,
)
from macro_positioning.rules.risk import (
    Side,
    Violation,
    account_risk_pct,
    recommended_size,
    validate_sizing,
    validate_stop_direction,
)


Mode = Literal["advisory", "enforce"]


@dataclass(frozen=True)
class TradeProposal:
    """Everything the gate needs to evaluate a hypothetical trade.

    `confluence_subscores` is a 3-tuple (pattern, fib, indicator).
    `tps` is required to be non-empty for the gate to skip the
    missing-tps soft violation.
    """

    ticker: str
    side: Side
    entry: float
    stop: float
    position_size: float
    account_equity: float
    confluence_subscores: tuple[int, int, int]
    setup_category: Optional[str] = None
    tps: tuple[float, ...] = ()

    def notional(self) -> float:
        return self.entry * self.position_size

    def allocation_pct(self) -> float:
        return self.notional() / self.account_equity if self.account_equity > 0 else 0.0


@dataclass(frozen=True)
class GateDecision:
    approved: bool
    mode: Mode
    confluence: ConfluenceBreakdown
    risk_pct: float
    allocation_pct: float
    exposure: ExposureSnapshot
    violations: list[Violation] = field(default_factory=list)
    suggested_size: Optional[float] = None
    suggested_stop: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "mode": self.mode,
            "confluence": self.confluence.as_dict(),
            "risk_pct": self.risk_pct,
            "allocation_pct": self.allocation_pct,
            "exposure": self.exposure.as_dict(),
            "violations": [v.as_dict() for v in self.violations],
            "suggested_size": self.suggested_size,
            "suggested_stop": self.suggested_stop,
        }


def evaluate_trade_proposal(
    proposal: TradeProposal,
    conn: sqlite3.Connection,
    *,
    mode: Mode = "advisory",
    caps_path: str | None = None,
    buckets_path: str | None = None,
) -> GateDecision:
    """Evaluate `proposal` against all v1 rules and return a `GateDecision`.

    Order of checks: confluence (drives tier → sizing caps) → stop sanity
    → account-risk + allocation sizing → portfolio caps. Each layer
    contributes 0..N violations; nothing short-circuits, so the caller
    sees the full picture even when multiple things are wrong.

    In `advisory` mode, `approved` is always True. In `enforce` mode,
    any `hard`-severity violation forces `approved=False`.
    """
    caps = load_caps(caps_path) if caps_path else load_caps()
    sevs = caps["severities"]
    violations: list[Violation] = []

    # 1. Confluence + tier
    p, f, i = proposal.confluence_subscores
    confluence = score_confluence(p, f, i, caps_path=caps_path)

    # 2. Missing stop / TPs (cheap checks before any math)
    if proposal.stop == proposal.entry:
        violations.append(
            Violation(
                code="missing_stop",
                severity=sevs["missing_stop"],
                message="entry and stop are equal — no risk defined",
            )
        )
    if not proposal.tps:
        violations.append(
            Violation(
                code="missing_tps",
                severity=sevs["missing_tps"],
                message="no take-profit levels supplied",
            )
        )

    # 3. Stop on the right side
    stop_v = validate_stop_direction(proposal.side, proposal.entry, proposal.stop)
    if stop_v is not None:
        violations.append(stop_v)

    # 4. Risk + sizing
    try:
        risk_pct = account_risk_pct(
            proposal.entry,
            proposal.stop,
            proposal.position_size,
            proposal.account_equity,
        )
    except ValueError as e:
        # Invalid inputs (zero equity / size) — treat as hard violation
        # but still return a populated decision so the caller can see
        # the structure of the rejection.
        violations.append(
            Violation(code="invalid_input", severity="hard", message=str(e))
        )
        risk_pct = 0.0

    alloc_pct = proposal.allocation_pct()
    violations.extend(
        validate_sizing(
            risk_pct,
            confluence.tier,
            allocation_pct=alloc_pct,
            caps_path=caps_path,
        )
    )

    # 5. Portfolio-level checks (skip if equity invalid — we already
    # flagged it above, and current_exposure would also raise)
    if proposal.account_equity > 0:
        exposure = current_exposure(
            conn, proposal.account_equity, buckets_path=buckets_path
        )
        violations.extend(
            check_portfolio_caps(
                exposure,
                proposed_ticker=proposal.ticker,
                proposed_notional=proposal.notional(),
                account_equity=proposal.account_equity,
                caps_path=caps_path,
                buckets_path=buckets_path,
            )
        )
    else:
        exposure = ExposureSnapshot(concurrent_trades=0, pct_deployed=0.0)

    # 6. Suggestions when the trade fails on sizing
    suggested_size: Optional[float] = None
    if any(v.code == "account_risk_exceeded" for v in violations):
        suggested_size = recommended_size(
            proposal.entry,
            proposal.stop,
            proposal.account_equity,
            caps_path=caps_path,
        )

    # 7. Approval decision
    if mode == "enforce":
        approved = not any(v.severity == "hard" for v in violations)
    else:
        approved = True

    return GateDecision(
        approved=approved,
        mode=mode,
        confluence=confluence,
        risk_pct=risk_pct,
        allocation_pct=alloc_pct,
        exposure=exposure,
        violations=violations,
        suggested_size=suggested_size,
        suggested_stop=None,  # reserved for v2 (would need pattern context)
    )
