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

## SECTION 10: OUTPUT FORMAT (Claude response template)

When analyzing any chart image, respond with this structure:

```
1. DOMINANT PATTERN
   [Pattern name, direction, validity assessment]

2. FIB CONFLUENCE
   [Levels visible, colors, alignment with pattern]

3. HISTORICAL LEVEL ALIGNMENT
   [Blue dashed levels, position relative to price and pattern]

4. MACD + TTM STATE
   [Expanding / compressing / squeeze, bullish or bearish]

5. RSI STRUCTURE
   [Above/below 50, divergence, trend line status]

6. OVERALL CONFLUENCE
   [Low / Medium / High — count of aligned factors]

7. BIAS
   [Bullish / Bearish / Neutral]

8. INVALIDATION LEVEL
   [Exact price or zone that breaks the thesis]

9. MOST PROBABLE NEXT MOVE
   [Price target, direction, timeframe context]
```

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
