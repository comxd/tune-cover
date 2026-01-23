"""
MusicBrainz and Cover Art Archive provider.
"""

import logging
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..core.exceptions import RateLimitError
from ..core.models import SearchResult
from .base import CoverProvider, handle_network_errors, is_valid_cover_url

logger = logging.getLogger(__name__)

# API endpoints
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
COVERART_API = "https://coverartarchive.org"

# Rate limiting: 1 request per second (only when no contact email)
RATE_LIMIT_DELAY = 1.1

# Retry delay for 503 errors (when using email-based rate limiting)
RETRY_DELAY_503 = 1.0

# HTTP timeouts (connect, read) in seconds
HTTP_TIMEOUT = (10, 30)


class MusicBrainzProvider(CoverProvider):
    """
    Cover art provider using MusicBrainz and Cover Art Archive.

    This provider searches MusicBrainz for album releases and fetches
    cover art from the Cover Art Archive.

    Rate limiting behavior:
    - Without contact email: 1.1s delay between requests (safe default)
    - With contact email: No pre-request delay, retry on 503 after 1s
      (MusicBrainz allows up to 50 req/s with proper User-Agent)
    """

    def __init__(self, contact_email: str | None = None):
        """
        Initialize the MusicBrainz provider.

        Args:
            contact_email: Optional contact email for User-Agent.
                          Improves rate limit from 1 to 50 requests/second.
        """
        from ..utils.user_agent import build_user_agent

        # Normalize email: strip whitespace and convert empty to None
        _email = contact_email.strip() if contact_email else ""
        self.contact_email = _email if _email else None
        self._use_rate_limit = not self.contact_email
        self._last_request_time = time.time()
        self._rate_limit_lock = threading.Lock()

        # Build User-Agent using centralized function
        user_agent = build_user_agent(self.contact_email)
        if self.contact_email:
            logger.info("MusicBrainz: Using email-based User-Agent (up to 50 req/s)")
        else:
            logger.info("MusicBrainz: No contact email, rate limit active (1 req/s)")

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

        # Configure retry strategy (for network errors, not rate limiting)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 504],  # Removed 503 - we handle it manually
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def update_user_agent(self, user_email: str | None = None):
        """
        Update the User-Agent dynamically (e.g., when user changes email in preferences).

        Args:
            user_email: Optional user-configured contact email
        """
        from ..utils.user_agent import build_user_agent

        # Normalize email
        _email = user_email.strip() if user_email else ""
        self.contact_email = _email if _email else None
        self._use_rate_limit = not self.contact_email

        # Update session headers
        user_agent = build_user_agent(self.contact_email)
        self._session.headers.update({"User-Agent": user_agent})

        if self.contact_email:
            logger.info("MusicBrainz: User-Agent updated with email (up to 50 req/s)")
        else:
            logger.info("MusicBrainz: User-Agent updated without email (1 req/s)")

    @property
    def name(self) -> str:
        return "MusicBrainz"

    @property
    def api_host(self) -> str:
        return "musicbrainz.org"

    @property
    def requires_api_key(self) -> bool:
        return False

    def _rate_limit_musicbrainz(self):
        """
        Enforce rate limiting for MusicBrainz API only (thread-safe).

        Only applies when no contact email is configured.
        With email: MusicBrainz allows up to 50 req/s, we rely on 503 retry.
        Without email: 1.1s delay between requests (safe default).

        Cover Art Archive (coverartarchive.org) has no strict rate limit
        as it's hosted by Internet Archive.
        """
        if not self._use_rate_limit:
            return  # Email configured, no pre-request delay needed

        with self._rate_limit_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY - elapsed)
            self._last_request_time = time.time()

    def _extract_year(self, date_str: str | None) -> str | None:
        """
        Safely extract a 4-digit year from a date string.

        Args:
            date_str: Date string (e.g., "2020-05-15", "2020", "20")

        Returns:
            4-digit year string if valid, None otherwise
        """
        if not date_str:
            return None
        date_str = str(date_str).strip()
        if len(date_str) >= 4:
            return date_str[:4]
        return None

    def _request_musicbrainz(
        self, url: str, params: dict | None = None, max_retries: int = 3
    ) -> requests.Response:
        """
        Make a request to MusicBrainz API with 503 retry handling.

        MusicBrainz has a specific rate limit pattern: 503 responses indicate
        temporary overload and should be retried after a short delay.
        This is handled here rather than in handle_network_errors because
        we want to retry before raising RateLimitError.

        Args:
            url: API endpoint URL
            params: Query parameters
            max_retries: Maximum retries on 503 error

        Returns:
            Response object (never None - raises exception on failure)

        Raises:
            NetworkError: For connection failures, timeouts, and other network issues
            RateLimitError: If 503 persists after max_retries
        """
        self._rate_limit_musicbrainz()

        for attempt in range(max_retries):
            with handle_network_errors("MusicBrainz"):
                response = self._session.get(url, params=params, timeout=HTTP_TIMEOUT)

                # Handle 503 Service Unavailable (rate limiting)
                # We retry before raising to handle temporary overload
                if response.status_code == 503:
                    if attempt < max_retries - 1:
                        logger.debug(f"MusicBrainz 503, retrying in {RETRY_DELAY_503}s...")
                        time.sleep(RETRY_DELAY_503)
                        continue
                    else:
                        logger.warning("MusicBrainz: Max retries reached on 503")
                        raise RateLimitError(
                            "MusicBrainz rate limit exceeded (503 after retries)",
                            retry_after=int(RETRY_DELAY_503),
                        )

                return response

        raise RateLimitError(
            "MusicBrainz rate limit exceeded (max retries)",
            retry_after=int(RETRY_DELAY_503),
        )

    def search(self, artist: str, album: str, year: str | None = None) -> list[SearchResult]:
        """
        Search for album releases on MusicBrainz.

        Args:
            artist: Artist name
            album: Album name
            year: Optional release year

        Returns:
            List of SearchResult objects
        """
        logger.info(
            f"MusicBrainz.search() called: artist={artist!r}, album={album!r}, year={year!r}"
        )

        # Build query with user-provided parameters
        query_parts = []
        if album:
            query_parts.append(f'release:"{album}"')
        if artist:
            query_parts.append(f'artist:"{artist}"')
        if year:
            query_parts.append(f"date:{year}*")

        if not query_parts:
            logger.warning("MusicBrainz search: empty query, returning []")
            return []

        query = " AND ".join(query_parts)
        logger.info(f"MusicBrainz API query: {query}")

        # Let NetworkError/RateLimitError bubble up to caller for proper UI handling
        response = self._request_musicbrainz(
            f"{MUSICBRAINZ_API}/release", params={"query": query, "fmt": "json", "limit": 10}
        )

        try:
            logger.debug(f"MusicBrainz response status: {response.status_code}")
            with handle_network_errors("MusicBrainz"):
                response.raise_for_status()

            data = response.json()
            logger.debug(f"MusicBrainz response: {len(data.get('releases', []))} releases found")

            results = []
            for release in data.get("releases", []):
                artist_credit = release.get("artist-credit", [{}])
                artist_name = artist_credit[0].get("name", "") if artist_credit else ""

                result = SearchResult(
                    provider=self.name,
                    mbid=release.get("id", ""),
                    artist=artist_name,
                    album=release.get("title", ""),
                    year=self._extract_year(release.get("date")),
                    score=release.get("score", 0),
                )
                results.append(result)

            return results
        except (KeyError, ValueError) as e:
            logger.error(f"MusicBrainz response parsing error: {e}")
            return []

    def lookup_by_mbid(self, mbid: str) -> SearchResult | None:
        """
        Direct lookup of a release by its MusicBrainz ID.

        This is the most reliable way to find cover art - no text search needed.

        Args:
            mbid: MusicBrainz release ID (e.g., "a2b62291-2981-4409-b024-44d5be206346")

        Returns:
            SearchResult if found, None otherwise
        """
        if not mbid:
            return None

        logger.info(f"Direct lookup by MBID: {mbid}")

        # Let NetworkError/RateLimitError bubble up to caller for proper UI handling
        response = self._request_musicbrainz(
            f"{MUSICBRAINZ_API}/release/{mbid}", params={"fmt": "json", "inc": "artist-credits"}
        )

        try:
            if response.status_code == 404:
                logger.debug(f"Release not found for MBID: {mbid}")
                return None

            with handle_network_errors("MusicBrainz"):
                response.raise_for_status()

            release = response.json()

            artist_credit = release.get("artist-credit", [{}])
            artist_name = artist_credit[0].get("name", "") if artist_credit else ""

            result = SearchResult(
                provider=self.name,
                mbid=mbid,
                artist=artist_name,
                album=release.get("title", ""),
                year=self._extract_year(release.get("date")),
                score=100,  # Direct match = perfect score
            )

            logger.info(f"Found release: {result.artist} - {result.album}")
            return result

        except (KeyError, ValueError) as e:
            logger.error(f"MusicBrainz response parsing error for MBID {mbid}: {e}")
            return None

    def lookup_by_isrc(self, isrc: str) -> SearchResult | None:
        """
        Look up a recording by its ISRC (International Standard Recording Code).

        ISRC identifies a specific recording, which can then be linked to releases.

        Args:
            isrc: ISRC code (12 characters, e.g., "USRC17607839")

        Returns:
            SearchResult if found, None otherwise
        """
        if not isrc:
            return None

        # Normalize ISRC
        isrc = isrc.replace("-", "").replace(" ", "").upper()
        if len(isrc) != 12:
            logger.warning(f"Invalid ISRC format: {isrc}")
            return None

        logger.info(f"Looking up ISRC: {isrc}")

        # Let NetworkError/RateLimitError bubble up to caller for proper UI handling
        response = self._request_musicbrainz(
            f"{MUSICBRAINZ_API}/isrc/{isrc}",
            params={"fmt": "json", "inc": "releases artist-credits"},
        )

        try:
            if response.status_code == 404:
                logger.debug(f"ISRC not found: {isrc}")
                return None

            with handle_network_errors("MusicBrainz"):
                response.raise_for_status()

            data = response.json()

            # ISRC returns recordings, we need to get a release from it
            recordings = data.get("recordings", [])
            if not recordings:
                logger.debug(f"No recordings found for ISRC: {isrc}")
                return None

            # Get the first recording with releases
            for recording in recordings:
                releases = recording.get("releases", [])
                if releases:
                    release = releases[0]
                    artist_credit = release.get("artist-credit", [{}])
                    artist_name = artist_credit[0].get("name", "") if artist_credit else ""

                    result = SearchResult(
                        provider=self.name,
                        mbid=release.get("id", ""),
                        artist=artist_name,
                        album=release.get("title", ""),
                        year=self._extract_year(release.get("date")),
                        score=95,  # High confidence for ISRC match
                    )
                    logger.info(f"Found release via ISRC: {result.artist} - {result.album}")
                    return result

            return None

        except (KeyError, ValueError) as e:
            logger.error(f"MusicBrainz ISRC response parsing error for {isrc}: {e}")
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

        logger.info(f"Looking up barcode: {barcode}")

        # Use search API with barcode query
        # Let NetworkError/RateLimitError bubble up to caller for proper UI handling
        response = self._request_musicbrainz(
            f"{MUSICBRAINZ_API}/release",
            params={"query": f"barcode:{barcode}", "fmt": "json", "limit": 1},
        )

        try:
            if response.status_code == 404:
                logger.debug(f"Barcode not found: {barcode}")
                return None

            with handle_network_errors("MusicBrainz"):
                response.raise_for_status()

            data = response.json()

            releases = data.get("releases", [])
            if not releases:
                logger.debug(f"No releases found for barcode: {barcode}")
                return None

            release = releases[0]
            artist_credit = release.get("artist-credit", [{}])
            artist_name = artist_credit[0].get("name", "") if artist_credit else ""

            result = SearchResult(
                provider=self.name,
                mbid=release.get("id", ""),
                artist=artist_name,
                album=release.get("title", ""),
                year=self._extract_year(release.get("date")),
                score=98,  # Very high confidence for barcode match
            )
            logger.info(f"Found release via barcode: {result.artist} - {result.album}")
            return result

        except (KeyError, ValueError) as e:
            logger.error(f"MusicBrainz barcode response parsing error for {barcode}: {e}")
            return None

    def get_cover_url(self, result: SearchResult) -> str | None:
        """
        Get cover art URL from Cover Art Archive.

        Args:
            result: SearchResult with MusicBrainz ID

        Returns:
            Cover art URL if available, None otherwise
        """
        if not result.mbid:
            return None

        # No rate limit for Cover Art Archive (hosted by Internet Archive)

        try:
            with handle_network_errors("Cover Art Archive"):
                response = self._session.get(
                    f"{COVERART_API}/release/{result.mbid}",
                    allow_redirects=True,
                    timeout=HTTP_TIMEOUT,
                )

                if response.status_code == 404:
                    return None

                response.raise_for_status()

            data = response.json()

            # Look for front cover first
            for image in data.get("images", []):
                if image.get("front", False):
                    thumbnails = image.get("thumbnails", {})
                    return (
                        thumbnails.get("large")
                        or thumbnails.get("500")
                        or thumbnails.get("250")
                        or image.get("image")
                    )

            # Fall back to first image
            if data.get("images"):
                image = data["images"][0]
                thumbnails = image.get("thumbnails", {})
                return thumbnails.get("large") or image.get("image")

            return None
        except (KeyError, ValueError) as e:
            logger.debug(f"Cover Art Archive parsing error for {result.mbid}: {e}")
            return None

    def get_cover_url_direct(self, mbid: str) -> str | None:
        """
        Get cover art URL directly from a MusicBrainz ID.

        Convenience method that combines lookup and cover URL retrieval.

        Args:
            mbid: MusicBrainz release ID

        Returns:
            Cover art URL if available, None otherwise
        """
        if not mbid:
            return None

        # No rate limit for Cover Art Archive (hosted by Internet Archive)
        logger.info(f"Direct cover lookup for MBID: {mbid}")

        try:
            with handle_network_errors("Cover Art Archive"):
                response = self._session.get(
                    f"{COVERART_API}/release/{mbid}", allow_redirects=True, timeout=HTTP_TIMEOUT
                )

                if response.status_code == 404:
                    logger.debug(f"No cover art for MBID: {mbid}")
                    return None

                response.raise_for_status()

            data = response.json()

            # Look for front cover first
            for image in data.get("images", []):
                if image.get("front", False):
                    thumbnails = image.get("thumbnails", {})
                    url = (
                        thumbnails.get("large")
                        or thumbnails.get("500")
                        or thumbnails.get("250")
                        or image.get("image")
                    )
                    if url:
                        logger.info(f"Found cover art for MBID {mbid}")
                        return url

            # Fall back to first image
            if data.get("images"):
                image = data["images"][0]
                thumbnails = image.get("thumbnails", {})
                url = thumbnails.get("large") or image.get("image")
                if url:
                    logger.info(f"Found cover art (fallback) for MBID {mbid}")
                    return url

            return None
        except (KeyError, ValueError) as e:
            logger.debug(f"Cover Art Archive parsing error for {mbid}: {e}")
            return None

    def get_thumbnail_url(self, result: SearchResult) -> str | None:
        """
        Get thumbnail URL for quick preview.

        Args:
            result: SearchResult with MusicBrainz ID

        Returns:
            Thumbnail URL if available, None otherwise
        """
        if not result.mbid:
            return None

        # No rate limit for Cover Art Archive (hosted by Internet Archive)

        try:
            with handle_network_errors("Cover Art Archive"):
                response = self._session.get(
                    f"{COVERART_API}/release/{result.mbid}",
                    allow_redirects=True,
                    timeout=HTTP_TIMEOUT,
                )

                if response.status_code == 404:
                    return None

                response.raise_for_status()

            data = response.json()

            for image in data.get("images", []):
                if image.get("front", False):
                    thumbnails = image.get("thumbnails", {})
                    return (
                        thumbnails.get("250") or thumbnails.get("small") or thumbnails.get("large")
                    )

            if data.get("images"):
                thumbnails = data["images"][0].get("thumbnails", {})
                return thumbnails.get("250") or thumbnails.get("small")

            return None
        except (KeyError, ValueError) as e:
            logger.debug(f"Error getting thumbnail URL for {result.mbid}: {e}")
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

        with handle_network_errors("Cover Art Archive"):
            response = self._session.get(url, timeout=HTTP_TIMEOUT)
            # A 404 means the cover doesn't exist - not a network error
            if response.status_code == 404:
                logger.debug(f"Cover not found (404): {url}")
                return None
            response.raise_for_status()
            return response.content

    def check_has_cover_art(self, mbid: str) -> bool:
        """
        Quick check if a release has cover art available.

        Args:
            mbid: MusicBrainz release ID

        Returns:
            True if cover art is available
        """
        # No rate limit for Cover Art Archive (hosted by Internet Archive)

        try:
            with handle_network_errors("Cover Art Archive"):
                response = self._session.head(
                    f"{COVERART_API}/release/{mbid}/front",
                    allow_redirects=True,
                    timeout=HTTP_TIMEOUT,
                )
                return response.status_code == 200
        except Exception:
            # For check methods, we return False on any error (network or otherwise)
            # rather than propagating the exception
            return False

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

    def calculate_match_score(
        self, artist: str, album: str, year: str | None, result: SearchResult
    ) -> int:
        """
        Calculate how well a search result matches the query.

        Args:
            artist: Query artist name
            album: Query album name
            year: Query year
            result: Search result to score

        Returns:
            Match score 0-100
        """
        score = 0

        # Normalize strings for comparison
        def normalize(s: str) -> str:
            return s.lower().strip() if s else ""

        q_artist = normalize(artist)
        q_album = normalize(album)
        r_artist = normalize(result.artist)
        r_album = normalize(result.album)

        # Artist match (40 points max)
        if q_artist and r_artist:
            if q_artist == r_artist:
                score += 40
            elif q_artist in r_artist or r_artist in q_artist:
                score += 25

        # Album match (40 points max)
        if q_album and r_album:
            if q_album == r_album:
                score += 40
            elif q_album in r_album or r_album in q_album:
                score += 25

        # Year match (20 points max)
        if year and result.year and year[:4] == result.year[:4]:
            score += 20

        return min(100, score)
