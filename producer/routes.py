"""
Alias module for REST API endpoints and routes to match README architecture documentation.
Re-exports from endpoints.py.
"""

from endpoints import api, get_network_ip

__all__ = ["api", "get_network_ip"]
