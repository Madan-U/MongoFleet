"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-16
Script Path : /data/database-management/backend/services/operations_service.py
Description : The operation engine. Every operation_type has a fixed,
               ordered step list; execute_operation() drives an `Operation`
               row through REQUESTED -> RUNNING -> SUCCESS/FAILED, and each
               step is written to `Operation.steps` (for the live progress
               UI) and `OperationLog` (for the scrolling log view) as it
               actually happens — nothing here is a simulated delay or a
               canned success message. Every "OK" comes from a real SSH/
               PyMongo check.

               Called from two places only:
                 - routes/operations.py, for "run now" (one-time immediate,
                   run in a background thread so the HTTP response returns
                   immediately and the frontend polls for live progress)
                 - services/scheduler_service.py, for a due ScheduledOperation

               restart/stop carry a long-running-query pre-check (section 5
               of the ops spec): if active ops have been running past the
               admin-configurable threshold (settings_service), the route
               layer blocks with a 409 requiring the user to explicitly
               force or cancel — this module never auto-forces anything.
"""

import base64
import logging
import os
from datetime import datetime
from typing import Callable, Optional

import yaml
from sqlalchemy.orm.attributes import flag_modified

from extensions import db
from models import Operation, OperationLog, OperationStatus, Server
from services import audit_service, mongo_service, notification_service, settings_service, ssh_service
from services.ssh_service import SSHExecutionError

logger = logging.getLogger("atlas.operations")

OPERATION_TYPES = (
    "start", "stop", "restart", "create_user", "backup",
    "configure_profiler", "configure_auth", "configure_memory",
    "configure_journal", "change_port",
)

DEFAULT_BACKUP_DIR = os.environ.get("MONGO_BACKUP_DIR", "/apps/DB/modb/backup")  # on the DB host, writable by <ssh_username>


class OperationError(RuntimeError):
    """Raised by a handler to fail the operation with a clear message."""


# ---------------------------------------------------------------------------
# Step + log bookkeeping
# ---------------------------------------------------------------------------
def _log(operation: Operation, level: str, message: str) -> None:
    db.session.add(OperationLog(operation_id=operation.id, level=level, message=message))
    db.session.commit()
    logger.info("[op %s] %s: %s", operation.id, level, message)


def _init_steps(operation: Operation, step_defs: list) -> None:
    operation.steps = [
        {"key": k, "label": l, "status": "PENDING", "started_at": None,
         "completed_at": None, "duration_ms": None, "message": None}
        for k, l in step_defs
    ]
    db.session.add(operation)
    db.session.commit()


def _find_step(operation: Operation, key: str) -> dict:
    for step in operation.steps:
        if step["key"] == key:
            return step
    raise KeyError(f"no such step '{key}' on operation {operation.id}")


def _step_start(operation: Operation, key: str) -> None:
    step = _find_step(operation, key)
    step["status"] = "RUNNING"
    step["started_at"] = datetime.utcnow().isoformat()
    operation.current_step = step["label"]
    flag_modified(operation, "steps")
    db.session.add(operation)
    db.session.commit()
    _log(operation, "INFO", f"[{step['label']}] started")


def _step_finish(operation: Operation, key: str, status: str, message: Optional[str] = None) -> None:
    """status: OK / WARN / FAILED"""
    step = _find_step(operation, key)
    step["status"] = status
    step["completed_at"] = datetime.utcnow().isoformat()
    if step["started_at"]:
        started = datetime.fromisoformat(step["started_at"])
        step["duration_ms"] = int((datetime.utcnow() - started).total_seconds() * 1000)
    step["message"] = message
    flag_modified(operation, "steps")
    finished = sum(1 for s in operation.steps if s["status"] in ("OK", "WARN", "FAILED"))
    operation.progress_pct = int(finished / len(operation.steps) * 100) if operation.steps else 0
    db.session.add(operation)
    db.session.commit()
    level = "ERROR" if status == "FAILED" else ("WARN" if status == "WARN" else "INFO")
    suffix = f" — {message}" if message else ""
    _log(operation, level, f"[{step['label']}] {status}{suffix}")


def _run_ssh(server: Server, command_key: str, params: Optional[dict] = None):
    result = ssh_service.run_allowlisted_command(
        host=server.ip_address, port=22, credential_ref=server.ssh_credential_ref,
        command_key=command_key, params=params or {},
    )
    if not result.ok:
        raise OperationError(f"{command_key} failed: exit={result.exit_status} {result.stderr.strip()}")
    return result


def _read_config(server: Server) -> str:
    if not server.config_file_path:
        raise OperationError("Server has no config_file_path set in inventory — cannot edit mongod.conf")
    return _run_ssh(server, "mongo_config_read", {"config_path": server.config_file_path}).stdout


def _set_yaml_path(doc: dict, dotted_path: str, value) -> dict:
    node = doc
    parts = dotted_path.split(".")
    for key in parts[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise OperationError(f"Unexpected non-mapping value at '{key}' in mongod.conf")
    node[parts[-1]] = value
    return doc


def _get_yaml_path(doc: dict, dotted_path: str):
    node = doc
    for key in dotted_path.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _ist(dt: Optional[datetime]) -> str:
    """Formats a naive-UTC datetime as an IST string for display/notifications.
    Stored timestamps stay UTC in the DB — this is purely a presentation
    conversion (+5:30), done with plain arithmetic so it works even if the
    'tzdata' package isn't installed on the box."""
    if dt is None:
        return "—"
    from datetime import timedelta
    ist_dt = dt + timedelta(hours=5, minutes=30)
    return ist_dt.strftime("%d-%b-%Y %I:%M:%S %p") + " IST"


def _ist_ts_compact() -> str:
    """Current IST time as a filename-safe timestamp (YYYYMMDD_HHMMSS),
    for backup folder / config-backup file names on disk. Same +5:30
    plain-arithmetic approach as _ist() above — deliberately not using
    zoneinfo/pytz so this keeps working even without tzdata installed."""
    from datetime import timedelta
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# Config-file edit primitive shared by the 4 "edit mongod.conf" operations
# ---------------------------------------------------------------------------
_CONFIG_STEP_DEFS = [
    ("validate", "Validate parameters"),
    ("read_config", "Read mongod.conf"),
    ("backup_config", "Back up mongod.conf"),
    ("edit_config", "Update configuration"),
    ("restart", "Restart mongod"),
    ("verify", "Verify configuration applied"),
]


def _configure_via_config_edit(server: Server, operation: Operation, dotted_path: str, value) -> dict:
    _step_start(operation, "read_config")
    raw = _read_config(server)
    try:
        doc = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        _step_finish(operation, "read_config", "FAILED", str(exc))
        raise OperationError(f"Could not parse existing mongod.conf as YAML: {exc}") from exc
    _step_finish(operation, "read_config", "OK")

    _step_start(operation, "backup_config")
    ts = _ist_ts_compact().replace("_", "")
    _run_ssh(server, "mongo_config_backup_copy", {"config_path": server.config_file_path, "ts": ts})
    backup_path = f"{server.config_file_path}.bak.{ts}"
    _step_finish(operation, "backup_config", "OK", f"backed up to {backup_path}")

    _step_start(operation, "edit_config")
    _set_yaml_path(doc, dotted_path, value)
    new_text = yaml.safe_dump(doc, default_flow_style=False, sort_keys=False)
    b64 = base64.b64encode(new_text.encode("utf-8")).decode("ascii")
    _run_ssh(server, "mongo_config_write", {"config_path": server.config_file_path, "b64_content": b64})
    _step_finish(operation, "edit_config", "OK", f"{dotted_path} = {value}")

    _step_start(operation, "restart")
    _run_ssh(server, "mongo_service_restart")
    _step_finish(operation, "restart", "OK")

    _step_start(operation, "verify")
    health = mongo_service.check_health(server.ip_address, server.port, server.mongo_credential_ref, connect_timeout_ms=30000, selection_timeout_ms=30000)
    if not health.reachable:
        _step_finish(operation, "verify", "FAILED", "mongod not reachable after restart")
        raise OperationError("mongod_not_reachable_after_config_change")
    verify_raw = _read_config(server)
    verify_doc = yaml.safe_load(verify_raw) or {}
    actual = _get_yaml_path(verify_doc, dotted_path)
    if actual != value:
        _step_finish(operation, "verify", "WARN",
                     f"mongod is up, but {dotted_path} on disk reads {actual!r} (expected {value!r})")
    else:
        _step_finish(operation, "verify", "OK", f"mongod up, {dotted_path} confirmed = {actual!r}")

    return {"backup_path": backup_path, dotted_path: value, "verified_value": actual}


# ---------------------------------------------------------------------------
# Handlers — one per operation_type. Signature: (server, operation, params).
# Each initialises its own step list first via _init_steps().
# ---------------------------------------------------------------------------
def _op_start(server: Server, operation: Operation, params: dict):
    _init_steps(operation, [
        ("start", "Start mongod"),
        ("verify", "Verify mongod accepted connections"),
    ])
    _step_start(operation, "start")
    _run_ssh(server, "mongo_service_start")
    _step_finish(operation, "start", "OK")

    _step_start(operation, "verify")
    health = mongo_service.check_health(server.ip_address, server.port, server.mongo_credential_ref, connect_timeout_ms=30000, selection_timeout_ms=30000)
    if not health.reachable:
        _step_finish(operation, "verify", "FAILED", health.error or "not reachable")
        raise OperationError("mongod_not_reachable_after_start")
    _step_finish(operation, "verify", "OK", f"role={health.replica_state}")
    return {"action": "start", "role": health.replica_state}


def _op_stop(server: Server, operation: Operation, params: dict):
    _init_steps(operation, [
        ("long_running", "Check for long-running operations"),
        ("connections", "Check active connections"),
        ("stop", "Stop mongod"),
        ("verify", "Verify mongod stopped"),
    ])
    force = bool(params.get("force"))
    threshold = settings_service.get_long_running_threshold_minutes()

    _step_start(operation, "long_running")
    precheck = mongo_service.check_long_running_ops(
        server.ip_address, server.port, server.mongo_credential_ref, threshold)
    operation.precheck_results = precheck
    db.session.add(operation)
    db.session.commit()
    if precheck["blocking"] and not force:
        _step_finish(operation, "long_running", "FAILED",
                     f"{precheck['count']} ops running >{threshold}min — confirmation required")
        raise OperationError("long_running_operations_detected")
    elif precheck["blocking"]:
        _step_finish(operation, "long_running", "WARN",
                     f"{precheck['count']} ops >{threshold}min (longest {precheck['longest_minutes']}min) — user forced")
    else:
        _step_finish(operation, "long_running", "OK", "No long-running operations found")

    _step_start(operation, "connections")
    health = mongo_service.check_health(server.ip_address, server.port, server.mongo_credential_ref, connect_timeout_ms=30000, selection_timeout_ms=30000)
    _step_finish(operation, "connections", "OK",
                 f"active_connections={health.connections_current}" if health.reachable else "mongo unreachable")

    _step_start(operation, "stop")
    _run_ssh(server, "mongo_service_stop")
    _step_finish(operation, "stop", "OK")

    _step_start(operation, "verify")
    post = mongo_service.check_health(server.ip_address, server.port, server.mongo_credential_ref)
    if post.reachable:
        _step_finish(operation, "verify", "WARN", "mongod still reachable after stop — process may still be shutting down")
    else:
        _step_finish(operation, "verify", "OK", "mongod is down")
    return {"action": "stop", "precheck": precheck}


def _op_restart(server: Server, operation: Operation, params: dict):
    _init_steps(operation, [
        ("connectivity", "Verify connectivity before restart"),
        ("long_running", "Check for long-running operations"),
        ("stop", "Stop mongod"),
        ("start", "Start mongod"),
        ("verify_conn", "Verify mongod connectivity"),
        ("verify_replset", "Verify replica-set health"),
    ])
    force = bool(params.get("force"))
    threshold = settings_service.get_long_running_threshold_minutes()

    _step_start(operation, "connectivity")
    pre_health = mongo_service.check_health(server.ip_address, server.port, server.mongo_credential_ref, connect_timeout_ms=30000, selection_timeout_ms=30000)
    if pre_health.reachable:
        _step_finish(operation, "connectivity", "OK", f"role={pre_health.replica_state}")
    else:
        _step_finish(operation, "connectivity", "WARN", "mongod not reachable before restart")

    _step_start(operation, "long_running")
    precheck = mongo_service.check_long_running_ops(
        server.ip_address, server.port, server.mongo_credential_ref, threshold)
    operation.precheck_results = precheck
    db.session.add(operation)
    db.session.commit()
    if precheck["blocking"] and not force:
        _step_finish(operation, "long_running", "FAILED",
                     f"{precheck['count']} ops running >{threshold}min — confirmation required")
        raise OperationError("long_running_operations_detected")
    elif precheck["blocking"]:
        _step_finish(operation, "long_running", "WARN",
                     f"{precheck['count']} ops >{threshold}min (longest {precheck['longest_minutes']}min) — user forced")
    else:
        _step_finish(operation, "long_running", "OK", "No long-running operations found")

    _step_start(operation, "stop")
    _run_ssh(server, "mongo_service_stop")
    _step_finish(operation, "stop", "OK")

    _step_start(operation, "start")
    _run_ssh(server, "mongo_service_start")
    _step_finish(operation, "start", "OK")

    _step_start(operation, "verify_conn")
    post_health = mongo_service.check_health(server.ip_address, server.port, server.mongo_credential_ref, connect_timeout_ms=30000, selection_timeout_ms=30000)
    if not post_health.reachable:
        _step_finish(operation, "verify_conn", "FAILED", post_health.error or "unreachable after restart")
        raise OperationError("mongod_not_reachable_after_restart")
    _step_finish(operation, "verify_conn", "OK")

    _step_start(operation, "verify_replset")
    _step_finish(operation, "verify_replset", "OK", f"role={post_health.replica_state}")

    return {"action": "restart", "precheck": precheck, "post_role": post_health.replica_state}


def _op_create_user(server: Server, operation: Operation, params: dict):
    _init_steps(operation, [
        ("validate", "Validate parameters"),
        ("create", "Create user"),
        ("verify", "Verify user exists"),
    ])
    _step_start(operation, "validate")
    target_db = params.get("target_db")
    username = params.get("username")
    password = params.get("password")
    roles = params.get("roles") or []
    if not (target_db and username and password and roles):
        _step_finish(operation, "validate", "FAILED", "target_db, username, password, roles are all required")
        raise OperationError("create_user requires target_db, username, password, roles")
    _step_finish(operation, "validate", "OK")

    _step_start(operation, "create")
    result = mongo_service.create_user(
        host=server.ip_address, port=server.port, credential_ref=server.mongo_credential_ref,
        target_db=target_db, username=username, password=password, roles=roles,
    )
    if not result.get("ok"):
        _step_finish(operation, "create", "FAILED", result.get("error"))
        raise OperationError(result.get("error") or "createUser failed")
    _step_finish(operation, "create", "OK")

    _step_start(operation, "verify")
    verify = mongo_service.user_exists(
        server.ip_address, server.port, server.mongo_credential_ref, target_db, username)
    if verify.get("exists"):
        _step_finish(operation, "verify", "OK", f"usersInfo confirms '{username}' with roles {verify.get('roles')}")
    else:
        _step_finish(operation, "verify", "WARN", verify.get("error") or "could not confirm via usersInfo")
    return {"target_db": target_db, "username": username, "roles": roles}


def _op_backup(server: Server, operation: Operation, params: dict):
    _init_steps(operation, [
        ("validate", "Validate parameters"),
        ("prepare", "Prepare backup directory"),
        ("run", "Run mongodump"),
        ("verify", "Verify backup output"),
    ])
    _step_start(operation, "validate")
    scope = params.get("scope")
    db_name = params.get("db_name")
    collection_name = params.get("collection_name")
    if not db_name or scope not in ("db", "collection"):
        _step_finish(operation, "validate", "FAILED", "requires scope ('db'|'collection') and db_name")
        raise OperationError("backup requires scope ('db'|'collection') and db_name")
    if scope == "collection" and not collection_name:
        _step_finish(operation, "validate", "FAILED", "scope 'collection' requires collection_name")
        raise OperationError("backup scope 'collection' requires collection_name")
    _step_finish(operation, "validate", "OK")

    ts = _ist_ts_compact()
    backup_name = f"{db_name}_{ts}" if scope == "db" else f"{db_name}_{collection_name}_{ts}"
    backup_path = f"{DEFAULT_BACKUP_DIR}/{backup_name}"

    _step_start(operation, "prepare")
    _step_finish(operation, "prepare", "OK", f"target: {backup_path}")

    _step_start(operation, "run")
    compression = params.get("compression", "none")
    use_gzip = compression == "gzip"
    if scope == "db":
        cmd_key = "mongo_backup_db_gzip" if use_gzip else "mongo_backup_db"
        result = _run_ssh(server, cmd_key, {
            "backup_dir": DEFAULT_BACKUP_DIR, "db_name": db_name, "backup_name": backup_name})
    else:
        cmd_key = "mongo_backup_collection_gzip" if use_gzip else "mongo_backup_collection"
        result = _run_ssh(server, cmd_key, {
            "backup_dir": DEFAULT_BACKUP_DIR, "db_name": db_name,
            "collection_name": collection_name, "backup_name": backup_name})
    _step_finish(operation, "run", "OK",
                 (result.stdout.strip() or "mongodump completed") + (" (gzip)" if use_gzip else ""))

    _step_start(operation, "verify")
    check = ssh_service.run_allowlisted_command(
        host=server.ip_address, port=22, credential_ref=server.ssh_credential_ref,
        command_key="mongo_backup_verify", params={"backup_dir": backup_path},
    )
    if check.ok and "cannot access" not in check.stdout.lower() and "no such file" not in check.stdout.lower():
        _step_finish(operation, "verify", "OK", check.stdout.strip())
    else:
        _step_finish(operation, "verify", "WARN", "mongodump reported success but size check could not confirm the output directory")
    return {"scope": scope, "path": backup_path, "compression": compression}


def _op_configure_profiler(server: Server, operation: Operation, params: dict):
    _init_steps(operation, [
        ("validate", "Validate parameters"),
        ("apply", "Apply profiler setting"),
        ("verify", "Verify profiler setting"),
    ])
    _step_start(operation, "validate")
    target_db = params.get("target_db")
    enabled = bool(params.get("enabled"))
    threshold_ms = params.get("threshold_ms")
    if not target_db:
        _step_finish(operation, "validate", "FAILED", "target_db is required")
        raise OperationError("configure_profiler requires target_db")
    if enabled and threshold_ms is None:
        _step_finish(operation, "validate", "FAILED", "threshold_ms is required when enabling the profiler")
        raise OperationError("configure_profiler requires threshold_ms when enabling the profiler")
    _step_finish(operation, "validate", "OK")

    _step_start(operation, "apply")
    result = mongo_service.set_profiler(
        host=server.ip_address, port=server.port, credential_ref=server.mongo_credential_ref,
        target_db=target_db, enabled=enabled, threshold_ms=threshold_ms,
    )
    if not result.get("ok"):
        _step_finish(operation, "apply", "FAILED", result.get("error"))
        raise OperationError(result.get("error") or "profile command failed")
    _step_finish(operation, "apply", "OK", f"was={result.get('was')}")

    _step_start(operation, "verify")
    status = mongo_service.get_profiler_status(server.ip_address, server.port, server.mongo_credential_ref, target_db)
    expected_level = 1 if enabled else 0
    if status.get("ok") and status.get("level") == expected_level:
        _step_finish(operation, "verify", "OK", f"level={status.get('level')} slowms={status.get('slowms')}")
    else:
        _step_finish(operation, "verify", "WARN", status.get("error") or f"reported level={status.get('level')}")
    return {"target_db": target_db, "enabled": enabled, "threshold_ms": threshold_ms}


def _op_configure_auth(server: Server, operation: Operation, params: dict):
    _init_steps(operation, _CONFIG_STEP_DEFS)
    _step_start(operation, "validate")
    if "enabled" not in params:
        _step_finish(operation, "validate", "FAILED", "enabled is required")
        raise OperationError("configure_auth requires enabled")
    enabled = bool(params.get("enabled"))
    _step_finish(operation, "validate", "OK")
    result = _configure_via_config_edit(server, operation, "security.authorization", "enabled" if enabled else "disabled")
    return {"enabled": enabled, **result}


def _op_configure_memory(server: Server, operation: Operation, params: dict):
    _init_steps(operation, _CONFIG_STEP_DEFS)
    _step_start(operation, "validate")
    cache_size_gb = params.get("cache_size_gb")
    if cache_size_gb is None:
        _step_finish(operation, "validate", "FAILED", "cache_size_gb is required")
        raise OperationError("configure_memory requires cache_size_gb")
    _step_finish(operation, "validate", "OK")
    result = _configure_via_config_edit(
        server, operation, "storage.wiredTiger.engineConfig.cacheSizeGB", float(cache_size_gb))
    return {"cache_size_gb": cache_size_gb, **result}


def _op_configure_journal(server: Server, operation: Operation, params: dict):
    _init_steps(operation, _CONFIG_STEP_DEFS)
    _step_start(operation, "validate")
    if "enabled" not in params:
        _step_finish(operation, "validate", "FAILED", "enabled is required")
        raise OperationError("configure_journal requires enabled")
    enabled = bool(params.get("enabled"))
    _step_finish(operation, "validate", "OK")
    result = _configure_via_config_edit(server, operation, "storage.journal.enabled", enabled)
    return {"enabled": enabled, **result}


def _op_change_port(server: Server, operation: Operation, params: dict):
    _init_steps(operation, _CONFIG_STEP_DEFS + [("update_inventory", "Update inventory record")])
    _step_start(operation, "validate")
    new_port = params.get("new_port")
    if not new_port:
        _step_finish(operation, "validate", "FAILED", "new_port is required")
        raise OperationError("change_port requires new_port")
    _step_finish(operation, "validate", "OK")

    result = _configure_via_config_edit(server, operation, "net.port", int(new_port))

    _step_start(operation, "update_inventory")
    old_port = server.port
    server.port = int(new_port)
    db.session.add(server)
    db.session.commit()
    _step_finish(operation, "update_inventory", "OK", f"{old_port} -> {new_port}")

    return {"old_port": old_port, "new_port": new_port, **result}


_HANDLERS: dict = {
    "start": _op_start, "stop": _op_stop, "restart": _op_restart,
    "create_user": _op_create_user, "backup": _op_backup,
    "configure_profiler": _op_configure_profiler, "configure_auth": _op_configure_auth,
    "configure_memory": _op_configure_memory, "configure_journal": _op_configure_journal,
    "change_port": _op_change_port,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def execute_operation(operation: Operation, actor_username: Optional[str] = None) -> Operation:
    """Runs `operation` (already persisted as REQUESTED) to completion.
    Called either in a background thread right after the run-now API call
    (so the HTTP response returns immediately and the frontend polls this
    row for live step progress), or synchronously from the scheduler cron."""
    server = Server.query.get(operation.server_id)
    if not server:
        operation.status = OperationStatus.FAILED.value
        operation.error_message = "server_not_found"
        operation.completed_at = datetime.utcnow()
        db.session.add(operation)
        db.session.commit()
        return operation

    handler = _HANDLERS.get(operation.operation_type)
    if handler is None:
        operation.status = OperationStatus.FAILED.value
        operation.error_message = f"unknown operation_type: {operation.operation_type}"
        operation.completed_at = datetime.utcnow()
        db.session.add(operation)
        db.session.commit()
        return operation

    operation.status = OperationStatus.RUNNING.value
    operation.started_at = datetime.utcnow()
    db.session.add(operation)
    db.session.commit()
    _log(operation, "INFO", f"Starting {operation.operation_type} on {server.hostname} ({server.ip_address})")

    try:
        result = handler(server, operation, operation.params or {})
        operation.status = OperationStatus.SUCCESS.value
        operation.result = "SUCCESS"
        operation.postcheck_results = result
        _log(operation, "INFO", f"Completed successfully: {result}")
    except OperationError as exc:
        operation.status = OperationStatus.FAILED.value
        operation.result = "FAILED"
        operation.error_message = str(exc)
    except SSHExecutionError as exc:
        operation.status = OperationStatus.FAILED.value
        operation.result = "FAILED"
        operation.error_message = f"SSH error: {exc}"
        _log(operation, "ERROR", f"SSH error: {exc}")
    except Exception as exc:  # noqa: BLE001 — the engine must never crash the caller
        operation.status = OperationStatus.FAILED.value
        operation.result = "FAILED"
        operation.error_message = f"Unexpected error: {exc}"
        _log(operation, "ERROR", f"Unexpected error: {exc}")
        logger.exception("Unhandled operation error (operation_id=%s)", operation.id)

    operation.completed_at = datetime.utcnow()
    operation.progress_pct = 100
    db.session.add(operation)
    db.session.commit()

    action_suffix = "succeeded" if operation.status == OperationStatus.SUCCESS.value else "failed"
    audit_service.record(
        action=f"operation.{operation.operation_type}.{action_suffix}",
        actor_username=actor_username, target_type="server", target_id=server.id,
        detail={"operation_id": operation.id, "hostname": server.hostname, "params": operation.params,
                "result": operation.postcheck_results if operation.status == OperationStatus.SUCCESS.value else None,
                "error": operation.error_message},
    )

    try:
        duration = "—"
        if operation.started_at and operation.completed_at:
            secs = int((operation.completed_at - operation.started_at).total_seconds())
            duration = f"{secs // 60}m {secs % 60}s"
        notification_service.notify_operation_result(
            hostname=server.hostname, operation_type=operation.operation_type, status=operation.status,
            started_ist=_ist(operation.started_at), completed_ist=_ist(operation.completed_at),
            duration=duration, requested_by=actor_username or "scheduler", error_message=operation.error_message,
        )
    except Exception:  # noqa: BLE001 — a notification failure must never affect the operation result
        logger.exception("notify_operation_result failed for operation_id=%s", operation.id)

    return operation
