"""
Abstract base class for cover art providers.
"""

import ipaddress
import logging
import re
import socket
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import requests

from ..core.exceptions import NetworkError, RateLimitError
from ..core.models import SearchResult
from .circuit_breaker import CircuitBreakerRegistry
from .metrics import MetricsRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


@contextmanager
def handle_network_errors(provider_name: str, use_circuit_breaker: bool = True) -> "Iterator[None]":
    """
    Context manager for consistent network error handling across all providers.

    Converts requests exceptions into our custom exception hierarchy:
    - ConnectionError, Timeout → NetworkError
    - HTTPError with 429/503 → RateLimitError
    - Other RequestException → NetworkError

    Additionally:
    - Integrates with circuit breaker to prevent cascading failures
    - Records metrics for monitoring and debugging
    - Uses structured logging for better observability

    This ensures consistent error handling across MusicBrainz, Discogs, and Last.fm,
    allowing the UI to properly distinguish between network failures (temporary,
    user can retry) and empty results (search worked but found nothing).

    Usage:
        with handle_network_errors("Discogs"):
            response = session.get(url)
            response.raise_for_status()

    Args:
        provider_name: Name of the provider for error messages (e.g., "Discogs")
        use_circuit_breaker: Whether to check/update circuit breaker state

    Raises:
        NetworkError: For connection failures, timeouts, circuit open, and other issues
        RateLimitError: For HTTP 429 or 503 responses (rate limiting)
    """
    breaker = CircuitBreakerRegistry().get_breaker(provider_name)
    metrics = MetricsRegistry().get_metrics(provider_name)
    start_time = time.time()

    # Check circuit breaker state
    if use_circuit_breaker and not breaker.allow_request():
        logger.warning(
            "Request blocked by circuit breaker",
            extra={
                "provider": provider_name,
                "circuit_state": breaker.state.value,
                "failure_count": breaker.failure_count,
            },
        )
        raise NetworkError(f"{provider_name} is temporarily unavailable (circuit open)")

    try:
        yield
        # Success: record metrics and update circuit breaker
        duration_ms = (time.time() - start_time) * 1000
        metrics.record_request(success=True, duration_ms=duration_ms)
        if use_circuit_breaker:
            breaker.record_success()

    except requests.exceptions.ConnectionError as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics.record_request(success=False, duration_ms=duration_ms)
        if use_circuit_breaker:
            breaker.record_failure()
        logger.error(
            "Network connection error",
            extra={
                "provider": provider_name,
                "error_type": "ConnectionError",
                "error_message": str(e),
                "duration_ms": duration_ms,
            },
        )
        raise NetworkError(f"{provider_name} connection failed: {e}") from e

    except requests.exceptions.Timeout as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics.record_request(success=False, duration_ms=duration_ms)
        if use_circuit_breaker:
            breaker.record_failure()
        logger.error(
            "Network timeout",
            extra={
                "provider": provider_name,
                "error_type": "Timeout",
                "error_message": str(e),
                "duration_ms": duration_ms,
            },
        )
        raise NetworkError(f"{provider_name} request timed out: {e}") from e

    except requests.exceptions.HTTPError as e:
        duration_ms = (time.time() - start_time) * 1000
        response = e.response
        status_code = response.status_code if response is not None else None

        if status_code in (429, 503):
            # Retry-After can be either seconds (numeric) or HTTP-date (RFC 7231).
            # We only parse numeric values for simplicity; HTTP-date is rare for rate limiting.
            # NOTE: Use `response is not None` instead of `if response` because Response.__bool__
            # returns self.ok, which is False for 4xx/5xx status codes.
            retry_after = response.headers.get("Retry-After") if response is not None else None
            retry_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
            metrics.record_request(success=False, duration_ms=duration_ms, rate_limited=True)
            if use_circuit_breaker:
                breaker.record_failure()
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "provider": provider_name,
                    "error_type": "RateLimitError",
                    "status_code": status_code,
                    "retry_after": retry_seconds,
                    "duration_ms": duration_ms,
                },
            )
            raise RateLimitError(
                f"{provider_name} rate limit exceeded (HTTP {status_code})",
                retry_after=retry_seconds,
            ) from e

        metrics.record_request(success=False, duration_ms=duration_ms)
        if use_circuit_breaker:
            breaker.record_failure()
        logger.error(
            "HTTP error",
            extra={
                "provider": provider_name,
                "error_type": "HTTPError",
                "status_code": status_code,
                "error_message": str(e),
                "duration_ms": duration_ms,
            },
        )
        raise NetworkError(f"{provider_name} request failed: {e}") from e

    except requests.exceptions.RequestException as e:
        duration_ms = (time.time() - start_time) * 1000
        # When urllib3's Retry exhausts attempts on 429/503, it wraps the final
        # response in a generic RequestException rather than HTTPError.
        # The status code appears in the error message string, so we check for it
        # to provide a proper RateLimitError. This string matching is fragile but
        # necessary due to urllib3's retry implementation hiding the original status.
        error_str = str(e).lower()
        is_rate_limited = "429" in error_str or "503" in error_str

        if is_rate_limited:
            metrics.record_request(success=False, duration_ms=duration_ms, rate_limited=True)
            if use_circuit_breaker:
                breaker.record_failure()
            logger.warning(
                "Rate limit exceeded after retries",
                extra={
                    "provider": provider_name,
                    "error_type": "RateLimitError",
                    "error_message": str(e),
                    "duration_ms": duration_ms,
                },
            )
            raise RateLimitError(
                f"{provider_name} rate limit exceeded after retries",
                retry_after=None,
            ) from e

        metrics.record_request(success=False, duration_ms=duration_ms)
        if use_circuit_breaker:
            breaker.record_failure()
        logger.error(
            "Network request error",
            extra={
                "provider": provider_name,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "duration_ms": duration_ms,
            },
        )
        raise NetworkError(f"{provider_name} request failed: {e}") from e


# Allowed domains for cover art downloads (SSRF prevention)
ALLOWED_COVER_DOMAINS: set[str] = {
    # MusicBrainz / Cover Art Archive
    "coverartarchive.org",
    "archive.org",
    # Discogs
    "discogs.com",
    "api.discogs.com",
    "i.discogs.com",
    "s.discogs.com",
    # Last.fm
    "lastfm.freetls.fastly.net",
    "lastfm-img2.akamaized.net",
    "last.fm",
    "lastfm.io",
}

# Domains that are allowed to use HTTP (not HTTPS)
HTTP_ALLOWED_DOMAINS: set[str] = {
    "archive.org",
    "coverartarchive.org",
}

# Pattern for archive.org CDN subdomains (e.g., ia800500.us.archive.org)
ARCHIVE_ORG_CDN_PATTERN = re.compile(r"^ia\d+\.us\.archive\.org$")


def _is_private_ip(hostname: str) -> bool:
    """
    Check if a hostname resolves to a private/reserved IP address.

    Args:
        hostname: Hostname to check

    Returns:
        True if hostname resolves to a private IP, False otherwise.
        Returns False if DNS resolution fails (let the HTTP request fail instead).
    """
    # First check if hostname is a literal IP address
    try:
        ip = ipaddress.ip_address(hostname)
        return bool(
            ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
        )
    except ValueError:
        # Not a literal IP, try DNS resolution
        pass

    try:
        # Resolve hostname to IP addresses
        ip_addresses = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
        for addr_info in ip_addresses:
            ip_str = addr_info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
                # Check for private, loopback, link-local, reserved addresses
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                    or ip.is_multicast
                ):
                    return True
            except ValueError:
                continue
        return False
    except (socket.gaierror, OSError):
        # DNS resolution failed - for whitelisted domains, allow the request
        # The HTTP request will fail if DNS is truly unavailable
        # This prevents blocking valid domains that temporarily fail DNS lookup
        return False


def _is_archive_org_domain(domain: str) -> bool:
    """
    Check if a domain is archive.org or one of its CDN subdomains.

    Args:
        domain: Domain to check

    Returns:
        True if domain is archive.org or a valid CDN subdomain
    """
    if domain == "archive.org":
        return True
    # Check for CDN pattern (e.g., ia800500.us.archive.org)
    return domain.endswith(".archive.org") and bool(ARCHIVE_ORG_CDN_PATTERN.match(domain))


def _is_whitelisted_domain(hostname: str) -> bool:
    """
    Check if a hostname is in the whitelist of allowed domains.

    Args:
        hostname: Hostname to check

    Returns:
        True if hostname is whitelisted
    """
    # Check exact match first
    if hostname in ALLOWED_COVER_DOMAINS:
        return True

    # Check for archive.org CDN subdomains
    if _is_archive_org_domain(hostname):
        return True

    # Check if it's a subdomain of an allowed domain
    return any(hostname.endswith("." + allowed) for allowed in ALLOWED_COVER_DOMAINS)


def is_valid_cover_url(url: str) -> bool:
    """
    Validate that a URL is allowed for cover art downloads.

    This prevents SSRF attacks by only allowing downloads from
    known cover art provider domains. Also blocks private/local IPs.

    Args:
        url: URL to validate

    Returns:
        True if URL is from an allowed domain, False otherwise
    """
    if not url:
        return False

    try:
        parsed = urlparse(url)

        # Extract hostname (without port)
        hostname = parsed.hostname
        if not hostname:
            logger.warning(f"Could not extract hostname from URL: {url}")
            return False

        hostname = hostname.lower()

        # Check for non-standard ports (only allow 80 and 443)
        port = parsed.port
        if port is not None and port not in (80, 443):
            logger.warning(f"Non-standard port not allowed: {port}")
            return False

        # Check scheme - HTTP only allowed for specific domains
        if parsed.scheme == "http":
            if not (_is_archive_org_domain(hostname) or hostname in HTTP_ALLOWED_DOMAINS):
                logger.warning(f"HTTP not allowed for domain: {hostname}")
                return False
        elif parsed.scheme != "https":
            logger.warning(f"Invalid URL scheme: {parsed.scheme}")
            return False

        # Check whitelist first - whitelisted domains pass even if DNS fails
        if not _is_whitelisted_domain(hostname):
            logger.warning(f"URL domain not in allowlist: {hostname}")
            return False

        # For whitelisted domains, check for private/local IP addresses
        # This protects against DNS rebinding attacks on whitelisted domains
        # Only check if hostname looks like an IP or can be resolved
        if _is_private_ip(hostname):
            logger.warning(f"Private/local IP address not allowed: {hostname}")
            return False

        return True

    except ValueError as e:
        logger.warning(f"Error parsing URL {url}: {e}")
        return False


class CoverProvider(ABC):
    """
    Abstract base class for cover art providers.

    All cover art providers (MusicBrainz, Discogs, Last.fm, etc.)
    should inherit from this class and implement the required methods.

    Resource Management:
        Providers maintain HTTP session connections that should be properly closed
        when no longer needed. Use providers as context managers for automatic cleanup:

        >>> with MusicBrainzProvider() as provider:
        ...     results = provider.search("Artist", "Album")

        Alternatively, call close() explicitly when done:

        >>> provider = MusicBrainzProvider()
        >>> try:
        ...     results = provider.search("Artist", "Album")
        ... finally:
        ...     provider.close()
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""

    @property
    @abstractmethod
    def api_host(self) -> str:
        """Return the API host (e.g., 'musicbrainz.org', 'api.discogs.com')."""

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """Return True if this provider requires an API key."""

    @abstractmethod
    def search(self, artist: str, album: str, year: str | None = None) -> list[SearchResult]:
        """
        Search for album releases.

        Args:
            artist: Artist name
            album: Album name
            year: Optional release year

        Returns:
            List of SearchResult objects
        """

    @abstractmethod
    def get_cover_url(self, result: SearchResult) -> str | None:
        """
        Get the cover art URL for a search result.

        Args:
            result: SearchResult from a previous search

        Returns:
            Cover art URL if available, None otherwise
        """

    @abstractmethod
    def download_cover(self, url: str) -> bytes | None:
        """
        Download cover art from a URL.

        Args:
            url: Cover art URL

        Returns:
            Raw image data if successful, None otherwise
        """

    def is_configured(self) -> bool:
        """
        Check if the provider is properly configured.

        Returns:
            True if the provider is ready to use
        """
        if self.requires_api_key:
            return self._has_api_key()
        return True

    def _has_api_key(self) -> bool:
        """Check if API key is configured. Override in subclasses."""
        return False

    def calculate_match_score(
        self, local_artist: str, local_album: str, local_year: str | None, result: SearchResult
    ) -> int:
        """
        Calculate a match score between local album and search result.

        Args:
            local_artist: Local album artist
            local_album: Local album name
            local_year: Local album year
            result: Search result to compare

        Returns:
            Match score (0-100)
        """
        score = 0
        local_artist = (local_artist or "").lower().strip()
        local_album = (local_album or "").lower().strip()
        remote_artist = (result.artist or "").lower().strip()
        remote_album = (result.album or "").lower().strip()
        remote_year = result.year or ""

        # Artist match (40 points max)
        if local_artist and remote_artist:
            if local_artist == remote_artist:
                score += 40
            elif local_artist in remote_artist or remote_artist in local_artist:
                score += 20

        # Album match (40 points max)
        if local_album and remote_album:
            if local_album == remote_album:
                score += 40
            elif local_album in remote_album or remote_album in local_album:
                score += 20

        # Year match (20 points)
        if local_year and remote_year and local_year[:4] == remote_year[:4]:
            score += 20

        return score
