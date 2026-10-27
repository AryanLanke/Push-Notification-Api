"""
Database models and SQLAlchemy connection management.
Supports both PostgreSQL (production) and SQLite with WAL mode (development).
"""

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, Index
from sqlalchemy.engine import Engine
import sqlite3
import uuid
from datetime import datetime

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def configure_sqlite(dbapi_connection, connection_record):
    """Enable WAL mode and busy timeout for SQLite to prevent locking under concurrency."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


class Device(db.Model):
    """
    Registered device stored in the database.
    Represents web browsers, mobile endpoints, or pagers.
    """

    __tablename__ = "devices"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(20), nullable=False, default="web", index=True)
    ip_address = db.Column(db.String(50), nullable=False, default="127.0.0.1", index=True)
    port = db.Column(db.Integer, nullable=False, default=5001, index=True)
    email = db.Column(db.String(100), default="")

    subscription_data = db.Column(db.Text, nullable=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_device_ip_port", "ip_address", "port"),
    )

    def to_dict(self):
        return {
            "device_id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "ip_address": self.ip_address,
            "port": self.port,
            "email": self.email,
            "has_subscription": bool(self.subscription_data),
            "address": f"http://{self.ip_address}:{self.port}",
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
        }


class Notification(db.Model):
    """
    Notification audit history stored in the database.
    Tracks every dispatched notification, retry counts, and per-device results.
    """

    __tablename__ = "notifications"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    enqueued_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    processed_at = db.Column(db.DateTime, nullable=True)

    total_devices = db.Column(db.Integer, default=0)
    successful = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    retry_count = db.Column(db.Integer, default=0)

    status = db.Column(db.String(20), default="queued", index=True)
    details = db.Column(db.Text, default="[]")

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "status": self.status,
            "enqueued_at": self.enqueued_at.isoformat() if self.enqueued_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "total_devices": self.total_devices,
            "successful": self.successful,
            "failed": self.failed,
            "retry_count": self.retry_count,
            "details": json.loads(self.details) if self.details else [],
        }
