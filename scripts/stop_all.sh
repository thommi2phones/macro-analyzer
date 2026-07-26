#!/bin/bash
# Macro Analyzer — stop all local processes started by run_all.sh.
set -u
PORT=8002
stopped=""

for entry in \
  "listener:start_telegram_listener.py" \
  "scheduler:ingestion.scheduler --cron"; do
  name="${entry%%:*}"; pattern="${entry#*:}"
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    pkill -f "$pattern" && stopped="$stopped $name"
  fi
done

if lsof -ti ":$PORT" >/dev/null 2>&1; then
  lsof -ti ":$PORT" | xargs kill 2>/dev/null && stopped="$stopped api-server"
fi

echo "stopped:${stopped:-  (nothing was running)}"
