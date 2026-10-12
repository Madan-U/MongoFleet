"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/routes/inventory.py
Description : Server inventory API — list, detail, create, connectivity test,
               live health refresh. Backs inventory.html / server-detail.html.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify

from models import ServerHealth
from security import login_required, permission_required, current_user
from services import inventory_service, audit_service, metrics_service, mongo_service

bp = Blueprint("inventory", __name__, url_prefix="/api/inventory")


def _utc_iso(dt):
    return dt.isoformat() + "Z" if dt else None

def _latest_status(server_id: int) -> str:
    row = (
        ServerHealth.query.filter_by(server_id=server_id)
        .order_by(ServerHealth.checked_at.desc())
        .first()
    )
    return row.status if row else "UNKNOWN"


def _server_to_dict(server, include_status: bool = True) -> dict:
    return {
        "id": server.id,
        "hostname": server.hostname,
        "fqdn": server.fqdn,
        "ip_address": server.ip_address,
        "environment": server.environment,
        "cluster_name": server.cluster_name,
        "replica_set_name": server.replica_set_name,
        "node_role": server.node_role,
        "port": server.port,
        "mongo_version": server.mongo_version,
        "mongo_edition": server.mongo_edition,
        "os_version": server.os_version,
        "cpu_cores": server.cpu_cores,
        "memory_gb": float(server.memory_gb) if server.memory_gb is not None else None,
        "disk_gb": float(server.disk_gb) if server.disk_gb is not None else None,
        "criticality": server.criticality,
        "owner": server.owner,
        "application_name": server.application_name,
        "monitoring_enabled": server.monitoring_enabled,
        "backup_status": server.backup_status,
        "updated_at": _utc_iso(server.updated_at),
        # These two come only from the hourly cron (static_inventory_service) —
        # never fabricated on a page load. null/"" means it hasn't run yet.
        "static_collected_at": _utc_iso(server.static_collected_at),
        "static_collection_error": server.static_collection_error,
        "latest_status": _latest_status(server.id) if include_status else None,
    }


@bp.get("/servers")
@login_required
def list_servers():
    servers = inventory_service.list_servers(
        environment=request.args.get("environment"),
        cluster_name=request.args.get("cluster_name"),
    )
    return jsonify({"servers": [_server_to_dict(s) for s in servers], "count": len(servers)})


@bp.get("/servers/<int:server_id>")
@login_required
def get_server(server_id: int):
    server = inventory_service.get_server(server_id)
    if not server:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_server_to_dict(server))


@bp.post("/servers")
@permission_required("server.create")
def create_server():
    payload = request.get_json(silent=True) or {}
    for field in ("hostname", "ip_address"):
        if not payload.get(field):
            return jsonify({"error": f"{field}_required"}), 400
    server = inventory_service.create_server(payload)
    audit_service.record(action="server.create", actor_user_id=current_user().id,
                          actor_username=current_user().username,
                          target_type="server", target_id=server.id, detail=payload,
                          source_ip=request.remote_addr)
    return jsonify(_server_to_dict(server)), 201


@bp.put("/servers/<int:server_id>")
@permission_required("server.edit")
def update_server(server_id: int):
    server = inventory_service.get_server(server_id)
    if not server:
        return jsonify({"error": "not_found"}), 404
    payload = request.get_json(silent=True) or {}
    server = inventory_service.update_server(server, payload)
    audit_service.record(action="server.edit", actor_user_id=current_user().id,
                          actor_username=current_user().username,
                          target_type="server", target_id=server.id, detail=payload,
                          source_ip=request.remote_addr)
    return jsonify(_server_to_dict(server))


@bp.delete("/servers/<int:server_id>")
@permission_required("server.delete")
def delete_server(server_id: int):
    server = inventory_service.get_server(server_id)
    if not server:
        return jsonify({"error": "not_found"}), 404
    inventory_service.deactivate_server(server)
    audit_service.record(action="server.delete", actor_user_id=current_user().id,
                          actor_username=current_user().username,
                          target_type="server", target_id=server_id, detail=None,
                          source_ip=request.remote_addr)
    return jsonify({"status": "deactivated"})


@bp.post("/servers/<int:server_id>/test-connectivity")
@permission_required("server.view")
def test_connectivity(server_id: int):
    server = inventory_service.get_server(server_id)
    if not server:
        return jsonify({"error": "not_found"}), 404
    result = inventory_service.test_connectivity(server)
    audit_service.record(action="server.test_connectivity", actor_user_id=current_user().id,
                          actor_username=current_user().username,
                          target_type="server", target_id=server.id, detail=result,
                          source_ip=request.remote_addr)
    return jsonify(result)


@bp.get("/servers/<int:server_id>/live-metrics")
@permission_required("server.view")
def live_metrics(server_id: int):
    """Real-time pull for the server-detail page: OS metrics over SSH
    (os_live_metrics) + Mongo health over PyMongo. Nothing here is cached —
    every call is a fresh round-trip to the actual server. Any field that
    couldn't be read comes back null; the frontend must render that as
    'unavailable', not a placeholder number."""
    server = inventory_service.get_server(server_id)
    if not server:
        return jsonify({"error": "not_found"}), 404

    os_metrics = metrics_service.get_live_metrics(
        host=server.ip_address, credential_ref=server.ssh_credential_ref,
    )
    mongo_health = mongo_service.check_health(
        host=server.ip_address, port=server.port, credential_ref=server.mongo_credential_ref,
    )

    return jsonify({
        "checked_at": _utc_iso(datetime.utcnow()),
        "os": {
            "reachable": os_metrics.reachable,
            "cpu_pct": os_metrics.cpu_pct,
            "memory_pct": os_metrics.memory_pct,
            "disk_pct": os_metrics.disk_pct,
            "uptime_seconds": os_metrics.os_uptime_seconds,
            "error": os_metrics.error,
        },
        "mongo": {
            "reachable": mongo_health.reachable,
            "replica_state": mongo_health.replica_state,
            "is_primary": mongo_health.is_primary,
            "replication_lag_seconds": mongo_health.replication_lag_seconds,
            "connections_current": mongo_health.connections_current,
            "version": mongo_health.version,
            "uptime_seconds": mongo_health.uptime_seconds,
            "error": mongo_health.error,
        },
        "status": "OK" if (os_metrics.reachable and mongo_health.reachable) else "CRITICAL",
    })


@bp.post("/servers/<int:server_id>/refresh-health")
@permission_required("server.view")
def refresh_health(server_id: int):
    server = inventory_service.get_server(server_id)
    if not server:
        return jsonify({"error": "not_found"}), 404
    snapshot = inventory_service.refresh_health(server)
    return jsonify({
        "checked_at": _utc_iso(snapshot.checked_at),
        "reachable_mongo": snapshot.reachable_mongo,
        "replica_state": snapshot.replica_state,
        "replication_lag_seconds": float(snapshot.replication_lag_seconds) if snapshot.replication_lag_seconds is not None else None,
        "connections_current": snapshot.connections_current,
        "status": snapshot.status,
        "detail": snapshot.detail,
    })
