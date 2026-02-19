# 🔔 Notification Delivery API (Enterprise Architecture)

A professional, decoupled backend API for delivering push notifications. Built with **Producer-Consumer architecture**, a **Message Queue**, and a **Multi-threaded Worker Pool**.

This API is designed for high-scalability and handles multiple device types (Web, Mobile, Pager) using specialized routing logic.

---

## 🏗️ System Architecture

The API uses an asynchronous design to ensure the server stays responsive even under heavy load:

1.  **PRODUCER (API Endpoints):** Validates requests and enqueues jobs into the system. It responds instantly with a `202 Accepted` status.
2.  **MESSAGE BROKER (Queue):** A thread-safe `queue.Queue` that manages the flow of notification jobs.
3.  **CONSUMER (Worker Pool):** A pool of 5 background threads that constantly pull jobs from the queue and execute them.
4.  **ROUTING LOGIC:** Automatically detects device types (web, mobile, pager) and dispatches them to the correct delivery handler.

---

## ✨ Features

- ✅ **Producer-Consumer Design** - Decouples API requests from message delivery.
- ✅ **Worker Pool** - 5 concurrent background workers for parallel processing.
- ✅ **Real Web Push (VAPID)** - Integrated `pywebpush` for cryptographically signed browser notifications.
- ✅ **Multi-Device Routing** - Specialized handlers for Web, Mobile (FCM/APNs), and Pagers.
- ✅ **Job Tracking** - Track the status of every notification job (Queued → Processing → Completed).
- ✅ **CORS Enabled** - Ready to be called from any frontend or mobile app.

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.8+
- [Postman](https://www.postman.com/) (recommended for testing)

### 2. Setup
```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# Install enterprise dependencies
pip install -r requirements.txt
```

### 3. Run the API
```bash
python app_pure.py
```
*The server will start on `http://localhost:5000` and launch 5 background consumer threads.*

---

## 📡 API Reference

### System Info
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api` | System architecture info and available endpoints |
| GET | `/vapid/public-key` | Fetch the VAPID Public Key for browser frontend |

### Device Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/devices` | List all registered devices and types |
| POST | `/devices/register` | Register a new device (supports `type="web"`, `"mobile"`, `"pager"`) |
| POST | `/devices/subscribe` | Store browser PushSubscription object for Web Push |
| DELETE | `/devices/<id>` | Unregister a device |

### Notification Delivery
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/notifications/send` | **Producer:** Enqueue a notification to the worker pool |
| GET | `/notifications/status/<job_id>` | Track job progress (Total, Successful, Failed) |
| GET | `/notifications/history` | View historical processed logs |

---

## 🔒 Security Summary

This API implements **VAPID (Voluntary Application Server Identification)**. 
- **Keys:** Cryptographically generated Public/Private keys are located in `app_pure.py`.
- **Note:** In this demo, keys are hardcoded for "plug-and-play" usability. In production, these should be moved to a `.env` file or Secret Manager.

---

## 🛠️ Production Evolution (Roadmap)

To move this from a professional prototype to a global-scale service, the following upgrades are recommended:

1.  **Storage Persistence:** Replace the In-Memory dictionaries with a database (e.g., **PostgreSQL** or **MongoDB**) to prevent data loss on restarts.
2.  **External Broker:** Swap the Python internal `queue.Queue` for a dedicated message broker like **Redis** or **RabbitMQ** for cross-server job management.
3.  **Authentication:** Add **API Keys** or **JWT Tokens** to the `/notifications/send` endpoint to prevent unauthorized broadcasting.
4.  **Mobile Integration:** Populate the `mobile` handler with real **Firebase Cloud Messaging (FCM)** credentials.

---
*Developed for the Web Push Notification Internship - Designed for Reliability & Speed.*
