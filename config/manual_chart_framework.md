# Chart Analysis Framework
## Reference guide for Claude agent — chart image analysis and signal evaluation

---

## PRIORITY HIERARCHY
Evaluate every chart screenshot in this exact order:

| Priority | Element | Role |
|----------|---------|------|
| 1 | Blue solid pattern structures | Directional hypothesis |
| 2 | Fibonacci levels (color-coded) | Confluence validation |
| 3 | Blue dashed historical price levels | Structural zones |
| 4 | Custom MACD histogram + TTM squeeze | Primary momentum confirmation |
| 5 | RSI structure and divergence | Secondary momentum confirmation |
| 6 | Thanos EMA cluster | Trend strength / volatility |
| 7 | SRChannel alignment | Structural gut check |

---

## SECTION 1: PATTERN FIRST ANALYSIS ← MOST IMPORTANT

Patterns are drawn with **solid blue lines**.

### Pattern types
- Flags
- Pennants
- Rising channels
- Falling channels
- Wedges (rising / falling)
- Trend lines
- Head and Shoulders
- Inverse Head and Shoulders
- Cup and Handle

### Validity requirements
A pattern is only valid when it has:
- Clear geometric structure
- Multiple reaction points
- Respect of boundaries

### Pattern → Bias mapping
| Pattern | Bias |
|---------|------|
| Flag in uptrend | Bullish continuation |
| Rising wedge with weakening momentum | Bearish |
| Head and Shoulders | Bearish |
| Inverse Head and Shoulders | Bullish |
| Falling wedge | Bullish reversal |
| Channel breakout above | Bullish momentum shift |
| Channel breakdown below | Bearish momentum shift |
| Cup and Handle | Bullish continuation |
| Descending channel | Bearish / short bias |
| Symmetrical triangle | Breakout direction-dependent |

**Pattern determines directional hypothesis. Everything else confirms or denies it.**

---

## SECTION 2: FIBONACCI CONFLUENCE ← SECOND MOST IMPORTANT

Fibonacci is anchored **swing to swing** (high to low for retracement, low to high for extension).

### Color significance
| Color | Significance |
|-------|-------------|
| **White** | Normal level |
| **Yellow** | Important level |
| **Green** | Critical level — highest probability reaction zone |

### Retracement levels
- 0.382
- 0.5
- 0.618 ← most important (golden ratio)
- 0.65–0.70
- 0.786

### Extension levels (targets)
- 1.272
- 1.414
- 1.618
- 2.0

### How to use
- Validate pullback zones **inside** the pattern
- Identify neckline or breakout confluence
- Project measured moves to extension levels
- Identify exhaustion areas

### Interpretation rules
- **Green Fib inside pattern boundary** = highest probability reaction zone
- **Yellow Fib aligning with pattern support** = strong entry zone
- **Failure at Green Fib level** = structural shift — invalidation signal
- **Fib alone does not create a trade** — must confluence with pattern

---

## SECTION 3: HISTORICAL PRICE LEVELS (BLUE DASHED LINES)

These represent:
- Major historical resistance
- Major historical support
- Prior breakout zones
- Multi-touch reaction levels

### Confluence model
```
Pattern boundary + Fib level + Blue dashed level = Strong structural zone
```

### Interpretation
- **Break and hold above level** → continuation
- **Rejection with wick** → level respected
- **Repeated reactions** → increases probability of large move

---

## SECTION 4: MACD HISTOGRAM + TTM SQUEEZE — PRIMARY MOMENTUM

### Bullish confirmation
- Increasing positive histogram bars
- Squeeze release **upward**
- Expansion after consolidation

### Bearish confirmation
- Increasing negative histogram bars
- Squeeze release **downward**

### Divergence (caution signal)
- Weakening histogram while price makes new highs → momentum fading
- Bearish divergence at resistance → potential reversal

**MACD must align with pattern break for the strongest setup.**

---

## SECTION 5: RSI STRUCTURE — SECONDARY CONFIRMATION

RSI is used **structurally**, not as overbought/oversold.

### What to look for
- Divergence (price ≠ RSI direction)
- RSI trend line breaks
- RSI channel breaks
- RSI head and shoulders formation
- RSI holding above or below 50

### Bullish signals
- RSI holding above 50
- Bullish divergence at pattern support

### Bearish signals
- RSI holding below 50
- Bearish divergence at resistance

**RSI confirms momentum regime shift.**

---

## SECTION 6: THANOS EMA CLUSTER

Used for:
- Consolidation detection (tight compression)
- Breakout validation (price breaking through cluster)
- Confluence with Fibonacci

### Interpretation
- **Tight EMA compression** → volatility expansion imminent
- **Strong EMA stacking** (all EMAs aligned, spread out in trend direction) → trend strength

**Not a primary signal — used as confluence.**

---

## SECTION 7: SRCHANNEL

Used as:
- Structural gut check
- Level validation
- Confluence validator

If SRChannel aligns with:
- Pattern boundary
- Fib level
- Historical dashed level

→ That zone increases in importance.

---

## SECTION 8: CONFLUENCE MODEL

A strong trade setup typically has:

```
✅ Clear pattern structure
✅ Yellow or Green Fib at pattern boundary
✅ Blue dashed historical level nearby
✅ MACD histogram expansion or squeeze release
✅ RSI structural alignment
```

**Not all 5 required.** More alignment = higher probability.

| Alignment count | Probability |
|----------------|-------------|
| 5/5 | Extremely high |
| 4/5 | High |
| 3/5 | Medium |
| 2/5 | Low — wait for more |
| 1/5 | Skip |

---

## SECTION 9: INVALIDATION MODEL

### Bullish trade — invalid if:
- Pattern breaks down (price closes below pattern structure)
- Clean break below Green 0.786 Fib
- Strong negative MACD expansion
- RSI structural breakdown (breaks trendline, falls below 50)

### Bearish trade — invalid if:
- Pattern breaks out above resistance
- Strong positive MACD expansion
- RSI structural breakout above key level

---

## SECTION 0: THE TRADER'S PAIRED MESSAGE — READ FIRST

Most charts are posted WITH a text message (provided in the prompt as
"TRADER'S MESSAGE POSTED WITH THIS CHART"). That message is the trader's own
words about THIS chart and is the single most important input — it usually
states the actual call and **overrides** what the chart geometry alone
implies. Examples from real posts:

- *"LEU incredible move from $9 break to $333"* → the move ALREADY happened →
  `retrospective`, NOT a fresh long to 333.
- *"SUI still needs a wedge break, can long on a break over"* → CONDITIONAL —
  not yet triggered; setup `status: "pending"`.
- *"BTC vs Money... what matters is BTC vs MONEY"* → musing/education →
  `no_trade`.
- *"ZEC extreme caution... we warned about this"* → commentary/warning →
  `no_trade` or the stated direction, not an invented one.
- *"should have stops there if long"* → risk note on an existing position.

Rule: when the message and the chart disagree, the MESSAGE wins for
`call_type`, `is_forward_looking`, and direction. Use the chart for the
precise levels (entry/stop/targets). If there is no message, fall back to
chart-only reading.

### These channels' slang — learn it, it changes call_type

| Slang | Means |
|---|---|
| "nut box" / "nutted" | the target/resistance zone; "nutted at top" = tagged the top |
| "**faded**" / "fade" | reversed and dropped AFTER a move → the move HAPPENED |
| "dropping it" / "rekt" / "dumped" | already fell → past event |
| "hit X and faded", "nutted at top and faded" | **RETROSPECTIVE** — the move played out, now reversing. NOT a fresh long. |
| "needs to break / re-break / continuation", "would need a break", "needs to clear $X" | **CONDITIONAL** — setup not triggered yet → directional but `status: "pending"` |
| "W3 / W4 / W5", "wave 3" | Elliott wave count |
| "DCA", "bag", "send it" | accumulate / position / bullish push |

Key rule: a caption describing a move in the PAST TENSE that already
resolved ("hit the nut box and faded", "nutted at top", "dropped it") is
`retrospective` with `is_forward_looking=false` — even if the chart still
shows upside targets drawn. The drawn targets were the OLD thesis; the
message says it's over.

---

## SECTION 10: OUTPUT FORMAT — STRICT JSON

Respond with **valid JSON ONLY** (no prose, no Markdown fences) matching this
schema exactly. Getting `call_type`, `direction`, and `is_forward_looking`
right matters MORE than the technical detail — downstream scoring depends on
correctly understanding WHAT KIND of call this is.

```json
{
  "asset_class": "crypto | equity | commodity | index | fx | unknown",
  "ticker": "string — the symbol exactly as shown (BTC, BTC/USDT, AAPL, XAUUSD)",
  "timeframe": "the chart's timeframe (15m, 1h, 4h, 1D, 1W) or null",
  "call_type": "directional_long | directional_short | bidirectional | retrospective | no_trade | not_a_chart",
  "is_forward_looking": true,
  "trade_stage": "watching | active | completed",
  "bias": "bullish | bearish | neutral",
  "pattern": "dominant pattern name, or null",
  "confluence_score": 3,
  "setups": [
    {
      "direction": "long | short",
      "entry": 0.2154,
      "stop_loss": 0.1285,
      "invalidation": "plain-language condition that kills the thesis",
      "take_profits": [0.2175, 0.2283],
      "final_target": 0.2283,
      "status": "pending | triggered | completed"
    }
  ],
  "indicators_visible": ["MACD", "RSI", "..."],
  "notes": "one-line context"
}
```

### call_type — decide FIRST, it gates everything

| call_type | When | setups |
|---|---|---|
| `directional_long` | One actionable bullish thesis (entry/target above, invalidation below) | 1 long setup |
| `directional_short` | One actionable bearish thesis | 1 short setup |
| `bidirectional` | BOTH a long AND a short scenario are drawn — price sits at a decision zone (e.g. golden pocket) and the chart maps both ways. NOT a single bias — do NOT collapse to bullish/bearish. | 2 setups: one long, one short |
| `retrospective` | The marked move has ALREADY happened — price has run past the projected zone, OR the message brags it "played out" / "we were right" / past-tense. `is_forward_looking=false`. | setups with `status: "completed"` |
| `no_trade` | This IS a price chart, but with no actionable setup right now (just levels, a cautionary "watching", general commentary on a chart) | `[]` |
| `not_a_chart` | The IMAGE itself is NOT a price chart — a screenshot of text/a message, a meme, a results brag. **Judge by the IMAGE, not the caption:** a real price chart whose caption is just a link/emoji (e.g. a t.me link + 👇) is still a chart — classify it from the chart, NOT not_a_chart. | `[]` |

### Decision rules
- **not_a_chart check FIRST — judge the IMAGE, not the caption:** if the
  IMAGE is a screenshot of text, a meme, a "results"/"strategy" brag, or a
  wall of written "thoughts" with no actual price chart → `not_a_chart`,
  empty setups. BUT if the IMAGE is a real price chart, it is NEVER
  not_a_chart, even when the caption is just a link (x.com / t.me) or emojis
  (👇) — classify from the chart in that case. Do NOT call real charts
  `no_trade` either (that's for charts with no setup).
- **Retrospective check next:** if current price is already at/beyond the
  final target (the move played out), OR the message is past-tense / brags
  the call worked ("played out perfectly", "we stuck to our guns", "we were
  right", "incredible move from $9 to $333", "would have exited"), it's
  `retrospective`, not a fresh call. Set `is_forward_looking=false`.
- **Cautionary ≠ long.** Messages like "starting to fail", "don't want to
  see it break below", "extreme caution", "losing the breakout" are NOT a
  long call — set `bias: bearish` (or `neutral`/`no_trade` if no level).
  Never default an emphatic warning to directional_long.
- **`bias` = CURRENT/ACTIVE sentiment, NOT the original thesis.** A trade can
  be structurally long (`call_type=directional_long`, setup direction long)
  while its present read is `neutral` — this is the common MULTI-STAGE case:
  the long was entered, price ran and faded/took profit, and it's now
  consolidating, watching for continuation vs invalidation ("wicked the nut
  box and faded, now in a wedge", "needs to hold above the break to stay
  viable"). Keep call_type/direction as the trade structure, but set
  `bias` to where momentum sits RIGHT NOW. If it's coiling/uncertain →
  `neutral`; only `bullish`/`bearish` when current momentum clearly leans.
- **`trade_stage` lifecycle (watching → active → completed) — 3 buckets:**
  - `watching` = the ENTRY TRIGGER HAS NOT FIRED. **GENERAL RULE: for ANY
    bounded consolidation/continuation pattern — pennant, wedge, triangle,
    diamond, flag, rectangle/range/box, channel, dome — the entry trigger is
    the BREAKOUT of that structure. While price is still INSIDE the pattern
    (coiling, ranging, "still in this diamond", near the apex), it has NOT
    triggered → `watching`.** This holds for bidirectional setups too: a
    long+short bracket on an unbroken pattern is `watching` (neither side
    fired). Cues: "still in the [pattern]", "needs to break", "hasn't
    confirmed", price visibly contained within the drawn structure.
  - **"broke wedge / broke out" = the trigger FIRED → `active`** (a move is
    underway). The yellow horizontal fib levels above also act as TP targets;
    price working through them = active, until the final nut box = completed.
  - `active` = the entry TRIGGER HAS FIRED — price has BROKEN OUT of the
    structure and is now running/being managed (incl. partial profit taken,
    monitoring continuation vs invalidation toward the nut box). Cues:
    "broke over/out", price clearly outside the pattern heading toward the
    box, "wicked the nut box and now managing". A pattern that has NOT broken
    is NEVER active — it's watching.
  - `completed` = the final target was reached — **price hit the NUT BOX**
    (see below), or the move otherwise fully played out. Pairs with
    `retrospective`.
  - **Nibble/starter ≠ active.** A small "nibbled a bit", "starter", "tiny
    position" BEFORE the structural trigger (trendline/pattern break) fires is
    still `watching`. When the caption CONFLICTS ("nibbled a bit of short
    watching here"), the CHART is the tiebreaker: if price hasn't broken the
    trigger structure, it's `watching`. An explicit "watching" in the text is
    a strong watching signal.
- **THE NUT BOX = the final take-profit zone — a highlighted RED/PURPLE
  RECTANGLE** near the top (long) or bottom (short) of the chart.
  **VISUAL CHECK FIRST (this is the accuracy signal — nut box hit = target
  reached = the trade worked):** look at where the most-recent price candles
  are relative to that rectangle. **If price has reached / entered / tagged /
  wicked the rectangle → `trade_stage: completed` (and `retrospective`).**
  This takes PRECEDENCE over any wedge/consolidation that is forming — "hit
  the nut box, now forming a wedge" is `completed` (the original trade hit
  target; the wedge is a NEW potential setup we don't recycle). Do NOT call
  it `watching` just because a new pattern is visible. Caption cues:
  "hit/tagged/wicked the nut box", "nutted", "reached the box".
- **ELLIOTT WAVES (W1–W5 labels on the chart):** these mark an Elliott wave
  count, NOT separate trades. W5 is typically the final target; W4 is the
  pullback after the W3 leg. A chart actively progressing through the waves
  (in W3/W4 working toward the W5 target) is a LIVE position → `active`, not
  watching. Only `completed` once W5 / the nut box is reached.
- **HARD CAPTION RULE — these phrases = `completed` + `retrospective`, FULL
  STOP, no matter what conditional text follows them:** "in the nut box" /
  "sitting in the nut box" / "at the nut box" / "wicked the nut box" / "hit/
  tagged the nut box" / "nutted" / "taking (a few) TP" / "took profit" /
  "over the nut box" / "gave you a [perfect] nut box" / "back from the nut
  box" / "retraced (back) from the nut box" / "hit nut box [then] retraced". Price reaching the nut box = TARGET HIT = the trade
  worked. Do NOT let trailing "needs to build over / needs volume / watching
  / for more" downgrade it to active/watching/no_trade — that trailing text
  is hypothetical re-entry musing (we don't recycle). The nut-box contact is
  the decisive event.
- **PRECEDENCE — completed beats re-entry musing (do NOT recycle trades).**
  When a caption says price HIT the nut box and then faded/dropped/dumped
  (the move happened) BUT also muses "would need a re-break to be viable
  again" / "re-break for more" / "needs to get back over", the call is
  `retrospective` + `trade_stage: completed`. The forward musing is a
  hypothetical NEW trade that almost never gets taken — it must NOT flip the
  classification to `directional_long`/`active`/`watching`. The PAST event
  (hit the box, faded) wins. Example: "three (SOL) hit upper nut box and
  faded back below ... would need a re-break to be viable again" →
  retrospective, completed (NOT directional_long/watching).
- **CONSISTENCY — `no_trade` cannot have a lifecycle.** If a chart shows a
  setup being watched, entered, managed, or completed, the call_type is
  `directional_long` / `directional_short` / `bidirectional` — NOT `no_trade`.
  `no_trade` and `not_a_chart` have `trade_stage: null`. Only when there is
  genuinely no setup at all (pure commentary on a chart) is it `no_trade`.
  A caption like "needs to hold over the orange line, had a few bounces" is a
  WATCHED long (directional_long + watching), not no_trade.
- **Dominance & total-market-cap charts = `no_trade`.** Tickers that are
  market-structure INDICES, not tradeable assets — anything ending in `.D`
  (BTC.D, USDT.D, ETH.D = dominance), or `TOTAL` / `TOTAL2` / `TOTAL3` /
  `OTHERS` / `CRYPTOCAP:*` (total market cap) — are macro CONTEXT, never a
  trade call. Always `call_type: no_trade`, even with directional language
  ("BTC.D fading", "USDT.D breaking out", "Total Cap rolling over").
- **Pure commentary = `no_trade`.** A general market observation with NO
  actionable setup or specific entry/level being called — "not any real
  support until $400", "sinking like a rock", "not much happening" — is
  `no_trade`, even when it carries directional flavor. Only call it
  directional/retrospective when there's an actual setup, entry, or a move
  being claimed as theirs.
- **Bidirectional:** two white entry rays pointing opposite ways, or explicit
  "if breaks up → X, if breaks down → Y" structure → `bidirectional` with two
  setups. Never force a single `bias`; use `bias: "neutral"`.
- **Bounded target:** when the chart marks a target with nothing projected
  beyond it ("up to 1750, then nothing"), put it in `final_target`. The call
  is judged on reaching `final_target`, not on holding past it.
- **direction per setup** comes from ray geometry: TP above entry = long, TP
  below entry = short (see CHART MARKUP CONVENTIONS). The top-level `bias` is
  the narrative lean; per-setup `direction` is what gets scored.
- If you genuinely cannot read a ticker, set `ticker: null` and
  `call_type: "no_trade"` — never invent a symbol.

---

## CHART MARKUP CONVENTIONS (owner-specific)

| Markup | Meaning |
|--------|---------|
| **WHITE horizontal ray** | ENTRY price |
| **ORANGE horizontal ray** | TAKE PROFIT (TP) price |
| **RED horizontal ray** | STOP LOSS price — NEVER an entry, NEVER a TP |
| **BLUE dashed horizontal line** | Key support/resistance level |
| **BLUE solid line** | Pattern structure (channel, wedge, trend line) |
| TP < entry | SHORT trade |
| TP > entry | LONG trade |
| Multiple WHITE rays | Multiple separate trade entries (can be BOTH long AND short on same chart) |
| Orange rays ABOVE a white ray | TPs for that long entry |
| Orange rays BELOW a white ray | TPs for that short entry |
| Red ray between entries | Stop loss level — group by proximity to determine which entry it belongs to |

---

## BOTH-SIDES SETUPS
A single chart can contain TWO simultaneous setups — one long, one short.
- Each white ray is a separate entry
- Group orange TPs by proximity to their white entry ray
- Store as two separate records with the same image_path
- Common context: price in a key zone (e.g. Fibonacci golden pocket) where it can move either direction

**Fibonacci Golden Pocket** = the zone between the 0.618 and 0.65 levels.
This is the highest-probability reaction zone. Price here warrants both-sides consideration.

---

## INDICATOR GUIDE — WHAT'S ON THE CHARTS

### Order Block Analyzer (colored horizontal bands/boxes)
- Shows institutional order blocks as colored zones (typically green = demand, red = supply)
- Used as a **supplementary check only** — NEVER as a standalone signal
- First check or last check — adds context to a setup already justified by pattern + Fib
- Do NOT call these blue dashed levels. They are filled zones, not lines.

### Trade Setup RR (large green/red boxes on chart)
- Old TradingView indicator the owner **no longer uses**
- **Disregard entirely** — do not interpret these as entries or targets
- If you see large green/red filled rectangles on a chart, ignore them

### Thanos EMA Cluster
- Multiple EMAs plotted together (typically 5/8/13/21/34/55 or similar)
- Tight cluster = compression, volatility coming
- Spread/stacked = trend in force

### TTM Squeeze (dots on MACD histogram baseline)
- Red dots = squeeze active (coiling)
- Green dots = squeeze released (expansion)
- Direction of first bar after release = likely direction of move

**Weighting rule:** When TTM is RED shaded / actively building (squeeze coiling), weight this heavily as a breakout signal. The longer the red squeeze persists, the larger the expected move. A red squeeze inside a pattern at a Fib level = extremely high probability setup. This should increase confluence score by +1 when present.

---

## DRAWING INTERPRETATION RULES (learned from validation)

| What you see | What it means | What it is NOT |
|---|---|---|
| Solid blue diagonal lines | Pattern structure (channel, wedge, trendline) | |
| Yellow hand-drawn scribble / curve | Owner's **price expectation sketch** — NOT a confirmed pattern | Not a pattern, not a Fib |
| Cursor crosshair ⊕ with price label | Cursor position only — NOT a level | Not a drawn level |
| Filled colored horizontal bands | Order Block Analyzer zones | Not blue dashed levels |
| Large green/red filled rectangles | Trade Setup RR indicator (deprecated) — ignore | Not entries or TPs |
| Orange rays above a white ray | TPs for the long at that white entry | |
| Orange rays below a white ray | TPs for the short at that white entry | |
| Zoomed price panel screenshot | Companion detail image — read independently, do NOT assume its levels belong to a nearby chart | |
| Orange labels on Fib grid | ALWAYS TPs — orange = take profit, regardless of position | Not Fib levels |

---

## OWNER'S TRADING STYLE NOTES

- Heavy Fibonacci — 0.618 + golden pocket (0.618–0.65) confluences are highest priority
- Preferred timeframes: **4h, 1D, 1W** (swing/macro)
- Dominant setups: breakouts, cup & handle, falling wedge, symmetrical triangle, descending channel
- Heavy crypto focus: BTC, XRP, SOL, DOGE, HBAR, SUI + XAUUSD, XAGUSD, TSLA
- Rarely trades without at least pattern + Fib confluence
- Extensions (1.272, 1.618) used for TP projection on breakouts
- Often marks both-sides setups at key Fib zones

---

*Last updated: 2026-02-22*
*Reference doc for: image_analyzer.py extraction prompt, agent/loop.py signal evaluation, future AI instances*
