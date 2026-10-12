#!/usr/bin/env bash
# =============================================================================
# Script      : run_scheduled_operations.sh
# Description : Cron wrapper — picks up REQUESTED operations from the queue
#               and executes them against the MongoDB fleet (start/stop/backup
#               etc.). Designed to run every 1 minute via cron or systemd timer.
# Author      : Madan U
# Email       : madanu135@gmail.com
# Date        : 2026-09-15
# Usage       : */1 * * * * /path/to/run_scheduled_operations.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
BASE_DIR="$(dirname "$APP_DIR")"
LOG_FILE="${LOG_DIR:-$BASE_DIR/logs}/scheduled-operations-cron.log"

cd "$APP_DIR"
source venv/bin/activate

{
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') START ---"
    python scripts/run_scheduled_operations.py
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') END ---"
} >> "$LOG_FILE" 2>&1
