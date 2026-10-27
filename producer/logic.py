"""
Producer Business Logic, Delivery Workers, Queue Engine, and Dispatchers.
Supports Redis durable queue with in-memory fallback, bounded thread pool execution,
Server-Sent Events broadcasting, and multi-protocol delivery (WebPush, FCM, HTTP).
"""

import os
import json
import requests
import queue
import threading
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException
from database import db, Notification

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ProducerLogic")

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")
}

VALID_DEVICE_TYPES = ["web", "mobile", "pager"]
WORKER_POOL_SIZE = 5
MAX_DISPATCH_THREADS = 20

# ---------------------------------------------------------------------------
# Durable Queue Backend (Redis with In-Memory Fallback)
# ---------------------------------------------------------------------------

class DurableNotificationQueue:
    """
    Queue abstraction: uses Redis for distributed persistence if REDIS_URL is provided,
    otherwise falls back to Python's in-memory queue.Queue().
    """

    def __init__(self, redis_url=None):
        self.redis = None
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        if self.redis_url:
            try:
                import redis
                client = redis.Redis.from_url(self.redis_url, decode_responses=True)
                client.ping()
                self.redis = client
                logger.info("Connected to Redis durable queue at %s", self.redis_url)
            except Exception as e:
                logger.warning("Could not connect to Redis (%s). Using in-memory queue fallback.", e)
                self.redis = None

        if not self.redis:
            self._mem_queue = queue.Queue()

    def put(self, job):
        """Put job into queue (persisted to Redis if configured)."""
        if self.redis:
            self.redis.rpush("notification_jobs", json.dumps(job))
        else:
            self._mem_queue.put(job)

    def get(self, block=True, timeout=1):
        """Pull job from queue."""
        if self.redis:
            # blpop returns (queue_name, value) or None
            item = self.redis.blpop("notification_jobs", timeout=timeout if block else 0)
            if item:
                return json.loads(item[1])
            if not block:
                raise queue.Empty()
            return None
        else:
            if block:
                try:
                    return self._mem_queue.get(timeout=timeout)
                except queue.Empty:
                    return None
            return self._mem_queue.get_nowait()

    def get_nowait(self):
        return self.get(block=False)

    def task_done(self):
        if not self.redis:
            try:
                self._mem_queue.task_done()
            except ValueError:
                pass

    def empty(self):
        if self.redis:
            return self.redis.llen("notification_jobs") == 0
        return self._mem_queue.empty()


# Initialize global queue
notification_queue = DurableNotificationQueue()

# Thread-safe in-memory fast tracker for active dashboard polling/status
job_tracker = {}
job_tracker_lock = threading.Lock()


def update_job_tracker(job_id, data):
    """Thread-safe update to the job_tracker dictionary."""
    with job_tracker_lock:
        if job_id not in job_tracker:
            job_tracker[job_id] = {}
        job_tracker[job_id].update(data)


def get_job_tracker(job_id):
    """Thread-safe read of a job from the job_tracker."""
    with job_tracker_lock:
        if job_id in job_tracker:
            return dict(job_tracker[job_id])
        return None


def get_active_queued_jobs():
    """Thread-safe snapshot of active jobs in the tracker."""
    with job_tracker_lock:
        active = []
        for job_id, job in job_tracker.items():
            if job.get("status") in ["queued", "processing"]:
                active.append({
                    "job_id": job_id,
                    "title": job.get("title", "Unknown"),
                    "status": job.get("status"),
                    "total_devices": job.get("total_devices", 0),
                    "enqueued_at": job.get("enqueued_at"),
                })
        return active


# ---------------------------------------------------------------------------
# SSE Client Management (Multi-tab real-time push)
# ---------------------------------------------------------------------------

sse_clients = []
sse_clients_lock = threading.Lock()


def broadcast_sse(data):
    """Push a typed event to all connected SSE dashboard clients instantly."""
    with sse_clients_lock:
        for client_queue in sse_clients:
            try:
                client_queue.put_nowait(data)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Device Health and Delivery Handlers
# ---------------------------------------------------------------------------

def check_device_active(device_dict):
    """
    Health check: pings device /status endpoint with a 2s timeout.
    Returns True if online, False otherwise.
    """
    try:
        url = f"http://{device_dict['ip_address']}:{device_dict['port']}/status"
        response = requests.get(url, timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def send_web_push(device_dict, title, message):
    """
    Delivers to Web Browsers:
    Uses VAPID webpush if subscription_data exists, otherwise delivers via HTTP /receive.
    """
    sub_json = device_dict.get("subscription_data")

    if sub_json:
        try:
            subscription = json.loads(sub_json) if isinstance(sub_json, str) else sub_json
            payload = json.dumps({"title": title, "body": message, "message": message})

            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
            logger.info("Delivered via global VAPID web push to '%s'", device_dict['name'])
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "success",
                "message": "Delivered via Global Web Push Service",
                "received_at": datetime.now().isoformat(),
            }
        except WebPushException as ex:
            logger.warning("VAPID Push error for '%s': %s", device_dict['name'], ex)
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "failed",
                "message": f"Global Push Error: {ex}",
            }
        except Exception as e:
            logger.error("Web Push exception for '%s': %s", device_dict['name'], e)
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "failed",
                "message": f"System Error: {str(e)}",
            }

    else:
        # Pre-delivery health check
        if not check_device_active(device_dict):
            logger.warning(
                "Device '%s' at http://%s:%s is inactive/offline",
                device_dict['name'], device_dict['ip_address'], device_dict['port']
            )
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "failed",
                "message": f"Device offline — not reachable at http://{device_dict['ip_address']}:{device_dict['port']}",
            }

        address = f"http://{device_dict['ip_address']}:{device_dict['port']}/receive"
        try:
            payload = {
                "title": title,
                "message": message,
                "from": "Producer API",
            }
            response = requests.post(address, json=payload, timeout=5)
            if response.status_code == 200:
                return {
                    "device_id": device_dict["id"],
                    "device_name": device_dict["name"],
                    "device_type": "web",
                    "status": "success",
                    "message": "Delivered to consumer server",
                }
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "failed",
                "message": f"Consumer returned HTTP {response.status_code}",
            }
        except Exception as e:
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "failed",
                "message": f"Connection failed: {str(e)}",
            }


def send_mobile_push(device_dict, title, message):
    """Deliver to Mobile devices via Google Firebase (FCM) or simulated fallback."""
    fcm_token = device_dict.get("subscription_data")

    if fcm_token and os.getenv("FIREBASE_CREDENTIALS_FILE"):
        try:
            import firebase_admin
            from firebase_admin import messaging, credentials

            if not firebase_admin._apps:
                cred = credentials.Certificate(os.getenv("FIREBASE_CREDENTIALS_FILE"))
                firebase_admin.initialize_app(cred)

            fcm_msg = messaging.Message(
                notification=messaging.Notification(title=title, body=message),
                token=fcm_token
            )
            response = messaging.send(fcm_msg)
            logger.info("Delivered to FCM for '%s' (ID: %s)", device_dict['name'], response)
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "mobile",
                "status": "success",
                "message": "Delivered via Google Firebase FCM",
                "received_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error("FCM error for '%s': %s", device_dict['name'], e)
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "mobile",
                "status": "failed",
                "message": f"FCM Error: {str(e)}",
            }

    # Simulation Mode
    time.sleep(0.2)
    logger.info("Mobile push simulated for '%s' (ID: %s)", device_dict['name'], device_dict['id'])
    return {
        "device_id": device_dict["id"],
        "device_name": device_dict["name"],
        "device_type": "mobile",
        "status": "success",
        "message": "Mobile push simulated (Firebase not configured)",
    }


def send_pager_notification(device_dict, title, message):
    """Deliver alert to Pager systems."""
    time.sleep(0.1)
    logger.info("Pager alert simulated for '%s' (ID: %s)", device_dict['name'], device_dict['id'])
    return {
        "device_id": device_dict["id"],
        "device_name": device_dict["name"],
        "device_type": "pager",
        "status": "success",
        "message": "Pager alert simulated (integrate pager gateway for production)",
    }


DEVICE_HANDLERS = {
    "web": send_web_push,
    "mobile": send_mobile_push,
    "pager": send_pager_notification,
}


# ---------------------------------------------------------------------------
# Job Processing with Bounded Concurrency & Transaction Safety
# ---------------------------------------------------------------------------

def process_job(job, app):
    """
    Process a single notification job with bounded thread pool dispatching,
    safe database transactions, and real-time SSE broadcasts.
    """
    job_id = job["job_id"]
    title = job["title"]
    message = job["message"]
    target_devices = job["target_devices"]

    logger.info("Processing job %s: '%s' → %d device(s)", job_id, title, len(target_devices))

    update_job_tracker(job_id, {"status": "processing"})
    broadcast_sse({"type": "job_processing", "job_id": job_id})

    results = []

    # Use bounded ThreadPoolExecutor to prevent OS thread exhaustion
    num_workers = min(MAX_DISPATCH_THREADS, max(len(target_devices), 1))
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_map = {}
        for device_dict in target_devices:
            handler = DEVICE_HANDLERS.get(device_dict.get("device_type"), send_web_push)
            future = executor.submit(handler, device_dict, title, message)
            future_map[future] = device_dict

        for future in as_completed(future_map):
            device_dict = future_map[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error("Exception during dispatch to %s: %s", device_dict.get("name"), e)
                results.append({
                    "device_id": device_dict.get("id"),
                    "device_name": device_dict.get("name"),
                    "device_type": device_dict.get("device_type", "web"),
                    "status": "failed",
                    "message": f"Internal execution error: {str(e)}",
                })

    successful = len([r for r in results if r["status"] == "success"])
    failed = len([r for r in results if r["status"] == "failed"])

    # Update database with rollback protection
    with app.app_context():
        try:
            notif = db.session.get(Notification, job_id)
            if notif:
                notif.processed_at = datetime.utcnow()
                notif.successful = successful
                notif.failed = failed
                notif.status = "completed"
                notif.details = json.dumps(results)
                db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            logger.error("Database update error for job %s: %s", job_id, db_err)

    # Update fast in-memory tracker
    update_job_tracker(
        job_id,
        {
            "status": "completed",
            "processed_at": datetime.now().isoformat(),
            "successful": successful,
            "failed": failed,
            "results": results,
        }
    )

    broadcast_sse({
        "type": "job_complete",
        "job_id": job_id,
        "status": "completed",
        "successful": successful,
        "failed": failed,
    })

    logger.info("Job %s completed: %d ok, %d failed", job_id, successful, failed)


def notification_worker(app):
    """Background worker loop pulling jobs from the durable queue."""
    while True:
        try:
            job = notification_queue.get(block=True, timeout=2)
            if job is None:
                continue

            try:
                process_job(job, app)
            except Exception as e:
                logger.error("Error processing job %s: %s", job.get("job_id"), e)
            finally:
                notification_queue.task_done()
        except Exception as ex:
            logger.error("Worker exception: %s", ex)
            time.sleep(1)


def start_worker_pool(app):
    """Start the pool of background worker threads."""
    for i in range(WORKER_POOL_SIZE):
        t = threading.Thread(
            target=notification_worker, args=(app,), daemon=True
        )
        t.start()
    logger.info("Started background worker pool (%d worker threads)", WORKER_POOL_SIZE)
