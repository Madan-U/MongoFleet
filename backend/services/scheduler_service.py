"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-15
Script Path : /data/database-management/backend/services/scheduler_service.py
Description : Finds ScheduledOperation rows that are due right now and turns
               each into a real Operation via operations_service.execute_operation().
               Intended to run from scripts/run_scheduled_operations.py on a
               1-minute cron — see deploy/README.md "Scheduled operations
               cron". This module never executes anything itself; it only
               decides *whether* a schedule is due and hands off.
"""

import logging
from datetime import datetime, timedelta

from extensions import db
from models import Operation, OperationStatus, ScheduledOperation, User
from services import operations_service

logger = logging.getLogger("atlas.scheduler")

# How often the cron itself runs. A recurring schedule is considered "due"
# if we're within this many minutes of its target time and it hasn't
# already fired in that same window — this makes the match tolerant of the
# cron firing a few seconds late without ever double-firing.
FIRE_WINDOW_MINUTES = 1


def _due_one_time(now: datetime) -> list[ScheduledOperation]:
    return (
        ScheduledOperation.query
        .filter(ScheduledOperation.schedule_type == "ONE_TIME")
        .filter(ScheduledOperation.is_active.is_(True))
        .filter(ScheduledOperation.run_at <= now)
        .all()
    )


def _due_recurring(now: datetime) -> list[ScheduledOperation]:
    due = []
    candidates = (
        ScheduledOperation.query
        .filter(ScheduledOperation.schedule_type == "RECURRING")
        .filter(ScheduledOperation.is_active.is_(True))
        .all()
    )
    for sched in candidates:
        if sched.day_of_week is not None and sched.day_of_week != now.weekday():
            continue
        if sched.time_of_day is None:
            continue
        target_today = now.replace(
            hour=sched.time_of_day.hour, minute=sched.time_of_day.minute,
            second=0, microsecond=0,
        )
        if abs((now - target_today).total_seconds()) > FIRE_WINDOW_MINUTES * 60:
            continue
        # Already fired in this same window (e.g. cron ran twice in the
        # same minute, or the box caught up after being briefly down)?
        if sched.last_triggered_at and (now - sched.last_triggered_at) < timedelta(minutes=FIRE_WINDOW_MINUTES):
            continue
        due.append(sched)
    return due


def _due_interval(now: datetime) -> list[ScheduledOperation]:
    """An INTERVAL schedule is due once (now - reference) has reached
    interval_minutes, where reference is the last fire time, or created_at
    if it has never fired yet. This is elapsed-time based (not a fixed
    clock grid) — a schedule created at 10:03 with a 5-minute interval
    fires at 10:08, 10:13, ... regardless of wall-clock minute boundaries."""
    due = []
    candidates = (
        ScheduledOperation.query
        .filter(ScheduledOperation.schedule_type == "INTERVAL")
        .filter(ScheduledOperation.is_active.is_(True))
        .all()
    )
    for sched in candidates:
        if not sched.interval_minutes or sched.interval_minutes < 1:
            continue
        if sched.last_triggered_at is None:
            if sched.run_at:
                if now >= sched.run_at:
                    due.append(sched)
            elif now - sched.created_at >= timedelta(minutes=sched.interval_minutes):
                due.append(sched)
        elif now - sched.last_triggered_at >= timedelta(minutes=sched.interval_minutes):
            due.append(sched)
    return due


def _fire(sched: ScheduledOperation, now: datetime) -> Operation:
    operation = Operation(
        operation_type=sched.operation_type,
        server_id=sched.server_id,
        requested_by=sched.created_by,
        status=OperationStatus.REQUESTED.value,
        params=sched.params or {},
        triggered_by_schedule_id=sched.id,
    )
    db.session.add(operation)
    db.session.commit()

    actor = User.query.get(sched.created_by)
    operations_service.execute_operation(operation, actor_username=actor.username if actor else None)

    if sched.schedule_type == "ONE_TIME":
        sched.is_active = False
    sched.last_triggered_at = now
    sched.resulting_operation_id = operation.id
    db.session.add(sched)
    db.session.commit()
    return operation



def run_due_schedules() -> dict:
    """Entry point for the cron script. Returns a summary dict for logging."""
    now = datetime.utcnow()
    due = _due_one_time(now) + _due_recurring(now) + _due_interval(now)
    fired, failed = 0, 0
    for sched in due:
        try:
            op = _fire(sched, now)
            if op.status == OperationStatus.SUCCESS.value:
                fired += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001 — one bad schedule must not block the rest
            failed += 1
            logger.exception("Failed to fire scheduled_operation id=%s", sched.id)
    return {"checked": len(due), "fired": fired, "failed": failed}
