"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-12
Script Path : /data/database-management/backend/scripts/poll_alerts.py
Description : Cron entrypoint. Scans audit_logs for anything new since the
               last run, turns matching rows into alerts, and dispatches
               whatever is pending. Scheduled every 1 minute via crontab or
               a systemd timer — see deploy/README.md "Alert polling"
               section for setup. Safe to run more often than the audit
               table actually changes; safe to overlap (advisory lock).

               Usage:
                   cd /data/database-management/backend
                   source venv/bin/activate
                   python scripts/poll_alerts.py
"""

import sys
import os
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from services import alert_service

logger = logging.getLogger("atlas.cron.alerts")


def run():
    app = create_app()
    with app.app_context():
        started = time.monotonic()
        result = alert_service.run_poll_cycle()
        elapsed = time.monotonic() - started

        if result.get("skipped"):
            print(f"[poll_alerts] skipped (previous run still in progress) duration={elapsed:.1f}s")
            return

        gen, disp = result["generate"], result["dispatch"]
        logger.info(
            "Alert poll done: scanned=%s created=%s sent=%s failed=%s duration=%.1fs",
            gen["scanned"], gen["created"], disp["sent"], disp["failed"], elapsed,
        )
        print(f"[poll_alerts] scanned={gen['scanned']} created={gen['created']} "
              f"sent={disp['sent']} failed={disp['failed']} cursor={gen['cursor']} "
              f"duration={elapsed:.1f}s")


if __name__ == "__main__":
    run()
