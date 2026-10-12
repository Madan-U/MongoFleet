"""
Author      : Madan U
Script Path : /data/database-management/backend/scripts/check_server_health.py
Description : Cron entrypoint. Runs a live Mongo health check against every
               active server and persists a ServerHealth snapshot. Powers the
               dashboard's "System Health" card.
"""

import sys
import os
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import Server
from services import inventory_service

logger = logging.getLogger("atlas.cron.server_health")


def run():
    app = create_app()
    with app.app_context():
        started = time.monotonic()
        servers = Server.query.filter_by(is_active=True).all()
        ok = 0
        failed = 0
        for server in servers:
            try:
                inventory_service.refresh_health(server)
                ok += 1
            except Exception as exc:
                failed += 1
                logger.exception("Health check failed for %s", server.hostname)
                print(f"[check_server_health] {server.hostname} failed: {exc}")
        elapsed = time.monotonic() - started
        print(f"[check_server_health] total={len(servers)} ok={ok} failed={failed} "
              f"duration={elapsed:.1f}s")


if __name__ == "__main__":
    run()
