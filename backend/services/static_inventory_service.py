"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-10
Script Path : /data/database-management/backend/services/static_inventory_service.py
Description : Discovers slow-changing OS and MongoDB facts (FQDN, OS name,
               CPU cores, total memory/disk, Mongo version/edition) via SSH
               and PyMongo, and writes them onto the `servers` row. This is
               the ONLY writer of these fields — the server-detail page reads
               them straight from Postgres and never triggers a live pull
               itself. Intended to run from scripts/collect_static_inventory.py
               on an hourly cron, not from a request handler.
"""

import logging
import re
from datetime import datetime
from typing import Optional

from extensions import db
from models import Server
from services import ssh_service, mongo_service
from services.ssh_service import SSHExecutionError

logger = logging.getLogger("atlas.static_inventory")

_LINE_RE = re.compile(r"^([A-Z_]+):(.*)$")


def _parse_kv(stdout: str) -> dict:
    values = {}
    for line in stdout.splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            values[m.group(1)] = m.group(2).strip()
    return values


def _to_int(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def refresh_static_inventory(server: Server) -> None:
    """Pull SSH + Mongo facts for one server and write them onto its row.
    Never raises — failures are recorded on the row itself
    (`static_collection_error`) so the collector can move on to the next
    server and the UI can show what actually happened."""
    errors = []

    # --- OS facts via SSH ---------------------------------------------------
    try:
        ssh_result = ssh_service.run_allowlisted_command(
            host=server.ip_address, port=22,
            credential_ref=server.ssh_credential_ref,
            command_key="os_static_info",
        )
        if ssh_result.ok:
            values = _parse_kv(ssh_result.stdout)
            server.fqdn = values.get("FQDN") or server.fqdn
            server.os_version = values.get("OS_PRETTY") or server.os_version
            server.cpu_cores = _to_int(values.get("CPU_CORES")) or server.cpu_cores
            mem_gb = _to_int(values.get("MEM_TOTAL_GB"))
            disk_gb = _to_int(values.get("DISK_TOTAL_GB"))
            if mem_gb is not None:
                server.memory_gb = mem_gb
            if disk_gb is not None:
                server.disk_gb = disk_gb
        else:
            errors.append(f"ssh: exit={ssh_result.exit_status} {ssh_result.stderr.strip()}")
    except SSHExecutionError as exc:
        errors.append(f"ssh: {exc}")

    # --- MongoDB facts via PyMongo -------------------------------------------
    try:
        health = mongo_service.check_health(
            host=server.ip_address, port=server.port, credential_ref=server.mongo_credential_ref,
        )
        if health.reachable:
            server.mongo_version = health.version or server.mongo_version
            server.node_role = health.replica_state or server.node_role
        else:
            errors.append(f"mongo: {health.error}")
    except Exception as exc:  # noqa: BLE001 — collector must never crash the batch
        errors.append(f"mongo: {exc}")

    server.static_collected_at = datetime.utcnow()
    server.static_collection_error = "; ".join(errors) if errors else None
    db.session.add(server)


def refresh_all_active(batch_commit: bool = True) -> dict:
    """Run refresh_static_inventory() for every active server. Returns a
    summary dict for the cron script to log."""
    servers = Server.query.filter_by(is_active=True).all()
    ok, failed = 0, 0
    for server in servers:
        refresh_static_inventory(server)
        if server.static_collection_error:
            failed += 1
            logger.warning("Static inventory partial/failed for %s: %s",
                            server.hostname, server.static_collection_error)
        else:
            ok += 1
        if not batch_commit:
            db.session.commit()
    if batch_commit:
        db.session.commit()
    return {"total": len(servers), "ok": ok, "failed": failed}
