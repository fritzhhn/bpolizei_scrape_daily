#!/usr/bin/env bash
# Installiert einen täglichen LaunchAgent (macOS) um 6:00 Uhr.
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/de.berlin.polizeimeldungen.scrape.plist"
mkdir -p "$PROJECT/data/logs"
cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>de.berlin.polizeimeldungen.scrape</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${PROJECT}/scripts/run_daily.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>6</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${PROJECT}/data/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT}/data/logs/launchd.err.log</string>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "LaunchAgent installiert: $PLIST"
echo "Täglicher Lauf um 06:00. Logs in data/logs/"
