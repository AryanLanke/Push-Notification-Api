"""
Notification Delivery API - Producer/Consumer Architecture

Flask REST API with queue-based notification delivery.
JSON-only backend — no frontend dependencies.

Architecture:
    Producer: API endpoint enqueues notification jobs into a queue.
    Consumer: Background worker thread dequeues and processes jobs.
    Routing:  Notifications routed to handlers based on device_type.

Device types supported:
    - "web"    → Web Push via VAPID/pywebpush (structure prepared)
    - "mobile" → FCM/APNs (simulated)
    - "pager"  → Pager gateway (simulated)
"""

from flask import Flask, request, jsonify
import threading
import queue
import time
import uuid
import json
from datetime import datetime

# ============================================================================
# FLASK APP INITIALIZATION
# ============================================================================
app = Flask(__name__)

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

VALID_DEVICE_TYPES = ["web", "mobile", "pager"]

# ============================================================================
# VAPID CONFIGURATION (Web Push)
# ============================================================================
VAPID_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgXZPF2yqh5c2NRQd0
IshEqtynnMwLXNJ8XWkSh6lI+HKhRANCAASp7Fvl3l7pYu6WtEITxLn6/y0OmbXs
gr13n+MrJxon10RHtlRfAInHaceoBOqBhmrtKAmNGmJ7RsW3ADwUlrVd
-----END PRIVATE KEY-----"""

VAPID_PUBLIC_KEY = "BKnsW-XeXuli7pa0QhPEufr_LQ6ZteyCvXef4ysnGifXREe2VF8Aicdpx6gE6oGGau0oCY0aYntGxbcAPBSWtV0"

VAPID_CLAIMS = {"sub": "mailto:admin@example.com"}

# ============================================================================
# IN-MEMORY STORAGE
# ============================================================================
# {device_id: {token, name, email, device_type, subscription_data, registered_at}}
registered_devices = {}

notification_history = []

# ============================================================================
# MESSAGE QUEUE (Producer → Consumer bridge)
# ============================================================================
# Jobs are dicts: {job_id, title, message, target_devices, enqueued_at}
notification_queue = queue.Queue()

# Tracks job processing results by job_id
# {job_id: {status, enqueued_at, processed_at, results}}
job_tracker = {}

# ============================================================================
# NOTIFICATION HANDLERS (per device type)
# ============================================================================

def send_web_push(device_id, device_info, title, message):
    """
    Send web push notification.
    Uses VAPID + pywebpush when real keys are configured.
    Falls back to simulation if keys are placeholders.
    """
    subscription_data = device_info.get("subscription_data")

    if VAPID_PRIVATE_KEY != "PLACEHOLDER_PRIVATE_KEY" and subscription_data:
        # Real web push path — requires: pip install pywebpush
        try:
            from pywebpush import webpush, WebPushException
            payload = json.dumps({"title": title, "body": message})
            webpush(
                subscription_info=subscription_data,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            print(f"[WEB] Push sent to '{device_info['name']}' (ID: {device_id})")
            return {"device_id": device_id, "device_name": device_info["name"],
                    "device_type": "web", "status": "success",
                    "message": "Web push delivered"}
        except Exception as e:
            print(f"[WEB:FAIL] {device_info['name']}: {e}")
            return {"device_id": device_id, "device_name": device_info["name"],
                    "device_type": "web", "status": "failed",
                    "message": str(e)}
    else:
        # Simulation mode
        time.sleep(0.15)
        print(f"[WEB:SIM] Push simulated for '{device_info['name']}' (ID: {device_id})")
        return {"device_id": device_id, "device_name": device_info["name"],
                "device_type": "web", "status": "success",
                "message": "Web push simulated (VAPID keys not configured)"}


def send_mobile_push(device_id, device_info, title, message):
    """Send mobile push notification. Replace with FCM/APNs integration."""
    time.sleep(0.2)
    print(f"[MOBILE:SIM] Push simulated for '{device_info['name']}' (ID: {device_id})")
    return {"device_id": device_id, "device_name": device_info["name"],
            "device_type": "mobile", "status": "success",
            "message": "Mobile push simulated (integrate FCM/APNs for production)"}


def send_pager_notification(device_id, device_info, title, message):
    """Send pager notification. Replace with pager gateway integration."""
    time.sleep(0.1)
    print(f"[PAGER:SIM] Alert simulated for '{device_info['name']}' (ID: {device_id})")
    return {"device_id": device_id, "device_name": device_info["name"],
            "device_type": "pager", "status": "success",
            "message": "Pager alert simulated (integrate pager gateway for production)"}


# Route map: device_type → handler function
DEVICE_HANDLERS = {
    "web": send_web_push,
    "mobile": send_mobile_push,
    "pager": send_pager_notification,
}

# ============================================================================
# CONSUMER — Background worker thread
# ============================================================================

WORKER_POOL_SIZE = 5

def notification_worker(worker_id):
    """
    Continuously consumes jobs from notification_queue.
    Each job fans out to per-device threads, routed by device_type.
    Runs in a daemon thread — exits when the main process stops.
    """
    while True:
        job = notification_queue.get()  # Blocks until a job is available
        job_id = job["job_id"]
        title = job["title"]
        message = job["message"]
        target_devices = job["target_devices"]

        print(f"\n[CONSUMER-{worker_id}] Processing job {job_id}: '{title}' → {len(target_devices)} device(s)")

        job_tracker[job_id]["status"] = "processing"

        results = []
        threads = []

        for device_id, device_info in target_devices.items():
            device_type = device_info.get("device_type", "web")
            handler = DEVICE_HANDLERS.get(device_type, send_web_push)

            def _dispatch(did=device_id, dinfo=device_info, h=handler):
                result = h(did, dinfo, title, message)
                results.append(result)

            t = threading.Thread(target=_dispatch)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        successful = len([r for r in results if r["status"] == "success"])
        failed = len([r for r in results if r["status"] == "failed"])

        # Record to history
        record = {
            "id": job_id,
            "title": title,
            "message": message,
            "enqueued_at": job["enqueued_at"],
            "processed_at": datetime.now().isoformat(),
            "total_devices": len(target_devices),
            "successful": successful,
            "failed": failed,
            "details": results
        }
        notification_history.append(record)

        # Update job tracker
        job_tracker[job_id].update({
            "status": "completed",
            "processed_at": record["processed_at"],
            "successful": successful,
            "failed": failed,
            "results": results
        })

        print(f"[CONSUMER-{worker_id}] Job {job_id} done — {successful} ok, {failed} failed")
        notification_queue.task_done()


# Start worker pool (5 consumer threads)
for i in range(WORKER_POOL_SIZE):
    t = threading.Thread(target=notification_worker, args=(i + 1,), daemon=True)
    t.start()
print(f"✓ Worker pool started ({WORKER_POOL_SIZE} consumers)")

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route("/api", methods=["GET"])
def api_info():
    """Return API info and endpoints."""
    return jsonify({
        "message": "Notification Delivery API — Producer/Consumer Architecture",
        "version": "2.0.0",
        "architecture": "Queue-based producer/consumer with device-type routing",
        "device_types": VALID_DEVICE_TYPES,
        "endpoints": {
            "GET  /api": "This info",
            "GET  /devices": "List all registered devices",
            "POST /devices/register": "Register a device (web/mobile/pager)",
            "POST /devices/subscribe": "Store web push subscription for a device",
            "DELETE /devices/<device_id>": "Remove a device",
            "POST /notifications/send": "Enqueue notification (producer)",
            "GET  /notifications/status/<job_id>": "Check job processing status",
            "GET  /notifications/history": "View notification history",
            "GET  /vapid/public-key": "Get VAPID public key for web push"
        }
    }), 200


@app.route("/vapid/public-key", methods=["GET"])
def get_vapid_key():
    """Return VAPID public key for client-side web push subscription."""
    return jsonify({
        "success": True,
        "public_key": VAPID_PUBLIC_KEY,
        "configured": VAPID_PUBLIC_KEY != "PLACEHOLDER_PUBLIC_KEY"
    }), 200


# ============================================================================
# DEVICE ENDPOINTS
# ============================================================================

@app.route("/devices", methods=["GET"])
def list_devices():
    """List all registered devices."""
    devices_list = [
        {
            "device_id": device_id,
            "name": info.get("name", "Unknown"),
            "email": info.get("email", ""),
            "device_type": info.get("device_type", "web"),
            "has_subscription": bool(info.get("subscription_data")),
            "registered_at": info.get("registered_at", "Unknown")
        }
        for device_id, info in registered_devices.items()
    ]

    return jsonify({
        "success": True,
        "message": f"Found {len(devices_list)} registered device(s)",
        "count": len(devices_list),
        "devices": devices_list
    }), 200


@app.route("/devices/register", methods=["POST"])
def register_device():
    """
    Register a new device.
    Body: {name: required, email: optional, device_type: "web"|"mobile"|"pager"}
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

    email = data.get("email", "").strip()
    device_type = data.get("device_type", "web").strip().lower()

    if device_type not in VALID_DEVICE_TYPES:
        return jsonify({
            "success": False,
            "error": f"Invalid device_type: '{device_type}'",
            "hint": f"Must be one of: {VALID_DEVICE_TYPES}"
        }), 400

    device_id = str(uuid.uuid4())

    registered_devices[device_id] = {
        "token": device_id,
        "name": device_name,
        "device_type": device_type,
        "subscription_data": None,
        "registered_at": datetime.now().isoformat()
    }

    print(f"[NEW DEVICE] Registered: '{device_name}' type={device_type} (ID: {device_id})")

    return jsonify({
        "success": True,
        "message": "Device registered successfully",
        "device_id": device_id,
        "device_name": device_name,
        "device_type": device_type,
        "email": email,
        "registered_at": registered_devices[device_id]["registered_at"]
    }), 201


@app.route("/devices/subscribe", methods=["POST"])
def subscribe_device():
    """
    Store web push subscription object for an existing device.
    Body: {device_id: required, subscription: {endpoint, keys: {p256dh, auth}}}
    Used by browser clients after calling PushManager.subscribe().
    """
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "No JSON data provided"}), 400

    device_id = data.get("device_id", "").strip()
    subscription = data.get("subscription")

    if not device_id:
        return jsonify({"success": False, "error": "Missing field: 'device_id'"}), 400

    if device_id not in registered_devices:
        return jsonify({"success": False, "error": "Device not found"}), 404

    if not subscription or not isinstance(subscription, dict):
        return jsonify({
            "success": False,
            "error": "Missing or invalid 'subscription' object",
            "hint": "Pass the PushSubscription object from PushManager.subscribe()"
        }), 400

    # Validate subscription structure
    endpoint = subscription.get("endpoint", "")
    keys = subscription.get("keys", {})
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return jsonify({
            "success": False,
            "error": "Subscription must contain endpoint and keys (p256dh, auth)"
        }), 400

    registered_devices[device_id]["subscription_data"] = subscription
    registered_devices[device_id]["device_type"] = "web"

    print(f"[SUBSCRIBE] Web push subscription stored for device {device_id}")

    return jsonify({
        "success": True,
        "message": "Web push subscription stored",
        "device_id": device_id
    }), 200


@app.route("/devices/<device_id>", methods=["DELETE"])
def unregister_device(device_id):
    """Remove a device by ID."""
    if device_id not in registered_devices:
        return jsonify({
            "success": False,
            "error": "Device not found",
            "device_id": device_id,
            "hint": "Check the device_id or use GET /devices to see all registered devices"
        }), 404

    device_info = registered_devices[device_id]
    del registered_devices[device_id]

    print(f"[REMOVED] Device unregistered: '{device_info.get('name')}' (ID: {device_id})")

    return jsonify({
        "success": True,
        "message": "Device unregistered successfully",
        "device_id": device_id,
        "device_name": device_info.get("name", "Unknown")
    }), 200


# ============================================================================
# NOTIFICATION ENDPOINTS (PRODUCER)
# ============================================================================

@app.route("/notifications/send", methods=["POST"])
def send_notification():
    """
    Producer endpoint — validates and enqueues a notification job.
    Does NOT process inline. Consumer worker handles delivery.
    Body: {title, message, device_ids (optional)}
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
        return jsonify({
            "success": False,
            "error": "Missing required field: 'title'"
        }), 400

    if not message:
        return jsonify({
            "success": False,
            "error": "Missing required field: 'message'"
        }), 400

    if not registered_devices:
        return jsonify({
            "success": False,
            "error": "No devices registered"
        }), 404

    # Resolve target devices
    if device_ids:
        target_devices = {}
        not_found = []
        for dev_id in device_ids:
            if dev_id in registered_devices:
                target_devices[dev_id] = registered_devices[dev_id].copy()
            else:
                not_found.append(dev_id)

        if not target_devices:
            return jsonify({
                "success": False,
                "error": "None of the specified devices were found",
                "not_found": not_found
            }), 404
    else:
        target_devices = {k: v.copy() for k, v in registered_devices.items()}

    # Create job and enqueue (this is the PRODUCER action)
    job_id = str(uuid.uuid4())
    enqueued_at = datetime.now().isoformat()

    job = {
        "job_id": job_id,
        "title": title,
        "message": message,
        "target_devices": target_devices,
        "enqueued_at": enqueued_at
    }

    job_tracker[job_id] = {
        "status": "queued",
        "enqueued_at": enqueued_at,
        "total_devices": len(target_devices),
        "title": title
    }

    notification_queue.put(job)

    print(f"[PRODUCER] Enqueued job {job_id}: '{title}' → {len(target_devices)} device(s)")

    return jsonify({
        "success": True,
        "message": "Notification job enqueued",
        "job_id": job_id,
        "status": "queued",
        "total_devices": len(target_devices),
        "hint": f"Track status at GET /notifications/status/{job_id}"
    }), 202


@app.route("/notifications/status/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """Check the processing status of a notification job."""
    if job_id not in job_tracker:
        return jsonify({
            "success": False,
            "error": "Job not found",
            "hint": "Check the job_id returned from POST /notifications/send"
        }), 404

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


@app.route("/notifications/history", methods=["GET"])
def get_notification_history():
    """Get notification history (last 50)."""
    return jsonify({
        "success": True,
        "message": f"Found {len(notification_history)} notification(s) in history",
        "count": len(notification_history),
        "notifications": notification_history[-50:]
    }), 200


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({
        "success": False,
        "error": "Endpoint not found",
        "hint": "Use GET /api for available endpoints."
    }), 404


@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 errors."""
    return jsonify({
        "success": False,
        "error": "Method not allowed",
        "hint": "Check the HTTP method (GET, POST, DELETE)"
    }), 405


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500


# ============================================================================
# RUN THE SERVER
# ============================================================================

def get_local_ip():
    """Get local network IP address."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    import os

    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        local_ip = get_local_ip()
        print("=" * 60)
        print("NOTIFICATION API v2 — Producer/Consumer")
        print("=" * 60)
        print(f"  Local:   http://localhost:5000")
        print(f"  Network: http://{local_ip}:5000")
        print(f"  API:     http://localhost:5000/api")
        print("")
        print("Architecture:")
        print("  Producer → Queue → Consumer → Device Handlers")
        print("  Device types: web | mobile | pager")
        print("")
        print("Press Ctrl+C to stop")
        print("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=True)           