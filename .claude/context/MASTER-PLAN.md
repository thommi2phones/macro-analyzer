# Master Plan — Macro Analyzer to Usable State

> **Created:** 2026-06-17 · **Owner:** Thomas · **Branch:** `claude/streams-live`
> **Companion docs:** `STATE.md` (live session state) · `DECISIONS.md` (architecture decisions) · `OPEN-QUESTIONS.md` (blockers)
> This is the single roadmap to a usable product. STATE.md is the per-session handoff; this file is the destination.

---

## 1. Definition of "usable"

The operator can sit down and, in one place:

1. **See every source tiered by conviction** (T0→T4), regardless of input type. ✅ *shipped this session*
2. **See what each source is actually calling** — themes, assets, trades — with **trustworthy per-source accuracy**.
3. **Get a conviction score per source/call** that folds in real accuracy (setup-win + alpha), not just trust weight.
4. **See emerging themes** rolled up across all sources (sectors / macro narratives / tickers).
5. **Get timing signals** — the core goal: *"when to buy."*
6. **Run the execution funnel** end to end: Positioning → Concepts → Identify → Live → Journal, on real data.
7. **Trust durability** — the listener survives reboots, work is committed, the app is deployable.

We are roughly **55–60% there**. Ingestion, extraction, accuracy backtesting, and the source-intelligence UI exist. The gaps are: wiring accuracy → conviction, themes/timing, and the execution funnel's stubbed data.

---

## 2. Current-state snapshot (2026-06-17)

**Health:** ~565 tests passing, 1 pre-existing failure (`test_watchlist_resolver::…mention_summary`). Branch `claude/streams-live` with **~82 uncommitted files** (large in-flight effort: insiders, signals, substack, theme-map rewrite + this session's tier/Sources work).

| Layer | State |
|---|---|
| Telegram ingest (5 channels, dedup, albums) | ✅ Real |
| Vision extraction (caption-aware, LOCKED prompt) | ✅ Real — 91–100% core fields |
| Full corpus extracted (~6,263 charts) | ✅ Done |
| Accuracy backtester (`call_accuracy.py`) | ✅ Real — `setup_win_rate` + alpha; 1,494 calls scored |
| Conviction-tier registry (T0–T4 + infra/self) | ✅ Shipped — committed `f6ee3a9` |
| Unified **Sources** view (tier + group clustering, rich drill-down) | ✅ Shipped this session (uncommitted) |
| Per-source **accuracy badge** on TrustedAuthorCard | ⚠️ Built but **HIDDEN** — pending trustworthy numbers |
| Conviction = accuracy-weighted | ⛔ Not wired (still trust-weight only) |
| Theme map / asset map (live from signals) | 🟡 In-flight (streams-live WIP), 2 tests failing |
| Timing ("when to buy") | ⛔ Not started — the goal |
| Execution funnel: kpis / heroSignals / watchlist | ⛔ STUB (zero-state) in `desk_data.py` |
| Execution funnel: activeTrades / closedTrades / journal | ✅ Real (empty until first trade) |
| Durability (launchd listener) + deploy | ⛔ Not started |

---

## 3. Milestones

Timelines are in **work-sessions** (one focused sitting) plus rough calendar, assuming ~3–4 sessions/week. Dates are targets, not commitments.

### M1 — Trust the numbers  ·  *2–3 sessions · target by 2026-06-24*
Make per-source accuracy trustworthy and visible, then fold it into conviction.
- [ ] Refine `learning/call_accuracy.py`: winsorize `r_multiple` (`_MAX_SANE_R=8`), min-sample gate (`_MIN_SAMPLE=10`, `meaningful` flag), ticker validation (drop junk), market-relative **alpha** (call ret − BTC, beta-stripped). *(largely done per STATE — verify + lock)*
- [ ] Re-run `backtest_calls()` → `source_accuracy(window_days=N)`; sanity-check the alpha flip (Market Traders +5.0% / Big_Nuts +3.8%).
- [ ] **Fold accuracy into conviction** in `learning/source_themes.py` — conviction = f(confluence, pattern, TF, persistence, freshness, **setup_win, alpha**).
- [ ] **Re-enable the accuracy badge** on `TrustedAuthorCard` (now live in the Sources drill-down) — it's currently hidden.
- [ ] Surface accuracy on the Sources cards (tier grid) so ranking reflects real performance, not just trust weight.
- **Done when:** clicking a T0 source shows its real setup-win-rate + alpha, and conviction scores move with accuracy.

### M2 — Themes & positioning live  ·  *2–3 sessions · target by 2026-07-01*
Roll calls up into themes the operator can act on.
- [ ] Finish the streams-live theme-map/asset-map wiring (real `signals` → `themeMap[]`/`assetMap[]`); fix the 2 failing `test_streams_builders` tests (`direction`/`concepts` filter).
- [ ] Conviction-weight the theme rollup (a T0 source's call counts more than a T3's).
- [ ] Emerging-concepts panel driven by real novelty/velocity.
- [ ] Decide: does the **Sources** view subsume `streams`/`influence`, or do they stay as theme-centric views? (IA decision — see §5.)
- **Done when:** the operator sees "what's emerging, by conviction" across all sources without reading individual charts.

### M3 — Timing: "when to buy"  ·  *3–5 sessions · target by 2026-07-15*  ·  **the goal**
- [ ] Define the timing signal: per-ticker, combine (a) conviction-weighted call density, (b) setup freshness/decay, (c) confluence across sources, (d) macro/regime alignment.
- [ ] Backtest the timing signal against the scored-call outcomes (does "buy when signal fires" beat buy-and-hold / BTC?).
- [ ] Surface timing on the ticker drill-down and as a feed ("act now" candidates).
- **Done when:** the system emits ranked, time-stamped "buy candidates" with a measured edge over baseline.

### M4 — Execution funnel usable  ·  *3–4 sessions · target by 2026-07-29*
Wire the stubbed dashboard sections to real data so the funnel is operable.
- [ ] `kpis` — real cash posture / exposure from trades + regime.
- [ ] `heroSignals[]` / `watchlist[]` — real scored setups (currently STUB in `desk_data.py`).
- [ ] `reasoning{}` — per-setup explain blob keyed by signalId.
- [ ] `processScorecard` — real metrics (journal feedback loop already provides the data).
- [ ] Verify Positioning → Concepts → Identify → Live → Journal round-trips on real data.
- **Done when:** an idea flows from a source call → watchlist → plan → trade → review without hitting a stub.

### M5 — Durability & ship  ·  *2–3 sessions · target by 2026-08-05*
- [ ] **launchd plist** for the Telegram listener (survives reboot; replace `nohup`/`/tmp/tg-listener.pid`).
- [ ] **Commit & merge** `claude/streams-live` to `main` (currently 82 uncommitted files); land the tier/Sources/group work cleanly.
- [ ] Branch/worktree cleanup — prune merged `claude/*` branches and stale worktrees.
- [ ] Deployment decision (Render per D-2026-05-08-003) + tactical-gate endpoint live test with `Trading-Agent-V1-CODEX`.
- [ ] Backfill `agent_call_log.source_credits` column (echo_ties wants it).
- **Done when:** the app runs unattended, work is on `main`, and it's deployable.

---

## 4. Cross-cutting / always-on
- [ ] Populate Telegram `known_senders` user-IDs (settings.py) so group posts attribute to individual authors — run `scripts/telegram_smoke_test.py`.
- [ ] Keep `config/sources.json` tiers current as new sources are added (CSV → ingest flow).
- [ ] Refresh stale market data (`prices fetch --watchlist` + `score run`) — data has drifted weeks old before.
- [ ] Keep `STATE.md` checkpointed at the end of each session; append `DECISIONS.md` on non-trivial calls.

## 5. Open decisions (resolve before/while building)
- **IA:** Does **Sources** (tier-grouped roster) fully replace `streams` + `influence`, or do those stay as theme/capital-flow views? *Leaning: Sources = roster, Streams = themes, retire Influence once Sources covers it.* (M2)
- **Conviction formula weights** — confirm the accuracy weighting (how much do setup_win vs alpha count vs the existing confluence/pattern terms?). (M1)
- **Timing signal definition** — the central modeling choice. (M3)
- **Deployment target** — Render still the call? Needed for the tactical-gate live test. (M5, from OPEN-QUESTIONS)
- **Group coverage** — break out member authors under more groups (e.g. Gem Hunters has none)? (cosmetic, anytime)

## 6. Risks
- **Uncommitted WIP (82 files)** on `streams-live` is the biggest risk — a lost worktree loses weeks. *Mitigation: M5 commit, but consider an interim checkpoint commit sooner.*
- **Anthropic credits near-$0** — blocks re-extraction only; accuracy/conviction/themes work uses yfinance + DB, so not blocking the critical path.
- **Listener durability** — currently a `nohup` pid in `/tmp`; a reboot silently stops forward capture. M5, but low-effort to pull earlier.

---

## 7. Sequencing summary

```
NOW ──► M1 Trust numbers ──► M2 Themes ──► M3 Timing (GOAL) ──► M4 Funnel ──► M5 Ship
        (accuracy→conviction)  (rollups)    (when to buy)        (un-stub)     (durable+deploy)
        ~by 06-24              ~by 07-01     ~by 07-15            ~by 07-29     ~by 08-05
```

Critical path to "I can act on this": **M1 → M2 → M3.** M4 (funnel polish) and M5 (ship) can partially overlap once the intelligence layer is trustworthy.
