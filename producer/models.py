# SQLAlchemy is an "ORM" (Object-Relational Mapper).
# This means it lets us write normal Python classes instead of complicated SQL queries.
from flask_sqlalchemy import SQLAlchemy
import uuid
from datetime import datetime

# Creates our database control object. We attach it to the Flask app in app.py.
db = SQLAlchemy()


class Device(db.Model):
    """
    Registered device stored in the database.
    Think of this class as the blueprint for the 'devices' table in the database.
    Every time a user registers a device, it creates a new 'Row' using these columns.
    """

    __tablename__ = "devices"

    # db.Column creates a column in our database table
    # primary_key=True means this is the unique identifier for the row
    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # nullable=False means this field cannot be left blank
    name = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(20), nullable=False, default="web")
    ip_address = db.Column(db.String(50), nullable=False, default="127.0.0.1")
    port = db.Column(db.Integer, nullable=False, default=5001)
    email = db.Column(db.String(100), default="")

    # db.Text is used for long pieces of data, like JSON subscription strings
    subscription_data = db.Column(db.Text, nullable=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

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
            "registered_at": self.registered_at.isoformat(),
        }


class Notification(db.Model):
    """
    Notification history stored in the database.
    This tracks every single notification we have ever sent and its success/failure status.
    """

    __tablename__ = "notifications"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    enqueued_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)

    # These three integers keep track of the results for all target devices
    total_devices = db.Column(db.Integer, default=0)
    successful = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)

    status = db.Column(db.String(20), default="queued")
    details = db.Column(db.Text, default="[]")
