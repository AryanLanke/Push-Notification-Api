"""
REST API Endpoints and Admin Dashboard Routes for Producer.
Includes API Key authentication, SSRF protection, health checks,
Server-Sent Events streaming, and device/notification controllers.
"""

from flask import Blueprint, request, jsonify, render_template, Response, current_app
from database import db, Device, Notification
from logic import (
    job_tracker,
    update_job_tracker,
    get_job_tracker,
    get_active_queued_jobs,
    notification_queue,
    VALID_DEVICE_TYPES,
    VAPID_PUBLIC_KEY,
    WORKER_POOL_SIZE,
    sse_clients,
    sse_clients_lock,
    broadcast_sse,
)
from datetime import datetime
import functools
import json
import uuid
import socket
import queue
import os
import logging

logger = logging.getLogger("ProducerEndpoints")

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


def require_api_key(f):
    """
    Decorator enforcing API Key authentication on protected endpoints.
    Allows request through if API_KEY is unset or when running in TESTING mode.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        configured_key = os.getenv("API_KEY")
        # Bypass authentication in testing mode or if no key is configured
        if current_app.config.get("TESTING") or not configured_key:
            return f(*args, **kwargs)

        provided_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("Authorization", "").replace("Bearer ", "")
            or request.args.get("api_key")
        )

        if not provided_key or provided_key != configured_key:
            return (
                jsonify({
                    "success": False,
                    "error": "Unauthorized: Invalid or missing API Key",
                    "hint": "Provide header 'X-API-Key: <key>' or 'Authorization: Bearer <key>'",
                }),
                401,
            )
        return f(*args, **kwargs)
    return decorated


def is_ssrf_target(host):
    """Detect cloud metadata and prohibited SSRF targets."""
    prohibited = {"169.254.169.254", "metadata.google.internal", "instance-data"}
    return host in prohibited


# ============================================================================
# SYSTEM & HEALTH ENDPOINTS
# ============================================================================


@api.route("/", methods=["GET"])
def admin_dashboard():
    """Serve the Producer admin dashboard."""
    return render_template("producer.html")


@api.route("/health", methods=["GET"])
def health_check():
    """Liveness probe for Docker / Kubernetes / Load Balancers."""
    db_ok = True
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as e:
        logger.error("Health check DB probe failed: %s", e)
        db_ok = False

    return (
        jsonify({
            "status": "healthy" if db_ok else "unhealthy",
            "database": "connected" if db_ok else "disconnected",
            "timestamp": datetime.utcnow().isoformat(),
        }),
        200 if db_ok else 503,
    )


@api.route("/events")
def sse_stream():
    """Server-Sent Events (SSE) stream for real-time dashboard updates."""
    client_queue = queue.Queue()
    with sse_clients_lock:
        sse_clients.append(client_queue)

    def event_stream():
        try:
            while True:
                try:
                    data = client_queue.get(timeout=30)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    # Keep-alive comment for long-lived connection stability
                    yield ": keep-alive\n\n"
        finally:
            with sse_clients_lock:
                if client_queue in sse_clients:
                    sse_clients.remove(client_queue)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@api.route("/api", methods=["GET"])
def api_info():
    """Discovery endpoint: returns system status and routes."""
    return (
        jsonify({
            "message": "Notification Delivery API — Producer",
            "version": "4.1.0 (Production Hardened)",
            "architecture": "Distributed Producer-Consumer with persistent storage",
            "device_types": VALID_DEVICE_TYPES,
            "persistence": "PostgreSQL / SQLite WAL",
            "worker_pool": WORKER_POOL_SIZE,
            "auth_enabled": bool(os.getenv("API_KEY")),
            "network_ip": get_network_ip(),
            "endpoints": {
                "GET  /health": "System health probe",
                "GET  /api": "API route documentation",
                "GET  /devices": "List all registered devices",
                "POST /devices/register": "Register a consumer device (requires API Key if configured)",
                "DELETE /devices/<device_id>": "Unregister a device (requires API Key if configured)",
                "POST /notifications/send": "Enqueue a notification job (requires API Key if configured)",
                "GET  /notifications/queue": "View currently active jobs in queue",
                "GET  /notifications/status/<job_id>": "Check job status",
                "GET  /notifications/history": "View historical notifications",
                "GET  /vapid/public-key": "Get VAPID public key for Web Push",
            },
        }),
        200,
    )


@api.route("/vapid/public-key", methods=["GET"])
def get_vapid_key():
    """Return VAPID public key for client-side Web Push subscription."""
    return (
        jsonify({
            "success": True,
            "public_key": VAPID_PUBLIC_KEY,
            "configured": bool(VAPID_PUBLIC_KEY),
        }),
        200,
    )


# ============================================================================
# DEVICE MANAGEMENT CONTROLLERS
# ============================================================================


@api.route("/devices", methods=["GET"])
def list_devices():
    """List all registered devices from the database."""
    devices = Device.query.all()
    devices_list = [d.to_dict() for d in devices]

    return (
        jsonify({
            "success": True,
            "message": f"Found {len(devices_list)} registered device(s)",
            "count": len(devices_list),
            "devices": devices_list,
        }),
        200,
    )


@api.route("/devices/register", methods=["POST"])
def register_device():
    """
    Register a new consumer device or update existing subscription.
    """
    data = request.get_json()

    if not data:
        return (
            jsonify({
                "success": False,
                "error": "No JSON data provided",
                "hint": "Send a JSON body with 'name' field",
            }),
            400,
        )

    device_name = data.get("name", "").strip()
    if not device_name:
        return (
            jsonify({
                "success": False,
                "error": "Missing required field: 'name'",
                "hint": "The 'name' field is required and cannot be empty",
            }),
            400,
        )

    device_type = data.get("device_type", "web").strip().lower()
    if device_type not in VALID_DEVICE_TYPES:
        return (
            jsonify({
                "success": False,
                "error": f"Invalid device_type: '{device_type}'",
                "hint": f"Must be one of: {VALID_DEVICE_TYPES}",
            }),
            400,
        )

    ip_address = data.get("ip_address", "127.0.0.1").strip()
    try:
        port = int(data.get("port", 5001))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid port number"}), 400

    email = data.get("email", "").strip()

    # SSRF Protection
    if is_ssrf_target(ip_address):
        return (
            jsonify({
                "success": False,
                "error": "Registration rejected: Disallowed destination host",
            }),
            400,
        )

    # Resolve hostname to IP if it's not already an IP
    try:
        ip_address = socket.gethostbyname(ip_address)
    except Exception:
        pass

    local_ips = {"127.0.0.1"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # Duplicate device check
    if ip_address == "127.0.0.1":
        existing_device = Device.query.filter_by(port=port).first()
    elif ip_address in local_ips:
        existing_device = Device.query.filter(
            Device.port == port,
            Device.ip_address.in_(local_ips)
        ).first()
    else:
        existing_device = Device.query.filter_by(ip_address=ip_address, port=port).first()

    subscription_data = data.get("subscription_data")
    if isinstance(subscription_data, dict):
        subscription_data = json.dumps(subscription_data)

    # If already registered and updating subscription
    if existing_device:
        if subscription_data and not existing_device.subscription_data:
            existing_device.subscription_data = subscription_data
            try:
                db.session.commit()
                broadcast_sse({"type": "device_change"})
                return (
                    jsonify({
                        "success": True,
                        "message": "Device subscription updated",
                        "device": existing_device.to_dict(),
                    }),
                    200,
                )
            except Exception as e:
                db.session.rollback()
                logger.error("DB error updating device: %s", e)

        return (
            jsonify({
                "success": False,
                "error": f"Address already in use — {ip_address}:{port} is already registered as '{existing_device.name}'",
                "device": existing_device.to_dict(),
                "hint": "Remove the existing device first if you want to re-register this address with a different name.",
            }),
            409,
        )

    device = Device(
        name=device_name,
        device_type=device_type,
        ip_address=ip_address,
        port=port,
        email=email,
        subscription_data=subscription_data,
    )

    try:
        db.session.add(device)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Failed to register device: %s", e)
        return jsonify({"success": False, "error": "Database error while registering device"}), 500

    broadcast_sse({"type": "device_change"})
    logger.info("Registered new device: '%s' (%s at %s:%s)", device_name, device_type, ip_address, port)

    return (
        jsonify({
            "success": True,
            "message": "Device registered successfully",
            "device": device.to_dict(),
        }),
        201,
    )


@api.route("/devices/<device_id>", methods=["DELETE"])
def unregister_device(device_id):
    """Remove a device from the database by its ID."""
    device = db.session.get(Device, device_id)

    if not device:
        return (
            jsonify({
                "success": False,
                "error": "Device not found",
                "device_id": device_id,
                "hint": "Check the device_id or use GET /devices to see all registered devices",
            }),
            404,
        )

    device_name = device.name
    try:
        db.session.delete(device)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Failed to delete device %s: %s", device_id, e)
        return jsonify({"success": False, "error": "Database error deleting device"}), 500

    broadcast_sse({"type": "device_change"})
    logger.info("Unregistered device: '%s' (%s)", device_name, device_id)

    return (
        jsonify({
            "success": True,
            "message": "Device unregistered successfully",
            "device_id": device_id,
            "device_name": device_name,
        }),
        200,
    )


# ============================================================================
# NOTIFICATION DISPATCH & QUERY CONTROLLERS
# ============================================================================


@api.route("/notifications/send", methods=["POST"])
@require_api_key
def send_notification():
    """
    Accept notification payload and enqueue for background worker pool delivery.
    Responds immediately with 202 Accepted.
    """
    data = request.get_json()

    if not data:
        return (
            jsonify({
                "success": False,
                "error": "No JSON data provided",
                "hint": "Send a JSON body with 'title' and 'message' fields",
            }),
            400,
        )

    title = data.get("title", "").strip()
    message = data.get("message", "").strip()
    device_ids = data.get("device_ids", [])
    if not device_ids and data.get("device_id"):
        device_ids = [data.get("device_id")]

    if not title:
        return (
            jsonify({"success": False, "error": "Missing required field: 'title'"}),
            400,
        )

    if not message:
        return (
            jsonify({"success": False, "error": "Missing required field: 'message'"}),
            400,
        )

    # Sanitize length
    if len(title) > 255:
        return jsonify({"success": False, "error": "Title exceeds maximum length of 255 characters"}), 400
    if len(message) > 10000:
        return jsonify({"success": False, "error": "Message exceeds maximum length of 10,000 characters"}), 400

    # Fetch target devices
    if device_ids:
        target_devices = Device.query.filter(Device.id.in_(device_ids)).all()
        not_found = [did for did in device_ids if did not in [d.id for d in target_devices]]

        if not target_devices:
            return (
                jsonify({
                    "success": False,
                    "error": "None of the specified devices were found",
                    "not_found": not_found,
                }),
                404,
            )
    else:
        target_devices = Device.query.all()

    if not target_devices:
        return (
            jsonify({
                "success": False,
                "error": "No devices registered",
                "hint": "Register at least one device before sending notifications",
            }),
            404,
        )

    job_id = str(uuid.uuid4())
    notif = Notification(
        id=job_id,
        title=title,
        message=message,
        total_devices=len(target_devices),
        status="queued",
    )

    try:
        db.session.add(notif)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("DB error creating notification record: %s", e)
        return jsonify({"success": False, "error": "Database error persisting notification"}), 500

    device_dicts = [
        {
            "id": d.id,
            "name": d.name,
            "device_type": d.device_type,
            "ip_address": d.ip_address,
            "port": d.port,
            "subscription_data": d.subscription_data,
        }
        for d in target_devices
    ]

    job = {
        "job_id": job_id,
        "title": title,
        "message": message,
        "target_devices": device_dicts,
        "enqueued_at": datetime.now().isoformat(),
        "retry_count": 0,
    }

    # Record in thread-safe fast tracker
    update_job_tracker(job_id, {
        "status": "queued",
        "enqueued_at": job["enqueued_at"],
        "total_devices": len(device_dicts),
        "title": title,
    })

    # Push to durable queue
    notification_queue.put(job)

    # Broadcast to admin dashboard
    broadcast_sse({
        "type": "job_queued",
        "job_id": job_id,
        "title": title,
        "total_devices": len(device_dicts)
    })

    target_addresses = [f"http://{d['ip_address']}:{d['port']}" for d in device_dicts]
    logger.info("Enqueued job %s: '%s' to %d target(s)", job_id, title, len(device_dicts))

    return (
        jsonify({
            "success": True,
            "message": "Notification job enqueued",
            "job_id": job_id,
            "status": "queued",
            "total_devices": len(device_dicts),
            "target_addresses": target_addresses,
            "hint": f"Track status at GET /notifications/status/{job_id}",
        }),
        202,
    )


@api.route("/notifications/status/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """Return status of a specific notification job (fast memory lookup with DB fallback)."""
    tracked = get_job_tracker(job_id)
    if tracked:
        return (
            jsonify({
                "success": True,
                "job_id": job_id,
                "status": tracked.get("status"),
                "enqueued_at": tracked.get("enqueued_at"),
                "processed_at": tracked.get("processed_at"),
                "total_devices": tracked.get("total_devices"),
                "successful": tracked.get("successful"),
                "failed": tracked.get("failed"),
                "results": tracked.get("results"),
            }),
            200,
        )

    notif = db.session.get(Notification, job_id)
    if not notif:
        return (
            jsonify({
                "success": False,
                "error": "Job not found",
                "hint": "Check the job_id returned from POST /notifications/send",
            }),
            404,
        )

    return (
        jsonify({
            "success": True,
            "job_id": job_id,
            "status": notif.status,
            "enqueued_at": notif.enqueued_at.isoformat() if notif.enqueued_at else None,
            "processed_at": notif.processed_at.isoformat() if notif.processed_at else None,
            "total_devices": notif.total_devices,
            "successful": notif.successful,
            "failed": notif.failed,
            "retry_count": notif.retry_count,
            "results": json.loads(notif.details) if notif.details else [],
        }),
        200,
    )


@api.route("/notifications/queue", methods=["GET"])
def get_queued_jobs():
    """Return all jobs that are currently 'queued' or 'processing' (thread-safe)."""
    active_jobs = get_active_queued_jobs()
    active_jobs.sort(key=lambda x: x["enqueued_at"] if x["enqueued_at"] else "")

    return (
        jsonify({
            "success": True,
            "count": len(active_jobs),
            "queue": active_jobs,
        }),
        200,
    )


@api.route("/notifications/history", methods=["GET"])
def get_notification_history():
    """Return the last 50 sent notification records."""
    notifications = (
        Notification.query.order_by(Notification.enqueued_at.desc())
        .limit(50)
        .all()
    )

    history = [n.to_dict() for n in notifications]

    return (
        jsonify({
            "success": True,
            "message": f"Found {len(history)} notification(s) in history",
            "count": len(history),
            "notifications": history,
        }),
        200,
    )
