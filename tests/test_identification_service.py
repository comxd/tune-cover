"""
Tests for the identification service module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.identification_service import (
    IdentificationLevel,
    IdentificationResult,
    IdentificationService,
    get_identification_service,
)
from src.core.models import AlbumInfo, CoverInfo, SearchResult


@pytest.fixture
def mock_musicbrainz_provider():
    """Create a mock MusicBrainz provider."""
    provider = MagicMock()
    provider.lookup_by_mbid.return_value = None
    provider.lookup_by_isrc.return_value = None
    provider.lookup_by_barcode.return_value = None
    provider.search.return_value = []
    return provider


@pytest.fixture
def mock_discogs_provider():
    """Create a mock Discogs provider."""
    provider = MagicMock()
    provider.lookup_by_release_id.return_value = None
    provider.lookup_by_barcode.return_value = None
    provider.search.return_value = []
    return provider


@pytest.fixture
def mock_lastfm_provider():
    """Create a mock Last.fm provider."""
    provider = MagicMock()
    provider.search.return_value = []
    return provider


@pytest.fixture
def sample_album():
    """Create a sample album for testing."""
    return AlbumInfo(
        path=Path("/music/Artist/Album"),
        artist="Pink Floyd",
        album="The Dark Side of the Moon",
        year="1973",
        track_count=10,
        cover=CoverInfo(),
        sample_file=Path("/music/Artist/Album/track1.mp3"),
        musicbrainz_albumid="mbid-123",
        musicbrainz_releasegroupid="rg-456",
        musicbrainz_artistid="artist-789",
        isrc="USRC17607839",
        barcode="5099902987422",
        discogs_release_id="123456",
    )


@pytest.fixture
def album_no_ids():
    """Create an album without identifiers."""
    return AlbumInfo(
        path=Path("/music/Artist/Album"),
        artist="Pink Floyd",
        album="The Dark Side of the Moon",
        year="1973",
        track_count=10,
        cover=CoverInfo(),
        sample_file=Path("/music/Artist/Album/track1.mp3"),
    )


class TestIdentificationLevel:
    """Tests for IdentificationLevel enum."""

    def test_level_values(self):
        """Test that all levels are defined."""
        assert IdentificationLevel.MBID
        assert IdentificationLevel.DISCOGS_ID
        assert IdentificationLevel.BARCODE
        assert IdentificationLevel.ISRC
        assert IdentificationLevel.TEXT_SEARCH
        assert IdentificationLevel.FINGERPRINT


class TestIdentificationResult:
    """Tests for IdentificationResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = IdentificationResult(success=False)

        assert not result.success
        assert result.level is None
        assert result.search_result is None
        assert result.confidence == 0
        assert result.message == ""
        assert result.levels_attempted == []

    def test_successful_result(self):
        """Test successful result."""
        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="mbid-123",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=100,
        )

        result = IdentificationResult(
            success=True,
            level=IdentificationLevel.MBID,
            search_result=search_result,
            confidence=100,
            message="Identified via MBID",
            levels_attempted=[IdentificationLevel.MBID],
        )

        assert result.success
        assert result.level == IdentificationLevel.MBID
        assert result.search_result == search_result
        assert result.confidence == 100


class TestIdentificationService:
    """Tests for IdentificationService class."""

    def test_init(self, mock_musicbrainz_provider, mock_discogs_provider, mock_lastfm_provider):
        """Test service initialization."""
        service = IdentificationService(
            musicbrainz_provider=mock_musicbrainz_provider,
            discogs_provider=mock_discogs_provider,
            lastfm_provider=mock_lastfm_provider,
        )

        assert service._musicbrainz == mock_musicbrainz_provider
        assert service._discogs == mock_discogs_provider
        assert service._lastfm == mock_lastfm_provider

    def test_identify_by_mbid(self, mock_musicbrainz_provider, sample_album):
        """Test identification via MBID."""
        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="mbid-123",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=100,
        )
        mock_musicbrainz_provider.lookup_by_mbid.return_value = search_result

        service = IdentificationService(musicbrainz_provider=mock_musicbrainz_provider)
        result = service.identify(sample_album)

        assert result.success
        assert result.level == IdentificationLevel.MBID
        assert result.confidence == 100
        mock_musicbrainz_provider.lookup_by_mbid.assert_called_once_with("mbid-123")

    def test_identify_by_discogs_id(self, mock_discogs_provider, sample_album):
        """Test identification via Discogs ID."""
        # Clear MBID to force Discogs lookup
        sample_album.musicbrainz_albumid = None

        search_result = SearchResult(
            provider="Discogs",
            mbid="123456",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=100,
        )
        mock_discogs_provider.lookup_by_release_id.return_value = search_result

        service = IdentificationService(discogs_provider=mock_discogs_provider)
        result = service.identify(sample_album)

        assert result.success
        assert result.level == IdentificationLevel.DISCOGS_ID
        mock_discogs_provider.lookup_by_release_id.assert_called_once_with("123456")

    def test_identify_by_barcode(
        self, mock_musicbrainz_provider, mock_discogs_provider, sample_album
    ):
        """Test identification via barcode."""
        # Clear direct IDs
        sample_album.musicbrainz_albumid = None
        sample_album.discogs_release_id = None

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="mbid-from-barcode",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=98,
        )
        mock_musicbrainz_provider.lookup_by_barcode.return_value = search_result

        service = IdentificationService(
            musicbrainz_provider=mock_musicbrainz_provider,
            discogs_provider=mock_discogs_provider,
        )
        result = service.identify(sample_album)

        assert result.success
        assert result.level == IdentificationLevel.BARCODE
        mock_musicbrainz_provider.lookup_by_barcode.assert_called_once_with("5099902987422")

    def test_identify_by_isrc(self, mock_musicbrainz_provider, sample_album):
        """Test identification via ISRC."""
        # Clear other identifiers
        sample_album.musicbrainz_albumid = None
        sample_album.discogs_release_id = None
        sample_album.barcode = None

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="mbid-from-isrc",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=95,
        )
        mock_musicbrainz_provider.lookup_by_isrc.return_value = search_result

        service = IdentificationService(musicbrainz_provider=mock_musicbrainz_provider)
        result = service.identify(sample_album)

        assert result.success
        assert result.level == IdentificationLevel.ISRC
        mock_musicbrainz_provider.lookup_by_isrc.assert_called_once_with("USRC17607839")

    def test_identify_by_text_search(self, mock_musicbrainz_provider, album_no_ids):
        """Test identification via text search."""
        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="mbid-from-search",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=90,
        )
        mock_musicbrainz_provider.search.return_value = [search_result]

        service = IdentificationService(musicbrainz_provider=mock_musicbrainz_provider)
        result = service.identify(album_no_ids)

        assert result.success
        assert result.level == IdentificationLevel.TEXT_SEARCH
        mock_musicbrainz_provider.search.assert_called_once()

    def test_identify_no_match(self, mock_musicbrainz_provider, album_no_ids):
        """Test identification when no match found."""
        service = IdentificationService(musicbrainz_provider=mock_musicbrainz_provider)
        result = service.identify(album_no_ids)

        assert not result.success
        assert result.level is None
        assert "No match found" in result.message

    def test_identify_with_specific_levels(self, mock_musicbrainz_provider, sample_album):
        """Test identification with specific levels."""
        service = IdentificationService(musicbrainz_provider=mock_musicbrainz_provider)

        # Only try TEXT_SEARCH level
        result = service.identify(sample_album, levels=[IdentificationLevel.TEXT_SEARCH])

        assert IdentificationLevel.TEXT_SEARCH in result.levels_attempted
        assert IdentificationLevel.MBID not in result.levels_attempted

    def test_identify_stop_on_success(self, mock_musicbrainz_provider, sample_album):
        """Test that identification stops on first success."""
        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="mbid-123",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=100,
        )
        mock_musicbrainz_provider.lookup_by_mbid.return_value = search_result

        service = IdentificationService(musicbrainz_provider=mock_musicbrainz_provider)
        result = service.identify(sample_album, stop_on_success=True)

        assert result.success
        # Should only have attempted MBID
        assert result.levels_attempted == [IdentificationLevel.MBID]

    def test_identify_continue_on_success(self, mock_musicbrainz_provider, sample_album):
        """Test identification continuing after success."""
        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="mbid-123",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            score=100,
        )
        mock_musicbrainz_provider.lookup_by_mbid.return_value = search_result
        mock_musicbrainz_provider.lookup_by_isrc.return_value = search_result
        mock_musicbrainz_provider.lookup_by_barcode.return_value = search_result

        service = IdentificationService(musicbrainz_provider=mock_musicbrainz_provider)
        result = service.identify(sample_album, stop_on_success=False)

        # Should have attempted multiple levels
        assert len(result.levels_attempted) > 1

    def test_get_available_levels(
        self,
        mock_musicbrainz_provider,
        mock_discogs_provider,
        sample_album,
        album_no_ids,
    ):
        """Test getting available identification levels."""
        service = IdentificationService(
            musicbrainz_provider=mock_musicbrainz_provider,
            discogs_provider=mock_discogs_provider,
        )

        # Album with all identifiers
        levels = service.get_available_levels(sample_album)
        assert IdentificationLevel.MBID in levels
        assert IdentificationLevel.DISCOGS_ID in levels
        assert IdentificationLevel.BARCODE in levels
        assert IdentificationLevel.ISRC in levels
        assert IdentificationLevel.TEXT_SEARCH in levels

        # Album without identifiers
        levels_no_ids = service.get_available_levels(album_no_ids)
        assert IdentificationLevel.MBID not in levels_no_ids
        assert IdentificationLevel.TEXT_SEARCH in levels_no_ids

    def test_get_identification_summary(self, sample_album, album_no_ids):
        """Test getting identification summary."""
        service = IdentificationService()

        # Album with identifiers
        summary = service.get_identification_summary(sample_album)
        assert summary["MusicBrainz ID"] == "mbid-123"
        assert summary["Discogs ID"] == "123456"
        assert summary["Barcode"] == "5099902987422"
        assert summary["ISRC"] == "USRC17607839"
        assert summary["Artist"] == "Pink Floyd"
        assert summary["Album"] == "The Dark Side of the Moon"

        # Album without identifiers
        summary_no_ids = service.get_identification_summary(album_no_ids)
        assert summary_no_ids["MusicBrainz ID"] == "N/A"
        assert summary_no_ids["Discogs ID"] == "N/A"

    def test_set_acoustid_user_key(self):
        """Test setting AcoustID user API key for submissions."""
        service = IdentificationService()
        service.set_acoustid_user_key("test-user-key")

        assert service.fingerprinter.user_key == "test-user-key"
        # api_key should remain the default (read-only)
        from src.core.fingerprint import AudioFingerprinter

        assert service.fingerprinter.api_key == AudioFingerprinter.DEFAULT_API_KEY


class TestGetIdentificationService:
    """Tests for get_identification_service function."""

    def test_returns_service(self):
        """Test that function returns IdentificationService instance."""
        # Reset singleton
        import src.core.identification_service

        src.core.identification_service._default_service = None

        service = get_identification_service()
        assert isinstance(service, IdentificationService)

    def test_singleton_pattern(self):
        """Test that function returns the same instance."""
        # Reset singleton
        import src.core.identification_service

        src.core.identification_service._default_service = None

        service1 = get_identification_service()
        service2 = get_identification_service()

        assert service1 is service2

    def test_updates_providers(self, mock_musicbrainz_provider):
        """Test that providing providers updates singleton."""
        # Reset singleton
        import src.core.identification_service

        src.core.identification_service._default_service = None

        service1 = get_identification_service()
        assert service1._musicbrainz is None

        service2 = get_identification_service(musicbrainz_provider=mock_musicbrainz_provider)
        assert service2._musicbrainz == mock_musicbrainz_provider
        assert service1._musicbrainz == mock_musicbrainz_provider
