"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/services/credential_service.py
Description : Resolves a server's ssh_credential_ref / mongo_credential_ref
               (a short name like "prod" or "nonprod") to the actual
               credential material, sourced from environment variables set
               in .env on the app server. This is the single choke point for
               credential access, so it's the one place to swap in a real
               secrets manager (Vault / AWS Secrets Manager) later without
               touching callers.

               Nothing here ever accepts a secret from a request body,
               and no secret is ever written to the `servers` table,
               logs, or audit records.
"""

import os
from dataclasses import dataclass
from typing import Optional


class CredentialResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SSHCredential:
    username: str
    key_path: Optional[str] = None
    password: Optional[str] = None  # only populated if no key is configured


def get_ssh_credential(ref: str) -> SSHCredential:
    ref = (ref or "nonprod").upper()
    username = os.environ.get(f"SSH_USER_{ref}")
    key_path = os.environ.get(f"SSH_KEY_PATH_{ref}")
    password = os.environ.get(f"SSH_PASSWORD_{ref}")

    if not username:
        raise CredentialResolutionError(f"No SSH_USER_{ref} configured in .env")
    if not key_path and not password:
        raise CredentialResolutionError(
            f"No SSH_KEY_PATH_{ref} or SSH_PASSWORD_{ref} configured in .env"
        )
    return SSHCredential(username=username, key_path=key_path, password=password)


@dataclass(frozen=True)
class MongoCredential:
    username: Optional[str]
    password: Optional[str]
    auth_source: str = "admin"


def get_mongo_credential(ref: str) -> MongoCredential:
    ref = (ref or "nonprod").upper()
    username = os.environ.get(f"MONGO_USER_{ref}")
    password = os.environ.get(f"MONGO_PASSWORD_{ref}")
    auth_source = os.environ.get(f"MONGO_AUTHSOURCE_{ref}", "admin")
    return MongoCredential(username=username, password=password, auth_source=auth_source)
