import os
import json
import requests
import queue
import threading
import time
from datetime import datetime
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException
from models import db, Notification

load_dotenv()

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")
}

VALID_DEVICE_TYPES = ["web", "mobile", "pager"]

WORKER_POOL_SIZE = 5

# Shared queues and tracking
# A Queue is like a line at a restaurant. Jobs go in one end, workers pull them out the other.
notification_queue = queue.Queue()

# We track jobs in RAM (dictionary) so the UI can check their status instantly
# without having to query the database every single second.
job_tracker = {}


def send_web_push(device_dict, title, message):
    """
    Handles sending notifications to Web Browsers.
    It checks if the device registered with a real VAPID subscription (Real Browser popup)
    or just an IP/Port (Simulation for your testing).
    """
    sub_json = device_dict.get("subscription_data")

    if sub_json:
        try:
            subscription = json.loads(sub_json)
            payload = json.dumps({"title": title, "body": message})

            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
            print(
                f"[REAL-WEB] Delivered via global push to '{device_dict['name']}'"
            )
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "success",
                "message": "Delivered via Global Push Service",
                "received_at": datetime.now().isoformat(),
            }
        except WebPushException as ex:
            print(f"[WEB:VAPID-FAIL] {ex}")
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "failed",
                "message": f"Global Push Error: {ex}",
            }
        except Exception as e:
            return {
                "device_id": device_dict["id"],
                "device_name": device_dict["name"],
                "device_type": "web",
                "status": "failed",
                "message": f"System Error: {str(e)}",
            }

    else:
        address = (
            f"http://{device_dict['ip_address']}:{device_dict['port']}/receive"
        )
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
                "message": f"Consumer error: {response.status_code}",
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
    time.sleep(0.2)
    print(
        f"[MOBILE:SIM] Push simulated for '{device_dict['name']}' (ID: {device_dict['id']})"
    )
    return {
        "device_id": device_dict["id"],
        "device_name": device_dict["name"],
        "device_type": "mobile",
        "status": "success",
        "message": "Mobile push simulated (integrate FCM/APNs for production)",
    }


def send_pager_notification(device_dict, title, message):
    time.sleep(0.1)
    print(
        f"[PAGER:SIM] Alert simulated for '{device_dict['name']}' (ID: {device_dict['id']})"
    )
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


def notification_worker(app):
    """
    Worker thread logic that pulls jobs from queue.
    Think of a 'Worker Thread' as a mini-employee running in the background.
    They sit in a loop forever, waiting for a job to appear in the 'notification_queue'.
    """
    while True:
        # 1. Grab the next job in line. This line "blocks" (pauses) until a job arrives.
        job = notification_queue.get()
        job_id = job["job_id"]
        title = job["title"]
        message = job["message"]
        target_devices = job["target_devices"]

        print(
            f"\n[WORKER] Processing job {job_id}: '{title}' → {len(target_devices)} device(s)"
        )

        job_tracker[job_id]["status"] = "processing"

        results = []
        threads = []

        # 2. Loop through every device we need to send this to
        for device_dict in target_devices:
            # Pick the right delivery boy (Web, Mobile, or Pager)
            handler = DEVICE_HANDLERS.get(
                device_dict["device_type"], send_web_push
            )

            # We use mini-threads here so we can send to 100 devices at the EXACT SAME TIME,
            # rather than waiting for device 1 to finish before messaging device 2.
            def _dispatch(d=device_dict, h=handler):
                result = h(d, title, message)
                results.append(result)

            t = threading.Thread(target=_dispatch)
            threads.append(t)
            t.start()

        # Wait for all the mini-threads to finish sending
        for t in threads:
            t.join()

        # 3. Count up the successes and failures
        successful = len([r for r in results if r["status"] == "success"])
        failed = len([r for r in results if r["status"] == "failed"])

        # 4. Update the SQL Database with the final scores
        with app.app_context():
            notif = db.session.get(Notification, job_id)
            if notif:
                notif.processed_at = datetime.utcnow()
                notif.successful = successful
                notif.failed = failed
                notif.status = "completed"
                notif.details = json.dumps(results)
                db.session.commit()

        # Update the fast RAM tracker
        job_tracker[job_id].update(
            {
                "status": "completed",
                "processed_at": datetime.now().isoformat(),
                "successful": successful,
                "failed": failed,
                "results": results,
            }
        )

        print(f"[WORKER] Job {job_id} done — {successful} ok, {failed} failed")

        # 5. Tell the queue "I am finished with this job!"
        notification_queue.task_done()


def start_worker_pool(app):
    """
    Initialize and start the background worker pool.
    We create 5 workers (from WORKER_POOL_SIZE). They run 'daemon=True', meaning
    when you shut down the main Flask app, these workers die instantly.
    """
    for i in range(WORKER_POOL_SIZE):
        t = threading.Thread(
            target=notification_worker, args=(app,), daemon=True
        )
        t.start()
    print(f"✓ Worker pool started ({WORKER_POOL_SIZE} workers)")
