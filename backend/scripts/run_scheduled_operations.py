"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-15
Script Path : /data/database-management/backend/scripts/run_scheduled_operations.py
Description : Cron entrypoint. Runs services.scheduler_service.run_due_schedules()
               and logs a summary. Scheduled every 1 minute via crontab — see
               deploy/README.md "Scheduled operations cron" section.

               Usage:
                   cd /data/database-management/backend
                   source venv/bin/activate
                   python scripts/run_scheduled_operations.py
"""

import sys
import os
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from services import scheduler_service

logger = logging.getLogger("atlas.cron.scheduler")


def run():
    app = create_app()
    with app.app_context():
        started = time.monotonic()
        summary = scheduler_service.run_due_schedules()
        elapsed = time.monotonic() - started
        logger.info(
            "Scheduled-operations check done: checked=%s fired=%s failed=%s duration=%.1fs",
            summary["checked"], summary["fired"], summary["failed"], elapsed,
        )
        print(f"[run_scheduled_operations] checked={summary['checked']} "
              f"fired={summary['fired']} failed={summary['failed']} "
              f"duration={elapsed:.1f}s")


if __name__ == "__main__":
    run()
