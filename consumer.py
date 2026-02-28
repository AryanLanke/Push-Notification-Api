"""
Consumer Device — Notification Receiver

A separate Flask application that acts as a Consumer Device.
Runs on its own port (default: 5001) and receives notifications
from the Producer API (Port 5000).

On startup, it auto-registers itself with the Producer API.

Usage:
    python consumer.py                     # Runs on port 5001
    python consumer.py --port 5002         # Runs on port 5002
    python consumer.py --name "Device2"    # Custom device name
"""

from flask import Flask, request, jsonify, render_template
import requests
import argparse
from datetime import datetime

app = Flask(__name__)

# Store received notifications in memory
received_notifications = []


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
        count=len(received_notifications)
    )


@app.route("/receive", methods=["POST"])
def receive_notification():
    """
    Endpoint called by the Producer to deliver a notification.
    Stores in memory. Browser page polls /poll to pick it up and show
    a real OS-level system notification popup.
    """
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "No data received"}), 400

    notification = {
        "title": data.get("title", "No Title"),
        "message": data.get("message", "No Message"),
        "from": data.get("from", "Unknown"),
        "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    received_notifications.append(notification)

    print(f"\n{'='*50}")
    print(f"📬 NOTIFICATION RECEIVED!")
    print(f"   Title:   {notification['title']}")
    print(f"   Message: {notification['message']}")
    print(f"   From:    {notification['from']}")
    print(f"   Time:    {notification['received_at']}")
    print(f"{'='*50}\n")

    return jsonify({
        "success": True,
        "message": "Notification received and stored",
        "total_received": len(received_notifications)
    }), 200


@app.route("/poll", methods=["GET"])
def poll():
    """
    Lightweight polling endpoint for the browser page.
    Returns only NEW notifications since the last known count.
    Called every 2 seconds by the browser — triggers system notification popup.
    """
    try:
        since = int(request.args.get("since", 0))
    except ValueError:
        since = 0

    new_notifications = received_notifications[since:]
    return jsonify({
        "total": len(received_notifications),
        "new_count": len(new_notifications),
        "new_notifications": new_notifications
    }), 200


@app.route("/status", methods=["GET"])
def status():
    """Health check endpoint for the consumer device."""
    return jsonify({
        "success": True,
        "device_name": app.config["DEVICE_NAME"],
        "device_id": app.config.get("DEVICE_ID", "not-registered"),
        "port": app.config["PORT"],
        "notifications_received": len(received_notifications),
        "status": "online"
    }), 200


# ============================================================================
# REGISTER WITH PRODUCER ON STARTUP
# ============================================================================

def register_with_producer(name, port, producer_port):
    """Auto-register this consumer device with the Producer API."""
    producer_url = f"http://127.0.0.1:{producer_port}/devices/register"
    payload = {
        "name": name,
        "device_type": "web",
        "ip_address": "127.0.0.1",
        "port": port,
        "email": ""
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
        else:
            print(f"⚠ Registration failed: {response.text}")
            return None
    except requests.exceptions.ConnectionError:
        print(f"⚠ Could not reach Producer at Port {producer_port}")
        print(f"  Make sure producer.py is running first!")
        return None


# ============================================================================
# RUN THE CONSUMER
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consumer Device — Notification Receiver")
    parser.add_argument("--port", type=int, default=5001, help="Port for this consumer (default: 5001)")
    parser.add_argument("--name", type=str, default="Consumer-Device-1", help="Name of this device")
    parser.add_argument("--producer-port", type=int, default=5000, help="Producer port (default: 5000)")
    args = parser.parse_args()

    app.config["DEVICE_NAME"] = args.name
    app.config["PORT"] = args.port
    app.config["PRODUCER_PORT"] = args.producer_port

    print("=" * 60)
    print(f"CONSUMER DEVICE — {args.name}")
    print("=" * 60)
    print(f"  This device:  http://127.0.0.1:{args.port}")
    print(f"  Producer at:  http://127.0.0.1:{args.producer_port}")
    print("")

    # Auto-register with the Producer API
    register_with_producer(args.name, args.port, args.producer_port)

    print("")
    print(f"  Dashboard: http://localhost:{args.port}")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    app.run(host="0.0.0.0", port=args.port, debug=False)
