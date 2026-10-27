"""
Consumer Device — Notification Receiver (Production Hardened)

A separate Flask application that acts as a Consumer Device.
Runs on its own port (default: 5001) and receives notifications
from the Producer API (Port 5000).

On startup, it auto-registers itself with the Producer API.
Uses per-client Server-Sent Events (SSE) queues to push notifications
to connected browser tabs without race conditions.
"""

from flask import Flask, request, jsonify, render_template, Response, send_from_directory
import requests
import argparse
import json
import threading
import queue
import socket
import logging
import os
from datetime import datetime

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Consumer")

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

app = Flask(__name__, static_folder="static")

# Store received notifications in memory
received_notifications = []
notifications_lock = threading.Lock()

# Multi-client SSE queue management (avoids Event.set/clear race conditions)
sse_clients = []
sse_clients_lock = threading.Lock()


# ============================================================================
# CONSUMER ENDPOINTS
# ============================================================================


@app.route("/", methods=["GET"])
def home():
    """Display the consumer dashboard showing received notifications."""
    with notifications_lock:
        notifs_copy = list(received_notifications)

    return render_template(
        "consumer.html",
        device_name=app.config.get("DEVICE_NAME", "Consumer-Device"),
        device_id=app.config.get("DEVICE_ID", "not-registered"),
        port=app.config.get("PORT", 5001),
        producer_host=app.config.get("PRODUCER_HOST", "127.0.0.1"),
        producer_port=app.config.get("PRODUCER_PORT", 5000),
        notifications=notifs_copy,
        count=len(notifs_copy),
    )


@app.route("/sw.js")
def service_worker():
    """Serve the push notification service worker from the root scope."""
    try:
        response = send_from_directory(app.static_folder, "sw.js")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Content-Type"] = "application/javascript"
        response.headers["Cache-Control"] = "no-cache"
        return response
    except Exception as e:
        logger.error(f"Error serving sw.js: {e}")
        return Response("// sw.js not found", mimetype="application/javascript", status=404)


@app.route("/receive", methods=["POST"])
def receive_notification():
    """
    Endpoint called by the Producer to deliver a notification.
    Saves message and immediately broadcasts to all active SSE browser connections.
    """
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "No data received"}), 400

    if not data.get("title") or not data.get("message"):
        return jsonify({
            "success": False,
            "error": "Missing required fields: 'title' and 'message'"
        }), 400

    notification = {
        "title": data.get("title", "No Title"),
        "message": data.get("message", "No Message"),
        "from": data.get("from", "Producer API"),
        "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    with notifications_lock:
        received_notifications.append(notification)
        total = len(received_notifications)

    # Fan out to all active SSE queues without blocking
    with sse_clients_lock:
        for client_q in sse_clients:
            try:
                client_q.put_nowait(notification)
            except Exception:
                pass

    logger.info(f"Notification received: '{notification['title']}' from {notification['from']}")

    return (
        jsonify({
            "success": True,
            "message": "Notification received and stored",
            "total_received": total,
        }),
        200,
    )


@app.route("/events")
def sse_stream():
    """
    Server-Sent Events (SSE) endpoint using individual queues per client connection.
    Guarantees every browser tab receives all notifications without dropouts.
    """
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
                    # Keep-alive heartbeat comment
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


@app.route("/status", methods=["GET"])
def status():
    """Health check endpoint for the consumer device."""
    with notifications_lock:
        count = len(received_notifications)

    return (
        jsonify({
            "success": True,
            "device_name": app.config.get("DEVICE_NAME", "Consumer-Device"),
            "device_id": app.config.get("DEVICE_ID", "not-registered"),
            "port": app.config.get("PORT", 5001),
            "notifications_received": count,
            "status": "online",
        }),
        200,
    )


@app.route("/subscribe", methods=["POST"])
def update_subscription():
    """
    Allow browser frontend to send its Web Push subscription to be forwarded
    to the Producer API.
    """
    data = request.get_json()
    if not data or "subscription" not in data:
        return jsonify({"success": False, "error": "Missing subscription data"}), 400

    subscription = data["subscription"]
    device_id = app.config.get("DEVICE_ID")

    producer_host = app.config.get("PRODUCER_HOST", "127.0.0.1")
    producer_port = app.config.get("PRODUCER_PORT", 5000)
    api_key = app.config.get("API_KEY", "")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        # Re-register or update device with real VAPID subscription
        producer_url = f"http://{producer_host}:{producer_port}/devices/register"
        payload = {
            "name": app.config.get("DEVICE_NAME", "Web Device"),
            "device_type": "web",
            "ip_address": app.config.get("REGISTER_HOST", "127.0.0.1"),
            "port": app.config.get("PORT", 5001),
            "subscription_data": subscription,
        }
        res = requests.post(producer_url, json=payload, headers=headers, timeout=5)
        if res.status_code in [200, 201]:
            resp_data = res.json()
            if "device" in resp_data and "device_id" in resp_data["device"]:
                app.config["DEVICE_ID"] = resp_data["device"]["device_id"]
            logger.info("Successfully updated Web Push subscription with Producer")
            return jsonify({"success": True, "message": "Subscription linked to Producer"}), 200
        else:
            return jsonify({"success": False, "error": res.text}), res.status_code
    except Exception as e:
        logger.error(f"Failed to forward subscription to Producer: {e}")
        return jsonify({"success": False, "error": str(e)}), 502


# ============================================================================
# REGISTER WITH PRODUCER ON STARTUP
# ============================================================================


def register_with_producer(name, port, producer_host, producer_port, host="127.0.0.1", api_key=""):
    """
    Auto-register this consumer device with the Producer API.
    Retries up to 5 times in case Producer container is initializing.
    """
    import time

    producer_url = f"http://{producer_host}:{producer_port}/devices/register"
    payload = {
        "name": name,
        "device_type": "web",
        "ip_address": host,
        "port": port,
        "email": "",
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(producer_url, json=payload, headers=headers, timeout=5)
            if response.status_code == 201:
                data = response.json()
                device_id = data["device"]["device_id"]
                app.config["DEVICE_ID"] = device_id
                logger.info(f"Registered with Producer at port {producer_port} (ID: {device_id})")
                return device_id
            elif response.status_code == 409:
                data = response.json()
                if "device" in data and "device_id" in data["device"]:
                    device_id = data["device"]["device_id"]
                    app.config["DEVICE_ID"] = device_id
                    logger.info(f"Linked to existing registration on Producer (ID: {device_id})")
                    return device_id
                logger.info(f"Already registered with Producer at port {producer_port}")
                return "already-registered"
            else:
                logger.warning(f"Registration response: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.ConnectionError:
            if attempt < max_retries:
                logger.info(f"Producer not ready yet... retrying in 3s (attempt {attempt}/{max_retries})")
                time.sleep(3)
            else:
                logger.error(f"Could not reach Producer at http://{producer_host}:{producer_port} after {max_retries} attempts")
                return None


# ============================================================================
# RUN THE CONSUMER
# ============================================================================

def create_consumer_app():
    """Application factory for consumer device"""
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Consumer Device — Notification Receiver"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", 5001)),
        help="Port for this consumer (default: 5001)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=os.getenv("DEVICE_NAME", "Consumer-Device-1"),
        help="Name of this device",
    )
    parser.add_argument(
        "--producer-host",
        type=str,
        default=os.getenv("PRODUCER_HOST", "127.0.0.1"),
        help="Producer host IP/address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--producer-port",
        type=int,
        default=int(os.getenv("PRODUCER_PORT", 5000)),
        help="Producer port (default: 5000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("HOST", "auto"),
        help="Host IP/address for this consumer (default: auto-detect)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.getenv("API_KEY", "dev-secret-key-change-in-prod"),
        help="API Key for Producer authentication",
    )
    parser.add_argument(
        "--no-register",
        action="store_true",
        default=False,
        help="Skip auto-registration",
    )
    args = parser.parse_args()

    app.config["DEVICE_NAME"] = args.name
    app.config["PORT"] = args.port
    app.config["PRODUCER_HOST"] = args.producer_host
    app.config["PRODUCER_PORT"] = args.producer_port
    app.config["API_KEY"] = args.api_key

    if args.host == "auto":
        register_host = get_network_ip()
    else:
        register_host = args.host
    app.config["REGISTER_HOST"] = register_host

    logger.info("=" * 60)
    logger.info(f"CONSUMER DEVICE — {args.name}")
    logger.info(f"  This device:  http://{register_host}:{args.port}")
    logger.info(f"  Producer at:  http://{args.producer_host}:{args.producer_port}")
    logger.info("=" * 60)

    if not args.no_register:
        register_with_producer(
            args.name,
            args.port,
            args.producer_host,
            args.producer_port,
            register_host,
            args.api_key
        )

    app.run(host="0.0.0.0", port=args.port, debug=False)
