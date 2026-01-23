"""
Discogs API provider for cover art.
"""

import logging
import re
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..core.exceptions import ProviderError
from ..core.models import SearchResult
from .base import CoverProvider, handle_network_errors, is_valid_cover_url

logger = logging.getLogger(__name__)

# API endpoints
DISCOGS_API = "https://api.discogs.com"

# Rate limiting: Discogs allows 60 requests per minute for authenticated users
# For unauthenticated: 25 requests per minute
RATE_LIMIT_DELAY = 1.0

# HTTP timeouts (connect, read) in seconds
HTTP_TIMEOUT = (10, 30)


class DiscogsProvider(CoverProvider):
    """
    Cover art provider using the Discogs API.

    Discogs provides a large database of music releases with cover art.
    An API key (token) is recommended for higher rate limits.
    """

    def __init__(self, api_token: str | None = None, user_email: str | None = None):
        """
        Initialize the Discogs provider.

        Args:
            api_token: Optional Discogs personal access token for higher rate limits
            user_email: Optional user-configured contact email for User-Agent
        """
        self.api_token = api_token
        self._user_email = user_email
        self._session = requests.Session()
        self._setup_session()
        self._last_request_time = time.time()
        self._rate_limit_lock = threading.Lock()

    def _setup_session(self):
        """Configure the HTTP session."""
        from ..utils.user_agent import build_user_agent

        headers = {
            "User-Agent": build_user_agent(self._user_email),
            "Accept": "application/vnd.discogs.v2.discogs+json",
        }
        if self.api_token:
            headers["Authorization"] = f"Discogs token={self.api_token}"

        self._session.headers.update(headers)

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def set_api_token(self, token: str):
        """
        Set or update the API token.

        Args:
            token: Discogs personal access token
        """
        self.api_token = token
        self._setup_session()

    def update_user_agent(self, user_email: str | None = None):
        """
        Update the User-Agent dynamically (e.g., when user changes email in preferences).

        Args:
            user_email: Optional user-configured contact email
        """
        from ..utils.user_agent import build_user_agent

        self._user_email = user_email
        user_agent = build_user_agent(user_email)
        self._session.headers.update({"User-Agent": user_agent})
        logger.debug("Discogs: User-Agent updated")

    @property
    def name(self) -> str:
        return "Discogs"

    @property
    def api_host(self) -> str:
        return "api.discogs.com"

    @property
    def requires_api_key(self) -> bool:
        return True  # API key required for Discogs

    def _has_api_key(self) -> bool:
        return bool(self.api_token)

    def _rate_limit(self):
        """Enforce rate limiting for Discogs API (thread-safe)."""
        with self._rate_limit_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY - elapsed)
            self._last_request_time = time.time()

    def search(self, artist: str, album: str, year: str | None = None) -> list[SearchResult]:
        """
        Search for album releases on Discogs.

        Args:
            artist: Artist name
            album: Album name
            year: Optional release year

        Returns:
            List of SearchResult objects
        """
        self._rate_limit()

        # Build query
        query_parts = []
        if artist:
            query_parts.append(artist)
        if album:
            query_parts.append(album)

        if not query_parts:
            return []

        query = " ".join(query_parts)

        # Build query with user-provided parameters
        params = {"q": query, "type": "release", "per_page": 10}

        if year:
            params["year"] = year

        try:
            with handle_network_errors("Discogs"):
                response = self._session.get(
                    f"{DISCOGS_API}/database/search", params=params, timeout=HTTP_TIMEOUT
                )
                # Check for auth error before raise_for_status
                if response.status_code == 401:
                    logger.error(
                        "Discogs search error: Authentication required. Please configure API token."
                    )
                    raise ProviderError(
                        "Discogs requires an API token. Please configure it in preferences.",
                        provider_name="Discogs",
                    )
                response.raise_for_status()

            data = response.json()

            results = []
            for item in data.get("results", []):
                # Parse title (usually "Artist - Album")
                title = item.get("title", "")
                parts = title.split(" - ", 1)
                if len(parts) == 2:
                    item_artist, item_album = parts
                else:
                    item_artist = ""
                    item_album = title

                # Extract year from release date
                item_year = item.get("year")
                if item_year:
                    item_year = str(item_year)

                result = SearchResult(
                    provider=self.name,
                    mbid=str(item.get("id", "")),  # Using Discogs ID
                    artist=item_artist.strip(),
                    album=item_album.strip(),
                    year=item_year,
                    score=self._calculate_relevance(item, artist, album),
                    has_cover_art=bool(item.get("cover_image")),
                    cover_url=item.get("cover_image"),
                )
                results.append(result)

            # Sort by score descending
            results.sort(key=lambda r: r.score, reverse=True)
            return results

        except (KeyError, ValueError) as e:
            logger.error(f"Discogs response parsing error: {e}")
            return []

    def _calculate_relevance(self, item: dict, artist: str, album: str) -> int:
        """Calculate relevance score for a search result."""
        score = 50  # Base score

        title = item.get("title", "").lower()
        artist_lower = artist.lower() if artist else ""
        album_lower = album.lower() if album else ""

        # Boost if artist matches
        if artist_lower and artist_lower in title:
            score += 25

        # Boost if album matches
        if album_lower and album_lower in title:
            score += 25

        # Penalize compilations
        if item.get("format") and "Comp" in str(item.get("format")):
            score -= 10

        # Prefer releases with cover images
        if item.get("cover_image"):
            score += 5

        return min(100, max(0, score))

    def lookup_by_release_id(self, release_id: str) -> SearchResult | None:
        """
        Direct lookup of a release by its Discogs release ID.

        Args:
            release_id: Discogs release ID (numeric string)

        Returns:
            SearchResult if found, None otherwise
        """
        if not release_id:
            return None

        # Clean and validate
        release_id = str(release_id).strip()
        if not release_id.isdigit():
            logger.warning(f"Invalid Discogs release ID format: {release_id}")
            return None

        logger.info(f"Direct lookup by Discogs release ID: {release_id}")

        self._rate_limit()

        try:
            with handle_network_errors("Discogs"):
                response = self._session.get(
                    f"{DISCOGS_API}/releases/{release_id}", timeout=HTTP_TIMEOUT
                )

                if response.status_code == 404:
                    logger.debug(f"Release not found for Discogs ID: {release_id}")
                    return None

                if response.status_code == 401:
                    logger.error("Discogs lookup error: Authentication required")
                    return None

                response.raise_for_status()

            data = response.json()

            # Extract artist(s)
            artists = data.get("artists", [])
            artist_name = artists[0].get("name", "") if artists else ""
            # Remove trailing numbers in parentheses that Discogs uses for disambiguation
            if artist_name:
                artist_name = re.sub(r"\s*\(\d+\)$", "", artist_name)

            # Extract year
            year = data.get("year")
            if year:
                year = str(year)

            # Get primary cover image
            cover_url = None
            images = data.get("images", [])
            for img in images:
                if img.get("type") == "primary":
                    cover_url = img.get("uri") or img.get("resource_url")
                    break
            if not cover_url and images:
                cover_url = images[0].get("uri") or images[0].get("resource_url")

            result = SearchResult(
                provider=self.name,
                mbid=release_id,  # Store Discogs ID in mbid field
                artist=artist_name,
                album=data.get("title", ""),
                year=year,
                score=100,  # Direct match = perfect score
                has_cover_art=bool(images),
                cover_url=cover_url,
            )

            logger.info(f"Found release: {result.artist} - {result.album}")
            return result

        except (KeyError, ValueError) as e:
            logger.error(f"Discogs parsing error for ID {release_id}: {e}")
            return None

    def lookup_by_barcode(self, barcode: str) -> SearchResult | None:
        """
        Look up a release by its barcode (UPC/EAN).

        Args:
            barcode: UPC (12 digits) or EAN (13 digits) barcode

        Returns:
            SearchResult if found, None otherwise
        """
        if not barcode:
            return None

        # Clean barcode
        barcode = barcode.replace("-", "").replace(" ", "")
        if not barcode.isdigit() or len(barcode) not in (12, 13):
            logger.warning(f"Invalid barcode format: {barcode}")
            return None

        logger.info(f"Discogs lookup by barcode: {barcode}")

        self._rate_limit()

        try:
            with handle_network_errors("Discogs"):
                response = self._session.get(
                    f"{DISCOGS_API}/database/search",
                    params={"barcode": barcode, "type": "release", "per_page": 1},
                    timeout=HTTP_TIMEOUT,
                )

                if response.status_code == 401:
                    logger.error("Discogs barcode lookup error: Authentication required")
                    return None

                response.raise_for_status()

            data = response.json()

            results = data.get("results", [])
            if not results:
                logger.debug(f"No releases found for barcode: {barcode}")
                return None

            item = results[0]

            # Parse title (usually "Artist - Album")
            title = item.get("title", "")
            parts = title.split(" - ", 1)
            if len(parts) == 2:
                item_artist, item_album = parts
            else:
                item_artist = ""
                item_album = title

            # Extract year
            item_year = item.get("year")
            if item_year:
                item_year = str(item_year)

            result = SearchResult(
                provider=self.name,
                mbid=str(item.get("id", "")),
                artist=item_artist.strip(),
                album=item_album.strip(),
                year=item_year,
                score=98,  # High confidence for barcode match
                has_cover_art=bool(item.get("cover_image")),
                cover_url=item.get("cover_image"),
            )

            logger.info(f"Found release via barcode: {result.artist} - {result.album}")
            return result

        except (KeyError, ValueError) as e:
            logger.error(f"Discogs barcode parsing error for {barcode}: {e}")
            return None

    def get_cover_url(self, result: SearchResult) -> str | None:
        """
        Get cover art URL from Discogs.

        Args:
            result: SearchResult with Discogs ID

        Returns:
            Cover art URL if available, None otherwise
        """
        # If we already have the URL from search, return it
        if result.cover_url:
            return result.cover_url

        if not result.mbid:
            return None

        self._rate_limit()

        try:
            with handle_network_errors("Discogs"):
                response = self._session.get(
                    f"{DISCOGS_API}/releases/{result.mbid}", timeout=HTTP_TIMEOUT
                )

                if response.status_code == 404:
                    return None

                response.raise_for_status()

            data = response.json()

            # Get primary image or first image
            images = data.get("images", [])
            for img in images:
                if img.get("type") == "primary":
                    return img.get("uri") or img.get("resource_url")

            if images:
                return images[0].get("uri") or images[0].get("resource_url")

            return None

        except (KeyError, ValueError) as e:
            logger.debug(f"Discogs parsing error for {result.mbid}: {e}")
            return None

    def download_cover(self, url: str) -> bytes | None:
        """
        Download cover art from URL.

        Args:
            url: Cover art URL

        Returns:
            Raw image data if successful, None if not found or invalid URL
        """
        # Validate URL to prevent SSRF attacks
        if not is_valid_cover_url(url):
            logger.error(f"Invalid or blocked cover URL: {url}")
            return None

        with handle_network_errors("Discogs"):
            response = self._session.get(url, timeout=HTTP_TIMEOUT)
            # A 404 means the cover doesn't exist - not a network error
            if response.status_code == 404:
                logger.debug(f"Cover not found (404): {url}")
                return None
            response.raise_for_status()
            return response.content

    def close(self) -> None:
        """Close the HTTP session and release resources."""
        if self._session:
            self._session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
