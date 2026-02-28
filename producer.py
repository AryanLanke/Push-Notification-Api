"""
Producer — Notification Delivery API

Flask REST API with queue-based notification delivery.
Manages device registration, notification broadcasting, and history.

Architecture:
    Producer:  API endpoint enqueues notification jobs.
    Consumer:  Separate application(s) on different port(s) that
               receive and display notifications.
    Broker:    Thread-safe queue bridges producer and worker pool.
    Routing:   Device-type routing (web, mobile, pager).

Persistence:
    SQLite database via SQLAlchemy for device storage.
    VAPID keys loaded from .env file.

Usage:
    python producer.py      # Runs on port 5000
"""

from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
import socket
import json
import requests
import queue
import threading
import uuid
import time
from datetime import datetime
from pywebpush import webpush, WebPushException


def get_network_ip():
    """Get the local network IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Load environment variables from .env
load_dotenv()

# ============================================================================
# FLASK APP INITIALIZATION
# ============================================================================
app = Flask(__name__)

# Database configuration (SQLite)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URI", "sqlite:///notifications.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# CORS configuration
try:
    from flask_cors import CORS
    CORS(app)
    print("✓ CORS enabled via flask-cors")
except ImportError:
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response
    print("⚠ CORS enabled via manual headers (install flask-cors for better support)")

# ============================================================================
# VAPID CONFIGURATION (from .env)
# ============================================================================
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS = {"sub": os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")}

VALID_DEVICE_TYPES = ["web", "mobile", "pager"]


def send_web_push(device_dict, title, message):
    """
    Send notification to a web consumer.
    Checks if it's a 'Simulation' (IP/Port) or a 'Real Browser' (VAPID).
    """
    sub_json = device_dict.get('subscription_data')

    if sub_json:
        # Real web push via VAPID
        try:
            subscription = json.loads(sub_json)
            payload = json.dumps({"title": title, "body": message})

            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            print(f"[REAL-WEB] Delivered via global push to '{device_dict['name']}'")
            return {"device_id": device_dict["id"], "device_name": device_dict["name"],
                    "device_type": "web", "status": "success",
                    "message": "Delivered via Global Push Service",
                    "received_at": datetime.now().isoformat()}
        except WebPushException as ex:
            print(f"[WEB:VAPID-FAIL] {ex}")
            return {"device_id": device_dict["id"], "device_name": device_dict["name"],
                    "device_type": "web", "status": "failed",
                    "message": f"Global Push Error: {ex}"}
        except Exception as e:
            return {"device_id": device_dict["id"], "device_name": device_dict["name"],
                    "device_type": "web", "status": "failed",
                    "message": f"System Error: {str(e)}"}

    else:
        # Simulation mode — deliver via local HTTP POST
        address = f"http://{device_dict['ip_address']}:{device_dict['port']}/receive"
        try:
            payload = {"title": title, "message": message, "from": "Producer API"}
            response = requests.post(address, json=payload, timeout=5)
            if response.status_code == 200:
                return {"device_id": device_dict["id"], "device_name": device_dict["name"],
                        "device_type": "web", "status": "success",
                        "message": "Delivered to consumer server"}
            return {"device_id": device_dict["id"], "device_name": device_dict["name"],
                    "device_type": "web", "status": "failed",
                    "message": f"Consumer error: {response.status_code}"}
        except Exception as e:
            return {"device_id": device_dict["id"], "device_name": device_dict["name"],
                    "device_type": "web", "status": "failed",
                    "message": f"Connection failed: {str(e)}"}


# ============================================================================
# DATABASE MODELS
# ============================================================================

class Device(db.Model):
    """Registered device stored in the database."""
    __tablename__ = "devices"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(20), nullable=False, default="web")
    ip_address = db.Column(db.String(50), nullable=False, default="127.0.0.1")
    port = db.Column(db.Integer, nullable=False, default=5001)
    email = db.Column(db.String(100), default="")
    subscription_data = db.Column(db.Text, nullable=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "device_id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "ip_address": self.ip_address,
            "port": self.port,
            "email": self.email,
            "has_subscription": bool(self.subscription_data),
            "address": f"http://{self.ip_address}:{self.port}",
            "registered_at": self.registered_at.isoformat()
        }


class Notification(db.Model):
    """Notification history stored in the database."""
    __tablename__ = "notifications"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    enqueued_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    total_devices = db.Column(db.Integer, default=0)
    successful = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="queued")
    details = db.Column(db.Text, default="[]")


# Create tables on startup
with app.app_context():
    db.create_all()
    print("✓ Database initialized (SQLite)")

# ============================================================================
# MESSAGE QUEUE (Producer → Worker Pool bridge)
# ============================================================================
notification_queue = queue.Queue()

# Tracks job processing results by job_id (in-memory for speed)
job_tracker = {}

# ============================================================================
# NOTIFICATION HANDLERS (per device type)
# ============================================================================


def send_mobile_push(device_dict, title, message):
    """Send mobile push notification. Replace with FCM/APNs integration."""
    time.sleep(0.2)
    print(f"[MOBILE:SIM] Push simulated for '{device_dict['name']}' (ID: {device_dict['id']})")
    return {"device_id": device_dict["id"], "device_name": device_dict["name"],
            "device_type": "mobile", "status": "success",
            "message": "Mobile push simulated (integrate FCM/APNs for production)"}


def send_pager_notification(device_dict, title, message):
    """Send pager notification. Replace with pager gateway integration."""
    time.sleep(0.1)
    print(f"[PAGER:SIM] Alert simulated for '{device_dict['name']}' (ID: {device_dict['id']})")
    return {"device_id": device_dict["id"], "device_name": device_dict["name"],
            "device_type": "pager", "status": "success",
            "message": "Pager alert simulated (integrate pager gateway for production)"}


# Route map: device_type → handler function
DEVICE_HANDLERS = {
    "web": send_web_push,
    "mobile": send_mobile_push,
    "pager": send_pager_notification,
}

# ============================================================================
# BACKGROUND WORKER POOL
# ============================================================================
WORKER_POOL_SIZE = 5


def notification_worker(worker_id):
    """
    Continuously consumes jobs from notification_queue.
    Routes each device to the correct handler.
    Runs in a daemon thread — exits when the main process stops.
    """
    while True:
        job = notification_queue.get()
        job_id = job["job_id"]
        title = job["title"]
        message = job["message"]
        target_devices = job["target_devices"]

        print(f"\n[WORKER-{worker_id}] Processing job {job_id}: '{title}' → {len(target_devices)} device(s)")

        job_tracker[job_id]["status"] = "processing"

        results = []
        threads = []

        for device_dict in target_devices:
            handler = DEVICE_HANDLERS.get(device_dict["device_type"], send_web_push)

            def _dispatch(d=device_dict, h=handler):
                result = h(d, title, message)
                results.append(result)

            t = threading.Thread(target=_dispatch)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        successful = len([r for r in results if r["status"] == "success"])
        failed = len([r for r in results if r["status"] == "failed"])

        # Update database record
        with app.app_context():
            notif = db.session.get(Notification, job_id)
            if notif:
                notif.processed_at = datetime.utcnow()
                notif.successful = successful
                notif.failed = failed
                notif.status = "completed"
                notif.details = json.dumps(results)
                db.session.commit()

        # Update in-memory tracker
        job_tracker[job_id].update({
            "status": "completed",
            "processed_at": datetime.now().isoformat(),
            "successful": successful,
            "failed": failed,
            "results": results
        })

        print(f"[WORKER-{worker_id}] Job {job_id} done — {successful} ok, {failed} failed")
        notification_queue.task_done()


# Start worker pool
for i in range(WORKER_POOL_SIZE):
    t = threading.Thread(target=notification_worker, args=(i + 1,), daemon=True)
    t.start()
print(f"✓ Worker pool started ({WORKER_POOL_SIZE} workers)")

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route("/", methods=["GET"])
def admin_dashboard():
    """Serve the Producer admin dashboard."""
    return render_template("producer.html")


@app.route("/api", methods=["GET"])
def api_info():
    """Discovery endpoint: returns system info and available API routes."""
    return jsonify({
        "message": "Notification Delivery API — Producer",
        "version": "3.0.0",
        "architecture": "Distributed Producer-Consumer with SQLite persistence",
        "device_types": VALID_DEVICE_TYPES,
        "persistence": "SQLite database",
        "worker_pool": WORKER_POOL_SIZE,
        "network_ip": get_network_ip(),
        "endpoints": {
            "GET  /api": "This info",
            "GET  /devices": "List all registered devices",
            "POST /devices/register": "Register a device (with IP/port)",
            "DELETE /devices/<device_id>": "Remove a device",
            "POST /notifications/send": "Enqueue notification (producer)",
            "GET  /notifications/status/<job_id>": "Check job processing status",
            "GET  /notifications/history": "View notification history",
            "GET  /vapid/public-key": "Get VAPID public key"
        }
    }), 200


@app.route("/vapid/public-key", methods=["GET"])
def get_vapid_key():
    """Return VAPID public key for client-side web push subscription."""
    return jsonify({
        "success": True,
        "public_key": VAPID_PUBLIC_KEY,
        "configured": bool(VAPID_PUBLIC_KEY)
    }), 200


# ============================================================================
# DEVICE ENDPOINTS
# ============================================================================

@app.route("/devices", methods=["GET"])
def list_devices():
    """List all registered devices from the database."""
    devices = Device.query.all()
    devices_list = [d.to_dict() for d in devices]

    return jsonify({
        "success": True,
        "message": f"Found {len(devices_list)} registered device(s)",
        "count": len(devices_list),
        "devices": devices_list
    }), 200


@app.route("/devices/register", methods=["POST"])
def register_device():
    """
    Register a new consumer device.
    Body: {name (required), ip_address, port, device_type, email}
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "No JSON data provided",
            "hint": "Send a JSON body with 'name' field"
        }), 400

    device_name = data.get("name", "").strip()
    if not device_name:
        return jsonify({
            "success": False,
            "error": "Missing required field: 'name'",
            "hint": "The 'name' field is required and cannot be empty"
        }), 400

    device_type = data.get("device_type", "web").strip().lower()
    if device_type not in VALID_DEVICE_TYPES:
        return jsonify({
            "success": False,
            "error": f"Invalid device_type: '{device_type}'",
            "hint": f"Must be one of: {VALID_DEVICE_TYPES}"
        }), 400

    ip_address = data.get("ip_address", "127.0.0.1").strip()
    port = data.get("port", 5001)
    email = data.get("email", "").strip()

    device = Device(
        name=device_name,
        device_type=device_type,
        ip_address=ip_address,
        port=int(port),
        email=email
    )
    db.session.add(device)
    db.session.commit()

    print(f"[NEW DEVICE] Registered: '{device_name}' type={device_type} "
          f"at {ip_address}:{port} (ID: {device.id})")

    return jsonify({
        "success": True,
        "message": "Device registered successfully",
        "device": device.to_dict()
    }), 201


@app.route("/devices/<device_id>", methods=["DELETE"])
def unregister_device(device_id):
    """Remove a device from the database by its ID."""
    device = db.session.get(Device, device_id)

    if not device:
        return jsonify({
            "success": False,
            "error": "Device not found",
            "device_id": device_id,
            "hint": "Check the device_id or use GET /devices to see all registered devices"
        }), 404

    device_name = device.name
    db.session.delete(device)
    db.session.commit()

    print(f"[REMOVED] Device unregistered: '{device_name}' (ID: {device_id})")

    return jsonify({
        "success": True,
        "message": "Device unregistered successfully",
        "device_id": device_id,
        "device_name": device_name
    }), 200


# ============================================================================
# NOTIFICATION ENDPOINTS
# ============================================================================

@app.route("/notifications/send", methods=["POST"])
def send_notification():
    """
    Accept a notification request and push it to the worker queue.
    Returns immediately (202 Accepted) while workers handle delivery.
    Body: {title (required), message (required), device_ids (optional)}
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "No JSON data provided",
            "hint": "Send a JSON body with 'title' and 'message' fields"
        }), 400

    title = data.get("title", "").strip()
    message = data.get("message", "").strip()
    device_ids = data.get("device_ids", [])
    if not device_ids and data.get("device_id"):
        device_ids = [data.get("device_id")]

    if not title:
        return jsonify({"success": False, "error": "Missing required field: 'title'"}), 400

    if not message:
        return jsonify({"success": False, "error": "Missing required field: 'message'"}), 400

    # Fetch target devices from database
    if device_ids:
        target_devices = Device.query.filter(Device.id.in_(device_ids)).all()
        not_found = [did for did in device_ids if did not in [d.id for d in target_devices]]

        if not target_devices:
            return jsonify({
                "success": False,
                "error": "None of the specified devices were found",
                "not_found": not_found
            }), 404
    else:
        target_devices = Device.query.all()

    if not target_devices:
        return jsonify({
            "success": False,
            "error": "No devices registered",
            "hint": "Register at least one device before sending notifications"
        }), 404

    # Create notification record in database
    job_id = str(uuid.uuid4())
    notif = Notification(
        id=job_id,
        title=title,
        message=message,
        total_devices=len(target_devices),
        status="queued"
    )
    db.session.add(notif)
    db.session.commit()

    # Convert Device model objects to plain dicts (safe for background threads)
    device_dicts = [{
        "id": d.id,
        "name": d.name,
        "device_type": d.device_type,
        "ip_address": d.ip_address,
        "port": d.port
    } for d in target_devices]

    # Enqueue the job
    job = {
        "job_id": job_id,
        "title": title,
        "message": message,
        "target_devices": device_dicts,
        "enqueued_at": datetime.now().isoformat()
    }

    job_tracker[job_id] = {
        "status": "queued",
        "enqueued_at": job["enqueued_at"],
        "total_devices": len(device_dicts),
        "title": title
    }

    notification_queue.put(job)

    target_addresses = [f"http://{d['ip_address']}:{d['port']}" for d in device_dicts]
    print(f"[PRODUCER] Enqueued job {job_id}: '{title}' → {len(device_dicts)} device(s)")
    print(f"[PRODUCER] Targets: {target_addresses}")

    return jsonify({
        "success": True,
        "message": "Notification job enqueued",
        "job_id": job_id,
        "status": "queued",
        "total_devices": len(device_dicts),
        "target_addresses": target_addresses,
        "hint": f"Track status at GET /notifications/status/{job_id}"
    }), 202


@app.route("/notifications/status/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """
    Return the current status of a notification job.
    Possible statuses: 'queued', 'processing', 'completed'.
    """
    # Check in-memory tracker first (faster)
    if job_id in job_tracker:
        job = job_tracker[job_id]
        return jsonify({
            "success": True,
            "job_id": job_id,
            "status": job["status"],
            "enqueued_at": job.get("enqueued_at"),
            "processed_at": job.get("processed_at"),
            "total_devices": job.get("total_devices"),
            "successful": job.get("successful"),
            "failed": job.get("failed"),
            "results": job.get("results")
        }), 200

    # Fallback to database
    notif = db.session.get(Notification, job_id)
    if not notif:
        return jsonify({
            "success": False,
            "error": "Job not found",
            "hint": "Check the job_id returned from POST /notifications/send"
        }), 404

    return jsonify({
        "success": True,
        "job_id": job_id,
        "status": notif.status,
        "enqueued_at": notif.enqueued_at.isoformat() if notif.enqueued_at else None,
        "processed_at": notif.processed_at.isoformat() if notif.processed_at else None,
        "total_devices": notif.total_devices,
        "successful": notif.successful,
        "failed": notif.failed,
        "results": json.loads(notif.details) if notif.details else []
    }), 200


@app.route("/notifications/history", methods=["GET"])
def get_notification_history():
    """Return the last 50 notification jobs sent."""
    notifications = Notification.query.order_by(Notification.enqueued_at.desc()).limit(50).all()

    history = [{
        "id": n.id,
        "title": n.title,
        "message": n.message,
        "status": n.status,
        "enqueued_at": n.enqueued_at.isoformat() if n.enqueued_at else None,
        "processed_at": n.processed_at.isoformat() if n.processed_at else None,
        "total_devices": n.total_devices,
        "successful": n.successful,
        "failed": n.failed
    } for n in notifications]

    return jsonify({
        "success": True,
        "message": f"Found {len(history)} notification(s) in history",
        "count": len(history),
        "notifications": history
    }), 200


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found",
                    "hint": "Use GET /api for available endpoints."}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"success": False, "error": "Method not allowed",
                    "hint": "Check the HTTP method (GET, POST, DELETE)"}), 405

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# RUN THE SERVER
# ============================================================================

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        local_ip = get_network_ip()
        print("=" * 60)
        print("NOTIFICATION API — Producer")
        print("=" * 60)
        print(f"  Local:   http://localhost:5000")
        print(f"  Network: http://{local_ip}:5000")
        print(f"  API:     http://localhost:5000/api")
        print("")
        print("Architecture:")
        print("  Producer → Queue → Workers → Consumer Devices")
        print(f"  Worker Pool: {WORKER_POOL_SIZE} threads")
        print("  Database: SQLite (notifications.db)")
        print("")
        print("Press Ctrl+C to stop")
        print("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=True)
