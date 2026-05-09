# Data Sources Catalogue

> **Last updated:** 2026-05-09
> **Cross-references:** `docs/architecture_overview.md §Intelligence Layer`, `docs/architecture.md §Intelligence Layer: Classifier Details`

Reference: data sources and API integrations for the Macro Positioning Analyzer. FRED series catalogue audited against [Urban Kaoberg](https://urbankaoberg.com/) network traffic and expanded to support the intelligence layer classifiers.

---

## API Providers

### 1. FRED (Federal Reserve Economic Data)

| | |
|---|---|
| **Status** | Integrated (`FREDMarketDataProvider`) |
| **Cost** | Free |
| **Sign-up** | https://fred.stlouisfed.org/docs/api/api_key.html |
| **Rate limit** | 120 requests/minute, no daily cap |
| **Base URL** | `https://api.stlouisfed.org/fred/series/observations` |
| **Config** | `MPA_FRED_API_KEY` in `.env` |

51 series fetched across 9 categories. Three categories — **Intelligence Layer** below — are consumed by the classifiers in `macro_indicators.py` before the LLM synthesis call.

#### FRED Series Catalogue

**Rates**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `DFEDTARU` | Fed Funds Upper Target | % |
| `DGS10` | 10Y Treasury Yield | % |
| `DGS2` | 2Y Treasury Yield | % |
| `DGS30` | 30Y Treasury Yield | % |
| `T10Y2Y` | 10Y-2Y Spread | bps |
| `T10YIE` | 10Y Breakeven Inflation | % ← **quadrant classifier (inflation primary)** |
| `DFII10` | 10Y Real Yield | % |

**Inflation**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `CPIAUCSL` | CPI All Urban Consumers | index ← **quadrant classifier (inflation fallback)** |
| `PPIACO` | PPI All Commodities | index |
| `PCEPI` | PCE Price Index | index |
| `PCEPILFE` | Core PCE Price Index | index |

**Labor**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `UNRATE` | Unemployment Rate | % |
| `PAYEMS` | Nonfarm Payrolls | thousands |
| `ICSA` | Initial Jobless Claims | claims |
| `JTSJOL` | JOLTS Job Openings | thousands |

**Growth**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `A191RL1Q225SBEA` | Real GDP QoQ Annualised | % ← **quadrant classifier (growth primary)** |
| `INDPRO` | Industrial Production Index | index ← **quadrant classifier (growth fallback)** |
| `DGORDER` | Durable Goods Orders | millions $ |
| `BOPGSTB` | Trade Balance Goods & Services | millions $ |

**Consumer**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `RSAFS` | Retail Sales | millions $ |
| `PI` | Personal Income | billions $ |
| `PCE` | Personal Consumption Expenditures | billions $ |
| `UMCSENT` | UMich Consumer Sentiment | index |
| `MICH` | UMich Inflation Expectations | % |

**Housing**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `HOUST` | Housing Starts | thousands |
| `PERMIT` | Building Permits | thousands |
| `EXHOSLUSM495S` | Existing Home Sales | units |
| `HSN1F` | New Home Sales | thousands |

**Fiscal**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `MTSDS133FMS` | Federal Surplus/Deficit | millions $ |

**Financial Conditions** ← FCI classifier inputs

| Series ID | Metric | Unit | Classifier role |
|-----------|--------|------|-----------------|
| `NFCI` | Chicago Fed NFCI | index | **FCI primary** (used directly) |
| `ANFCI` | Adjusted NFCI | index | FCI supporting context |
| `STLFSI4` | St. Louis Fed Financial Stress Index | index | FCI supporting context |
| `VIXCLS` | VIX | index | FCI sub-indicator (scale: 20.0, weight: 0.05) |
| `DTWEXBGS` | Trade-Weighted USD | index | Context only |
| `DFF` | Effective Fed Funds Rate | % | Context only |
| `SOFR` | SOFR | % | Context only |
| `TEDRATE` | TED Spread | % | FCI sub-indicator (scale: 0.5, weight: 0.60) |
| `BAMLH0A0HYM2` | HY OAS Spread | % | FCI sub-indicator (scale: 4.0, weight: 0.20) |

FCI label thresholds: `NFCI > 0.3` → tightening, `< -0.3` → easing, else neutral.

**Geopolitical Risk** ← EPU classifier inputs

| Series ID | Metric | Unit |
|-----------|--------|------|
| `USEPUINDXD` | US Economic Policy Uncertainty (daily) | index (~100 = avg) |
| `GEPUCURRENT` | Global EPU Index | index (~100 = avg) |
| `EPUTRADE` | Trade Policy Uncertainty | index (~100 = avg) |
| `EPUFISCAL` | Fiscal Policy Uncertainty | index (~100 = avg) |
| `EPUMONETARY` | Monetary Policy Uncertainty | index (~100 = avg) |
| `EMVNATSEC` | Equity Market Vol: National Security | index (~100 = avg) |

EPU composite = simple average of available series. Level: `> 150` → elevated, `< 80` → low, else moderate. Dominant driver = series with highest absolute deviation from 100.

**Cross-Asset (for correlation matrix — planned)**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `SP500` | S&P 500 | index |
| `NASDAQCOM` | NASDAQ Composite | index |
| `DCOILWTICO` | WTI Crude Oil | $/barrel |
| `DCOILBRENTEU` | Brent Crude Oil | $/barrel |
| `DHHNGSP` | Natural Gas (Henry Hub) | $/mmbtu |
| `DEXJPUS` | JPY/USD | yen per dollar |
| `DEXUSEU` | USD/EUR | dollars per euro |

**Capital Flows**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `FDHBFIN` | Foreign-Held Federal Debt | millions $ |
| `BOPBCA` | Current Account Balance | millions $ |
| `GFDEBTN` | Total Public Debt Outstanding | millions $ |

---

### 2. Financial Modeling Prep (FMP)

| | |
|---|---|
| **Status** | Not yet integrated |
| **Cost** | Freemium — 250 calls/day free, paid $19-79/month |
| **Sign-up** | https://site.financialmodelingprep.com/developer/docs |
| **Config** | `MPA_FMP_API_KEY` (to be added) |

Used by Urban Kaoberg for historical OHLCV price data on equities, commodities, and FX. Also provides an economic calendar on paid plans.

**Key endpoints:**
- `/api/v3/historical-price-full/{symbol}` — EOD price data
- `/api/v3/quote/{symbol}` — real-time (15-min delayed free) quotes
- `/api/v3/economic_calendar` — economic events (Premium+ only)

**Free tier gotcha:** 250 calls/day is tight for the full ticker universe.

---

### 3. Finnhub

| | |
|---|---|
| **Status** | Not yet integrated |
| **Cost** | Freemium — 60 calls/minute free |
| **Sign-up** | https://finnhub.io/register |
| **Config** | `MPA_FINNHUB_API_KEY` (to be added) |

Per-ticker news with AI-classified sentiment. Also general market news.

---

### 4. Google News RSS

| | |
|---|---|
| **Status** | Not yet integrated |
| **Cost** | Free, no API key |
| **Rate limit** | Poll every 15-30 min to be safe |

Feed pattern: `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en`

---

### 5. COT Data (CFTC) — PHASE C, DEFERRED

| | |
|---|---|
| **Status** | Deferred — not built |
| **Cost** | Free (public domain) |
| **Source** | CFTC weekly Commitments of Traders reports |
| **Planned file** | `src/macro_positioning/market/cot_provider.py` |

Urban Kaoberg's commodities module includes COT positioning data (net long/short by commercial vs non-commercial traders). This was identified as one of the 5 Urban Kaoberg intelligence items to adopt.

**Why deferred:** Requires CFTC CSV parsing or a Quandl/commodity_data API connector. The data is weekly and less time-critical than the FRED-based classifiers. Will be prioritized after Phase A (classifiers) and Phase B (SPA dashboard) are validated.

**What it would enable:**
- For each commodity (crude, gold, natgas, corn, etc.): net speculative positioning as a contrarian/confirmation signal
- Positioning extremes (>95th percentile) flagged on the asset breakdown view
- COT data block injected into the synthesis prompt alongside regime/FCI/EPU

---

## Urban Kaoberg Platform Reference

[urbankaoberg.com](https://urbankaoberg.com/) — macro financial dashboard (beta) by Kaoboy Holdings, LLC. Used as an architectural reference. Network traffic audit revealed their FRED series list and module structure.

### What we adopted from Urban Kaoberg (2026-05 sprint)

| Urban Kaoberg feature | What we built | Status |
|---|---|---|
| Macro Regime quadrant (Goldilocks/Reflation/Stagflation/Deflation) | `classify_growth_inflation_quadrant()` in `macro_indicators.py` | ✅ Built |
| Financial Conditions Index (NFCI + z-scores) | `compute_fci()` in `macro_indicators.py` | ✅ Built |
| Geopolitics / EPU risk dashboard | `compute_geopolitical_risk()` in `macro_indicators.py` | ✅ Built |
| Asset class grouping (EQUITIES / RATES / CREDIT / etc.) | `AssetBreakdown.asset_class` + `_THEME_TO_ASSET_CLASS` in `command_data.py` | ✅ Built |
| COT data (Forward Curves, Commodity Spreads, COT) | `cot_provider.py` | ⏳ Phase C, deferred |

The three classifiers are injected into the LLM synthesis prompt (`brain/prompts.py`) as structured blocks, so the LLM explicitly references regime, FCI, and EPU when justifying direction and confidence.

### Urban Kaoberg Module Map (reference)

**Macro Analytical Modules:**

| Module | Data Source | Key Content |
|--------|-------------|-------------|
| Dashboard (AI) | FRED + FMP | 32+ economic indicators, auto-refresh on release days |
| Geopolitics | FRED | EPU risk dashboard (trade/fiscal/monetary uncertainty) |
| Calendar | FMP | Economic events |
| Fin Conditions | FRED | NFCI, STLFSI, VIX, USD, TED Spread, HY Spreads (z-scores + percentile) |
| Capital Flows | FRED | Foreign-held debt, trade balance, current account, TIC net flows |
| Correlations | FRED | Cross-asset correlation matrix (30/60/90-day rolling) |
| Macro Regime | FRED | Growth vs inflation quadrant with asset class performance expectations |
| Trade Signals (AI) | TBD | Appears under construction |
| News (AI) | Finnhub + Google News RSS + OpenAI | AI-classified headlines with BULLISH/BEARISH/NEUTRAL |

**Per-Asset Modules (commodities specific):**
- Forward Curves, Commodity Spreads, **COT**, Energy Inventories

---

## Integration Priority

| # | Provider | Cost | Covers | Status |
|---|----------|------|--------|--------|
| 1 | **FRED** | Free | Macro indicators, fin conditions, geopolitics, regime classifiers | ✅ Integrated |
| 2 | **Finnhub** | Free (60/min) | Per-ticker news + sentiment | Next |
| 3 | **Google News RSS** | Free | Broad macro headlines | Next |
| 4 | **FMP** | Freemium (250/day) | OHLCV prices, economic calendar | Later |
| 5 | **CFTC COT** | Free | Speculative positioning in commodities/FX/rates | Phase C |
