# Integration Contract: Macro Analyzer ↔ Trading Agent V1

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
└──────────┬───────────┘           └──────────┬───────────┘
           │                                   │
           │         INTEGRATION LAYER         │
           │                                   │
           │  ① Macro view → tactical gate     │
           │  ② Trade outcomes → source score  │
           └───────────────────────────────────┘
```

- **Macro Analyzer** tells you *what to be long/short directionally* (commodities bullish, rates bullish, equities bearish).
- **Trading Agent** tells you *when and how to enter a specific setup* (AAPL long at 182.50, stop 179.80, TP 189).

---

## Why Separate Repos

1. **Different tech stacks** — Python/FastAPI vs Node/Next.js. Merging forces a rewrite.
2. **Different cadences** — Macro is batch/on-demand; Trading Agent is real-time webhook-driven.
3. **Different deployment** — Trading Agent runs 24/7 on Render; Macro Analyzer is local/research.
4. **Risk isolation** — changes to macro framework can't break live trading.
5. **Cleaner mental model** — one repo per altitude.

---

## The Contract

### Endpoint 1: Macro view → Trading Agent decision gate

**Provider:** Macro Analyzer
**Consumer:** Trading Agent V1 (`webhook/decision.js`)

#### Request

```http
GET /positioning/view?asset={ticker}&asset_class={class}
```

Params:
- `asset` — ticker symbol (e.g. `AAPL`, `GLD`, `SPY`)
- `asset_class` — optional: `equities`, `commodities`, `rates`, `fx`, `crypto`, `credit`

#### Response

```json
{
  "asset": "AAPL",
  "asset_class": "equities",
  "direction": "bearish",
  "confidence": 0.72,
  "horizon": "2-8 weeks",
  "source_theses": [
    "thesis_id_1",
    "thesis_id_2"
  ],
  "last_updated": "2026-04-19T14:30:00Z",
  "regime": "Late-cycle slowdown with cooling inflation",
  "gate_suggestion": {
    "allow_long": false,
    "allow_short": true,
    "size_multiplier": 0.8,
    "notes": "Macro disagrees with long setups on equities"
  }
}
```

#### How Trading Agent uses it

In `webhook/decision.js`, after all existing hard gates, add one more call:

```javascript
const macroView = await fetch(
  `${MACRO_ANALYZER_URL}/positioning/view?asset=${packet.symbol}`
).then(r => r.json());

if (packet.bias === 'BULLISH' && !macroView.gate_suggestion.allow_long) {
  return {
    action: 'WAIT',
    confidence: 'LOW',
    risk_tier: 'BLOCKED',
    reason_codes: ['macro_disagrees_long'],
  };
}
```

- If macro says bearish and setup is long → downgrade confidence or block
- If macro says bullish and setup is long → confidence stays, maybe upgrade
- If macro has no view for this asset → allow (graceful fallback)

---

### Endpoint 2: Trade outcomes → source scoring

**Provider:** Macro Analyzer
**Consumer:** Trading Agent V1 (post-trade lifecycle handler)

#### Request

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

Fields:
- `outcome` — `win`, `loss`, `breakeven`
- `pnl_r` — R-multiple (risk units gained/lost)
- `macro_view_at_entry` — snapshot of macro view at trade entry (for attribution)

#### Response

```json
{
  "recorded": true,
  "sources_credited": ["doomberg", "macromicro"],
  "source_weights_updated": {
    "doomberg": { "old": 0.70, "new": 0.72 },
    "macromicro": { "old": 0.65, "new": 0.66 }
  }
}
```

#### How Macro Analyzer uses it

When a trade closes, the Trading Agent posts the outcome back. The Macro
Analyzer:
1. Looks up the theses cited in `macro_view_at_entry.source_theses`
2. Identifies the newsletter sources those theses came from
3. If the macro view agreed with the trade direction and the trade won,
   those sources get a trust weight bump
4. If the macro view agreed but the trade lost, slight trust weight decrease
5. Updates persist to the source registry

This creates a feedback loop: **sources that reliably produce profitable macro views get weighted more heavily in future thesis synthesis.**

---

## Implementation Status

| Component | Status |
|---|---|
| Integration contract documented (this file) | ✅ Done |
| `GET /positioning/view` endpoint in Macro Analyzer | ⏳ Todo |
| `POST /source-scoring/outcome` endpoint in Macro Analyzer | ⏳ Todo |
| Source scoring update logic | ⏳ Todo |
| Macro gate call in Trading Agent `decision.js` | ⏳ Todo (in other repo) |
| Outcome POST call in Trading Agent lifecycle | ⏳ Todo (in other repo) |

---

## Graceful Degradation

Both systems **must work without the other**:

- If Trading Agent can't reach Macro Analyzer → trade decisions proceed without the macro gate (log a warning, don't block)
- If Macro Analyzer never gets outcome data → source weights stay at their defaults (trade history just won't refine them)
- If `/positioning/view` has no view for a ticker → return `{"direction": "unknown", "gate_suggestion": {"allow_long": true, "allow_short": true}}` so the tactical side isn't blocked

---

## Not In Scope

These are intentionally **out of scope** for the integration layer:

- Shared database or data model (each system owns its own persistence)
- Shared authentication (start with endpoint secrecy + API keys per system)
- Real-time streaming (polling / request-response is enough for macro-tactical coordination)
- Unified UI (each system has its own dashboard; a combined view is future work)

---

## Future Extensions

When both systems are mature, possible additions:

1. **Unified dashboard** — a third service that queries both APIs and shows macro + tactical in one view
2. **Shared trade memory vector store** — Trading Agent's trade memory + Macro Analyzer's historical theses in one vector store for retrieval
3. **Alert routing** — when Macro Analyzer detects a regime change, push to Trading Agent to invalidate active setups that no longer agree
4. **Auto-position sizing** — Macro confidence + tactical confidence combined into dynamic R-multiplier
