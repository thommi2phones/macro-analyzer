# launchd agents — local durability

These are the macOS LaunchAgents that keep the collectors running unattended.
They are the source-of-truth copies; the live ones live in
`~/Library/LaunchAgents/`. To (re)install:

```bash
cp deploy/launchd/*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.macro-analyzer.tg-listener.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.macro.free-ingest.plist
```

## The agents

| Agent | Cadence | Runs | Cost |
|---|---|---|---|
| `com.macro-analyzer.tg-listener` | always-on (`KeepAlive`) | Telegram listener — live KOL chart capture + auto-extract | free* |
| `com.macro.free-ingest` | 06:00 + 13:00 daily | `daily_free_ingest.py` — Gmail/News/Substack/Podcasts + insiders + FRED + prices + heuristic scoring | **free** |

\* the listener auto-extracts charts, which uses the vision backend.

Both survive **reboot** (load at login), **sleep** (launchd runs a missed
`StartCalendarInterval` fire once on wake), and **crash** (`KeepAlive` on the
listener).

Paid LLM prose/chart extraction is **deliberately not** in `free-ingest` — that
stays a manual, budgeted step (`macro-positioning signals extract`).

## The one non-obvious requirement: Full Disk Access

The repo lives under `~/Documents`, which macOS TCC protects. A LaunchAgent is
**denied** access there unless the *executable it runs* has been granted Full
Disk Access. That is why both plists invoke **`.venv/bin/python` directly** —
that interpreter has been granted FDA (System Settings → Privacy & Security →
Full Disk Access). Running via `uv` or `bash` instead fails with
`Operation not permitted`, because those binaries don't have the grant.

If you recreate the venv, re-grant FDA to the new `.venv/bin/python` (or the
base interpreter it symlinks to).
