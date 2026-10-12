"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/scripts/create_admin_user.py
Description : Interactive one-time creation of the first platform_admin user.
               Password is entered via a hidden prompt (getpass) — never
               accepted as a command-line argument (would land in shell
               history / process list) and never hardcoded.

               Usage:
                   cd /data/database-management/backend
                   source venv/bin/activate
                   python scripts/create_admin_user.py
"""

import sys
import os
from getpass import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import User, Role
from security import hash_password


def run():
    app = create_app()
    with app.app_context():
        username = input("Username: ").strip()
        email = input("Email: ").strip()
        full_name = input("Full name: ").strip()

        if User.query.filter_by(username=username).first():
            print(f"User '{username}' already exists. Aborting.")
            return

        password = getpass("Password: ")
        confirm = getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match. Aborting.")
            return
        if len(password) < 12:
            print("Password must be at least 12 characters. Aborting.")
            return

        admin_role = Role.query.filter_by(name="platform_admin").first()
        if not admin_role:
            print("Role 'platform_admin' not found — run seed_roles_permissions.py first.")
            return

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            roles=[admin_role],
        )
        db.session.add(user)
        db.session.commit()
        print(f"Created platform_admin user '{username}'.")


if __name__ == "__main__":
    run()
