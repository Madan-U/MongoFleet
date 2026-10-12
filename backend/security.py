"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/security.py
Description : Password hashing helpers and auth/permission decorators used
               by route handlers. Sessions are server-side (Flask signed
               cookie + SQLAlchemy-backed user), not a bearer token — simplest
               correct option for a single internal console; can be swapped
               for JWT/SSO later without touching business logic.
"""

from functools import wraps
from typing import Callable

from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from models import User


def hash_password(raw_password: str) -> str:
    """Hash a plaintext password for storage. Never store plaintext."""
    return generate_password_hash(raw_password, method="pbkdf2:sha256", salt_length=16)


def verify_password(raw_password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, raw_password)


def current_user() -> "User | None":
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def login_required(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user.is_active:
            return jsonify({"error": "authentication_required"}), 401
        return fn(*args, **kwargs)
    return wrapper


def permission_required(code: str) -> Callable:
    """Route decorator enforcing a specific RBAC permission code,
    e.g. @permission_required('server.restart')."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or not user.is_active:
                return jsonify({"error": "authentication_required"}), 401
            if not user.has_permission(code):
                return jsonify({"error": "permission_denied", "required": code}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
