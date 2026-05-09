# Decisions Log

Append-only. Never delete entries. Most recent first.

---

## 2026-05-09 — LLM stack: Gemini for vision, separate deep_research slot for narrative; no own-LLM yet

**Decision:** Use Gemini 2.5 Pro (already wired, unlimited on the account)
for all chart vision and current-state synthesis tasks. Reserve a SEPARATE
future `deep_research` agent slot for narrative synthesis on the live web —
intended provider Perplexity Deep Research or OpenAI deep-research, called
under strict budget guards (per-call cost cap, per-day cap, only on
high-conviction setups). Do NOT conflate vision (Gemini, cheap, recurring)
with deep research (Perplexity, expensive, rare). Building our own LLM is
deferred until `training_corpus/` has years of outcome-labeled examples —
the logging contract is the runway for that.
**Rationale:** Right tool per job. Gemini multimodal is genuinely strong
for chart structure (S/R, trendlines, indicator state) and free on the
current account. Perplexity/OpenAI deep-research is unmatched for live
discourse aggregation ("what's the macro consensus on yields this week")
because it actually traverses sources — but expensive enough that gating
matters. Conflating them in one code path leads to either over-spending or
under-using vision. Own-LLM economics only work once we have labeled
training data, which we don't.
**Alternatives:** Single LLM path for everything (rejected — wrong-tool
problem); jump to fine-tuned own-LLM now (rejected — premature, no corpus);
skip Perplexity entirely (rejected — narrative synthesis on the live web
genuinely matters and prompt-engineered Gemini won't match a research
agent that traverses sources).

---

## 2026-05-09 — Time-weighting uses macro-appropriate horizons (NOT day/week-tight)

**Decision:** Mention extraction half-life defaults to 30d standalone; in the
watchlist resolver, half-life equals the extraction window length (7d window
→ 7d half-life, 90d → 90d). Technical scorer uses 5d/20d/60d momentum
horizons (≈ weekly/monthly/cycle). NO bias toward 1d / 7d windows in the
scoring layer.
**Rationale:** A macro thesis lives over weeks-to-months. Tighter half-lives
bias the system toward news-cycle noise. Stale-but-relevant content stays
weighted (a mention from 30d ago in a 90d window still counts at 0.79).
**Alternatives:** Tighter 14d-or-less half-lives (rejected — too tactical
for a macro analyzer).

---

## 2026-05-09 — yfinance is the default price provider; provider abstraction for later

**Decision:** Default `PriceProvider` is `YFinanceProvider`. No API key, free,
covers equities + ETFs + indices + crypto via symbol mapping. Provider
interface lets us swap to FMP / Finnhub / Polygon later without touching
scoring/runner.
**Rationale:** Ships today with zero infra. yfinance is fragile (Yahoo
scrape) but acceptable for daily bars while we're learning the loop. Phase 7
prod can pay for FMP if reliability matters.
**Alternatives:** FMP first (250/day free; needs key); CoinGecko for crypto
(rejected as primary — adds source).

---

## 2026-05-09 — SQLite WAL mode + caller-supplied connection pattern

**Decision:** `initialize_database()` enables WAL mode + busy_timeout=5000.
Read helpers in `prices/fetcher.py` accept optional `conn` param; use inside
transactions to avoid the inner-call's `initialize_database` deadlocking the
outer's BEGIN.
**Rationale:** Default rollback-journal locks the whole DB on writes. With
the FastAPI server holding read connections, CLI score-pass writes block
indefinitely. WAL eliminates the contention; the conn-passing pattern
eliminates DDL-inside-transaction deadlock.
**Alternatives:** PostgreSQL (overkill for single-operator); separate DB per
concern (operationally heavy).

---

## 2026-05-09 — Watchlist as a living object: anchors + theme + mentions

**Decision:** Active watchlist composed at runtime from three streams:
(1) anchors from `config/watchlist.json` always, (2) regime-aligned theme
tickers from `config/asset_themes.json` when current regime matches a
theme's `preferred_regimes`, (3) top mention-extracted tickers per window
above min count. Each entry carries `origins: [str]`.
**Rationale:** Static watchlists go stale fast. Macro themes shift; the
operator wants the system to surface what's actually being talked about
without manual curation. Origins make the source visible ("anchor",
"theme:uranium", "mentions:30d:w8.4").
**Alternatives:** Manual-only (rejected — defeats discovery); LLM-only
(rejected — token cost + nondeterminism for what regex + count handles).

---

## 2026-05-09 — Brain built inside macro-analyzer, not a separate repo

**Decision:** Keep `brain/` as a sub-package of `macro-analyzer` (`src/macro_positioning/brain/`) rather than extracting to a separate `macro-brain` repo.
**Rationale:** The original architecture doc planned a separate `macro-brain` repo, but building it in-repo was the pragmatic path: shared SQLite, shared models, single deployment, no HTTP contract overhead for what is currently a single-operator tool. Can extract later if GPU hosting or independent scaling is needed.
**Alternatives:** Separate `macro-brain` repo with `POST /brain/ingest` contract (as originally planned). Still valid if the system grows to need independent deployment.

---

## 2026-05-09 — Intelligence layer: pure functions on list[MarketObservation]

**Decision:** All three classifiers (quadrant, FCI, EPU) are implemented as pure `list[MarketObservation] → Pydantic model` functions with no side effects or network calls.
**Rationale:** Makes them trivially testable (23 tests with a factory helper `_obs(metric, value)`), composable (single FRED fetch powers all three), and safe to call in `_build_macro_indicators()` wrapped in try/except without state concerns.
**Alternatives:** Class-based providers that fetch their own data (rejected — redundant FRED calls, harder to test).

---

## 2026-05-09 — Institutional-terminal aesthetic: consumer chrome permanently banned

**Decision:** Strip and permanently ban: `backdrop-filter: blur()`, `radial-gradient` on body/panels, glow `box-shadow`, `@keyframes` animation, `linear-gradient` on nav/UI chrome, marketing hero copy.
**Rationale:** "This is not a consumer product. This should be straight tactical, to the point, very clear to read." Color is reserved for signal (green=bullish/easing, red=bearish/tightening, gold=high conviction/transitional). Every surface is flat `var(--surface)` + `1px solid var(--border)`.
**Alternatives:** None — this is a locked product direction from the user.

---

## 2026-05-09 — SPA dashboard (React/JSX) replaces server-rendered HTML

**Decision:** Old Python HTML-generation pipeline (`output_ui.py`, `tactical_ui.py`, etc.) is superseded by a React SPA at `web/positioning.jsx`. Old routes 307-redirect to the SPA. Old files retained for reference but not rendered.
**Rationale:** Enables component reuse, live data binding without full page reload, cleaner separation of data (FastAPI JSON endpoints) from presentation (JSX components).
**Alternatives:** HTMX on top of existing Python templates (simpler but harder to build the MacroIndicatorStrip and asset-class grouping interactions).

---

## 2026-05-09 — EPU composite: simple average, no additional normalization

**Decision:** EPU composite score = simple average of available EPU series values (no scale factors applied).
**Rationale:** EPU indices are already normalized to ~100 historical average by their designers. Unlike FCI sub-indicators (VIX, TED spread — measured in different units), EPU series are directly comparable. Simple average is defensible and transparent.
**Alternatives:** Weighted average (rejected — no evidence one EPU series is more predictive); z-score normalization (redundant given EPU's built-in normalization).

---

## 2026-05-09 — `format_prompt_blocks()` returns ("—","—","—") on empty input

**Decision:** `format_prompt_blocks([])` returns the sentinel tuple `("—", "—", "—")` rather than raising or returning empty strings.
**Rationale:** Prevents `KeyError` on `MACRO_ANALYSIS_PROMPT.format(...)` in the heuristic fallback path where `observations` may be an empty list. The LLM sees literal "—" and correctly treats it as "no data available", which is better than a missing key error or blank sections that confuse the model.
**Alternatives:** Guard clause in `synthesis.py` (rejected — more code for same effect); empty strings (rejected — blank section headers with no content confuse the model).
