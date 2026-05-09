# Macro Trading Analyzer Input - System Backbone

## Purpose

This document is the foundational logic layer for the Macro Trading Analyzer. It is designed to function as:

- A market reasoning framework
- A trading decision engine
- A relational knowledge base
- A setup scoring model
- A trade journaling schema
- A macro and technical analysis ontology
- A future RAG or vector database source
- A rules engine for discretionary and systematic trade review

The system should evaluate opportunities by moving from broad context to specific execution:

1. Macro regime
2. Liquidity environment
3. Asset class leadership
4. Sector or theme strength
5. Individual asset structure
6. Volume and flow confirmation
7. Setup classification
8. Entry quality
9. Risk and invalidation
10. Position sizing
11. Psychological execution quality
12. Post-trade review

## Core System Principle

The analyzer should never treat a trade as a standalone chart pattern. Every setup exists inside a larger stack of conditions:

- Macro environment
- Liquidity cycle
- Market regime
- Sector rotation
- Asset-specific narrative
- Technical structure
- Volume behavior
- Sentiment and positioning
- Risk/reward
- Trader psychology

A technically attractive setup inside a hostile macro regime should be downgraded. A macro-attractive thesis with poor technical timing should also be downgraded. The highest-quality setups occur when macro, liquidity, sector strength, technical structure, volume, and defined risk align.

---

# 1. Core Market Philosophy

## Operating Principles

- Markets are probabilistic systems, not prediction engines
- The goal is not to be right on every trade, but to consistently identify asymmetric opportunities
- Macro defines the environment
- Liquidity defines the fuel
- Sector rotation defines where capital is moving
- Technical analysis defines timing
- Volume confirms intent
- Risk management determines survival
- Psychology determines execution consistency
- Journaling converts experience into edge

## Foundational Beliefs

### Liquidity Drives Markets

When liquidity expands, risk assets generally become easier to own. When liquidity contracts, breakouts fail more often, volatility rises, and capital preservation becomes more important.

### Macro Regime Determines Setup Quality

The same technical pattern has a different expected value depending on the macro backdrop. A breakout in a risk-on liquidity expansion has a higher probability of continuation than a breakout during tightening financial conditions.

### Price Structure Reveals Behavior

Market structure shows whether buyers or sellers are in control. Higher highs and higher lows indicate accumulation and trend strength. Lower highs and lower lows indicate distribution and weakness.

### Volume Confirms Intent

Price movement without volume is less trustworthy. Volume expansion near key levels suggests institutional interest, forced positioning, or emotional capitulation.

### Risk Comes Before Reward

A setup without a clear invalidation level is incomplete. The analyzer should penalize any trade where downside cannot be clearly defined.

### Macro Thesis Is Not Trade Timing

A strong long-term thesis does not justify a bad entry. Macro creates the watchlist. Technicals create the trade.

## Analyzer Rules

```json
{
  "core_rules": [
    {
      "rule_id": "macro_first_execution_second",
      "description": "Use macro regime to define directional bias and technical analysis to define entries and exits",
      "priority": "critical"
    },
    {
      "rule_id": "confirmation_stacking_required",
      "description": "Higher conviction requires alignment across macro, technical, volume, sector, and risk/reward signals",
      "priority": "critical"
    },
    {
      "rule_id": "defined_risk_required",
      "description": "No setup should receive a high score without a clear invalidation level",
      "priority": "critical"
    },
    {
      "rule_id": "macro_not_timing",
      "description": "A strong macro thesis cannot override poor technical entry quality",
      "priority": "high"
    },
    {
      "rule_id": "conservative_bias_default",
      "description": "When signals are mixed, downgrade the setup rather than assuming bullish resolution",
      "priority": "high"
    }
  ]
}
```

---

# 2. Macro Regime Framework

## Macro Inputs

The analyzer should classify the market using the following macro inputs:

- Liquidity trend
- Federal Reserve policy direction
- Interest rate trend
- Real rate trend
- Dollar trend
- Inflation trend
- Inflation expectations
- Credit stress
- Volatility trend
- Equity breadth
- Commodity leadership
- Fiscal stress
- Geopolitical stress
- Earnings cycle
- Capital rotation
- Risk appetite

## Macro Regime Categories

### 2.1 Risk-On Expansion

Risk-on expansion occurs when liquidity is improving, financial conditions are supportive, volatility is contained, breadth is expanding, and investors are willing to own growth, cyclicals, crypto, and higher-beta assets.

Conditions:

- Liquidity improving
- Dollar stable or weakening
- Rates stable or declining
- Credit stress low
- Volatility contained
- Equity breadth expanding
- Growth or cyclicals outperforming
- Crypto participation improving
- Breakouts holding more consistently

Trading implications:

- Favor long setups
- Favor breakout continuation
- Increase willingness to hold winners
- Allow larger position sizes when technicals confirm
- Focus on relative strength leaders
- Pullbacks into support are often buyable

```json
{
  "regime": "risk_on_expansion",
  "bias": "bullish",
  "risk_posture": "constructive",
  "preferred_setups": [
    "breakout_continuation",
    "pullback_to_support",
    "high_tight_flag",
    "sector_rotation_leader",
    "relative_strength_continuation"
  ],
  "position_sizing_modifier": 1.25,
  "setup_score_modifier": 10
}
```

### 2.2 Risk-Off Contraction

Risk-off contraction occurs when liquidity tightens, the dollar strengthens, rates rise or remain restrictive, credit stress increases, volatility expands, and market breadth deteriorates.

Conditions:

- Liquidity tightening
- Dollar strengthening
- Rates rising or restrictive
- Credit spreads widening
- Volatility rising
- Breadth weakening
- Defensive assets outperforming
- Breakouts failing frequently

Trading implications:

- Reduce exposure
- Favor cash or defensive positions
- Lower trust in breakouts
- Require stronger confirmation
- Use smaller size
- Prioritize short-duration trades
- Avoid weak or illiquid assets

```json
{
  "regime": "risk_off_contraction",
  "bias": "defensive",
  "risk_posture": "capital_preservation",
  "preferred_setups": [
    "failed_breakout_short",
    "defensive_rotation",
    "mean_reversion_after_capitulation",
    "cash_preservation"
  ],
  "position_sizing_modifier": 0.5,
  "setup_score_modifier": -15
}
```

### 2.3 Commodity-Led Inflation Regime

Commodity-led inflation occurs when real assets outperform financial assets, inflation expectations rise, energy and metals gain leadership, and resource scarcity becomes a dominant market narrative.

Conditions:

- Commodities outperform equities
- Energy strong
- Metals strong
- Inflation expectations rising
- Resource equities outperforming
- Dollar may be mixed
- Real asset narratives strengthening

Trading implications:

- Favor uranium, energy, gold, silver, miners, and commodity equities
- Prioritize relative strength within commodity sectors
- Watch for inflation-sensitive rotations
- Avoid assuming broad equity strength applies equally across sectors

```json
{
  "regime": "commodity_led_inflation",
  "bias": "real_asset_bullish",
  "risk_posture": "selective_aggression",
  "preferred_setups": [
    "commodity_breakout",
    "miner_relative_strength",
    "uranium_accumulation",
    "precious_metals_continuation"
  ],
  "position_sizing_modifier": 1.1,
  "setup_score_modifier": 8
}
```

### 2.4 Monetary Debasement / Hard Asset Regime

This regime occurs when fiscal stress, debt concerns, currency debasement fears, or sovereign credibility concerns drive capital toward scarce assets.

Conditions:

- Fiscal deficits rising
- Debt sustainability concerns increasing
- Real yields falling or unstable
- Gold outperforming
- Bitcoin or scarce digital assets strengthening
- Dollar confidence weakening
- Inflation or currency narrative rising

Trading implications:

- Favor gold, silver, Bitcoin, uranium, and scarce hard assets
- Watch for long-duration accumulation structures
- Give more weight to secular thesis alignment
- Still require technical timing for entries

```json
{
  "regime": "monetary_debasement_hard_asset",
  "bias": "scarcity_asset_bullish",
  "risk_posture": "theme_accumulation",
  "preferred_setups": [
    "hard_asset_breakout",
    "long_base_accumulation",
    "scarcity_asset_pullback",
    "relative_strength_vs_fiat"
  ],
  "position_sizing_modifier": 1.0,
  "setup_score_modifier": 6
}
```

### 2.5 Transitional / Choppy Regime

Transitional chop occurs when macro signals conflict, leadership rotates quickly, breakouts fail, volatility is unstable, and conviction is difficult to sustain.

Conditions:

- Mixed liquidity signals
- Mixed dollar and rate signals
- Breadth inconsistent
- Sector leadership unstable
- Breakout failure rate elevated
- News-driven reversals frequent

Trading implications:

- Reduce position size
- Favor patience
- Use tighter invalidation
- Avoid overtrading
- Wait for clean regime confirmation
- Trade smaller and faster if trading at all

```json
{
  "regime": "transitional_chop",
  "bias": "neutral_to_cautious",
  "risk_posture": "reduced_activity",
  "preferred_setups": [
    "range_trade",
    "support_retest",
    "small_probe",
    "watchlist_building"
  ],
  "position_sizing_modifier": 0.65,
  "setup_score_modifier": -8
}
```

---

# 3. Liquidity and Cycle Model

## Liquidity Inputs

- Central bank policy direction
- Balance sheet expansion or contraction
- Real yields
- Dollar liquidity
- Credit spreads
- Treasury volatility
- Banking stress
- Stablecoin liquidity for crypto
- Market breadth
- Volatility compression or expansion

## Liquidity States

### Expanding Liquidity

- Supports risk assets
- Increases probability of breakout continuation
- Supports crypto and growth assets
- Encourages higher-beta exposure

### Neutral Liquidity

- Requires more technical confirmation
- Sector selection matters more
- Avoid broad assumptions

### Contracting Liquidity

- Penalizes speculative assets
- Raises probability of failed breakouts
- Supports cash and defensive positioning
- Requires smaller sizing

```json
{
  "liquidity_model": {
    "expanding": {
      "risk_asset_bias": "positive",
      "breakout_confidence_modifier": 8,
      "position_size_modifier": 1.2
    },
    "neutral": {
      "risk_asset_bias": "selective",
      "breakout_confidence_modifier": 0,
      "position_size_modifier": 1.0
    },
    "contracting": {
      "risk_asset_bias": "negative",
      "breakout_confidence_modifier": -12,
      "position_size_modifier": 0.6
    }
  }
}
```

---

# 4. Trading Philosophy

## Trading Style

The user follows a hybrid style:

- Swing trading
- Position trading
- Macro thematic investing
- Momentum continuation
- Breakout and retest execution
- Commodity and hard asset thematic exposure
- Selective crypto speculation when liquidity and narrative align

## Trade Selection Principles

A trade should generally require:

- Macro regime support
- Sector or theme strength
- Clear technical structure
- Volume confirmation
- Defined invalidation
- Favorable risk/reward
- No major psychological conflict

## What Makes a Trade Attractive

- Asset is aligned with the current macro regime
- Asset belongs to a leading or strengthening sector
- Price is breaking out from a meaningful base or reclaiming a key level
- Volume expands during the move
- Retest holds above prior resistance or support
- Risk can be defined tightly
- Upside target is materially larger than downside
- Broader market conditions support follow-through

## What Makes a Trade Unattractive

- Asset is extended far above support
- Entry is based on fear of missing out
- Volume does not confirm price movement
- Breakout has already failed
- Macro backdrop is hostile
- Invalidation is unclear
- Risk/reward is poor
- Position sizing is driven by emotion

---

# 5. Technical Analysis Framework

## 5.1 Market Structure

### Bullish Structure

- Higher highs
- Higher lows
- Prior resistance becomes support
- Pullbacks are shallow
- Breakouts hold
- Volume expands on upward moves
- Volume contracts on pullbacks

### Bearish Structure

- Lower highs
- Lower lows
- Prior support becomes resistance
- Rallies are sold
- Breakdowns hold
- Volume expands on downward moves

### Neutral Structure

- Range-bound price action
- Failed breakouts and breakdowns
- No consistent trend
- Mixed volume signals
- Choppy moving average behavior

```json
{
  "market_structure_signals": [
    {
      "signal": "bullish_structure",
      "conditions": ["higher_highs == true", "higher_lows == true", "support_retests_hold == true"],
      "score_modifier": 12
    },
    {
      "signal": "bearish_structure",
      "conditions": ["lower_highs == true", "lower_lows == true", "resistance_retests_fail == true"],
      "score_modifier": -12
    },
    {
      "signal": "neutral_structure",
      "conditions": ["range_bound == true", "trend_unclear == true"],
      "score_modifier": -5
    }
  ]
}
```

## 5.2 Key Levels

The analyzer should track:

- Prior highs
- Prior lows
- Range highs
- Range lows
- Breakout levels
- Retest zones
- Volume shelves
- VWAP
- Anchored VWAP
- 20-day moving average
- 50-day moving average
- 200-day moving average
- Psychological round numbers
- Gap levels
- Order block zones

## Level Quality Ranking

High-quality levels:

- Tested multiple times
- Aligned with volume shelf
- Aligned with moving average
- Aligned with prior breakout or breakdown
- Causes visible reaction
- Sits near macro or sector inflection

Low-quality levels:

- Random intraday pivots without volume
- Levels far away from current structure
- Levels with no visible reaction history
- Levels that have already failed repeatedly

## 5.3 Breakout Logic

### High-Quality Breakout

- Breaks above meaningful resistance
- Closes above breakout level
- Volume expands above average
- Sector or market confirms
- Retest holds or price follows through quickly
- Not extremely extended from moving averages

### Low-Quality Breakout

- Breaks resistance intraday but closes below
- Weak or declining volume
- Broader market weak
- Sector not confirming
- Asset already extended
- Breakout occurs into major overhead supply

```json
{
  "breakout_model": {
    "high_quality_breakout": {
      "conditions": [
        "resistance_break == true",
        "close_above_level == true",
        "relative_volume >= 1.5",
        "sector_confirmation == true",
        "extension_from_support <= acceptable_threshold"
      ],
      "score_modifier": 18
    },
    "low_quality_breakout": {
      "conditions": [
        "resistance_break == true",
        "close_above_level == false OR relative_volume < 1.0 OR market_confirmation == false"
      ],
      "score_modifier": -10
    },
    "failed_breakout": {
      "conditions": [
        "breakout_occurred == true",
        "close_back_below_breakout_level == true",
        "follow_through_failed == true"
      ],
      "score_modifier": -18,
      "warning": "potential_trapped_buyers"
    }
  }
}
```

## 5.4 Pullback and Retest Logic

### High-Quality Pullback

- Occurs within an uptrend
- Pulls back to prior breakout level, moving average, VWAP, or order block
- Volume contracts during pullback
- Buyers step in at logical level
- Risk is clearly defined

### Low-Quality Pullback

- Pullback breaks key support
- Volume increases on selling
- Broader market deteriorates
- Asset loses relative strength
- No clear level holds

```json
{
  "pullback_model": {
    "constructive_pullback": {
      "conditions": [
        "primary_trend == up",
        "pullback_to_key_level == true",
        "selling_volume_contracts == true",
        "support_holds == true"
      ],
      "score_modifier": 15
    },
    "distribution_pullback": {
      "conditions": [
        "support_breaks == true",
        "selling_volume_expands == true",
        "relative_strength_deteriorates == true"
      ],
      "score_modifier": -15
    }
  }
}
```

---

# 6. Volume and Flow Logic

## Volume Principles

- Volume confirms intent
- Rising price with rising volume supports accumulation
- Rising price with weak volume is less reliable
- Falling price with rising volume may indicate distribution or capitulation depending on context
- Falling price with declining volume may indicate normal pullback
- Volume spikes near key levels often mark important inflection points

## Volume Signal Types

### Accumulation

- Price holds range despite high volume
- Pullbacks are absorbed
- Higher lows form
- Breakout eventually occurs with volume expansion

### Distribution

- Price fails to advance despite high volume
- Rallies are sold
- Lower highs form
- Breakdown occurs with volume expansion

### Capitulation

- Sharp decline
- Large volume spike
- Emotional selling
- Potential reversal if price reclaims key level

### Exhaustion

- Price extends rapidly
- Volume spikes late in move
- Momentum divergence appears
- Follow-through weakens

```json
{
  "volume_flow_model": {
    "accumulation": {
      "conditions": [
        "range_holds == true",
        "high_volume_absorption == true",
        "higher_lows == true"
      ],
      "score_modifier": 12
    },
    "distribution": {
      "conditions": [
        "price_stalls_on_high_volume == true",
        "lower_highs == true",
        "support_pressure == rising"
      ],
      "score_modifier": -12
    },
    "capitulation_reversal_candidate": {
      "conditions": [
        "sharp_decline == true",
        "volume_spike == true",
        "key_level_reclaim == true"
      ],
      "score_modifier": 8
    },
    "exhaustion_warning": {
      "conditions": [
        "extended_move == true",
        "late_volume_spike == true",
        "momentum_divergence == true"
      ],
      "score_modifier": -10
    }
  }
}
```

---

# 7. Order Block and Institutional Behavior Logic

## Order Block Concept

Order blocks represent zones where meaningful buying or selling likely occurred before a strong directional move. The analyzer should treat them as potential areas of future reaction, support, resistance, accumulation, or distribution.

## Bullish Order Block

Conditions:

- Down candle or consolidation before strong upward move
- Followed by displacement higher
- Volume expands during or after the move
- Zone later acts as support
- Retest holds with reduced selling pressure

## Bearish Order Block

Conditions:

- Up candle or consolidation before strong downward move
- Followed by displacement lower
- Volume expands during or after the move
- Zone later acts as resistance
- Retest fails with selling pressure

```json
{
  "order_block_model": {
    "bullish_order_block": {
      "conditions": [
        "pre_move_consolidation == true",
        "displacement_up == true",
        "volume_expansion == true",
        "retest_holds == true"
      ],
      "score_modifier": 14
    },
    "bearish_order_block": {
      "conditions": [
        "pre_move_consolidation == true",
        "displacement_down == true",
        "volume_expansion == true",
        "retest_rejects == true"
      ],
      "score_modifier": -14
    },
    "invalidated_order_block": {
      "conditions": [
        "price_closes_through_zone == true",
        "retest_fails_to_hold == true"
      ],
      "score_modifier": -10
    }
  }
}
```

---

# 8. Setup Taxonomy

## 8.1 Breakout Continuation

Price breaks above meaningful resistance with volume confirmation and supportive market context.

Requirements:

- Resistance break
- Close above level
- Relative volume above average
- Market or sector support
- Defined invalidation below breakout level

Best environment:

- Risk-on expansion
- Commodity-led regime for real assets
- Sector leadership phase

## 8.2 Breakout Retest

Price breaks out, pulls back to retest the breakout level, and holds support.

Requirements:

- Prior breakout
- Pullback to breakout level
- Support holds
- Selling volume contracts
- Buyers return

Best environment:

- Risk-on expansion
- Strong sector trend
- Early to mid trend phase

## 8.3 High Tight Flag / Momentum Consolidation

Strong upward move followed by tight consolidation near highs, suggesting limited selling pressure.

Requirements:

- Strong impulse move
- Tight range near highs
- Volume contracts during consolidation
- Break above flag with volume

Best environment:

- Strong risk-on regime
- Narrative-driven sector
- High relative strength assets

## 8.4 Pullback to Support

Asset in uptrend pulls back to a logical support zone and shows signs of demand.

Requirements:

- Primary trend up
- Pullback to key level
- Volume contraction on pullback
- Support reaction
- Clear invalidation

## 8.5 Failed Breakout / Trap

Price breaks above resistance but fails to hold, trapping buyers and increasing downside risk.

Requirements:

- Breakout attempt
- Close back below level
- Weak follow-through
- Volume spike or reversal candle

Trading implication:

- Avoid long setup
- Consider reversal risk
- Downgrade related setups

## 8.6 Capitulation Reversal

Sharp selloff with volume spike followed by reclaim of key level.

Requirements:

- Extreme selloff
- Volume spike
- Reclaim of level
- Stabilization
- Broader context not structurally broken

Risk note:

- Requires careful sizing because volatility remains elevated

## 8.7 Long Base Accumulation

Asset builds a multi-week or multi-month base with repeated support holds and improving volume behavior.

Requirements:

- Long consolidation
- Support repeatedly defended
- Selling pressure decreases
- Relative strength improves
- Breakout level clearly defined

---

# 9. Risk Management Framework

## Core Rules

- Define invalidation before entry
- Never size aggressively without confirmation stacking
- Reduce size when macro regime is unclear
- Avoid adding to losing trades unless part of a pre-defined plan
- Do not let macro conviction override technical failure
- Failed breakout equals immediate reassessment
- Wider stop requires smaller size
- Higher volatility requires smaller size
- Concentrated positions require higher confidence

## Position Sizing Variables

- Setup score
- Macro regime
- Liquidity state
- Technical confirmation
- Volume confirmation
- Distance to invalidation
- Volatility
- Liquidity of asset
- Portfolio concentration
- Time horizon
- Psychological clarity

```json
{
  "position_sizing_framework": {
    "tier_1_high_conviction": {
      "score_range": "85_to_100",
      "conditions": [
        "macro_alignment == strong",
        "technical_structure == strong",
        "volume_confirmation == strong",
        "risk_reward >= 3",
        "invalidation_defined == true"
      ],
      "sizing": "largest_allowed_within_portfolio_limits"
    },
    "tier_2_quality_setup": {
      "score_range": "70_to_84",
      "conditions": [
        "setup_quality == good",
        "some_confirmation_missing == true"
      ],
      "sizing": "standard_or_staged_entry"
    },
    "tier_3_probe": {
      "score_range": "55_to_69",
      "conditions": [
        "mixed_signals == true",
        "watchlist_quality == good_but_unconfirmed"
      ],
      "sizing": "small_probe_only"
    },
    "tier_4_avoid": {
      "score_range": "below_55",
      "conditions": [
        "setup_quality == weak OR invalidation_defined == false"
      ],
      "sizing": "avoid"
    }
  }
}
```

## Conservative Bias Adjustments

```json
{
  "conservative_bias_adjustments": [
    { "condition": "macro_regime == unclear", "score_adjustment": -10 },
    { "condition": "liquidity_state == contracting", "score_adjustment": -12 },
    { "condition": "volume_confirmation == weak", "score_adjustment": -10 },
    { "condition": "invalidation_defined == false", "score_adjustment": -20 },
    { "condition": "asset_extended_from_support == true", "score_adjustment": -10 },
    { "condition": "failed_breakout_recent == true", "score_adjustment": -15 },
    { "condition": "risk_reward < 2", "score_adjustment": -12 }
  ]
}
```

---

# 10. Composite Trade Scoring Model

## Base Score Components

```json
{
  "trade_score_model": {
    "macro_alignment": 20,
    "liquidity_alignment": 15,
    "sector_theme_strength": 10,
    "technical_structure": 20,
    "volume_flow_confirmation": 15,
    "risk_reward_quality": 10,
    "relative_strength": 5,
    "psychological_execution_quality": 5,
    "max_score": 100
  }
}
```

## Score Interpretation

- 90 to 100: Elite setup, rare, eligible for strong sizing if portfolio risk allows
- 80 to 89: High-quality setup, eligible for larger-than-standard sizing
- 70 to 79: Good setup, standard sizing or staged entry
- 60 to 69: Developing setup, small probe or wait for confirmation
- 50 to 59: Weak or incomplete setup, watch only
- Below 50: Avoid

## Score Calculation Flow

```json
{
  "score_calculation_flow": [
    "calculate_macro_alignment_score",
    "calculate_liquidity_score",
    "calculate_sector_theme_score",
    "calculate_technical_structure_score",
    "calculate_volume_flow_score",
    "calculate_risk_reward_score",
    "calculate_relative_strength_score",
    "calculate_psychology_score",
    "apply_regime_modifier",
    "apply_conservative_bias_adjustments",
    "assign_trade_grade",
    "assign_position_size_tier"
  ]
}
```

---

# 11. Asset and Sector Theme Logic

## Uranium Theme

Core thesis:

- Nuclear renaissance
- Energy security demand
- Structural supply constraints
- Long-duration commodity cycle
- Potential institutional underexposure
- Commodity and real asset tailwinds

Bullish conditions:

- Uranium equities outperforming
- URNM breaking out or holding trend
- DNN and related miners confirming
- Volume expands on sector strength
- Commodity-led or hard asset regime active
- Energy security narrative strengthening

Risk conditions:

- Uranium equities diverge negatively
- Breakouts fail
- Commodity regime weakens
- Liquidity contracts severely
- Speculative miners lose leadership

## Precious Metals Theme

Core thesis:

- Monetary debasement
- Fiscal stress
- Inflation hedge
- Geopolitical hedge
- Real asset rotation
- Potential weakness in fiat confidence

Bullish conditions:

- Dollar weakening
- Real rates falling
- Gold and silver showing relative strength
- Miners confirming
- Fiscal or geopolitical stress rising
- Breakouts holding above key levels

Risk conditions:

- Dollar strengthens sharply
- Real rates rise
- Metals fail at resistance
- Miners diverge negatively
- Breakouts repeatedly fail

## Crypto / Reflexive Risk Asset Theme

Core thesis:

- Liquidity-driven upside
- Narrative reflexivity
- Attention and community as market forces
- High volatility and asymmetric upside
- Strong requirement for risk control

Bullish conditions:

- Liquidity improving
- Risk appetite rising
- Crypto market breadth improving
- Volume accelerating
- Narrative strength increasing
- Holder distribution improving

Risk conditions:

- Liquidity contracting
- Narrative fading
- Holder concentration high
- Thin exit liquidity
- Failed breakouts
- Excessive euphoria

---

# 12. Trading Psychology Framework

## Core Psychological Rules

- Avoid emotional chasing after large moves
- Do not increase size to compensate for missed trades
- Do not treat hindsight clarity as proof the setup was obvious in real time
- Process quality matters more than outcome quality
- A missed trade is only a mistake if it fit the playbook and had a clear trigger
- A losing trade is acceptable if the setup was valid and risk was defined
- A winning trade is not automatically good if the process was poor

## Ideal Trader State

- Patient during unclear regimes
- Aggressive only during high-confirmation setups
- Detached from individual trade outcomes
- Prepared with key levels before price reaches them
- Focused on repeatability
- Willing to miss trades that do not fit the system

## Failure Modes

- Chasing extended moves
- Oversizing based on conviction alone
- Ignoring weak volume
- Ignoring failed breakout signals
- Confusing thesis with timing
- Entering without invalidation
- Hesitating on valid setups due to lack of preparation

```json
{
  "psychology_model": {
    "positive_execution_state": {
      "conditions": [
        "entry_planned_in_advance == true",
        "invalidation_defined == true",
        "position_size_predefined == true",
        "setup_matches_playbook == true"
      ],
      "score_modifier": 5
    },
    "negative_execution_state": {
      "conditions": [
        "fomo_entry == true OR revenge_sizing == true OR invalidation_defined == false"
      ],
      "score_modifier": -15
    }
  }
}
```

---

# 13. Trade Journal Database Schema

## Table: assets

```json
{
  "asset_id": "string",
  "ticker": "string",
  "asset_name": "string",
  "asset_class": "equity | etf | commodity | crypto | index | currency",
  "sector": "string",
  "theme": "string",
  "liquidity_profile": "high | medium | low",
  "volatility_profile": "high | medium | low"
}
```

## Table: macro_regimes

```json
{
  "regime_id": "string",
  "date": "date",
  "regime_type": "risk_on_expansion | risk_off_contraction | commodity_led_inflation | monetary_debasement_hard_asset | transitional_chop",
  "liquidity_state": "expanding | neutral | contracting",
  "dollar_trend": "up | down | sideways",
  "rate_trend": "up | down | sideways",
  "volatility_state": "expanding | contracting | stable",
  "breadth_state": "expanding | deteriorating | mixed",
  "confidence_score": "integer_0_to_100"
}
```

## Table: technical_setups

```json
{
  "setup_id": "string",
  "asset_id": "string",
  "date": "date",
  "timeframe": "string",
  "setup_type": "breakout_continuation | breakout_retest | pullback_to_support | high_tight_flag | failed_breakout | capitulation_reversal | long_base_accumulation",
  "market_structure": "bullish | bearish | neutral",
  "key_level": "number",
  "entry_zone": "number_or_range",
  "invalidation_level": "number",
  "target_zone": "number_or_range",
  "risk_reward": "number",
  "technical_score": "integer_0_to_100"
}
```

## Table: volume_signals

```json
{
  "volume_signal_id": "string",
  "setup_id": "string",
  "relative_volume": "number",
  "volume_pattern": "accumulation | distribution | capitulation | exhaustion | neutral",
  "volume_confirmation": "strong | moderate | weak",
  "volume_score": "integer_0_to_100"
}
```

## Table: trade_scores

```json
{
  "score_id": "string",
  "setup_id": "string",
  "macro_alignment_score": "integer_0_to_20",
  "liquidity_score": "integer_0_to_15",
  "sector_theme_score": "integer_0_to_10",
  "technical_structure_score": "integer_0_to_20",
  "volume_flow_score": "integer_0_to_15",
  "risk_reward_score": "integer_0_to_10",
  "relative_strength_score": "integer_0_to_5",
  "psychology_score": "integer_0_to_5",
  "raw_total_score": "integer_0_to_100",
  "adjusted_total_score": "integer_0_to_100",
  "grade": "A_plus | A | B | C | D | avoid",
  "position_size_tier": "tier_1 | tier_2 | tier_3 | avoid"
}
```

## Table: trades

```json
{
  "trade_id": "string",
  "setup_id": "string",
  "asset_id": "string",
  "entry_date": "date",
  "entry_price": "number",
  "exit_date": "date_or_null",
  "exit_price": "number_or_null",
  "position_size": "number",
  "stop_loss": "number",
  "target_price": "number",
  "status": "planned | active | closed | missed | avoided",
  "pnl": "number_or_null",
  "pnl_percent": "number_or_null",
  "execution_notes": "string"
}
```

## Table: missed_trades

```json
{
  "missed_trade_id": "string",
  "setup_id": "string",
  "reason_missed": "not_prepared | hesitation | no_alert | unclear_trigger | emotional_bias | outside_playbook",
  "was_valid_in_real_time": "boolean",
  "hindsight_bias_risk": "low | medium | high",
  "lesson": "string",
  "rule_adjustment": "string"
}
```

---

# 14. Relational Knowledge Graph

```json
{
  "relationships": [
    { "from": "macro_regime", "to": "asset_class", "relationship": "influences" },
    { "from": "liquidity_state", "to": "risk_appetite", "relationship": "drives" },
    { "from": "sector_theme", "to": "asset", "relationship": "contains" },
    { "from": "asset", "to": "technical_setup", "relationship": "forms" },
    { "from": "technical_setup", "to": "volume_signal", "relationship": "confirmed_or_rejected_by" },
    { "from": "technical_setup", "to": "trade_score", "relationship": "evaluated_by" },
    { "from": "trade_score", "to": "position_size", "relationship": "determines" },
    { "from": "trade", "to": "journal_entry", "relationship": "reviewed_in" }
  ]
}
```

---

# 15. End-to-End Analyzer Workflow

```json
{
  "analyzer_workflow": [
    { "step": 1, "name": "classify_macro_regime", "output": "macro_regime_type" },
    { "step": 2, "name": "classify_liquidity_state", "output": "liquidity_state" },
    { "step": 3, "name": "identify_leading_asset_classes_and_sectors", "output": "theme_candidates" },
    { "step": 4, "name": "scan_assets_for_market_structure", "output": "technical_candidates" },
    { "step": 5, "name": "classify_setup_type", "output": "setup_taxonomy_label" },
    { "step": 6, "name": "evaluate_volume_and_flow", "output": "volume_confirmation_status" },
    { "step": 7, "name": "define_entry_invalidation_and_target", "output": "risk_reward_profile" },
    { "step": 8, "name": "calculate_trade_score", "output": "raw_score" },
    { "step": 9, "name": "apply_conservative_bias_adjustments", "output": "adjusted_score" },
    { "step": 10, "name": "assign_trade_grade_and_position_size", "output": "trade_decision" },
    { "step": 11, "name": "log_trade_or_missed_setup", "output": "journal_record" }
  ]
}
```

---

# 16. Final System Definition

```json
{
  "macro_trading_analyzer": {
    "system_goal": "Identify, score, and journal asymmetric trading opportunities by combining macro regime analysis, liquidity conditions, sector themes, technical structure, volume behavior, risk management, and psychology",
    "core_logic": "Macro defines environment, liquidity defines fuel, sector rotation defines opportunity, technicals define execution, volume confirms intent, risk defines size, psychology determines consistency",
    "decision_outputs": [
      "avoid",
      "watchlist",
      "small_probe",
      "standard_entry",
      "high_conviction_entry",
      "trim_or_exit",
      "journal_only"
    ],
    "excluded_domains": [
      "business_gtm",
      "sales_workflows",
      "lifestyle",
      "fitness",
      "vpn_opsec",
      "relocation"
    ]
  }
}
```
