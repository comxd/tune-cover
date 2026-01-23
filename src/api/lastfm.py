"""
Last.fm API provider for cover art.
"""

import logging
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..core.models import SearchResult
from .base import CoverProvider, handle_network_errors, is_valid_cover_url

logger = logging.getLogger(__name__)

# API endpoints
LASTFM_API = "https://ws.audioscrobbler.com/2.0/"

# Rate limiting: 1 request per second to be safe and consistent with other providers
RATE_LIMIT_DELAY = 1.0

# HTTP timeouts (connect, read) in seconds
HTTP_TIMEOUT = (10, 30)


class LastFmProvider(CoverProvider):
    """
    Cover art provider using the Last.fm API.

    Last.fm provides album information and cover art URLs.
    An API key is required for all requests.
    """

    def __init__(self, api_key: str | None = None, user_email: str | None = None):
        """
        Initialize the Last.fm provider.

        Args:
            api_key: Last.fm API key (required for API access)
            user_email: Optional user-configured contact email for User-Agent
        """
        self.api_key = api_key
        self._user_email = user_email
        self._session = requests.Session()
        self._setup_session()
        self._last_request_time = time.time()
        self._rate_limit_lock = threading.Lock()

    def _setup_session(self):
        """Configure the HTTP session."""
        from ..utils.user_agent import build_user_agent

        self._session.headers.update({"User-Agent": build_user_agent(self._user_email)})

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

    def set_api_key(self, key: str):
        """
        Set or update the API key.

        Args:
            key: Last.fm API key
        """
        self.api_key = key

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
        logger.debug("Last.fm: User-Agent updated")

    @property
    def name(self) -> str:
        return "Last.fm"

    @property
    def api_host(self) -> str:
        return "ws.audioscrobbler.com"

    @property
    def requires_api_key(self) -> bool:
        return True

    def _has_api_key(self) -> bool:
        return bool(self.api_key)

    def _rate_limit(self):
        """Enforce rate limiting for Last.fm API (thread-safe)."""
        with self._rate_limit_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY - elapsed)
            self._last_request_time = time.time()

    def search(self, artist: str, album: str, year: str | None = None) -> list[SearchResult]:
        """
        Search for albums on Last.fm.

        Args:
            artist: Artist name
            album: Album name
            year: Optional release year (not used by Last.fm API)

        Returns:
            List of SearchResult objects
        """
        if not self.api_key:
            logger.warning("Last.fm API key not configured")
            return []

        self._rate_limit()

        # Last.fm album.search method
        params = {
            "method": "album.search",
            "album": f"{artist} {album}".strip() if artist else album,
            "api_key": self.api_key,
            "format": "json",
            "limit": 10,
        }

        try:
            with handle_network_errors("Last.fm"):
                response = self._session.get(LASTFM_API, params=params, timeout=HTTP_TIMEOUT)
                response.raise_for_status()

            data = response.json()

            if "error" in data:
                logger.error(f"Last.fm API error: {data.get('message')}")
                return []

            results = []
            albums = data.get("results", {}).get("albummatches", {}).get("album", [])

            for item in albums:
                # Get the largest available image
                cover_url = self._get_best_image(item.get("image", []))

                result = SearchResult(
                    provider=self.name,
                    mbid=item.get("mbid", ""),
                    artist=item.get("artist", ""),
                    album=item.get("name", ""),
                    year=None,  # Last.fm search doesn't return year
                    score=self._calculate_relevance(item, artist, album),
                    has_cover_art=bool(cover_url),
                    cover_url=cover_url,
                )
                results.append(result)

            # Sort by score descending
            results.sort(key=lambda r: r.score, reverse=True)
            return results

        except (KeyError, ValueError) as e:
            logger.error(f"Last.fm response parsing error: {e}")
            return []

    def _get_best_image(self, images) -> str | None:
        """Get the largest available image URL."""
        # Validate that images is a list
        if not isinstance(images, list):
            return None

        # Last.fm images are ordered: small, medium, large, extralarge, mega
        size_priority = ["mega", "extralarge", "large", "medium", "small"]

        image_map = {}
        for img in images:
            if isinstance(img, dict):
                size = img.get("size")
                url = img.get("#text")
                if size and url:
                    image_map[size] = url

        for size in size_priority:
            if image_map.get(size):
                return image_map[size]

        return None

    def _calculate_relevance(self, item: dict, artist: str, album: str) -> int:
        """Calculate relevance score for a search result."""
        score = 50  # Base score

        item_artist = (item.get("artist", "") or "").lower()
        item_album = (item.get("name", "") or "").lower()
        artist_lower = artist.lower() if artist else ""
        album_lower = album.lower() if album else ""

        # Exact artist match
        if artist_lower and item_artist == artist_lower:
            score += 25
        elif artist_lower and artist_lower in item_artist:
            score += 15

        # Exact album match
        if album_lower and item_album == album_lower:
            score += 25
        elif album_lower and album_lower in item_album:
            score += 15

        return min(100, max(0, score))

    def get_cover_url(self, result: SearchResult) -> str | None:
        """
        Get cover art URL from Last.fm.

        Args:
            result: SearchResult with album info

        Returns:
            Cover art URL if available, None otherwise
        """
        # If we already have the URL from search, return it
        if result.cover_url:
            return result.cover_url

        if not self.api_key:
            return None

        self._rate_limit()

        # Use album.getinfo for more detailed info
        params = {"method": "album.getinfo", "api_key": self.api_key, "format": "json"}

        # Prefer MBID if available, otherwise use artist/album
        if result.mbid:
            params["mbid"] = result.mbid
        else:
            params["artist"] = result.artist
            params["album"] = result.album

        try:
            with handle_network_errors("Last.fm"):
                response = self._session.get(LASTFM_API, params=params, timeout=HTTP_TIMEOUT)

                if response.status_code == 404:
                    return None

                response.raise_for_status()

            data = response.json()

            if "error" in data:
                return None

            album_info = data.get("album", {})
            images = album_info.get("image", [])
            return self._get_best_image(images)

        except (KeyError, ValueError) as e:
            logger.debug(f"Last.fm parsing error: {e}")
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

        with handle_network_errors("Last.fm"):
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
