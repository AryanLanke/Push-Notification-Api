"""
Consumer Device — Notification Receiver

A separate Flask application that acts as a Consumer Device.
Runs on its own port (default: 5001) and receives notifications
from the Producer API (Port 5000).

On startup, it auto-registers itself with the Producer API.
Uses Server-Sent Events (SSE) to push notifications to the
browser instantly instead of polling every 2 seconds.

Usage:
    python consumer.py                     # Runs on port 5001
    python consumer.py --port 5002         # Runs on port 5002
    python consumer.py --name "Device2"    # Custom device name
"""

from flask import Flask, request, jsonify, render_template, Response
import requests
import argparse
import json
import threading
from datetime import datetime

app = Flask(__name__)

# Store received notifications in memory (just a simple Python list)
received_notifications = []

# SSE: threading.Event is like a "Bell" in a restaurant kitchen.
# When a new notification arrives, we "ring the bell" (`sse_event.set()`).
# This wakes up the browser's connection so it can fetch the new data instantly.
sse_event = threading.Event()


# ============================================================================
# CONSUMER ENDPOINTS
# ============================================================================


@app.route("/", methods=["GET"])
def home():
    """Display the consumer dashboard showing received notifications."""
    return render_template(
        "consumer.html",
        device_name=app.config["DEVICE_NAME"],
        device_id=app.config.get("DEVICE_ID", "not-registered"),
        port=app.config["PORT"],
        producer_port=app.config["PRODUCER_PORT"],
        notifications=received_notifications,
        count=len(received_notifications),
    )


@app.route("/receive", methods=["POST"])
def receive_notification():
    """
    Endpoint called by the Producer to deliver a notification.
    1. It saves the message to our list.
    2. It "rings the bell" to tell the browser "Hey, new data is here!"
    (This is much faster than polling the server every 5 seconds).
    """
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "No data received"}), 400

    # Reject payloads missing required fields
    if not data.get("title") or not data.get("message"):
        return jsonify({"success": False, "error": "Missing required fields: 'title' and 'message'"}), 400

    notification = {
        "title": data.get("title", "No Title"),
        "message": data.get("message", "No Message"),
        "from": data.get("from", "Unknown"),
        "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    received_notifications.append(notification)

    # Wake up all SSE listener threads so the browser gets the update instantly
    # .set() rings the bell. .clear() resets the bell for the next time.
    sse_event.set()
    sse_event.clear()

    print(f"\n{'='*50}")
    print("📬 NOTIFICATION RECEIVED!")
    print(f"   Title:   {notification['title']}")
    print(f"   Message: {notification['message']}")
    print(f"   From:    {notification['from']}")
    print(f"   Time:    {notification['received_at']}")
    print(f"{'='*50}\n")

    return (
        jsonify(
            {
                "success": True,
                "message": "Notification received and stored",
                "total_received": len(received_notifications),
            }
        ),
        200,
    )


@app.route("/events")
def sse_stream():
    """
    Server-Sent Events (SSE) endpoint.
    Instead of the browser constantly asking "Are there new messages?",
    the browser opens ONE connection here and leaves it open.
    When a message arrives at /receive, this function pushes it to the browser.
    """

    def event_stream():
        last_seen = len(received_notifications)
        while True:
            # Block until /receive signals a new notification (or timeout for keep-alive)
            sse_event.wait(timeout=30)
            current_count = len(received_notifications)

            if current_count > last_seen:
                new_items = received_notifications[last_seen:]
                for item in new_items:
                    yield f"data: {json.dumps(item)}\n\n"
                last_seen = current_count
            else:
                # Send a keep-alive comment so the connection doesn't drop
                yield ": keep-alive\n\n"

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
    return (
        jsonify(
            {
                "success": True,
                "device_name": app.config["DEVICE_NAME"],
                "device_id": app.config.get("DEVICE_ID", "not-registered"),
                "port": app.config["PORT"],
                "notifications_received": len(received_notifications),
                "status": "online",
            }
        ),
        200,
    )


# ============================================================================
# REGISTER WITH PRODUCER ON STARTUP
# ============================================================================


def register_with_producer(name, port, producer_host, producer_port):
    """
    Auto-register this consumer device with the Producer API.
    When you start this script, it automatically sends a POST request
    to the Producer saying "Hi, I'm here, here is my IP and Port!"
    """
    producer_url = f"http://{producer_host}:{producer_port}/devices/register"
    payload = {
        "name": name,
        "device_type": "web",
        "ip_address": "127.0.0.1",
        "port": port,
        "email": "",
    }
    try:
        response = requests.post(producer_url, json=payload, timeout=5)
        if response.status_code == 201:
            data = response.json()
            device_id = data["device"]["device_id"]
            app.config["DEVICE_ID"] = device_id
            print(f"✓ Registered with Producer at Port {producer_port}")
            print(f"  Device ID: {device_id}")
            print(f"  Address:   http://127.0.0.1:{port}")
            return device_id
        elif response.status_code == 409:
            data = response.json()
            if "device" in data and "device_id" in data["device"]:
                device_id = data["device"]["device_id"]
                app.config["DEVICE_ID"] = device_id
                print(f"✓ Already registered with Producer at Port {producer_port}. Linked to existing ID: {device_id}")
                return device_id
            print(f"✓ Already registered with Producer at Port {producer_port} (No ID returned)")
            return "already-registered"
        else:
            print(f"⚠ Registration failed: {response.text}")
            return None
    except requests.exceptions.ConnectionError:
        print(f"⚠ Could not reach Producer at http://{producer_host}:{producer_port}")
        print("  Make sure producer.py is running first!")
        return None


# ============================================================================
# RUN THE CONSUMER
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Consumer Device — Notification Receiver"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="Port for this consumer (default: 5001)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="Consumer-Device-1",
        help="Name of this device",
    )
    parser.add_argument(
        "--producer-host",
        type=str,
        default="127.0.0.1",
        help="Producer host IP/address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--producer-port",
        type=int,
        default=5000,
        help="Producer port (default: 5000)",
    )
    args = parser.parse_args()

    app.config["DEVICE_NAME"] = args.name
    app.config["PORT"] = args.port
    app.config["PRODUCER_HOST"] = args.producer_host
    app.config["PRODUCER_PORT"] = args.producer_port

    print("=" * 60)
    print(f"CONSUMER DEVICE — {args.name}")
    print("=" * 60)
    print(f"  This device:  http://127.0.0.1:{args.port}")
    print(f"  Producer at:  http://{args.producer_host}:{args.producer_port}")
    print("")

    # Auto-register with the Producer API
    register_with_producer(args.name, args.port, args.producer_host, args.producer_port)

    print("")
    print(f"  Dashboard: http://localhost:{args.port}")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    app.run(host="0.0.0.0", port=args.port, debug=False)
