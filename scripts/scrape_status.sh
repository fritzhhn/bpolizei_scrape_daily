#!/usr/bin/env bash
# Fortschritt des laufenden Full-Scrapes anzeigen
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${PWD}/data/logs/full-scrape.log"
DB="${PWD}/data/meldungen.db"

echo "=== Prozess ==="
pgrep -fl "scraper.scrape" 2>/dev/null || echo "(kein Scraper aktiv)"

echo ""
echo "=== Log (letzte 8 Zeilen) ==="
tail -8 "$LOG" 2>/dev/null || echo "Kein Log."

echo ""
echo "=== Datenbank ==="
if [[ -f "$DB" ]]; then
  sqlite3 "$DB" "SELECT COUNT(*) AS meldungen FROM meldungen;"
  ls -lh "$DB"
  sqlite3 "$DB" "SELECT mode, started_at, articles_fetched, articles_new, errors FROM scrape_runs ORDER BY id DESC LIMIT 1;" 2>/dev/null | head -1
else
  echo "Noch keine DB."
fi
