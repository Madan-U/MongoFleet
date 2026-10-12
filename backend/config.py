"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-10
Script Path : /data/database-management/backend/config.py
Description : Central application configuration. ALL secrets and credentials
               are read from environment variables — nothing sensitive is
               ever hardcoded in source.

               .env location (standard practice, matches current deployment):
                 1. /etc/mongofleet/.env   <- production (systemd reads this)
                 2. ./.env (backend/.env)     <- dev fallback only, if #1 absent

               See .env.example for the required keys and deploy/README.md
               for how .env is created on the server (never commit .env,
               never paste real secrets in chat or tickets).
"""

import os
from datetime import timedelta
from urllib.parse import quote_plus

from dotenv import load_dotenv

_SYSTEM_ENV_PATH = "/etc/mongofleet/.env"
_LOCAL_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

if os.path.isfile(_SYSTEM_ENV_PATH):
    load_dotenv(_SYSTEM_ENV_PATH)
    ENV_SOURCE = _SYSTEM_ENV_PATH
elif os.path.isfile(_LOCAL_ENV_PATH):
    load_dotenv(_LOCAL_ENV_PATH)
    ENV_SOURCE = _LOCAL_ENV_PATH
else:
    ENV_SOURCE = None  # rely on the process environment (e.g. systemd EnvironmentFile=)


def _require(name: str) -> str:
    """Fetch a required environment variable or fail fast at startup."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Checked {_SYSTEM_ENV_PATH} then {_LOCAL_ENV_PATH} "
            f"(loaded from: {ENV_SOURCE or 'process environment only'})"
        )
    return value


class BaseConfig:
    # --- Flask / session security -----------------------------------------
    SECRET_KEY = _require("ATLAS_SECRET_KEY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set to "false" only while running over plain HTTP (e.g. this POC before
    # a TLS cert is in place). Must be "true" the moment nginx is HTTPS —
    # otherwise the session cookie is readable by anyone on-path, which
    # matters a lot more once the app is reachable from the public internet.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSION_LIFETIME_HOURS", "8")))

    # --- PostgreSQL (platform metadata DB) ----------------------------------
    PG_HOST = _require("PG_HOST")
    PG_PORT = os.environ.get("PG_PORT", "5432")
    PG_DB = _require("PG_DB")
    PG_USER = _require("PG_USER")
    PG_PASSWORD = _require("PG_PASSWORD")

    # quote_plus escapes characters like '@', ':', '/' that are valid in a
    # password but have special meaning inside a URI — without this, a
    # password containing '@' silently truncates the host/user parsing.
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql+psycopg2://{quote_plus(PG_USER)}:{quote_plus(PG_PASSWORD)}"
        f"@{PG_HOST}:{PG_PORT}/{PG_DB}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_size": 10, "pool_recycle": 1800}

    # --- SSH execution service (Paramiko) -----------------------------------
    # Credentials for OS-level SSH to managed MongoDB hosts are NOT read as a
    # single global secret. Each server row in the `servers` table stores a
    # `ssh_credential_ref` — a lookup key resolved through get_ssh_credential()
    # below, backed by env vars per-environment (or, once available, a real
    # secrets manager / Vault). This avoids one shared credential unlocking
    # every server, and keeps credential rotation server-scoped.
    SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "8"))
    SSH_COMMAND_TIMEOUT = int(os.environ.get("SSH_COMMAND_TIMEOUT", "20"))
    SSH_KNOWN_HOSTS_PATH = os.environ.get("SSH_KNOWN_HOSTS_PATH", "/home/<app_service_user>/.ssh/known_hosts")

    # --- MongoDB driver defaults --------------------------------------------
    MONGO_CONNECT_TIMEOUT_MS = int(os.environ.get("MONGO_CONNECT_TIMEOUT_MS", "4000"))
    MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.environ.get("MONGO_SERVER_SELECTION_TIMEOUT_MS", "4000"))

    # --- Logging -------------------------------------------------------------
    LOG_DIR = os.environ.get("LOG_DIR", "/data/database-management/logs")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class DevConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProdConfig(BaseConfig):
    DEBUG = False


CONFIG_MAP = {"dev": DevConfig, "prod": ProdConfig}


def get_config():
    env = os.environ.get("ATLAS_ENV", "prod").lower()
    return CONFIG_MAP.get(env, ProdConfig)
