"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-12
Script Path : /data/database-management/backend/services/alert_rules.py
Description : Declarative rules that decide which audit_logs rows become
               alerts, and at what severity. This is the one file to edit
               when a new audit action should (or shouldn't) raise an alert
               — alert_service.py itself never hardcodes an action name.

               A rule is just: does this audit row match? -> (severity, title,
               message). First matching rule wins. Rows matching nothing are
               skipped (no Alert row is created for them at all).
"""

from dataclasses import dataclass
from typing import Callable, Optional

from models import AlertSeverity


@dataclass
class AlertRule:
    code: str
    description: str
    matches: Callable[[str, dict], bool]
    severity: str
    title: Callable[[dict], str]
    message: Callable[[dict], str]


def _detail_flag_false(detail: dict, key: str) -> bool:
    """True if detail[key] is explicitly present and falsy (e.g. {'ok': false})."""
    return isinstance(detail, dict) and key in detail and not detail.get(key)


RULES = [
    AlertRule(
        code="operation.failed",
        description="Any operation-engine action that ended in failure or rollback.",
        matches=lambda action, detail: action.startswith("operation.") and (
            action.endswith(".failed") or action.endswith(".rolled_back") or action.endswith(".timed_out")
        ),
        severity=AlertSeverity.CRITICAL.value,
        title=lambda row: f"Operation failed: {row.get('action')}",
        message=lambda row: f"{row.get('actor_username') or 'system'} — target {row.get('target_type')} "
                             f"{row.get('target_id')}. Detail: {row.get('detail')}",
    ),
    AlertRule(
        code="operation.succeeded",
        description="Any operation-engine action (one-time or scheduled) that completed successfully.",
        matches=lambda action, detail: action.startswith("operation.") and action.endswith(".succeeded"),
        severity=AlertSeverity.INFO.value,
        title=lambda row: f"Operation succeeded: {row.get('action')}",
        message=lambda row: f"{row.get('actor_username') or 'scheduler'} — target {row.get('target_type')} "
                             f"{row.get('target_id')}. Detail: {row.get('detail')}",
    ),
    AlertRule(
        code="server.connectivity_failed",
        description="A connectivity test against a registered server failed.",
        matches=lambda action, detail: action == "server.test_connectivity" and _detail_flag_false(detail, "ok"),
        severity=AlertSeverity.WARNING.value,
        title=lambda row: f"Connectivity test failed for server {row.get('target_id')}",
        message=lambda row: f"Requested by {row.get('actor_username') or 'system'}. Detail: {row.get('detail')}",
    ),
    AlertRule(
        code="login.failed",
        description="A failed login attempt.",
        matches=lambda action, detail: action == "login.failed",
        severity=AlertSeverity.WARNING.value,
        title=lambda row: f"Failed login attempt: {row.get('actor_username') or 'unknown user'}",
        message=lambda row: f"Source IP: {row.get('source_ip') or 'unknown'}",
    ),
    AlertRule(
        code="server.created",
        description="A new server was registered in inventory.",
        matches=lambda action, detail: action == "server.create",
        severity=AlertSeverity.INFO.value,
        title=lambda row: f"New server registered: {row.get('target_id')}",
        message=lambda row: f"Registered by {row.get('actor_username') or 'system'}.",
    ),
]


def match_rule(action: str, detail: Optional[dict]) -> Optional[AlertRule]:
    detail = detail or {}
    for rule in RULES:
        if rule.matches(action, detail):
            return rule
    return None
