from flask import Blueprint, request, jsonify, render_template
from models import db, Device, Notification
from services import (
    job_tracker,
    notification_queue,
    VALID_DEVICE_TYPES,
    VAPID_PUBLIC_KEY,
    WORKER_POOL_SIZE,
)
from datetime import datetime
import json
import uuid
import socket

# A "Blueprint" is the way Flask lets us split our app into multiple files.
# Instead of putting `@app.route` in app.py, we put `@api.route` here,
# and then app.py loads this entire "Blueprint" file at once.
api = Blueprint("api", __name__)


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


@api.route("/", methods=["GET"])
def admin_dashboard():
    """Serve the Producer admin dashboard."""
    return render_template("producer.html")


@api.route("/api", methods=["GET"])
def api_info():
    """
    Discovery endpoint: returns system info and available API routes.
    When someone visits http://localhost:5000/api in their browser,
    this code runs and sends back a JSON response (like a dictionary).
    """
    return (
        jsonify(
            {
                "message": "Notification Delivery API — Producer",
                "version": "4.0.0 (Modular Refactoring)",
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
                    "GET  /notifications/queue": "View currently queued jobs waiting for workers",
                    "GET  /notifications/status/<job_id>": "Check job processing status",
                    "GET  /notifications/history": "View notification history",
                    "GET  /vapid/public-key": "Get VAPID public key",
                },
            }
        ),
        200,
    )


@api.route("/vapid/public-key", methods=["GET"])
def get_vapid_key():
    """Return VAPID public key for client-side web push subscription."""
    return (
        jsonify(
            {
                "success": True,
                "public_key": VAPID_PUBLIC_KEY,
                "configured": bool(VAPID_PUBLIC_KEY),
            }
        ),
        200,
    )


@api.route("/devices", methods=["GET"])
def list_devices():
    """List all registered devices from the database."""
    devices = Device.query.all()
    devices_list = [d.to_dict() for d in devices]

    return (
        jsonify(
            {
                "success": True,
                "message": f"Found {len(devices_list)} registered device(s)",
                "count": len(devices_list),
                "devices": devices_list,
            }
        ),
        200,
    )


@api.route("/devices/register", methods=["POST"])
def register_device():
    """
    Register a new consumer device.
    "POST" means the user is sending us data to save.
    They send a JSON body with: {name, ip_address, port, device_type, email}
    """
    # 1. Grab the JSON data the user sent us
    data = request.get_json()

    if not data:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No JSON data provided",
                    "hint": "Send a JSON body with 'name' field",
                }
            ),
            400,
        )

    # 2. Check if they gave us a name (it's required!)
    device_name = data.get("name", "").strip()
    if not device_name:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Missing required field: 'name'",
                    "hint": "The 'name' field is required and cannot be empty",
                }
            ),
            400,
        )

    device_type = data.get("device_type", "web").strip().lower()
    if device_type not in VALID_DEVICE_TYPES:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Invalid device_type: '{device_type}'",
                    "hint": f"Must be one of: {VALID_DEVICE_TYPES}",
                }
            ),
            400,
        )

    # 3. Fill out the rest of the information
    ip_address = data.get("ip_address", "127.0.0.1").strip()
    port = data.get("port", 5001)
    email = data.get("email", "").strip()

    # 4. Create a new Database Row using our Device Class (from models.py)
    device = Device(
        name=device_name,
        device_type=device_type,
        ip_address=ip_address,
        port=int(port),
        email=email,
    )

    # 5. Tell the database to save our new row!
    db.session.add(device)
    db.session.commit()

    print(
        f"[NEW DEVICE] Registered: '{device_name}' type={device_type} "
        f"at {ip_address}:{port} (ID: {device.id})"
    )

    # 6. Send a success message back to whoever called us
    return (
        jsonify(
            {
                "success": True,
                "message": "Device registered successfully",
                "device": device.to_dict(),
            }
        ),
        201,
    )


@api.route("/devices/<device_id>", methods=["DELETE"])
def unregister_device(device_id):
    """Remove a device from the database by its ID."""
    device = db.session.get(Device, device_id)

    if not device:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Device not found",
                    "device_id": device_id,
                    "hint": "Check the device_id or use GET /devices to see all registered devices",
                }
            ),
            404,
        )

    device_name = device.name
    db.session.delete(device)
    db.session.commit()

    print(f"[REMOVED] Device unregistered: '{device_name}' (ID: {device_id})")

    return (
        jsonify(
            {
                "success": True,
                "message": "Device unregistered successfully",
                "device_id": device_id,
                "device_name": device_name,
            }
        ),
        200,
    )


@api.route("/notifications/send", methods=["POST"])
def send_notification():
    """
    Accept a notification request and push it to the worker queue.
    This doesn't wait for the notification to send. It simply drops the
    job into a queue and immediately tells the user "Accepted!"
    Meanwhile, the background threads do the real work independently.
    """
    data = request.get_json()

    if not data:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No JSON data provided",
                    "hint": "Send a JSON body with 'title' and 'message' fields",
                }
            ),
            400,
        )

    title = data.get("title", "").strip()
    message = data.get("message", "").strip()
    device_ids = data.get("device_ids", [])
    if not device_ids and data.get("device_id"):
        device_ids = [data.get("device_id")]

    if not title:
        return (
            jsonify(
                {"success": False, "error": "Missing required field: 'title'"}
            ),
            400,
        )

    if not message:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Missing required field: 'message'",
                }
            ),
            400,
        )

    # Fetch target devices from database
    if device_ids:
        target_devices = Device.query.filter(Device.id.in_(device_ids)).all()
        not_found = [
            did
            for did in device_ids
            if did not in [d.id for d in target_devices]
        ]

        if not target_devices:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "None of the specified devices were found",
                        "not_found": not_found,
                    }
                ),
                404,
            )
    else:
        target_devices = Device.query.all()

    if not target_devices:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No devices registered",
                    "hint": "Register at least one device before sending notifications",
                }
            ),
            404,
        )

    # Create notification record in database
    job_id = str(uuid.uuid4())
    notif = Notification(
        id=job_id,
        title=title,
        message=message,
        total_devices=len(target_devices),
        status="queued",
    )
    db.session.add(notif)
    db.session.commit()

    # Convert Device model objects to plain dictionaries.
    # We do this because background threads crash if they try to use raw Database objects.
    device_dicts = [
        {
            "id": d.id,
            "name": d.name,
            "device_type": d.device_type,
            "ip_address": d.ip_address,
            "port": d.port,
        }
        for d in target_devices
    ]

    # Package all of the information into a single 'Job' bundle
    job = {
        "job_id": job_id,
        "title": title,
        "message": message,
        "target_devices": device_dicts,
        "enqueued_at": datetime.now().isoformat(),
    }

    # Record the job in our fast RAM-based tracker for the UI to see instantly
    job_tracker[job_id] = {
        "status": "queued",
        "enqueued_at": job["enqueued_at"],
        "total_devices": len(device_dicts),
        "title": title,
    }

    # DROP THE JOB INTO THE QUEUE.
    # From here, the background workers (in services.py) will pick it up and process it.
    notification_queue.put(job)

    target_addresses = [
        f"http://{d['ip_address']}:{d['port']}" for d in device_dicts
    ]
    print(
        f"[PRODUCER] Enqueued job {job_id}: '{title}' → {len(device_dicts)} device(s)"
    )
    print(f"[PRODUCER] Targets: {target_addresses}")

    return (
        jsonify(
            {
                "success": True,
                "message": "Notification job enqueued",
                "job_id": job_id,
                "status": "queued",
                "total_devices": len(device_dicts),
                "target_addresses": target_addresses,
                "hint": f"Track status at GET /notifications/status/{job_id}",
            }
        ),
        202,
    )


@api.route("/notifications/status/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """
    Return the current status of a notification job.
    """
    if job_id in job_tracker:
        job = job_tracker[job_id]
        return (
            jsonify(
                {
                    "success": True,
                    "job_id": job_id,
                    "status": job["status"],
                    "enqueued_at": job.get("enqueued_at"),
                    "processed_at": job.get("processed_at"),
                    "total_devices": job.get("total_devices"),
                    "successful": job.get("successful"),
                    "failed": job.get("failed"),
                    "results": job.get("results"),
                }
            ),
            200,
        )

    notif = db.session.get(Notification, job_id)
    if not notif:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Job not found",
                    "hint": "Check the job_id returned from POST /notifications/send",
                }
            ),
            404,
        )

    return (
        jsonify(
            {
                "success": True,
                "job_id": job_id,
                "status": notif.status,
                "enqueued_at": (
                    notif.enqueued_at.isoformat()
                    if notif.enqueued_at
                    else None
                ),
                "processed_at": (
                    notif.processed_at.isoformat()
                    if notif.processed_at
                    else None
                ),
                "total_devices": notif.total_devices,
                "successful": notif.successful,
                "failed": notif.failed,
                "results": json.loads(notif.details) if notif.details else [],
            }
        ),
        200,
    )


@api.route("/notifications/queue", methods=["GET"])
def get_queued_jobs():
    """Return all jobs that are currently 'queued' or 'processing'."""
    active_jobs = []

    for job_id, job in job_tracker.items():
        if job["status"] in ["queued", "processing"]:
            active_jobs.append(
                {
                    "job_id": job_id,
                    "title": job.get("title", "Unknown"),
                    "status": job["status"],
                    "total_devices": job.get("total_devices", 0),
                    "enqueued_at": job.get("enqueued_at"),
                }
            )

    active_jobs.sort(
        key=lambda x: x["enqueued_at"] if x["enqueued_at"] else ""
    )

    return (
        jsonify(
            {"success": True, "count": len(active_jobs), "queue": active_jobs}
        ),
        200,
    )


@api.route("/notifications/history", methods=["GET"])
def get_notification_history():
    """Return the last 50 notification jobs sent."""
    notifications = (
        Notification.query.order_by(Notification.enqueued_at.desc())
        .limit(50)
        .all()
    )

    history = [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "status": n.status,
            "enqueued_at": (
                n.enqueued_at.isoformat() if n.enqueued_at else None
            ),
            "processed_at": (
                n.processed_at.isoformat() if n.processed_at else None
            ),
            "total_devices": n.total_devices,
            "successful": n.successful,
            "failed": n.failed,
        }
        for n in notifications
    ]

    return (
        jsonify(
            {
                "success": True,
                "message": f"Found {len(history)} notification(s) in history",
                "count": len(history),
                "notifications": history,
            }
        ),
        200,
    )
