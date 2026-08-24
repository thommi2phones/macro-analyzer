"""Alerting layer — turn a scoring-pass state change into an interrupt.

The scoring pass has always computed "this is a tier_1 A setup". Until
this package existed, that conclusion only reached the operator if the
operator happened to open the SPA. It didn't, twice, in August 2026.

Three pieces, deliberately separate:

  rules.py   — derive alerts from consecutive `trade_scores` rows
  store.py   — persist them (durable record + dedupe + delivery state)
  notify.py  — deliver them to a channel (Telegram today)

`runner.run_alert_cycle()` wires the three together and is what the
launchd job calls.
"""

from macro_positioning.alerts.runner import run_alert_cycle

__all__ = ["run_alert_cycle"]
