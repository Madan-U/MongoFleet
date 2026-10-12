"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-10
Script Path : /data/database-management/backend/services/metrics_service.py
Description : Live, point-in-time OS metrics over SSH (CPU%, memory%, disk%,
               OS uptime). Called on every server-detail page load/refresh —
               nothing here is cached or stored in Postgres. If a value can't
               be parsed, the field comes back as None; callers must show
               "unavailable", never a fabricated number.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from services import ssh_service
from services.ssh_service import SSHExecutionError

logger = logging.getLogger("atlas.metrics")

_LINE_RE = re.compile(r"^([A-Z_]+):(.*)$")


def _parse_kv(stdout: str) -> dict:
    values = {}
    for line in stdout.splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            values[m.group(1)] = m.group(2).strip()
    return values


def _to_float(raw: Optional[str]) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _to_int(raw: Optional[str]) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


@dataclass
class LiveMetrics:
    reachable: bool
    cpu_pct: Optional[float] = None
    memory_pct: Optional[float] = None
    disk_pct: Optional[float] = None
    os_uptime_seconds: Optional[int] = None
    error: Optional[str] = None


def get_live_metrics(host: str, credential_ref: str,
                      connect_timeout: int = 8, command_timeout: int = 15) -> LiveMetrics:
    """Fresh SSH pull of CPU/memory/disk/uptime. No caching, no fallback
    numbers — a metric that fails to parse stays None all the way to the API
    response, and the frontend must render that as "unavailable"."""
    try:
        result = ssh_service.run_allowlisted_command(
            host=host, port=22, credential_ref=credential_ref,
            command_key="os_live_metrics",
            connect_timeout=connect_timeout, command_timeout=command_timeout,
        )
    except SSHExecutionError as exc:
        logger.warning("Live metrics SSH failed for %s: %s", host, exc)
        return LiveMetrics(reachable=False, error=str(exc))

    if not result.ok:
        return LiveMetrics(reachable=False, error=result.stderr.strip() or f"exit={result.exit_status}")

    values = _parse_kv(result.stdout)
    return LiveMetrics(
        reachable=True,
        cpu_pct=_to_float(values.get("CPU_PCT")),
        memory_pct=_to_float(values.get("MEM_PCT")),
        disk_pct=_to_float(values.get("DISK_PCT")),
        os_uptime_seconds=_to_int(values.get("OS_UPTIME_SEC")),
    )
