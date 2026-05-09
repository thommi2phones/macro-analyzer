# Macro Positioning Analyzer — Dashboard Design Brief

**Audience:** Claw Design (and any future designer or developer working on the system)
**Owner:** Application Agent (delivery) + user (product direction)
**Aesthetic baseline:** institutional-terminal (dark, data-dense, monospaced for numbers)
**Date:** 2026-05-08 (updated 2026-05-09)
**Companion docs:** `docs/macro_thesis_v3.md` (worldview), `docs/trading_framework.md` (rules engine), `docs/inputs_pipeline.md` (data pipeline), `docs/architecture_overview.md` (system architecture)

---

## 1. What this product is

A **macro trading workspace** for a single operator who:
1. Reads dozens of macro newsletters, podcasts, and economic data series
2. Wants a system that *scores* tradeable setups against a defined framework
3. Executes trades **manually** (not automated — see §11)
4. Reviews outcomes weekly to refine the system

The dashboard is the operator's **daily window into the system**. Three top-level routes serve distinct mental modes:
- `/positioning` — the **trading desk** (what to do today)
- `/dev` — the **system room** (what's the system doing under the hood)
- `/journal` — the **review desk** (what worked, what didn't, what to learn)

This is not a CRM. It is not a dashboard for executives. It is the screen a serious trader stares at all day. Closer to Bloomberg Terminal in feel than to Stripe Dashboard in feel.

---

## 2. Aesthetic baseline — LOCKED. Do not deviate.

### 2.1 Core principles

- Dark background (`#0a0e14` or similar deep blue-black)
- Monospaced font for all numbers, prices, scores, percentages
- Sans-serif for narrative text and labels
- Hairline borders (`1px solid var(--border)`), no drop shadows, no rounded corners > 6px
- Color used **only for signal**, never decoration:
  - **Gold/amber** = high conviction / transitional / warning
  - **Green** = bullish / aligned / positive P&L / easing conditions
  - **Red** = bearish / contradictory / negative P&L / tightening
  - **Dim grey** = inactive, stale, unknown, neutral
- No animations beyond instant state changes (no easing, no fade-ins, no pulses)
- Density over whitespace — assume the user wants to see more, not less

### 2.2 What was stripped in the institutional-terminal iteration (2026-05)

The initial build had consumer-product chrome that was explicitly removed. The following are **permanently banned** from this codebase:

| Element | Why removed |
|---|---|
| `backdrop-filter: blur()` on any element | Makes it look like a consumer app, not a terminal |
| `radial-gradient` on body or panels | Decorative, not functional |
| `box-shadow` with glow (e.g. `0 0 12px rgba(...)`) | Glow is decoration, not signal |
| `@keyframes pulse` / animated status dots | Animation for animation's sake |
| `linear-gradient` on nav links, user avatar, brand mark | Marketing chrome |
| Hero copy / taglines / marketing language | This is not a consumer product |
| `.guide-hero` / `.guide-kicker` / promotional section headers | Replaced with bare `<h2 class="h">` |

**Rule:** Every background is `var(--surface)` or `var(--bg-0)` with `1px solid var(--border)`. Color communicates data, not brand.

### 2.3 Color tokens (current)

```css
--bg-0:         #0a0e14
--bg-1:         #0f1419
--bg-2:         #141a22
--surface:      #1a2130
--border:       #2a3444
--text:         #e2e8f0
--text-dim:     #64748b
--accent-1:     #3b82f6   /* blue — links, interactive */
--accent-2:     #6366f1   /* indigo — brand mark */
--green:        #22c55e
--green-2:      #16a34a
--red:          #ef4444
--gold:         #eab308
```

---

## 3. Dashboard architecture (current implementation)

The dashboard is a **Single-Page Application (SPA)**, not server-rendered HTML.

```
web/index.html          — shell, loads React 18 + Babel from CDN
web/positioning.jsx     — all tab components (Positioning, Dev, etc.)
web/styles.css          — shared design tokens + component CSS
```

FastAPI serves the SPA shell and JSON data endpoints. Old Python HTML-generation files (`output_ui.py`, `tactical_ui.py`, `guide_ui.py`) are still present for reference but all routes 307-redirect to the SPA.

**Data binding:**

| Component | Endpoint | Cadence |
|---|---|---|
| Macro indicator strip (regime/FCI/EPU) | `GET /api/dashboard/desk` | on load |
| Command center snapshot | `GET /api/dashboard/command-center` | on demand |
| Brain activity log | `GET /api/dashboard/brain/activity` | 1 min |
| Source health | `GET /api/dashboard/sources` | 5 min |

---

## 4. Information architecture

### 4.1 `/positioning` — Trader view (daily workspace)

**Mental mode:** "what should I do today?"

| Section | Purpose | Key data |
|---|---|---|
| **Macro Indicator Strip** | Regime read in 3 tiles | Regime quadrant badge · FCI score+label · EPU level |
| **Regime tape** | Active framework read | Thesis regime + confidence + trend |
| **Actionable Signals** | Top LONG/SHORT/WATCH | Asset, conviction, horizon, rationale, tactical annotation |
| **Theme clusters** | Macro theme heatmap | Per-theme direction counts + avg confidence |
| **Asset breakdown** | Per-asset drill-down, grouped by class | Asset, dominant direction, conviction, thesis count |
| **Thesis list** | Full deduplicated thesis set | Sorted by confidence, with run_count |

#### MacroIndicatorStrip component

Three-tile row rendered by `MacroIndicatorStrip({ ind })` in `positioning.jsx`.

| Tile | Data | Color coding |
|---|---|---|
| REGIME QUADRANT | `quadrant` (boom/goldilocks/stagflation/deflation/transitional) + growth/inflation signals | `--gold` (boom/stagflation), `--green` (goldilocks), `--red` (deflation), `--text-dim` (transitional) |
| FIN. CONDITIONS | FCI score + label (tightening/neutral/easing) + summary | `--red` (tightening), `--green` (easing), `--text-dim` (neutral) |
| GEO/POLICY RISK | EPU level (elevated/moderate/low) + dominant driver | `--red` (elevated), `--text-dim` (moderate), `--green` (low) |

### 4.2 `/dev` — Builder view

**Mental mode:** "is the system healthy and what is it spending?"

| Section | Purpose | Key data |
|---|---|---|
| **Brain activity** | Last N LLM calls | Timestamp, model, latency, tokens, cost, success |
| **Source health** | Per-source freshness | Source, last fetch, freshness score, trust weight, routing tags |
| **Integration status** | Tactical connectivity | Last poll, contract version, schema drift, `tactical_reachable` flag |
| **Cost tracker** | LLM spend | Today / 7d / 30d by backend |

### 4.3 `/journal` — Review view (PLANNED, not built)

**Mental mode:** "what does the data say about my process?"

Designed in §7 of the original brief. Not yet implemented. See `docs/architecture_overview.md §Open Decisions`.

---

## 5. User journeys

### Journey 1 — Morning briefing (target: 2 min)
1. Open `/positioning`
2. Glance at MacroIndicatorStrip — regime still goldilocks? FCI easing or tightening?
3. Scan actionable signals — anything new at conviction ≥ 0.8?
4. Check active trades (when implemented) — any approaching invalidation?
5. Close. Move on with day.

### Journey 2 — Regime shift response
1. Indicator strip shows stagflation badge (was goldilocks yesterday)
2. Review theme clusters — which themes are driving the shift?
3. Drill into bearish thesis list — which theses are stagflation-related?
4. Reconsider any LONG positions in equities (macro disagrees)

### Journey 3 — Weekly review (target: 20 min, Sunday evening)
1. Open `/journal` (when built)
2. Closed trades → source attribution → thesis change log
3. Source leaderboard → promote/archive sources

---

## 6. Component inventory (atomic UI elements)

### Data display
- **MacroIndicatorStrip** — 3-tile row: regime badge · FCI score · EPU level. CSS: `.indicator-strip`, `.ind-tile`, `.ind-label`, `.ind-value`, `.ind-sub`
- **Regime badge** — pill with regime name. Color from `_QUADRANT_COLOR` map in `positioning.jsx`
- **Score chip** — confidence as `0.00–1.00` in monospaced, color-coded green/red/gold
- **Direction tag** — BULLISH/BEARISH/NEUTRAL/WATCHFUL pill
- **Theme cluster row** — theme name, direction counts (B/bearish/neutral/mixed), avg confidence bar
- **Asset breakdown row** — asset, class badge, dominant direction, conviction, thesis count
- **Actionable signal card** — LONG/SHORT/WATCH badge, asset, conviction bar, horizon, rationale text, optional tactical annotation

### Layout
- **Shared shell** — top bar with route switcher + regime tape + connection dot
- **`.panel`** — `background: var(--surface); border: 1px solid var(--border); border-radius: 8px;`
- **`.h`** — section header: `font-size: 0.7rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-dim)`

---

## 7. Design iteration history

| Date | Change | Rationale |
|---|---|---|
| 2026-04 | Initial HTML dashboard built via Python template rendering | Fastest path to visible output |
| 2026-05-08 | Migrated to React SPA (`web/positioning.jsx`). Old routes 307-redirect. | Enables component reuse, live data binding without full page reload |
| 2026-05-09 | Stripped all consumer-product chrome (blur, gradients, glow, animations, hero copy) | "This is not a consumer product. This should be straight tactical, to the point, very clear to read." |
| 2026-05-09 | Added MacroIndicatorStrip (regime/FCI/EPU 3-tile row) | Urban Kaoberg intelligence layer — regime context above the fold |
| 2026-05-09 | Asset breakdown grouped by asset_class | Urban Kaoberg reference — equities/rates/credit/commodities/fx grouping more readable than flat list |

---

## 8. What this is NOT

- Not an auto-trading interface. Manual execution only.
- Not a multi-user product. One operator.
- Not a portfolio analytics tool. P&L and exposure live elsewhere.
- Not a research workspace. Surfaces what the system has *concluded*, not what to read next.
- Not a consumer app. No marketing copy, no hero imagery, no onboarding flows.

---

## 9. Execution model — IMPORTANT

The system is **manual-execution-first** for the foreseeable future. Tactical-executor wiring is a later phase. Design accordingly: the dashboard is a **decision-support surface**, not a control surface.

---

## 10. Open design questions

1. **How aggressive should the regime-change notification be?** Only on label change (recommended), or on every confidence update?
2. **Where does chart upload happen?** In-card on the setup, or top-level upload zone?
3. **Color-blind safe palette?** Gold/green/amber needs shape redundancy for deuteranopia.
4. **Live-update strategy** — polling vs SSE. Recommend: polling first, SSE only if cadence is a UX bottleneck.
5. **`/journal` view** — designed but not built. Priority after tactical integration.
