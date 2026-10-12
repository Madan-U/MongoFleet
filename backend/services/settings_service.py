"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-16
Script Path : /data/database-management/backend/services/settings_service.py
Description : Thin wrapper over the generic SystemSetting key/value table.
               Today this only holds the long-running-query threshold used
               by the restart/stop pre-check (section 5 of the ops spec —
               "configurable by an Admin/DBA"), but new settings can be
               added here without a new migration each time.
"""

from extensions import db
from models import SystemSetting

LONG_RUNNING_THRESHOLD_KEY = "long_running_query_threshold_minutes"
DEFAULT_LONG_RUNNING_THRESHOLD_MINUTES = 15


def get_setting(key: str, default=None):
    row = SystemSetting.query.get(key)
    return row.value if row else default


def set_setting(key: str, value, updated_by_user_id=None):
    row = SystemSetting.query.get(key)
    if row:
        row.value = value
        row.updated_by = updated_by_user_id
    else:
        row = SystemSetting(key=key, value=value, updated_by=updated_by_user_id)
    db.session.add(row)
    db.session.commit()
    return row


def get_long_running_threshold_minutes() -> int:
    return int(get_setting(LONG_RUNNING_THRESHOLD_KEY, DEFAULT_LONG_RUNNING_THRESHOLD_MINUTES))


def set_long_running_threshold_minutes(minutes: int, updated_by_user_id=None):
    return set_setting(LONG_RUNNING_THRESHOLD_KEY, int(minutes), updated_by_user_id)
