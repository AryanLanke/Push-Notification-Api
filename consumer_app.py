"""
Consumer Device — Notification Receiver

A separate Flask application that acts as a "Consumer Device."
Runs on its own port (default: 5001) and receives notifications
from the Generator/Producer API (Port 5000).

On startup, it auto-registers itself with the Generator API.

Usage:
    python consumer_app.py                  # Runs on port 5001
    python consumer_app.py --port 5002      # Runs on port 5002
    python consumer_app.py --name "Device2" # Custom device name
"""

from flask import Flask, request, jsonify, render_template_string
import requests
import argparse
import os
from datetime import datetime

app = Flask(__name__)

# Store received notifications in memory
received_notifications = []

# ============================================================================
# CONSUMER HTML TEMPLATE
# ============================================================================

CONSUMER_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Consumer Device — {{ device_name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0a0a1a; color: #e0e0e0;
            min-height: 100vh; padding: 30px;
        }
        .header {
            background: linear-gradient(135deg, #1a1a3e, #2d1b69);
            border-radius: 16px; padding: 30px; margin-bottom: 30px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .header h1 {
            font-size: 1.8rem; margin-bottom: 8px;
            background: linear-gradient(90deg, #00d2ff, #7b2ff7);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .header p { color: #888; font-size: 0.95rem; }
        .status {
            display: inline-block; padding: 4px 12px; border-radius: 20px;
            font-size: 0.8rem; font-weight: 600; margin-top: 10px;
        }
        .status.online { background: #0d3b0d; color: #4caf50; border: 1px solid #4caf50; }

        /* Permission banner */
        #permBanner {
            background: rgba(123,47,247,0.12); border: 1px solid rgba(123,47,247,0.35);
            border-radius: 12px; padding: 14px 20px; margin-bottom: 24px;
            display: flex; align-items: center; justify-content: space-between; gap: 12px;
        }
        #permBanner p { font-size: 0.85rem; color: #c4b5fd; }
        #permBtn {
            background: #7b2ff7; border: none; color: #fff; padding: 8px 16px;
            border-radius: 8px; cursor: pointer; font-size: 0.82rem;
            font-family: inherit; font-weight: 600; white-space: nowrap;
        }
        #permBtn:hover { opacity: 0.85; }

        .info-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px; margin-bottom: 30px;
        }
        .info-card {
            background: #1a1a2e; border-radius: 12px; padding: 20px;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .info-card label { color: #666; font-size: 0.8rem; text-transform: uppercase; }
        .info-card .value { font-size: 1.2rem; font-weight: 600; margin-top: 5px; color: #fff; }

        .notifications-list { list-style: none; }
        .notification-item {
            background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 12px;
            border-left: 4px solid #7b2ff7;
            animation: slideIn 0.3s ease-out;
        }
        .notification-item h3 { color: #7b2ff7; margin-bottom: 6px; }
        .notification-item p { color: #ccc; }
        .notification-item .time { color: #555; font-size: 0.8rem; margin-top: 8px; }
        .notification-item.new-item { border-left-color: #00d2ff; }

        .empty { text-align: center; padding: 60px; color: #444; }
        .empty .icon { font-size: 3rem; margin-bottom: 15px; }

        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-20px); }
            to   { opacity: 1; transform: translateX(0); }
        }

        .refresh-btn {
            background: linear-gradient(135deg, #7b2ff7, #00d2ff);
            border: none; color: #fff; padding: 10px 24px; border-radius: 8px;
            cursor: pointer; font-size: 0.9rem; margin-bottom: 20px;
        }
        .refresh-btn:hover { opacity: 0.85; }

        .live-badge {
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 0.75rem; color: #4caf50; margin-bottom: 20px; margin-left: 12px;
        }
        .live-dot {
            width: 7px; height: 7px; border-radius: 50%; background: #4caf50;
            animation: pulse 2s infinite;
        }
        @keyframes pulse { 0%,100%{opacity:1}50%{opacity:.3} }
    </style>
</head>
<body>
    <div class="header">
        <h1>📡 Consumer Device: {{ device_name }}</h1>
        <p>Receiving notifications from Generator API at http://localhost:{{ producer_port }}</p>
        <span class="status online">● ONLINE — Port {{ port }}</span>
    </div>

    <!-- Browser notification permission banner (hidden if already granted) -->
    <div id="permBanner" style="display:none;">
        <p>🔔 Allow browser notifications to get real OS-level system popups when a notification arrives!</p>
        <button id="permBtn" onclick="requestPermission()">Allow Notifications</button>
    </div>

    <div class="info-grid">
        <div class="info-card">
            <label>Device ID</label>
            <div class="value">{{ device_id[:12] }}...</div>
        </div>
        <div class="info-card">
            <label>Address</label>
            <div class="value">localhost:{{ port }}</div>
        </div>
        <div class="info-card">
            <label>Notifications Received</label>
            <div class="value" id="count">{{ count }}</div>
        </div>
        <div class="info-card">
            <label>Device Type</label>
            <div class="value">Web</div>
        </div>
    </div>

    <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>
    <span class="live-badge"><div class="live-dot"></div> Live — updates every 2s</span>

    <h2 style="margin-bottom: 15px;">📬 Received Notifications</h2>

    <ul class="notifications-list" id="notifList">
        {% if notifications %}
            {% for n in notifications|reverse %}
            <li class="notification-item">
                <h3>{{ n.title }}</h3>
                <p>{{ n.message }}</p>
                <div class="time">Received at: {{ n.received_at }}</div>
            </li>
            {% endfor %}
        {% else %}
        <div class="empty" id="emptyState">
            <div class="icon">📭</div>
            <p>No notifications received yet.</p>
            <p style="margin-top: 8px; font-size: 0.85rem;">Use the Generator API at Port {{ producer_port }} to send one!</p>
        </div>
        {% endif %}
    </ul>

<script>
    let seenCount = {{ count }};

    // Check permission on page load
    window.addEventListener('load', () => {
        if ('Notification' in window && Notification.permission === 'default') {
            document.getElementById('permBanner').style.display = 'flex';
        }
        // Start live polling
        poll();
        setInterval(poll, 2000);
    });

    // Request OS notification permission
    async function requestPermission() {
        const perm = await Notification.requestPermission();
        if (perm === 'granted') {
            document.getElementById('permBanner').style.display = 'none';
            new Notification('✅ Notifications Enabled!', {
                body: 'You will now receive real system popups from the Generator.'
            });
        }
    }

    // Fire a real OS-level browser system notification
    function showSystemNotification(title, body) {
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('🔔 ' + title, { body: body });
        }
    }

    // Add a new notification card to the top of the list
    function prependCard(n) {
        const empty = document.getElementById('emptyState');
        if (empty) empty.remove();

        const li = document.createElement('li');
        li.className = 'notification-item new-item';
        li.innerHTML = `<h3>${esc(n.title)}</h3><p>${esc(n.message)}</p><div class="time">Received at: ${esc(n.received_at)}</div>`;
        const list = document.getElementById('notifList');
        list.insertBefore(li, list.firstChild);
        setTimeout(() => li.classList.remove('new-item'), 3000);
    }

    function esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // Poll /poll for new notifications every 2s
    async function poll() {
        try {
            const res = await fetch('/poll?since=' + seenCount);
            if (!res.ok) return;
            const data = await res.json();
            if (data.new_notifications && data.new_notifications.length > 0) {
                data.new_notifications.forEach(n => {
                    prependCard(n);
                    showSystemNotification(n.title, n.message);
                });
                seenCount = data.total;
                document.getElementById('count').textContent = seenCount;
            }
        } catch(e) { /* server may be restarting */ }
    }
</script>
</body>
</html>
"""


# ============================================================================
# CONSUMER ENDPOINTS
# ============================================================================

@app.route("/", methods=["GET"])
def home():
    """Display the consumer dashboard showing received notifications."""
    return render_template_string(
        CONSUMER_PAGE,
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
    Endpoint called by the Generator/Producer to deliver a notification.
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
    Returns only NEW notifications since the last known count (index).
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
# REGISTER WITH GENERATOR ON STARTUP
# ============================================================================

def register_with_generator(name, port, producer_port):
    """Auto-register this consumer device with the Generator/Producer API."""
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
            print(f"✓ Registered with Generator at Port {producer_port}")
            print(f"  Device ID: {device_id}")
            print(f"  Address:   http://127.0.0.1:{port}")
            return device_id
        else:
            print(f"⚠ Registration failed: {response.text}")
            return None
    except requests.exceptions.ConnectionError:
        print(f"⚠ Could not reach Generator at Port {producer_port}")
        print(f"  Make sure app_pure.py is running first!")
        return None


# ============================================================================
# RUN THE CONSUMER
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consumer Device — Notification Receiver")
    parser.add_argument("--port", type=int, default=5001, help="Port for this consumer (default: 5001)")
    parser.add_argument("--name", type=str, default="Consumer-Device-1", help="Name of this device")
    parser.add_argument("--producer-port", type=int, default=5000, help="Generator/Producer port (default: 5000)")
    args = parser.parse_args()

    app.config["DEVICE_NAME"] = args.name
    app.config["PORT"] = args.port
    app.config["PRODUCER_PORT"] = args.producer_port

    print("=" * 60)
    print(f"CONSUMER DEVICE — {args.name}")
    print("=" * 60)
    print(f"  This device:  http://127.0.0.1:{args.port}")
    print(f"  Generator at: http://127.0.0.1:{args.producer_port}")
    print("")

    # Auto-register with the Generator API
    register_with_generator(args.name, args.port, args.producer_port)

    print("")
    print(f"  Dashboard: http://localhost:{args.port}")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    app.run(host="0.0.0.0", port=args.port, debug=False)
