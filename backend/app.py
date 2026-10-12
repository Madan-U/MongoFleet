"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-09
Script Path : /data/database-management/backend/app.py
Description : Flask application factory — wires config, extensions,
               blueprints, logging, and a basic health endpoint.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify

from config import get_config
from extensions import db, migrate


def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    db.init_app(app)
    migrate.init_app(app, db)

    _configure_logging(app)

    from routes.auth import bp as auth_bp
    from routes.inventory import bp as inventory_bp
    from routes.dashboard import bp as dashboard_bp
    from routes.alerts import bp as alerts_bp
    from routes.operations import bp as operations_bp
    from routes.monitoring import bp as monitoring_bp
    from routes.audit import bp as audit_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(operations_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(audit_bp)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": "internal_error"}), 500

    return app


def _configure_logging(app: Flask) -> None:
    log_dir = app.config.get("LOG_DIR", "/data/database-management/logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(log_dir, "mongofleet.log"), maxBytes=10_000_000, backupCount=10
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    app.logger.setLevel(level)
    app.logger.addHandler(handler)
    logging.getLogger("atlas.ssh").addHandler(handler)
    logging.getLogger("atlas.mongo").addHandler(handler)


if __name__ == "__main__":
    # Dev-only entrypoint. Production runs via gunicorn + wsgi.py.
    create_app().run(host="127.0.0.1", port=8000, debug=True)
