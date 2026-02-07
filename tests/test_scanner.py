"""
Tests for the music library scanner.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AlbumInfo, CoverInfo
from src.core.scanner import AUDIO_EXTENSIONS, COVER_EXTENSIONS, COVER_FILENAMES, MusicScanner


class TestMusicScannerInit:
    """Tests for MusicScanner initialization."""

    def test_init_default(self):
        """Test default initialization."""
        scanner = MusicScanner()
        assert scanner.exclude_patterns == []
        assert scanner.progress_callback is None
        assert scanner.cancelled_callback is None

    def test_init_with_excludes(self):
        """Test initialization with exclude patterns."""
        excludes = ["Podcasts", "Audiobooks"]
        scanner = MusicScanner(exclude_patterns=excludes)
        assert scanner.exclude_patterns == excludes

    def test_init_with_progress_callback(self, progress_tracker):
        """Test initialization with progress callback."""
        scanner = MusicScanner(progress_callback=progress_tracker.callback)
        assert scanner.progress_callback == progress_tracker.callback

    def test_init_with_cancelled_callback(self, cancellation_controller):
        """Test initialization with cancellation callback."""
        scanner = MusicScanner(cancelled_callback=cancellation_controller.callback)
        assert scanner.cancelled_callback == cancellation_controller.callback

    def test_init_with_all_options(self, progress_tracker, cancellation_controller):
        """Test initialization with all options."""
        excludes = ["test"]
        scanner = MusicScanner(
            exclude_patterns=excludes,
            progress_callback=progress_tracker.callback,
            cancelled_callback=cancellation_controller.callback,
        )
        assert scanner.exclude_patterns == excludes
        assert scanner.progress_callback == progress_tracker.callback
        assert scanner.cancelled_callback == cancellation_controller.callback


class TestShouldExclude:
    """Tests for _should_exclude method."""

    def test_exclude_hidden_directories(self, scanner):
        """Test that hidden directories are excluded."""
        assert scanner._should_exclude(".hidden")
        assert scanner._should_exclude(".config")
        assert scanner._should_exclude(".git")
        assert scanner._should_exclude(".")
        assert scanner._should_exclude("..")

    def test_exclude_regular_directories_not_excluded(self, scanner):
        """Test that regular directories are not excluded."""
        assert not scanner._should_exclude("Music")
        assert not scanner._should_exclude("Albums")
        assert not scanner._should_exclude("Rock")

    def test_exclude_patterns_case_insensitive(self, scanner_with_excludes):
        """Test pattern-based exclusion is case-insensitive."""
        assert scanner_with_excludes._should_exclude("Podcasts")
        assert scanner_with_excludes._should_exclude("PODCASTS")
        assert scanner_with_excludes._should_exclude("podcasts")
        assert scanner_with_excludes._should_exclude("PoDcAsTs")

    def test_exclude_patterns_partial_match(self, scanner_with_excludes):
        """Test pattern-based exclusion with partial matches."""
        assert scanner_with_excludes._should_exclude("My Podcasts")
        assert scanner_with_excludes._should_exclude("Audiobooks Collection")
        # Note: 'podcasts' pattern doesn't match 'podcast_files' (no 's')
        assert scanner_with_excludes._should_exclude("podcasts_folder")

    def test_exclude_patterns_no_match(self, scanner_with_excludes):
        """Test that non-matching directories are not excluded."""
        assert not scanner_with_excludes._should_exclude("Rock Music")
        assert not scanner_with_excludes._should_exclude("Albums")


class TestFindAlbumFolders:
    """Tests for _find_album_folders method."""

    def test_find_folders_basic_library(self, scanner, music_library):
        """Test finding album folders in a basic library."""
        folders = scanner._find_album_folders(music_library)
        assert len(folders) == 3

        folder_names = {f.name for f in folders}
        assert "Album1" in folder_names
        assert "Album2" in folder_names
        assert "Album3" in folder_names

    def test_find_folders_empty_library(self, scanner, empty_library):
        """Test finding album folders in an empty library."""
        folders = scanner._find_album_folders(empty_library)
        assert len(folders) == 0

    def test_find_folders_excludes_hidden(self, scanner, library_with_hidden):
        """Test that hidden folders are excluded."""
        folders = scanner._find_album_folders(library_with_hidden)
        assert len(folders) == 1
        assert folders[0].name == "Album"

    def test_find_folders_nested_structure(self, scanner, nested_library):
        """Test finding folders in deeply nested structure."""
        folders = scanner._find_album_folders(nested_library)
        assert len(folders) == 1
        assert folders[0].name == "CD1"

    def test_find_folders_with_exclude_patterns(self, tmp_path):
        """Test that exclude patterns filter out folders."""
        # Create library with podcasts folder
        album = tmp_path / "Music" / "Album"
        album.mkdir(parents=True)
        (album / "track.mp3").write_bytes(b"fake data")

        podcast = tmp_path / "My Podcasts" / "Episode"
        podcast.mkdir(parents=True)
        (podcast / "episode.mp3").write_bytes(b"fake data")

        scanner = MusicScanner(exclude_patterns=["podcast"])
        folders = scanner._find_album_folders(tmp_path)

        assert len(folders) == 1
        assert folders[0].name == "Album"

    def test_find_folders_nonexistent_directory(self, scanner, tmp_path):
        """Test scanning a nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"
        folders = scanner._find_album_folders(nonexistent)
        assert len(folders) == 0

    def test_find_folders_permission_denied(self, scanner, tmp_path, monkeypatch):
        """Test handling of permission denied errors."""

        def mock_walk(*args, **kwargs):
            raise PermissionError("Permission denied")

        monkeypatch.setattr(os, "walk", mock_walk)
        folders = scanner._find_album_folders(tmp_path)
        assert len(folders) == 0

    @pytest.mark.parametrize("extension", list(AUDIO_EXTENSIONS))
    def test_find_folders_all_audio_extensions(self, scanner, tmp_path, extension):
        """Test that all audio extensions are recognized."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / f"track{extension}").write_bytes(b"fake data")

        folders = scanner._find_album_folders(tmp_path)
        assert len(folders) == 1
        assert folders[0].name == "Album"


class TestScanAlbumFolder:
    """Tests for _scan_album_folder method."""

    def test_scan_folder_basic(self, scanner, music_library):
        """Test scanning a basic album folder."""
        album_folder = music_library / "Artist1" / "Album1"

        with (
            patch.object(
                scanner,
                "_extract_metadata",
                return_value={"artist": "Artist1", "album": "Album1", "year": "2020"},
            ),
            patch.object(scanner, "_check_embedded_cover", return_value=False),
        ):
            albums = scanner._scan_album_folder(album_folder)

        # Returns list now, should have one album
        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.path == album_folder
        assert album_info.track_count == 2
        assert ".mp3" in album_info.formats
        assert album_info.cover.has_folder is True
        assert album_info.cover.folder_file == "cover.jpg"

    def test_scan_folder_no_audio_files(self, scanner, tmp_path):
        """Test scanning a folder with no audio files."""
        empty_folder = tmp_path / "empty"
        empty_folder.mkdir()
        (empty_folder / "readme.txt").write_text("No music here")

        albums = scanner._scan_album_folder(empty_folder)
        assert albums == []  # Returns empty list instead of None

    def test_scan_folder_permission_denied(self, scanner, tmp_path, monkeypatch):
        """Test handling of permission denied when scanning folder."""
        album_folder = tmp_path / "protected"
        album_folder.mkdir()
        (album_folder / "track.mp3").write_bytes(b"fake data")

        def mock_iterdir(self):
            raise PermissionError("Permission denied")

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)
        albums = scanner._scan_album_folder(album_folder)
        assert albums == []  # Returns empty list instead of None

    def test_scan_folder_oserror(self, scanner, tmp_path, monkeypatch):
        """Test handling of OSError when scanning folder."""
        album_folder = tmp_path / "error"
        album_folder.mkdir()

        def mock_iterdir(self):
            raise OSError("Generic OS error")

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)
        albums = scanner._scan_album_folder(album_folder)
        assert albums == []  # Returns empty list instead of None

    def test_scan_folder_mixed_formats(self, scanner, tmp_path):
        """Test scanning folder with mixed audio formats."""
        album = tmp_path / "MixedFormats"
        album.mkdir()
        (album / "track1.mp3").write_bytes(b"fake mp3")
        (album / "track2.flac").write_bytes(b"fake flac")
        (album / "track3.ogg").write_bytes(b"fake ogg")

        # All files have same album tag -> grouped as one album
        with (
            patch.object(
                scanner,
                "_extract_metadata",
                return_value={"artist": "Artist", "album": "Album", "year": "2020"},
            ),
            patch.object(scanner, "_check_embedded_cover", return_value=False),
        ):
            albums = scanner._scan_album_folder(album)

        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.track_count == 3
        assert set(album_info.formats) == {".mp3", ".flac", ".ogg"}

    def test_scan_folder_returns_sample_file(self, scanner, tmp_path):
        """Test that scan returns a sample file."""
        album = tmp_path / "Album"
        album.mkdir()
        track = album / "track.mp3"
        track.write_bytes(b"fake mp3")

        # Single file -> individual file album
        with (
            patch.object(
                scanner, "_extract_metadata", return_value={"artist": "Artist", "album": "Album"}
            ),
            patch.object(scanner, "_file_has_embedded_cover", return_value=False),
        ):
            with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                albums = scanner._scan_album_folder(album)

        assert len(albums) == 1
        assert albums[0].sample_file == track

    def test_scan_folder_with_embedded_cover(self, scanner, tmp_path):
        """Test scanning folder with embedded cover detected."""
        album = tmp_path / "EmbeddedCover"
        album.mkdir()
        (album / "track1.mp3").write_bytes(b"fake mp3")
        (album / "track2.mp3").write_bytes(b"fake mp3")

        # Two files with same album -> album, not individual files
        with (
            patch.object(
                scanner, "_extract_metadata", return_value={"artist": "Artist", "album": "Album"}
            ),
            patch.object(scanner, "_check_embedded_cover", return_value=True),
        ):
            albums = scanner._scan_album_folder(album)

        assert len(albums) == 1
        assert albums[0].cover.has_embedded is True


class TestCheckEmbeddedCover:
    """Tests for _check_embedded_cover method."""

    def test_check_embedded_cover_found_in_first_file(self, scanner, tmp_path):
        """Test detection when first file has cover."""
        audio_files = [tmp_path / "track1.mp3", tmp_path / "track2.mp3"]
        for f in audio_files:
            f.write_bytes(b"fake")

        with patch.object(scanner, "_file_has_embedded_cover", side_effect=[True, False]):
            result = scanner._check_embedded_cover(audio_files)

        assert result is True

    def test_check_embedded_cover_not_found(self, scanner, tmp_path):
        """Test detection when no file has cover."""
        audio_files = [tmp_path / f"track{i}.mp3" for i in range(3)]
        for f in audio_files:
            f.write_bytes(b"fake")

        with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
            result = scanner._check_embedded_cover(audio_files)

        assert result is False

    def test_check_embedded_cover_checks_max_three_files(self, scanner, tmp_path):
        """Test that only first three files are checked."""
        audio_files = [tmp_path / f"track{i}.mp3" for i in range(10)]
        for f in audio_files:
            f.write_bytes(b"fake")

        call_count = 0

        def mock_has_cover(path):
            nonlocal call_count
            call_count += 1
            return False

        with patch.object(scanner, "_file_has_embedded_cover", side_effect=mock_has_cover):
            scanner._check_embedded_cover(audio_files)

        assert call_count == 3

    def test_check_embedded_cover_empty_list(self, scanner):
        """Test with empty file list."""
        result = scanner._check_embedded_cover([])
        assert result is False


class TestFileHasEmbeddedCover:
    """Tests for _file_has_embedded_cover method."""

    def test_file_has_embedded_cover_flac_with_cover(self, scanner, tmp_path):
        """Test FLAC file with embedded cover."""
        from mutagen.flac import FLAC

        audio_file = tmp_path / "test.flac"
        audio_file.write_bytes(b"fake")

        mock_flac = MagicMock(spec=FLAC)
        mock_flac.pictures = [MagicMock()]

        with patch("src.core.scanner.MutagenFile", return_value=mock_flac):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is True

    def test_file_has_embedded_cover_flac_without_cover(self, scanner, tmp_path):
        """Test FLAC file without embedded cover."""
        from mutagen.flac import FLAC

        audio_file = tmp_path / "test.flac"
        audio_file.write_bytes(b"fake")

        mock_flac = MagicMock(spec=FLAC)
        mock_flac.pictures = []

        with patch("src.core.scanner.MutagenFile", return_value=mock_flac):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is False

    def test_file_has_embedded_cover_mp3_with_apic(self, scanner, tmp_path):
        """Test MP3 file with APIC frame."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_mp3 = MagicMock()
        mock_mp3.tags = MagicMock()
        mock_mp3.tags.keys.return_value = ["APIC:Cover", "TIT2", "TPE1"]

        with patch("src.core.scanner.MutagenFile", return_value=mock_mp3):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is True

    def test_file_has_embedded_cover_mp3_without_apic(self, scanner, tmp_path):
        """Test MP3 file without APIC frame."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_mp3 = MagicMock()
        mock_mp3.tags = MagicMock()
        mock_mp3.tags.keys.return_value = ["TIT2", "TPE1", "TALB"]
        # Explicitly set pictures to empty to prevent generic check from passing
        mock_mp3.pictures = []

        with patch("src.core.scanner.MutagenFile", return_value=mock_mp3):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is False

    def test_file_has_embedded_cover_mp4_with_covr(self, scanner, tmp_path):
        """Test M4A/MP4 file with covr atom."""
        from mutagen.mp4 import MP4

        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_mp4 = MagicMock(spec=MP4)
        mock_mp4.tags = {"covr": [b"image_data"]}

        with patch("src.core.scanner.MutagenFile", return_value=mock_mp4):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is True

    def test_file_has_embedded_cover_mp4_without_covr(self, scanner, tmp_path):
        """Test M4A/MP4 file without covr atom."""
        from mutagen.mp4 import MP4

        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"fake")

        mock_mp4 = MagicMock(spec=MP4)
        mock_mp4.tags = {}

        with patch("src.core.scanner.MutagenFile", return_value=mock_mp4):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is False

    def test_file_has_embedded_cover_ogg_with_picture(self, scanner, tmp_path):
        """Test OGG file with metadata_block_picture."""
        from mutagen.oggvorbis import OggVorbis

        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake")

        # Create mock without spec to allow __contains__ override
        mock_ogg = MagicMock()
        # Make isinstance check work
        mock_ogg.__class__ = OggVorbis
        mock_ogg.__contains__ = MagicMock(return_value=True)
        mock_ogg.pictures = []  # Prevent generic check

        with (
            patch("src.core.scanner.MutagenFile", return_value=mock_ogg),
            patch(
                "src.core.scanner.isinstance",
                side_effect=lambda obj, cls: cls == OggVorbis
                if obj is mock_ogg
                else isinstance(obj, cls),
            ),
        ):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is True

    def test_file_has_embedded_cover_ogg_without_picture(self, scanner, tmp_path):
        """Test OGG file without metadata_block_picture."""
        from mutagen.oggvorbis import OggVorbis

        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake")

        # Create mock without spec to allow __contains__ override
        mock_ogg = MagicMock()
        mock_ogg.__class__ = OggVorbis
        mock_ogg.__contains__ = MagicMock(return_value=False)
        mock_ogg.pictures = []  # Prevent generic check

        with (
            patch("src.core.scanner.MutagenFile", return_value=mock_ogg),
            patch(
                "src.core.scanner.isinstance",
                side_effect=lambda obj, cls: cls == OggVorbis
                if obj is mock_ogg
                else isinstance(obj, cls),
            ),
        ):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is False

    def test_file_has_embedded_cover_none_audio(self, scanner, tmp_path):
        """Test handling of None return from MutagenFile."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        with patch("src.core.scanner.MutagenFile", return_value=None):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is False

    def test_file_has_embedded_cover_exception(self, scanner, tmp_path):
        """Test handling of exceptions during cover check."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        with patch("src.core.scanner.MutagenFile", side_effect=OSError("Read error")):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is False

    def test_file_has_embedded_cover_no_tags(self, scanner, tmp_path):
        """Test file with no tags."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = None
        # Explicitly set pictures to empty to prevent generic check from passing
        mock_audio.pictures = []

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            result = scanner._file_has_embedded_cover(audio_file)

        assert result is False


class TestWmaTagIterationRegression:
    """
    Regression tests for WMA crash: ASFTags inherits from list.

    Bug: When checking for embedded covers in WMA files, iterating
    `for key in tags` yields (name, value) tuples from ASFTags (which
    inherits from list), causing `key.startswith("APIC")` to crash
    with AttributeError.

    Fix: Use explicit `tags.keys()` which returns string keys for all
    mutagen tag types, including ASFTags.

    See: src/core/scanner.py:654
    """

    def _make_asf_like_tags(self, keys: list[str]):
        """Create a mock that simulates ASFTags behavior.

        ASFTags inherits from list: direct iteration yields tuples,
        but .keys() returns string keys.
        """
        tags = MagicMock()
        # Simulate ASFTags: __iter__ yields (name, value) tuples, NOT string keys
        tags.__iter__ = lambda self: iter([(k, MagicMock()) for k in keys])
        # .keys() correctly returns string keys
        tags.keys.return_value = keys
        return tags

    def test_file_has_embedded_cover_wma_with_apic(self, scanner, tmp_path):
        """
        Regression: _file_has_embedded_cover must use tags.keys() for WMA files.

        Without .keys(), iterating ASFTags yields tuples and
        tuple.startswith("APIC") raises AttributeError.
        """
        wma_file = tmp_path / "test.wma"
        wma_file.write_bytes(b"fake")

        tags = self._make_asf_like_tags(["APIC:Cover", "WM/Title"])

        mock_audio = MagicMock()
        mock_audio.tags = tags
        mock_audio.pictures = []

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            result = scanner._file_has_embedded_cover(wma_file)

        assert result is True
        # Verify .keys() was called (not direct iteration)
        tags.keys.assert_called()

    def test_file_has_embedded_cover_wma_without_apic(self, scanner, tmp_path):
        """Regression: WMA file without APIC should return False, not crash."""
        wma_file = tmp_path / "test.wma"
        wma_file.write_bytes(b"fake")

        tags = self._make_asf_like_tags(["WM/Title", "WM/AlbumTitle"])

        mock_audio = MagicMock()
        mock_audio.tags = tags
        mock_audio.pictures = []

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            result = scanner._file_has_embedded_cover(wma_file)

        assert result is False


class TestExtractMetadata:
    """Tests for _extract_metadata method."""

    def test_extract_metadata_basic(self, scanner, tmp_path):
        """Test basic metadata extraction."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = {"artist": ["Test Artist"], "album": ["Test Album"], "date": ["2020"]}

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] == "Test Artist"
        assert metadata["album"] == "Test Album"
        assert metadata["year"] == "2020"

    def test_extract_metadata_albumartist_priority(self, scanner, tmp_path):
        """Test that albumartist takes priority over artist."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = {
            "albumartist": ["Album Artist"],
            "artist": ["Track Artist"],
            "album": ["Test Album"],
        }

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] == "Album Artist"

    def test_extract_metadata_year_formats(self, scanner, tmp_path):
        """Test extraction of year from various date formats."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        # Full date format
        mock_audio = MagicMock()
        mock_audio.tags = {"date": ["2020-05-15"]}

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            metadata = scanner._extract_metadata(audio_file)

        assert metadata["year"] == "2020"

    def test_extract_metadata_year_key(self, scanner, tmp_path):
        """Test extraction from 'year' tag instead of 'date'."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = {"year": ["2019"]}

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            metadata = scanner._extract_metadata(audio_file)

        assert metadata["year"] == "2019"

    def test_extract_metadata_originaldate(self, scanner, tmp_path):
        """Test extraction from 'originaldate' tag."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = {"originaldate": ["1985"]}

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            metadata = scanner._extract_metadata(audio_file)

        assert metadata["year"] == "1985"

    def test_extract_metadata_no_tags(self, scanner, tmp_path):
        """Test extraction from file with no tags (and path doesn't match patterns)."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = None

        # Mock path parser to return empty results (no pattern match)
        mock_parsed = MagicMock()
        mock_parsed.artist = None
        mock_parsed.album = None
        mock_parsed.year = None

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            with patch("src.core.scanner.parse_path", return_value=mock_parsed):
                metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] is None
        assert metadata["album"] is None
        assert metadata["year"] is None

    def test_extract_metadata_none_file(self, scanner, tmp_path):
        """Test handling of None return from MutagenFile (and path doesn't match patterns)."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        # Mock path parser to return empty results (no pattern match)
        mock_parsed = MagicMock()
        mock_parsed.artist = None
        mock_parsed.album = None
        mock_parsed.year = None

        with patch("src.core.scanner.MutagenFile", return_value=None):
            with patch("src.core.scanner.parse_path", return_value=mock_parsed):
                metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] is None
        assert metadata["album"] is None
        assert metadata["year"] is None

    def test_extract_metadata_exception(self, scanner, tmp_path):
        """Test handling of exceptions during metadata extraction (and path doesn't match patterns)."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        # Mock path parser to return empty results (no pattern match)
        mock_parsed = MagicMock()
        mock_parsed.artist = None
        mock_parsed.album = None
        mock_parsed.year = None

        with patch("src.core.scanner.MutagenFile", side_effect=OSError("Read error")):
            with patch("src.core.scanner.parse_path", return_value=mock_parsed):
                metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] is None
        assert metadata["album"] is None
        assert metadata["year"] is None

    def test_extract_metadata_empty_tags(self, scanner, tmp_path):
        """Test extraction from file with empty tags (and path doesn't match patterns)."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = {}

        # Mock path parser to return empty results (no pattern match)
        mock_parsed = MagicMock()
        mock_parsed.artist = None
        mock_parsed.album = None
        mock_parsed.year = None

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            with patch("src.core.scanner.parse_path", return_value=mock_parsed):
                metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] is None
        assert metadata["album"] is None
        assert metadata["year"] is None

    def test_extract_metadata_performer_fallback(self, scanner, tmp_path):
        """Test fallback to 'performer' tag for artist."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = {"performer": ["The Performer"]}

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] == "The Performer"

    def test_extract_metadata_path_fallback(self, scanner, tmp_path):
        """Test path parsing fallback when audio tags are missing."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = None  # No tags

        # Mock path parser to return parsed metadata
        mock_parsed = MagicMock()
        mock_parsed.artist = "Path Artist"
        mock_parsed.album = "Path Album"
        mock_parsed.year = "2020"

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            with patch("src.core.scanner.parse_path", return_value=mock_parsed):
                metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] == "Path Artist"
        assert metadata["album"] == "Path Album"
        assert metadata["year"] == "2020"
        assert metadata["metadata_source"] == "path"

    def test_extract_metadata_tags_override_path(self, scanner, tmp_path):
        """Test that audio tags take priority over path parsing."""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        mock_audio = MagicMock()
        mock_audio.tags = {
            "artist": ["Tag Artist"],
            "album": ["Tag Album"],
        }

        # This should not be called since tags exist
        mock_parsed = MagicMock()
        mock_parsed.artist = "Path Artist"
        mock_parsed.album = "Path Album"

        with patch("src.core.scanner.MutagenFile", return_value=mock_audio):
            with patch("src.core.scanner.parse_path", return_value=mock_parsed) as mock_parse:
                metadata = scanner._extract_metadata(audio_file)

        assert metadata["artist"] == "Tag Artist"
        assert metadata["album"] == "Tag Album"
        assert metadata["metadata_source"] == "tags"
        # parse_path should not be called when tags exist
        mock_parse.assert_not_called()


class TestCheckFolderCover:
    """Tests for _check_folder_cover method."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("cover.jpg", True),
            ("folder.jpg", True),
            ("front.png", True),
            ("album.jpeg", True),
            ("albumart.gif", True),
            ("COVER.JPG", True),  # Case insensitive
            ("Front.PNG", True),
            ("cover_large.jpg", True),  # Partial match
            ("my_albumart.png", True),
            ("random.jpg", False),  # Not a recognized cover name
            ("cover.txt", False),  # Wrong extension
        ],
    )
    def test_check_folder_cover_various_names(self, scanner, tmp_path, filename, expected):
        """Test detection of various cover filename patterns."""
        folder = tmp_path / "album"
        folder.mkdir()
        (folder / filename).write_bytes(b"fake image")

        has_cover, cover_file = scanner._check_folder_cover(folder)
        assert has_cover is expected
        if expected:
            assert cover_file == filename

    def test_check_folder_cover_none(self, scanner, tmp_path):
        """Test folder with no cover image."""
        folder = tmp_path / "album"
        folder.mkdir()
        (folder / "track.mp3").write_bytes(b"fake")

        has_cover, cover_file = scanner._check_folder_cover(folder)
        assert has_cover is False
        assert cover_file is None

    def test_check_folder_cover_permission_denied(self, scanner, tmp_path, monkeypatch):
        """Test handling of permission denied when checking folder cover."""
        folder = tmp_path / "protected"
        folder.mkdir()

        def mock_iterdir(self):
            raise PermissionError("Permission denied")

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)
        has_cover, cover_file = scanner._check_folder_cover(folder)
        assert has_cover is False
        assert cover_file is None

    def test_check_folder_cover_oserror(self, scanner, tmp_path, monkeypatch):
        """Test handling of OSError when checking folder cover."""
        folder = tmp_path / "error"
        folder.mkdir()

        def mock_iterdir(self):
            raise OSError("Generic OS error")

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)
        has_cover, cover_file = scanner._check_folder_cover(folder)
        assert has_cover is False
        assert cover_file is None

    @pytest.mark.parametrize("extension", list(COVER_EXTENSIONS))
    def test_check_folder_cover_all_extensions(self, scanner, tmp_path, extension):
        """Test that all image extensions are recognized."""
        folder = tmp_path / "album"
        folder.mkdir()
        (folder / f"cover{extension}").write_bytes(b"fake image")

        has_cover, cover_file = scanner._check_folder_cover(folder)
        assert has_cover is True

    def test_check_folder_cover_first_match_returned(self, scanner, tmp_path):
        """Test that first matching cover is returned."""
        folder = tmp_path / "album"
        folder.mkdir()
        # Create multiple cover files
        (folder / "cover.jpg").write_bytes(b"fake")
        (folder / "folder.png").write_bytes(b"fake")

        has_cover, cover_file = scanner._check_folder_cover(folder)
        assert has_cover is True
        assert cover_file in ["cover.jpg", "folder.png"]


class TestScanLibrary:
    """Tests for scan_library method."""

    def test_scan_library_basic(self, tmp_path):
        """Test scanning a basic library.

        Bug fix: Single files now have path=filepath, not path=folder.
        This allows correct handling of individual files in shared folders.
        """
        # Create simple library
        album = tmp_path / "Artist" / "Album"
        album.mkdir(parents=True)
        track_file = album / "track.mp3"
        track_file.write_bytes(b"fake mp3")

        scanner = MusicScanner()

        with (
            patch.object(
                scanner,
                "_extract_metadata",
                return_value={"artist": "Artist", "album": "Album", "year": "2020"},
            ),
            patch.object(scanner, "_file_has_embedded_cover", return_value=False),
            patch.object(scanner, "_check_folder_cover", return_value=(False, None)),
        ):
            albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        # Single file: path is the file itself, not the folder
        assert albums[0].path == track_file

    def test_scan_library_multiple_albums(self, scanner, music_library):
        """Test scanning library with multiple albums."""

        # Return album metadata so files are grouped as albums
        def mock_extract(filepath):
            # Extract album name from path
            album_name = filepath.parent.name
            return {"artist": "Artist", "album": album_name, "year": "2020"}

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                albums = scanner.scan_library(music_library)

        assert len(albums) == 3

    def test_scan_library_empty(self, scanner, empty_library):
        """Test scanning an empty library."""
        albums = scanner.scan_library(empty_library)
        assert len(albums) == 0

    def test_scan_library_progress_callback(self, tmp_path, progress_tracker):
        """Test that progress callback is called correctly."""
        # Create library with 3 albums
        for i in range(3):
            album = tmp_path / f"Artist{i}" / f"Album{i}"
            album.mkdir(parents=True)
            (album / "track.mp3").write_bytes(b"fake mp3")

        scanner = MusicScanner(progress_callback=progress_tracker.callback)

        with patch.object(scanner, "_extract_metadata", return_value={}):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                scanner.scan_library(tmp_path)

        assert len(progress_tracker.calls) == 3
        # Check progress increments
        assert progress_tracker.calls[0][0] == 1
        assert progress_tracker.calls[1][0] == 2
        assert progress_tracker.calls[2][0] == 3
        # Check total is consistent
        assert all(call[1] == 3 for call in progress_tracker.calls)

    def test_scan_library_cancellation(self, tmp_path, cancellation_controller):
        """Test that scan can be cancelled."""
        # Create library with 10 albums
        for i in range(10):
            album = tmp_path / f"Artist{i}" / f"Album{i}"
            album.mkdir(parents=True)
            (album / "track.mp3").write_bytes(b"fake mp3")

        # Cancel after 3 albums
        scan_count = 0

        def cancel_after_three():
            nonlocal scan_count
            return scan_count >= 3

        scanner = MusicScanner(cancelled_callback=cancel_after_three)

        def count_scans(*args, **kwargs):
            nonlocal scan_count
            scan_count += 1
            return {}

        with patch.object(scanner, "_extract_metadata", side_effect=count_scans):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                albums = scanner.scan_library(tmp_path)

        # Should stop after 3 albums
        assert len(albums) <= 4  # May process up to 4 due to timing

    def test_scan_library_cancellation_immediate(self, tmp_path):
        """Test immediate cancellation."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track.mp3").write_bytes(b"fake mp3")

        scanner = MusicScanner(cancelled_callback=lambda: True)
        albums = scanner.scan_library(tmp_path)

        assert len(albums) == 0

    def test_scan_library_with_excludes(self, tmp_path):
        """Test that excluded folders are not scanned.

        Bug fix: Single files now have path=filepath, not path=folder.
        """
        # Create regular album
        album = tmp_path / "Music" / "Album"
        album.mkdir(parents=True)
        track_file = album / "track.mp3"
        track_file.write_bytes(b"fake mp3")

        # Create excluded folder
        podcast = tmp_path / "Podcasts" / "Episode"
        podcast.mkdir(parents=True)
        (podcast / "episode.mp3").write_bytes(b"fake mp3")

        scanner = MusicScanner(exclude_patterns=["podcast"])

        with patch.object(scanner, "_extract_metadata", return_value={}):
            with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
                with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                    albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        # Single file: path is the file itself, not the folder
        assert albums[0].path == track_file


class TestWalkErrorHandler:
    """Tests for _walk_error_handler method."""

    def test_walk_error_handler_logs_warning(self, scanner, caplog):
        """Test that walk errors are logged."""
        import logging

        caplog.set_level(logging.WARNING)

        error = OSError(13, "Permission denied", "/path/to/file")
        scanner._walk_error_handler(error)

        assert "Access error" in caplog.text
        assert "/path/to/file" in caplog.text


class TestEmptyFoldersHandling:
    """Tests for handling of empty folders."""

    def test_empty_folder_ignored(self, scanner, tmp_path):
        """Test that empty folders are ignored."""
        (tmp_path / "EmptyFolder").mkdir()
        albums = scanner.scan_library(tmp_path)
        assert len(albums) == 0

    def test_folder_with_only_images_ignored(self, scanner, tmp_path):
        """Test that folders with only images are ignored."""
        folder = tmp_path / "ImagesOnly"
        folder.mkdir()
        (folder / "cover.jpg").write_bytes(b"fake image")
        (folder / "back.png").write_bytes(b"fake image")

        albums = scanner.scan_library(tmp_path)
        assert len(albums) == 0

    def test_folder_with_only_text_ignored(self, scanner, tmp_path):
        """Test that folders with only text files are ignored."""
        folder = tmp_path / "TextOnly"
        folder.mkdir()
        (folder / "info.txt").write_text("Album info")
        (folder / "playlist.m3u").write_text("#EXTM3U")

        albums = scanner.scan_library(tmp_path)
        assert len(albums) == 0


class TestNonAudioFilesHandling:
    """Tests for handling of non-audio files."""

    def test_non_audio_files_not_counted(self, scanner, library_with_non_audio):
        """Test that non-audio files are not counted as tracks."""
        with patch.object(scanner, "_extract_metadata", return_value={}):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                albums = scanner.scan_library(library_with_non_audio)

        assert len(albums) == 1
        # Only the mp3 file should be counted
        assert albums[0].track_count == 1
        assert albums[0].formats == [".mp3"]

    def test_non_audio_extensions_ignored(self, scanner, tmp_path):
        """Test that non-audio file extensions are ignored."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track.mp3").write_bytes(b"fake mp3")
        (album / "movie.mp4").write_bytes(b"fake video")  # .mp4 is in AUDIO_EXTENSIONS
        (album / "doc.pdf").write_bytes(b"fake pdf")

        # Return album metadata so files are grouped
        with (
            patch.object(
                scanner, "_extract_metadata", return_value={"artist": "Artist", "album": "Album"}
            ),
            patch.object(scanner, "_check_embedded_cover", return_value=False),
        ):
            albums = scanner.scan_library(tmp_path)

        # Note: .mp4 is in AUDIO_EXTENSIONS for M4A files
        # Only clear non-audio files like PDF should be ignored
        # With .mp4 treated as audio, we get 1 album with 2 tracks
        assert len(albums) == 1


class TestAudioExtensions:
    """Tests for audio extension constants."""

    def test_common_extensions(self):
        """Test that common audio extensions are included."""
        assert ".mp3" in AUDIO_EXTENSIONS
        assert ".flac" in AUDIO_EXTENSIONS
        assert ".ogg" in AUDIO_EXTENSIONS
        assert ".m4a" in AUDIO_EXTENSIONS
        assert ".opus" in AUDIO_EXTENSIONS
        assert ".wav" in AUDIO_EXTENSIONS
        assert ".aiff" in AUDIO_EXTENSIONS
        assert ".wma" in AUDIO_EXTENSIONS

    def test_case_sensitivity(self):
        """Test extension matching is case-insensitive."""
        # Extensions are stored lowercase
        assert all(ext == ext.lower() for ext in AUDIO_EXTENSIONS)


class TestCoverFilenamesConstants:
    """Tests for cover filename constants."""

    def test_common_names(self):
        """Test that common cover filenames are included."""
        assert "cover" in COVER_FILENAMES
        assert "folder" in COVER_FILENAMES
        assert "front" in COVER_FILENAMES
        assert "album" in COVER_FILENAMES
        assert "albumart" in COVER_FILENAMES

    def test_all_lowercase(self):
        """Test that all filenames are lowercase."""
        assert all(name == name.lower() for name in COVER_FILENAMES)


class TestCoverExtensions:
    """Tests for cover extension constants."""

    def test_common_extensions(self):
        """Test that common image extensions are included."""
        assert ".jpg" in COVER_EXTENSIONS
        assert ".jpeg" in COVER_EXTENSIONS
        assert ".png" in COVER_EXTENSIONS
        assert ".gif" in COVER_EXTENSIONS
        assert ".bmp" in COVER_EXTENSIONS
        assert ".webp" in COVER_EXTENSIONS


class TestPermissionDenied:
    """Tests for permission denied error handling."""

    def test_find_folders_logs_permission_error(self, scanner, tmp_path, monkeypatch, caplog):
        """Test that permission errors are logged when finding folders."""
        import logging

        caplog.set_level(logging.ERROR)

        def mock_walk(*args, **kwargs):
            raise PermissionError("Permission denied")

        monkeypatch.setattr(os, "walk", mock_walk)
        folders = scanner._find_album_folders(tmp_path)

        assert len(folders) == 0
        assert "Permission denied" in caplog.text

    def test_scan_folder_handles_permission_error(self, scanner, tmp_path, monkeypatch, caplog):
        """Test that permission errors are handled when scanning folder."""
        import logging

        caplog.set_level(logging.WARNING)

        album = tmp_path / "Protected"
        album.mkdir()

        def mock_iterdir(self):
            raise PermissionError("Permission denied")

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)
        result = scanner._scan_album_folder(album)

        assert result == []  # Returns empty list instead of None
        assert "Permission denied" in caplog.text

    def test_check_folder_cover_handles_permission_error(
        self, scanner, tmp_path, monkeypatch, caplog
    ):
        """Test that permission errors are handled when checking folder cover."""
        import logging

        caplog.set_level(logging.WARNING)

        folder = tmp_path / "Protected"
        folder.mkdir()

        def mock_iterdir(self):
            raise PermissionError("Permission denied")

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)
        has_cover, cover_file = scanner._check_folder_cover(folder)

        assert has_cover is False
        assert cover_file is None
        assert "Permission denied" in caplog.text


class TestIntegration:
    """Integration tests for the scanner."""

    def test_full_scan_with_all_features(self, tmp_path, progress_tracker, cancellation_controller):
        """Test a complete scan with progress tracking and metadata."""
        # Create a realistic library structure
        # Album with folder cover
        album1 = tmp_path / "Rock" / "Band1" / "Album1"
        album1.mkdir(parents=True)
        (album1 / "track1.mp3").write_bytes(b"fake mp3")
        (album1 / "track2.mp3").write_bytes(b"fake mp3")
        (album1 / "cover.jpg").write_bytes(b"fake image")

        # Album without cover
        album2 = tmp_path / "Jazz" / "Artist2" / "Album2"
        album2.mkdir(parents=True)
        (album2 / "song.flac").write_bytes(b"fake flac")

        # Hidden folder (should be excluded)
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "track.mp3").write_bytes(b"fake mp3")

        scanner = MusicScanner(
            exclude_patterns=["exclude"],
            progress_callback=progress_tracker.callback,
            cancelled_callback=cancellation_controller.callback,
        )

        with (
            patch.object(
                scanner,
                "_extract_metadata",
                return_value={"artist": "Test", "album": "Test Album", "year": "2020"},
            ),
            patch.object(scanner, "_check_embedded_cover", return_value=False),
        ):
            albums = scanner.scan_library(tmp_path)

        # Should find 2 albums (hidden excluded)
        assert len(albums) == 2

        # Progress callback should be called for each album
        assert len(progress_tracker.calls) == 2

        # Cancellation callback should be checked
        assert cancellation_controller.check_count > 0

    def test_scan_preserves_album_info(self, tmp_path):
        """Test that album info is correctly preserved."""
        album = tmp_path / "Artist" / "Album"
        album.mkdir(parents=True)
        track = album / "track.mp3"
        track.write_bytes(b"fake mp3")
        track2 = album / "track2.mp3"  # Add second track for album detection
        track2.write_bytes(b"fake mp3")
        (album / "cover.jpg").write_bytes(b"fake image")

        scanner = MusicScanner()

        mock_metadata = {"artist": "Test Artist", "album": "Test Album", "year": "2020"}

        with patch.object(scanner, "_extract_metadata", return_value=mock_metadata):
            with patch.object(scanner, "_check_embedded_cover", return_value=True):
                albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        album_info = albums[0]

        assert album_info.path == album
        assert album_info.artist == "Test Artist"
        assert album_info.album == "Test Album"
        assert album_info.year == "2020"
        assert album_info.track_count == 2  # Now 2 tracks
        assert album_info.cover.has_embedded is True
        assert album_info.cover.has_folder is True
        assert album_info.cover.folder_file == "cover.jpg"
        assert album_info.sample_file in [track, track2]  # One of the tracks
        assert ".mp3" in album_info.formats


class TestCoverComparison:
    """Tests for cover comparison functionality."""

    def test_covers_differ_when_both_exist_and_differ(self, tmp_path):
        """Test that covers_differ is True when both covers exist and differ."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track1.mp3").write_bytes(b"fake mp3")
        (album / "track2.mp3").write_bytes(b"fake mp3")  # 2 tracks for album detection
        # Create folder cover with specific bytes
        folder_cover_bytes = b"folder cover image bytes"
        (album / "cover.jpg").write_bytes(folder_cover_bytes)

        scanner = MusicScanner()

        mock_metadata = {"artist": "Artist", "album": "Album", "year": "2020"}

        # Mock embedded cover with different bytes
        embedded_cover_bytes = b"embedded cover different bytes"

        with patch.object(scanner, "_extract_metadata", return_value=mock_metadata):
            with patch.object(scanner, "_check_embedded_cover", return_value=True):
                with patch(
                    "src.core.scanner.extract_embedded_cover", return_value=embedded_cover_bytes
                ):
                    albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.cover.has_embedded is True
        assert album_info.cover.has_folder is True
        assert album_info.cover.covers_differ is True

    def test_covers_differ_false_when_identical(self, tmp_path):
        """Test that covers_differ is False when both covers are identical."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track1.mp3").write_bytes(b"fake mp3")
        (album / "track2.mp3").write_bytes(b"fake mp3")  # 2 tracks for album detection
        # Create folder cover with specific bytes
        identical_bytes = b"identical cover bytes"
        (album / "cover.jpg").write_bytes(identical_bytes)

        scanner = MusicScanner()

        mock_metadata = {"artist": "Artist", "album": "Album", "year": "2020"}

        with patch.object(scanner, "_extract_metadata", return_value=mock_metadata):
            with patch.object(scanner, "_check_embedded_cover", return_value=True):
                with patch("src.core.scanner.extract_embedded_cover", return_value=identical_bytes):
                    albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.cover.has_embedded is True
        assert album_info.cover.has_folder is True
        assert album_info.cover.covers_differ is False

    def test_covers_differ_false_when_only_embedded(self, tmp_path):
        """Test that covers_differ is False when only embedded cover exists."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track1.mp3").write_bytes(b"fake mp3")
        (album / "track2.mp3").write_bytes(b"fake mp3")  # 2 tracks for album detection
        # No folder cover

        scanner = MusicScanner()

        mock_metadata = {"artist": "Artist", "album": "Album", "year": "2020"}

        with patch.object(scanner, "_extract_metadata", return_value=mock_metadata):
            with patch.object(scanner, "_check_embedded_cover", return_value=True):
                albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.cover.has_embedded is True
        assert album_info.cover.has_folder is False
        assert album_info.cover.covers_differ is False

    def test_covers_differ_false_when_only_folder(self, tmp_path):
        """Test that covers_differ is False when only folder cover exists."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track1.mp3").write_bytes(b"fake mp3")
        (album / "track2.mp3").write_bytes(b"fake mp3")  # 2 tracks for album detection
        (album / "cover.jpg").write_bytes(b"folder cover")

        scanner = MusicScanner()

        mock_metadata = {"artist": "Artist", "album": "Album", "year": "2020"}

        with patch.object(scanner, "_extract_metadata", return_value=mock_metadata):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.cover.has_embedded is False
        assert album_info.cover.has_folder is True
        assert album_info.cover.covers_differ is False

    def test_covers_differ_false_when_no_covers(self, tmp_path):
        """Test that covers_differ is False when no covers exist."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track.mp3").write_bytes(b"fake mp3")

        scanner = MusicScanner()

        mock_metadata = {"artist": "Artist", "album": "Album", "year": "2020"}

        with patch.object(scanner, "_extract_metadata", return_value=mock_metadata):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.cover.has_embedded is False
        assert album_info.cover.has_folder is False
        assert album_info.cover.covers_differ is False

    def test_covers_differ_when_first_file_has_no_cover(self, tmp_path):
        """Test that covers_differ works when embedded cover is in 2nd or 3rd file."""
        album = tmp_path / "Album"
        album.mkdir()
        (album / "track1.mp3").write_bytes(b"fake mp3 no cover")
        (album / "track2.mp3").write_bytes(b"fake mp3 with cover")
        (album / "track3.mp3").write_bytes(b"fake mp3")
        folder_cover_bytes = b"folder cover bytes"
        (album / "cover.jpg").write_bytes(folder_cover_bytes)

        scanner = MusicScanner()

        mock_metadata = {"artist": "Artist", "album": "Album", "year": "2020"}

        # Simulate: first file has no cover, second file has embedded cover
        embedded_cover_bytes = b"embedded cover different bytes"
        call_count = [0]

        def mock_extract_embedded_cover(filepath):
            call_count[0] += 1
            if "track2" in str(filepath):
                return embedded_cover_bytes
            return None

        with patch.object(scanner, "_extract_metadata", return_value=mock_metadata):
            with patch.object(scanner, "_check_embedded_cover", return_value=True):
                with patch(
                    "src.core.scanner.extract_embedded_cover",
                    side_effect=mock_extract_embedded_cover,
                ):
                    albums = scanner.scan_library(tmp_path)

        assert len(albums) == 1
        album_info = albums[0]
        assert album_info.cover.has_embedded is True
        assert album_info.cover.has_folder is True
        # The key assertion: covers_differ should be True even though first file had no cover
        assert album_info.cover.covers_differ is True
        # Verify that extract was called multiple times (iterating through files)
        assert call_count[0] >= 2


class TestImageDimensionHelpers:
    """Tests for image dimension helper functions."""

    def test_get_image_dimensions_from_bytes_png(self):
        """Test getting dimensions from PNG bytes."""
        from src.core.scanner import _get_image_dimensions_from_bytes

        # Minimal valid PNG header for 100x50 image
        # PNG signature + IHDR chunk with dimensions
        png_header = (
            b"\x89PNG\r\n\x1a\n"  # PNG signature
            b"\x00\x00\x00\r"  # IHDR chunk length (13 bytes)
            b"IHDR"  # IHDR chunk type
            b"\x00\x00\x00\x64"  # Width: 100
            b"\x00\x00\x00\x32"  # Height: 50
            b"\x08\x02\x00\x00\x00"  # bit depth, color type, compression, filter, interlace
            b"\x00\x00\x00\x00"  # CRC (dummy)
        )

        dims = _get_image_dimensions_from_bytes(png_header)
        assert dims == (100, 50)

    def test_get_image_dimensions_from_bytes_invalid(self):
        """Test that invalid data returns None."""
        from src.core.scanner import _get_image_dimensions_from_bytes

        dims = _get_image_dimensions_from_bytes(b"not an image")
        assert dims is None

    def test_get_image_dimensions_from_bytes_empty(self):
        """Test that empty data returns None."""
        from src.core.scanner import _get_image_dimensions_from_bytes

        dims = _get_image_dimensions_from_bytes(b"")
        assert dims is None


class TestRescanAlbumCovers:
    """Tests for rescan_album_covers method."""

    def test_rescan_updates_has_embedded(self, scanner, tmp_path):
        """Test that rescan updates has_embedded status."""
        # Create album folder with audio file
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").write_bytes(b"fake mp3")

        # Create AlbumInfo with initial cover state
        cover = CoverInfo(
            has_embedded=False,
            has_folder=False,
            folder_file=None,
            folder_path=None,
            covers_differ=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=1,
            cover=cover,
        )

        # Mock _check_embedded_cover to return True
        with patch.object(scanner, "_check_embedded_cover", return_value=True):
            with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                with patch(
                    "src.core.scanner.extract_embedded_cover",
                    return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
                ):
                    scanner.rescan_album_covers(album)

        assert album.cover.has_embedded is True

    def test_rescan_updates_has_folder(self, scanner, tmp_path):
        """Test that rescan updates has_folder status."""
        # Create album folder with audio file and cover
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").write_bytes(b"fake mp3")
        cover_path = album_path / "cover.jpg"
        cover_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)

        cover = CoverInfo(
            has_embedded=False,
            has_folder=False,
            folder_file=None,
            folder_path=None,
            covers_differ=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=1,
            cover=cover,
        )

        with patch.object(scanner, "_check_embedded_cover", return_value=False):
            with patch.object(scanner, "_check_folder_cover", return_value=(True, "cover.jpg")):
                scanner.rescan_album_covers(album)

        assert album.cover.has_folder is True
        assert album.cover.folder_file == "cover.jpg"
        assert album.cover.folder_path == cover_path

    def test_rescan_clears_hashes(self, scanner, tmp_path):
        """Test that rescan clears cached hashes."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").write_bytes(b"fake mp3")

        cover = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=album_path / "cover.jpg",
            covers_differ=False,
            embedded_hash="abc123",
            folder_hash="def456",
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=1,
            cover=cover,
        )

        with patch.object(scanner, "_check_embedded_cover", return_value=False):
            with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                scanner.rescan_album_covers(album)

        # Hashes should be cleared for lazy recomputation
        assert album.cover.embedded_hash is None
        assert album.cover.folder_hash is None

    def test_rescan_updates_dimensions(self, scanner, tmp_path):
        """Test that rescan updates cover dimensions."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").write_bytes(b"fake mp3")
        cover_path = album_path / "cover.jpg"
        cover_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        cover = CoverInfo(
            has_embedded=False,
            has_folder=False,
            folder_file=None,
            folder_path=None,
            covers_differ=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=1,
            cover=cover,
        )

        mock_dimensions = (500, 500)
        with patch.object(scanner, "_check_embedded_cover", return_value=False):
            with patch.object(scanner, "_check_folder_cover", return_value=(True, "cover.jpg")):
                with patch(
                    "src.core.scanner._get_image_dimensions_from_bytes",
                    return_value=mock_dimensions,
                ):
                    scanner.rescan_album_covers(album)

        assert album.cover.folder_dimensions == mock_dimensions

    def test_rescan_updates_sizes(self, scanner, tmp_path):
        """Test that rescan updates file sizes."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").write_bytes(b"fake mp3")
        cover_data = b"\xff\xd8\xff" + b"\x00" * 1000
        cover_path = album_path / "cover.jpg"
        cover_path.write_bytes(cover_data)

        cover = CoverInfo(
            has_embedded=False,
            has_folder=False,
            folder_file=None,
            folder_path=None,
            covers_differ=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=1,
            cover=cover,
        )

        with patch.object(scanner, "_check_embedded_cover", return_value=False):
            with patch.object(scanner, "_check_folder_cover", return_value=(True, "cover.jpg")):
                scanner.rescan_album_covers(album)

        assert album.cover.folder_size_bytes == len(cover_data)

    def test_rescan_detects_cover_difference(self, scanner, tmp_path):
        """Test that rescan detects when covers differ."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").write_bytes(b"fake mp3")
        cover_path = album_path / "cover.jpg"
        cover_path.write_bytes(b"\xff\xd8\xff" + b"folder_data")

        cover = CoverInfo(
            has_embedded=False,
            has_folder=False,
            folder_file=None,
            folder_path=None,
            covers_differ=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=1,
            cover=cover,
        )

        embedded_data = b"\x89PNG\r\n" + b"embedded_data"
        with patch.object(scanner, "_check_embedded_cover", return_value=True):
            with patch.object(scanner, "_check_folder_cover", return_value=(True, "cover.jpg")):
                with patch("src.core.scanner.extract_embedded_cover", return_value=embedded_data):
                    scanner.rescan_album_covers(album)

        # Covers should differ since data is different
        assert album.cover.covers_differ is True

    def test_rescan_no_audio_files_does_nothing(self, scanner, tmp_path):
        """Test that rescan does nothing when no audio files."""
        album_path = tmp_path / "Empty"
        album_path.mkdir(parents=True)
        (album_path / "readme.txt").write_text("not audio")

        cover = CoverInfo(
            has_embedded=False,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=album_path / "cover.jpg",
            covers_differ=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=0,
            cover=cover,
        )

        # Should not change anything since no audio files
        original_has_folder = album.cover.has_folder
        scanner.rescan_album_covers(album)
        assert album.cover.has_folder == original_has_folder

    def test_rescan_handles_exception(self, scanner, tmp_path):
        """Test that rescan handles exceptions gracefully."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").write_bytes(b"fake mp3")

        cover = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=album_path / "cover.jpg",
            covers_differ=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Artist",
            album="Album",
            year=None,
            track_count=1,
            cover=cover,
        )

        # Simulate exception during rescan
        with patch.object(scanner, "_check_embedded_cover", side_effect=OSError("Test error")):
            # Should not raise, just log and continue
            scanner.rescan_album_covers(album)

        # Original state should be preserved since method failed
        assert album.cover.has_embedded is True


class TestIndividualFilesDetection:
    """Tests for detecting individual files vs albums in folders.

    Regression tests for bug where folders with individual files
    (different albums or no album tags) showed only one item instead of
    one per file.
    """

    def test_folder_with_same_album_is_detected_as_album(self, scanner, tmp_path):
        """Test that files with same album tag are grouped as one album."""
        album_path = tmp_path / "MixedFolder"
        album_path.mkdir(parents=True)

        # Create 3 files with same album tag
        (album_path / "track1.mp3").write_bytes(b"fake mp3")
        (album_path / "track2.mp3").write_bytes(b"fake mp3")
        (album_path / "track3.mp3").write_bytes(b"fake mp3")

        # Mock metadata extraction to return same album for all files
        def mock_extract(filepath):
            return {
                "artist": "Common Artist",
                "album": "Common Album",
                "year": "2020",
                "musicbrainz_albumid": None,
                "musicbrainz_releasegroupid": None,
                "musicbrainz_artistid": None,
                "isrc": None,
                "barcode": None,
                "discogs_release_id": None,
                "acoustid": None,
                "metadata_source": "tags",
            }

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                    albums = scanner._scan_album_folder(album_path)

        # Should return one album with 3 tracks
        assert len(albums) == 1
        assert albums[0].track_count == 3
        assert albums[0].album == "Common Album"

    def test_folder_with_different_albums_returns_individual_files(self, scanner, tmp_path):
        """Test that files with different album tags create separate AlbumInfo."""
        folder_path = tmp_path / "MixedFolder"
        folder_path.mkdir(parents=True)

        # Create 3 files
        (folder_path / "song1.mp3").write_bytes(b"fake mp3")
        (folder_path / "song2.mp3").write_bytes(b"fake mp3")
        (folder_path / "song3.mp3").write_bytes(b"fake mp3")

        # Mock metadata extraction to return different albums
        call_count = [0]

        def mock_extract(filepath):
            call_count[0] += 1
            return {
                "artist": f"Artist {call_count[0]}",
                "album": f"Album {call_count[0]}",
                "year": "2020",
                "musicbrainz_albumid": None,
                "musicbrainz_releasegroupid": None,
                "musicbrainz_artistid": None,
                "isrc": None,
                "barcode": None,
                "discogs_release_id": None,
                "acoustid": None,
                "metadata_source": "tags",
            }

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
                with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                    albums = scanner._scan_album_folder(folder_path)

        # Should return 3 individual albums (one per file)
        assert len(albums) == 3
        for album in albums:
            assert album.track_count == 1

    def test_folder_with_no_album_tags_returns_individual_files(self, scanner, tmp_path):
        """Test that files without album tags create separate AlbumInfo."""
        folder_path = tmp_path / "UnsortedMusic"
        folder_path.mkdir(parents=True)

        # Create 2 files
        (folder_path / "random1.mp3").write_bytes(b"fake mp3")
        (folder_path / "random2.mp3").write_bytes(b"fake mp3")

        # Mock metadata extraction to return no album tags
        def mock_extract(filepath):
            return {
                "artist": "Various",
                "album": None,  # No album tag
                "year": None,
                "musicbrainz_albumid": None,
                "musicbrainz_releasegroupid": None,
                "musicbrainz_artistid": None,
                "isrc": None,
                "barcode": None,
                "discogs_release_id": None,
                "acoustid": None,
                "metadata_source": None,
            }

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
                with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                    albums = scanner._scan_album_folder(folder_path)

        # Should return 2 individual albums (one per file)
        assert len(albums) == 2
        for album in albums:
            assert album.track_count == 1
            # Album name should be the filename (stem)
            assert album.album in ["random1", "random2"]

    def test_single_file_folder_returns_individual(self, scanner, tmp_path):
        """Test that a folder with single file creates individual AlbumInfo."""
        folder_path = tmp_path / "SingleSong"
        folder_path.mkdir(parents=True)

        # Create 1 file
        (folder_path / "lonely_song.mp3").write_bytes(b"fake mp3")

        def mock_extract(filepath):
            return {
                "artist": "Solo Artist",
                "album": "Some Album",
                "year": "2020",
                "musicbrainz_albumid": None,
                "musicbrainz_releasegroupid": None,
                "musicbrainz_artistid": None,
                "isrc": None,
                "barcode": None,
                "discogs_release_id": None,
                "acoustid": None,
                "metadata_source": "tags",
            }

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
                with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                    albums = scanner._scan_album_folder(folder_path)

        # Single file is always treated as individual
        assert len(albums) == 1
        assert albums[0].track_count == 1

    def test_majority_album_match_groups_as_album(self, scanner, tmp_path):
        """Test that 70%+ same album tag groups files as album."""
        folder_path = tmp_path / "MostlyAlbum"
        folder_path.mkdir(parents=True)

        # Create 10 files
        for i in range(10):
            (folder_path / f"track{i}.mp3").write_bytes(b"fake mp3")

        # Mock: 8 files have same album, 2 have different
        call_count = [0]

        def mock_extract(filepath):
            call_count[0] += 1
            if call_count[0] <= 8:
                return {
                    "artist": "Common Artist",
                    "album": "Common Album",
                    "year": "2020",
                    "musicbrainz_albumid": None,
                    "musicbrainz_releasegroupid": None,
                    "musicbrainz_artistid": None,
                    "isrc": None,
                    "barcode": None,
                    "discogs_release_id": None,
                    "acoustid": None,
                    "metadata_source": "tags",
                }
            else:
                return {
                    "artist": "Other Artist",
                    "album": "Other Album",
                    "year": "2019",
                    "musicbrainz_albumid": None,
                    "musicbrainz_releasegroupid": None,
                    "musicbrainz_artistid": None,
                    "isrc": None,
                    "barcode": None,
                    "discogs_release_id": None,
                    "acoustid": None,
                    "metadata_source": "tags",
                }

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                    albums = scanner._scan_album_folder(folder_path)

        # Should be grouped as one album (80% match >= 70% threshold)
        assert len(albums) == 1
        assert albums[0].track_count == 10

    def test_scan_library_handles_individual_files(self, scanner, tmp_path):
        """Test that scan_library correctly handles folders with individual files."""
        # Create music library with mixed content
        album_folder = tmp_path / "RealAlbum"
        album_folder.mkdir(parents=True)
        for i in range(5):
            (album_folder / f"track{i}.mp3").write_bytes(b"fake mp3")

        singles_folder = tmp_path / "Singles"
        singles_folder.mkdir(parents=True)
        (singles_folder / "single1.mp3").write_bytes(b"fake mp3")
        (singles_folder / "single2.mp3").write_bytes(b"fake mp3")

        # Track which folder is being processed
        def mock_extract(filepath):
            if "RealAlbum" in str(filepath):
                return {
                    "artist": "Album Artist",
                    "album": "Real Album",
                    "year": "2020",
                    "musicbrainz_albumid": None,
                    "musicbrainz_releasegroupid": None,
                    "musicbrainz_artistid": None,
                    "isrc": None,
                    "barcode": None,
                    "discogs_release_id": None,
                    "acoustid": None,
                    "metadata_source": "tags",
                }
            else:
                # Different albums for singles
                return {
                    "artist": "Various",
                    "album": filepath.stem,  # Use filename as album
                    "year": "2021",
                    "musicbrainz_albumid": None,
                    "musicbrainz_releasegroupid": None,
                    "musicbrainz_artistid": None,
                    "isrc": None,
                    "barcode": None,
                    "discogs_release_id": None,
                    "acoustid": None,
                    "metadata_source": "tags",
                }

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
                    with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                        albums = scanner.scan_library(tmp_path)

        # Should have 1 album + 2 individual files = 3 total
        assert len(albums) == 3

        # Find the real album and check it
        real_album = next((a for a in albums if a.album == "Real Album"), None)
        assert real_album is not None
        assert real_album.track_count == 5

        # Find the singles and check they have track_count=1
        singles = [a for a in albums if a.album in ["single1", "single2"]]
        assert len(singles) == 2
        for single in singles:
            assert single.track_count == 1

    def test_individual_files_not_cached(self, scanner, tmp_path):
        """Regression test: Individual files should not be cached.

        Bug: When a folder had multiple individual files (different albums),
        only the first AlbumInfo was cached. On subsequent scans with cache,
        only that first file was returned, causing data loss.

        Fix: Only cache folders that return a single AlbumInfo (real albums).
        Folders with individual files (multiple AlbumInfo) are rescanned each time.
        """
        from unittest.mock import MagicMock

        # Create folder with individual files (different albums)
        singles_folder = tmp_path / "Singles"
        singles_folder.mkdir(parents=True)
        (singles_folder / "song1.mp3").write_bytes(b"fake mp3")
        (singles_folder / "song2.mp3").write_bytes(b"fake mp3")
        (singles_folder / "song3.mp3").write_bytes(b"fake mp3")

        # Mock metadata to return different albums for each file
        def mock_extract(filepath):
            return {
                "artist": "Various",
                "album": filepath.stem,  # Different album per file
                "year": "2021",
                "musicbrainz_albumid": None,
                "musicbrainz_releasegroupid": None,
                "musicbrainz_artistid": None,
                "isrc": None,
                "barcode": None,
                "discogs_release_id": None,
                "acoustid": None,
                "metadata_source": "tags",
            }

        # Create a mock cache
        mock_cache = MagicMock()
        mock_cache.get_cached_album.return_value = None  # No cached data

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
                    with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                        albums = scanner.scan_library(tmp_path, scan_cache=mock_cache)

        # Should have 3 individual files
        assert len(albums) == 3

        # Cache should NOT have been updated (individual files are not cached)
        mock_cache.update_folder.assert_not_called()

    def test_real_album_is_cached(self, scanner, tmp_path):
        """Test that real albums (single AlbumInfo) are cached correctly."""
        from unittest.mock import MagicMock

        # Create folder with real album (same album for all files)
        album_folder = tmp_path / "RealAlbum"
        album_folder.mkdir(parents=True)
        (album_folder / "track1.mp3").write_bytes(b"fake mp3")
        (album_folder / "track2.mp3").write_bytes(b"fake mp3")

        # Mock metadata to return same album for all files
        def mock_extract(filepath):
            return {
                "artist": "Artist",
                "album": "Album Name",  # Same album for all
                "year": "2020",
                "musicbrainz_albumid": None,
                "musicbrainz_releasegroupid": None,
                "musicbrainz_artistid": None,
                "isrc": None,
                "barcode": None,
                "discogs_release_id": None,
                "acoustid": None,
                "metadata_source": "tags",
            }

        # Create a mock cache
        mock_cache = MagicMock()
        mock_cache.get_cached_album.return_value = None  # No cached data

        with patch.object(scanner, "_extract_metadata", side_effect=mock_extract):
            with patch.object(scanner, "_check_embedded_cover", return_value=False):
                with patch.object(scanner, "_file_has_embedded_cover", return_value=False):
                    with patch.object(scanner, "_check_folder_cover", return_value=(False, None)):
                        albums = scanner.scan_library(tmp_path, scan_cache=mock_cache)

        # Should have 1 album
        assert len(albums) == 1
        assert albums[0].album == "Album Name"

        # Cache SHOULD have been updated for real album
        mock_cache.update_folder.assert_called_once()
