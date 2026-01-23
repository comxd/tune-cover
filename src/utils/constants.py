"""
Application-wide constants.

This module provides a single source of truth for application metadata.
The version is read dynamically from pyproject.toml via importlib.metadata.
"""

from importlib.metadata import PackageNotFoundError, version

# Application name variants
APP_NAME = "TuneCover"  # Human-readable display name
APP_NAME_SLUG = "tunecover"  # For package/URLs (matches pyproject.toml name)
APP_NAME_PASCAL = "TuneCover"  # For User-Agent and code identifiers

# Developer/contact info
AUTHOR = "David DIVERRES"
DEVELOPER_EMAIL = "david@comexpertise.com"
GITHUB_URL = "https://github.com/tunecover/tunecover"

# Version - read from pyproject.toml via importlib.metadata
# This is the Single Source of Truth pattern recommended by PyPA
# See: https://packaging.python.org/en/latest/discussions/single-source-version/
try:
    VERSION = version(APP_NAME_SLUG)
except PackageNotFoundError:
    # Fallback for development mode (editable install not done)
    VERSION = "0.0.0-dev"
