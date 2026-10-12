"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Description : Gunicorn runtime config for MongoFleet. Binds to localhost
               only — nginx is the public-facing edge (see deploy/README.md);
               gunicorn is never exposed directly on the network interface.
"""

import multiprocessing
import os

bind = "127.0.0.1:8000"
workers = min(4, multiprocessing.cpu_count() * 2 + 1)
worker_class = "gthread"
threads = 4
timeout = 60
graceful_timeout = 30
keepalive = 5

_log_dir = os.environ.get('LOG_DIR', '/opt/mongofleet/logs')
accesslog = f"{_log_dir}/gunicorn-access.log"
errorlog = f"{_log_dir}/gunicorn-error.log"
loglevel = "info"

pidfile = f"{_log_dir}/gunicorn.pid"
