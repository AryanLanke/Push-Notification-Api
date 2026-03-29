import pytest
import json
from producer import create_app
from database import db, Device, Notification
from logic import notification_queue, process_job

# We store the global app instance so our tests can grab its context
_test_app = None

@pytest.fixture
def client():
    global _test_app
    # Use application factory to create a test instance
    app = create_app(testing=True)
    _test_app = app

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        
        yield client
        
        with app.app_context():
            # Clear the queue so next test starts fresh
            while not notification_queue.empty():
                try:
                    notification_queue.get_nowait()
                    notification_queue.task_done()
                except:
                    break
            db.drop_all()


def test_api_info(client):
    """Test the discovery endpoint"""
    response = client.get("/api")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "Notification Delivery API" in data["message"]


def test_register_device(client):
    """Test device registration"""
    payload = {
        "name": "Test Web Browser",
        "device_type": "web",
        "ip_address": "127.0.0.1",
        "port": 5002,
    }
    response = client.post(
        "/devices/register",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 201
    data = json.loads(response.data)
    assert data["success"] is True
    assert data["device"]["name"] == "Test Web Browser"
    assert data["device"]["port"] == 5002


def test_device_validation(client):
    """Test registration with invalid data"""
    # Missing name
    response = client.post(
        "/devices/register",
        data=json.dumps({"device_type": "web"}),
        content_type="application/json",
    )
    assert response.status_code == 400

    # Invalid device type
    response = client.post(
        "/devices/register",
        data=json.dumps({"name": "Test", "device_type": "smartwatch"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_send_notification(client):
    """Test enqueuing a notification"""
    # First register a device
    client.post(
        "/devices/register",
        data=json.dumps({"name": "Test Device"}),
        content_type="application/json",
    )

    # Send a notification
    payload = {"title": "Welcome", "message": "Hello from tests"}
    response = client.post(
        "/notifications/send",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 202  # Accepted for processing
    data = json.loads(response.data)
    assert data["success"] is True
    assert "job_id" in data
    assert data["total_devices"] == 1


def test_send_no_devices(client):
    """Test sending when database is empty"""
    payload = {"title": "Welcome", "message": "Hello"}
    response = client.post(
        "/notifications/send",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 404
    data = json.loads(response.data)
    assert data["success"] is False
    assert "No devices registered" in data["error"]


def test_duplicate_registration(client):
    """Test that registering the same IP+Port twice returns 409"""
    payload = {
        "name": "Device A",
        "device_type": "web",
        "ip_address": "127.0.0.1",
        "port": 5002,
    }
    # First registration should succeed
    response = client.post(
        "/devices/register",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 201

    # Second registration with same IP+Port should fail
    response = client.post(
        "/devices/register",
        data=json.dumps({"name": "Device B", "ip_address": "127.0.0.1", "port": 5002}),
        content_type="application/json",
    )
    assert response.status_code == 409
    data = json.loads(response.data)
    assert data["success"] is False
    assert "already registered" in data["error"]


def test_send_to_offline_device(client):
    """
    Test that sending a notification to a device that is NOT running
    results in a 'failed' delivery for that device.
    This was flagged by the mentor: the system must detect inactive devices.
    """
    import time

    # Register a device on a port where nothing is running
    client.post(
        "/devices/register",
        data=json.dumps({
            "name": "Offline-Device",
            "device_type": "web",
            "ip_address": "127.0.0.1",
            "port": 9999,
        }),
        content_type="application/json",
    )

    # Send a notification to this offline device
    response = client.post(
        "/notifications/send",
        data=json.dumps({"title": "Test Offline", "message": "Should fail"}),
        content_type="application/json",
    )
    assert response.status_code == 202
    data = json.loads(response.data)
    job_id = data["job_id"]

    # Since we are not running background threads in testing, 
    # we manually grab the job and process it synchronously!
    job = notification_queue.get()
    process_job(job, _test_app)
    notification_queue.task_done()

    # Check job status — it should show 0 successful and 1 failed
    response = client.get(f"/notifications/status/{job_id}")
    status_data = json.loads(response.data)

    assert status_data["status"] == "completed"
    assert status_data["failed"] >= 1
    assert status_data["successful"] == 0

    # Verify the failure reason mentions the device is offline
    if status_data.get("results"):
        result = status_data["results"][0]
        assert result["status"] == "failed"
        assert result["device_name"] == "Offline-Device"
        assert "offline" in result["message"].lower() or "connection" in result["message"].lower()


def test_notification_history_has_details(client):
    """
    Test that the notification history endpoint returns per-device
    delivery details (device name, status, reason).
    Mentor asked: 'On which device it failed? Show me detailed info.'
    """
    import time

    # Register a device (offline, nothing running on port 9998)
    client.post(
        "/devices/register",
        data=json.dumps({
            "name": "Detail-Test-Device",
            "device_type": "web",
            "ip_address": "127.0.0.1",
            "port": 9998,
        }),
        content_type="application/json",
    )

    # Send notification
    client.post(
        "/notifications/send",
        data=json.dumps({"title": "Detail Test", "message": "Check details"}),
        content_type="application/json",
    )

    # Synchronously process the job that was just queued
    job = notification_queue.get()
    process_job(job, _test_app)
    notification_queue.task_done()

    # Fetch history
    response = client.get("/notifications/history")
    data = json.loads(response.data)

    assert data["success"] is True
    assert len(data["notifications"]) >= 1

    # The most recent notification should contain 'details' with per-device info
    latest = data["notifications"][0]
    assert "details" in latest
    assert len(latest["details"]) >= 1
    assert "device_name" in latest["details"][0]
    assert "status" in latest["details"][0]
    assert "message" in latest["details"][0]


def test_send_missing_fields(client):
    """Test that sending notification without title or message returns 400."""
    # Register a device first
    client.post(
        "/devices/register",
        data=json.dumps({"name": "Field-Test"}),
        content_type="application/json",
    )

    # Missing title
    response = client.post(
        "/notifications/send",
        data=json.dumps({"message": "No title here"}),
        content_type="application/json",
    )
    assert response.status_code == 400

    # Missing message
    response = client.post(
        "/notifications/send",
        data=json.dumps({"title": "No message here"}),
        content_type="application/json",
    )
    assert response.status_code == 400
