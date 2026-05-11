"""Rule-adherence scoring (0..100).

Compares plan + actual + review for a single closed trade and emits a
composite score. Each component contributes a bounded number of points
and is independently inspectable so calibration changes (which tilt
deserves more weight) are a small edit, not a rewrite.

Component weights (sum to 100):

  20  planned-vs-actual entry      |Δ|/planned_entry ≤ 1% = full credit
  20  planned-vs-actual stop       |Δ|/planned_stop  ≤ 1% = full credit
  20  TP discipline                first TP hit before stop / per plan
  20  risk_pct within cap          actual account_risk_pct ≤ tier cap
  10  entry_followed_retest        rule #5 honored (boolean)
  10  confluence tier met sizing   actual confluence high enough for the size taken

If a component's input is missing the component is skipped and its
points are redistributed proportionally across the remaining ones,
so a partial review still yields a meaningful 0..100. The breakdown
returned makes this transparent.

Pure compute over plan/trade/review dicts. Caps from
config/risk_caps.json via rules.load_caps().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from macro_positioning.rules import load_caps
from macro_positioning.rules.confluence import tier_for_score


COMPONENT_WEIGHTS = {
    "entry_fidelity": 20,
    "stop_fidelity": 20,
    "tp_discipline": 20,
    "risk_within_cap": 20,
    "followed_retest": 10,
    "sizing_for_confluence": 10,
}

# A relative price error below this counts as full credit; linearly
# decays to 0 at FIDELITY_MAX_ERROR.
FIDELITY_FULL_CREDIT_ERROR = 0.005   # 0.5%
FIDELITY_MAX_ERROR = 0.05            # 5%


@dataclass(frozen=True)
class AdherenceComponent:
    name: str
    weight: int
    earned: float            # 0..weight
    note: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "weight": self.weight,
            "earned": self.earned,
            "note": self.note,
        }


@dataclass(frozen=True)
class AdherenceScore:
    score: int               # 0..100, redistributed
    raw_earned: float        # sum of earned components before redistribution
    raw_weight: float        # sum of weights of evaluated components
    components: list[AdherenceComponent] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "raw_earned": self.raw_earned,
            "raw_weight": self.raw_weight,
            "components": [c.as_dict() for c in self.components],
        }


def compute_adherence(
    trade: dict,
    plan: dict | None,
    review: dict | None,
    *,
    caps_path: str | None = None,
) -> AdherenceScore:
    """Compute the per-trade adherence score.

    `trade` is the dict shape of a trades row (entry_price, stop_loss,
    pnl_percent, confluence_score, account_risk_pct,
    entry_followed_retest, etc). `plan` is the dict shape of a
    trade_plans row (None if no plan was recorded). `review` is the
    dict shape of a trade_reviews row from
    journal.repository.get_review (None if not yet reviewed).
    """
    caps = load_caps(caps_path) if caps_path else load_caps()
    components: list[AdherenceComponent] = []

    components.append(_score_entry_fidelity(plan, trade))
    components.append(_score_stop_fidelity(plan, trade))
    components.append(_score_tp_discipline(plan, trade, review))
    components.append(_score_risk_within_cap(trade, caps))
    components.append(_score_followed_retest(trade))
    components.append(_score_sizing_for_confluence(plan, trade, caps))

    evaluated = [c for c in components if c.weight > 0]
    raw_earned = sum(c.earned for c in evaluated)
    raw_weight = sum(c.weight for c in evaluated)

    if raw_weight == 0:
        return AdherenceScore(score=0, raw_earned=0.0, raw_weight=0.0, components=components)

    # Redistribute: scale earned / weight to the 0..100 range.
    score = round(100 * raw_earned / raw_weight)
    return AdherenceScore(
        score=int(score),
        raw_earned=raw_earned,
        raw_weight=raw_weight,
        components=components,
    )


# ---------------------------------------------------------------------------
# Individual component scorers — each returns an AdherenceComponent.
# A component with weight=0 was skipped (missing inputs) and is excluded
# from the redistribution math.
# ---------------------------------------------------------------------------


def _score_entry_fidelity(plan: dict | None, trade: dict) -> AdherenceComponent:
    name = "entry_fidelity"
    w = COMPONENT_WEIGHTS[name]
    if plan is None or plan.get("planned_entry") is None or trade.get("entry_price") is None:
        return AdherenceComponent(name, 0, 0.0, "skipped — no plan/entry recorded")
    planned = float(plan["planned_entry"])
    actual = float(trade["entry_price"])
    if planned <= 0:
        return AdherenceComponent(name, 0, 0.0, "skipped — planned_entry not positive")
    rel = abs(actual - planned) / planned
    earned = _fidelity_credit(rel, w)
    return AdherenceComponent(
        name, w, earned,
        f"|Δ|/planned = {rel:.4f} (full ≤ {FIDELITY_FULL_CREDIT_ERROR}, zero ≥ {FIDELITY_MAX_ERROR})",
    )


def _score_stop_fidelity(plan: dict | None, trade: dict) -> AdherenceComponent:
    name = "stop_fidelity"
    w = COMPONENT_WEIGHTS[name]
    if plan is None or plan.get("planned_stop") is None or trade.get("stop_loss") is None:
        return AdherenceComponent(name, 0, 0.0, "skipped — no plan/stop recorded")
    planned = float(plan["planned_stop"])
    actual = float(trade["stop_loss"])
    if planned <= 0:
        return AdherenceComponent(name, 0, 0.0, "skipped — planned_stop not positive")
    rel = abs(actual - planned) / planned
    earned = _fidelity_credit(rel, w)
    return AdherenceComponent(
        name, w, earned,
        f"|Δ|/planned = {rel:.4f}",
    )


def _score_tp_discipline(
    plan: dict | None, trade: dict, review: dict | None
) -> AdherenceComponent:
    """TP discipline is a coarse proxy: a winning trade that hit at
    least the first planned TP gets credit; a losing trade with stop
    intact also keeps credit (it followed the plan, the plan just
    didn't pay). The reviewer's `would_retake` answer informs ambiguity.
    """
    name = "tp_discipline"
    w = COMPONENT_WEIGHTS[name]
    if plan is None:
        return AdherenceComponent(name, 0, 0.0, "skipped — no plan")
    planned_tps = plan.get("planned_tps") or []
    pnl_pct = trade.get("pnl_percent")
    if pnl_pct is None:
        return AdherenceComponent(name, 0, 0.0, "skipped — trade not closed yet")
    if not planned_tps:
        return AdherenceComponent(name, 0, 0.0, "skipped — no planned TPs")

    # Winners: did exit_price reach at least the first TP?
    if pnl_pct > 0:
        entry = trade.get("entry_price") or 0.0
        exit_ = trade.get("exit_price") or 0.0
        first_tp = float(planned_tps[0])
        # Side-agnostic: did the exit pass the first TP in the favorable direction
        # (long: exit >= tp; short: exit <= tp). We infer direction from entry/exit.
        reached = (
            (exit_ >= first_tp and exit_ > entry)
            or (exit_ <= first_tp and exit_ < entry)
        )
        if reached:
            return AdherenceComponent(name, w, float(w), "winner reached first TP")
        return AdherenceComponent(name, w, float(w) * 0.5, "winner but did not reach first TP")

    # Losers: did the trade respect the plan (stopped out, not abandoned early)?
    # If the reviewer marked would_retake = no AND lesson hints at early-exit,
    # that's a discipline ding — but we only have structured fields here.
    # Heuristic: stop intact = full credit; otherwise half.
    plan_stop = plan.get("planned_stop")
    actual_stop = trade.get("stop_loss")
    if plan_stop is not None and actual_stop is not None and abs(plan_stop - actual_stop) / max(plan_stop, 1e-9) < 0.01:
        return AdherenceComponent(name, w, float(w), "loser — stop honored per plan")
    return AdherenceComponent(name, w, float(w) * 0.5, "loser — stop moved from plan")


def _score_risk_within_cap(trade: dict, caps: dict) -> AdherenceComponent:
    name = "risk_within_cap"
    w = COMPONENT_WEIGHTS[name]
    actual_risk = trade.get("account_risk_pct")
    if actual_risk is None:
        return AdherenceComponent(name, 0, 0.0, "skipped — risk_pct not recorded")

    tier = "standard"
    cs = trade.get("confluence_score")
    if cs is not None:
        tier = tier_for_score(int(cs))
        if tier == "insufficient":
            # Trade taken on insufficient confluence — risk math is moot,
            # confluence violation will dominate adherence. Half credit so
            # this trade isn't penalised twice on the risk axis specifically.
            return AdherenceComponent(name, w, float(w) * 0.5, "insufficient confluence — risk axis partial")

    cap = (
        caps["trade_level"]["high_conviction_account_risk_per_trade_pct"]
        if tier == "high_conviction"
        else caps["trade_level"]["max_account_risk_per_trade_pct"]
    )
    if actual_risk <= cap:
        return AdherenceComponent(name, w, float(w), f"{actual_risk:.4f} ≤ cap {cap:.4f}")
    # Linear penalty up to 2x the cap, then zero.
    if actual_risk >= 2 * cap:
        return AdherenceComponent(name, w, 0.0, f"{actual_risk:.4f} ≥ 2× cap {cap:.4f}")
    ratio = (actual_risk - cap) / cap
    earned = w * (1 - ratio)
    return AdherenceComponent(name, w, max(0.0, earned), f"{actual_risk:.4f} over cap {cap:.4f} (linear penalty)")


def _score_followed_retest(trade: dict) -> AdherenceComponent:
    name = "followed_retest"
    w = COMPONENT_WEIGHTS[name]
    flag = trade.get("entry_followed_retest")
    if flag is None:
        return AdherenceComponent(name, 0, 0.0, "skipped — retest flag not set")
    earned = float(w) if int(flag) == 1 else 0.0
    return AdherenceComponent(name, w, earned, "honored" if earned > 0 else "first-impulse entry")


def _score_sizing_for_confluence(
    plan: dict | None, trade: dict, caps: dict
) -> AdherenceComponent:
    """Did the size taken match what the confluence tier allowed?

    standard tier → allocation 3..5%; high_conviction → 7.5..8%;
    insufficient → no trade should have been taken at all.
    """
    name = "sizing_for_confluence"
    w = COMPONENT_WEIGHTS[name]
    cs = trade.get("confluence_score")
    entry = trade.get("entry_price")
    size = trade.get("position_size")
    # Account equity is on plan, not trade
    equity: Optional[float] = None
    if plan is not None:
        equity = plan.get("planned_account_equity")
    if cs is None or entry is None or size is None or not equity:
        return AdherenceComponent(name, 0, 0.0, "skipped — missing confluence / size / equity")

    tier = tier_for_score(int(cs))
    if tier == "insufficient":
        return AdherenceComponent(name, w, 0.0, "trade taken on insufficient confluence — zero credit")

    alloc = (entry * size) / equity
    t = caps["trade_level"]
    if tier == "standard":
        floor = t["standard_allocation_pct_floor"]
        ceil_ = t["standard_allocation_pct_ceiling"]
    else:
        floor = t["high_conviction_allocation_pct_floor"]
        ceil_ = t["high_conviction_allocation_pct_ceiling"]

    if floor <= alloc <= ceil_:
        return AdherenceComponent(name, w, float(w), f"{alloc:.4f} in {tier} band [{floor:.4f}, {ceil_:.4f}]")
    # Partial credit for being on the floor side (under-sized) — still discipline,
    # just leaving money on the table. Zero for over-sized.
    if alloc < floor:
        return AdherenceComponent(name, w, float(w) * 0.5, f"under-sized ({alloc:.4f} < {floor:.4f})")
    return AdherenceComponent(name, w, 0.0, f"over-sized ({alloc:.4f} > {ceil_:.4f})")


def _fidelity_credit(relative_error: float, weight: int) -> float:
    """Linear taper from full credit at FIDELITY_FULL_CREDIT_ERROR
    to zero at FIDELITY_MAX_ERROR."""
    if relative_error <= FIDELITY_FULL_CREDIT_ERROR:
        return float(weight)
    if relative_error >= FIDELITY_MAX_ERROR:
        return 0.0
    span = FIDELITY_MAX_ERROR - FIDELITY_FULL_CREDIT_ERROR
    ratio = (relative_error - FIDELITY_FULL_CREDIT_ERROR) / span
    return float(weight) * (1.0 - ratio)
