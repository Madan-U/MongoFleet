"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/services/inventory_service.py
Description : Server inventory business logic — list/create/update servers,
               run connectivity tests, and refresh a server's live-discovered
               fields (version, replica role, etc.) via mongo_service /
               ssh_service. No hardcoded or sample server rows are seeded
               anywhere — inventory starts empty until real servers are
               registered.
"""

from datetime import datetime
from typing import Optional

from extensions import db
from models import Server, ServerHealth
from services import mongo_service, ssh_service


def list_servers(environment: Optional[str] = None, cluster_name: Optional[str] = None) -> list[Server]:
    query = Server.query.filter_by(is_active=True)
    if environment:
        query = query.filter_by(environment=environment)
    if cluster_name:
        query = query.filter_by(cluster_name=cluster_name)
    return query.order_by(Server.hostname).all()


def get_server(server_id: int) -> Optional[Server]:
    return Server.query.get(server_id)


def create_server(data: dict) -> Server:
    server = Server(
        hostname=data["hostname"],
        ip_address=data["ip_address"],
        environment=data.get("environment"),
        cluster_name=data.get("cluster_name"),
        replica_set_name=data.get("replica_set_name"),
        port=data.get("port", 27017),
        owner=data.get("owner"),
        application_name=data.get("application_name"),
        criticality=data.get("criticality"),
        ssh_credential_ref=data.get("ssh_credential_ref", "nonprod"),
        mongo_credential_ref=data.get("mongo_credential_ref", "nonprod"),
    )
    db.session.add(server)
    db.session.commit()
    return server


def update_server(server: Server, data: dict) -> Server:
    """Update baseline metadata only (environment/cluster/criticality etc.) --
    never touches credentials or live-discovered fields."""
    for field in ("environment", "cluster_name", "criticality", "owner", "application_name", "mongo_edition"):
        if field in data:
            setattr(server, field, data[field])
    server.updated_at = datetime.utcnow()
    db.session.commit()
    return server


def deactivate_server(server: Server) -> None:
    """Soft delete -- matches list_servers()'s is_active filter, keeps history
    (ServerHealth, audit rows) intact instead of hard-deleting the row."""
    server.is_active = False
    server.updated_at = datetime.utcnow()
    db.session.commit()


def test_connectivity(server: Server) -> dict:
    """Live SSH + Mongo connectivity test — never simulated."""
    result = {"ssh": None, "mongo": None}
    try:
        ssh_res = ssh_service.run_allowlisted_command(
            host=server.ip_address, port=22,
            credential_ref=server.ssh_credential_ref,
            command_key="mongo_service_status",
        )
        result["ssh"] = {"ok": True, "detail": ssh_res.stdout.strip()}
    except Exception as exc:
        result["ssh"] = {"ok": False, "detail": str(exc)}

    mongo_res = mongo_service.check_health(
        host=server.ip_address, port=server.port, credential_ref=server.mongo_credential_ref,
    )
    result["mongo"] = {"ok": mongo_res.reachable, "detail": mongo_res.error or "reachable"}
    return result


def refresh_health(server: Server) -> ServerHealth:
    """Pull a live health snapshot and persist it as a point-in-time row.
    The dashboard should still prefer a fresh call for anything shown as
    'current status' — this snapshot is for history/trend, not a cache
    substituted for a live check."""
    mongo_res = mongo_service.check_health(
        host=server.ip_address, port=server.port, credential_ref=server.mongo_credential_ref,
    )
    status = "OK" if mongo_res.reachable else "CRITICAL"
    snapshot = ServerHealth(
        server_id=server.id,
        reachable_ssh=None,
        reachable_mongo=mongo_res.reachable,
        replica_state=mongo_res.replica_state,
        replication_lag_seconds=mongo_res.replication_lag_seconds,
        connections_current=mongo_res.connections_current,
        status=status,
        detail=mongo_res.error,
    )
    if mongo_res.reachable:
        server.node_role = mongo_res.replica_state
        server.mongo_version = mongo_res.version
    server.updated_at = datetime.utcnow()
    db.session.add(snapshot)
    db.session.commit()
    return snapshot
