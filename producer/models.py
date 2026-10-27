"""
Alias module for database models to match README architecture documentation.
Re-exports Device, Notification, and db from database.py.
"""

from database import db, Device, Notification

__all__ = ["db", "Device", "Notification"]
