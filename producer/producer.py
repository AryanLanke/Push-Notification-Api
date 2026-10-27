"""
Producer — Notification Delivery API (Production Hardened)

Flask REST API with durable queue-based notification delivery.
Supports SQLite (development) and PostgreSQL (production).
Manages device registration, notification broadcasting, and real-time SSE.
"""

from flask import Flask, jsonify
from dotenv import load_dotenv
import os
import logging

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ProducerApp")

# Load environment configuration
load_dotenv()

from database import db
from endpoints import api, get_network_ip
from logic import start_worker_pool, WORKER_POOL_SIZE

_workers_started = False


def create_app(testing=False):
    """Application factory for the Producer Flask API."""
    global _workers_started
    app = Flask(__name__)

    # Database configuration
    database_uri = os.getenv("DATABASE_URI", "sqlite:///notifications.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = database_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if testing:
        app.config["TESTING"] = True
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    db.init_app(app)

    # Enable CORS
    try:
        from flask_cors import CORS
        CORS(app)
    except ImportError:
        @app.after_request
        def add_cors_headers(response):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
            return response

    # Register routes
    app.register_blueprint(api)

    # Standard error handlers
    @app.errorhandler(404)
    def not_found(error):
        return (
            jsonify({
                "success": False,
                "error": "Endpoint not found",
                "hint": "Use GET /api for available endpoints.",
            }),
            404,
        )

    @app.errorhandler(405)
    def method_not_allowed(error):
        return (
            jsonify({
                "success": False,
                "error": "Method not allowed",
                "hint": "Check the HTTP method (GET, POST, DELETE)",
            }),
            405,
        )

    @app.errorhandler(500)
    def internal_error(error):
        return (
            jsonify({"success": False, "error": "Internal server error"}),
            500,
        )

    # Database initialization and worker startup
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            logger.error("Error creating database tables: %s", e)

        if not testing and not _workers_started:
            # Avoid duplicate worker pools under Werkzeug reloader
            if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not os.environ.get("FLASK_DEBUG"):
                start_worker_pool(app)
                _workers_started = True

    return app


# WSGI application instance for Gunicorn / uWSGI
app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PRODUCER_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ["1", "true"]

    local_ip = get_network_ip()
    logger.info("=" * 60)
    logger.info("NOTIFICATION API — Producer (Production Ready)")
    logger.info("=" * 60)
    logger.info("  Local:   http://localhost:%d", port)
    logger.info("  Network: http://%s:%d", local_ip, port)
    logger.info("  API:     http://localhost:%d/api", port)
    logger.info("  Health:  http://localhost:%d/health", port)
    logger.info("  Workers: %d threads", WORKER_POOL_SIZE)
    logger.info("=" * 60)

    app.run(host="0.0.0.0", port=port, debug=debug)
