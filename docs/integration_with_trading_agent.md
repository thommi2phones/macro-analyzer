# Integration Contract: Macro Analyzer ↔ Trading Agent V1

> **Last updated:** 2026-05-09
> **Cross-references:** `docs/architecture_overview.md §Contracts Between Layers`

## Purpose

This document defines the contract between the **Macro Analyzer** (this repo)
and the **Trading Agent V1 CODEX** repo
([thommi2phones/Trading-Agent-V1-CODEX](https://github.com/thommi2phones/Trading-Agent-V1-CODEX)).

They are intentionally kept as **two separate codebases** that communicate
through HTTP contracts. Neither depends on the other at the code level —
either can run without the other.

---

## Mental Model

```
┌──────────────────────┐           ┌──────────────────────┐
│  MACRO ANALYZER      │           │  TRADING AGENT V1    │
│  (Python, this repo) │           │  (Node)              │
│                      │           │                      │
│  Strategic brain     │           │  Tactical brain      │
│  Weeks → months      │           │  Intraday → days     │
│                      │           │                      │
│  Inputs:             │           │  Inputs:             │
│  - Newsletters       │           │  - TradingView alerts│
│  - FRED data         │           │  - Chart patterns    │
│  - Analyst notes     │           │  - Momentum indicators│
│                      │           │                      │
│  Outputs:            │           │  Outputs:            │
│  - Directional theses│           │  - LONG/SHORT/WAIT   │
│  - Positioning memo  │           │  - Per-setup decision│
│  - Regime quadrant   │           │                      │
│  - FCI score         │           │                      │
│  - EPU risk level    │           │                      │
└──────────┬───────────┘           └──────────┬───────────┘
           │                                   │
           │         INTEGRATION LAYER         │
           │                                   │
           │  ① Macro view → tactical gate     │
           │  ② Trade outcomes → source score  │
           │  ③ Tactical events → signal annot │
           └───────────────────────────────────┘
```

- **Macro Analyzer** tells you *what to be long/short directionally* and *what the regime is*.
- **Trading Agent** tells you *when and how to enter a specific setup*.

---

## Why Separate Repos

1. **Different tech stacks** — Python/FastAPI vs Node.js. Merging forces a rewrite.
2. **Different cadences** — Macro is batch/on-demand; Trading Agent is real-time webhook-driven.
3. **Different deployment** — Trading Agent runs 24/7 on Render; Macro Analyzer is local/research.
4. **Risk isolation** — changes to macro framework can't break live trading.
5. **Cleaner mental model** — one repo per altitude.

---

## Schema Contract

**Contract version:** `1.0.0`

Schema drift is prevented by a GitHub Actions CI pipeline:
- `schema-export-check` — verifies the schema export matches the codebase on every push to macro-analyzer
- `schema-mirror-pr` — automatically opens a PR in Trading-Agent-V1-CODEX when the integration schema changes
- `schema-drift-check` — blocks merge in Trading-Agent-V1-CODEX if it's out of sync with the latest macro-analyzer schema

---

## Implemented: Tactical Snapshot Pull

**Provider:** Trading Agent V1
**Consumer:** Macro Analyzer (`src/macro_positioning/integration/tactical_client.py`)

Macro Analyzer polls the tactical executor to annotate `ActionableSignal` entries with current setup state. This is a **read-only pull** — macro does not push commands to tactical.

```python
# tactical_client.fetch_tactical_snapshot()
GET {TACTICAL_EXECUTOR_URL}/tactical/snapshot

Response:
{
  "configured": true,
  "events": [
    {
      "payload": {
        "symbol": "GLD",
        "setup_id": "abc123",
        "setup_stage": "trigger",  # watch | trigger | in_trade | tp_zone
        "bias": "BULLISH"
      }
    }
  ]
}
```

When `tactical_reachable = True`, `ActionableSignal.tactical` is populated with a `TacticalAnnotation`:
```python
class TacticalAnnotation(BaseModel):
    active_setups: int = 0
    at_entry: int = 0       # setups in "trigger" stage
    in_trade: int = 0       # setups in "in_trade" stage
    blocked_by_gate: int = 0
    latest_stage: str = ""
```

When unreachable: `CommandCenterSnapshot.tactical_reachable = False`, signals render without annotation.

---

## Planned: Macro View → Tactical Gate

**Provider:** Macro Analyzer
**Consumer:** Trading Agent V1 (`webhook/decision.js`)
**Status:** ⏳ Not yet built

### Request

```http
GET /positioning/view?asset={ticker}&asset_class={class}
```

### Response

```json
{
  "asset": "AAPL",
  "asset_class": "equities",
  "direction": "bearish",
  "confidence": 0.72,
  "horizon": "2-8 weeks",
  "source_theses": ["thesis_id_1", "thesis_id_2"],
  "last_updated": "2026-05-09T14:30:00Z",
  "regime": {
    "quadrant": "stagflation",
    "growth_signal": "contracting",
    "inflation_signal": "elevated",
    "fci_label": "tightening",
    "epu_level": "elevated"
  },
  "gate_suggestion": {
    "allow_long": false,
    "allow_short": true,
    "size_multiplier": 0.8,
    "notes": "Macro disagrees with long setups on equities"
  }
}
```

**Note:** The `regime` block is new vs. original contract design — it surfaces the full quadrant/FCI/EPU context so the tactical side can gate on regime, not just direction. This is a planned addition to the `1.0.0` schema.

### How Trading Agent uses it

```javascript
const macroView = await fetch(
  `${MACRO_ANALYZER_URL}/positioning/view?asset=${packet.symbol}`
).then(r => r.json());

if (packet.bias === 'BULLISH' && !macroView.gate_suggestion.allow_long) {
  return { action: 'WAIT', reason_codes: ['macro_disagrees_long'] };
}
```

---

## Planned: Trade Outcomes → Source Scoring

**Provider:** Macro Analyzer (receives)
**Consumer:** Trading Agent V1 (sends)
**Status:** ⏳ Not yet built

```http
POST /source-scoring/outcome
Content-Type: application/json

{
  "trade_id": "setup_abc123",
  "symbol": "AAPL",
  "direction": "long",
  "entry_timestamp": "2026-04-15T14:00:00Z",
  "exit_timestamp": "2026-04-18T20:30:00Z",
  "outcome": "win",
  "pnl_r": 2.1,
  "macro_view_at_entry": {
    "direction": "bullish",
    "confidence": 0.65,
    "source_theses": ["thesis_id_1", "thesis_id_2"]
  }
}
```

When received, Macro Analyzer:
1. Looks up theses cited in `macro_view_at_entry.source_theses`
2. Identifies newsletter sources those theses came from
3. Updates trust weights: if macro agreed + trade won → bump; agreed + lost → slight decrease
4. Persists to source registry (SQLite)

This creates a feedback loop: **sources that reliably produce profitable macro views get weighted more heavily in future synthesis.**

---

## Planned: Regime Change Push (Alert Routing)

**Provider:** Macro Analyzer (pushes)
**Consumer:** Trading Agent V1
**Status:** ⏳ Future extension

When the regime quadrant flips (e.g. goldilocks → stagflation), Macro Analyzer pushes a notification to Trading Agent to invalidate active setups that no longer agree with the new regime. This is the `applyRegimeUpdate` contract mentioned in architecture planning.

---

## Implementation Status

| Component | Status |
|---|---|
| Integration contract documented | ✅ Done |
| Schema CI pipeline (export-check, mirror-pr, drift-check) | ✅ Done |
| `tactical_client.fetch_tactical_snapshot()` (pull, read-only) | ✅ Done |
| `TacticalAnnotation` on `ActionableSignal` | ✅ Done |
| `CommandCenterSnapshot.tactical_reachable` flag | ✅ Done |
| `GET /positioning/view` endpoint | ⏳ Todo |
| `POST /source-scoring/outcome` endpoint | ⏳ Todo |
| Source scoring update logic | ⏳ Todo |
| Macro gate call in Trading Agent `decision.js` | ⏳ Todo (other repo) |
| Outcome POST in Trading Agent lifecycle | ⏳ Todo (other repo) |
| Regime change push (alert routing) | ⏳ Future |

---

## Graceful Degradation

Both systems **must work without the other**:

- If Trading Agent unreachable → `tactical_reachable = False`; macro dashboard renders without tactical annotations; no blocking
- If Macro Analyzer unreachable → Trading Agent proceeds without macro gate (logs warning, doesn't block trades)
- If `/positioning/view` has no view for a ticker → return `{"direction": "unknown", "gate_suggestion": {"allow_long": true, "allow_short": true}}`
- If source scoring endpoint never receives data → source weights stay at defaults

---

## Not In Scope

- Shared database or data model (each system owns its own persistence)
- Shared authentication (API keys per system)
- Real-time streaming (polling + request-response is sufficient)
- Unified UI (each system has its own dashboard; combined view is future work)

---

## Trade-Close Webhook (PUSH from Trading Agent → Macro Analyzer)

When the Trading Agent closes a position (manual or automated), it POSTs the close event to the macro side so the journal-feedback loop flips the trade into `closed_pending_review` and prompts a structured review.

**Endpoint:** `POST /api/integration/trade-close`

**Auth:** Same bearer-token middleware as the rest of the API (`MPA_AUTH_TOKEN`). Empty in dev = open.

**Request body (JSON):**

| field             | type    | required | notes |
|-------------------|---------|----------|-------|
| `trade_id`        | string  | yes      | Must match an existing `trades.trade_id` on the macro side (otherwise 404) |
| `exit_date`       | string  | no       | ISO-8601 UTC timestamp |
| `exit_price`      | number  | no       | |
| `pnl`             | number  | no       | absolute, in account currency |
| `pnl_percent`     | number  | no       | percentage, e.g. `3.04` for +3.04% |
| `execution_notes` | string  | no       | free-text — e.g. `"stop hit"` / `"discretionary trim"` |

**Example:**

```bash
curl -X POST http://localhost:8001/api/integration/trade-close \
  -H 'content-type: application/json' \
  -d '{
    "trade_id": "trd-2026-014",
    "exit_date": "2026-05-10T14:30:00Z",
    "exit_price": 138.20,
    "pnl": 580.00,
    "pnl_percent": 4.38,
    "execution_notes": "trim into strength"
  }'
```

**Responses:**

| status | body | meaning |
|--------|------|---------|
| 200    | `{"trade_id": "...", "status": "closed", "review_status": "closed_pending_review"}` | flipped (or already in that state — idempotent) |
| 404    | `{"detail": "unknown trade_id: '...'"}` | trade not found on macro side |
| 422    | Pydantic validation envelope | malformed body (missing `trade_id`, wrong types) |

**Idempotency:** Re-POSTing the same payload is safe. If the trade is already `closed_reviewed`, the webhook does NOT revert it — `pnl` / `exit_price` are backfilled if provided but the state stays reviewed. If it's still `closed_pending_review`, exit metadata is updated.

**Side effects:** Sets `trades.status='closed'` and (only on first close) `trades.review_status='closed_pending_review'`. Backfills `exit_date`, `exit_price`, `pnl`, `pnl_percent`, `execution_notes` if supplied. The journal SPA's "pending reviews" strip picks the trade up on the next page load; the user submits the 7-question review via `POST /api/reviews/{trade_id}`, which writes derived `source_outcomes` rows and a calibration log entry.

**Failure mode:** If the macro side is unreachable, the Trading Agent should retry with exponential backoff. The review loop is best-effort feedback — never block trade execution on a failed webhook.

---

## Trade-Check Gate (PULL from Trading Agent → Macro Analyzer)

The Macro Analyzer runs the Trading Rule Framework v1 as a measure-and-flag layer. Trading systems (the external trading agent, or a future native execution layer inside Macro Analyzer) can ask the gate to evaluate a hypothetical trade against:

- Confluence Score (0–8, three subscores: Pattern 0–3, Fib 0–3, Indicator 0–2) and tier (insufficient / standard / high_conviction)
- Account-risk-per-trade % (= |entry − stop| × position_size / equity) vs per-tier caps
- Allocation % vs per-tier floor and absolute ceiling
- Stop sanity (must be on the correct side of entry; entry ≠ stop)
- Portfolio-level caps: max concurrent trades, % deployed, max trades per correlated bucket, max bucket exposure %

Caps live in `config/risk_caps.json`; correlation buckets in `config/correlation_buckets.json`. Edit + restart — no migration.

**Endpoint:** `POST /api/integration/trade-check`

**Auth:** Same bearer-token middleware as the rest of the API (`MPA_AUTH_TOKEN`). Empty in dev = open.

**Request body:**

| field                              | type        | required | notes |
|------------------------------------|-------------|----------|-------|
| `ticker`                           | string      | yes      | |
| `side`                             | `long`\|`short` | yes  | drives stop-direction check |
| `entry`                            | number > 0  | yes      | |
| `stop`                             | number > 0  | yes      | |
| `position_size`                    | number > 0  | yes      | units of the underlying |
| `account_equity`                   | number > 0  | yes      | denominator for risk_pct & allocation_pct |
| `confluence_subscores.pattern`     | int 0..3    | yes      | |
| `confluence_subscores.fib`         | int 0..3    | yes      | |
| `confluence_subscores.indicator`   | int 0..2    | yes      | |
| `setup_category`                   | string      | no       | flag/pennant/channel/hs/cup/range/ema/breakout |
| `tps`                              | number[]    | no       | empty list → `missing_tps` soft violation |
| `mode`                             | `advisory`\|`enforce` | no | default `advisory` (v1) |

**Example:**

```bash
curl -X POST http://localhost:8001/api/integration/trade-check \
  -H 'content-type: application/json' \
  -d '{
    "ticker": "NVDA",
    "side": "long",
    "entry": 500,
    "stop": 475,
    "position_size": 8,
    "account_equity": 100000,
    "confluence_subscores": {"pattern": 3, "fib": 2, "indicator": 1},
    "setup_category": "flag",
    "tps": [525, 550]
  }'
```

**Response shape:**

```json
{
  "approved": true,
  "mode": "advisory",
  "confluence": {"pattern": 3, "fib": 2, "indicator": 1, "total": 6, "tier": "standard"},
  "risk_pct": 0.002,
  "allocation_pct": 0.04,
  "exposure": {
    "concurrent_trades": 0,
    "pct_deployed": 0.0,
    "by_bucket": {}
  },
  "violations": [],
  "suggested_size": null,
  "suggested_stop": null
}
```

**Violation codes (severity):**

| code                                       | severity   | meaning |
|--------------------------------------------|------------|---------|
| `confluence_insufficient`                  | hard       | confluence below standard tier — do not enter |
| `account_risk_exceeded`                    | hard       | risk % over the cap for the trade's confluence tier |
| `allocation_below_standard_floor`          | soft       | allocation under the standard-tier floor |
| `allocation_above_high_conviction_ceiling` | hard       | allocation above the absolute ceiling (~8%) |
| `concurrent_trades_exceeded`               | hard       | adding this trade would breach max-concurrent cap |
| `pct_deployed_exceeded`                    | hard       | adding this trade would push deployed-% over cap |
| `bucket_trade_count_exceeded`              | soft       | bucket would hold more trades than allowed |
| `bucket_exposure_pct_exceeded`             | hard       | bucket would hold more notional than allowed |
| `missing_stop`                             | hard       | entry == stop, no risk defined |
| `missing_tps`                              | soft       | no take-profit levels supplied |
| `stop_on_wrong_side`                       | hard       | long stop ≥ entry or short stop ≤ entry |

**Modes:**

- **`advisory` (default in v1):** evaluator runs end-to-end and returns all violations + their severity. `approved` is always `true`. Use for logging, dashboarding, and pre-adoption measurement.
- **`enforce`:** `approved` is `false` if any violation has severity `hard`. Soft violations remain advisory. Trading agents are free to honor or ignore `approved`; the gate doesn't sit in the order path until the consumer wires it in.

**Suggested adjustments:**

- `suggested_size`: populated when `account_risk_exceeded` fires. Returns the largest position size that complies with the standard 1% account-risk cap given the proposed entry/stop. Re-submit with this size to verify.
- `suggested_stop`: reserved for v2 (would need pattern context).

**Two consumers, one evaluator:**

- **External trading agent (current target):** calls this HTTP endpoint before order submission. One-line insertion in the agent's pre-execute path. Honoring `approved` (vs logging it) is the agent's choice.
- **Future native execution layer:** imports `macro_positioning.rules.gate.evaluate_trade_proposal` directly. The pure function is identical; the HTTP route is just a thin wrapper. Designed so the gate doesn't have to be re-architected when execution moves in-process.

**No side effects:** the gate is read-only. It queries open trades for portfolio exposure but never writes to the DB. Safe to call as often as the consumer likes.
