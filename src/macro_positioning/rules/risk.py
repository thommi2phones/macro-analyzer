"""Per-trade risk math + sizing validation.

The framework's biggest gap was using "% of capital **allocated**" as
the sizing primitive — a 5% allocation with a wide stop on a volatile
asset risks far more than a 5% allocation with a tight stop. This
module's primitive is account-risk-% = (entry−stop) × size / equity,
which is the only quantity that actually answers "how much can I lose."

All functions are pure. Caps come from config/risk_caps.json via
`rules.load_caps()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from macro_positioning.rules import load_caps


Side = Literal["long", "short"]


@dataclass(frozen=True)
class Violation:
    """A single rule violation. severity drives whether enforce-mode
    would block (`hard`), warn (`soft`), or just record (`advisory`)."""

    code: str
    severity: Literal["hard", "soft", "advisory"]
    message: str

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message}


def account_risk_pct(
    entry: float,
    stop: float,
    position_size: float,
    account_equity: float,
) -> float:
    """Return the account risk fraction (e.g. 0.0075 = 0.75%) of this trade.

    Direction-agnostic — uses |entry − stop|. `position_size` is in
    units of the underlying (shares / coins / contracts). Multiply by
    notional risk-per-unit, then divide by equity.

    Raises ValueError on non-positive equity or non-positive size. A
    zero or negative stop distance returns 0 (caller's job to also
    raise a `missing_stop` / `stop_on_wrong_side` violation).
    """
    if account_equity <= 0:
        raise ValueError("account_equity must be positive")
    if position_size <= 0:
        raise ValueError("position_size must be positive")
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0
    return (risk_per_unit * position_size) / account_equity


def recommended_size(
    entry: float,
    stop: float,
    account_equity: float,
    *,
    target_risk_pct: float | None = None,
    caps_path: str | None = None,
) -> float:
    """Position size that yields exactly `target_risk_pct` (default =
    `max_account_risk_per_trade_pct` from caps). Returns 0 if stop
    distance is zero (caller must surface the missing-stop violation).
    """
    if account_equity <= 0:
        raise ValueError("account_equity must be positive")
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0
    if target_risk_pct is None:
        caps = load_caps(caps_path) if caps_path else load_caps()
        target_risk_pct = caps["trade_level"]["max_account_risk_per_trade_pct"]
    return (account_equity * target_risk_pct) / risk_per_unit


def validate_stop_direction(side: Side, entry: float, stop: float) -> Violation | None:
    """Long stops must be BELOW entry; short stops must be ABOVE.

    Reversed stops are a screaming bug — they don't reduce risk, they
    flip the trade into immediate loss on entry. Always hard.
    """
    if side == "long" and stop >= entry:
        return Violation(
            code="stop_on_wrong_side",
            severity="hard",
            message=f"long stop {stop} must be below entry {entry}",
        )
    if side == "short" and stop <= entry:
        return Violation(
            code="stop_on_wrong_side",
            severity="hard",
            message=f"short stop {stop} must be above entry {entry}",
        )
    return None


def validate_sizing(
    risk_pct: float,
    conviction_tier: Literal["insufficient", "standard", "high_conviction"],
    allocation_pct: float | None = None,
    *,
    caps_path: str | None = None,
) -> list[Violation]:
    """Check the trade against the trade-level caps for its conviction tier.

    Returns all applicable violations (could be 0..N). `allocation_pct`
    is `position_size × entry / equity` — required to police the
    allocation floor/ceiling rules. Pass None to skip that pair of
    checks.
    """
    caps = load_caps(caps_path) if caps_path else load_caps()
    t = caps["trade_level"]
    sevs = caps["severities"]
    out: list[Violation] = []

    if conviction_tier == "insufficient":
        out.append(
            Violation(
                code="confluence_insufficient",
                severity=sevs["confluence_insufficient"],
                message="confluence below standard-trade threshold; do not enter",
            )
        )
        # No further sizing checks make sense for a trade that shouldn't exist.
        return out

    risk_cap = (
        t["high_conviction_account_risk_per_trade_pct"]
        if conviction_tier == "high_conviction"
        else t["max_account_risk_per_trade_pct"]
    )
    if risk_pct > risk_cap:
        out.append(
            Violation(
                code="account_risk_exceeded",
                severity=sevs["account_risk_exceeded"],
                message=(
                    f"account risk {risk_pct:.4f} exceeds cap {risk_cap:.4f} "
                    f"for {conviction_tier} tier"
                ),
            )
        )

    if allocation_pct is not None:
        if conviction_tier == "standard":
            floor = t["standard_allocation_pct_floor"]
            ceil_ = t["standard_allocation_pct_ceiling"]
        else:  # high_conviction
            floor = t["high_conviction_allocation_pct_floor"]
            ceil_ = t["high_conviction_allocation_pct_ceiling"]

        if allocation_pct < floor:
            out.append(
                Violation(
                    code="allocation_below_standard_floor",
                    severity=sevs["allocation_below_standard_floor"],
                    message=(
                        f"allocation {allocation_pct:.4f} below {conviction_tier} "
                        f"floor {floor:.4f}"
                    ),
                )
            )
        # The "above high_conviction ceiling" case is dangerous regardless
        # of tier — a standard-tier trade with 9% allocation is the same
        # problem as a high-conviction trade with 9%.
        if allocation_pct > t["high_conviction_allocation_pct_ceiling"]:
            out.append(
                Violation(
                    code="allocation_above_high_conviction_ceiling",
                    severity=sevs["allocation_above_high_conviction_ceiling"],
                    message=(
                        f"allocation {allocation_pct:.4f} exceeds absolute ceiling "
                        f"{t['high_conviction_allocation_pct_ceiling']:.4f}"
                    ),
                )
            )

    return out
