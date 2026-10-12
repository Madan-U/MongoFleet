"""
Author      : Madan U
Description : Direct Log Parser. Connects via SSH, reads mongod.log directly without sudo,
              and updates PostgreSQL in IST.
"""

import sys
import os
import json
import logging
import shlex
import paramiko
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Server, SlowQueryLog, IndexRecommendation
from services.credential_service import get_ssh_credential

logger = logging.getLogger("atlas.cron.slow_queries")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

IST = timezone(timedelta(hours=5, minutes=30))

def parse_and_store_log(server_id, line):
    try:
        data = json.loads(line)
        if data.get("msg") != "Slow query":
            return
            
        attr = data.get("attr", {})
        namespace = attr.get("ns", "unknown.collection")
        
        if namespace.startswith("admin.") or namespace.startswith("config.") or namespace.startswith("local."):
            return

        ts_str = data.get("t", {}).get("$date")
        if ts_str:
            try:
                dt_utc = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts = dt_utc.astimezone(IST).replace(tzinfo=None)
            except Exception:
                ts = datetime.now(IST).replace(tzinfo=None)
        else:
            ts = datetime.now(IST).replace(tzinfo=None)

        query_hash = attr.get("queryHash", "UNKNOWN")
        duration = attr.get("durationMillis", 0)
        docs_scanned = attr.get("docsExamined", 0)
        query_shape = attr.get("command", {})
        
        # Check if already exists to prevent duplicate entries
        existing = SlowQueryLog.query.filter_by(
            server_id=server_id,
            ts=ts,
            query_hash=query_hash
        ).first()
        
        if existing:
            return

        slow_query = SlowQueryLog(
            server_id=server_id,
            ts=ts,
            query_hash=query_hash,
            namespace=namespace,
            operation=attr.get("type", "command"),
            duration_ms=duration,
            docs_scanned=docs_scanned,
            docs_returned=attr.get("nreturned", 0),
            query_shape=query_shape,
            raw_log=data
        )
        db.session.add(slow_query)
        
        plan_summary = attr.get("planSummary", "")
        if "COLLSCAN" in plan_summary and docs_scanned > 100:
            filter_shape = query_shape.get("filter", {})
            if filter_shape:
                index_keys = {k: 1 for k in filter_shape.keys() if not k.startswith('$')}
                if index_keys:
                    existing_rec = IndexRecommendation.query.filter_by(
                        server_id=server_id, namespace=namespace, rec_type="CREATE"
                    ).first()
                    
                    if not existing_rec:
                        rec = IndexRecommendation(
                            server_id=server_id,
                            namespace=namespace,
                            rec_type="CREATE",
                            index_keys=index_keys,
                            reason="COLLSCAN detected on slow query",
                            estimated_impact=f"Can reduce {docs_scanned} disk reads."
                        )
                        db.session.add(rec)
                        
    except json.JSONDecodeError:
        pass
    except Exception as e:
        logger.error(f"Error parsing log line: {e}")

def fetch_logs_via_ssh(server):
    # mongod log lives in <ssh_username>'s tree on the DB host; overridable per environment.
    log_path = os.environ.get("MONGO_LOG_PATH", "/apps/DB/modb/log/mongod.log")
    try:
        cred = get_ssh_credential(server.ssh_credential_ref)
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        known_hosts = os.environ.get("SSH_KNOWN_HOSTS_PATH", os.path.expanduser("~/.ssh/known_hosts"))
        if os.path.isfile(known_hosts):
            ssh.load_host_keys(known_hosts)
        # Fail closed on unknown host keys (same policy as services/ssh_service.py)
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        kwargs = dict(hostname=server.ip_address, port=22,
                      username=cred.username, timeout=10)
        if cred.key_path:
            kwargs["key_filename"] = cred.key_path
        else:
            kwargs["password"] = cred.password
        ssh.connect(**kwargs)

        # Direct tail, no sudo (<ssh_username> owns the log)
        command = f"tail -n 3000 {shlex.quote(log_path)} | grep 'Slow query'"
        stdin, stdout, stderr = ssh.exec_command(command)

        lines = stdout.readlines()
        err_output = stderr.read().decode()

        if err_output:
            logger.error(f"SSH Command Error on {server.hostname}: {err_output}")

        count = 0
        for line in lines:
            parse_and_store_log(server.id, line.strip())
            count += 1

        logger.info(f"Successfully processed {count} slow query log lines from {server.hostname}")
        db.session.commit()
        ssh.close()
    except Exception as e:
        logger.error(f"SSH Failed for {server.hostname}: {e}")
        db.session.rollback()

def run():
    app = create_app()
    with app.app_context():
        logger.info("Starting direct log parsing sync...")
        servers = Server.query.filter_by(is_active=True).all()
        for server in servers:
            fetch_logs_via_ssh(server)
        logger.info("Log parsing sync completed.")

if __name__ == "__main__":
    run()
