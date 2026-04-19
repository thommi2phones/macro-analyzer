# Macro Positioning Analyzer — Improvement Pass (2026-04-05)

## 1. Overall Project Assessment

**Verdict: directionally correct scaffold, output quality was the blocker.**

Strengths of what was already here:

- Clean separation of concerns: ingestion → normalization → extraction →
  validation → memo. You can swap out any stage (e.g. heuristic → LLM
  extractor) without touching the rest.
- Pydantic models (`Thesis`, `ValidatedThesis`, `PositioningMemo`,
  `MarketObservation`) are well-shaped and already capture the concepts a
  human macro PM would recognise (horizon, catalysts, risks, implied
  positioning, evidence with citations).
- FRED provider is real and comprehensive (60+ series, categorised).
  Gmail connector is real code with decent newsletter-source detection.
- Persistence is simple but working (SQLite).

Weaknesses (what this pass addressed):

1. **Heuristic extractor was noisy.** It fired on any sentence with one
   keyword, produced duplicate "themes" like `macro, inflation`, had
   no negation handling, and its `theme` was just a comma-joined list of
   assets which made consensus grouping useless.
2. **Validation was superficial.** `support_score` was essentially
   `thesis.confidence * 0.6 + small bonus per observation`. It did not
   compare expert direction to market direction at all — so the
   "Expert vs Market" section was cosmetic.
3. **Consensus was vote-counting, not trust-weighted.** One source = one
   vote, ignoring `trust_weight` in the source registry.
4. **FRED live provider had a fragile error path** — any network/init
   failure killed the pipeline instead of falling back to static data.
5. **No CLI, no RSS connector**, no ergonomic way to run the pipeline on
   a real source without writing Python.

## 2. Changes Made

### Extractor (`llm/extractor.py`)

- Expanded asset lexicon (credit, crypto, EM, metals) and introduced a
  separate `THEME_KEYWORDS` table so themes are macro narratives
  (`inflation`, `growth`, `labor`, `policy`, `liquidity`, `fiscal`,
  `geopolitics`) instead of concatenated asset lists.
- Added negation handling: `"not supportive"` / `"no longer improving"`
  no longer count as bullish.
- Added hedging markers (`might`, `could`, `perhaps`) that *lower*
  confidence, and conviction markers (`base case`, `we think`,
  `high conviction`) that raise it.
- Horizon extraction is now regex-based and recognises "tactical",
  "structural", "this quarter", "cycle", etc.
- Catalysts are now extracted as the clause *after* the catalyst
  marker, not the whole sentence.
- Added a `min_confidence` floor so low-signal sentences don't pollute
  output.

### Validation (`market/validation.py`)

- **Actual polarity comparison.** Each market observation is scanned
  for positive/negative markers ("supportive / improving / rising" vs
  "weakening / deteriorating / rolling over") and compared against the
  expert direction. Alignment is now
  `supportive | mixed | contradictory | unknown` based on
  `(agree − disagree) / directional` ratio.
- **Real thesis↔observation matching** with alias expansion:
  an `inflation` thesis now correctly picks up `rates` /
  `financial_conditions` observations; a `growth` thesis picks up
  `labor` / `consumer` / `housing`.
- `support_score` now *blends* prior confidence with live agreement
  signal, and decays on `mixed` / `watchful` positioning.
- `build_recommendations` drops `contradictory`-aligned theses entirely
  (the market is actively against you — don't promote it) and ranks
  surviving picks by confidence.

### Memo (`reports/memo.py`)

- Consensus views are **trust-weighted**. Two low-trust sources can be
  outweighed by one core source, and a 50/50 split no longer shows up
  as "consensus".
- Divergence is only reported when there are *strong* directional
  views on both sides (watchful + directional is normal, not a
  disagreement).
- TL;DR surfaces the leading consensus, flags "N thesis(es) where
  market disagrees", and shows the top actionable expression.
- "Expert vs Market" rows now include explicit `← MARKET DISAGREES`
  and `← no market signal yet` tags.

### Reliability

- Hardened `FREDMarketDataProvider.gather`: HTTP client init failures
  are now caught, so you fall through gracefully.
- `PositioningPipeline.run` now **falls back to static context
  observations** when the live provider returns zero. Previously if
  FRED was configured but the call failed, any sample/manual
  observations the caller passed in were silently discarded.

### Surface area

- **New CLI** (`macro_positioning.cli`) with three subcommands:
  - `sample` — run bundled sample data
  - `rss --feed src=url` — ingest RSS/Atom feeds
  - `text --source-id ... --title ... --file path` — ingest one doc
  Also wired as the `macro-positioning` console script in
  `pyproject.toml`.
- **New RSS/Atom connector** (`ingestion/rss_connector.py`) built on
  stdlib `xml.etree` + existing `httpx`/`bs4` — no new deps. Handles
  content-encoded HTML, strips scripts/styles, parses RFC-2822 and ISO
  dates.

### Tests

Suite grew from 24 → 65 passing tests:

- `tests/test_extractor.py` — 18 tests (sentence splitting, direction,
  negation, assets, theme, horizon, end-to-end extraction)
- `tests/test_validation.py` — 13 tests (polarity, alias matching,
  alignment classification, recommendation gating)
- `tests/test_memo.py` — 6 tests (trust weighting, divergence,
  market-disagreement surfacing)
- `tests/test_rss_connector.py` — 4 tests (RSS 2.0, Atom,
  empty/malformed input)

## 3. Sample Output Before / After

Before this pass, the sample run produced 6 theses with themes like
`"macro"`, `"growth, inflation"`, `"commodities, gold"`. Support scores
hovered around 0.27–0.61 regardless of whether the market actually
agreed. All five "Expert vs Market" rows said *unknown* or *mixed*.

After this pass (see `data/processed/sample_memo_after_improvements.md`
in your workspace): 5 theses with distinct themes
(`inflation, rates, commodities, equities, labor`). The bearish
inflation call is correctly flagged as *contradictory* to the market
signal, while the three bullish calls are *supportive*. The top three
recommendations are ranked and include horizons + explicit risk
callouts.

## 4. Known Limitations & Next Steps

**Polarity semantics are still globally symmetric.** A bearish-inflation
view and a bearish-equities view both have `polarity=-1`, but a market
observation like "real yields falling" is positive for duration and
*also* supportive of a disinflation thesis — they aren't the same
direction. The current matcher will sometimes flag these as
contradictory when they're actually aligned. A proper fix is to have
each observation carry a small `implies: {asset|theme -> polarity}`
map, so the validator looks up the correct polarity *per thesis*
rather than using a single scalar.

**Still ready to add:**

1. **LLM extractor** — `llm/extractor.py` has a `ThesisExtractor` ABC;
   plug Claude/OpenAI in, point at `llm/prompts.py`, keep the rest of
   the pipeline unchanged. Expect big gains on catalyst and risk
   extraction, where heuristics are weakest.
2. **Freshness decay** — `freshness_score` is hard-coded to 0.8. It
   should decay with `now - published_at` so older theses are
   down-weighted in consensus.
3. **Thesis lifecycle** — today every run emits fresh theses with new
   IDs. A dedupe-by-semantic-similarity layer would let you mark
   `weakening / invalidated` when subsequent content contradicts an
   earlier view from the same source.
4. **Source registry loading in the API** — `/sources/example` reads
   from a fixed path. Make this parametric, and expose `/sources`
   endpoints for adding/updating sources + trust weights at runtime.
5. **Output surfaces** — today only markdown is rendered. Add a JSON
   export (for downstream tooling) and a simple Jinja HTML memo for
   email / Slack delivery.
6. **Dashboard** — a tiny single-page dashboard (FastAPI + HTMX or a
   React artifact) showing the current thesis tracker, what's new this
   week, and what flipped alignment. This is what converts "memo tool"
   into "daily workflow".

## 5. How to Run Locally

```bash
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Run bundled sample end-to-end
python -m macro_positioning.cli sample

# Ingest an actual RSS feed and run the pipeline on it
python -m macro_positioning.cli rss \
    --feed thefed=https://www.federalreserve.gov/feeds/press_all.xml

# Ingest a single note / transcript
python -m macro_positioning.cli text \
    --source-id my_notes --title "Weekly view" --file view.txt
```
