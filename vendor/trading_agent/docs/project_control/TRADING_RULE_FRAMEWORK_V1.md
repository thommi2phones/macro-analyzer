# Trading Rule Framework v1.0 (Logged for Later Implementation)

Date logged: 2026-03-02
Owner: Thomas
Status: Deferred (implementation later; UI likely via Replit or similar)

## Trade Universe

### Primary Focus
- Equities
- Crypto spot
- Options on underlying equities or crypto proxies

### Secondary / Limited
- Perpetual futures (optional, not primary focus)

### Default Holding Style
- Multi-day to multi-week swing trades
- Occasional long-term position trades when macro structure supports

## Setup Classification Engine

Each trade must be classified into a Setup Category.

### A) Pattern Structure Priority (Highest Weight)
- Flags
- Pennants
- Channels
- Trendline breaks
- Head and Shoulders
- Cup and Handle
- Range breakouts
- EMA structure trades

### B) Fibonacci Confluence
- White levels = standard significance
- Yellow levels = important
- Green levels = critical
- Confluence with breakout level increases setup score

### C) Indicator Alignment Layer
- MACD crossover direction
- RSI trend and crossover
- TTM Squeeze state and fire
- Indicator alignment increases probability weighting
- Indicators are confirmation tools, not primary triggers

Each trade receives a **Confluence Score** based on:
- Pattern
- Fib Alignment
- Indicator Alignment

This score influences position sizing class.

## Entry Rules

### Primary Entry Structure
- Breakout → Retest → Breakout Confirmation

### Execution Logic
1. Identify breakout level
2. Wait for retest of breakout level
3. Enter only after confirmed bounce continuation

Entry is **not** taken on first breakout impulse unless high conviction override condition exists.

### Chart Protocol
- White horizontal ray = entry level
- Orange horizontal rays = take profit levels
- Alert set at entry level on 1 hour timeframe

## Position Sizing Rules

### Standard Trade
- 3% to 5% capital allocation

### High Conviction Trade
- 7.5% to 8% capital allocation
- Must have high confluence score
- Rare occurrence

No overexposure stacking without independent structure validation.

## Exit Structure — Spot / Underlying

Default: Multi-target scaling model

Example 3 TP Structure:
- TP1: Sell 50% of position
- TP2: Sell 50% of remaining
- TP3: Close remainder or leave runner

### Runner Logic
Leave small residual size if:
- Volume expansion
- Structure remains intact
- Trend acceleration confirmed

TP levels are defined before entry.
No emotional override exits unless stop loss or structure invalidation.

## Exit Structure — Options

Scaling logic applies, adjusted for:
- Theta decay
- Delta sensitivity
- IV expansion/contraction
- Time to expiration

Standard:
- Scale profits at defined technical targets

Advanced Profit Management:
- If position reaches outsized gain: convert to vertical spread, roll up, hedge via spread structure, reduce exposure while maintaining upside

Options must be managed dynamically relative to Greeks and expiration.

## Stop Loss / Invalidation

Stop defined at:
- Structure break
- Pattern invalidation
- Loss of key fib level
- EMA failure depending on setup

No averaging down without new structure.

## Timeframe Structure

- Primary execution: 1H and 4H alignment
- Daily structure confirmation
- Swing duration: days to weeks
- Position trades: multi-week to multi-month
- Must align with higher timeframe structure

## Trade Process Flow

1. Scout assets (scan main assets for structural setups)
2. Map trade (draw pattern, plot fibs, mark entry/TPs)
3. Deploy alert (1H timeframe at entry)
4. Execute only on rule confirmation (no discretionary impulse trades)

## Data Capture Requirements

Each trade must auto-log:
- Asset
- Setup type
- Confluence score
- Entry price
- TP levels
- Stop level
- Position size %
- Trade duration
- Exit distribution
- Final R multiple
- Screenshot before entry
- Screenshot after completion

Agent must compare:
- Planned vs actual execution
- Rule adherence score
- Deviation flags

## Performance Analysis Layer

Track:
- Win rate per setup type
- Win rate per confluence tier
- R multiple distribution
- Profit factor
- Avg hold time
- Performance by position size class
- Indicator alignment performance impact

System must allow rule refinement based on statistical edge evolution.

## Discipline Rules

- No trade without mapped structure
- No trade without predefined TP and stop
- No oversized allocation outside rule
- No revenge trades
- No deviation from breakout-retest rule
