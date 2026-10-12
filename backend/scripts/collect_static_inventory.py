"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-10
Script Path : /data/database-management/backend/scripts/collect_static_inventory.py
Description : Cron entrypoint. Runs services.static_inventory_service against
               every active server and logs a summary. Scheduled hourly via
               crontab or a systemd timer — see deploy/README.md
               "Static inventory cron" section for setup.

               Usage:
                   cd /data/database-management/backend
                   source venv/bin/activate
                   python scripts/collect_static_inventory.py
"""

import sys
import os
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from services import static_inventory_service

logger = logging.getLogger("atlas.cron.static_inventory")


def run():
    app = create_app()
    with app.app_context():
        started = time.monotonic()
        summary = static_inventory_service.refresh_all_active()
        elapsed = time.monotonic() - started
        logger.info(
            "Static inventory collection done: total=%s ok=%s failed=%s duration=%.1fs",
            summary["total"], summary["ok"], summary["failed"], elapsed,
        )
        print(f"[collect_static_inventory] total={summary['total']} "
              f"ok={summary['ok']} failed={summary['failed']} "
              f"duration={elapsed:.1f}s")


if __name__ == "__main__":
    run()
