# M6 — Alerts Module CLAUDE.md

## Purpose
Send trade alerts and reports via Discord and email.
Also handles the paper trading report command.

## Files
```
alerts/
├── CLAUDE.md
├── discord.py       ← Discord webhook alerts
└── email_alert.py   ← SMTP email alerts (optional)
```

## Discord setup
```
DISCORD_WEBHOOK_URL in .env  (optional — alerts silently skipped if not set)
```

## Alert format (what to send on a signal)
```
🚨 SIGNAL: BTC/USD LONG
━━━━━━━━━━━━━━━━━━━━
Setup:      Falling wedge breakout
Timeframe:  4H
Entry:      $48,250
TP:         $52,400  (+8.6%)
Stop:       $46,800  (-3.0%)
Confidence: 0.78
Rules:      [ema_cross_bullish, rsi_oversold, breakout_volume]
━━━━━━━━━━━━━━━━━━━━
Account:    $100,000 paper | 2 open positions
```

## Email setup (optional)
```
EMAIL_HOST / EMAIL_USER / EMAIL_PASS / EMAIL_TO in .env
```

## TODO for this module
- [ ] Add Discord embed formatting (colored embeds, not plain text)
- [ ] Add daily summary alert (end of day P&L, open positions)
- [ ] Add fill confirmation alert (when order executes)
- [ ] Rate limit alerts (don't spam if many signals fire at once)

## Consumed by
- `agent/loop.py` — called after each signal that passes confidence threshold
