"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/services/audit_service.py
Description : Single write path for audit records so every service/route
               logs actions the same way. Audit rows are never updated or
               deleted through this module — only inserted.
"""

from typing import Optional

from extensions import db
from models import AuditLog


def record(action: str, actor_user_id: Optional[int] = None, actor_username: Optional[str] = None,
           target_type: Optional[str] = None, target_id: Optional[str] = None,
           detail: Optional[dict] = None, source_ip: Optional[str] = None) -> AuditLog:
    entry = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail or {},
        source_ip=source_ip,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
