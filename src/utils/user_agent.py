"""
Centralized User-Agent construction for all API providers.

This module provides a single source of truth for the User-Agent string
used when making requests to external APIs (MusicBrainz, Discogs, Last.fm, etc.).
"""

from typing import TYPE_CHECKING

from .constants import APP_NAME_PASCAL, DEVELOPER_EMAIL, GITHUB_URL, VERSION

if TYPE_CHECKING:
    from .config import Config


def get_version() -> str:
    """
    Retrieve the application version.

    Returns:
        Version string (e.g., "1.0.0")
    """
    return VERSION


def build_user_agent(user_email: str | None = None) -> str:
    """
    Build a User-Agent string for API requests.

    Format: AppName/Version (dev_email; github_url; user_email)

    Args:
        user_email: Optional user-configured email (improves rate limits for MusicBrainz)

    Returns:
        User-Agent string suitable for HTTP headers

    Examples:
        >>> build_user_agent()
        'TuneCover/1.0.0 (me@domain.tld; https://github.com/...)'
        >>> build_user_agent("user@example.com")
        'TuneCover/1.0.0 (me@domain.tld; https://github.com/...; user@example.com)'
    """
    # Build the info parts
    parts = [DEVELOPER_EMAIL, GITHUB_URL]
    if user_email and user_email.strip():
        parts.append(user_email.strip())

    info = "; ".join(parts)

    return f"{APP_NAME_PASCAL}/{VERSION} ({info})"


def get_user_agent(config: "Config | None" = None) -> str:
    """
    Get the User-Agent string with user email from config if available.

    Args:
        config: Optional Config instance to retrieve user email from

    Returns:
        User-Agent string suitable for HTTP headers
    """
    user_email = None
    if config:
        user_email = config.get("app.contact_email", "")

    return build_user_agent(user_email)
