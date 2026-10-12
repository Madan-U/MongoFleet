"""
Description : Audit Logs API — list with search/action filters and a CSV
               export, backed by the real audit_logs table. Backs
               governance.html (previously hardcoded mock rows in the page).
"""

from flask import Blueprint, request, jsonify, Response
from sqlalchemy import or_

from models import AuditLog
from security import login_required

bp = Blueprint("audit", __name__, url_prefix="/api/audit")


def _row_to_dict(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "ts": a.ts.isoformat() + "Z" if a.ts else None,
        "actor_username": a.actor_username,
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "detail": a.detail,
        "source_ip": a.source_ip,
    }


def _filtered_query():
    query = AuditLog.query

    action = request.args.get("action")
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))

    search = request.args.get("search")
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            AuditLog.actor_username.ilike(like),
            AuditLog.action.ilike(like),
            AuditLog.target_type.ilike(like),
            AuditLog.target_id.ilike(like),
        ))

    return query.order_by(AuditLog.ts.desc())


@bp.get("")
@login_required
def list_audit():
    page = max(int(request.args.get("page", 1)), 1)
    page_size = min(max(int(request.args.get("page_size", 100)), 1), 500)

    query = _filtered_query()
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    return jsonify({
        "logs": [_row_to_dict(a) for a in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@bp.get("/export")
@login_required
def export_audit():
    """CSV export of the (optionally filtered) audit trail — powers the
    'Export' button on governance.html."""
    rows = _filtered_query().limit(10000).all()

    def _csv_escape(val):
        if val is None:
            return ""
        s = str(val).replace('"', '""')
        return f'"{s}"'

    header = "timestamp,user,action,target_type,target_id,source_ip\n"
    lines = [header]
    for a in rows:
        lines.append(",".join([
            _csv_escape(a.ts.isoformat() if a.ts else ""),
            _csv_escape(a.actor_username),
            _csv_escape(a.action),
            _csv_escape(a.target_type),
            _csv_escape(a.target_id),
            _csv_escape(a.source_ip),
        ]) + "\n")

    return Response(
        "".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs_export.csv"},
    )
