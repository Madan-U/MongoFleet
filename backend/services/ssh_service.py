"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/services/ssh_service.py
Description : Reusable SSH execution service built on Paramiko. This is the
               ONLY place in the codebase that opens an SSH connection.
               Routes and services must call `run_allowlisted_command()`,
               never raw command strings — the frontend can only ever select
               one of the named commands in COMMAND_REGISTRY.

               Host-key verification uses a fixed known_hosts file (populated
               by the DBA out-of-band via `ssh-keyscan`, not auto-accepted at
               connect time) so a compromised/spoofed host cannot silently
               MITM an operation.
"""

import logging
import os
import shlex
from dataclasses import dataclass
from typing import Optional

import paramiko

from services.credential_service import get_ssh_credential, SSHCredential

logger = logging.getLogger("atlas.ssh")


class SSHExecutionError(RuntimeError):
    pass


class CommandNotAllowedError(RuntimeError):
    pass


@dataclass(frozen=True)
class SSHResult:
    exit_status: int
    stdout: str
    stderr: str
    command: str

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


# ---------------------------------------------------------------------------
# Allowlisted operation registry.
# Each entry is a template; only these keys can ever be invoked, and only
# with the specific, validated params their handler accepts. This is what
# stands between "user clicks a button" and "arbitrary shell access".
# ---------------------------------------------------------------------------
COMMAND_REGISTRY = {
    "mongo_service_status": "systemctl is-active __MONGO_SERVICE__",
    "mongo_service_start": "sudo -n systemctl start __MONGO_SERVICE__",
    "mongo_service_stop": "sudo -n systemctl stop __MONGO_SERVICE__",
    "mongo_service_restart": "sudo -n systemctl restart __MONGO_SERVICE__",
    "os_cpu_snapshot": "top -bn1 | head -5",
    "os_memory_snapshot": "free -m",
    "os_disk_snapshot": "df -hP",
    "mongo_config_read": "cat {config_path}",
    "mongo_log_tail": "tail -n {lines} {log_path}",

    # Config-file edit primitives, used together by operations_service for
    # every "edit mongod.conf + restart" operation (auth/memory/journal/port).
    # Always back up before writing, never edit in place blind.
    "mongo_config_backup_copy": "cp {config_path} {config_path}.bak.{ts}",
    # Content arrives base64-encoded so arbitrary YAML (colons, quotes,
    # newlines) can never break out of the command template.
    "mongo_config_write": "echo {b64_content} | base64 -d | tee {config_path} > /dev/null",

    # Default-location backups (Operation #5). No --username/--password here
    # deliberately — passing a password on the command line puts it in the
    # remote process list (`ps`) and shell history. If mongod has auth
    # enabled, point mongodump at a keyFile/–config instead of extending this
    # template with credentials.
    "mongo_backup_db": (
        "mkdir -p {backup_dir} && "
        "__MONGODUMP__ --db {db_name} --out {backup_dir}/{backup_name} "
        "&& echo BACKUP_PATH:{backup_dir}/{backup_name}"
    ),
    "mongo_backup_db_gzip": (
        "mkdir -p {backup_dir} && "
        "__MONGODUMP__ --db {db_name} --gzip --out {backup_dir}/{backup_name} "
        "&& echo BACKUP_PATH:{backup_dir}/{backup_name}"
    ),
    "mongo_backup_collection": (
        "mkdir -p {backup_dir} && "
        "__MONGODUMP__ --db {db_name} --collection {collection_name} --out {backup_dir}/{backup_name} "
        "&& echo BACKUP_PATH:{backup_dir}/{backup_name}"
    ),
    "mongo_backup_collection_gzip": (
        "mkdir -p {backup_dir} && "
        "__MONGODUMP__ --db {db_name} --collection {collection_name} --gzip --out {backup_dir}/{backup_name} "
        "&& echo BACKUP_PATH:{backup_dir}/{backup_name}"
    ),
    "mongo_backup_verify": "du -sh {backup_dir} 2>&1",

    # Live, point-in-time OS metrics — called fresh on every server-detail
    # page load/refresh, never cached in Postgres. One round-trip, fixed
    # command (no substituted params — nothing here to allowlist per-value).
    # NOTE: every literal `{`/`}` below is doubled (`{{`/`}}`) because this
    # template goes through str.format() in run_allowlisted_command() — a
    # single brace would be parsed as a substitution field and break awk.
    "os_live_metrics": (
        "echo CPU_PCT:$(top -bn1 | grep -i 'Cpu(s)' | "
        "awk -F'id,' '{{split($1, vs, \",\"); idle=vs[length(vs)]; "
        "gsub(/[^0-9.]/,\"\",idle); printf \"%.1f\", 100-idle}}') "
        "&& echo MEM_PCT:$(free -m | awk '/Mem:/ {{printf \"%.1f\", ($2-$7)/$2*100}}') "
        "&& echo DISK_PCT:$(df -h / | awk 'NR==2 {{gsub(/%/,\"\",$5); print $5}}') "
        "&& echo OS_UPTIME_SEC:$(awk '{{print int($1)}}' /proc/uptime)"
    ),

    # Slow-changing OS/host facts — called only by the hourly static
    # inventory collector, never on a page load. Same brace-doubling note
    # as above applies.
    "os_static_info": (
        "echo FQDN:$(hostname -f 2>/dev/null || hostname) "
        "&& echo OS_PRETTY:$(grep -m1 PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"') "
        "&& echo CPU_CORES:$(nproc) "
        "&& echo MEM_TOTAL_GB:$(free -g | awk '/Mem:/{{print $2}}') "
        "&& echo DISK_TOTAL_GB:$(df -BG / | awk 'NR==2{{gsub(/G/,\"\",$2); print $2}}')"
    ),
}


# ---------------------------------------------------------------------------
# Environment-specific bits of the registry (resolved once at import time).
# Managed MongoDB hosts run mongod as a custom-installed systemd unit under
# the <ssh_username> OS user, so these are configurable rather than hardcoded:
#   MONGO_SERVICE_NAME   systemd unit name on the DB hosts   (default: mongodb)
#   MONGODUMP_BIN        mongodump binary; use a full path if the non-interactive
#                        SSH PATH of <ssh_username> does not include it (default: mongodump)
#   MONGODUMP_EXTRA_ARGS extra mongodump args, e.g. --config=/apps/DB/modb/cfg/mongodump.yaml
#                        (keeps credentials out of the remote process list)
# ---------------------------------------------------------------------------
_MONGO_SERVICE = os.environ.get("MONGO_SERVICE_NAME", "mongodb")
_MONGODUMP = (os.environ.get("MONGODUMP_BIN", "mongodump") + " " +
              os.environ.get("MONGODUMP_EXTRA_ARGS", "")).strip()
COMMAND_REGISTRY = {
    k: v.replace("__MONGO_SERVICE__", _MONGO_SERVICE).replace("__MONGODUMP__", _MONGODUMP)
    for k, v in COMMAND_REGISTRY.items()
}


def _build_client(host: str, port: int, cred: SSHCredential,
                   known_hosts_path: str, connect_timeout: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    if known_hosts_path:
        try:
            client.load_host_keys(known_hosts_path)
        except FileNotFoundError:
            logger.warning("known_hosts file not found at %s — connection will be rejected "
                            "unless the host key is already trusted system-wide", known_hosts_path)
    # Deliberately NOT AutoAddPolicy — an unknown host key must fail closed.
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    connect_kwargs = dict(
        hostname=host,
        port=port,
        username=cred.username,
        timeout=connect_timeout,
        banner_timeout=connect_timeout,
        auth_timeout=connect_timeout,
    )
    if cred.key_path:
        connect_kwargs["key_filename"] = cred.key_path
    elif cred.password:
        connect_kwargs["password"] = cred.password
    else:
        raise SSHExecutionError("No usable SSH credential (neither key nor password)")

    client.connect(**connect_kwargs)
    return client


def run_allowlisted_command(
    host: str,
    port: int,
    credential_ref: str,
    command_key: str,
    params: Optional[dict] = None,
    known_hosts_path: str = os.environ.get("SSH_KNOWN_HOSTS_PATH", os.path.expanduser("~/.ssh/known_hosts")),
    connect_timeout: int = 8,
    command_timeout: int = 20,
) -> SSHResult:
    """Execute one allowlisted command against `host` over SSH.

    Args:
        host: target hostname or IP.
        port: SSH port (usually 22).
        credential_ref: named credential set, e.g. "prod" / "nonprod".
        command_key: must be a key in COMMAND_REGISTRY.
        params: values to safely substitute into the command template.
        known_hosts_path: pinned known_hosts file for host-key verification.
        connect_timeout / command_timeout: seconds.

    Returns:
        SSHResult with exit status, stdout, stderr.

    Raises:
        CommandNotAllowedError: command_key isn't in the registry.
        SSHExecutionError: connection or execution failure.
    """
    if command_key not in COMMAND_REGISTRY:
        raise CommandNotAllowedError(f"'{command_key}' is not an allowlisted SSH operation")

    template = COMMAND_REGISTRY[command_key]
    params = params or {}
    try:
        # shlex.quote every substituted value — templates control the shape,
        # params can never inject extra shell syntax.
        safe_params = {k: shlex.quote(str(v)) for k, v in params.items()}
        command = template.format(**safe_params)
    except KeyError as exc:
        raise SSHExecutionError(f"Missing required param for '{command_key}': {exc}") from exc

    cred = get_ssh_credential(credential_ref)
    client = None
    try:
        client = _build_client(host, port, cred, known_hosts_path, connect_timeout)
        stdin, stdout, stderr = client.exec_command(command, timeout=command_timeout)
        exit_status = stdout.channel.recv_exit_status()
        result = SSHResult(
            exit_status=exit_status,
            stdout=stdout.read().decode("utf-8", errors="replace"),
            stderr=stderr.read().decode("utf-8", errors="replace"),
            command=command,
        )
        logger.info("SSH %s@%s: '%s' -> exit=%s", cred.username, host, command_key, exit_status)
        return result
    except Exception as exc:
        logger.error("SSH command failed on %s (%s): %s", host, command_key, exc)
        raise SSHExecutionError(str(exc)) from exc
    finally:
        if client:
            client.close()
