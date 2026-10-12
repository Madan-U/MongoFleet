#!/usr/bin/env bash
# =============================================================================
# Script      : run_static_inventory_collect.sh
# Description : Cron wrapper — collects static inventory (replica-set topology,
#               version, storage engine, auth mode) from all registered MongoDB
#               hosts and writes results to the metadata database.
#               Designed to run hourly via cron or systemd timer.
# Author      : Madan U
# Email       : madanu135@gmail.com
# Date        : 2026-09-10
# Usage       : 0 * * * * /path/to/run_static_inventory_collect.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
BASE_DIR="$(dirname "$APP_DIR")"
LOG_FILE="${LOG_DIR:-$BASE_DIR/logs}/static-inventory-cron.log"

cd "$APP_DIR"
source venv/bin/activate

{
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') START ---"
    python scripts/collect_static_inventory.py
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') END ---"
} >> "$LOG_FILE" 2>&1
