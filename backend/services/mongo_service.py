"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/services/mongo_service.py
Description : PyMongo-backed connectivity and health-check helpers. Every
               call opens a fresh short-lived client (no long-held pool to
               dozens of managed servers) and returns structured results —
               callers decide how to store/display, this module never
               invents data when a metric is unavailable.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from services.credential_service import get_mongo_credential

logger = logging.getLogger("atlas.mongo")


@dataclass
class MongoHealthResult:
    reachable: bool
    replica_state: Optional[str] = None
    is_primary: Optional[bool] = None
    replication_lag_seconds: Optional[float] = None
    connections_current: Optional[int] = None
    version: Optional[str] = None
    uptime_seconds: Optional[float] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _build_client(host: str, port: int, credential_ref: str,
                   connect_timeout_ms: int, selection_timeout_ms: int) -> MongoClient:
    cred = get_mongo_credential(credential_ref)
    kwargs = dict(
        host=host,
        port=port,
        connectTimeoutMS=connect_timeout_ms,
        serverSelectionTimeoutMS=selection_timeout_ms,
        directConnection=True,  # health-check exactly the node we asked for
    )
    if cred.username and cred.password:
        kwargs.update(username=cred.username, password=cred.password, authSource=cred.auth_source)
    return MongoClient(**kwargs)


def create_user(host: str, port: int, credential_ref: str, target_db: str,
                 username: str, password: str, roles: list,
                 connect_timeout_ms: int = 4000, selection_timeout_ms: int = 4000) -> dict:
    """Create a MongoDB user scoped to `target_db`. `roles` is a list of
    plain role names (e.g. ["readWrite", "dbAdmin"]) applied on that same db —
    good enough for the common case; cross-db roles aren't exposed via the
    operations GUI today."""
    client = None
    try:
        client = _build_client(host, port, credential_ref, connect_timeout_ms, selection_timeout_ms)
        client[target_db].command(
            "createUser", username, pwd=password,
            roles=[{"role": r, "db": target_db} for r in roles],
        )
        return {"ok": True}
    except PyMongoError as exc:
        logger.warning("createUser failed for %s on %s:%s/%s — %s", username, host, port, target_db, exc)
        return {"ok": False, "error": str(exc)}
    finally:
        if client:
            client.close()


def set_profiler(host: str, port: int, credential_ref: str, target_db: str,
                  enabled: bool, threshold_ms: Optional[int] = None,
                  connect_timeout_ms: int = 4000, selection_timeout_ms: int = 4000) -> dict:
    """level 0 = off, level 1 = ops slower than threshold_ms only. We never
    use level 2 (profile everything) from this GUI — too easy to fill the
    profile collection and hurt the very server being profiled."""
    client = None
    try:
        client = _build_client(host, port, credential_ref, connect_timeout_ms, selection_timeout_ms)
        level = 1 if enabled else 0
        kwargs = {"slowms": threshold_ms} if (enabled and threshold_ms is not None) else {}
        result = client[target_db].command("profile", level, **kwargs)
        return {"ok": True, "was": result.get("was"), "slowms": result.get("slowms")}
    except PyMongoError as exc:
        logger.warning("set_profiler failed on %s/%s — %s", host, target_db, exc)
        return {"ok": False, "error": str(exc)}
    finally:
        if client:
            client.close()


def user_exists(host: str, port: int, credential_ref: str, target_db: str, username: str,
                 connect_timeout_ms: int = 4000, selection_timeout_ms: int = 4000) -> dict:
    """Real post-check for create_user — queries usersInfo rather than
    assuming createUser succeeding means the user is actually there."""
    client = None
    try:
        client = _build_client(host, port, credential_ref, connect_timeout_ms, selection_timeout_ms)
        info = client[target_db].command("usersInfo", username)
        users = info.get("users", [])
        if not users:
            return {"ok": True, "exists": False}
        roles = [r.get("role") for r in users[0].get("roles", [])]
        return {"ok": True, "exists": True, "roles": roles}
    except PyMongoError as exc:
        return {"ok": False, "exists": False, "error": str(exc)}
    finally:
        if client:
            client.close()


def get_profiler_status(host: str, port: int, credential_ref: str, target_db: str,
                         connect_timeout_ms: int = 4000, selection_timeout_ms: int = 4000) -> dict:
    """Real post-check for configure_profiler. `profile(-1)` reads current
    settings without changing them."""
    client = None
    try:
        client = _build_client(host, port, credential_ref, connect_timeout_ms, selection_timeout_ms)
        result = client[target_db].command("profile", -1)
        return {"ok": True, "level": result.get("was"), "slowms": result.get("slowms")}
    except PyMongoError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if client:
            client.close()


def check_long_running_ops(host: str, port: int, credential_ref: str, threshold_minutes: int = 15,
                            connect_timeout_ms: int = 4000, selection_timeout_ms: int = 4000) -> dict:
    """Looks at currentOp for active operations running longer than
    threshold_minutes. Used as a pre-check before restart/stop so a DBA
    isn't surprised by killed long-running queries. If Mongo can't be
    reached at all, we don't block the operation on it — an unreachable
    server is usually exactly why a restart is being requested."""
    client = None
    try:
        client = _build_client(host, port, credential_ref, connect_timeout_ms, selection_timeout_ms)
        # NOTE: the legacy `currentOp` command (deprecated since 6.2) does not
        # reliably honor a "secs_running" filter when invoked via a raw driver
        # command — that pseudo-field match is only guaranteed through the
        # mongosh db.currentOp() helper. Using the $currentOp aggregation
        # stage + an explicit $match is the documented, reliable equivalent.
        pipeline = [
            {"$currentOp": {"allUsers": True, "idleConnections": False}},
            {"$match": {"active": True, "secs_running": {"$gte": threshold_minutes * 60}}},
        ]
        ops = list(client.admin.aggregate(pipeline))
        longest_secs = max((o.get("secs_running", 0) for o in ops), default=0)
        return {
            "checked": True, "blocking": len(ops) > 0, "count": len(ops),
            "longest_minutes": round(longest_secs / 60, 1), "threshold_minutes": threshold_minutes,
        }
    except PyMongoError as exc:
        logger.warning("check_long_running_ops could not reach %s:%s — %s", host, port, exc)
        return {"checked": False, "blocking": False, "count": 0, "longest_minutes": 0,
                "threshold_minutes": threshold_minutes, "error": str(exc)}
    finally:
        if client:
            client.close()


def check_health(host: str, port: int, credential_ref: str = "nonprod",
                  connect_timeout_ms: int = 4000, selection_timeout_ms: int = 4000) -> MongoHealthResult:
    """Live ping + rs.status()-equivalent + serverStatus() summary for one node.
    Never cached — call this fresh every time the UI needs current health."""
    client = None
    try:
        client = _build_client(host, port, credential_ref, connect_timeout_ms, selection_timeout_ms)
        client.admin.command("ping")

        server_status = client.admin.command("serverStatus")
        version = server_status.get("version")
        uptime = server_status.get("uptime")
        connections_current = (server_status.get("connections") or {}).get("current")

        replica_state = None
        is_primary = None
        lag_seconds = None
        try:
            repl_status = client.admin.command("replSetGetStatus")
            self_member = next((m for m in repl_status.get("members", []) if m.get("self")), None)
            if self_member:
                replica_state = self_member.get("stateStr")
                is_primary = replica_state == "PRIMARY"
            primary_member = next((m for m in repl_status.get("members", []) if m.get("state") == 1), None)
            if primary_member and self_member and not is_primary:
                lag = (primary_member.get("optimeDate") - self_member.get("optimeDate"))
                lag_seconds = abs(lag.total_seconds())
        except PyMongoError:
            # Standalone node — no replica set, that's a valid state, not an error.
            replica_state = "STANDALONE"

        return MongoHealthResult(
            reachable=True,
            replica_state=replica_state,
            is_primary=is_primary,
            replication_lag_seconds=lag_seconds,
            connections_current=connections_current,
            version=version,
            uptime_seconds=uptime,
            raw={"serverStatus": {"version": version, "uptime": uptime}},
        )
    except PyMongoError as exc:
        logger.warning("Mongo health check failed for %s:%s — %s", host, port, exc)
        return MongoHealthResult(reachable=False, error=str(exc))
    finally:
        if client:
            client.close()
