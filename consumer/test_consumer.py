import pytest
import json
from consumer import app, received_notifications


@pytest.fixture
def client():
    # Configure app for testing
    app.config["TESTING"] = True
    app.config["DEVICE_NAME"] = "Test Consumer"
    app.config["DEVICE_ID"] = "test-1234"
    app.config["PORT"] = 5001
    app.config["PRODUCER_PORT"] = 5000

    # Clear memory between tests
    received_notifications.clear()

    with app.test_client() as client:
        yield client


def test_status_endpoint(client):
    """Test health check endpoint"""
    response = client.get("/status")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "online"
    assert data["device_name"] == "Test Consumer"
    assert data["notifications_received"] == 0


def test_receive_notification(client):
    """Test receiving a payload from the Producer"""
    payload = {
        "title": "Alert",
        "message": "Test notification message",
        "from": "Producer API",
    }

    response = client.post(
        "/receive", data=json.dumps(payload), content_type="application/json"
    )

    assert response.status_code == 200
    data = json.loads(response.data)

    assert data["success"] is True
    assert data["total_received"] == 1

    # Verify it was stored in memory
    assert len(received_notifications) == 1
    assert received_notifications[0]["title"] == "Alert"
    assert received_notifications[0]["message"] == "Test notification message"


def test_receive_empty_data(client):
    """Test receiving bad data"""
    response = client.post(
        "/receive", data=json.dumps({}), content_type="application/json"
    )

    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["success"] is False
    assert "error" in data
