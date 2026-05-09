# Macro Positioning Analyzer — Dashboard Design Brief

**Audience:** Claw Design (and any future designer working on the system)
**Owner:** Application Agent (delivery) + user (product direction)
**Aesthetic baseline:** institutional-terminal (dark, data-dense, monospaced for numbers)
**Date:** 2026-05-08
**Companion docs:** `docs/macro_thesis_v3.md` (worldview), `docs/trading_framework.md` (rules engine), `docs/inputs_pipeline.md` (data pipeline)

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

## 2. Aesthetic baseline (already established — preserve, don't replace)

The current `/positioning` and `/dev` views (commit `5533b3a`) established:
- Dark background (`#0a0e14` or similar deep blue-black)
- Monospaced font for all numbers, prices, scores, percentages
- Sans-serif for narrative text and labels
- Hairline borders, no drop shadows, no rounded corners > 4px
- Color used sparingly and meaningfully:
  - **Gold/amber** = high conviction
  - **Green** = bullish / aligned / positive P&L
  - **Red** = bearish / contradictory / negative P&L
  - **Dim grey** = inactive, stale, unknown
- No animations beyond instant state changes (no easing, no fade-ins)
- Density over whitespace — assume the user wants to see more, not less

Claw Design should **refine** this — sharper typography, better spacing rhythm, clearer hierarchy — but **not** replace it with a brighter / friendlier / more "modern SaaS" aesthetic. The user's mental model is "institutional terminal" not "consumer app."

---

## 3. Information architecture

### 3.1 `/positioning` — Trader view (daily workspace)

**Mental mode:** "what should I do today?"

The screen the user opens every morning and checks throughout the day. Must work both on a 27" desktop monitor and on a phone (regime tape + hero signals + active trades, at minimum).

| Section | Purpose | Key data | Refresh cadence |
|---|---|---|---|
| **Regime tape** (top, always visible) | Current regime read in one glance | Active framework regime + active thesis regime + confidence + 7d trend sparkline | every 5 min |
| **Hero signal cards** (3-5 cards) | Today's highest-scored actionable setups | Asset, score 0-100, tier color, setup type, entry/invalidation/target, why-this-now (3 bullets) | on demand |
| **Watchlist scored table** | Full scored watchlist | Asset, score, score Δ vs yesterday, tier, regime fit, technical, volume, R/R, last update | every 15 min |
| **Active trades panel** | Trades user has open (manually entered) | Asset, entry, stop, target, current P&L %, age in days, regime when opened, score when opened, score now | every 5 min |
| **Reasoning trail** (drill-down sheet) | Why a setup got its score | Per-component sub-scores, contributing sources with weights, contributing theses, agent-by-agent breakdown, raw feature vector toggle | on click |
| **Manual trade log** (entry form, inline) | User logs a trade after executing manually | Asset (autocomplete), entry, size, stop, target, link to setup_id, optional notes | submit |
| **Outcome log** (entry form, inline) | User closes a trade | Exit, P&L, was-it-the-thesis (yes/no/partial), lesson (free text), hindsight bias check (radio) | submit |

### 3.2 `/dev` — Builder view

**Mental mode:** "is the system healthy and what is it spending?"

For ongoing project work, system health, observability. Desktop-first.

| Section | Purpose | Key data | Refresh cadence |
|---|---|---|---|
| **Project mgmt panel** (NEW) | Live to-do, decisions log, recent commits | `data/checklist.json` items grouped by status, recent decisions from chat threads, last 10 commits w/ author + msg | every 10 min |
| **Brain activity** | Last N brain calls | Timestamp, agent name, model, latency ms, tokens in/out, USD cost, success | every 1 min |
| **Source health** | Per-source freshness + attribution | Source name, last fetch, freshness score 0-1, current weight, 30d attribution win/loss, routing tags | every 5 min |
| **Regime history** | Regime classification over time | Time series (90d) of framework regime + thesis regime, classifier confidence, transition markers | every 1h |
| **Integration status** | Tactical-executor connectivity | Last poll, contract version, schema drift state, manual-vs-automated mode indicator | every 1 min |
| **Cost tracker** | LLM spend | Today / 7d / 30d $, by agent, by backend (Gemini/Claude/etc), spike alerts | every 5 min |

### 3.3 `/journal` — Review view (NEW)

**Mental mode:** "what does the data say about my process?"

Weekly + post-trade review surface. Framework explicitly emphasizes journaling as edge.

| Section | Purpose | Key data |
|---|---|---|
| **Closed trades** | Sortable, filterable | Asset, entry/exit, P&L, hold time, grade at entry, regime at entry, score-vs-outcome correlation indicator, source attribution |
| **Missed trades log** | Setups the user didn't take | From `missed_trades` table: setup, score-at-time, reason missed (dropdown), was-valid-real-time (boolean), hindsight risk score, lesson |
| **Process scorecard** | Was process clean even when outcome was bad | Per-trade: entry-planned-in-advance? invalidation-defined? size-predefined? setup-matched-playbook? Aggregated 30d score |
| **Source attribution leaderboard** | Which sources are earning their weight | Source, 30/90d attribution (gross + net), trade count contributed to, current weight, weight delta |
| **Thesis change log** | When thesis flipped or got refined | Diff log between thesis versions, regime transitions with timestamps, what triggered each |

---

## 4. User journeys

### Journey 1 — Morning briefing (target: 2 min)
1. Open `/positioning` on phone (commute) or desktop (home)
2. Glance at regime tape — has it changed? Confidence still high?
3. Scan hero signals — anything new at score ≥ 75?
4. Check active trades — any approaching invalidation? Any approaching target?
5. Close. Move on with day.

### Journey 2 — Setup evaluation (target: 5 min)
1. Hero signal catches eye → tap card → drill into reasoning trail (sheet slides over)
2. Read why-now bullets, scan sub-score bars
3. Drill into contributing sources — do I trust the call?
4. If chart_vision present, view the chart read
5. Decide manual entry → tap "log trade" → fill inline form (entry/size/stop) → submit
6. Trade is logged, score-at-entry frozen for later attribution

### Journey 3 — Outcome logging (target: 1 min on phone)
1. Trade closes (TradingView alert / broker fill notification)
2. Open `/positioning` on phone → tap closed trade → outcome log form
3. Enter exit price → P&L auto-computes
4. Answer "was it the thesis?" (yes / no / partial)
5. Type a one-line lesson
6. Submit → background job updates source weights

### Journey 4 — Weekly review (target: 20 min, Sunday evening)
1. Open `/journal`
2. Closed trades table → sort by score-vs-outcome correlation; identify mis-scored trades
3. Missed trades log → was anything valid in real time that I let slip?
4. Process scorecard → was I disciplined this week?
5. Source attribution leaderboard → any sources to promote / archive?
6. Thesis change log → did my thesis hold up?

### Journey 5 — System health check (ad hoc)
1. Open `/dev`
2. Mgmt panel → what's in flight, what's blocked?
3. Brain activity → any failed calls? Latency spikes?
4. Source health → any source gone stale?
5. Cost tracker → any surprise spend?

---

## 5. Component inventory (atomic UI elements)

These appear repeatedly across views. Designer should produce one canonical visual + interaction for each.

### Data display
- **Regime badge** — pill with regime name + confidence dot. Two variants: thesis (narrative regime) and framework (scoring regime).
- **Score chip** — large 0-100 number with tier color (Tier 1 = gold, Tier 2 = green, Tier 3 = amber, avoid = red) + small Δ arrow vs prior period
- **Sub-score bar** — labeled horizontal bar (e.g., "Macro · 18/20") with fill color matching the score range
- **Setup card** — asset symbol large, score chip top-right, regime badge top-left, key levels in monospaced rows, why-now bullets at bottom. Tappable.
- **Source pill** — source name, weight as a tiny inline number (0.85), freshness dot (green/amber/red/grey)
- **Time-series sparkline** — for regime history, score history, source weight history. Min 30 data points. No axis labels — pure shape.
- **P&L cell** — number + percent in monospaced, color-coded green/red, parentheses for negative
- **Tier indicator** — small colored bar + label ("Tier 1 — high conviction", etc.)

### Interactive
- **Drill-down sheet** — slides over from right; ~70% screen width on desktop, 100% on mobile. Used for reasoning trail, source detail, agent call detail.
- **Inline form** — manual trade entry, outcome log. **NO MODAL** — modal feels CRM. Use a slide-out region inside the active panel. Submit closes it.
- **Sortable table header** — click to sort, default sort indicator visible, supports multi-column secondary sort with shift-click
- **Filter chip row** — above tables. Toggle on/off. Active filters shown as filled chips, inactive as outlined chips.

### Layout
- **Shared shell** — top bar with route switcher + regime tape + cost-today indicator + connection status dot. Already established; refine.
- **Two-column grid** for desktop (main column 70%, sidebar 30%); single-column on mobile
- **Sticky regime tape** — pins to top during scroll on `/positioning`

---

## 6. Mobile

`/positioning` MUST be phone-friendly. Specifically:
- Regime tape (top, sticky)
- Hero signals (full-width cards, swipeable)
- Active trades (compact rows)
- Outcome log form must work one-handed

Other views (`/dev`, `/journal`) are desktop-first. Mobile renders but doesn't get the same care — those are weekly-review surfaces, not daily ones.

---

## 7. Data binding (every component → endpoint)

| Component | Endpoint | Source repo | Polling cadence |
|---|---|---|---|
| Regime tape | `GET /regime/current` | macro-brain | 5 min |
| Hero signals | `GET /signals/top?limit=5` | macro-brain | on demand + 15 min |
| Watchlist scored table | `GET /watchlist/scored` | macro-brain | 15 min |
| Active trades | `GET /trades?status=active` | macro-analyzer (DB) | 5 min |
| Reasoning trail | `GET /score/{setup_id}/explain` | macro-brain | on demand |
| Manual trade log (POST) | `POST /trades` | macro-analyzer | submit |
| Outcome log (POST) | `POST /trades/{id}/close` | macro-analyzer (triggers brain feedback) | submit |
| Mgmt panel | `GET /api/dashboard/mgmt` | macro-analyzer | 10 min |
| Brain activity | `GET /api/dashboard/brain/activity` | macro-analyzer (proxies macro-brain telemetry) | 1 min |
| Source health | `GET /api/dashboard/sources` | macro-analyzer | 5 min |
| Regime history | `GET /regime/history?days=90` | macro-brain | 1 h |
| Cost tracker | `GET /api/dashboard/cost` | macro-analyzer | 5 min |
| Closed trades | `GET /trades?status=closed` | macro-analyzer | on demand |
| Missed trades | `GET /missed-trades` | macro-analyzer | on demand |
| Process scorecard | `GET /journal/process-scorecard?days=30` | macro-analyzer | on demand |
| Source attribution leaderboard | `GET /journal/source-leaderboard?days=30` | macro-analyzer | on demand |
| Thesis change log | `GET /thesis/changelog` | macro-analyzer | on demand |

---

## 8. State and interaction notes

- **Optimistic UI for log submissions** — manual trade and outcome forms should show immediate confirmation and update in background. Trader is on a phone in a hurry.
- **Idempotency keys** on POST endpoints — submitting twice doesn't create two trades.
- **Offline-tolerant outcome logging** — if user is in a tunnel and tries to close a trade, queue locally and retry.
- **Regime change is event-worthy** — small toast/banner when classifier flips regime. Don't be noisy; do be visible.
- **Score Δ is more interesting than score** — emphasize change. A score that went 60 → 78 overnight matters more than a stable 82.

---

## 9. What success looks like

- User opens `/positioning` first thing, every morning, without thinking
- User can answer "what's my conviction here?" in < 5 seconds for any active trade
- User logs every trade outcome (no leakage to "I'll log it later") because the form is one-tap-fast
- Designer can take this brief and produce mockups without further requirements gathering
- New developer can implement any component by reading this doc + the bound endpoint

---

## 10. What this is NOT

- Not an auto-trading interface. Tactical executor automation is Phase 9 of the project plan.
- Not a multi-user product. One operator.
- Not a portfolio analytics tool. P&L and exposure live elsewhere (broker, Sheets, etc).
- Not a research workspace. Research happens in newsletters and notes; the dashboard surfaces what the system has *concluded*, not what to read next.
- Not a replacement for the trader's judgment. Surfaces signals; trader decides.

---

## 11. Execution model — IMPORTANT

The system is **manual-execution-first** for the foreseeable future. Tactical-executor wiring is Phase 9 (last) of the build. This affects design:
- Manual trade log + outcome log are first-class — they're how data enters the system
- The dashboard does not place orders, hold credentials, or know broker state
- A "send to executor" button does not exist yet (and may never need to, if manual flow is good enough)

Design accordingly: the dashboard is a **decision-support surface**, not a control surface.

---

## 12. Open design questions

1. **How aggressive should the regime-change toast be?** Every classification update? Only when confidence > 0.8? Only when the regime label itself changes? Recommend: only on label change, with optional sound on mobile.
2. **Where does chart upload happen?** From `/positioning` setup card (drag onto card → routes to `chart_vision` for that setup) or as a top-level upload zone? Recommend: in-card.
3. **How to surface "the framework was wrong" moments?** When score said 85 but trade lost → this is high-signal feedback. Should it ping immediately or wait for weekly review? Recommend: gentle inline marker on closed trade, deeper analysis in weekly review.
4. **Color-blind safe palette?** Tier 1 gold vs Tier 2 green vs Tier 3 amber needs to be distinguishable for deuteranopia. Add shape/icon redundancy.
5. **Live-update strategy** — polling intervals listed in §7 are starting points. Should we prefer SSE or WebSocket for regime tape and active trades? Recommend: start with polling (simpler), upgrade to SSE only if poll cadence becomes a UX bottleneck.

---

## 13. Deliverables expected from designer

1. High-fidelity mockups for `/positioning` (desktop + mobile)
2. High-fidelity mockups for `/dev` (desktop only)
3. High-fidelity mockups for `/journal` (desktop only)
4. Component spec sheet for the atoms in §5 (regime badge, score chip, sub-score bar, setup card, source pill, sparkline, P&L cell, tier indicator, drill-down sheet)
5. Updated color tokens / typography spec / spacing scale (refining the existing institutional-terminal baseline)
6. Interaction notes for state transitions (regime change, score update, trade close, etc.)

Implementation will follow the mockups in Phase 5 of the project plan. Implementation team is the Application Agent (Claude Code).
