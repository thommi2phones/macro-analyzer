// Glossary — one source of truth for what every number on the desk means.
//
// Loaded before components.jsx so every surface can annotate itself
// instead of the operator having to remember the model. Definitions here
// must track the code that produces the numbers:
//   composite + components → macro_brain/orchestrator/composer.py
//   weights                → macro_brain/types.py COMPONENT_WEIGHTS
//   grade / tier           → macro_brain/orchestrator/feature_vector.py
//   levels + R/R           → macro_positioning/scoring/levels.py

const MA_GLOSSARY = {
  // ── The headline number ──────────────────────────────────────
  composite: {
    short: "setup quality, not conviction",
    long:
      "0–100 setup quality: how well this asset fits the framework right " +
      "now. Nine weighted components (100 max) + the regime modifier − " +
      "conservative-bias penalties. It is NOT how strongly anyone believes " +
      "in the trade — that is the 0–5 conviction on each source call, which " +
      "reaches the composite only through Signal conviction (15 pts).",
  },

  tier: {
    short: "position size band, derived from the composite",
    long:
      "Position-size tier from the composite score: T1 ≥85, T2 ≥70, " +
      "T3 ≥55, avoid below 55. Any setup without a defined invalidation " +
      "(no stop) is avoid regardless of score.",
  },

  grade: {
    short: "letter grade of the composite",
    long: "A+ ≥90 · A ≥80 · B ≥70 · C ≥60 · D ≥50 · avoid below 50.",
  },

  // ── The nine components, keyed by the label the payload emits ──
  components: {
    "Macro alignment": {
      weight: 15,
      note: "Is this setup type one the active regime prefers? Scored as regime confidence when it matches, 30% of that when it doesn't — so a low-confidence regime read caps this component for everyone.",
    },
    "Liquidity": {
      weight: 15,
      note: "Financial conditions (FRED NFCI) — easing scores higher than tightening.",
    },
    "Sector strength": {
      weight: 5,
      note: "Mention momentum of the themes this asset belongs to.",
    },
    "Technical structure": {
      weight: 20,
      note: "Price structure: MA stack, higher lows/highs, breakouts. The heaviest single input.",
    },
    "Volume confirm": {
      weight: 15,
      note: "Is volume confirming the move, or is price drifting on nothing?",
    },
    "Risk / Reward": {
      weight: 10,
      note: "Planned reward ÷ risk from the agent's levels. 1:1 scores zero, 3:1 scores full.",
    },
    "Signal conviction": {
      weight: 15,
      note: "The tracked-voice tape — KOL calls, newsletters, insider filings, blended and weighted. The only route source conviction takes into the composite.",
    },
    "Relative strength": {
      weight: 3,
      note: "20-day return against this asset's benchmark.",
    },
    "Psychology · clean": {
      weight: 2,
      note: "Execution-quality checks — chasing, revenge trades, plan adherence.",
    },
  },

  // ── Adjustments applied after the weighted sum ───────────────
  modifiers: {
    short: "applied to the weighted total, then clamped to 0–100",
    long:
      "Regime modifier: risk-on expansion +10 · commodity-led inflation +8 · " +
      "monetary debasement +6 · transitional chop −8 · risk-off contraction " +
      "−15. Conservative-bias penalties subtract for unclear regime (−10), " +
      "contracting liquidity (−12), weak volume (−10), no invalidation " +
      "(−20), extension from support (−10), recent failed breakout (−15), " +
      "and R/R under 2 (−12).",
  },

  // ── Everything else the operator reads on a row or a card ────
  terms: {
    conviction:
      "0–5, set by the extractor: how strongly THIS source stated THIS call. Per-call, not per-asset — unrelated to the composite score.",
    rr: "Planned reward ÷ risk from the technical agent's entry, stop and target.",
    dScore: "Change in composite score versus the previous scoring pass.",
    tech: "Technical structure as a letter grade — its share of the 20 points available.",
    vol: "Volume confirmation as a letter grade — its share of the 15 points available.",
    regime: "Macro alignment bucket: fit ≥12 of 15 · mixed ≥6 · off below 6.",
    setup: "Which detector produced the levels — a structural read, or mechanical ATR rails when no structure was found.",
    levels: "Entry, stop and target from the technical agent. Stops clear the far edge of a real swing zone; targets are the next supply zone overhead. Where the chart has nothing overhead the target is an honest R-multiple projection, labelled 'open field'.",
    levelSource:
      "Chart structure = a swing zone, scored by touches, recency, volume and whether it flipped polarity. Trusted voices = levels your own followed sources drew, weighted by their backtested setup win rate. Open field = no zone in range, so the target is a 3R projection rather than an observed level.",
    refusedLevel:
      "A level that was considered and rejected — stale, on the wrong side of price, or implying risk outside the tradeable band. Shown rather than hidden so a missing human target is never silent.",
    side: "LONG/SHORT come from the tracked-voice bias; WATCH and AVOID come from the tier.",
    notRanking:
      "This component returned the same value for every asset in the pass, so it shifts every total equally and separates nothing. Checked per pass — the flag clears itself once the component starts discriminating.",
    setupType:
      "The setup named in the framework's own vocabulary (breakout continuation, support retest, uranium accumulation…), derived from the technical agent's detector plus the asset's theme and class. Macro alignment scores whether that name is one the active regime prefers.",
  },
};

// Small muted caption used under a score, a bar, or a section head.
function ScoreNote({ children, title }) {
  if (!children) return null;
  return (
    <div className="score-note" title={title || undefined}>{children}</div>
  );
}

// Component note lookup that degrades quietly if a label is renamed
// server-side — a missing definition renders nothing rather than "undefined".
function componentNote(label) {
  const d = MA_GLOSSARY.components[label];
  return d ? d.note : null;
}
