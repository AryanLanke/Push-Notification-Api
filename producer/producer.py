"""
Producer — Notification Delivery API (Modular Architecture)

Flask REST API with queue-based notification delivery.
Manages device registration, notification broadcasting, and history.

Usage:
    python producer.py      # Runs on port 5000
"""

from flask import Flask, jsonify
from dotenv import load_dotenv
import os

# Import our database definitions (from database.py)
from database import db

# Import our web address endpoints (from endpoints.py)
from endpoints import api, get_network_ip

# Import our background worker logic (from logic.py)
from logic import start_worker_pool, WORKER_POOL_SIZE

# Load passwords/API keys from the .env file secretly
load_dotenv()


def create_app(testing=False):
    """
    This function acts as a 'factory' that creates our Flask web server.
    We put it inside a function so we can easily create a fake 'testing'
    version of the server whenever we run pytest.
    """
    app = Flask(__name__)

    # Configure database
    # We use SQLite (a simple file-based database) by default.
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URI", "sqlite:///notifications.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # If we are running tests, use a temporary "in-memory" database
    # so we don't mess up our real data.
    if testing:
        app.config["TESTING"] = True
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    # Connect the database to our Flask app
    db.init_app(app)

    # Enable CORS (Cross-Origin Resource Sharing)
    # This prevents browsers from blocking requests if the frontend
    # is running on a different port than this backend API.
    try:
        from flask_cors import CORS

        CORS(app)
    except ImportError:

        @app.after_request
        def add_cors_headers(response):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization"
            )
            return response

    # Attach all of our API endpoints (routes.py) to this application
    app.register_blueprint(api)

    # Error Handlers
    @app.errorhandler(404)
    def not_found(error):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Endpoint not found",
                    "hint": "Use GET /api for available endpoints.",
                }
            ),
            404,
        )

    @app.errorhandler(405)
    def method_not_allowed(error):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Method not allowed",
                    "hint": "Check the HTTP method (GET, POST, DELETE)",
                }
            ),
            405,
        )

    @app.errorhandler(500)
    def internal_error(error):
        return (
            jsonify({"success": False, "error": "Internal server error"}),
            500,
        )

    # Initialize database and worker pool on startup
    with app.app_context():
        # This scans database.py and creates the tables if they don't exist yet
        db.create_all()
        # Start our 5 background threads to process notifications
        if not testing:
            start_worker_pool(app)

    return app


# This block only runs if we type `python producer.py` in the terminal
if __name__ == "__main__":
    app = create_app()

    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        local_ip = get_network_ip()
        print("=" * 60)
        print("NOTIFICATION API — Producer (Modular)")
        print("=" * 60)
        print("  Local:   http://localhost:5000")
        print(f"  Network: http://{local_ip}:5000")
        print("  API:     http://localhost:5000/api")
        print("")
        print("Architecture:")
        print("  Producer → Queue → Workers → Consumer Devices")
        print(f"  Worker Pool: {WORKER_POOL_SIZE} threads")
        print("  Database: SQLite (notifications.db)")
        print("")
        print("Press Ctrl+C to stop")
        print("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=True)
