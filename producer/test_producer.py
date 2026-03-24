import pytest
import json
from producer import create_app
from database import db, Device, Notification


@pytest.fixture
def client():
    # Use application factory to create a test instance
    app = create_app(testing=True)

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
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
