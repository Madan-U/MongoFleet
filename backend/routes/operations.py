"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-15
Script Path : /data/database-management/backend/routes/operations.py
Description : Operations API — run a supported operation immediately, list/
               inspect past runs (Operation + OperationLog), and manage
               schedules (one-time future or recurring) that the scheduler
               cron turns into runs later. Backs operations.html.
"""

from datetime import datetime, timedelta, timezone, time as dt_time
import threading

from flask import Blueprint, current_app, request, jsonify

from extensions import db
from models import Operation, OperationLog, ScheduledOperation, Server, AuditLog
from security import login_required, permission_required, current_user
from services import audit_service, mongo_service, operations_service, settings_service

bp = Blueprint("operations", __name__, url_prefix="/api/operations")

# The app's single scheduling timezone (section 3 of the ops spec). India has
# no DST, so this constant offset is safe to use directly rather than
# depending on a tz database being installed on the box.
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _parse_client_datetime_to_utc(raw: str) -> datetime:
    """Accepts either a timezone-aware ISO string (any offset) or a naive
    one — naive is treated as IST, since that's what the scheduling UI
    always sends. Returns a naive UTC datetime for storage."""
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt - _IST_OFFSET


def _ist_recurring_to_utc(day_of_week_ist, hour: int, minute: int):
    """Converts a recurring IST time-of-day (+ optional IST weekday) to the
    UTC time-of-day + weekday actually stored. Necessary because IST is
    UTC+5:30 — a time before 05:30 IST falls on the *previous* UTC day, so
    the weekday must shift too, not just the clock time."""
    total_min_ist = hour * 60 + minute
    total_min_utc = (total_min_ist - 330) % 1440
    utc_time = dt_time(hour=total_min_utc // 60, minute=total_min_utc % 60)
    if day_of_week_ist is None:
        return utc_time, None
    day_shift = -1 if (total_min_ist - 330) < 0 else 0
    return utc_time, (day_of_week_ist + day_shift) % 7


def _utc_recurring_to_ist(day_of_week_utc, time_of_day_utc):
    """Inverse of _ist_recurring_to_utc — for display only."""
    if time_of_day_utc is None:
        return None, None
    total_min_utc = time_of_day_utc.hour * 60 + time_of_day_utc.minute
    total_min_ist = (total_min_utc + 330) % 1440
    ist_str = f"{total_min_ist // 60:02d}:{total_min_ist % 60:02d}"
    if day_of_week_utc is None:
        return None, ist_str
    day_shift = 1 if (total_min_utc + 330) >= 1440 else 0
    return (day_of_week_utc + day_shift) % 7, ist_str

# Full set from the ops spec (section 2), plus "custom" via ?since=&until=
# (ISO 8601, UTC) which takes priority over `range` when both are present.
_RANGE_PRESETS = {
    "30s": timedelta(seconds=30), "1m": timedelta(minutes=1), "5m": timedelta(minutes=5),
    "10m": timedelta(minutes=10), "30m": timedelta(minutes=30), "1h": timedelta(hours=1),
    "8h": timedelta(hours=8), "12h": timedelta(hours=12), "24h": timedelta(hours=24),
    "2d": timedelta(days=2), "3d": timedelta(days=3), "7d": timedelta(days=7),
    "14d": timedelta(days=14), "21d": timedelta(days=21), "30d": timedelta(days=30),
}


def _resolve_range():
    """Returns (since, until, error). Priority: explicit ?since=&until= (ISO
    8601 UTC) for the custom-range picker, else a ?range= preset key from
    _RANGE_PRESETS, defaulting to 24h. range=all skips filtering (since=None)."""
    since_raw = request.args.get("since")
    until_raw = request.args.get("until")
    if since_raw:
        try:
            since = datetime.fromisoformat(since_raw)
            until = datetime.fromisoformat(until_raw) if until_raw else datetime.utcnow()
        except ValueError:
            return None, None, "invalid_since_or_until"
        return since, until, None

    range_key = request.args.get("range", "24h")
    now = datetime.utcnow()
    if range_key == "all":
        return None, now, None
    delta = _RANGE_PRESETS.get(range_key)
    if not delta:
        return None, None, "invalid_range"
    return now - delta, now, None

# Which RBAC permission a given operation_type requires. Reuses existing
# codes (server.restart, server.configuration.modify) where they already
# cover the action, adds the two new ones (server.backup, server.user.create)
# only where nothing existing fit.
_PERMISSION_FOR_TYPE = {
    "start": "server.restart",
    "stop": "server.restart",
    "restart": "server.restart",
    "create_user": "server.user.create",
    "backup": "server.backup",
    "configure_profiler": "server.configuration.modify",
    "configure_auth": "server.configuration.modify",
    "configure_memory": "server.configuration.modify",
    "configure_journal": "server.configuration.modify",
    "change_port": "server.configuration.modify",
}


def _require_permission_for_type(operation_type: str):
    """Returns None if the current user may perform operation_type, else an
    (response, status) tuple to return immediately."""
    perm = _PERMISSION_FOR_TYPE.get(operation_type)
    if perm is None:
        return jsonify({"error": "unknown_operation_type"}), 400
    user = current_user()
    if not user or not user.is_active:
        return jsonify({"error": "authentication_required"}), 401
    if not user.has_permission(perm):
        return jsonify({"error": "permission_denied", "required": perm}), 403
    return None


def _step_for_api(step: dict) -> dict:
    """op.steps stores naive-UTC iso strings for started_at/completed_at that
    operations_service.py re-parses internally with datetime.fromisoformat()
    for duration math — so we don't touch that stored format. We only append
    "Z" on the way out to the API so the frontend's `new Date()` treats these
    as UTC instead of misreading them as browser-local time."""
    out = dict(step)
    for key in ("started_at", "completed_at"):
        if out.get(key) and not out[key].endswith("Z"):
            out[key] = out[key] + "Z"
    return out


def _operation_to_dict(op: Operation, include_logs: bool = False) -> dict:
    from models import User
    requester = User.query.get(op.requested_by) if op.requested_by else None
    d = {
        "id": op.id,
        "triggered_by_schedule_id": op.triggered_by_schedule_id,
        "operation_type": op.operation_type,
        "server_id": op.server_id,
        "hostname": op.server.hostname if op.server else None,
        "requested_by": op.requested_by,
        "requested_by_username": requester.username if requester else None,
        "status": op.status,
        "current_step": op.current_step,
        "progress_pct": op.progress_pct,
        "steps": [_step_for_api(step) for step in (op.steps or [])],
        "params": op.params,
        "precheck_results": op.precheck_results,
        "postcheck_results": op.postcheck_results,
        "result": op.result,
        "error_message": op.error_message,
        "started_at": op.started_at.isoformat() + "Z" if op.started_at else None,
        "completed_at": op.completed_at.isoformat() + "Z" if op.completed_at else None,
        "created_at": op.created_at.isoformat() + "Z" if op.created_at else None,
    }
    if include_logs:
        logs = OperationLog.query.filter_by(operation_id=op.id).order_by(OperationLog.ts).all()
        d["logs"] = [{"ts": l.ts.isoformat() + "Z", "level": l.level, "message": l.message} for l in logs]
    return d


def _next_recurring_run_utc(day_of_week_utc, time_of_day_utc, now=None):
    """Next UTC instant a RECURRING schedule fires, scanning up to a week
    ahead. Returns None when the schedule has no time set."""
    if time_of_day_utc is None:
        return None
    now = now or datetime.utcnow()
    for offset in range(8):
        candidate_day = now + timedelta(days=offset)
        if day_of_week_utc is not None and candidate_day.weekday() != day_of_week_utc:
            continue
        candidate = candidate_day.replace(
            hour=time_of_day_utc.hour, minute=time_of_day_utc.minute, second=0, microsecond=0)
        if candidate <= now:
            continue
        return candidate
    return None


def _next_interval_run_utc(last_triggered_at, created_at, interval_minutes, run_at=None, now=None):
    """Next UTC instant an INTERVAL schedule fires."""
    if not interval_minutes:
        return None
    now = now or datetime.utcnow()
    if last_triggered_at is None:
        if run_at:
            return run_at if run_at > now else now
        reference = created_at
    else:
        reference = last_triggered_at
    step = timedelta(minutes=interval_minutes)
    next_run = reference + step
    while next_run <= now:
        next_run += step
    return next_run


def _schedule_to_dict(s: ScheduledOperation) -> dict:
    day_ist, time_ist = _utc_recurring_to_ist(s.day_of_week, s.time_of_day)
    last_op = s.resulting_operation

    next_run = None
    if s.is_active and not s.cancelled_at:
        if s.schedule_type == "RECURRING":
            next_run = _next_recurring_run_utc(s.day_of_week, s.time_of_day)
        elif s.schedule_type == "INTERVAL":
            next_run = _next_interval_run_utc(s.last_triggered_at, s.created_at, s.interval_minutes, s.run_at)

    return {
        "id": s.id,
        "operation_type": s.operation_type,
        "server_id": s.server_id,
        "hostname": s.server.hostname if s.server else None,
        "params": s.params,
        "schedule_type": s.schedule_type,
        "run_at": s.run_at.isoformat() + "Z" if s.run_at else None,     # UTC — frontend renders in IST
        "day_of_week": s.day_of_week,                                   # UTC weekday (0=Mon..6=Sun), as stored
        "time_of_day": s.time_of_day.strftime("%H:%M") if s.time_of_day else None,  # UTC, as stored
        "day_of_week_ist": day_ist,                                     # convenience — already converted
        "time_of_day_ist": time_ist,
        "interval_minutes": s.interval_minutes,
        "is_active": s.is_active,
        "cancelled_at": s.cancelled_at.isoformat() + "Z" if s.cancelled_at else None,
        "status": "CANCELLED" if s.cancelled_at else ("ENABLED" if s.is_active else "DISABLED"),
        "last_triggered_at": s.last_triggered_at.isoformat() + "Z" if s.last_triggered_at else None,
        "resulting_operation_id": s.resulting_operation_id,
        "last_run_status": last_op.status if last_op else None,
        "next_run_at": next_run.isoformat() + "Z" if next_run else None,
        "created_at": s.created_at.isoformat() + "Z" if s.created_at else None,
        "updated_at": s.updated_at.isoformat() + "Z" if s.updated_at else None,
    }


# Operation types that carry a real safety risk of interrupting in-flight
# work, so they get the long-running-query pre-check + explicit force/cancel
# gate (section 5). Every other type just runs.
_RISKY_TYPES_REQUIRING_PRECHECK = ("restart", "stop")


# ---------------------------------------------------------------------------
# Run now (one-time immediate) — executes in a background thread so the HTTP
# response returns right away; the frontend polls GET /api/operations/<id>
# for live step progress (steps[], current_step, progress_pct) until the
# status reaches SUCCESS/FAILED. No fake progress bar — this is the real
# Operation row being updated by operations_service as each step runs.
# ---------------------------------------------------------------------------
@bp.post("")
@login_required
def run_now():
    payload = request.get_json(silent=True) or {}
    operation_type = payload.get("operation_type")
    server_id = payload.get("server_id")
    params = dict(payload.get("params") or {})
    force = bool(payload.get("force"))

    if operation_type not in operations_service.OPERATION_TYPES:
        return jsonify({"error": "invalid_operation_type", "allowed": operations_service.OPERATION_TYPES}), 400
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400

    denied = _require_permission_for_type(operation_type)
    if denied:
        return denied

    server = Server.query.get(server_id)
    if not server:
        return jsonify({"error": "server_not_found"}), 404

    user = current_user()

    # Safety gate — block BEFORE creating any Operation row, so a cancelled
    # attempt leaves no half-run trace. Nothing is auto-forced; the caller
    # must resubmit with force=true after the user explicitly confirms.
    if operation_type in _RISKY_TYPES_REQUIRING_PRECHECK and not force:
        threshold = settings_service.get_long_running_threshold_minutes()
        precheck = mongo_service.check_long_running_ops(
            server.ip_address, server.port, server.mongo_credential_ref, threshold)
        if precheck["blocking"]:
            audit_service.record(
                action=f"operation.{operation_type}.confirmation_required",
                actor_user_id=user.id, actor_username=user.username,
                target_type="server", target_id=server.id,
                detail={"operation_type": operation_type, "precheck": precheck},
                source_ip=request.remote_addr,
            )
            return jsonify({"requires_confirmation": True, "warning": precheck}), 409

    if force:
        params["force"] = True

    operation = Operation(
        operation_type=operation_type, server_id=server.id,
        requested_by=user.id, status="REQUESTED", params=params,
    )
    db.session.add(operation)
    db.session.commit()

    audit_service.record(
        action=f"operation.{operation_type}.requested", actor_user_id=user.id, actor_username=user.username,
        target_type="server", target_id=server.id, detail={"operation_id": operation.id, "params": params},
        source_ip=request.remote_addr,
    )

    operation_id = operation.id
    username = user.username
    app_obj = current_app._get_current_object()

    def _run_in_background():
        with app_obj.app_context():
            op = Operation.query.get(operation_id)
            if op:
                operations_service.execute_operation(op, actor_username=username)

    threading.Thread(target=_run_in_background, daemon=True, name=f"op-{operation_id}").start()

    return jsonify(_operation_to_dict(operation)), 202


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@bp.get("")
@login_required
def list_operations():
    since, until, err = _resolve_range()
    if err:
        return jsonify({"error": err}), 400

    query = Operation.query
    if since is not None:
        query = query.filter(Operation.created_at >= since, Operation.created_at <= until)
    server_id = request.args.get("server_id")
    if server_id:
        query = query.filter_by(server_id=server_id)
    status = request.args.get("status")
    if status:
        query = query.filter(Operation.status.in_([s.upper() for s in status.split(",")]))
    operation_type = request.args.get("operation_type")
    if operation_type:
        query = query.filter_by(operation_type=operation_type)

    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("page_size", 50)), 1), 200)
    total = query.count()
    rows = query.order_by(Operation.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return jsonify({
        "operations": [_operation_to_dict(op) for op in rows],
        "total": total, "page": page, "page_size": page_size,
        "range": {"since": since.isoformat() if since else None, "until": until.isoformat()},
    })


@bp.get("/<operation_id>")
@login_required
def get_operation(operation_id):
    op = Operation.query.get(operation_id)
    if not op:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_operation_to_dict(op, include_logs=True))


# ---------------------------------------------------------------------------
# Schedules (one-time future, or recurring)
# ---------------------------------------------------------------------------
@bp.get("/schedules")
@login_required
def list_schedules():
    query = ScheduledOperation.query
    server_id = request.args.get("server_id")
    if server_id:
        query = query.filter_by(server_id=server_id)
    active_only = request.args.get("active_only", "true").lower() != "false"
    if active_only:
        query = query.filter_by(is_active=True)
    rows = query.order_by(ScheduledOperation.created_at.desc()).all()
    return jsonify({"schedules": [_schedule_to_dict(s) for s in rows], "count": len(rows)})


@bp.post("/schedules")
@login_required
def create_schedule():
    payload = request.get_json(silent=True) or {}
    operation_type = payload.get("operation_type")
    server_id = payload.get("server_id")
    schedule_type = payload.get("schedule_type")  # ONE_TIME | RECURRING
    params = payload.get("params") or {}

    if operation_type not in operations_service.OPERATION_TYPES:
        return jsonify({"error": "invalid_operation_type", "allowed": operations_service.OPERATION_TYPES}), 400
    if not server_id:
        return jsonify({"error": "server_id_required"}), 400
    if schedule_type not in ("ONE_TIME", "RECURRING", "INTERVAL"):
        return jsonify({"error": "schedule_type_must_be_ONE_TIME_RECURRING_or_INTERVAL"}), 400

    user = current_user()
    if not user or not user.is_active or not user.has_permission("operation.schedule"):
        return jsonify({"error": "permission_denied", "required": "operation.schedule"}), 403
    # Also require the permission for the underlying operation itself —
    # scheduling something you couldn't run yourself isn't allowed.
    denied = _require_permission_for_type(operation_type)
    if denied:
        return denied

    server = Server.query.get(server_id)
    if not server:
        return jsonify({"error": "server_not_found"}), 404

    sched = ScheduledOperation(
        operation_type=operation_type, server_id=server.id, params=params,
        schedule_type=schedule_type, created_by=user.id, is_active=True,
    )

    if schedule_type == "ONE_TIME":
        run_at_raw = payload.get("run_at")  # IST wall-clock (or any tz-aware ISO string)
        if not run_at_raw:
            return jsonify({"error": "run_at_required_for_ONE_TIME"}), 400
        try:
            sched.run_at = _parse_client_datetime_to_utc(run_at_raw)
        except ValueError:
            return jsonify({"error": "invalid_run_at"}), 400
        if sched.run_at <= datetime.utcnow():
            return jsonify({"error": "run_at_must_be_in_the_future"}), 400
    elif schedule_type == "RECURRING":
        time_raw = payload.get("time_of_day")  # "HH:MM" in IST
        if not time_raw:
            return jsonify({"error": "time_of_day_required_for_RECURRING"}), 400
        try:
            hour, minute = (int(p) for p in time_raw.split(":"))
        except (ValueError, TypeError):
            return jsonify({"error": "invalid_time_of_day_expected_HH_MM"}), 400
        day_of_week_ist = payload.get("day_of_week")  # 0=Mon..6=Sun IST, or null for every day
        if day_of_week_ist is not None:
            try:
                day_of_week_ist = int(day_of_week_ist)
            except (ValueError, TypeError):
                return jsonify({"error": "invalid_day_of_week"}), 400
            if not 0 <= day_of_week_ist <= 6:
                return jsonify({"error": "day_of_week_must_be_0_to_6"}), 400
        sched.time_of_day, sched.day_of_week = _ist_recurring_to_utc(day_of_week_ist, hour, minute)
    else:  # INTERVAL
        minutes = payload.get("interval_minutes")
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            return jsonify({"error": "interval_minutes_required_and_must_be_an_integer"}), 400
        if minutes < 1:
            return jsonify({"error": "interval_minutes_must_be_at_least_1"}), 400
        sched.interval_minutes = minutes
        
        run_at_raw = payload.get("run_at")
        if run_at_raw:
            try:
                sched.run_at = _parse_client_datetime_to_utc(run_at_raw)
            except ValueError:
                return jsonify({"error": "invalid_run_at"}), 400
            if sched.run_at <= datetime.utcnow():
                return jsonify({"error": "run_at_must_be_in_the_future"}), 400

    db.session.add(sched)
    db.session.commit()

    audit_service.record(
        action="operation.schedule.created", actor_user_id=user.id, actor_username=user.username,
        target_type="server", target_id=server.id,
        detail={"schedule_id": sched.id, "operation_type": operation_type,
                "schedule_type": schedule_type, "params": params},
        source_ip=request.remote_addr,
    )
    return jsonify(_schedule_to_dict(sched)), 201


@bp.patch("/schedules/<int:schedule_id>")
@login_required
def edit_schedule(schedule_id):
    """Edit/update/enable/disable a scheduled operation. Admin/DBA only —
    gated on the same 'operation.schedule' permission used to create one,
    which only the senior_dba/dba/admin roles carry (see
    seed_roles_permissions.py). Every change is captured old->new in the
    audit log, matching the ops-spec example."""
    sched = ScheduledOperation.query.get(schedule_id)
    if not sched:
        return jsonify({"error": "not_found"}), 404
    user = current_user()
    if not user or not user.is_active or not user.has_permission("operation.schedule"):
        return jsonify({"error": "permission_denied", "required": "operation.schedule"}), 403
    if sched.cancelled_at:
        return jsonify({"error": "schedule_cancelled", "message": "This schedule was cancelled and can no longer be edited."}), 409

    payload = request.get_json(silent=True) or {}
    before = _schedule_to_dict(sched)

    # Swapping the operation type is only allowed among the no-param
    # lifecycle ops (start/stop/restart) — e.g. "I scheduled a start but
    # meant stop". Types that take their own params (backup, create_user,
    # configure_*, change_port) need a fresh schedule instead, since the
    # existing params wouldn't necessarily make sense for the new type.
    _SWAPPABLE_OP_TYPES = {"start", "stop", "restart"}
    if "operation_type" in payload and payload["operation_type"] != sched.operation_type:
        new_type = payload["operation_type"]
        if sched.operation_type not in _SWAPPABLE_OP_TYPES or new_type not in _SWAPPABLE_OP_TYPES:
            return jsonify({
                "error": "operation_type_not_swappable",
                "message": "Only start/stop/restart can be changed on an existing schedule — cancel and create a new one for other operation types.",
            }), 400
        sched.operation_type = new_type

    if "params" in payload:
        sched.params = payload["params"] or {}

    if sched.schedule_type in ("ONE_TIME", "INTERVAL") and "run_at" in payload:
        if not payload["run_at"]:
            sched.run_at = None
        else:
            try:
                new_run_at = _parse_client_datetime_to_utc(payload["run_at"])
            except ValueError:
                return jsonify({"error": "invalid_run_at"}), 400
            if new_run_at <= datetime.utcnow():
                return jsonify({"error": "run_at_must_be_in_the_future"}), 400
            sched.run_at = new_run_at

    if sched.schedule_type == "RECURRING" and ("time_of_day" in payload or "day_of_week" in payload):
        time_raw = payload.get("time_of_day", before["time_of_day_ist"])
        try:
            hour, minute = (int(p) for p in time_raw.split(":"))
        except (ValueError, TypeError, AttributeError):
            return jsonify({"error": "invalid_time_of_day_expected_HH_MM"}), 400
        day_of_week_ist = payload.get("day_of_week", before["day_of_week_ist"])
        if day_of_week_ist is not None:
            try:
                day_of_week_ist = int(day_of_week_ist)
            except (ValueError, TypeError):
                return jsonify({"error": "invalid_day_of_week"}), 400
        sched.time_of_day, sched.day_of_week = _ist_recurring_to_utc(day_of_week_ist, hour, minute)

    if sched.schedule_type == "INTERVAL" and "interval_minutes" in payload:
        minutes = payload.get("interval_minutes")
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            return jsonify({"error": "interval_minutes_must_be_an_integer"}), 400
        if minutes < 1:
            return jsonify({"error": "interval_minutes_must_be_at_least_1"}), 400
        sched.interval_minutes = minutes

    if "is_active" in payload:
        sched.is_active = bool(payload["is_active"])

    sched.updated_by = user.id
    sched.updated_at = datetime.utcnow()
    db.session.add(sched)
    db.session.commit()

    after = _schedule_to_dict(sched)
    audit_service.record(
        action="operation.schedule.modified", actor_user_id=user.id, actor_username=user.username,
        target_type="server", target_id=sched.server_id,
        detail={"schedule_id": sched.id, "before": before, "after": after, "comment": payload.get("comment"), "change_summary": payload.get("change_summary")},
        source_ip=request.remote_addr,
    )
    return jsonify(after)


@bp.get("/schedules/<int:schedule_id>/history")
@login_required
def schedule_history(schedule_id):
    sched = ScheduledOperation.query.get(schedule_id)
    if not sched:
        return jsonify({"error": "not_found"}), 404

    rows = (
        AuditLog.query
        .filter(AuditLog.action.like("operation.schedule.%"))
        .filter(AuditLog.target_type == "server")
        .filter(AuditLog.target_id == str(sched.server_id))
        .order_by(AuditLog.ts.desc())
        .all()
    )
    history = []
    for r in rows:
        detail = r.detail or {}
        if detail.get("schedule_id") != schedule_id:
            continue
        history.append({
            "changed_by": r.actor_username,
            "changed_at": r.ts.isoformat() if r.ts else None,
            "change_summary": detail.get("change_summary"),
            "comment": detail.get("comment"),
            "action": r.action,
        })
    return jsonify({"history": history})

@bp.delete("/schedules/<int:schedule_id>")
@login_required
def cancel_schedule(schedule_id):
    sched = ScheduledOperation.query.get(schedule_id)
    if not sched:
        return jsonify({"error": "not_found"}), 404
    user = current_user()
    # Admin/DBA (operation.schedule) can cancel anything; anyone else may
    # only cancel a schedule they created themselves.
    if not (user.has_permission("operation.schedule") or sched.created_by == user.id):
        return jsonify({"error": "permission_denied"}), 403
    if sched.cancelled_at:
        return jsonify({"error": "already_cancelled"}), 409

    sched.is_active = False
    sched.cancelled_at = datetime.utcnow()
    sched.updated_by = user.id
    sched.updated_at = datetime.utcnow()
    db.session.add(sched)
    db.session.commit()

    audit_service.record(
        action="operation.schedule.cancelled", actor_user_id=user.id, actor_username=user.username,
        target_type="server", target_id=sched.server_id,
        detail={"schedule_id": sched.id, "operation_type": sched.operation_type},
        source_ip=request.remote_addr,
    )
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Admin-configurable safety threshold (section 5) — the "long-running query"
# minutes cutoff used by the restart/stop pre-check.
# ---------------------------------------------------------------------------
@bp.get("/settings/long-running-threshold")
@login_required
def get_threshold():
    return jsonify({"threshold_minutes": settings_service.get_long_running_threshold_minutes()})


@bp.patch("/settings/long-running-threshold")
@login_required
def update_threshold():
    user = current_user()
    if not user or not user.has_permission("server.configuration.modify"):
        return jsonify({"error": "permission_denied", "required": "server.configuration.modify"}), 403
    payload = request.get_json(silent=True) or {}
    minutes = payload.get("threshold_minutes")
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return jsonify({"error": "threshold_minutes_must_be_an_integer"}), 400
    if minutes < 1:
        return jsonify({"error": "threshold_minutes_must_be_positive"}), 400
    settings_service.set_long_running_threshold_minutes(minutes, updated_by_user_id=user.id)
    audit_service.record(
        action="operation.settings.threshold_modified", actor_user_id=user.id, actor_username=user.username,
        target_type="system", target_id=None, detail={"threshold_minutes": minutes},
        source_ip=request.remote_addr,
    )
    return jsonify({"threshold_minutes": minutes})
