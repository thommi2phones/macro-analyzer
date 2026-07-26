#!/bin/bash
# Build "Macro Analyzer.app" — a double-clickable launcher that runs run_all.sh
# in the user's GUI session (so it has ~/Documents access, unlike a launchd
# daemon). Drop the built app in Login Items for auto-start after login/reboot.
#
# Rebuild any time run_all.sh's location changes. Output: ~/Applications/Macro Analyzer.app
set -eu

RUN_ALL="/Users/thom/Documents/Personal/Code Projects/Macro Analyzer/scripts/run_all.sh"
APP="$HOME/Applications/Macro Analyzer.app"

mkdir -p "$HOME/Applications"
SCPT="$(mktemp /tmp/macro_launch.XXXXXX.applescript)"
cat > "$SCPT" <<EOF
set runAll to "$RUN_ALL"
try
	set out to do shell script "/bin/bash " & quoted form of runAll
	display notification "Collectors + dashboard are running." with title "Macro Analyzer" subtitle "Running"
on error errMsg
	display notification errMsg with title "Macro Analyzer" subtitle "Failed to start"
end try
EOF

rm -rf "$APP"
osacompile -o "$APP" "$SCPT"
rm -f "$SCPT"
echo "built: $APP"
echo "First launch: approve the Documents/Files access prompt (or grant the app"
echo "Full Disk Access in System Settings > Privacy & Security if it fails silently)."
