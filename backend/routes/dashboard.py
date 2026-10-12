"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/routes/dashboard.py
Description : Dashboard summary endpoint — aggregate counts computed live
               from the servers/server_health/operations/audit_logs tables.
               Returns zeros on an empty inventory rather than sample data.
"""

from flask import Blueprint, jsonify
from sqlalchemy import func

from extensions import db
from models import Server, ServerHealth, Operation, AuditLog
from security import login_required

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.get("/summary")
@login_required
def summary():
    total_servers = Server.query.filter_by(is_active=True).count()

    # Latest health row per server (empty inventory -> empty dict, not fake data)
    latest_health = {}
    for server_id, status in (
        db.session.query(ServerHealth.server_id, ServerHealth.status)
        .order_by(ServerHealth.server_id, ServerHealth.checked_at.desc())
        .all()
    ):
        latest_health.setdefault(server_id, status)

    status_counts = {"OK": 0, "WARN": 0, "CRITICAL": 0, "UNKNOWN": 0}
    for status in latest_health.values():
        status_counts[status] = status_counts.get(status, 0) + 1
    status_counts["UNKNOWN"] += max(total_servers - len(latest_health), 0)

    running_operations = Operation.query.filter(
        Operation.status.in_(["RUNNING", "QUEUED", "VERIFYING"])
    ).count()
    pending_approvals = Operation.query.filter_by(status="WAITING_FOR_APPROVAL").count()

    recent_audit = (
        AuditLog.query.order_by(AuditLog.ts.desc()).limit(10).all()
    )

    return jsonify({
        "total_servers": total_servers,
        "health_status_counts": status_counts,
        "running_operations": running_operations,
        "pending_approvals": pending_approvals,
        "recent_audit": [
            {
                "ts": a.ts.isoformat() + "Z",
                "action": a.action,
                "actor": a.actor_username,
                "target_type": a.target_type,
                "target_id": a.target_id,
            }
            for a in recent_audit
        ],
    })
