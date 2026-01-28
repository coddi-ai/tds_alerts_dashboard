"""
Configuration package for Multi-Technical-Alerts.

This package contains:
- settings.py: Application settings with validation
- logging_config.py: Centralized logging configuration
- users.py: User authentication database
"""

from .settings import get_settings
from .logging_config import setup_logging

__all__ = ["get_settings", "setup_logging"]
