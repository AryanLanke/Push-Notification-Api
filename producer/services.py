"""
Alias module for background worker logic and queue engine to match README architecture documentation.
Re-exports from logic.py.
"""

from logic import (
    notification_queue,
    job_tracker,
    job_tracker_lock,
    update_job_tracker,
    get_job_tracker,
    get_active_queued_jobs,
    broadcast_sse,
    check_device_active,
    send_web_push,
    send_mobile_push,
    send_pager_notification,
    process_job,
    notification_worker,
    start_worker_pool,
    VALID_DEVICE_TYPES,
    WORKER_POOL_SIZE,
    VAPID_PUBLIC_KEY,
    sse_clients,
    sse_clients_lock,
)

__all__ = [
    "notification_queue",
    "job_tracker",
    "job_tracker_lock",
    "update_job_tracker",
    "get_job_tracker",
    "get_active_queued_jobs",
    "broadcast_sse",
    "check_device_active",
    "send_web_push",
    "send_mobile_push",
    "send_pager_notification",
    "process_job",
    "notification_worker",
    "start_worker_pool",
    "VALID_DEVICE_TYPES",
    "WORKER_POOL_SIZE",
    "VAPID_PUBLIC_KEY",
    "sse_clients",
    "sse_clients_lock",
]
