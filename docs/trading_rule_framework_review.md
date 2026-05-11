# Trading Rule Framework v1 — Review

_Reviewed: 2026-05-10_
_Source doc:_ `vendor/trading_agent/docs/project_control/TRADING_RULE_FRAMEWORK_V1.md` (dated 2026-03-02, status "Deferred")
_Reviewer context:_ journal-feedback-loop worker chat (the review desk that will consume the framework's "Rule Adherence Score" and "Deviation flags" outputs)

## What's strong, keep as-is

- **Setup classification with Pattern > Fib > Indicator priority** — matches the chart-analysis framework in `config/chart_analysis_framework.md` and avoids the textbook-indicator trap that `config/rules.yaml` falls into.
- **Confluence score → position sizing class linkage** — right idea (size scales with conviction, not gut).
- **Breakout → Retest → Confirmation as the explicit primary entry** — codifies "no first-impulse trades."
- **Pre-defined TP levels + multi-target scaling** (50 / 50 / runner) — removes mid-trade discretion.
- **Discipline rules** are absolute and clean: no mapped structure → no trade, no predefined TP/stop → no trade, no oversized allocation, no revenge trades, no deviation from breakout-retest.

## Gaps to fix before the framework is enforceable

### 1. Confluence Score is undefined
Drives position sizing and is named throughout the doc, but never specified.
- What inputs feed it? (Pattern type? Fib level color? Indicator alignment count?)
- What scale — 0–10, 0–100, A/B/C/D?
- What thresholds map to standard (3–5%) vs high-conviction (7.5–8%)?

Without this, "must have high confluence score" isn't enforceable and the sizing rule degenerates to feel.

**Recommendation:** define an explicit rubric, e.g.
- Pattern (0–3): 0 none / 1 weak / 2 textbook / 3 textbook + multi-timeframe
- Fib (0–3): 0 none / 1 white confluence / 2 yellow / 3 green at breakout level
- Indicator alignment (0–2): 0 mixed/against / 1 partial / 2 full (MACD + RSI + Squeeze agree)
- Score 0–8. Standard sizing for 5–6, high-conviction only for 7–8.

### 2. No max-loss-per-trade rule
Position sizing is defined as % of capital **allocated**, not % of account **risked**. A 5% allocation with a 20% stop on a volatile crypto = 1% account risk; a 5% allocation with a 5% stop = 0.25% account risk. Same allocation, 4× difference in actual risk.

**Recommendation:** add explicit "max account risk per trade = X%" (typically 0.5–1%) and let position size be derived from that ÷ stop distance, with the 3–5% / 7.5–8% allocation rules as the upper cap.

### 3. No portfolio-level caps
"No overexposure stacking without independent structure validation" is qualitative. Missing:
- **Max concurrent open trades** (e.g., 5)
- **Max correlated exposure** — BTC + SOL + ETH should count as one bucket; XAUUSD + XAGUSD as one; not three separate full-size allocations
- **Max % deployed at once** (e.g., 40% of account)
- **Max single-sector / single-theme exposure** (e.g., no more than 20% in any one crypto theme)

### 4. No drawdown circuit-breaker
Framework prevents bad single trades but doesn't prevent tilt streaks. Nothing covers:
- N consecutive losses → halve sizing for the next M trades
- X% account drawdown → pause new entries until structure resets
- Cool-off after a stop-out (no new entry on the same asset for N bars)

**Recommendation:** add a "Session Discipline" section explicitly. E.g.: 3 consecutive losses → mandatory 24h pause + journal review before next entry.

### 5. "High conviction override" is undefined
Line 65: entries are taken at retest "unless high conviction override condition exists." This is the loophole that swallows discipline rule #5 ("No deviation from breakout-retest rule").

**Recommendation:** either delete the override clause entirely (cleaner), or specify exactly what qualifies — e.g., "confluence score ≥ 8 AND macro regime alignment AND 1D-and-4H structure both confirm." If it can't be specified, it's discretion in a rulebook.

### 6. Options exit logic is vague
"Convert to vertical spread, roll up, hedge via spread structure" lists tools but not triggers.
- At what gain (% or R multiple) do you convert to a spread?
- What delta threshold triggers a roll-up?
- What IV move triggers a hedge?

**Recommendation:** spec the triggers, or mark options as out-of-scope for v1 and revisit when the equities/spot rules are battle-tested.

### 7. No re-entry rule after stop-out
If a trade stops out and the structure re-validates the next day, can you re-enter? How many times before it's revenge trading?

**Recommendation:** allow one re-entry on the same setup after a stop-out, only if (a) structure remains valid and (b) the new stop is at a different invalidation level than the original (otherwise it's the same trade twice).

### 8. No time-stop
Swing trades are "days to weeks" but there's no rule for "if the setup hasn't played out in N bars, exit regardless." Dead-money positions tie up capital and attention.

**Recommendation:** define a time-stop per timeframe — e.g., 1H entries get 5 trading days, 4H entries get 10, 1D entries get 20. If neither stop nor TP1 has been hit, exit at market.

## Journal-feedback-loop tie-in (newly relevant 2026-05-10)

The framework's "Data Capture Requirements" (lines 145–162) and "Performance Analysis Layer" (lines 164–175) anticipated a review desk. That review desk now exists — the journal-feedback-loop v1 shipped this session (`src/macro_positioning/journal/`, branch `claude/upbeat-jang-208651`).

What the journal already captures via the 7-question review:
- Entry / stop / sizing / exit each scored 1–5 → directly feeds the framework's "Rule Adherence Score" (line 180).
- Thesis validity + would-retake + setup-score-hindsight → feeds "Rule refinement based on statistical edge evolution" (line 175).
- Sources credited → feeds attribution (separate from rule adherence, but adjacent).

What's **missing** to fully close the loop on framework v1:
- A field for "**setup category**" (flag / pennant / channel / H&S / cup-and-handle / range break / EMA structure) on the trade row itself. Currently the review captures thesis validity but not setup type, so "win rate per setup type" (line 167) isn't queryable.
- A field for "**confluence score at entry**" on the trade row — once the score is defined per gap #1 above. Without it, "win rate per confluence tier" (line 168) isn't queryable either.
- A "**deviation flag**" — boolean on the trade indicating whether the entry followed the breakout-retest rule or used an override. Lets PM compute the rule-adherence percentage cleanly.

These are PM/schema decisions, not journal-worker territory — flagging for the long-lived chat queue.

## Recommended next moves (in priority order)

1. **Define the Confluence Score rubric** — unlocks gaps #1 and the journal additions.
2. **Add max-account-risk-per-trade and portfolio caps** (gaps #2, #3) — biggest single bang for buck; prevents the failure modes most likely to end the account.
3. **Add session-discipline / drawdown circuit-breaker** (gap #4).
4. **Either delete or specify the high-conviction override** (gap #5).
5. **Add setup_category and confluence_score columns to `trades`** so the journal can attribute outcomes by category (PM / schema territory, not this worker).
6. Defer options-trigger spec (gap #6) and time-stop calibration (gap #8) until the equities/spot rules have run live for a quarter.

## What this review does NOT do

- It does not edit the framework doc itself — that lives in `vendor/trading_agent/`, which `VENDORED.md` marks read-only.
- It does not modify the upstream `~/Documents/Personal/Code Projects/trading_agent/` repo.
- The journal-feedback-loop worker stays scoped to its file territory; schema/sizing/risk additions belong elsewhere.
