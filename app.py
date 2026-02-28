"""
Notification Delivery API

Flask REST API for push notification delivery.
Supports device registration, targeted/broadcast notifications,
and async delivery using threading.
"""

from flask import Flask, request, jsonify, render_template, send_from_directory
import threading
import time
import uuid
import os
from datetime import datetime

# ============================================================================
# FLASK APP INITIALIZATION
# ============================================================================
app = Flask(__name__, static_folder='static')

# CORS configuration
try:
    from flask_cors import CORS
    CORS(app, resources={
        r"/api/*": {"origins": "*"},
        r"/devices/*": {"origins": "*"},
        r"/notifications/*": {"origins": "*"}
    })
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
# IN-MEMORY STORAGE
# ============================================================================
# {device_id: {token, name, email, registered_at}}
registered_devices = {}

notification_history = []


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def simulate_send_to_device(device_id, device_info, message, results):
    """Send notification to a device. Replace with FCM/APNs in production."""
    try:
        time.sleep(0.2)  # Simulated network delay
        
        # Test failure simulation
        if "fail" in device_info.get("token", "").lower():
            raise Exception("Simulated delivery failure")
        
        print(f"[OK] Notification sent to device '{device_info.get('name', 'Unknown')}' "
              f"(ID: {device_id})")
        
        results.append({
            "device_id": device_id,
            "device_name": device_info.get("name", "Unknown"),
            "status": "success",
            "message": "Notification delivered successfully"
        })
        
    except Exception as e:
        print(f"[FAIL] Failed to send to device '{device_info.get('name', 'Unknown')}' "
              f"(ID: {device_id}): {str(e)}")
        
        results.append({
            "device_id": device_id,
            "device_name": device_info.get("name", "Unknown"),
            "status": "failed",
            "message": str(e)
        })


def send_notifications_async(message, title):
    """Send notifications to all devices using threads."""
    if not registered_devices:
        print("[WARNING] No devices registered. Notification not sent.")
        return []
    
    results = []
    threads = []
    
    print(f"\n[SENDING] Notification: '{title}' to {len(registered_devices)} device(s)...")
    
    for device_id, device_info in registered_devices.items():
        thread = threading.Thread(
            target=simulate_send_to_device,
            args=(device_id, device_info, message, results)
        )
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    notification_record = {
        "id": str(uuid.uuid4()),
        "title": title,
        "message": message,
        "sent_at": datetime.now().isoformat(),
        "total_devices": len(registered_devices),
        "successful": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "failed"]),
        "details": results
    }
    notification_history.append(notification_record)
    
    return results


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route("/", methods=["GET"])
def home():
    """
    Serve the frontend dashboard.
    """
    return render_template("index.html")


@app.route("/service-worker.js", methods=["GET"])
def service_worker():
    """Serve service worker from root path."""
    return send_from_directory(app.static_folder, "service-worker.js",
                               mimetype="application/javascript")


@app.route("/api", methods=["GET"])
def api_info():
    """Return API info and endpoints."""
    return jsonify({
        "message": "Welcome to the Notification Delivery API!",
        "version": "1.0.0",
        "endpoints": {
            "GET /": "Frontend dashboard",
            "GET /api": "This help message",
            "GET /devices": "List all registered devices",
            "POST /devices/register": "Register a new device",
            "DELETE /devices/<device_id>": "Unregister a device",
            "POST /notifications/send": "Send notification to all devices",
            "GET /notifications/history": "View notification history"
        },
        "documentation": "See README.md for detailed usage instructions"
    }), 200


@app.route("/devices", methods=["GET"])
def list_devices():
    """List all registered devices."""
    devices_list = [
        {
            "device_id": device_id,
            "name": info.get("name", "Unknown"),
            "email": info.get("email", ""),
            "token": info.get("token", "")[:10] + "..." if len(info.get("token", "")) > 10 else info.get("token", ""),
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
    Body: {name: required, email: optional}
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
    
    # Get optional email
    email = data.get("email", "").strip()
    
    # Generate unique device ID (also used as token)
    device_id = str(uuid.uuid4())
    
    # Store the device
    registered_devices[device_id] = {
        "token": device_id,  # Use device_id as token for simplicity
        "name": device_name,
        "email": email,
        "registered_at": datetime.now().isoformat()
    }
    
    print(f"[NEW DEVICE] Registered: '{device_name}' (ID: {device_id})")
    
    return jsonify({
        "success": True,
        "message": "Device registered successfully",
        "device_id": device_id,
        "device_name": device_name,
        "email": email,
        "registered_at": registered_devices[device_id]["registered_at"]
    }), 201


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


@app.route("/notifications/send", methods=["POST"])
def send_notification():
    """
    Send notification to all or specific devices.
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
            "error": "Missing required field: 'title'",
            "hint": "The 'title' field is required and cannot be empty"
        }), 400
    
    if not message:
        return jsonify({
            "success": False,
            "error": "Missing required field: 'message'",
            "hint": "The 'message' field is required and cannot be empty"
        }), 400
    
    if not registered_devices:
        return jsonify({
            "success": False,
            "error": "No devices registered",
            "hint": "Register at least one device before sending notifications"
        }), 404
    
    if device_ids and len(device_ids) > 0:
        target_devices = {}
        not_found = []
        
        for dev_id in device_ids:
            if dev_id in registered_devices:
                target_devices[dev_id] = registered_devices[dev_id]
            else:
                not_found.append(dev_id)
        
        if not target_devices:
            return jsonify({
                "success": False,
                "error": "None of the specified devices were found",
                "not_found": not_found,
                "hint": "Check the device_ids and try again"
            }), 404
        
        send_mode = "specific"
        target_device_names = [target_devices[d]["name"] for d in target_devices]
    else:
        # Send to all devices
        target_devices = registered_devices.copy()
        send_mode = "all"
        target_device_names = []
    
    # Send notifications using threading
    results = []
    threads = []
    
    print(f"\n[SENDING] Notification: '{title}' to {len(target_devices)} device(s)...")
    
    for device_id, device_info in target_devices.items():
        thread = threading.Thread(
            target=simulate_send_to_device,
            args=(device_id, device_info, message, results)
        )
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # Calculate statistics
    successful = len([r for r in results if r["status"] == "success"])
    failed = len([r for r in results if r["status"] == "failed"])
    
    # Store notification in history
    notification_record = {
        "id": str(uuid.uuid4()),
        "title": title,
        "message": message,
        "sent_at": datetime.now().isoformat(),
        "send_mode": send_mode,
        "target_device_ids": device_ids if device_ids else None,
        "target_device_names": target_device_names if target_device_names else None,
        "total_devices": len(target_devices),
        "successful": successful,
        "failed": failed,
        "details": results
    }
    notification_history.append(notification_record)
    
    return jsonify({
        "success": True,
        "message": f"Notification sent to {len(target_devices)} device(s)",
        "send_mode": send_mode,
        "notification": {
            "title": title,
            "message": message
        },
        "statistics": {
            "total_devices": len(target_devices),
            "successful": successful,
            "failed": failed
        },
        "delivery_results": results
    }), 200


@app.route("/notifications/history", methods=["GET"])
def get_notification_history():
    """Get notification history."""
    return jsonify({
        "success": True,
        "message": f"Found {len(notification_history)} notification(s) in history",
        "count": len(notification_history),
        "notifications": notification_history[-50:]  # Return last 50 notifications
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
        "hint": "Check the URL and HTTP method. Use GET / for available endpoints."
    }), 404


@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 errors."""
    return jsonify({
        "success": False,
        "error": "Method not allowed",
        "hint": "Check that you're using the correct HTTP method (GET, POST, DELETE)"
    }), 405


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({
        "success": False,
        "error": "Internal server error",
        "hint": "Something went wrong on the server. Please try again."
    }), 500


# ============================================================================
# RUN THE SERVER
# ============================================================================

def get_local_ip():
    """Get the local network IP address."""
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
        print("NOTIFICATION DELIVERY API")
        print("=" * 60)
        print("Server starting...")
        print("")
        print("Access URLs:")
        print(f"  Local:    http://localhost:5000")
        print(f"  Network:  http://{local_ip}:5000")
        print("")
        print("📱 To access from your phone:")
        print(f"   Open http://{local_ip}:5000 on your phone browser")
        print("   (Make sure phone is on same WiFi network)")
        print("")
        print("Press Ctrl+C to stop the server")
        print("=" * 60)
    
    app.run(host="0.0.0.0", port=5000, debug=True)
