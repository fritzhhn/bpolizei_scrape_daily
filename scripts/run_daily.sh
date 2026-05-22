#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PWD}:${PYTHONPATH:-}"
LOG_DIR="${PWD}/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/scrape-$(date +%Y%m%d).log"
exec >>"$LOG_FILE" 2>&1
echo "=== Scrape $(date -Iseconds) ==="
if [[ -d .venv ]]; then
  source .venv/bin/activate
fi
python -m scraper.scrape --mode daily --skip-existing
