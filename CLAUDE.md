# Macro Analyzer — project rules

## Infrastructure is launchd-owned. Do NOT start servers by hand.

All long-running processes are owned by launchd LaunchAgents with
`KeepAlive` — they start at login and resurrect within ~15s if killed. A
session that runs its own `uvicorn`/`nohup` copy fights the supervisor,
duplicates DB writers, and (with the Telegram listener) dies on the
telethon session lock.

| Service | Label | Port |
| --- | --- | --- |
| Dev API + SPA (`--reload`) | `com.macro.uvicorn-8001` | 8001 |
| Second API instance | `com.macro.uvicorn-8181` | 8181 |
| Telegram listener | `com.macro-analyzer.tg-listener` | — |
| Free-layer daily ingest (06:00/13:00) | `com.macro.free-ingest` | — |
| DB backup (05:30/17:30) | `com.macro.db-backup` | — |

If a server looks down or wedged, check status and restart the *job* —
never spawn a replacement process:

```bash
launchctl list | grep macro
```

```bash
launchctl kickstart -k gui/$(id -u)/com.macro.uvicorn-8001
```

Logs: `~/Library/Logs/macro-uvicorn-8001.log` (and `-8181`, `macro-db-backup.log`).

## The database is shared, live, and irreplaceable.

`data/macro_positioning.db` is written concurrently by the API servers and
the Telegram listener. It holds months of ingested documents and signals
that cannot be re-fetched.

- Never delete, move, truncate, or re-create it — that includes its
  `-wal`/`-shm` sidecars while any writer is running.
- Never point a smoke test, fixture, or scratch script at the real path.
  Use a temp copy.
- `initialize_database()` refuses to create a prod DB from scratch unless
  the caller passes `allow_reinit=True`. Do not pass it to get past an
  error — that flag exists to make the wipe path deliberate.
- Stray `MACRO_POSITIONING_*` env vars halt startup on purpose (the real
  prefix is `MPA_`). Fix the typo; don't disable the guard.

Backups: twice daily to `~/Backups/macro-analyzer/` (outside the repo),
integrity-checked, with a poison guard that refuses to prune when the
source DB shrinks. Script: `scripts/backup_db.py`.

## Multiple sessions work in this repo at once.

Assume another worker chat may be editing files and hitting the same DB
concurrently. Prefer additive changes, verify before destructive ones, and
don't "clean up" processes or files you didn't create.
