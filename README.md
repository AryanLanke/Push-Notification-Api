# 🔔 Push Notification System

A distributed **Producer-Consumer** notification system built with **Flask** and **Python**.

The **Producer** manages device registration, queues notifications, and delivers them to registered consumer devices. The **Consumer** receives notifications and displays them in a real-time dashboard.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│              PRODUCER (Port 5000)                │
│                                                  │
│  REST API → Queue → Worker Pool → HTTP Delivery  │
│  SQLite DB │ VAPID Web Push │ Admin Dashboard    │
└────────────────────┬────────────────────────────┘
                     │  HTTP POST /receive
                     ▼
┌─────────────────────────────────────────────────┐
│              CONSUMER (Port 5001)                │
│                                                  │
│  Receives notifications │ Live polling dashboard │
│  OS-level browser notifications                  │
└─────────────────────────────────────────────────┘
```

## Project Structure

```
notification-system/
├── producer.py            # Producer API server (port 5000)
├── consumer.py            # Consumer device server (port 5001)
├── templates/
│   ├── producer.html      # Admin dashboard UI
│   └── consumer.html      # Consumer dashboard UI
├── requirements.txt       # Python dependencies
├── .env                   # VAPID keys & database config
├── .gitignore
└── README.md
```

---

## Getting Started

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the Producer

```bash
python producer.py
```

The Producer starts on **http://localhost:5000** and provides:
- Admin dashboard at `/`
- REST API for device registration and notifications
- Background worker pool for async delivery

### 3. Start the Consumer

In a **separate terminal**:

```bash
python consumer.py
```

The Consumer starts on **http://localhost:5001** and:
- Auto-registers with the Producer on startup
- Receives notifications via HTTP POST
- Displays them in a real-time dashboard

#### Consumer Options

```bash
python consumer.py --port 5002 --name "My-Device" --producer-port 5000
```

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 5001 | Port for this consumer |
| `--name` | Consumer-Device-1 | Device display name |
| `--producer-port` | 5000 | Producer API port |

---

## API Endpoints (Producer)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Admin dashboard |
| `GET` | `/api` | API info & endpoints |
| `GET` | `/devices` | List registered devices |
| `POST` | `/devices/register` | Register a device |
| `DELETE` | `/devices/<id>` | Remove a device |
| `POST` | `/notifications/send` | Send notification |
| `GET` | `/notifications/status/<job_id>` | Check job status |
| `GET` | `/notifications/history` | View notification history |
| `GET` | `/vapid/public-key` | Get VAPID public key |

---

## How It Works

1. **Consumer** starts and auto-registers with the **Producer**
2. Open the **Producer dashboard** (`http://localhost:5000`) to see registered devices
3. Send a notification from the dashboard
4. The Producer queues the job and worker threads deliver it to each consumer
5. The **Consumer dashboard** (`http://localhost:5001`) shows received notifications in real-time

---

## Tech Stack

- **Backend**: Python, Flask, Flask-SQLAlchemy
- **Database**: SQLite
- **Web Push**: pywebpush, py-vapid (VAPID protocol)
- **Async**: Thread-based worker pool with queue
- **Frontend**: Vanilla HTML/CSS/JS with live polling
