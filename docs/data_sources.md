# Data Sources Catalogue

Reference: data sources and API integrations for the Macro Positioning Analyzer, discovered by auditing [Urban Kaoberg](https://urbankaoberg.com/) network traffic and mapped to our pipeline.

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

Covers the vast majority of macro data: rates, inflation, labor, growth, consumer, housing, fiscal, financial conditions, geopolitical risk indices, and cross-asset correlation inputs.

#### FRED Series Catalogue

**Rates**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `DFEDTARU` | Fed Funds Upper Target | % |
| `DGS10` | 10Y Treasury Yield | % |
| `DGS2` | 2Y Treasury Yield | % |
| `DGS30` | 30Y Treasury Yield | % |
| `T10Y2Y` | 10Y-2Y Spread | bps |
| `T10YIE` | 10Y Breakeven Inflation | % |
| `DFII10` | 10Y Real Yield | % |

**Inflation**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `CPIAUCSL` | CPI All Urban Consumers | index |
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
| `A191RL1Q225SBEA` | Real GDP QoQ Annualised | % |
| `INDPRO` | Industrial Production Index | index |
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

**Financial Conditions**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `NFCI` | Chicago Fed NFCI | index |
| `ANFCI` | Adjusted NFCI | index |
| `STLFSI4` | St. Louis Fed Financial Stress Index | index |
| `VIXCLS` | VIX | index |
| `DTWEXBGS` | Trade-Weighted USD | index |
| `DFF` | Effective Fed Funds Rate | % |
| `SOFR` | SOFR | % |
| `TEDRATE` | TED Spread | % |
| `BAMLH0A0HYM2` | HY OAS Spread | % |

**Geopolitical Risk**

| Series ID | Metric | Unit |
|-----------|--------|------|
| `USEPUINDXD` | US Economic Policy Uncertainty (daily) | index |
| `GEPUCURRENT` | Global EPU Index | index |
| `EPUTRADE` | Trade Policy Uncertainty | index |
| `EPUFISCAL` | Fiscal Policy Uncertainty | index |
| `EPUMONETARY` | Monetary Policy Uncertainty | index |
| `EMVNATSEC` | Equity Market Vol: National Security | index |

**Cross-Asset (for correlation matrix)**

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
| `BOPGSTB` | Trade Balance | millions $ |
| `BOPBCA` | Current Account Balance | millions $ |
| `GFDEBTN` | Total Public Debt Outstanding | millions $ |

**Macro Regime** (Growth vs Inflation quadrant)

| Series ID | Use |
|-----------|-----|
| `INDPRO` | Growth momentum (3-month change in YoY) |
| `CPIAUCSL` | Inflation momentum (3-month change in YoY) |

---

### 2. Financial Modeling Prep (FMP)

| | |
|---|---|
| **Status** | Not yet integrated |
| **Cost** | Freemium — 250 calls/day free, paid $19-79/month |
| **Sign-up** | https://site.financialmodelingprep.com/developer/docs |
| **Rate limit** | 250 calls/day (free), up to 10,000/day (paid) |
| **Config** | `MPA_FMP_API_KEY` (to be added) |

Used by Urban Kaoberg for historical OHLCV price data on equities, commodities, and FX. Also provides an economic calendar on paid plans.

**Key endpoints:**
- `/api/v3/historical-price-full/{symbol}` — EOD price data
- `/api/v3/quote/{symbol}` — real-time (15-min delayed free) quotes
- `/api/v3/economic_calendar` — economic events (Premium+ only)

**Tickers observed:**
- Equities: SPY, QQQ, IWM, DIA, EEM, EFA, VTI, XLK, XLF, XLE, XLV, SOXX
- Commodities: BZUSD, CLUSD, NGUSD, HOUSD, RBUSD, GCUSD, SIUSD, HGUSD, PLUSD, ZCUSX, KEUSX, ZSUSX, LEUSX, GFUSX, HEUSX, KCUSX, CCUSD, SBUSX, CTUSX
- FX: DX-Y.NYB, EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, USDSEK, USDNOK, USDMXN

**Free tier gotcha:** 250 calls/day is tight. Fetching all the above tickers daily eats ~45 calls just for prices. Economic calendar requires $49+/month.

---

### 3. Finnhub

| | |
|---|---|
| **Status** | Not yet integrated |
| **Cost** | Freemium — 60 calls/minute free, paid $49-99/month |
| **Sign-up** | https://finnhub.io/register |
| **Rate limit** | 60 calls/minute (free) |
| **Config** | `MPA_FINNHUB_API_KEY` (to be added) |

Used by Urban Kaoberg for per-ticker news headlines with AI-classified sentiment. Also provides general market news.

**Key endpoints:**
- `/api/v1/company-news?symbol={ticker}&from=YYYY-MM-DD&to=YYYY-MM-DD` — ticker-specific news
- `/api/v1/news?category=general` — general market news (categories: general, forex, crypto, merger)
- `/api/v1/calendar/economic` — economic events calendar

**Notes:** Free tier includes basic sentiment labels (positive/negative/neutral). Attribution required when displaying data.

---

### 4. Google News RSS

| | |
|---|---|
| **Status** | Not yet integrated |
| **Cost** | Free, no API key required |
| **Rate limit** | Unofficial — poll every 15-30 minutes to be safe |

Used by Urban Kaoberg for broad macro/geopolitical headlines by category, which are then classified by their AI sentiment pipeline.

**Feed pattern:**
```
https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en
```

**Useful queries for macro analysis:**
- `economy macro outlook`
- `federal reserve interest rates`
- `inflation CPI PPI`
- `oil commodities gold`
- `geopolitics sanctions tariffs`
- `stock market equities`
- `currency forex dollar`

**Notes:** No sentiment data included — requires own NLP pipeline or LLM classification. No historical data; must poll and store. No SLA.

---

## Urban Kaoberg Platform Reference

The above APIs were discovered by auditing network requests from [urbankaoberg.com](https://urbankaoberg.com/), a macro financial dashboard (beta) by Kaoboy Holdings, LLC.

### Platform Module Map

**Asset Class Tabs:** MACRO, EQUITIES, CREDIT, RATES, FX, COMMODITIES, FUNDS, CRYPTO, Special Sits, PORTFOLIO

**Macro Analytical Modules:**

| Module | Data Source | Key Content |
|--------|-------------|-------------|
| Dashboard (AI) | FRED + FMP | 32+ economic indicators across 8 categories with auto-refresh on release days |
| Geopolitics | FRED | Risk dashboard with EPU indices, trade/fiscal/monetary uncertainty; sanctions, elections, energy security trackers |
| Calendar | FMP | Economic events calendar |
| Fin Conditions | FRED | NFCI, STLFSI, VIX, USD, Fed Funds, SOFR, TED Spread, HY Spreads — with z-scores and percentile rankings |
| Capital Flows | FRED | Foreign-held debt, trade balance, current account, TIC net flows |
| Correlations | FRED | Cross-asset correlation matrix (30/60/90-day rolling windows) across equities, rates, FX, commodities |
| Macro Regime | FRED | Growth vs inflation quadrant (Goldilocks/Reflation/Stagflation/Deflation) with asset class performance expectations |
| Trade Signals (AI) | TBD | Appears under construction |
| News (AI) | Finnhub + Google News RSS + OpenAI | AI-classified headlines with BULLISH/BEARISH/NEUTRAL sentiment |

**Per-Asset Module Types:**
- Charts (FMP OHLCV data, technical overlays, oscillators)
- AI Analysis, Screener, Heatmaps, Sectors, Scatter, Volatility, World (equities)
- Forward Curves, Commodity Spreads, COT, Energy Inventories (commodities)
- FX Matrix, Rate Differentials, Fair Value, FX Flows (currencies)

---

## Integration Priority

| # | Provider | Cost | Covers | Status |
|---|----------|------|--------|--------|
| 1 | **FRED** | Free | Macro indicators, fin conditions, geopolitics, correlations, regime | Integrated |
| 2 | **Finnhub** | Free (60/min) | Per-ticker news + sentiment | Next |
| 3 | **Google News RSS** | Free | Broad macro headlines | Next |
| 4 | **FMP** | Freemium (250/day) | OHLCV prices, economic calendar | Later |
