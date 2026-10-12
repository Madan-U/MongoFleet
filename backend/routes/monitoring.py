from flask import Blueprint, request, jsonify
from models import SlowQueryLog, IndexRecommendation, Server, ServerHealth
from extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func

from security import login_required

bp = Blueprint("monitoring", __name__, url_prefix="/api/monitoring")

@bp.route('/performance-advisor/<int:server_id>', methods=['GET'])
@login_required
def get_performance_advisor(server_id):
    timeframe = request.args.get('timeframe', '1h')
    now = datetime.utcnow()
    
    if timeframe == '30s': start_time = now - timedelta(seconds=30)
    elif timeframe == '1m': start_time = now - timedelta(minutes=1)
    elif timeframe == '5m': start_time = now - timedelta(minutes=5)
    elif timeframe == '1h': start_time = now - timedelta(hours=1)
    elif timeframe == '24h': start_time = now - timedelta(hours=24)
    elif timeframe == 'custom': start_time = now - timedelta(hours=24) 
    else: start_time = now - timedelta(hours=1)
    
    # 1. Slow Queries
    slow_queries = db.session.query(
        SlowQueryLog.query_hash,
        SlowQueryLog.namespace,
        func.count(SlowQueryLog.id).label('execution_count'),
        func.avg(SlowQueryLog.duration_ms).label('avg_duration'),
        func.avg(SlowQueryLog.docs_scanned).label('avg_scanned')
    ).filter(
        SlowQueryLog.server_id == server_id,
        SlowQueryLog.ts >= start_time
    ).group_by(
        SlowQueryLog.query_hash,
        SlowQueryLog.namespace
    ).order_by(func.avg(SlowQueryLog.duration_ms).desc()).limit(10).all()

    query_results = []
    for q in slow_queries:
        hours_diff = (now - start_time).total_seconds() / 3600
        exec_per_hour = round(q.execution_count / hours_diff, 2) if hours_diff > 0 else q.execution_count
        sample = SlowQueryLog.query.filter_by(query_hash=q.query_hash).first()
        
        query_results.append({
            "query_hash": q.query_hash,
            "namespace": q.namespace,
            "query_shape": sample.query_shape if sample else {},
            "exec_per_hour": exec_per_hour,
            "avg_duration_ms": round(q.avg_duration, 2) if q.avg_duration else 0,
            "avg_docs_scanned": round(q.avg_scanned, 0) if q.avg_scanned else 0
        })

    # 2. Fetch Index Recommendations (CREATE & DROP)
    recs = IndexRecommendation.query.filter_by(server_id=server_id).all()
    rec_results = [{
        "namespace": r.namespace,
        "rec_type": r.rec_type,
        "index_name": r.index_name,
        "index_keys": r.index_keys,
        "reason": r.reason,
        "estimated_impact": r.estimated_impact
    } for r in recs]

    return jsonify({
        "status": "success",
        "slow_queries": query_results,
        "recommendations": rec_results 
    }), 200


@bp.get('/dashboard-stats')
@login_required
def get_dashboard_stats():
    """Fleet-wide monitoring stats for the Metrics Dashboard tab: latest
    ServerHealth row per server (real data, empty inventory -> zeros, never
    fabricated), plus 24h slow-query / index-recommendation counts."""
    total_servers = Server.query.filter_by(is_active=True).count()

    latest_health = {}
    for row in (
        db.session.query(ServerHealth)
        .order_by(ServerHealth.server_id, ServerHealth.checked_at.desc())
        .all()
    ):
        latest_health.setdefault(row.server_id, row)

    status_counts = {"OK": 0, "WARN": 0, "CRITICAL": 0, "UNKNOWN": 0}
    cpu_vals, mem_vals, disk_vals, conn_total = [], [], [], 0
    per_server = []

    servers_by_id = {s.id: s for s in Server.query.filter_by(is_active=True).all()}
    for server_id, server in servers_by_id.items():
        health = latest_health.get(server_id)
        status = health.status if health else "UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1

        if health:
            if health.cpu_pct is not None:
                cpu_vals.append(float(health.cpu_pct))
            if health.memory_pct is not None:
                mem_vals.append(float(health.memory_pct))
            if health.disk_pct is not None:
                disk_vals.append(float(health.disk_pct))
            if health.connections_current:
                conn_total += health.connections_current

        per_server.append({
            "server_id": server_id,
            "hostname": server.hostname,
            "environment": server.environment,
            "status": status,
            "cpu_pct": float(health.cpu_pct) if health and health.cpu_pct is not None else None,
            "memory_pct": float(health.memory_pct) if health and health.memory_pct is not None else None,
            "disk_pct": float(health.disk_pct) if health and health.disk_pct is not None else None,
            "connections_current": health.connections_current if health else None,
            "replication_lag_seconds": float(health.replication_lag_seconds) if health and health.replication_lag_seconds is not None else None,
            "checked_at": health.checked_at.isoformat() + "Z" if health and health.checked_at else None,
        })

    since_24h = datetime.utcnow() - timedelta(hours=24)
    slow_queries_24h = SlowQueryLog.query.filter(SlowQueryLog.ts >= since_24h).count()
    create_recs = IndexRecommendation.query.filter_by(rec_type="CREATE").count()
    drop_recs = IndexRecommendation.query.filter_by(rec_type="DROP").count()

    def _avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    return jsonify({
        "status": "success",
        "total_servers": total_servers,
        "health_status_counts": status_counts,
        "avg_cpu_pct": _avg(cpu_vals),
        "avg_memory_pct": _avg(mem_vals),
        "avg_disk_pct": _avg(disk_vals),
        "total_connections": conn_total,
        "slow_queries_24h": slow_queries_24h,
        "index_recommendations": {"create": create_recs, "drop": drop_recs},
        "servers": per_server,
    }), 200
