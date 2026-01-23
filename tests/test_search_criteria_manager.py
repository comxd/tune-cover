"""
Tests for search criteria manager.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AlbumInfo, CoverInfo
from src.ui.search_criteria_manager import SearchCriteria, SearchCriteriaManager


@pytest.fixture
def mock_config():
    """Create a mock config object."""
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        "search.use_artist": True,
        "search.use_album": True,
        "search.use_year": False,
        "search.use_title": False,
    }.get(key, default)
    return config


@pytest.fixture
def regular_album(tmp_path):
    """Create a regular album with all metadata."""
    return AlbumInfo(
        path=tmp_path,
        artist="Led Zeppelin",
        album="Led Zeppelin IV",
        year="1971",
        track_count=8,
        cover=CoverInfo(),
        sample_file=tmp_path / "01 - Black Dog.flac",
    )


@pytest.fixture
def compilation_album(tmp_path):
    """Create a compilation album."""
    return AlbumInfo(
        path=tmp_path,
        artist="Various Artists",
        album="Now That's What I Call Music 50",
        year="2001",
        track_count=40,
        cover=CoverInfo(),
        sample_file=tmp_path / "01 - Some Song.mp3",
    )


@pytest.fixture
def single_file_album(tmp_path):
    """Create a single file album."""
    single_file = tmp_path / "Bohemian Rhapsody.mp3"
    single_file.touch()
    return AlbumInfo(
        path=single_file,
        artist="Queen",
        album="",  # Empty album
        year="1975",
        track_count=1,
        cover=CoverInfo(),
        sample_file=single_file,
    )


@pytest.fixture
def empty_metadata_album(tmp_path):
    """Create an album with mostly empty metadata."""
    return AlbumInfo(
        path=tmp_path,
        artist="",
        album="",
        year="",
        track_count=5,
        cover=CoverInfo(),
        sample_file=tmp_path / "track.mp3",
    )


class TestSearchCriteriaManager:
    """Tests for SearchCriteriaManager class."""

    def test_regular_album_enables_all_filled_fields(self, mock_config, regular_album):
        """Should enable checkboxes for fields with values (respecting config)."""
        manager = SearchCriteriaManager(mock_config)

        with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
            mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
            criteria = manager.compute_criteria(regular_album)

        assert criteria.artist_enabled is True
        assert criteria.artist_value == "Led Zeppelin"
        assert criteria.album_enabled is True
        assert criteria.album_value == "Led Zeppelin IV"
        # Year respects config: use_year=False by default, so disabled even with value
        assert criteria.year_enabled is False
        assert criteria.year_value == "1971"

    def test_empty_fields_are_unchecked(self, mock_config, empty_metadata_album):
        """Should uncheck checkboxes when fields are empty."""
        manager = SearchCriteriaManager(mock_config)

        with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
            mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
            criteria = manager.compute_criteria(empty_metadata_album)

        assert criteria.artist_enabled is False
        assert criteria.album_enabled is False
        assert criteria.year_enabled is False

    def test_compilation_unchecks_artist(self, mock_config, compilation_album):
        """Should uncheck artist for detected compilation."""
        manager = SearchCriteriaManager(mock_config)

        criteria = manager.compute_criteria(compilation_album)

        assert criteria.artist_enabled is False
        assert criteria.album_enabled is True
        assert criteria.is_compilation is True

    def test_single_file_prioritizes_artist_and_title(self, mock_config, single_file_album):
        """Should prioritize Artist + Title for single files."""
        manager = SearchCriteriaManager(mock_config)

        with patch.object(manager, "_extract_title", return_value="Bohemian Rhapsody"):
            with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
                mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
                criteria = manager.compute_criteria(single_file_album, is_single_file=True)

        assert criteria.artist_enabled is True
        assert criteria.title_enabled is True
        assert criteria.album_enabled is False  # Empty album, should be unchecked

    def test_single_file_uses_filename_fallback(self, mock_config, single_file_album):
        """Should use filename as title when metadata title is missing."""
        manager = SearchCriteriaManager(mock_config)

        # Mock to return None from metadata, so filename fallback is used
        with (
            patch.object(manager, "_get_title_from_metadata", return_value=None),
            patch(
                "src.ui.search_criteria_manager.extract_title_from_filename",
                return_value="Bohemian Rhapsody",
            ),
            patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect,
        ):
            mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
            criteria = manager.compute_criteria(single_file_album, is_single_file=True)

        assert criteria.title_value == "Bohemian Rhapsody"

    def test_caches_compilation_status_on_album(self, mock_config, regular_album):
        """Should cache compilation detection result on album."""
        manager = SearchCriteriaManager(mock_config)

        # First call - should detect
        with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
            mock_detect.return_value = MagicMock(is_compilation=False, reason="single_artist")
            manager.compute_criteria(regular_album)

        assert regular_album.is_compilation is False

        # Second call - should use cache
        with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
            mock_detect.return_value = MagicMock(is_compilation=True, reason="error")
            criteria = manager.compute_criteria(regular_album)

        # Should still be False (from cache)
        assert criteria.is_compilation is False
        # detect_compilation should not have been called again
        mock_detect.assert_not_called()

    def test_info_message_for_compilation(self, mock_config, compilation_album):
        """Should include info message when compilation detected."""
        manager = SearchCriteriaManager(mock_config)

        criteria = manager.compute_criteria(compilation_album)

        assert criteria.info_message is not None
        assert "compilation" in criteria.info_message.lower()


class TestSearchCriteria:
    """Tests for SearchCriteria dataclass."""

    def test_default_values(self):
        """Should have correct default values."""
        criteria = SearchCriteria(
            artist_enabled=True,
            artist_value="Artist",
            album_enabled=True,
            album_value="Album",
            year_enabled=False,
            year_value="",
            title_enabled=False,
            title_value="",
        )
        assert criteria.info_message is None
        assert criteria.is_compilation is False
        assert criteria.compilation_reason is None


class TestSingleFileLogic:
    """Tests for single file specific behavior."""

    def test_title_and_artist_both_enabled(self, mock_config, tmp_path):
        """When both title and artist exist, both should be enabled."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        album = AlbumInfo(
            path=single_file,
            artist="Queen",
            album="A Night at the Opera",
            year="1975",
            track_count=1,
            sample_file=single_file,
        )

        manager = SearchCriteriaManager(mock_config)

        with patch.object(manager, "_extract_title", return_value="Bohemian Rhapsody"):
            with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
                mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
                criteria = manager.compute_criteria(album, is_single_file=True)

        assert criteria.artist_enabled is True
        assert criteria.title_enabled is True
        # Album should be unchecked if title is present
        assert criteria.title_value == "Bohemian Rhapsody"

    def test_title_only_when_no_artist(self, mock_config, tmp_path):
        """When only title exists, artist should be disabled."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        album = AlbumInfo(
            path=single_file,
            artist="",  # No artist
            album="",
            year="",
            track_count=1,
            sample_file=single_file,
        )

        manager = SearchCriteriaManager(mock_config)

        with patch.object(manager, "_extract_title", return_value="Song Title"):
            with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
                mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
                criteria = manager.compute_criteria(album, is_single_file=True)

        assert criteria.artist_enabled is False
        assert criteria.title_enabled is True

    def test_title_with_different_album(self, mock_config, tmp_path):
        """When title exists with different album name, album should be enabled."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        album = AlbumInfo(
            path=single_file,
            artist="",  # No artist
            album="Greatest Hits",  # Different from title
            year="",
            track_count=1,
            sample_file=single_file,
        )

        manager = SearchCriteriaManager(mock_config)

        with patch.object(manager, "_extract_title", return_value="Song Title"):
            with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
                mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
                criteria = manager.compute_criteria(album, is_single_file=True)

        assert criteria.artist_enabled is False
        assert criteria.title_enabled is True
        assert criteria.album_enabled is True  # Different from title

    def test_artist_only_with_album(self, mock_config, tmp_path):
        """When artist exists but no title, should use album."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        album = AlbumInfo(
            path=single_file,
            artist="Queen",
            album="Greatest Hits",
            year="",
            track_count=1,
            sample_file=single_file,
        )

        manager = SearchCriteriaManager(mock_config)

        with patch.object(manager, "_extract_title", return_value=""):  # No title
            with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
                mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
                criteria = manager.compute_criteria(album, is_single_file=True)

        assert criteria.artist_enabled is True
        assert criteria.title_enabled is False
        assert criteria.album_enabled is True

    def test_artist_only_without_album(self, mock_config, tmp_path):
        """When artist exists but no title or album."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        album = AlbumInfo(
            path=single_file,
            artist="Queen",
            album="",  # No album
            year="",
            track_count=1,
            sample_file=single_file,
        )

        manager = SearchCriteriaManager(mock_config)

        with patch.object(manager, "_extract_title", return_value=""):  # No title
            with patch("src.ui.search_criteria_manager.detect_compilation") as mock_detect:
                mock_detect.return_value = MagicMock(is_compilation=False, reason="test")
                criteria = manager.compute_criteria(album, is_single_file=True)

        assert criteria.artist_enabled is True
        assert criteria.title_enabled is False
        assert criteria.album_enabled is False


class TestExtractTitle:
    """Tests for title extraction."""

    def test_no_sample_file_returns_empty(self, mock_config, tmp_path):
        """Should return empty string when no sample file."""
        album = AlbumInfo(
            path=tmp_path,
            artist="Artist",
            album="Album",
            year="",
            track_count=1,
            sample_file=None,  # No sample file
        )

        manager = SearchCriteriaManager(mock_config)
        title = manager._extract_title(album)

        assert title == ""

    def test_uses_metadata_title_first(self, mock_config, tmp_path):
        """Should prefer metadata title over filename."""
        single_file = tmp_path / "01 - Track Name.mp3"
        single_file.touch()

        album = AlbumInfo(
            path=single_file,
            artist="Artist",
            album="Album",
            year="",
            track_count=1,
            sample_file=single_file,
        )

        manager = SearchCriteriaManager(mock_config)

        with patch.object(manager, "_get_title_from_metadata", return_value="Metadata Title"):
            title = manager._extract_title(album)

        assert title == "Metadata Title"

    def test_falls_back_to_filename(self, mock_config, tmp_path):
        """Should fall back to filename when no metadata title."""
        single_file = tmp_path / "Song Name.mp3"
        single_file.touch()

        album = AlbumInfo(
            path=single_file,
            artist="Artist",
            album="Album",
            year="",
            track_count=1,
            sample_file=single_file,
        )

        manager = SearchCriteriaManager(mock_config)

        with (
            patch.object(manager, "_get_title_from_metadata", return_value=None),
            patch(
                "src.ui.search_criteria_manager.extract_title_from_filename",
                return_value="Song Name",
            ),
        ):
            title = manager._extract_title(album)

        assert title == "Song Name"


class TestGetTitleFromMetadata:
    """Tests for _get_title_from_metadata method."""

    def test_extracts_title_as_list(self, mock_config, tmp_path):
        """Should extract title when returned as list."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        manager = SearchCriteriaManager(mock_config)

        mock_audio = MagicMock()
        mock_audio.tags = {"title": ["Test Title"]}

        with patch("src.ui.search_criteria_manager.MutagenFile", return_value=mock_audio):
            title = manager._get_title_from_metadata(single_file)

        assert title == "Test Title"

    def test_extracts_title_as_string(self, mock_config, tmp_path):
        """Should extract title when returned as string."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        manager = SearchCriteriaManager(mock_config)

        mock_audio = MagicMock()
        mock_audio.tags = {"title": "Test Title"}

        with patch("src.ui.search_criteria_manager.MutagenFile", return_value=mock_audio):
            title = manager._get_title_from_metadata(single_file)

        assert title == "Test Title"

    def test_returns_none_when_no_title_tag(self, mock_config, tmp_path):
        """Should return None when no title tag."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        manager = SearchCriteriaManager(mock_config)

        mock_audio = MagicMock()
        mock_audio.tags = {"artist": ["Artist"]}

        with patch("src.ui.search_criteria_manager.MutagenFile", return_value=mock_audio):
            title = manager._get_title_from_metadata(single_file)

        assert title is None

    def test_handles_exception(self, mock_config, tmp_path):
        """Should return None on exception."""
        single_file = tmp_path / "song.mp3"
        single_file.touch()

        manager = SearchCriteriaManager(mock_config)

        with patch("src.ui.search_criteria_manager.MutagenFile", side_effect=OSError("Error")):
            title = manager._get_title_from_metadata(single_file)

        assert title is None
