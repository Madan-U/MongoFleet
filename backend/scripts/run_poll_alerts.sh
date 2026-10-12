#!/usr/bin/env bash
# =============================================================================
# Script      : run_poll_alerts.sh
# Description : Cron wrapper — polls alert rules against the MongoDB fleet
#               and writes any triggered alerts to the database.
#               Designed to run every 1 minute via cron or systemd timer.
# Author      : Madan U
# Email       : madanu135@gmail.com
# Date        : 2026-09-12
# Usage       : */1 * * * * /path/to/run_poll_alerts.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
BASE_DIR="$(dirname "$APP_DIR")"
LOG_FILE="${LOG_DIR:-$BASE_DIR/logs}/alerts-cron.log"

cd "$APP_DIR"
source venv/bin/activate

{
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') START ---"
    python scripts/poll_alerts.py
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') END ---"
} >> "$LOG_FILE" 2>&1
