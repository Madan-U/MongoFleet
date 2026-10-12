"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/routes/auth.py
Description : Login/logout/current-user endpoints. Login is checked against
               real user rows in Postgres via werkzeug password hashing —
               no hardcoded credentials, no bypass.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify, session

from extensions import db
from models import User
from security import verify_password, current_user, login_required
from services import audit_service

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username_and_password_required"}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        audit_service.record(action="login.failed", actor_username=username,
                              source_ip=request.remote_addr)
        return jsonify({"error": "invalid_credentials"}), 401

    session.clear()
    session["user_id"] = user.id
    session.permanent = True

    user.last_login_at = datetime.utcnow()
    db.session.commit()

    audit_service.record(action="login.success", actor_user_id=user.id, actor_username=user.username,
                          source_ip=request.remote_addr)

    return jsonify({
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "roles": [r.name for r in user.roles],
    })


@bp.post("/logout")
@login_required
def logout():
    user = current_user()
    audit_service.record(action="logout", actor_user_id=user.id, actor_username=user.username,
                          source_ip=request.remote_addr)
    session.clear()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False}), 200
    return jsonify({
        "authenticated": True,
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "roles": [r.name for r in user.roles],
        "permissions": sorted({p.code for r in user.roles for p in r.permissions}),
    })
