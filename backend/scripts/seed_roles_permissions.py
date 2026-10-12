"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/scripts/seed_roles_permissions.py
Description : One-time (idempotent) seed of baseline roles and permissions.
               Run after `flask db upgrade`:
                   cd /data/database-management/backend
                   source venv/bin/activate
                   python scripts/seed_roles_permissions.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Role, Permission

PERMISSIONS = [
    ("server.view", "View inventory and server details"),
    ("server.create", "Register a new server"),
    ("server.edit", "Edit server metadata"),
    ("server.delete", "Deactivate/remove a server"),
    ("server.restart", "Restart MongoDB on a server"),
    ("server.configuration.view", "View MongoDB configuration"),
    ("server.configuration.modify", "Modify MongoDB configuration"),
    ("server.backup", "Run a db-level or collection-level backup"),
    ("server.user.create", "Create a MongoDB user on a server"),
    ("operation.schedule", "Create/cancel scheduled (one-time or recurring) operations"),
    ("mongodb.upgrade", "Run minor/major MongoDB upgrades"),
    ("mongodb.failover", "Trigger a replica-set failover"),
    ("mongodb.failback", "Trigger a replica-set failback"),
    ("audit.view", "View audit logs"),
    ("audit.export", "Export audit logs"),
    ("production.operation.approve", "Approve high-risk production operations"),
]

ROLES = {
    "platform_admin": [code for code, _ in PERMISSIONS],
    "senior_dba": [
        "server.view", "server.create", "server.edit", "server.restart",
        "server.configuration.view", "server.configuration.modify",
        "server.backup", "server.user.create", "operation.schedule",
        "mongodb.upgrade", "mongodb.failover", "mongodb.failback",
        "audit.view", "production.operation.approve",
    ],
    "dba": [
        "server.view", "server.create", "server.edit", "server.restart",
        "server.configuration.view", "server.configuration.modify",
        "server.backup", "server.user.create", "operation.schedule",
        "audit.view",
    ],
    "operator": ["server.view", "server.restart"],
    "auditor": ["server.view", "audit.view", "audit.export"],
    "viewer": ["server.view"],
}


def run():
    app = create_app()
    with app.app_context():
        perm_by_code = {}
        for code, description in PERMISSIONS:
            perm = Permission.query.filter_by(code=code).first()
            if not perm:
                perm = Permission(code=code, description=description)
                db.session.add(perm)
            perm_by_code[code] = perm
        db.session.flush()

        for role_name, perm_codes in ROLES.items():
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name)
                db.session.add(role)
            role.permissions = [perm_by_code[c] for c in perm_codes]

        db.session.commit()
        print(f"Seeded {len(PERMISSIONS)} permissions and {len(ROLES)} roles.")


if __name__ == "__main__":
    run()
