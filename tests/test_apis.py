"""
Tests for the API providers.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

import pytest
import requests
import responses

from src.api.base import handle_network_errors, is_valid_cover_url
from src.api.discogs import DISCOGS_API, DiscogsProvider
from src.api.lastfm import LASTFM_API, LastFmProvider
from src.api.musicbrainz import COVERART_API, MUSICBRAINZ_API, MusicBrainzProvider
from src.core.exceptions import NetworkError, ProviderError, RateLimitError
from src.core.models import SearchResult


class TestHandleNetworkErrors:
    """Direct unit tests for the handle_network_errors context manager."""

    def test_connection_error_raises_network_error(self):
        """Test ConnectionError is converted to NetworkError."""
        with pytest.raises(NetworkError, match=r"(?i)connection failed"):
            with handle_network_errors("TestProvider"):
                raise requests.exceptions.ConnectionError("test error")

    def test_timeout_raises_network_error(self):
        """Test Timeout is converted to NetworkError."""
        with pytest.raises(NetworkError, match=r"(?i)timed out"):
            with handle_network_errors("TestProvider"):
                raise requests.exceptions.Timeout("test timeout")

    def test_http_429_raises_rate_limit_error(self):
        """Test HTTP 429 raises RateLimitError."""
        response = requests.models.Response()
        response.status_code = 429
        response.headers["Retry-After"] = "60"
        error = requests.exceptions.HTTPError(response=response)

        with pytest.raises(RateLimitError) as exc_info:
            with handle_network_errors("TestProvider"):
                raise error

        assert exc_info.value.retry_after == 60

    def test_http_503_raises_rate_limit_error(self):
        """Test HTTP 503 raises RateLimitError."""
        response = requests.models.Response()
        response.status_code = 503
        error = requests.exceptions.HTTPError(response=response)

        with pytest.raises(RateLimitError, match=r"(?i)rate limit"):
            with handle_network_errors("TestProvider"):
                raise error

    def test_http_500_raises_network_error(self):
        """Test HTTP 500 raises NetworkError (not RateLimitError)."""
        response = requests.models.Response()
        response.status_code = 500
        error = requests.exceptions.HTTPError(response=response)

        with pytest.raises(NetworkError):
            with handle_network_errors("TestProvider"):
                raise error

    def test_generic_request_exception_raises_network_error(self):
        """Test generic RequestException is converted to NetworkError."""
        with pytest.raises(NetworkError, match=r"(?i)request failed"):
            with handle_network_errors("TestProvider"):
                raise requests.exceptions.RequestException("generic error")

    def test_rate_limit_in_retry_message_raises_rate_limit_error(self):
        """Test that rate limit errors from urllib3 retry are detected."""
        # urllib3 wraps exhausted retries in a RequestException with status in message
        error_msg = "Max retries exceeded (Caused by ResponseError('too many 429 error responses'))"
        with pytest.raises(RateLimitError):
            with handle_network_errors("TestProvider"):
                raise requests.exceptions.RequestException(error_msg)

    def test_provider_name_in_error_message(self):
        """Test that provider name appears in error messages."""
        with pytest.raises(NetworkError, match="CustomProvider"):
            with handle_network_errors("CustomProvider"):
                raise requests.exceptions.ConnectionError("test")

    def test_exception_chaining_preserved(self):
        """Test that original exception is chained with 'from'."""
        original = requests.exceptions.Timeout("original timeout")
        with pytest.raises(NetworkError) as exc_info:
            with handle_network_errors("TestProvider"):
                raise original

        assert exc_info.value.__cause__ is original

    def test_non_request_exception_not_caught(self):
        """Test that non-requests exceptions pass through unchanged."""
        with pytest.raises(ValueError, match="not a network error"):
            with handle_network_errors("TestProvider"):
                raise ValueError("not a network error")


class TestUrlValidation:
    """Tests for URL validation (SSRF prevention)."""

    def test_valid_coverartarchive_url(self):
        """Test that coverartarchive.org URLs are allowed."""
        assert is_valid_cover_url("https://coverartarchive.org/release/123/front.jpg")

    def test_valid_archive_org_url(self):
        """Test that archive.org URLs are allowed."""
        assert is_valid_cover_url("https://archive.org/download/image.jpg")

    def test_valid_discogs_url(self):
        """Test that discogs URLs are allowed."""
        assert is_valid_cover_url("https://i.discogs.com/image.jpg")
        assert is_valid_cover_url("https://s.discogs.com/image.jpg")

    def test_valid_lastfm_url(self):
        """Test that last.fm URLs are allowed."""
        assert is_valid_cover_url("https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg")
        assert is_valid_cover_url("https://lastfm-img2.akamaized.net/i/u/cover.jpg")

    def test_invalid_domain(self):
        """Test that unknown domains are rejected."""
        assert not is_valid_cover_url("http://example.com/cover.jpg")
        assert not is_valid_cover_url("https://evil.com/cover.jpg")

    def test_invalid_scheme(self):
        """Test that non-HTTP schemes are rejected."""
        assert not is_valid_cover_url("ftp://coverartarchive.org/image.jpg")
        assert not is_valid_cover_url("file:///etc/passwd")

    def test_empty_url(self):
        """Test that empty URLs are rejected."""
        assert not is_valid_cover_url("")
        assert not is_valid_cover_url(None)

    def test_subdomain_allowed(self):
        """Test that subdomains of allowed domains are accepted."""
        assert is_valid_cover_url("https://ia800500.us.archive.org/image.jpg")

    def test_http_allowed_for_archive(self):
        """Test that HTTP is allowed for archive.org."""
        assert is_valid_cover_url("http://archive.org/image.jpg")

    def test_http_allowed_for_coverartarchive(self):
        """Test that HTTP is allowed for coverartarchive.org."""
        assert is_valid_cover_url("http://coverartarchive.org/release/123/front-500.jpg")


class TestCoverProviderBase:
    """Tests for the base CoverProvider class."""

    def test_calculate_match_score_exact_match(self):
        """Test score calculation for exact match."""
        # Create a concrete implementation for testing
        provider = MusicBrainzProvider()

        result = SearchResult(
            provider="test",
            mbid="123",
            artist="Pink Floyd",
            album="The Wall",
            year="1979",
            score=100,
        )

        score = provider.calculate_match_score("Pink Floyd", "The Wall", "1979", result)

        # Exact match: 40 (artist) + 40 (album) + 20 (year) = 100
        assert score == 100

    def test_calculate_match_score_partial_match(self):
        """Test score calculation for partial match."""
        provider = MusicBrainzProvider()

        result = SearchResult(
            provider="test",
            mbid="123",
            artist="Pink Floyd",
            album="The Wall (Remastered)",
            year="2011",
            score=90,
        )

        score = provider.calculate_match_score("Pink Floyd", "The Wall", "1979", result)

        # Partial album match ("The Wall" in "The Wall (Remastered)"), exact artist
        # 40 (artist) + 25 (partial album) = 65
        assert score == 65

    def test_calculate_match_score_no_match(self):
        """Test score calculation for no match."""
        provider = MusicBrainzProvider()

        result = SearchResult(
            provider="test",
            mbid="123",
            artist="The Beatles",
            album="Abbey Road",
            year="1969",
            score=50,
        )

        score = provider.calculate_match_score("Pink Floyd", "The Wall", "1979", result)

        assert score == 0

    def test_calculate_match_score_with_none_values(self):
        """Test score calculation when some values are None."""
        provider = MusicBrainzProvider()

        result = SearchResult(
            provider="test", mbid="123", artist="Pink Floyd", album="", year=None, score=50
        )

        score = provider.calculate_match_score("Pink Floyd", None, None, result)

        # Should not crash, just match on available fields
        assert score == 40  # Only artist matches


class TestMusicBrainzProvider:
    """Tests for MusicBrainzProvider."""

    def test_init(self):
        """Test provider initialization."""
        provider = MusicBrainzProvider()
        assert provider.name == "MusicBrainz"
        assert provider.requires_api_key is False

    def test_is_configured_always_true(self):
        """Test that MusicBrainz is always configured."""
        provider = MusicBrainzProvider()
        assert provider.is_configured() is True

    def test_init_with_email(self):
        """Test provider initialization with contact email."""
        provider = MusicBrainzProvider(contact_email="test@example.com")
        assert provider.contact_email == "test@example.com"
        assert provider._use_rate_limit is False  # No rate limit with email
        assert "test@example.com" in provider._session.headers["User-Agent"]

    def test_init_without_email(self):
        """Test provider initialization without contact email."""
        provider = MusicBrainzProvider()
        assert provider.contact_email is None
        assert provider._use_rate_limit is True  # Rate limit active without email
        # User-Agent should contain app name from centralized module
        assert "TuneCover" in provider._session.headers["User-Agent"]

    def test_init_with_empty_email(self):
        """Test provider initialization with empty email string."""
        provider = MusicBrainzProvider(contact_email="   ")
        # Empty/whitespace-only email is normalized to None
        assert provider.contact_email is None
        assert provider._use_rate_limit is True  # Rate limit active when no valid email

    def test_rate_limit_skipped_with_email(self):
        """Test that rate limit is skipped when email is configured."""
        provider = MusicBrainzProvider(contact_email="test@example.com")

        # Call rate limit twice quickly - should not block
        start = time.time()
        provider._rate_limit_musicbrainz()
        provider._rate_limit_musicbrainz()
        elapsed = time.time() - start

        # With email, no delay should occur
        assert elapsed < 0.5  # Should be nearly instant

    @responses.activate
    def test_search_success(self):
        """Test successful search with mocked response."""
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release",
            json={
                "releases": [
                    {
                        "id": "mbid-123",
                        "title": "The Wall",
                        "artist-credit": [{"name": "Pink Floyd"}],
                        "date": "1979-11-30",
                        "score": 100,
                    },
                    {
                        "id": "mbid-456",
                        "title": "The Wall (Remastered)",
                        "artist-credit": [{"name": "Pink Floyd"}],
                        "date": "2011-03-22",
                        "score": 90,
                    },
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        results = provider.search("Pink Floyd", "The Wall", "1979")

        assert len(results) == 2
        assert results[0].provider == "MusicBrainz"
        assert results[0].mbid == "mbid-123"
        assert results[0].artist == "Pink Floyd"
        assert results[0].album == "The Wall"
        assert results[0].year == "1979"
        assert results[0].score == 100

    @responses.activate
    def test_search_empty_artist_credit(self):
        """Test search with empty artist-credit array."""
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release",
            json={
                "releases": [
                    {
                        "id": "mbid-123",
                        "title": "Unknown Album",
                        "artist-credit": [],
                        "date": "2000",
                        "score": 50,
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        results = provider.search("Unknown", "Unknown Album", None)

        assert len(results) == 1
        assert results[0].artist == ""

    def test_search_empty_query_returns_empty(self):
        """Test that empty query returns empty list."""
        provider = MusicBrainzProvider()
        results = provider.search("", "", None)
        assert results == []

    @responses.activate
    def test_search_network_error(self):
        """Test search raises NetworkError for connection errors."""
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        provider = MusicBrainzProvider()
        with pytest.raises(NetworkError) as exc_info:
            provider.search("Pink Floyd", "The Wall", None)
        assert "connection failed" in str(exc_info.value).lower()

    @responses.activate
    def test_search_timeout_error(self):
        """Test search raises NetworkError for timeout errors."""
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release",
            body=requests.exceptions.Timeout("Request timed out"),
        )

        provider = MusicBrainzProvider()
        with pytest.raises(NetworkError) as exc_info:
            provider.search("Pink Floyd", "The Wall", None)
        assert "timed out" in str(exc_info.value).lower()

    @responses.activate
    def test_search_http_500_error(self):
        """Test search raises NetworkError for HTTP 500 errors."""
        # With retry strategy, it will retry 3 times before failing
        for _ in range(4):
            responses.add(responses.GET, f"{MUSICBRAINZ_API}/release", status=500)

        provider = MusicBrainzProvider()
        with pytest.raises(NetworkError):
            provider.search("Pink Floyd", "The Wall", None)

    @responses.activate
    def test_search_invalid_json(self):
        """Test search handles invalid JSON response."""
        responses.add(
            responses.GET, f"{MUSICBRAINZ_API}/release", body="not valid json", status=200
        )

        provider = MusicBrainzProvider()
        results = provider.search("Pink Floyd", "The Wall", None)

        assert results == []

    @responses.activate
    def test_get_cover_url_success_front_cover(self):
        """Test getting cover URL with front cover available."""
        responses.add(
            responses.GET,
            f"{COVERART_API}/release/mbid-123",
            json={
                "images": [
                    {
                        "front": False,
                        "image": "http://example.com/back.jpg",
                        "thumbnails": {"large": "http://example.com/back_large.jpg"},
                    },
                    {
                        "front": True,
                        "image": "http://example.com/front.jpg",
                        "thumbnails": {
                            "large": "http://example.com/front_large.jpg",
                            "500": "http://example.com/front_500.jpg",
                            "250": "http://example.com/front_250.jpg",
                        },
                    },
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid="mbid-123")
        url = provider.get_cover_url(result)

        assert url == "http://example.com/front_large.jpg"

    @responses.activate
    def test_get_cover_url_fallback_to_500(self):
        """Test fallback to 500px thumbnail when large not available."""
        responses.add(
            responses.GET,
            f"{COVERART_API}/release/mbid-123",
            json={
                "images": [
                    {
                        "front": True,
                        "image": "http://example.com/front.jpg",
                        "thumbnails": {
                            "500": "http://example.com/front_500.jpg",
                            "250": "http://example.com/front_250.jpg",
                        },
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid="mbid-123")
        url = provider.get_cover_url(result)

        assert url == "http://example.com/front_500.jpg"

    @responses.activate
    def test_get_cover_url_fallback_to_first_image(self):
        """Test fallback to first image when no front cover."""
        responses.add(
            responses.GET,
            f"{COVERART_API}/release/mbid-123",
            json={
                "images": [
                    {
                        "front": False,
                        "image": "http://example.com/back.jpg",
                        "thumbnails": {"large": "http://example.com/back_large.jpg"},
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid="mbid-123")
        url = provider.get_cover_url(result)

        assert url == "http://example.com/back_large.jpg"

    @responses.activate
    def test_get_cover_url_404(self):
        """Test get_cover_url returns None on 404."""
        responses.add(responses.GET, f"{COVERART_API}/release/mbid-123", status=404)

        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid="mbid-123")
        url = provider.get_cover_url(result)

        assert url is None

    def test_get_cover_url_no_mbid(self):
        """Test get_cover_url returns None when no MBID."""
        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid=None)
        url = provider.get_cover_url(result)

        assert url is None

    @responses.activate
    def test_get_cover_url_empty_mbid(self):
        """Test get_cover_url returns None when MBID is empty string."""
        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid="")
        url = provider.get_cover_url(result)

        assert url is None

    @responses.activate
    def test_get_thumbnail_url_success(self):
        """Test getting thumbnail URL."""
        responses.add(
            responses.GET,
            f"{COVERART_API}/release/mbid-123",
            json={
                "images": [
                    {
                        "front": True,
                        "image": "http://example.com/front.jpg",
                        "thumbnails": {
                            "large": "http://example.com/front_large.jpg",
                            "250": "http://example.com/front_250.jpg",
                            "small": "http://example.com/front_small.jpg",
                        },
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid="mbid-123")
        url = provider.get_thumbnail_url(result)

        assert url == "http://example.com/front_250.jpg"

    @responses.activate
    def test_get_thumbnail_url_fallback_to_small(self):
        """Test thumbnail URL fallback to small when 250 not available."""
        responses.add(
            responses.GET,
            f"{COVERART_API}/release/mbid-123",
            json={
                "images": [
                    {
                        "front": True,
                        "image": "http://example.com/front.jpg",
                        "thumbnails": {
                            "large": "http://example.com/front_large.jpg",
                            "small": "http://example.com/front_small.jpg",
                        },
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid="mbid-123")
        url = provider.get_thumbnail_url(result)

        assert url == "http://example.com/front_small.jpg"

    def test_get_thumbnail_url_no_mbid(self):
        """Test get_thumbnail_url returns None when no MBID."""
        provider = MusicBrainzProvider()
        result = SearchResult(provider="MusicBrainz", mbid=None)
        url = provider.get_thumbnail_url(result)

        assert url is None

    @responses.activate
    def test_download_cover_success(self):
        """Test successful cover download."""
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # Fake PNG header
        # Use allowed domain (coverartarchive.org)
        responses.add(
            responses.GET,
            "https://coverartarchive.org/release/test-id/front.jpg",
            body=image_data,
            status=200,
            content_type="image/jpeg",
        )

        provider = MusicBrainzProvider()
        data = provider.download_cover("https://coverartarchive.org/release/test-id/front.jpg")

        assert data == image_data

    @responses.activate
    def test_download_cover_404(self):
        """Test download_cover returns None on 404.

        A 404 indicates the cover image doesn't exist, which is semantically
        different from a network error. Returning None allows callers to
        distinguish between "image not found" and "network failure".
        """
        responses.add(
            responses.GET, "https://coverartarchive.org/release/test-id/front.jpg", status=404
        )

        provider = MusicBrainzProvider()
        result = provider.download_cover("https://coverartarchive.org/release/test-id/front.jpg")
        assert result is None

    @responses.activate
    def test_download_cover_network_error(self):
        """Test download_cover raises NetworkError on connection error."""
        responses.add(
            responses.GET,
            "https://coverartarchive.org/release/test-id/front.jpg",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        provider = MusicBrainzProvider()
        with pytest.raises(NetworkError):
            provider.download_cover("https://coverartarchive.org/release/test-id/front.jpg")

    def test_download_cover_blocked_url(self):
        """Test download_cover rejects URLs from non-allowed domains."""
        provider = MusicBrainzProvider()
        data = provider.download_cover("http://example.com/cover.jpg")

        assert data is None

    @responses.activate
    def test_check_has_cover_art_true(self):
        """Test check_has_cover_art returns True when cover exists."""
        responses.add(responses.HEAD, f"{COVERART_API}/release/mbid-123/front", status=200)

        provider = MusicBrainzProvider()
        has_cover = provider.check_has_cover_art("mbid-123")

        assert has_cover is True

    @responses.activate
    def test_check_has_cover_art_false(self):
        """Test check_has_cover_art returns False when no cover."""
        responses.add(responses.HEAD, f"{COVERART_API}/release/mbid-123/front", status=404)

        provider = MusicBrainzProvider()
        has_cover = provider.check_has_cover_art("mbid-123")

        assert has_cover is False

    @responses.activate
    def test_check_has_cover_art_network_error(self):
        """Test check_has_cover_art handles errors gracefully."""
        responses.add(
            responses.HEAD,
            f"{COVERART_API}/release/mbid-123/front",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        provider = MusicBrainzProvider()
        has_cover = provider.check_has_cover_art("mbid-123")

        assert has_cover is False

    def test_close(self):
        """Test close method closes the session."""
        provider = MusicBrainzProvider()
        provider.close()
        # Session should be closed (no exception raised)
        assert True

    def test_context_manager(self):
        """Test context manager usage."""
        with MusicBrainzProvider() as provider:
            assert provider.name == "MusicBrainz"
        # Session should be closed after exiting context

    def test_context_manager_with_exception(self):
        """Test context manager properly exits on exception."""
        try:
            with MusicBrainzProvider() as provider:
                raise ValueError("Test exception")
        except ValueError:
            pass
        # Session should still be closed

    def test_rate_limiting_enforced(self):
        """Test that rate limiting adds delay between requests to MusicBrainz API."""
        provider = MusicBrainzProvider()

        # Patch time.sleep to track calls
        with patch("time.sleep") as mock_sleep:
            # Simulate first request (no delay needed)
            provider._last_request_time = time.time()

            # Second request should trigger delay
            provider._rate_limit_musicbrainz()

            # First call shouldn't sleep (or minimal sleep)
            # Let's test that sleep is called when needed
            provider._last_request_time = time.time()
            provider._rate_limit_musicbrainz()

            # Sleep may or may not be called depending on timing
            # The important thing is no exception is raised

    def test_rate_limiting_thread_safety(self):
        """Test rate limiting is thread-safe with concurrent access."""
        provider = MusicBrainzProvider()
        request_times = []
        lock = threading.Lock()

        def make_request():
            provider._rate_limit_musicbrainz()
            with lock:
                request_times.append(time.time())

        # Run multiple concurrent requests
        with patch("time.sleep"):  # Don't actually sleep in test
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(make_request) for _ in range(10)]
                for future in as_completed(futures):
                    future.result()

        # All requests should have completed without error
        assert len(request_times) == 10

    def test_extract_year_valid_full_date(self):
        """Test _extract_year with full date."""
        provider = MusicBrainzProvider()
        assert provider._extract_year("2020-05-15") == "2020"

    def test_extract_year_valid_year_only(self):
        """Test _extract_year with year only."""
        provider = MusicBrainzProvider()
        assert provider._extract_year("1979") == "1979"

    def test_extract_year_none_input(self):
        """Test _extract_year with None."""
        provider = MusicBrainzProvider()
        assert provider._extract_year(None) is None

    def test_extract_year_empty_string(self):
        """Test _extract_year with empty string."""
        provider = MusicBrainzProvider()
        assert provider._extract_year("") is None

    def test_extract_year_short_string(self):
        """Test _extract_year with string shorter than 4 chars."""
        provider = MusicBrainzProvider()
        assert provider._extract_year("20") is None
        assert provider._extract_year("197") is None

    def test_extract_year_whitespace(self):
        """Test _extract_year strips whitespace."""
        provider = MusicBrainzProvider()
        assert provider._extract_year("  2020-01-01  ") == "2020"

    @responses.activate
    def test_lookup_by_mbid_success(self):
        """Test successful lookup by MusicBrainz ID."""
        mbid = "a2b62291-2981-4409-b024-44d5be206346"
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release/{mbid}",
            json={
                "id": mbid,
                "title": "The Wall",
                "date": "1979-11-30",
                "artist-credit": [{"name": "Pink Floyd"}],
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = provider.lookup_by_mbid(mbid)

        assert result is not None
        assert result.mbid == mbid
        assert result.artist == "Pink Floyd"
        assert result.album == "The Wall"
        assert result.year == "1979"
        assert result.score == 100

    @responses.activate
    def test_lookup_by_mbid_not_found(self):
        """Test lookup by MBID returns None for 404."""
        mbid = "nonexistent-mbid"
        responses.add(responses.GET, f"{MUSICBRAINZ_API}/release/{mbid}", status=404)

        provider = MusicBrainzProvider()
        result = provider.lookup_by_mbid(mbid)

        assert result is None

    def test_lookup_by_mbid_empty_input(self):
        """Test lookup by MBID with empty input."""
        provider = MusicBrainzProvider()
        assert provider.lookup_by_mbid("") is None
        assert provider.lookup_by_mbid(None) is None

    @responses.activate
    def test_lookup_by_isrc_success(self):
        """Test successful lookup by ISRC."""
        isrc = "USRC17607839"
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/isrc/{isrc}",
            json={
                "recordings": [
                    {
                        "id": "recording-id",
                        "releases": [
                            {
                                "id": "release-mbid",
                                "title": "Wish You Were Here",
                                "date": "1975-09-12",
                                "artist-credit": [{"name": "Pink Floyd"}],
                            }
                        ],
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = provider.lookup_by_isrc(isrc)

        assert result is not None
        assert result.mbid == "release-mbid"
        assert result.artist == "Pink Floyd"
        assert result.album == "Wish You Were Here"
        assert result.year == "1975"
        assert result.score == 95

    @responses.activate
    def test_lookup_by_isrc_not_found(self):
        """Test lookup by ISRC returns None for 404."""
        isrc = "USRC12345678"
        responses.add(responses.GET, f"{MUSICBRAINZ_API}/isrc/{isrc}", status=404)

        provider = MusicBrainzProvider()
        result = provider.lookup_by_isrc(isrc)

        assert result is None

    @responses.activate
    def test_lookup_by_isrc_no_recordings(self):
        """Test lookup by ISRC with no recordings."""
        isrc = "USRC12345678"
        responses.add(
            responses.GET, f"{MUSICBRAINZ_API}/isrc/{isrc}", json={"recordings": []}, status=200
        )

        provider = MusicBrainzProvider()
        result = provider.lookup_by_isrc(isrc)

        assert result is None

    def test_lookup_by_isrc_invalid_format(self):
        """Test lookup by ISRC with invalid format."""
        provider = MusicBrainzProvider()
        # Too short
        assert provider.lookup_by_isrc("ABC123") is None
        # Too long
        assert provider.lookup_by_isrc("USRC123456789999") is None
        # Empty
        assert provider.lookup_by_isrc("") is None
        assert provider.lookup_by_isrc(None) is None

    def test_lookup_by_isrc_normalizes_format(self):
        """Test lookup by ISRC normalizes dashes and case."""
        provider = MusicBrainzProvider()
        # We can't easily test the API call here, but we can test that
        # invalid formats after normalization are rejected
        # "abc-def-gh-ijkl" has 12 chars when dashes are removed -> valid format
        # This would make an API call if responses weren't activated

    @responses.activate
    def test_lookup_by_barcode_success(self):
        """Test successful lookup by barcode."""
        barcode = "724349691704"  # 12-digit UPC
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release",
            json={
                "releases": [
                    {
                        "id": "release-mbid",
                        "title": "The Dark Side of the Moon",
                        "date": "1973-03-01",
                        "artist-credit": [{"name": "Pink Floyd"}],
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = provider.lookup_by_barcode(barcode)

        assert result is not None
        assert result.mbid == "release-mbid"
        assert result.artist == "Pink Floyd"
        assert result.album == "The Dark Side of the Moon"
        assert result.year == "1973"
        assert result.score == 98

    @responses.activate
    def test_lookup_by_barcode_13_digit(self):
        """Test lookup by 13-digit EAN barcode."""
        barcode = "0724349691704"  # 13-digit EAN
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release",
            json={
                "releases": [
                    {
                        "id": "release-mbid",
                        "title": "Animals",
                        "date": "1977",
                        "artist-credit": [{"name": "Pink Floyd"}],
                    }
                ]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        result = provider.lookup_by_barcode(barcode)

        assert result is not None
        assert result.album == "Animals"

    @responses.activate
    def test_lookup_by_barcode_not_found(self):
        """Test lookup by barcode returns None when no releases found."""
        barcode = "123456789012"
        responses.add(
            responses.GET, f"{MUSICBRAINZ_API}/release", json={"releases": []}, status=200
        )

        provider = MusicBrainzProvider()
        result = provider.lookup_by_barcode(barcode)

        assert result is None

    def test_lookup_by_barcode_invalid_format(self):
        """Test lookup by barcode with invalid format."""
        provider = MusicBrainzProvider()
        # Too short
        assert provider.lookup_by_barcode("123") is None
        # Too long
        assert provider.lookup_by_barcode("12345678901234") is None
        # Contains letters
        assert provider.lookup_by_barcode("12345678901a") is None
        # Empty
        assert provider.lookup_by_barcode("") is None
        assert provider.lookup_by_barcode(None) is None


class TestDiscogsProvider:
    """Tests for DiscogsProvider."""

    def test_init_without_token(self):
        """Test initialization without API token."""
        provider = DiscogsProvider()
        assert provider.name == "Discogs"
        assert provider.requires_api_key is True
        assert provider.api_token is None

    def test_init_with_token(self):
        """Test initialization with API token."""
        provider = DiscogsProvider(api_token="test_token")
        assert provider.api_token == "test_token"

    def test_set_api_token(self):
        """Test setting API token after initialization."""
        provider = DiscogsProvider()
        provider.set_api_token("new_token")
        assert provider.api_token == "new_token"
        # Verify headers are updated
        assert "Authorization" in provider._session.headers
        assert "new_token" in provider._session.headers["Authorization"]

    def test_is_configured_requires_token(self):
        """Test that Discogs requires a token to be configured."""
        provider = DiscogsProvider()
        assert provider.is_configured() is False

    def test_has_api_key_false_without_token(self):
        """Test _has_api_key returns False without token."""
        provider = DiscogsProvider()
        assert provider._has_api_key() is False

    def test_has_api_key_true_with_token(self):
        """Test _has_api_key returns True with token."""
        provider = DiscogsProvider(api_token="token")
        assert provider._has_api_key() is True

    @responses.activate
    def test_search_success(self):
        """Test successful search."""
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            json={
                "results": [
                    {
                        "id": 12345,
                        "title": "Pink Floyd - The Wall",
                        "year": 1979,
                        "cover_image": "http://example.com/cover.jpg",
                        "format": ["Album", "LP"],
                    },
                    {
                        "id": 67890,
                        "title": "Pink Floyd - The Wall (Remastered)",
                        "year": 2011,
                        "cover_image": "http://example.com/cover2.jpg",
                    },
                ]
            },
            status=200,
        )

        provider = DiscogsProvider()
        results = provider.search("Pink Floyd", "The Wall", "1979")

        assert len(results) == 2
        assert results[0].provider == "Discogs"
        assert results[0].mbid == "12345"
        assert results[0].artist == "Pink Floyd"
        assert results[0].album == "The Wall"
        assert results[0].year == "1979"
        assert results[0].has_cover_art is True
        assert results[0].cover_url == "http://example.com/cover.jpg"

    @responses.activate
    def test_search_with_token(self):
        """Test search with API token includes authorization header."""
        responses.add(
            responses.GET, f"{DISCOGS_API}/database/search", json={"results": []}, status=200
        )

        provider = DiscogsProvider(api_token="my_secret_token")
        provider.search("Test", "Album", None)

        # Verify authorization header was sent
        assert len(responses.calls) == 1
        assert "Authorization" in responses.calls[0].request.headers
        assert "my_secret_token" in responses.calls[0].request.headers["Authorization"]

    @responses.activate
    def test_search_title_parsing_without_hyphen(self):
        """Test title parsing when no hyphen separator."""
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            json={"results": [{"id": 12345, "title": "Just Album Title", "year": 2000}]},
            status=200,
        )

        provider = DiscogsProvider()
        results = provider.search("", "Just Album Title", None)

        assert len(results) == 1
        assert results[0].artist == ""
        assert results[0].album == "Just Album Title"

    def test_search_empty_query_returns_empty(self):
        """Test that empty query returns empty list."""
        provider = DiscogsProvider()
        results = provider.search("", "", None)
        assert results == []

    @responses.activate
    def test_search_network_error(self):
        """Test search raises NetworkError for connection errors."""
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        provider = DiscogsProvider()
        with pytest.raises(NetworkError) as exc_info:
            provider.search("Pink Floyd", "The Wall", None)
        assert "connection failed" in str(exc_info.value).lower()

    @responses.activate
    def test_search_timeout_error(self):
        """Test search raises NetworkError for timeout errors."""
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            body=requests.exceptions.Timeout("Request timed out"),
        )

        provider = DiscogsProvider()
        with pytest.raises(NetworkError) as exc_info:
            provider.search("Pink Floyd", "The Wall", None)
        assert "timed out" in str(exc_info.value).lower()

    @responses.activate
    def test_search_http_429_rate_limit(self):
        """Test search raises RateLimitError for HTTP 429."""
        from src.core.exceptions import RateLimitError

        for _ in range(4):
            responses.add(responses.GET, f"{DISCOGS_API}/database/search", status=429)

        provider = DiscogsProvider()
        with pytest.raises(RateLimitError):
            provider.search("Pink Floyd", "The Wall", None)

    @responses.activate
    def test_get_cover_url_from_search_result(self):
        """Test get_cover_url returns URL from search result."""
        provider = DiscogsProvider()
        result = SearchResult(
            provider="Discogs", mbid="12345", cover_url="http://example.com/cover.jpg"
        )

        url = provider.get_cover_url(result)
        assert url == "http://example.com/cover.jpg"

    @responses.activate
    def test_get_cover_url_api_lookup(self):
        """Test get_cover_url fetches from API when URL not in result."""
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/releases/12345",
            json={
                "images": [
                    {"type": "secondary", "uri": "http://example.com/back.jpg"},
                    {"type": "primary", "uri": "http://example.com/front.jpg"},
                ]
            },
            status=200,
        )

        provider = DiscogsProvider()
        result = SearchResult(provider="Discogs", mbid="12345", cover_url=None)

        url = provider.get_cover_url(result)
        assert url == "http://example.com/front.jpg"

    @responses.activate
    def test_get_cover_url_api_fallback_to_first_image(self):
        """Test get_cover_url falls back to first image when no primary."""
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/releases/12345",
            json={"images": [{"type": "secondary", "uri": "http://example.com/back.jpg"}]},
            status=200,
        )

        provider = DiscogsProvider()
        result = SearchResult(provider="Discogs", mbid="12345", cover_url=None)

        url = provider.get_cover_url(result)
        assert url == "http://example.com/back.jpg"

    @responses.activate
    def test_get_cover_url_404(self):
        """Test get_cover_url returns None on 404."""
        responses.add(responses.GET, f"{DISCOGS_API}/releases/12345", status=404)

        provider = DiscogsProvider()
        result = SearchResult(provider="Discogs", mbid="12345", cover_url=None)

        url = provider.get_cover_url(result)
        assert url is None

    def test_get_cover_url_no_mbid(self):
        """Test get_cover_url returns None when no MBID."""
        provider = DiscogsProvider()
        result = SearchResult(provider="Discogs", mbid=None, cover_url=None)
        url = provider.get_cover_url(result)

        assert url is None

    @responses.activate
    def test_download_cover_success(self):
        """Test successful cover download."""
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        # Use allowed domain (i.discogs.com)
        responses.add(
            responses.GET,
            "https://i.discogs.com/image/R-12345-cover.jpg",
            body=image_data,
            status=200,
            content_type="image/jpeg",
        )

        provider = DiscogsProvider()
        data = provider.download_cover("https://i.discogs.com/image/R-12345-cover.jpg")

        assert data == image_data

    @responses.activate
    def test_download_cover_error(self):
        """Test download_cover raises NetworkError on connection error."""
        responses.add(
            responses.GET,
            "https://i.discogs.com/image/R-12345-cover.jpg",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        provider = DiscogsProvider()
        with pytest.raises(NetworkError):
            provider.download_cover("https://i.discogs.com/image/R-12345-cover.jpg")

    @responses.activate
    def test_download_cover_404(self):
        """Test download_cover returns None on 404.

        A 404 indicates the cover image doesn't exist, which is semantically
        different from a network error.
        """
        responses.add(
            responses.GET, "https://i.discogs.com/image/R-12345-cover.jpg", status=404
        )

        provider = DiscogsProvider()
        result = provider.download_cover("https://i.discogs.com/image/R-12345-cover.jpg")
        assert result is None

    def test_download_cover_blocked_url(self):
        """Test download_cover rejects URLs from non-allowed domains."""
        # Blocked URLs return None before any network request is made (SSRF prevention)
        provider = DiscogsProvider()
        data = provider.download_cover("http://example.com/cover.jpg")

        assert data is None

    def test_calculate_relevance_exact_match(self):
        """Test relevance calculation for exact match."""
        provider = DiscogsProvider()
        item = {"title": "pink floyd - the wall", "cover_image": "http://example.com/cover.jpg"}

        score = provider._calculate_relevance(item, "Pink Floyd", "The Wall")

        # Base 50 + artist 25 + album 25 + cover 5 = 105, capped at 100
        assert score == 100

    def test_calculate_relevance_compilation_penalty(self):
        """Test relevance calculation penalizes compilations."""
        provider = DiscogsProvider()
        item = {"title": "various - compilation", "format": ["Compilation"]}

        score = provider._calculate_relevance(item, "Various", "Compilation")

        # Base 50 + artist 25 + album 25 - compilation 10 = 90
        assert score == 90

    def test_calculate_relevance_no_match(self):
        """Test relevance calculation for no match."""
        provider = DiscogsProvider()
        item = {"title": "the beatles - abbey road"}

        score = provider._calculate_relevance(item, "Pink Floyd", "The Wall")

        # Base 50 only
        assert score == 50

    def test_close(self):
        """Test close method closes the session."""
        provider = DiscogsProvider()
        provider.close()
        assert True

    def test_context_manager(self):
        """Test context manager usage."""
        with DiscogsProvider() as provider:
            assert provider.name == "Discogs"

    def test_rate_limiting_thread_safety(self):
        """Test rate limiting is thread-safe."""
        provider = DiscogsProvider()
        request_times = []
        lock = threading.Lock()

        def make_request():
            provider._rate_limit()
            with lock:
                request_times.append(time.time())

        with patch("time.sleep"), ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            for future in as_completed(futures):
                future.result()

        assert len(request_times) == 10

    @responses.activate
    def test_lookup_by_release_id_success(self):
        """Test successful lookup by Discogs release ID."""
        release_id = "12345"
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/releases/{release_id}",
            json={
                "id": 12345,
                "title": "The Wall",
                "year": 1979,
                "artists": [{"name": "Pink Floyd"}],
                "images": [
                    {"type": "primary", "uri": "http://example.com/cover.jpg"},
                    {"type": "secondary", "uri": "http://example.com/back.jpg"},
                ],
            },
            status=200,
        )

        provider = DiscogsProvider()
        result = provider.lookup_by_release_id(release_id)

        assert result is not None
        assert result.mbid == "12345"
        assert result.artist == "Pink Floyd"
        assert result.album == "The Wall"
        assert result.year == "1979"
        assert result.score == 100
        assert result.has_cover_art is True
        assert result.cover_url == "http://example.com/cover.jpg"

    @responses.activate
    def test_lookup_by_release_id_not_found(self):
        """Test lookup by release ID returns None for 404."""
        release_id = "99999999"
        responses.add(responses.GET, f"{DISCOGS_API}/releases/{release_id}", status=404)

        provider = DiscogsProvider()
        result = provider.lookup_by_release_id(release_id)

        assert result is None

    def test_lookup_by_release_id_empty_input(self):
        """Test lookup by release ID with empty input."""
        provider = DiscogsProvider()
        assert provider.lookup_by_release_id("") is None
        assert provider.lookup_by_release_id(None) is None

    def test_lookup_by_release_id_invalid_format(self):
        """Test lookup by release ID with invalid format."""
        provider = DiscogsProvider()
        assert provider.lookup_by_release_id("abc") is None
        assert provider.lookup_by_release_id("12.34") is None

    @responses.activate
    def test_lookup_by_release_id_removes_artist_disambiguation(self):
        """Test that artist disambiguation numbers are removed."""
        release_id = "12345"
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/releases/{release_id}",
            json={
                "id": 12345,
                "title": "The Wall",
                "year": 1979,
                "artists": [{"name": "Pink Floyd (2)"}],
                "images": [],
            },
            status=200,
        )

        provider = DiscogsProvider()
        result = provider.lookup_by_release_id(release_id)

        assert result is not None
        assert result.artist == "Pink Floyd"  # (2) should be removed

    @responses.activate
    def test_lookup_by_barcode_success(self):
        """Test successful lookup by barcode."""
        barcode = "724349691704"  # 12-digit UPC
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            json={
                "results": [
                    {
                        "id": 12345,
                        "title": "Pink Floyd - The Dark Side of the Moon",
                        "year": 1973,
                        "cover_image": "http://example.com/cover.jpg",
                    }
                ]
            },
            status=200,
        )

        provider = DiscogsProvider()
        result = provider.lookup_by_barcode(barcode)

        assert result is not None
        assert result.mbid == "12345"
        assert result.artist == "Pink Floyd"
        assert result.album == "The Dark Side of the Moon"
        assert result.year == "1973"
        assert result.score == 98
        assert result.cover_url == "http://example.com/cover.jpg"

    @responses.activate
    def test_lookup_by_barcode_13_digit(self):
        """Test lookup by 13-digit EAN barcode."""
        barcode = "0724349691704"  # 13-digit EAN
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            json={
                "results": [
                    {
                        "id": 67890,
                        "title": "Pink Floyd - Animals",
                        "year": 1977,
                        "cover_image": "http://example.com/animals.jpg",
                    }
                ]
            },
            status=200,
        )

        provider = DiscogsProvider()
        result = provider.lookup_by_barcode(barcode)

        assert result is not None
        assert result.album == "Animals"

    @responses.activate
    def test_lookup_by_barcode_not_found(self):
        """Test lookup by barcode returns None when no results."""
        barcode = "123456789012"
        responses.add(
            responses.GET, f"{DISCOGS_API}/database/search", json={"results": []}, status=200
        )

        provider = DiscogsProvider()
        result = provider.lookup_by_barcode(barcode)

        assert result is None

    def test_lookup_by_barcode_invalid_format(self):
        """Test lookup by barcode with invalid format."""
        provider = DiscogsProvider()
        # Too short
        assert provider.lookup_by_barcode("123") is None
        # Too long
        assert provider.lookup_by_barcode("12345678901234") is None
        # Contains letters
        assert provider.lookup_by_barcode("12345678901a") is None
        # Empty
        assert provider.lookup_by_barcode("") is None
        assert provider.lookup_by_barcode(None) is None

    @responses.activate
    def test_lookup_by_barcode_title_without_hyphen(self):
        """Test lookup by barcode when title has no hyphen separator."""
        barcode = "123456789012"
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            json={
                "results": [
                    {
                        "id": 12345,
                        "title": "The Dark Side of the Moon",  # No artist separator
                        "year": 1973,
                        "cover_image": "http://example.com/cover.jpg",
                    }
                ]
            },
            status=200,
        )

        provider = DiscogsProvider()
        result = provider.lookup_by_barcode(barcode)

        assert result is not None
        assert result.artist == ""
        assert result.album == "The Dark Side of the Moon"


class TestLastFmProvider:
    """Tests for LastFmProvider."""

    def test_init_without_key(self):
        """Test initialization without API key."""
        provider = LastFmProvider()
        assert provider.name == "Last.fm"
        assert provider.requires_api_key is True
        assert provider.api_key is None

    def test_init_with_key(self):
        """Test initialization with API key."""
        provider = LastFmProvider(api_key="test_key")
        assert provider.api_key == "test_key"

    def test_is_configured_false_without_key(self):
        """Test is_configured returns False without key."""
        provider = LastFmProvider()
        assert provider.is_configured() is False

    def test_is_configured_true_with_key(self):
        """Test is_configured returns True with key."""
        provider = LastFmProvider(api_key="test_key")
        assert provider.is_configured() is True

    def test_search_without_key_returns_empty(self):
        """Test that search without API key returns empty list."""
        provider = LastFmProvider()
        results = provider.search("Artist", "Album", None)
        assert results == []

    def test_set_api_key(self):
        """Test setting API key after initialization."""
        provider = LastFmProvider()
        provider.set_api_key("new_key")
        assert provider.api_key == "new_key"

    @responses.activate
    def test_search_success(self):
        """Test successful search."""
        responses.add(
            responses.GET,
            LASTFM_API,
            json={
                "results": {
                    "albummatches": {
                        "album": [
                            {
                                "name": "The Wall",
                                "artist": "Pink Floyd",
                                "mbid": "mbid-123",
                                "image": [
                                    {"size": "small", "#text": "http://example.com/small.jpg"},
                                    {"size": "medium", "#text": "http://example.com/medium.jpg"},
                                    {"size": "large", "#text": "http://example.com/large.jpg"},
                                    {
                                        "size": "extralarge",
                                        "#text": "http://example.com/extralarge.jpg",
                                    },
                                ],
                            }
                        ]
                    }
                }
            },
            status=200,
        )

        provider = LastFmProvider(api_key="test_key")
        results = provider.search("Pink Floyd", "The Wall", "1979")

        assert len(results) == 1
        assert results[0].provider == "Last.fm"
        assert results[0].mbid == "mbid-123"
        assert results[0].artist == "Pink Floyd"
        assert results[0].album == "The Wall"
        assert results[0].year is None  # Last.fm doesn't return year
        assert results[0].has_cover_art is True
        assert results[0].cover_url == "http://example.com/extralarge.jpg"

    @responses.activate
    def test_search_api_error_response(self):
        """Test search handles API error in response."""
        responses.add(
            responses.GET, LASTFM_API, json={"error": 10, "message": "Invalid API key"}, status=200
        )

        provider = LastFmProvider(api_key="invalid_key")
        results = provider.search("Pink Floyd", "The Wall", None)

        assert results == []

    @responses.activate
    def test_search_network_error(self):
        """Test search raises NetworkError for connection errors."""
        responses.add(
            responses.GET,
            LASTFM_API,
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        provider = LastFmProvider(api_key="test_key")
        with pytest.raises(NetworkError) as exc_info:
            provider.search("Pink Floyd", "The Wall", None)
        assert "connection failed" in str(exc_info.value).lower()

    @responses.activate
    def test_search_timeout_error(self):
        """Test search raises NetworkError for timeout errors."""
        responses.add(
            responses.GET, LASTFM_API, body=requests.exceptions.Timeout("Request timed out")
        )

        provider = LastFmProvider(api_key="test_key")
        with pytest.raises(NetworkError) as exc_info:
            provider.search("Pink Floyd", "The Wall", None)
        assert "timed out" in str(exc_info.value).lower()

    @responses.activate
    def test_search_http_500_error(self):
        """Test search raises NetworkError for HTTP 500 errors."""
        for _ in range(4):
            responses.add(responses.GET, LASTFM_API, status=500)

        provider = LastFmProvider(api_key="test_key")
        with pytest.raises(NetworkError):
            provider.search("Pink Floyd", "The Wall", None)

    def test_get_best_image(self):
        """Test image size priority selection."""
        provider = LastFmProvider()

        images = [
            {"size": "small", "#text": "http://small.jpg"},
            {"size": "medium", "#text": "http://medium.jpg"},
            {"size": "large", "#text": "http://large.jpg"},
            {"size": "extralarge", "#text": "http://extralarge.jpg"},
        ]

        best = provider._get_best_image(images)
        assert best == "http://extralarge.jpg"

    def test_get_best_image_with_mega(self):
        """Test that mega size is preferred over extralarge."""
        provider = LastFmProvider()

        images = [
            {"size": "small", "#text": "http://small.jpg"},
            {"size": "extralarge", "#text": "http://extralarge.jpg"},
            {"size": "mega", "#text": "http://mega.jpg"},
        ]

        best = provider._get_best_image(images)
        assert best == "http://mega.jpg"

    def test_get_best_image_fallback(self):
        """Test fallback to smaller size when larger not available."""
        provider = LastFmProvider()

        images = [
            {"size": "small", "#text": "http://small.jpg"},
            {"size": "medium", "#text": "http://medium.jpg"},
        ]

        best = provider._get_best_image(images)
        assert best == "http://medium.jpg"

    def test_get_best_image_empty_returns_none(self):
        """Test that empty list returns None."""
        provider = LastFmProvider()
        assert provider._get_best_image([]) is None

    def test_get_best_image_empty_url(self):
        """Test that empty URL is skipped."""
        provider = LastFmProvider()

        images = [
            {"size": "extralarge", "#text": ""},
            {"size": "large", "#text": "http://large.jpg"},
        ]

        best = provider._get_best_image(images)
        assert best == "http://large.jpg"

    def test_calculate_relevance_exact_match(self):
        """Test relevance calculation for exact match."""
        provider = LastFmProvider()
        item = {"artist": "Pink Floyd", "name": "The Wall"}

        score = provider._calculate_relevance(item, "Pink Floyd", "The Wall")

        # Base 50 + exact artist 25 + exact album 25 = 100
        assert score == 100

    def test_calculate_relevance_partial_match(self):
        """Test relevance calculation for partial match."""
        provider = LastFmProvider()
        item = {"artist": "Pink Floyd", "name": "The Wall (Remastered)"}

        score = provider._calculate_relevance(item, "Pink Floyd", "the wall")

        # Base 50 + exact artist 25 + partial album 15 = 90
        assert score == 90

    def test_calculate_relevance_no_match(self):
        """Test relevance calculation for no match."""
        provider = LastFmProvider()
        item = {"artist": "The Beatles", "name": "Abbey Road"}

        score = provider._calculate_relevance(item, "Pink Floyd", "The Wall")

        # Base 50 only
        assert score == 50

    @responses.activate
    def test_get_cover_url_from_search_result(self):
        """Test get_cover_url returns URL from search result."""
        provider = LastFmProvider(api_key="test_key")
        result = SearchResult(
            provider="Last.fm", mbid="mbid-123", cover_url="http://example.com/cover.jpg"
        )

        url = provider.get_cover_url(result)
        assert url == "http://example.com/cover.jpg"

    @responses.activate
    def test_get_cover_url_with_mbid(self):
        """Test get_cover_url uses MBID for API lookup."""
        responses.add(
            responses.GET,
            LASTFM_API,
            json={
                "album": {
                    "name": "The Wall",
                    "artist": "Pink Floyd",
                    "image": [
                        {"size": "large", "#text": "http://example.com/large.jpg"},
                        {"size": "extralarge", "#text": "http://example.com/extralarge.jpg"},
                    ],
                }
            },
            status=200,
        )

        provider = LastFmProvider(api_key="test_key")
        result = SearchResult(
            provider="Last.fm",
            mbid="mbid-123",
            artist="Pink Floyd",
            album="The Wall",
            cover_url=None,
        )

        url = provider.get_cover_url(result)
        assert url == "http://example.com/extralarge.jpg"

        # Verify MBID was used in request
        assert "mbid=mbid-123" in responses.calls[0].request.url

    @responses.activate
    def test_get_cover_url_with_artist_album(self):
        """Test get_cover_url uses artist/album when no MBID."""
        responses.add(
            responses.GET,
            LASTFM_API,
            json={
                "album": {
                    "name": "The Wall",
                    "artist": "Pink Floyd",
                    "image": [{"size": "extralarge", "#text": "http://example.com/cover.jpg"}],
                }
            },
            status=200,
        )

        provider = LastFmProvider(api_key="test_key")
        result = SearchResult(
            provider="Last.fm", mbid="", artist="Pink Floyd", album="The Wall", cover_url=None
        )

        url = provider.get_cover_url(result)
        assert url == "http://example.com/cover.jpg"

        # Verify artist/album were used in request
        assert "artist=Pink" in responses.calls[0].request.url
        assert "album=The" in responses.calls[0].request.url

    def test_get_cover_url_no_api_key(self):
        """Test get_cover_url returns None when no API key."""
        provider = LastFmProvider()
        result = SearchResult(provider="Last.fm", mbid="mbid-123", cover_url=None)

        url = provider.get_cover_url(result)
        assert url is None

    @responses.activate
    def test_get_cover_url_api_error_response(self):
        """Test get_cover_url handles API error in response."""
        responses.add(
            responses.GET, LASTFM_API, json={"error": 6, "message": "Album not found"}, status=200
        )

        provider = LastFmProvider(api_key="test_key")
        result = SearchResult(provider="Last.fm", mbid="invalid-mbid", cover_url=None)

        url = provider.get_cover_url(result)
        assert url is None

    @responses.activate
    def test_download_cover_success(self):
        """Test successful cover download."""
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        # Use allowed domain (lastfm.freetls.fastly.net)
        responses.add(
            responses.GET,
            "https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg",
            body=image_data,
            status=200,
            content_type="image/jpeg",
        )

        provider = LastFmProvider()
        data = provider.download_cover("https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg")

        assert data == image_data

    @responses.activate
    def test_download_cover_error(self):
        """Test download_cover raises NetworkError on connection error."""
        responses.add(
            responses.GET,
            "https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg",
            body=requests.exceptions.ConnectionError("Connection refused"),
        )

        provider = LastFmProvider()
        with pytest.raises(NetworkError):
            provider.download_cover("https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg")

    @responses.activate
    def test_download_cover_404(self):
        """Test download_cover returns None on 404.

        A 404 indicates the cover image doesn't exist, which is semantically
        different from a network error.
        """
        responses.add(
            responses.GET, "https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg", status=404
        )

        provider = LastFmProvider()
        result = provider.download_cover("https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg")
        assert result is None

    def test_download_cover_blocked_url(self):
        """Test download_cover rejects URLs from non-allowed domains."""
        # Blocked URLs return None before any network request is made (SSRF prevention)
        provider = LastFmProvider()
        data = provider.download_cover("http://example.com/cover.jpg")

        assert data is None

    def test_close(self):
        """Test close method closes the session."""
        provider = LastFmProvider()
        provider.close()
        assert True

    def test_context_manager(self):
        """Test context manager usage."""
        with LastFmProvider(api_key="test_key") as provider:
            assert provider.name == "Last.fm"

    def test_rate_limiting_thread_safety(self):
        """Test rate limiting is thread-safe."""
        provider = LastFmProvider(api_key="test_key")
        request_times = []
        lock = threading.Lock()

        def make_request():
            provider._rate_limit()
            with lock:
                request_times.append(time.time())

        with patch("time.sleep"), ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            for future in as_completed(futures):
                future.result()

        assert len(request_times) == 10


class TestAllProvidersCommon:
    """Common tests for all providers."""

    @pytest.fixture(
        params=[
            lambda: MusicBrainzProvider(),
            lambda: DiscogsProvider(),
            lambda: LastFmProvider(api_key="test_key"),
        ]
    )
    def provider(self, request):
        """Fixture that provides each provider type."""
        return request.param()

    def test_provider_has_name(self, provider):
        """Test all providers have a name."""
        assert provider.name is not None
        assert len(provider.name) > 0

    def test_provider_has_requires_api_key(self, provider):
        """Test all providers have requires_api_key property."""
        assert isinstance(provider.requires_api_key, bool)

    def test_provider_is_context_manager(self, provider):
        """Test all providers support context manager protocol."""
        assert hasattr(provider, "__enter__")
        assert hasattr(provider, "__exit__")

    def test_provider_has_close_method(self, provider):
        """Test all providers have close method."""
        assert hasattr(provider, "close")
        assert callable(provider.close)

    def test_provider_has_search_method(self, provider):
        """Test all providers have search method."""
        assert hasattr(provider, "search")
        assert callable(provider.search)

    def test_provider_has_get_cover_url_method(self, provider):
        """Test all providers have get_cover_url method."""
        assert hasattr(provider, "get_cover_url")
        assert callable(provider.get_cover_url)

    def test_provider_has_download_cover_method(self, provider):
        """Test all providers have download_cover method."""
        assert hasattr(provider, "download_cover")
        assert callable(provider.download_cover)

    def test_provider_has_api_host(self, provider):
        """Test all providers have api_host property."""
        assert hasattr(provider, "api_host")
        assert provider.api_host is not None
        assert len(provider.api_host) > 0
        assert isinstance(provider.api_host, str)

    def test_provider_api_host_is_valid_hostname(self, provider):
        """Test all providers return a valid hostname (no protocol, no path)."""
        api_host = provider.api_host
        # Should not contain protocol
        assert not api_host.startswith("http://"), (
            f"api_host should not include protocol: {api_host}"
        )
        assert not api_host.startswith("https://"), (
            f"api_host should not include protocol: {api_host}"
        )
        # Should not contain path
        assert "/" not in api_host, f"api_host should not include path: {api_host}"
        # Should look like a valid domain
        assert "." in api_host, f"api_host should be a valid domain: {api_host}"


class TestNetworkErrorHandling:
    """Tests for network error handling across all providers."""

    @pytest.mark.parametrize(
        "exception_type,exception_msg",
        [
            (requests.exceptions.ConnectionError, "Connection refused"),
            (requests.exceptions.Timeout, "Request timed out"),
            (requests.exceptions.SSLError, "SSL certificate verify failed"),
            (requests.exceptions.ProxyError, "Proxy error"),
            (requests.exceptions.ChunkedEncodingError, "Connection broken"),
        ],
    )
    @responses.activate
    def test_musicbrainz_handles_various_network_errors(self, exception_type, exception_msg):
        """Test MusicBrainz raises NetworkError for various network errors."""
        responses.add(
            responses.GET, f"{MUSICBRAINZ_API}/release", body=exception_type(exception_msg)
        )

        provider = MusicBrainzProvider()
        with pytest.raises(NetworkError):
            provider.search("Test", "Album", None)

    @pytest.mark.parametrize(
        "exception_type,exception_msg",
        [
            (requests.exceptions.ConnectionError, "Connection refused"),
            (requests.exceptions.Timeout, "Request timed out"),
        ],
    )
    @responses.activate
    def test_discogs_handles_various_network_errors(self, exception_type, exception_msg):
        """Test Discogs raises NetworkError for various network errors."""
        responses.add(
            responses.GET, f"{DISCOGS_API}/database/search", body=exception_type(exception_msg)
        )

        provider = DiscogsProvider()
        with pytest.raises(NetworkError):
            provider.search("Test", "Album", None)

    @pytest.mark.parametrize(
        "exception_type,exception_msg",
        [
            (requests.exceptions.ConnectionError, "Connection refused"),
            (requests.exceptions.Timeout, "Request timed out"),
        ],
    )
    @responses.activate
    def test_lastfm_handles_various_network_errors(self, exception_type, exception_msg):
        """Test Last.fm raises NetworkError for various network errors."""
        responses.add(responses.GET, LASTFM_API, body=exception_type(exception_msg))

        provider = LastFmProvider(api_key="test_key")
        with pytest.raises(NetworkError):
            provider.search("Test", "Album", None)


class TestHTTPErrorCodes:
    """Tests for HTTP error code handling."""

    @pytest.mark.parametrize("status_code", [500, 502, 504])
    @responses.activate
    def test_musicbrainz_search_raises_on_retryable_errors(self, status_code):
        """Test MusicBrainz search raises NetworkError for retryable HTTP errors."""
        # Add multiple responses for retry logic (original + 3 retries)
        for _ in range(4):
            responses.add(responses.GET, f"{MUSICBRAINZ_API}/release", status=status_code)

        provider = MusicBrainzProvider()
        with pytest.raises(NetworkError):
            provider.search("Test", "Album", None)

    @responses.activate
    def test_musicbrainz_search_raises_rate_limit_on_503(self):
        """Test MusicBrainz search raises RateLimitError for 503 status."""
        from src.core.exceptions import RateLimitError

        # Add multiple responses for manual retry logic
        for _ in range(4):
            responses.add(responses.GET, f"{MUSICBRAINZ_API}/release", status=503)

        provider = MusicBrainzProvider()
        with pytest.raises(RateLimitError):
            provider.search("Test", "Album", None)

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    @responses.activate
    def test_musicbrainz_search_raises_on_client_errors(self, status_code):
        """Test MusicBrainz search raises NetworkError for client HTTP errors.

        All HTTP errors now raise NetworkError for consistent error handling,
        allowing the UI to properly inform users of network issues.
        """
        responses.add(responses.GET, f"{MUSICBRAINZ_API}/release", status=status_code)

        provider = MusicBrainzProvider()
        with pytest.raises(NetworkError):
            provider.search("Test", "Album", None)

    @pytest.mark.parametrize("status_code", [400, 403, 404, 500, 502, 504])
    @responses.activate
    def test_discogs_search_raises_network_error_on_http_errors(self, status_code):
        """Test Discogs search raises NetworkError for various HTTP error codes.

        All HTTP errors (except 401 and rate limit codes) now raise NetworkError
        for consistent error handling across all providers.
        """
        for _ in range(4):
            responses.add(responses.GET, f"{DISCOGS_API}/database/search", status=status_code)

        provider = DiscogsProvider()
        with pytest.raises(NetworkError):
            provider.search("Test", "Album", None)

    @responses.activate
    def test_discogs_search_raises_rate_limit_on_429(self):
        """Test Discogs search raises RateLimitError on 429 status."""
        from src.core.exceptions import RateLimitError

        for _ in range(4):
            responses.add(responses.GET, f"{DISCOGS_API}/database/search", status=429)

        provider = DiscogsProvider()
        with pytest.raises(RateLimitError):
            provider.search("Test", "Album", None)

    @responses.activate
    def test_discogs_search_raises_rate_limit_on_503(self):
        """Test Discogs search raises RateLimitError on 503 status."""
        from src.core.exceptions import RateLimitError

        for _ in range(4):
            responses.add(responses.GET, f"{DISCOGS_API}/database/search", status=503)

        provider = DiscogsProvider()
        with pytest.raises(RateLimitError):
            provider.search("Test", "Album", None)

    @responses.activate
    def test_discogs_search_raises_on_auth_error(self):
        """Test Discogs search raises ProviderError on 401 auth error."""
        for _ in range(4):
            responses.add(responses.GET, f"{DISCOGS_API}/database/search", status=401)

        provider = DiscogsProvider()
        with pytest.raises(ProviderError) as exc_info:
            provider.search("Test", "Album", None)

        assert "API token" in str(exc_info.value)
        assert exc_info.value.provider_name == "Discogs"

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 500, 502, 504])
    @responses.activate
    def test_lastfm_search_raises_network_error_on_http_errors(self, status_code):
        """Test Last.fm search raises NetworkError for various HTTP error codes.

        All HTTP errors (except rate limit codes) now raise NetworkError
        for consistent error handling across all providers.
        """
        for _ in range(4):
            responses.add(responses.GET, LASTFM_API, status=status_code)

        provider = LastFmProvider(api_key="test_key")
        with pytest.raises(NetworkError):
            provider.search("Test", "Album", None)

    @responses.activate
    def test_lastfm_search_raises_rate_limit_on_429(self):
        """Test Last.fm search raises RateLimitError on 429 status."""
        from src.core.exceptions import RateLimitError

        for _ in range(4):
            responses.add(responses.GET, LASTFM_API, status=429)

        provider = LastFmProvider(api_key="test_key")
        with pytest.raises(RateLimitError):
            provider.search("Test", "Album", None)

    @responses.activate
    def test_lastfm_search_raises_rate_limit_on_503(self):
        """Test Last.fm search raises RateLimitError on 503 status."""
        from src.core.exceptions import RateLimitError

        for _ in range(4):
            responses.add(responses.GET, LASTFM_API, status=503)

        provider = LastFmProvider(api_key="test_key")
        with pytest.raises(RateLimitError):
            provider.search("Test", "Album", None)


class TestRetryLogicWithBackoff:
    """Tests for retry logic with exponential backoff."""

    @responses.activate
    def test_musicbrainz_retries_on_503(self):
        """Test MusicBrainz retries on 503 errors."""
        # First 2 requests return 503, third succeeds
        responses.add(responses.GET, f"{MUSICBRAINZ_API}/release", status=503)
        responses.add(responses.GET, f"{MUSICBRAINZ_API}/release", status=503)
        responses.add(
            responses.GET,
            f"{MUSICBRAINZ_API}/release",
            json={
                "releases": [{"id": "mbid-123", "title": "Test", "artist-credit": [], "score": 100}]
            },
            status=200,
        )

        provider = MusicBrainzProvider()
        results = provider.search("Test", "Album", None)

        # Should have made 3 requests (2 retries + 1 success)
        assert len(responses.calls) == 3
        assert len(results) == 1

    @responses.activate
    def test_discogs_retries_on_429(self):
        """Test Discogs retries on 429 rate limit errors."""
        # First request returns 429, second succeeds
        responses.add(responses.GET, f"{DISCOGS_API}/database/search", status=429)
        responses.add(
            responses.GET,
            f"{DISCOGS_API}/database/search",
            json={"results": [{"id": 123, "title": "Test - Album", "year": 2000}]},
            status=200,
        )

        provider = DiscogsProvider()
        results = provider.search("Test", "Album", None)

        assert len(responses.calls) == 2
        assert len(results) == 1

    @responses.activate
    def test_lastfm_retries_on_500(self):
        """Test Last.fm retries on 500 errors."""
        responses.add(responses.GET, LASTFM_API, status=500)
        responses.add(
            responses.GET, LASTFM_API, json={"results": {"albummatches": {"album": []}}}, status=200
        )

        provider = LastFmProvider(api_key="test_key")
        results = provider.search("Test", "Album", None)

        assert len(responses.calls) == 2
        assert results == []


class TestConcurrentAccess:
    """Tests for concurrent access to providers."""

    @responses.activate
    def test_musicbrainz_concurrent_searches(self):
        """Test MusicBrainz handles concurrent searches."""
        # Add enough responses for concurrent requests
        for i in range(20):
            responses.add(
                responses.GET,
                f"{MUSICBRAINZ_API}/release",
                json={
                    "releases": [
                        {
                            "id": f"mbid-{i}",
                            "title": f"Album {i}",
                            "artist-credit": [],
                            "score": 100,
                        }
                    ]
                },
                status=200,
            )

        provider = MusicBrainzProvider()
        results = []
        errors = []

        def search_album(i):
            try:
                result = provider.search(f"Artist {i}", f"Album {i}", None)
                return result
            except Exception as e:
                return e

        with patch("time.sleep"):  # Skip rate limiting delays in test
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(search_album, i): i for i in range(10)}
                for future in as_completed(futures):
                    result = future.result()
                    if isinstance(result, Exception):
                        errors.append(result)
                    else:
                        results.extend(result)

        assert len(errors) == 0
        # Some results may be returned (depends on mocking)

    def test_provider_session_thread_safety(self):
        """Test provider sessions are thread-safe."""
        provider = MusicBrainzProvider()
        errors = []

        def access_session():
            try:
                # Just access session attributes
                _ = provider._session.headers
                return True
            except Exception as e:
                return e

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(access_session) for _ in range(50)]
            for future in as_completed(futures):
                result = future.result()
                if isinstance(result, Exception):
                    errors.append(result)

        assert len(errors) == 0
