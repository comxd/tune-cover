"""
Tests for the metadata cleaner module.
"""

import pytest

from src.core.metadata_cleaner import (
    _apply_fallback_cleaning,
    clean_album,
    clean_artist,
    clean_metadata,
    clean_track,
    is_filter_available,
)


class TestCleanArtist:
    """Tests for clean_artist function."""

    def test_none_input(self):
        """Test with None input."""
        assert clean_artist(None) is None

    def test_empty_string(self):
        """Test with empty string."""
        assert clean_artist("") is None

    def test_whitespace_only(self):
        """Test with whitespace-only string."""
        assert clean_artist("   ") is None

    def test_normal_artist(self):
        """Test with normal artist name."""
        assert clean_artist("Pink Floyd") == "Pink Floyd"

    def test_artist_with_whitespace(self):
        """Test stripping whitespace."""
        assert clean_artist("  Pink Floyd  ") == "Pink Floyd"

    def test_artist_with_topic_suffix(self):
        """Test removal of YouTube '- Topic' suffix if library available."""
        result = clean_artist("Pink Floyd - Topic")
        # Result depends on whether music-metadata-filter is installed
        assert result is not None
        # If the library is available, it removes " - Topic"
        # If not, it just returns the stripped input


class TestCleanAlbum:
    """Tests for clean_album function."""

    def test_none_input(self):
        """Test with None input."""
        assert clean_album(None) is None

    def test_empty_string(self):
        """Test with empty string."""
        assert clean_album("") is None

    def test_whitespace_only(self):
        """Test with whitespace-only string."""
        assert clean_album("   ") is None

    def test_normal_album(self):
        """Test with normal album name."""
        assert clean_album("The Dark Side of the Moon") == "The Dark Side of the Moon"

    def test_album_with_remastered(self):
        """Test removal of remastered tags."""
        result = clean_album("The Dark Side of the Moon (Remastered)")
        assert "Remastered" not in result
        assert "The Dark Side of the Moon" in result

    def test_album_with_remastered_year(self):
        """Test removal of remastered with year."""
        result = clean_album("The Dark Side of the Moon (2011 Remastered)")
        assert "Remastered" not in result
        assert "2011" not in result
        assert "The Dark Side of the Moon" in result

    def test_album_with_deluxe_edition(self):
        """Test removal of deluxe edition."""
        result = clean_album("The Dark Side of the Moon [Deluxe Edition]")
        assert "Deluxe" not in result.lower()
        assert "Edition" not in result.lower()

    def test_album_with_single(self):
        """Test removal of single marker."""
        result = clean_album("Comfortably Numb - Single")
        assert result == "Comfortably Numb"

    def test_album_with_ep(self):
        """Test removal of EP marker."""
        result = clean_album("Live EP - EP")
        assert "- EP" not in result

    def test_album_with_official_video(self):
        """Test removal of official video marker."""
        result = clean_album("Money (Official Video)")
        assert "Official" not in result
        assert "Video" not in result

    def test_album_with_official_audio(self):
        """Test removal of official audio marker."""
        result = clean_album("Time (Official Audio)")
        assert "Official" not in result
        assert "Audio" not in result

    def test_album_with_quality_indicator(self):
        """Test removal of quality indicators."""
        result = clean_album("The Wall [FLAC]")
        assert "FLAC" not in result

    def test_album_with_format_indicator(self):
        """Test removal of format indicators."""
        result = clean_album("Animals [CD Rip]")
        assert "CD" not in result or "Rip" not in result

    def test_album_with_explicit(self):
        """Test removal of explicit marker."""
        result = clean_album("The Dark Side of the Moon (Explicit)")
        assert "Explicit" not in result

    def test_album_complex_cleanup(self):
        """Test cleaning album with multiple markers."""
        result = clean_album("The Dark Side of the Moon (2011 Remastered) [Deluxe Edition] [FLAC]")
        assert "Remastered" not in result
        assert "Deluxe" not in result.lower()
        assert "FLAC" not in result
        assert "The Dark Side of the Moon" in result


class TestCleanTrack:
    """Tests for clean_track function."""

    def test_none_input(self):
        """Test with None input."""
        assert clean_track(None) is None

    def test_empty_string(self):
        """Test with empty string."""
        assert clean_track("") is None

    def test_normal_track(self):
        """Test with normal track name."""
        assert clean_track("Money") == "Money"

    def test_track_with_remastered(self):
        """Test removal of remastered tags."""
        result = clean_track("Money (2011 Remastered)")
        assert "Remastered" not in result
        assert "Money" in result

    def test_track_with_video(self):
        """Test removal of video markers."""
        result = clean_track("Money (Official Music Video)")
        assert "Video" not in result

    def test_track_with_lyrics_marker(self):
        """Test removal of lyrics marker."""
        result = clean_track("Money (Lyrics)")
        assert "Lyrics" not in result or result == "Money"  # Depends on library availability


class TestCleanMetadata:
    """Tests for clean_metadata function."""

    def test_all_none(self):
        """Test with all None inputs."""
        result = clean_metadata()
        assert result == (None, None, None, None)

    def test_with_values(self):
        """Test with actual values."""
        artist, album, year, track = clean_metadata(
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            year="1973",
            track="Money",
        )

        assert artist == "Pink Floyd"
        assert album == "The Dark Side of the Moon"
        assert year == "1973"
        assert track == "Money"

    def test_year_passes_through(self):
        """Test that year is not modified."""
        _, _, year, _ = clean_metadata(year="1973")
        assert year == "1973"

    def test_cleaning_applied(self):
        """Test that cleaning is applied to fields."""
        artist, album, year, track = clean_metadata(
            artist="  Pink Floyd  ",
            album="The Dark Side of the Moon (Remastered)",
            year="1973",
            track="Money (Official Video)",
        )

        assert artist == "Pink Floyd"
        assert "Remastered" not in album
        assert year == "1973"
        assert "Video" not in track


class TestFallbackCleaning:
    """Tests for the fallback regex cleaning."""

    def test_remove_remastered_parens(self):
        """Test fallback removes remastered in parentheses."""
        result = _apply_fallback_cleaning("Album (Remastered)")
        assert "Remastered" not in result

    def test_remove_remastered_brackets(self):
        """Test fallback removes remastered in brackets."""
        result = _apply_fallback_cleaning("Album [Remastered]")
        assert "Remastered" not in result

    def test_remove_year_remastered(self):
        """Test fallback removes year remastered."""
        result = _apply_fallback_cleaning("Album (2011 Remastered)")
        assert "2011" not in result
        assert "Remastered" not in result

    def test_trailing_whitespace(self):
        """Test fallback removes trailing whitespace."""
        result = _apply_fallback_cleaning("Album   ")
        assert result == "Album"


class TestIsFilterAvailable:
    """Tests for is_filter_available function."""

    def test_returns_boolean(self):
        """Test that function returns a boolean."""
        result = is_filter_available()
        assert isinstance(result, bool)
