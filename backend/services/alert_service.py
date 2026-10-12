"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-12
Script Path : /data/database-management/backend/services/alert_service.py
Description : Turns new audit_logs rows into Alert rows (generation), then
               attempts delivery of pending alerts (dispatch). audit_logs is
               never written to by this module — see models.py Alert /
               AlertPollState for why.

               Meant to be driven by scripts/poll_alerts.py on a schedule
               (cron/systemd timer, every 1 min — see deploy/README.md
               "Alert polling"). run_poll_cycle() is also exposed to a
               manual "Check now" button in the UI (POST /api/alerts/poll)
               for testing before a schedule is wired up; both paths call
               the exact same code.
"""

import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import text

from extensions import db
from models import AuditLog, Alert, AlertPollState, AlertStatus
from services.alert_rules import match_rule

logger = logging.getLogger("atlas.alerts")

# Any single postgres integer works as the advisory-lock key; it just needs
# to be unique to this job so it never collides with a lock some other part
# of the app might take. Picked arbitrarily.
_ADVISORY_LOCK_KEY = 725_190_001
_MAX_DISPATCH_ATTEMPTS = 5
_GENERATE_BATCH_SIZE = 500


def _get_or_create_cursor() -> AlertPollState:
    state = AlertPollState.query.get(1)
    if not state:
        state = AlertPollState(id=1, last_audit_id=0)
        db.session.add(state)
        db.session.commit()
    return state


def generate_pending_alerts() -> dict:
    """Scan audit_logs forward from the last cursor position, create an
    Alert row (status=PENDING) for every row that matches a rule, then
    advance the cursor past everything it looked at — including rows that
    matched nothing, so they're never re-scanned again."""
    state = _get_or_create_cursor()
    rows = (
        AuditLog.query.filter(AuditLog.id > state.last_audit_id)
        .order_by(AuditLog.id.asc())
        .limit(_GENERATE_BATCH_SIZE)
        .all()
    )

    created = 0
    for row in rows:
        rule = match_rule(row.action, row.detail)
        if rule:
            row_dict = {
                "actor_username": row.actor_username,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "detail": row.detail,
                "source_ip": row.source_ip,
            }
            db.session.add(Alert(
                audit_log_id=row.id,
                ts=row.ts,
                rule_code=rule.code,
                severity=rule.severity,
                title=rule.title(row_dict),
                message=rule.message(row_dict),
                action=row.action,
                actor_username=row.actor_username,
                target_type=row.target_type,
                target_id=row.target_id,
                status=AlertStatus.PENDING.value,
            ))
            created += 1
        state.last_audit_id = row.id

    state.last_run_at = datetime.utcnow()
    db.session.commit()
    return {"scanned": len(rows), "created": created, "cursor": state.last_audit_id}


# ---------------------------------------------------------------------------
# Dispatch — pluggable channels. Nothing is configured out of the box except
# "log" (always on, zero setup) so alerts show up in the UI immediately. Add
# ALERT_CHANNELS=log,email and the SMTP_* vars once real notification infra
# (mailbox, Slack webhook, etc.) is decided — see deploy/README.md.
# ---------------------------------------------------------------------------
def _channels_from_config() -> list:
    import os
    raw = os.environ.get("ALERT_CHANNELS", "log")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _send_log(alert: Alert) -> None:
    logger.warning("ALERT [%s] %s — %s", alert.severity, alert.title, alert.message)


def _send_email(alert: Alert) -> None:
    import os
    host = os.environ.get("SMTP_HOST")
    to_addr = os.environ.get("ALERT_EMAIL_TO")
    if not host or not to_addr:
        raise RuntimeError("email channel enabled but SMTP_HOST / ALERT_EMAIL_TO not set")
    from_addr = os.environ.get("SMTP_FROM", "mongofleet@localhost")
    port = int(os.environ.get("SMTP_PORT", "25"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")

    msg = MIMEText(alert.message or "")
    msg["Subject"] = f"[MongoFleet] [{alert.severity}] {alert.title}"
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP(host, port, timeout=10) as server:
        server.ehlo()
        if user and password:
            server.starttls()
            server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())


_SENDERS = {"log": _send_log, "email": _send_email}


def dispatch_pending_alerts() -> dict:
    channels = _channels_from_config()
    pending = (
        Alert.query.filter(
            Alert.status.in_([AlertStatus.PENDING.value, AlertStatus.FAILED.value]),
            Alert.attempts < _MAX_DISPATCH_ATTEMPTS,
        )
        .order_by(Alert.id.asc())
        .all()
    )

    sent, failed = 0, 0
    for alert in pending:
        alert.attempts += 1
        last_error: Optional[str] = None
        for channel in channels:
            sender = _SENDERS.get(channel)
            if not sender:
                last_error = f"unknown channel '{channel}'"
                continue
            try:
                sender(alert)
                alert.channel = channel
            except Exception as exc:  # noqa: BLE001 — any channel failure just marks FAILED for retry
                last_error = f"{channel}: {exc}"

        if last_error and "log" not in channels:
            # only real failure if the always-on 'log' channel wasn't enough
            alert.status = AlertStatus.FAILED.value
            alert.error_message = last_error
            failed += 1
        else:
            alert.status = AlertStatus.SENT.value
            alert.sent_at = datetime.utcnow()
            alert.error_message = None
            sent += 1
        db.session.commit()

    return {"considered": len(pending), "sent": sent, "failed": failed}


def run_poll_cycle() -> dict:
    """One full cycle: generate alerts for new audit rows, then dispatch
    whatever is pending. Wrapped in a Postgres advisory lock so an overlapping
    cron run (this one still running past its minute) exits immediately
    instead of racing the in-progress run."""
    got_lock = db.session.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY}
    ).scalar()
    if not got_lock:
        logger.info("alert poll cycle skipped: previous run still holds the advisory lock")
        return {"skipped": True}

    try:
        gen_result = generate_pending_alerts()
        dispatch_result = dispatch_pending_alerts()
        return {"skipped": False, "generate": gen_result, "dispatch": dispatch_result}
    finally:
        db.session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        db.session.commit()
