"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/models.py
Description : SQLAlchemy ORM models for the MongoFleet platform metadata
               store (PostgreSQL). Covers auth/RBAC, inventory, and the
               operation-engine skeleton (Section 8 of the spec) that later
               phases (restart, upgrade, failover) will build on.
"""

from datetime import datetime
import enum
import uuid

from sqlalchemy.dialects.postgresql import UUID
from extensions import db


def gen_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    # e.g. "platform_admin", "senior_dba", "dba", "operator", "auditor", "viewer"
    description = db.Column(db.String(255))
    permissions = db.relationship("Permission", secondary="role_permissions", backref="roles")


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False)
    # e.g. "server.restart", "mongodb.failover", "audit.export"
    description = db.Column(db.String(255))


role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)
    roles = db.relationship("Role", secondary="user_roles", backref="users")

    def has_permission(self, code: str) -> bool:
        return any(p.code == code for role in self.roles for p in role.permissions)


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class Server(db.Model):
    __tablename__ = "servers"
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(120), nullable=False)
    fqdn = db.Column(db.String(255))
    ip_address = db.Column(db.String(45), nullable=False)
    environment = db.Column(db.String(20))          # prod / uat / cug / pqa / dev
    cluster_name = db.Column(db.String(120))
    replica_set_name = db.Column(db.String(120))
    node_role = db.Column(db.String(20))             # PRIMARY / SECONDARY / ARBITER / UNKNOWN
    port = db.Column(db.Integer, default=27017)
    mongo_version = db.Column(db.String(20))
    mongo_edition = db.Column(db.String(40))          # e.g. "Community", "Enterprise"
    os_version = db.Column(db.String(120))            # PRETTY_NAME from /etc/os-release
    data_directory = db.Column(db.String(255))
    config_file_path = db.Column(db.String(255))
    cpu_cores = db.Column(db.Integer)
    memory_gb = db.Column(db.Numeric(10, 2))
    disk_gb = db.Column(db.Numeric(10, 2))
    owner = db.Column(db.String(120))
    application_name = db.Column(db.String(120))
    criticality = db.Column(db.String(10))           # P1..P4
    monitoring_enabled = db.Column(db.Boolean, default=True)
    backup_status = db.Column(db.String(20))
    maintenance_window = db.Column(db.String(120))
    # Which named credential set (see services/credential_service.py) SSH
    # and MongoDB auth should use for this host — never a raw secret here.
    ssh_credential_ref = db.Column(db.String(40), default="nonprod")
    mongo_credential_ref = db.Column(db.String(40), default="nonprod")
    is_active = db.Column(db.Boolean, default=True)
    # Set only by the hourly static-inventory collector (scripts/collect_static_inventory.py),
    # never by a page load — this is how the UI can show "last collected Xh ago" honestly.
    static_collected_at = db.Column(db.DateTime)
    static_collection_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    health_checks = db.relationship("ServerHealth", backref="server", lazy="dynamic")


class ServerHealth(db.Model):
    """Point-in-time health snapshot. Populated by live checks, not a cache
    users are shown instead of a live pull — see services/monitoring."""
    __tablename__ = "server_health"
    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)
    reachable_ssh = db.Column(db.Boolean)
    reachable_mongo = db.Column(db.Boolean)
    replica_state = db.Column(db.String(20))
    replication_lag_seconds = db.Column(db.Numeric(10, 2))
    cpu_pct = db.Column(db.Numeric(5, 2))
    memory_pct = db.Column(db.Numeric(5, 2))
    disk_pct = db.Column(db.Numeric(5, 2))
    connections_current = db.Column(db.Integer)
    status = db.Column(db.String(20))                 # OK / WARN / CRITICAL / UNKNOWN
    detail = db.Column(db.Text)


# ---------------------------------------------------------------------------
# Operation engine skeleton (Section 8) — models only in this phase.
# Execution workers land in a later phase; see README "Phase status".
# ---------------------------------------------------------------------------
class OperationStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    ROLLED_BACK = "ROLLED_BACK"


class Operation(db.Model):
    __tablename__ = "operations"
    triggered_by_schedule_id = db.Column(db.Integer, db.ForeignKey("scheduled_operations.id"))
    id = db.Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    operation_type = db.Column(db.String(60), nullable=False)   # restart / failover / minor_upgrade / ...
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(30), default=OperationStatus.REQUESTED.value, nullable=False)
    current_step = db.Column(db.String(120))
    progress_pct = db.Column(db.Integer, default=0)
    params = db.Column(db.JSON, default=dict)
    # Ordered checklist for the live progress UI: [{key, label, status,
    # started_at, completed_at, duration_ms, message}, ...]. Written
    # incrementally by operations_service as each step runs — the frontend
    # polls GET /api/operations/<id> and renders this directly, so there is
    # no separate "fake progress" simulation anywhere.
    steps = db.Column(db.JSON, default=list)
    precheck_results = db.Column(db.JSON)
    postcheck_results = db.Column(db.JSON)
    result = db.Column(db.String(20))
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    server = db.relationship("Server")


class OperationLog(db.Model):
    __tablename__ = "operation_logs"
    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(UUID(as_uuid=False), db.ForeignKey("operations.id"), nullable=False)
    ts = db.Column(db.DateTime, default=datetime.utcnow)
    level = db.Column(db.String(10), default="INFO")
    message = db.Column(db.Text)


# ---------------------------------------------------------------------------
# Operation scheduling — a *request* to run an operation later or on a
# recurrence, kept deliberately separate from `Operation` (a *run*). The
# scheduler cron (scripts/run_scheduled_operations.py) is the only thing
# that ever turns a due row here into an actual Operation; this table by
# itself never executes anything.
# ---------------------------------------------------------------------------
class ScheduleType(str, enum.Enum):
    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"
    INTERVAL = "INTERVAL"


class ScheduledOperation(db.Model):
    __tablename__ = "scheduled_operations"
    id = db.Column(db.Integer, primary_key=True)
    operation_type = db.Column(db.String(40), nullable=False)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False)
    params = db.Column(db.JSON, default=dict)
    schedule_type = db.Column(db.String(20), nullable=False)          # ONE_TIME / RECURRING / INTERVAL
    run_at = db.Column(db.DateTime)                                    # ONE_TIME: exact UTC datetime
    day_of_week = db.Column(db.Integer)                                # RECURRING: 0=Mon..6=Sun, null=daily
    time_of_day = db.Column(db.Time)                                   # RECURRING: HH:MM (UTC) to fire
    interval_minutes = db.Column(db.Integer)                           # INTERVAL: fire every N minutes
    is_active = db.Column(db.Boolean, default=True, nullable=False)    # False once ONE_TIME fired, or disabled/cancelled
    cancelled_at = db.Column(db.DateTime)                              # set only by DELETE /schedules/:id — distinct from "disabled"
    last_triggered_at = db.Column(db.DateTime)
    resulting_operation_id = db.Column(UUID(as_uuid=False), db.ForeignKey("operations.id"))  # Operation row from the most recent fire
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime)

    server = db.relationship("Server")
    resulting_operation = db.relationship("Operation", foreign_keys="[ScheduledOperation.resulting_operation_id]")


# ---------------------------------------------------------------------------
# Small admin-configurable key/value settings — starting with the
# long-running-query threshold used by the restart/stop pre-check. Deliberately
# generic (not a dedicated column somewhere) so future thresholds/toggles
# don't each need their own migration.
# ---------------------------------------------------------------------------
class SystemSetting(db.Model):
    __tablename__ = "system_settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.JSON, nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    actor_username = db.Column(db.String(80))
    action = db.Column(db.String(80), nullable=False)   # login, server.create, operation.request, ...
    target_type = db.Column(db.String(40))
    target_id = db.Column(db.String(40))
    detail = db.Column(db.JSON)
    source_ip = db.Column(db.String(45))


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
# Deliberately a separate table rather than an `alert_sent` column bolted onto
# audit_logs — audit_service.record() is documented as insert-only ("audit
# rows are never updated or deleted"), and adding an UPDATE path just for
# alerting would break that guarantee for every future reader of audit_logs.
# The one-to-one FK + unique constraint below is what prevents the same audit
# event from ever generating two alerts, without ever touching the audit row.
class AlertSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class AlertStatus(str, enum.Enum):
    PENDING = "PENDING"   # matched a rule, not dispatched yet
    SENT = "SENT"
    FAILED = "FAILED"     # dispatch attempted and failed (retried next cycle)


class Alert(db.Model):
    __tablename__ = "alerts"
    id = db.Column(db.Integer, primary_key=True)
    audit_log_id = db.Column(db.Integer, db.ForeignKey("audit_logs.id"), nullable=False, unique=True)
    ts = db.Column(db.DateTime, nullable=False)  # copied from the audit row's ts for cheap range queries
    rule_code = db.Column(db.String(80), nullable=False)
    severity = db.Column(db.String(10), nullable=False)  # CRITICAL / WARNING / INFO
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    action = db.Column(db.String(80))
    actor_username = db.Column(db.String(80))
    target_type = db.Column(db.String(40))
    target_id = db.Column(db.String(40))
    status = db.Column(db.String(10), default=AlertStatus.PENDING.value, nullable=False)
    channel = db.Column(db.String(20))          # which channel last attempted delivery (log / email / ...)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_at = db.Column(db.DateTime)

    audit_log = db.relationship("AuditLog")


class AlertPollState(db.Model):
    """Single-row cursor: the highest audit_logs.id the poller has already
    evaluated. Scanning forward from this cursor (instead of re-scanning all
    of audit_logs for rows with 'no alert yet') keeps every poll cycle cheap
    regardless of how large audit_logs grows."""
    __tablename__ = "alert_poll_state"
    id = db.Column(db.Integer, primary_key=True)  # always row id=1
    last_audit_id = db.Column(db.Integer, default=0, nullable=False)
    last_run_at = db.Column(db.DateTime)


# ---------------------------------------------------------------------------
# Monitoring & Performance Advisor (Section: Monitoring)
# ---------------------------------------------------------------------------
class SlowQueryLog(db.Model):
    """One row per captured slow-query occurrence, parsed from mongod logs
    (see scripts/parse_slow_queries.py). Aggregated by query_hash+namespace
    in the performance-advisor endpoint to surface the worst offenders."""
    __tablename__ = "slow_query_logs"
    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    ts = db.Column(db.DateTime, nullable=False, index=True)
    query_hash = db.Column(db.String(64), nullable=False, index=True)
    namespace = db.Column(db.String(120), nullable=False)
    operation = db.Column(db.String(20))
    duration_ms = db.Column(db.Integer)
    docs_scanned = db.Column(db.Integer)
    docs_returned = db.Column(db.Integer)
    query_shape = db.Column(db.JSON)
    raw_log = db.Column(db.JSON)

    server = db.relationship("Server")


class IndexRecommendation(db.Model):
    """CREATE/DROP index suggestions surfaced on the Performance Advisor tab.
    Populated by the slow-query analysis job; rec_type is 'CREATE' or 'DROP'."""
    __tablename__ = "index_recommendations"
    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    namespace = db.Column(db.String(120), nullable=False)
    rec_type = db.Column(db.String(20), nullable=False)   # CREATE / DROP
    index_name = db.Column(db.String(120))
    index_keys = db.Column(db.JSON, nullable=False)
    reason = db.Column(db.Text)
    estimated_impact = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    server = db.relationship("Server")
