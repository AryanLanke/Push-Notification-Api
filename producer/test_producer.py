import pytest
import json
import os
import time
from producer import create_app
from database import db, Device, Notification
from logic import notification_queue, process_job

_test_app = None

@pytest.fixture
def client():
    global _test_app
    app = create_app(testing=True)
    _test_app = app

    with app.test_client() as client:
        with app.app_context():
            db.create_all()

        yield client

        with app.app_context():
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


def test_health_check(client):
    """Test the health check endpoint for monitoring/orchestrators"""
    response = client.get("/health")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


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
    response = client.post(
        "/devices/register",
        data=json.dumps({"device_type": "web"}),
        content_type="application/json",
    )
    assert response.status_code == 400

    response = client.post(
        "/devices/register",
        data=json.dumps({"name": "Test", "device_type": "smartwatch"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_ssrf_rejection(client):
    """Test that registration rejects cloud metadata IPs"""
    payload = {
        "name": "Cloud Metadata",
        "device_type": "web",
        "ip_address": "169.254.169.254",
        "port": 80,
    }
    response = client.post(
        "/devices/register",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert "Disallowed" in data["error"]


def test_send_notification(client):
    """Test enqueuing a notification"""
    client.post(
        "/devices/register",
        data=json.dumps({"name": "Test Device"}),
        content_type="application/json",
    )

    payload = {"title": "Welcome", "message": "Hello from tests"}
    response = client.post(
        "/notifications/send",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 202
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
    response = client.post(
        "/devices/register",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 201

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
    """Test that sending to an offline device records failure"""
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

    response = client.post(
        "/notifications/send",
        data=json.dumps({"title": "Test Offline", "message": "Should fail"}),
        content_type="application/json",
    )
    assert response.status_code == 202
    data = json.loads(response.data)
    job_id = data["job_id"]

    job = notification_queue.get()
    process_job(job, _test_app)
    notification_queue.task_done()

    response = client.get(f"/notifications/status/{job_id}")
    status_data = json.loads(response.data)

    assert status_data["status"] == "completed"
    assert status_data["failed"] >= 1
    assert status_data["successful"] == 0


def test_notification_history_has_details(client):
    """Test that notification history endpoint returns per-device delivery details"""
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

    client.post(
        "/notifications/send",
        data=json.dumps({"title": "Detail Test", "message": "Check details"}),
        content_type="application/json",
    )

    job = notification_queue.get()
    process_job(job, _test_app)
    notification_queue.task_done()

    response = client.get("/notifications/history")
    data = json.loads(response.data)

    assert data["success"] is True
    assert len(data["notifications"]) >= 1

    latest = data["notifications"][0]
    assert "details" in latest
    assert len(latest["details"]) >= 1
    assert "device_name" in latest["details"][0]
    assert "status" in latest["details"][0]
    assert "message" in latest["details"][0]


def test_send_missing_fields(client):
    """Test that sending notification without title or message returns 400"""
    client.post(
        "/devices/register",
        data=json.dumps({"name": "Field-Test"}),
        content_type="application/json",
    )

    response = client.post(
        "/notifications/send",
        data=json.dumps({"message": "No title here"}),
        content_type="application/json",
    )
    assert response.status_code == 400

    response = client.post(
        "/notifications/send",
        data=json.dumps({"title": "No message here"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_topics_endpoint(client):
    """Test registering devices with topics and listing distinct topics"""
    client.post(
        "/devices/register",
        data=json.dumps({"name": "Ops-Device", "port": 5081, "topic": "devops"}),
        content_type="application/json",
    )
    client.post(
        "/devices/register",
        data=json.dumps({"name": "Alerts-Device", "port": 5082, "topic": "alerts"}),
        content_type="application/json",
    )

    response = client.get("/topics")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True
    assert "devops" in data["topics"]
    assert "alerts" in data["topics"]


def test_send_by_topic(client):
    """Test targeting notification dispatch by topic channel"""
    client.post(
        "/devices/register",
        data=json.dumps({"name": "Billing-Server", "port": 5083, "topic": "billing"}),
        content_type="application/json",
    )

    response = client.post(
        "/notifications/send",
        data=json.dumps({
            "title": "Invoice Generated",
            "message": "Monthly invoice #402 ready",
            "topic": "billing"
        }),
        content_type="application/json",
    )
    assert response.status_code == 202
    data = json.loads(response.data)
    assert data["success"] is True
    assert data["total_devices"] == 1


def test_delivery_receipt_ack(client):
    """Test webhook delivery receipt ACK endpoint"""
    reg = client.post(
        "/devices/register",
        data=json.dumps({"name": "Ack-Device", "port": 5084, "topic": "general"}),
        content_type="application/json",
    )
    dev_id = json.loads(reg.data)["device"]["device_id"]

    # Send notification to generate job
    send_res = client.post(
        "/notifications/send",
        data=json.dumps({"title": "Receipt Test", "message": "Verify ACK"}),
        content_type="application/json",
    )
    job_id = json.loads(send_res.data)["job_id"]

    # Send delivery receipt ACK
    ack_res = client.post(
        "/notifications/ack",
        data=json.dumps({
            "job_id": job_id,
            "device_id": dev_id,
            "device_name": "Ack-Device"
        }),
        content_type="application/json",
    )
    assert ack_res.status_code == 200
    ack_data = json.loads(ack_res.data)
    assert ack_data["success"] is True


def test_rate_limiting_exceeded(client):
    """Test that requests exceeding the configured rate limit return 429 Too Many Requests"""
    # Enable rate limiting testing flag for this app context
    client.application.config["ENABLE_RATE_LIMIT_TESTING"] = True
    try:
        # Register test device first
        client.post(
            "/devices/register",
            data=json.dumps({"name": "Rate-Device", "port": 5090}),
            content_type="application/json",
        )

        from endpoints import _rate_limit_records, _rate_limit_lock
        with _rate_limit_lock:
            # Simulate 60 recent requests from the test client IP
            _rate_limit_records["127.0.0.1"] = [time.time()] * 60

        response = client.post(
            "/notifications/send",
            data=json.dumps({"title": "Spam", "message": "Flood"}),
            content_type="application/json",
        )
        assert response.status_code == 429
        data = json.loads(response.data)
        assert data["success"] is False
        assert "Too Many Requests" in data["error"]
        assert "Retry-After" in response.headers
    finally:
        client.application.config["ENABLE_RATE_LIMIT_TESTING"] = False
        with _rate_limit_lock:
            _rate_limit_records.clear()


