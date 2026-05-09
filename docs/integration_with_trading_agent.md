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
