# 🔔 Notification Delivery API (Distributed Architecture)

A professional, distributed notification system with a **Generator/Producer** API and **Consumer Device** applications communicating over HTTP.

---

## 🏗️ System Architecture

```
┌──────────────────────────┐       HTTP POST        ┌─────────────────────────┐
│    GENERATOR (Producer)  │  ──────────────────►    │   CONSUMER (Device)     │
│    app_pure.py           │     /receive            │   consumer_app.py       │
│    Port 5000             │                         │   Port 5001             │
│                          │◄──────────────────      │                         │
│    SQLite Database       │    Auto-registers       │   Displays received     │
│    Worker Pool (5)       │    on startup           │   notifications         │
│    VAPID Keys (.env)     │                         │                         │
└──────────────────────────┘                         └─────────────────────────┘
```

1. **Generator (Producer):** `app_pure.py` — The core API on Port 5000. Accepts notification requests, stores devices in SQLite, and dispatches jobs via a worker pool.
2. **Consumer (Device):** `consumer_app.py` — A separate app on Port 5001 (or any port). Auto-registers itself with the Generator. Receives and displays notifications.
3. **Communication:** The Generator sends HTTP POST requests to each Consumer's `/receive` endpoint at their registered IP:port.

---

## ✨ Features

- ✅ **Distributed Architecture** — Generator and Consumer are separate applications
- ✅ **SQLite Database** — Persistent device storage (survives server restarts)
- ✅ **Worker Pool** — 5 concurrent background workers for parallel delivery
- ✅ **IP/Port Identification** — Each device is identified by its network address
- ✅ **VAPID Keys in .env** — Secrets stored securely outside the code
- ✅ **Auto-Registration** — Consumers register themselves on startup
- ✅ **Job Tracking** — Track notification status (Queued → Processing → Completed)
- ✅ **Visual Consumer Dashboard** — See received notifications in real-time

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.8+
- [Postman](https://www.postman.com/) (recommended for testing)

### 2. Setup
```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate     # Windows
source .venv/bin/activate  # Mac/Linux

# Install all dependencies
pip install -r requirements.txt
```

### 3. Run the Generator (Terminal 1)
```bash
python app_pure.py
```
*Starts the Generator/Producer API on Port 5000. Initializes SQLite database and 5 worker threads.*

### 4. Run a Consumer Device (Terminal 2)
```bash
python consumer_app.py --port 5001 --name "Dashboard-App"
```
*Starts a Consumer Device on Port 5001. Auto-registers with the Generator.*

### 5. Run More Consumer Devices (Terminal 3, etc.)
```bash
python consumer_app.py --port 5002 --name "Mobile-Simulator"
python consumer_app.py --port 5003 --name "Flipkart-App"
```
*Each consumer runs on its own port, simulating different devices on the network.*

---

## 📡 API Reference (Generator — Port 5000)

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api` | System info and all available endpoints |
| GET | `/vapid/public-key` | VAPID public key for browser push |

### Devices
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/devices` | List all registered devices (from database) |
| POST | `/devices/register` | Register a device with name, IP, port, type |
| DELETE | `/devices/<id>` | Unregister a device |

### Notifications
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/notifications/send` | Enqueue a notification job |
| GET | `/notifications/status/<job_id>` | Track job progress |
| GET | `/notifications/history` | View notification history (from database) |

### Consumer Device Endpoints (Port 5001+)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Visual dashboard showing received notifications |
| POST | `/receive` | Endpoint called by Generator to deliver notifications |
| GET | `/status` | Health check for the consumer device |

---

## 🧪 Demo Flow

### Step 1: Start Generator
```bash
python app_pure.py
```

### Step 2: Start Consumer
```bash
python consumer_app.py --port 5001 --name "My-Dashboard"
```

### Step 3: Send Notification (via Postman or cURL)
```bash
curl -X POST http://localhost:5000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{"title": "Hello!", "message": "This is a real notification!"}'
```

### Step 4: Check the Consumer Dashboard
Open `http://localhost:5001` in your browser — you'll see the notification displayed!

---

## 🔒 Security

- **VAPID Keys:** Stored in `.env` file (not in code, not on GitHub)
- **Database:** SQLite file (`notifications.db`) is gitignored
- **CORS:** Configurable cross-origin access

---

## 📦 Tech Stack

| Category | Technology | Purpose |
|----------|-----------|---------|
| Framework | Flask | REST API server |
| Database | SQLAlchemy + SQLite | Persistent device storage |
| Security | Flask-CORS, Py-VAPID | Cross-origin + push signing |
| Delivery | PyWebPush, Requests | Web push + HTTP delivery |
| Architecture | Threading, Queue | Worker pool + async processing |
| Config | python-dotenv | Environment variable management |

---
*Developed for the Web Push Notification Internship — Distributed Generator/Consumer Architecture*
