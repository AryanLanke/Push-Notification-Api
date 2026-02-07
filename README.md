# 🔔 Notification Delivery API

A beginner-friendly REST API built with Flask for delivering notifications to registered devices.

## ✨ Features

- ✅ **Device Registration** - Register devices with push tokens
- ✅ **Bulk Notifications** - Send notifications to all registered devices
- ✅ **Fault Tolerance** - One device failure doesn't stop others
- ✅ **Non-Blocking** - Uses threading for fast responses
- ✅ **In-Memory Storage** - Simple storage (easy to upgrade to database)
- ✅ **Clean Error Handling** - Meaningful JSON error responses
- ✅ **Notification History** - Track all sent notifications

---

## 🚀 How to Run the Server

### Step 1: Prerequisites

Make sure you have Python installed (version 3.8 or higher):

```bash
python --version
```

### Step 2: Create a Virtual Environment (Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate it (Windows)
venv\Scripts\activate

# Activate it (Mac/Linux)
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Run the Server

```bash
python app.py
```

You should see:

```
============================================================
🔔 Notification Delivery API
============================================================
Server starting...
API URL: http://localhost:5000
Press Ctrl+C to stop the server
============================================================
```

The server is now running at `http://localhost:5000`

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info and available endpoints |
| GET | `/devices` | List all registered devices |
| POST | `/devices/register` | Register a new device |
| DELETE | `/devices/<device_id>` | Unregister a device |
| POST | `/notifications/send` | Send notification to all devices |
| GET | `/notifications/history` | View notification history |

---

## 🧪 How to Test with Postman

### Setting Up Postman

1. Download and install [Postman](https://www.postman.com/downloads/)
2. Open Postman
3. Create a new request for each endpoint below

### Test 1: Check API is Running

- **Method:** GET
- **URL:** `http://localhost:5000/`
- **Expected Response:**
```json
{
    "message": "Welcome to the Notification Delivery API! 🔔",
    "version": "1.0.0",
    "endpoints": {...}
}
```

### Test 2: Register a Device

- **Method:** POST
- **URL:** `http://localhost:5000/devices/register`
- **Headers:** `Content-Type: application/json`
- **Body (raw JSON):**
```json
{
    "token": "abc123xyz789",
    "name": "John's iPhone"
}
```
- **Expected Response (201 Created):**
```json
{
    "success": true,
    "message": "Device registered successfully",
    "device_id": "unique-uuid-here",
    "device_name": "John's iPhone",
    "registered_at": "2024-02-06T12:00:00"
}
```

### Test 3: Register Another Device

- **Method:** POST
- **URL:** `http://localhost:5000/devices/register`
- **Body (raw JSON):**
```json
{
    "token": "def456uvw123",
    "name": "Sarah's Android"
}
```

### Test 4: List All Devices

- **Method:** GET
- **URL:** `http://localhost:5000/devices`
- **Expected Response:**
```json
{
    "success": true,
    "message": "Found 2 registered device(s)",
    "count": 2,
    "devices": [
        {
            "device_id": "uuid-1",
            "name": "John's iPhone",
            "token": "abc123xyz7...",
            "registered_at": "2024-02-06T12:00:00"
        },
        {
            "device_id": "uuid-2",
            "name": "Sarah's Android",
            "token": "def456uvw1...",
            "registered_at": "2024-02-06T12:01:00"
        }
    ]
}
```

### Test 5: Send a Notification

- **Method:** POST
- **URL:** `http://localhost:5000/notifications/send`
- **Headers:** `Content-Type: application/json`
- **Body (raw JSON):**
```json
{
    "title": "Welcome!",
    "message": "Thank you for registering with our app!"
}
```
- **Expected Response:**
```json
{
    "success": true,
    "message": "Notification sent to 2 device(s)",
    "notification": {
        "title": "Welcome!",
        "message": "Thank you for registering with our app!"
    },
    "statistics": {
        "total_devices": 2,
        "successful": 2,
        "failed": 0
    },
    "delivery_results": [
        {
            "device_id": "uuid-1",
            "device_name": "John's iPhone",
            "status": "success",
            "message": "Notification delivered successfully"
        },
        {
            "device_id": "uuid-2",
            "device_name": "Sarah's Android",
            "status": "success",
            "message": "Notification delivered successfully"
        }
    ]
}
```

### Test 6: View Notification History

- **Method:** GET
- **URL:** `http://localhost:5000/notifications/history`

### Test 7: Unregister a Device

- **Method:** DELETE
- **URL:** `http://localhost:5000/devices/{device_id}`
  - Replace `{device_id}` with an actual device ID from Step 4

### Test 8: Test Error Handling

Try registering a device with a token containing "fail" to see simulated failures:

```json
{
    "token": "fail_test_token",
    "name": "Test Failure Device"
}
```

Then send a notification - this device will show as "failed" while others succeed.

---

## 📊 Understanding the Code Structure

```
app.py
├── Flask App Initialization
├── In-Memory Storage (dictionaries)
├── Helper Functions
│   ├── simulate_send_to_device()  - Simulates push notification delivery
│   └── send_notifications_async() - Manages threading for parallel delivery
├── API Endpoints
│   ├── GET  /                      - API information
│   ├── GET  /devices               - List devices
│   ├── POST /devices/register      - Register device
│   ├── DELETE /devices/{id}        - Remove device
│   ├── POST /notifications/send    - Send notification
│   └── GET  /notifications/history - View history
└── Error Handlers
    ├── 404 - Not Found
    ├── 405 - Method Not Allowed
    └── 500 - Internal Server Error
```

---

## 🗄️ How to Extend with a Real Database

Currently, devices are stored in memory (they're lost when the server restarts). Here's how to add a real database:

### Option 1: SQLite (Simple, No Setup)

```python
# Install: pip install flask-sqlalchemy

from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///notifications.db'
db = SQLAlchemy(app)

class Device(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    token = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(100))
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    total_devices = db.Column(db.Integer)
    successful = db.Column(db.Integer)
    failed = db.Column(db.Integer)

# Create tables
with app.app_context():
    db.create_all()
```

### Option 2: PostgreSQL (Production-Ready)

```python
# Install: pip install flask-sqlalchemy psycopg2-binary

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://user:password@localhost/notifications'
```

### Option 3: MongoDB (NoSQL)

```python
# Install: pip install flask-pymongo

from flask_pymongo import PyMongo

app.config['MONGO_URI'] = 'mongodb://localhost:27017/notifications'
mongo = PyMongo(app)

# Use mongo.db.devices and mongo.db.notifications
```

---

## 🔥 How to Integrate with Firebase Cloud Messaging (FCM)

FCM is Google's free push notification service. Here's how to integrate:

### Step 1: Set Up Firebase

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create a new project
3. Go to Project Settings → Service Accounts
4. Click "Generate new private key" to download credentials JSON

### Step 2: Install Firebase Admin SDK

```bash
pip install firebase-admin
```

### Step 3: Initialize Firebase

```python
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize Firebase (do this once at app startup)
cred = credentials.Certificate('path/to/your-firebase-credentials.json')
firebase_admin.initialize_app(cred)
```

### Step 4: Replace the Simulation Function

```python
def send_to_device_fcm(device_token, title, message):
    """
    Send a real push notification via Firebase Cloud Messaging.
    """
    try:
        # Create the notification message
        notification = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=message,
            ),
            token=device_token,  # The device's FCM token
        )
        
        # Send the message
        response = messaging.send(notification)
        print(f"Successfully sent message: {response}")
        return {"status": "success", "message_id": response}
        
    except Exception as e:
        print(f"Error sending message: {e}")
        return {"status": "failed", "error": str(e)}
```

### Step 5: Send to Multiple Devices

```python
def send_to_all_devices_fcm(title, message):
    """
    Send notification to all registered devices via FCM.
    """
    tokens = [device["token"] for device in registered_devices.values()]
    
    if not tokens:
        return {"error": "No devices registered"}
    
    # Create multicast message
    multicast = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=message,
        ),
        tokens=tokens,
    )
    
    # Send to all devices at once
    response = messaging.send_multicast(multicast)
    
    return {
        "success_count": response.success_count,
        "failure_count": response.failure_count,
    }
```

---

## 🛠️ Troubleshooting

### "ModuleNotFoundError: No module named 'flask'"
```bash
pip install flask
```

### "Address already in use"
Another process is using port 5000. Either:
- Close the other process, or
- Change the port in `app.py`: `app.run(port=5001)`

### "Connection refused" in Postman
Make sure the Flask server is running and you're using `http://` (not `https://`)

---

## 📝 Quick Reference

### cURL Examples (Alternative to Postman)

```bash
# Check API
curl http://localhost:5000/

# Register device
curl -X POST http://localhost:5000/devices/register \
  -H "Content-Type: application/json" \
  -d '{"token": "abc123", "name": "My Phone"}'

# List devices
curl http://localhost:5000/devices

# Send notification
curl -X POST http://localhost:5000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{"title": "Hello", "message": "World"}'

# View history
curl http://localhost:5000/notifications/history

# Delete device
curl -X DELETE http://localhost:5000/devices/{device_id}
```

---

## 🎓 What's Next?

1. **Add Authentication** - Protect endpoints with API keys or JWT
2. **Add Rate Limiting** - Prevent abuse with Flask-Limiter
3. **Add Logging** - Use Python's logging module for production
4. **Add Testing** - Write unit tests with pytest
5. **Deploy** - Use Heroku, Railway, or AWS for production

---

Made with ❤️ for beginner Python developers
