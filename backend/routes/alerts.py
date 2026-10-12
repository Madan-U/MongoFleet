"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-12
Script Path : /data/database-management/backend/routes/alerts.py
Description : Alerts API — list with time-range/severity/status filters,
               summary counts (for the sidebar badge), and a manual
               "run now" trigger for the poll cycle. Backs alerts.html.
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from sqlalchemy import func, or_

from extensions import db
from models import Alert
from security import login_required
from services import alert_service

bp = Blueprint("alerts", __name__, url_prefix="/api/alerts")

_RANGE_PRESETS = {
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def _resolve_range():
    """Returns (since, until) datetimes from ?range=30m|1h|6h|24h|7d|custom
    plus &from=&to= (ISO 8601) when range=custom. Defaults to 24h."""
    range_key = request.args.get("range", "24h")
    now = datetime.utcnow()

    if range_key == "custom":
        from_raw, to_raw = request.args.get("from"), request.args.get("to")
        try:
            since = datetime.fromisoformat(from_raw) if from_raw else now - timedelta(hours=24)
            until = datetime.fromisoformat(to_raw) if to_raw else now
        except ValueError:
            return None, None, "invalid_custom_range"
        return since, until, None

    delta = _RANGE_PRESETS.get(range_key)
    if not delta:
        return None, None, "invalid_range"
    return now - delta, now, None


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "audit_log_id": a.audit_log_id,
        "ts": a.ts.isoformat() + "Z",
        "severity": a.severity,
        "rule_code": a.rule_code,
        "title": a.title,
        "message": a.message,
        "action": a.action,
        "actor_username": a.actor_username,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "status": a.status,
        "channel": a.channel,
        "attempts": a.attempts,
        "error_message": a.error_message,
        "sent_at": a.sent_at.isoformat() + "Z" if a.sent_at else None,
    }


@bp.get("")
@login_required
def list_alerts():
    since, until, err = _resolve_range()
    if err:
        return jsonify({"error": err}), 400

    query = Alert.query.filter(Alert.ts >= since, Alert.ts <= until)

    severity = request.args.get("severity")
    if severity:
        query = query.filter(Alert.severity.in_([s.upper() for s in severity.split(",")]))

    status = request.args.get("status")
    if status:
        query = query.filter(Alert.status.in_([s.upper() for s in status.split(",")]))

    search = request.args.get("search")
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Alert.title.ilike(like), Alert.message.ilike(like), Alert.actor_username.ilike(like)
        ))

    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("page_size", 50)), 1), 200)

    total = query.count()
    rows = (
        query.order_by(Alert.ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for sev, cnt in (
        db.session.query(Alert.severity, func.count(Alert.id))
        .filter(Alert.ts >= since, Alert.ts <= until)
        .group_by(Alert.severity)
        .all()
    ):
        counts[sev] = cnt

    return jsonify({
        "alerts": [_alert_to_dict(a) for a in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "severity_counts": counts,
        "range": {"since": since.isoformat() + "Z", "until": until.isoformat() + "Z"},
    })


@bp.get("/summary")
@login_required
def summary():
    """Lightweight counts for the sidebar nav badge — unresolved (PENDING or
    FAILED) alerts, critical severity only, so the badge only lights up for
    things that actually still need attention."""
    unresolved_critical = Alert.query.filter(
        Alert.severity == "CRITICAL",
        Alert.status.in_(["PENDING", "FAILED"]),
    ).count()
    unresolved_total = Alert.query.filter(Alert.status.in_(["PENDING", "FAILED"])).count()
    return jsonify({
        "unresolved_critical": unresolved_critical,
        "unresolved_total": unresolved_total,
    })


@bp.post("/poll")
@login_required
def poll_now():
    """Manual trigger for the same cycle scripts/poll_alerts.py runs on a
    schedule — lets the UI's "Check now" button work before a cron/systemd
    timer is set up, without duplicating any logic."""
    result = alert_service.run_poll_cycle()
    return jsonify(result)
