// Mock data for Macro Analyzer dashboard.
// Reflects the v3 thesis (capital rotation through hyper-liquidity cycle)
// + trading framework regime model.

window.MA_DATA = {
  // ---------- Regime ----------
  regime: {
    framework: {
      label: "Commodity-Led Inflation",
      slug: "commodity_led_inflation",
      confidence: 0.78,
      bias: "real_asset_bullish",
      sizingModifier: 1.1,
      scoreModifier: 8,
      sinceDays: 14,
    },
    thesis: {
      label: "Two-Speed · Liquidity ↔ Structural",
      narrative:
        "Liquidity setting the pace, structural energy / resource stress setting leadership. Capital rotating from index beta into real assets faster than fundamentals are repaired.",
      version: "v3",
      author: "Lindsey",
      lastRevised: "2026-04-22",
    },
    // 90-day daily regime confidence trace (0..1) — for sparkline shape
    confidenceTrace: [0.41,0.43,0.42,0.45,0.49,0.52,0.50,0.48,0.51,0.55,0.58,0.62,0.60,0.58,0.61,0.65,0.68,0.66,0.64,0.66,0.69,0.71,0.70,0.67,0.69,0.72,0.74,0.73,0.71,0.74,0.76,0.78,0.76,0.74,0.77,0.79,0.81,0.79,0.77,0.79,0.81,0.82,0.80,0.78,0.80,0.82,0.83,0.81,0.79,0.80,0.82,0.83,0.81,0.78,0.79,0.81,0.83,0.81,0.79,0.80,0.81,0.83,0.82,0.80,0.79,0.81,0.83,0.82,0.80,0.78,0.77,0.79,0.80,0.78,0.76,0.77,0.78,0.78,0.77,0.78,0.79,0.78,0.77,0.78],
    transitions: [
      { date: "2026-02-04", from: "Transitional Chop", to: "Dovish Liquidity Wave" },
      { date: "2026-03-19", from: "Dovish Liquidity Wave", to: "Commodity-Led Inflation" },
    ],
  },

  // ---------- KPI strip ----------
  kpis: {
    cashPosture: { label: "Neutral", pct: 32, delta: -4 },
    activeTrades: { count: 6, exposureUsd: 184500 },
    pnlToday: { usd: 3120, pct: 1.69 },
    pnlWeek: { usd: 8450, pct: 4.58 },
    signalsHigh: { count: 4, deltaVsYesterday: +1 }, // score >= 75
    spendToday: { usd: 4.82, capUsd: 25 },
  },

  // ---------- Hero signals (top scored setups today) ----------
  heroSignals: [
    {
      id: "sig-ura-2605",
      asset: "URA",
      name: "Sprott Uranium Miners",
      side: "LONG",
      score: 88,
      scorePrev: 74,
      tier: 1,
      setup: "Long Base Accumulation · Breakout retest",
      regimeFit: "commodity_led_inflation",
      entry: 41.20,
      stop: 39.40,
      target: 47.50,
      rr: 3.50,
      whyNow: [
        "Reactor restart cadence accelerating; physical U₃O₈ tape firming above $94.",
        "Group reclaimed 50DMA on volume; relative strength leader vs SPY (+6.4% 20d).",
        "Aligns with framework regime: real-asset bias + liquidity neutral-to-easing.",
      ],
      sources: ["Doomberg", "Doomberg Substack", "FRED · CPI exp.", "Capitalist Exploits"],
      lastUpdate: "08:14",
    },
    {
      id: "sig-gld-2605",
      asset: "GLD",
      name: "SPDR Gold Trust",
      side: "LONG",
      score: 84,
      scorePrev: 81,
      tier: 1,
      setup: "Pullback to 50DMA · Demand reaction",
      regimeFit: "commodity_led_inflation",
      entry: 268.40,
      stop: 261.00,
      target: 296.00,
      rr: 3.73,
      whyNow: [
        "Real yields rolled over -18bps in 2 sessions; central-bank tape printed +47t May.",
        "Pullback held 50DMA on contracting volume — textbook constructive pullback.",
        "Debasement / hard-asset thesis intact; positioning still under Q4'25 peak.",
      ],
      sources: ["Doomberg", "FRED · DGS10", "Goldman GIR (S)"],
      lastUpdate: "08:11",
    },
    {
      id: "sig-xop-2605",
      asset: "XOP",
      name: "Oil & Gas E&P",
      side: "LONG",
      score: 78,
      scorePrev: 70,
      tier: 2,
      setup: "Breakout continuation",
      regimeFit: "commodity_led_inflation",
      entry: 152.10,
      stop: 147.00,
      target: 168.00,
      rr: 3.12,
      whyNow: [
        "Brent reclaimed $86 after Strait headlines; OVX deflating into the move.",
        "Sector breadth (XLE adv/dec) at 28d high; capex tape supportive.",
        "Cluster vote: 3/4 energy theses bullish, 1 mixed.",
      ],
      sources: ["Energy Cap.", "Reuters", "FRED · WTI"],
      lastUpdate: "08:09",
    },
    {
      id: "sig-tlt-2605",
      asset: "TLT",
      name: "20Y+ Treasury",
      side: "SHORT",
      score: 72,
      scorePrev: 76,
      tier: 2,
      setup: "Lower-high · failed reclaim",
      regimeFit: "commodity_led_inflation",
      entry: 86.40,
      stop: 88.20,
      target: 81.50,
      rr: 2.72,
      whyNow: [
        "Failed to reclaim 50DMA; lower high vs April. Inflation tape sticky.",
        "Term premium expanding; supply schedule front-loaded into Q3.",
      ],
      sources: ["FRED · DGS30", "Bianco (S)"],
      lastUpdate: "07:58",
    },
    {
      id: "sig-btc-2605",
      asset: "BTC",
      name: "Bitcoin",
      side: "WATCH",
      score: 68,
      scorePrev: 62,
      tier: 3,
      setup: "Probe · waiting on liquidity confirm",
      regimeFit: "monetary_debasement_hard_asset",
      entry: 71200,
      stop: 67800,
      target: 84000,
      rr: 3.76,
      whyNow: [
        "Holding above 200DMA but no decisive reclaim of prior range high.",
        "Stablecoin liquidity flat 4w; needs liquidity confirm before sizing.",
      ],
      sources: ["Doomberg", "Glassnode"],
      lastUpdate: "07:52",
    },
  ],

  // ---------- Watchlist (full scored) ----------
  watchlist: [
    { asset: "URA",  side: "LONG",  score: 88, dScore: +14, tier: 1, regime: "fit",  tech: "A",  vol: "A",  rr: 3.50, last: "08:14" },
    { asset: "GLD",  side: "LONG",  score: 84, dScore: +3,  tier: 1, regime: "fit",  tech: "A",  vol: "B+", rr: 3.73, last: "08:11" },
    { asset: "XOP",  side: "LONG",  score: 78, dScore: +8,  tier: 2, regime: "fit",  tech: "B+", vol: "A",  rr: 3.12, last: "08:09" },
    { asset: "TLT",  side: "SHORT", score: 72, dScore: -4,  tier: 2, regime: "fit",  tech: "B",  vol: "B",  rr: 2.72, last: "07:58" },
    { asset: "BTC",  side: "WATCH", score: 68, dScore: +6,  tier: 3, regime: "mix",  tech: "B",  vol: "C",  rr: 3.76, last: "07:52" },
    { asset: "DBA",  side: "WATCH", score: 65, dScore: +2,  tier: 3, regime: "fit",  tech: "B-", vol: "B",  rr: 2.40, last: "07:46" },
    { asset: "ITA",  side: "LONG",  score: 64, dScore: -3,  tier: 3, regime: "mix",  tech: "B",  vol: "C+", rr: 2.10, last: "07:43" },
    { asset: "COPX", side: "WATCH", score: 61, dScore: +1,  tier: 3, regime: "fit",  tech: "C+", vol: "B",  rr: 2.85, last: "07:40" },
    { asset: "NVDA", side: "WATCH", score: 58, dScore: -7,  tier: 3, regime: "mix",  tech: "B",  vol: "B+", rr: 1.90, last: "07:36" },
    { asset: "QQQ",  side: "AVOID", score: 49, dScore: -5,  tier: 4, regime: "off",  tech: "C",  vol: "C",  rr: 1.30, last: "07:31" },
    { asset: "HYG",  side: "AVOID", score: 44, dScore: -2,  tier: 4, regime: "off",  tech: "C-", vol: "C",  rr: 1.10, last: "07:29" },
    { asset: "ARKK", side: "AVOID", score: 38, dScore: -9,  tier: 4, regime: "off",  tech: "D",  vol: "C-", rr: 0.90, last: "07:25" },
  ],

  // ---------- Active trades ----------
  activeTrades: [
    {
      id: "t-2026-019", asset: "URA", side: "LONG",
      entry: 38.10, stop: 36.50, target: 47.50,
      sizeUsd: 32000, ageDays: 11,
      pnlPct: +6.42, pnlUsd: +2054,
      regimeAtOpen: "Commodity-Led Inflation", scoreAtOpen: 74, scoreNow: 88,
      status: "running",
    },
    {
      id: "t-2026-018", asset: "GLD", side: "LONG",
      entry: 261.20, stop: 257.00, target: 296.00,
      sizeUsd: 48000, ageDays: 18,
      pnlPct: +2.75, pnlUsd: +1320,
      regimeAtOpen: "Commodity-Led Inflation", scoreAtOpen: 79, scoreNow: 84,
      status: "running",
    },
    {
      id: "t-2026-017", asset: "XOP", side: "LONG",
      entry: 149.40, stop: 145.50, target: 168.00,
      sizeUsd: 28000, ageDays: 6,
      pnlPct: +1.81, pnlUsd: +507,
      regimeAtOpen: "Commodity-Led Inflation", scoreAtOpen: 70, scoreNow: 78,
      status: "running",
    },
    {
      id: "t-2026-016", asset: "ITA", side: "LONG",
      entry: 162.30, stop: 158.40, target: 178.00,
      sizeUsd: 22000, ageDays: 22,
      pnlPct: -0.62, pnlUsd: -136,
      regimeAtOpen: "Commodity-Led Inflation", scoreAtOpen: 67, scoreNow: 64,
      status: "near_invalidation",
    },
    {
      id: "t-2026-015", asset: "TLT", side: "SHORT",
      entry: 88.10, stop: 89.80, target: 81.50,
      sizeUsd: 30000, ageDays: 4,
      pnlPct: +1.93, pnlUsd: +578,
      regimeAtOpen: "Commodity-Led Inflation", scoreAtOpen: 76, scoreNow: 72,
      status: "running",
    },
    {
      id: "t-2026-014", asset: "COPX", side: "LONG",
      entry: 41.80, stop: 40.10, target: 48.00,
      sizeUsd: 24500, ageDays: 9,
      pnlPct: -1.20, pnlUsd: -294,
      regimeAtOpen: "Commodity-Led Inflation", scoreAtOpen: 68, scoreNow: 61,
      status: "watch",
    },
  ],

  // ---------- Reasoning trail (per-setup explain) ----------
  reasoning: {
    "sig-ura-2605": {
      total: 88,
      tier: 1,
      components: [
        { label: "Macro alignment",   score: 18, max: 20, color: "amber" },
        { label: "Liquidity",         score: 12, max: 15, color: "amber" },
        { label: "Sector strength",   score:  9, max: 10, color: "amber" },
        { label: "Technical structure", score: 13, max: 15, color: "green" },
        { label: "Volume confirm",    score:  9, max: 10, color: "green" },
        { label: "Risk / Reward",     score: 14, max: 15, color: "green" },
        { label: "Setup quality",     score:  8, max: 10, color: "amber" },
        { label: "Psychology · clean", score:  5, max:  5, color: "green" },
      ],
      modifiers: [
        { label: "Regime fit · commodity_led_inflation", value: "+8" },
        { label: "Failed-breakout penalty", value: "0" },
        { label: "Extended-from-support penalty", value: "0" },
      ],
      sources: [
        { name: "Doomberg",          weight: 0.92, freshness: "fresh", contrib: +14, tags: ["energy","commodities"] },
        { name: "Energy Capitalist", weight: 0.81, freshness: "fresh", contrib: +9,  tags: ["energy"] },
        { name: "FRED · CPI exp.",   weight: 0.78, freshness: "fresh", contrib: +6,  tags: ["macro"] },
        { name: "Capitalist Exploits", weight: 0.74, freshness: "1d", contrib: +4,  tags: ["thematic"] },
        { name: "Bianco Research",   weight: 0.68, freshness: "2d",   contrib: +3,  tags: ["macro"] },
        { name: "Twitter · @woodway", weight: 0.42, freshness: "fresh", contrib: +1,  tags: ["positioning"] },
      ],
      theses: [
        { theme: "Energy",      direction: "bullish", confidence: 0.81 },
        { theme: "Hard assets", direction: "bullish", confidence: 0.74 },
        { theme: "Tech / AI",   direction: "mixed",   confidence: 0.55 },
      ],
      agentBreakdown: [
        { agent: "regime_classifier",   model: "gemini-2.5-pro",     latencyMs: 820, costUsd: 0.018, ok: true },
        { agent: "narrative_synthesizer", model: "claude-haiku-4.5", latencyMs: 1240, costUsd: 0.012, ok: true },
        { agent: "score_composer",      model: "gemini-2.5-pro",     latencyMs: 690, costUsd: 0.011, ok: true },
        { agent: "chart_vision",        model: "gemini-2.5-pro",     latencyMs: 1980, costUsd: 0.024, ok: true },
        { agent: "rationale_writer",    model: "claude-haiku-4.5",   latencyMs: 540, costUsd: 0.005, ok: true },
      ],
    },
  },

  // ---------- Closed trades (journal) ----------
  closedTrades: [
    { id: "t-2026-013", asset: "GDX", side: "LONG", entry: 38.20, exit: 41.40, pnlPct: +8.38, holdDays: 14, scoreEntry: 81, regimeEntry: "Commodity-Led Inflation", thesis: "yes",     planClean: true,  lesson: "Held through 50DMA wobble — paid." },
    { id: "t-2026-012", asset: "URA", side: "LONG", entry: 35.70, exit: 33.40, pnlPct: -6.44, holdDays:  6, scoreEntry: 71, regimeEntry: "Transitional Chop",          thesis: "no",      planClean: true,  lesson: "Took setup in bad regime; framework warned." },
    { id: "t-2026-011", asset: "ITA", side: "LONG", entry: 158.10, exit: 168.00, pnlPct: +6.26, holdDays: 21, scoreEntry: 73, regimeEntry: "Commodity-Led Inflation",  thesis: "partial", planClean: true,  lesson: "Defense lagged then caught up; bigger size next." },
    { id: "t-2026-010", asset: "QQQ", side: "SHORT", entry: 521.40, exit: 528.10, pnlPct: -1.28, holdDays:  3, scoreEntry: 64, regimeEntry: "Dovish Liquidity Wave",   thesis: "no",      planClean: false, lesson: "Counter-regime short. Stop. Don't fade liquidity." },
    { id: "t-2026-009", asset: "GLD", side: "LONG", entry: 248.60, exit: 261.20, pnlPct: +5.07, holdDays:  9, scoreEntry: 78, regimeEntry: "Commodity-Led Inflation",  thesis: "yes",     planClean: true,  lesson: "Sized correctly; clean entry on 20DMA." },
    { id: "t-2026-008", asset: "COPX", side: "LONG", entry: 39.10, exit: 38.20, pnlPct: -2.30, holdDays:  4, scoreEntry: 66, regimeEntry: "Commodity-Led Inflation",  thesis: "partial", planClean: true,  lesson: "Right thesis, early entry — wait for retest hold." },
    { id: "t-2026-007", asset: "BTC", side: "LONG", entry: 67400, exit: 71200, pnlPct: +5.64, holdDays: 11, scoreEntry: 72, regimeEntry: "Dovish Liquidity Wave",     thesis: "yes",     planClean: true,  lesson: "Liquidity tape was clear; took it." },
    { id: "t-2026-006", asset: "TLT", side: "SHORT", entry: 91.20, exit: 88.10, pnlPct: +3.40, holdDays:  7, scoreEntry: 70, regimeEntry: "Commodity-Led Inflation",  thesis: "yes",     planClean: true,  lesson: "Term premium thesis paid quickly." },
    { id: "t-2026-005", asset: "ARKK", side: "SHORT", entry: 51.20, exit: 50.40, pnlPct: +1.56, holdDays:  2, scoreEntry: 62, regimeEntry: "Transitional Chop",      thesis: "partial", planClean: true,  lesson: "Took partial at first target; correct." },
    { id: "t-2026-004", asset: "DBA", side: "LONG", entry: 26.40, exit: 26.10, pnlPct: -1.14, holdDays: 12, scoreEntry: 65, regimeEntry: "Commodity-Led Inflation",  thesis: "no",      planClean: true,  lesson: "Ag fundamentals didn't catch — invalidation hit." },
  ],

  missedTrades: [
    { asset: "GDX", scoreAtTime: 82, reason: "missed_alert", validReal: true,  hindsightRisk: 2, lesson: "Set proper alerts on Tier-1 setups." },
    { asset: "ITA", scoreAtTime: 73, reason: "hesitation",   validReal: true,  hindsightRisk: 3, lesson: "Defense thesis was real-time clear; sized too small." },
    { asset: "OIH", scoreAtTime: 70, reason: "size_concern", validReal: true,  hindsightRisk: 4, lesson: "Correlation w/ XOP — should've routed XOP only." },
    { asset: "URNM", scoreAtTime: 76, reason: "duplicate",   validReal: false, hindsightRisk: 1, lesson: "URA already covered — no miss." },
  ],

  processScorecard: {
    days: 30,
    score: 86,
    metrics: [
      { label: "Entry planned in advance",   value: 92, of: 100 },
      { label: "Invalidation defined",       value: 100, of: 100 },
      { label: "Size predefined",            value: 88, of: 100 },
      { label: "Setup matched playbook",     value: 79, of: 100 },
      { label: "Outcome logged within 24h",  value: 71, of: 100 },
      { label: "Lesson written",             value: 86, of: 100 },
    ],
  },

  sourceLeaderboard: [
    { name: "Doomberg",            weight: 0.92, dWeight: +0.04, attribUsd: +6840, trades: 7, tags: ["energy","commodities"] },
    { name: "Energy Capitalist",   weight: 0.81, dWeight: +0.02, attribUsd: +3120, trades: 5, tags: ["energy"] },
    { name: "FRED · DGS10/CPI",    weight: 0.78, dWeight: 0.00,  attribUsd: +2470, trades: 9, tags: ["macro"] },
    { name: "Capitalist Exploits", weight: 0.74, dWeight: +0.01, attribUsd: +1810, trades: 4, tags: ["thematic"] },
    { name: "Bianco Research",     weight: 0.68, dWeight: -0.01, attribUsd: +890,  trades: 6, tags: ["macro","rates"] },
    { name: "Goldman GIR (S)",     weight: 0.62, dWeight: -0.02, attribUsd: +420,  trades: 3, tags: ["sell-side"] },
    { name: "@woodway (Twitter)",  weight: 0.42, dWeight: -0.06, attribUsd: -380,  trades: 4, tags: ["positioning"] },
    { name: "ZeroHedge RSS",       weight: 0.28, dWeight: -0.08, attribUsd: -640,  trades: 3, tags: ["news"] },
  ],

  // Spearman ρ between score components and realized PnL %.
  // Empty until closed trades exist; SPA renders zero-state from the same shape.
  scoreCorrelation: {
    n_pairs: 14,
    components: [
      { name: "adjusted_total",       spearman: +0.42, p_value: 0.13, n: 14 },
      { name: "macro_alignment",      spearman: +0.31, p_value: 0.27, n: 14 },
      { name: "liquidity",            spearman: +0.18, p_value: 0.54, n: 14 },
      { name: "sector_theme",         spearman: +0.55, p_value: 0.04, n: 14 },
      { name: "technical_structure",  spearman: +0.38, p_value: 0.18, n: 14 },
      { name: "volume_flow",          spearman: +0.22, p_value: 0.45, n: 14 },
      { name: "risk_reward",          spearman: +0.49, p_value: 0.07, n: 14 },
      { name: "relative_strength",    spearman: +0.27, p_value: 0.34, n: 14 },
      { name: "psychology",           spearman: -0.08, p_value: 0.78, n: 14 },
    ],
  },

  thesisChangelog: [
    { date: "2026-04-22", from: "v2.4", to: "v3.0", title: "Capital Rotation Through Hyper-Liquidity Cycle", summary: "Reframed as two-speed market. Energy + AI explicitly linked. Cash treated as strategic, not residual.", regimes: ["+commodity_expansion", "+monetary_debasement_hard_asset"] },
    { date: "2026-03-08", from: "v2.3", to: "v2.4", title: "Defense as early signal", summary: "Defense recognized as leading rather than late-cycle on procurement tape.", regimes: [] },
    { date: "2026-01-30", from: "v2.2", to: "v2.3", title: "Liquidity-led mechanics formalized", summary: "Distinguished short-term liquidity layer from medium-term structural layer.", regimes: ["+dovish_liquidity_wave"] },
  ],

  // ---------- /dev surfaces ----------
  brainActivity: [
    { ts: "08:14:22", agent: "score_composer",       model: "gemini-2.5-pro",   latencyMs: 690,  tokensIn: 2840, tokensOut: 412, costUsd: 0.011, ok: true },
    { ts: "08:14:11", agent: "narrative_synthesizer", model: "claude-haiku-4.5", latencyMs: 1240, tokensIn: 6210, tokensOut: 924, costUsd: 0.012, ok: true },
    { ts: "08:13:58", agent: "regime_classifier",    model: "gemini-2.5-pro",   latencyMs: 820,  tokensIn: 4180, tokensOut: 188, costUsd: 0.018, ok: true },
    { ts: "08:13:42", agent: "chart_vision",         model: "gemini-2.5-pro",   latencyMs: 1980, tokensIn: 1890, tokensOut: 311, costUsd: 0.024, ok: true },
    { ts: "08:13:14", agent: "rationale_writer",     model: "claude-haiku-4.5", latencyMs: 540,  tokensIn: 1820, tokensOut: 396, costUsd: 0.005, ok: true },
    { ts: "08:12:52", agent: "transcription",        model: "gemini-2.5-flash", latencyMs: 4120, tokensIn:    0, tokensOut:   0, costUsd: 0.041, ok: true },
    { ts: "08:11:46", agent: "score_composer",       model: "gemini-2.5-pro",   latencyMs: 720,  tokensIn: 2790, tokensOut: 401, costUsd: 0.011, ok: true },
    { ts: "08:09:32", agent: "score_composer",       model: "gemini-2.5-pro",   latencyMs: 740,  tokensIn: 2810, tokensOut: 408, costUsd: 0.011, ok: true },
    { ts: "08:08:11", agent: "vision",               model: "gemini-2.5-pro",   latencyMs: 2400, tokensIn: 1740, tokensOut: 240, costUsd: 0.022, ok: false },
    { ts: "08:07:09", agent: "narrative_synthesizer", model: "claude-haiku-4.5", latencyMs: 1180, tokensIn: 5980, tokensOut: 880, costUsd: 0.011, ok: true },
  ],

  sourceHealth: [
    { name: "Doomberg",            kind: "Substack",      lastFetch: "08:02", freshness: 1.00, weight: 0.92, attrib30d: +6840, tags: ["energy"] },
    { name: "Capitalist Exploits", kind: "Substack",      lastFetch: "07:56", freshness: 0.96, weight: 0.74, attrib30d: +1810, tags: ["thematic"] },
    { name: "Bianco Research",     kind: "Substack",      lastFetch: "06:14", freshness: 0.71, weight: 0.68, attrib30d: +890,  tags: ["macro"] },
    { name: "Energy Capitalist",   kind: "Newsletter",    lastFetch: "08:11", freshness: 1.00, weight: 0.81, attrib30d: +3120, tags: ["energy"] },
    { name: "FRED · DGS10",        kind: "Data feed",     lastFetch: "08:14", freshness: 1.00, weight: 0.78, attrib30d: +2470, tags: ["macro"] },
    { name: "FRED · CPI exp.",     kind: "Data feed",     lastFetch: "08:14", freshness: 1.00, weight: 0.78, attrib30d: +2470, tags: ["macro"] },
    { name: "Forward Guidance",    kind: "Podcast (RSS)", lastFetch: "Yest", freshness: 0.42, weight: 0.61, attrib30d: +210,  tags: ["macro","podcast"] },
    { name: "Macro Voices",        kind: "Podcast (RSS)", lastFetch: "2d",   freshness: 0.18, weight: 0.55, attrib30d: -120,  tags: ["macro","podcast"] },
    { name: "ZeroHedge",           kind: "RSS",           lastFetch: "08:10", freshness: 0.99, weight: 0.28, attrib30d: -640,  tags: ["news"] },
    { name: "@woodway",            kind: "Twitter",       lastFetch: "08:13", freshness: 1.00, weight: 0.42, attrib30d: -380,  tags: ["positioning"] },
  ],

  costTracker: {
    today: 4.82, week: 28.16, month: 112.40,
    capDaily: 25, capMonthly: 600,
    byAgent: [
      { agent: "narrative_synthesizer", usd: 1.84 },
      { agent: "regime_classifier",     usd: 1.12 },
      { agent: "score_composer",        usd: 0.78 },
      { agent: "chart_vision",          usd: 0.61 },
      { agent: "transcription",         usd: 0.32 },
      { agent: "rationale_writer",      usd: 0.15 },
    ],
    byBackend: [
      { backend: "Gemini 2.5 Pro",     usd: 3.21 },
      { backend: "Claude Haiku 4.5",   usd: 1.29 },
      { backend: "Gemini 2.5 Flash",   usd: 0.32 },
    ],
    spike: false,
  },

  mgmt: {
    todos: [
      { status: "in_flight",    title: "Wire /journal endpoints in macro-analyzer API",         owner: "Application Agent", age: "2h" },
      { status: "in_flight",    title: "Add chart_vision retry on rate-limit",                  owner: "Application Agent", age: "5h" },
      { status: "blocked",      title: "Re-tune setup score weights against last 30 closed",   owner: "Framework Agent",   age: "1d" },
      { status: "todo",         title: "Add Glassnode connector for stablecoin liquidity",      owner: "Application Agent", age: "—" },
      { status: "todo",         title: "Quarterly thesis review · v3.1 candidate",              owner: "Thesis Agent",      age: "—" },
      { status: "done",         title: "Migrate to Gemini 2.5 Pro for regime_classifier",       owner: "Application Agent", age: "12h" },
    ],
    decisions: [
      { date: "2026-05-08", title: "Manual-execution-first stays through Phase 8", who: "Operator" },
      { date: "2026-05-06", title: "Score Δ visualized over absolute score on hero cards", who: "Operator + Application Agent" },
      { date: "2026-05-02", title: "Doomberg weight raised to 0.92 after attribution review", who: "Framework Agent" },
    ],
    commits: [
      { hash: "5533b3a", author: "thommi", msg: "dashboard: refine positioning shell (gradient strip, hero signals)" },
      { hash: "a14e09c", author: "thommi", msg: "brain: gemini 2.5 pro for regime_classifier" },
      { hash: "7e2b1d4", author: "thommi", msg: "ingestion: per-source freshness weighting" },
      { hash: "9c01a8f", author: "thommi", msg: "framework: tighten failed-breakout penalty (-15→-18)" },
      { hash: "31b770a", author: "thommi", msg: "db: add missed_trades table" },
    ],
  },

  integration: {
    tactical: { connected: true, lastPoll: "08:14:30", contractVersion: "v3", schemaDrift: false, mode: "manual" },
  },
};
