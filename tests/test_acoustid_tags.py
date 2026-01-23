"""
Tests for the acoustid_tags utility module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.acoustid_tags import (
    SUPPORTED_EXTENSIONS,
    extract_acoustid,
    save_acoustid_to_file,
    save_acoustid_to_folder,
)


class TestSupportedExtensions:
    """Tests for supported extensions constant."""

    def test_includes_common_formats(self):
        """Test that common audio formats are supported."""
        assert ".mp3" in SUPPORTED_EXTENSIONS
        assert ".flac" in SUPPORTED_EXTENSIONS
        assert ".ogg" in SUPPORTED_EXTENSIONS
        assert ".m4a" in SUPPORTED_EXTENSIONS

    def test_includes_opus(self):
        """Test that Opus format is supported."""
        assert ".opus" in SUPPORTED_EXTENSIONS

    def test_includes_mp4(self):
        """Test that MP4 format is supported."""
        assert ".mp4" in SUPPORTED_EXTENSIONS


class TestExtractAcoustid:
    """Tests for extract_acoustid function."""

    def test_returns_none_for_nonexistent_file(self):
        """Test returns None for file that doesn't exist."""
        result = extract_acoustid(Path("/nonexistent/path.mp3"))
        assert result is None

    def test_returns_none_for_unsupported_extension(self):
        """Test returns None for unsupported file extension."""
        with patch("pathlib.Path.exists", return_value=True):
            result = extract_acoustid(Path("/fake/path.wav"))
        assert result is None

    def test_extract_from_mp3_txxx(self):
        """Test extraction from MP3 TXXX frame."""
        mock_audio = MagicMock()
        mock_audio.tags = {"TXXX:Acoustid Id": MagicMock(text=["abc123-acoustid"])}

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", return_value=mock_audio),
        ):
            result = extract_acoustid(Path("/fake/path.mp3"))

        assert result == "abc123-acoustid"

    def test_extract_from_flac(self):
        """Test extraction from FLAC file."""
        from mutagen.flac import FLAC

        mock_audio = MagicMock(spec=FLAC)
        mock_audio.get.side_effect = lambda k: ["flac-acoustid"] if k == "ACOUSTID_ID" else None

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", return_value=mock_audio),
        ):
            result = extract_acoustid(Path("/fake/path.flac"))

        assert result == "flac-acoustid"

    def test_extract_from_ogg(self):
        """Test extraction from OGG file."""
        mock_audio = MagicMock()
        mock_audio.get.side_effect = lambda k: ["ogg-acoustid"] if k == "ACOUSTID_ID" else None

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", return_value=mock_audio),
        ):
            result = extract_acoustid(Path("/fake/path.ogg"))

        assert result == "ogg-acoustid"

    def test_extract_from_m4a(self):
        """Test extraction from M4A file."""
        from mutagen.mp4 import MP4

        mock_audio = MagicMock(spec=MP4)
        mock_audio.tags = {"----:com.apple.iTunes:Acoustid Id": [b"mp4-acoustid"]}

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", return_value=mock_audio),
        ):
            result = extract_acoustid(Path("/fake/path.m4a"))

        assert result == "mp4-acoustid"

    def test_returns_none_when_no_acoustid_tag(self):
        """Test returns None when AcoustID tag is not present."""
        mock_audio = MagicMock()
        mock_audio.tags = {}

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", return_value=mock_audio),
        ):
            result = extract_acoustid(Path("/fake/path.mp3"))

        assert result is None

    def test_handles_mutagen_none_return(self):
        """Test handles None return from MutagenFile."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", return_value=None),
        ):
            result = extract_acoustid(Path("/fake/path.mp3"))

        assert result is None

    def test_handles_exception(self):
        """Test handles exception gracefully."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", side_effect=OSError("Error")),
        ):
            result = extract_acoustid(Path("/fake/path.mp3"))

        assert result is None

    def test_lowercase_acoustid_key(self):
        """Test extraction with lowercase acoustid_id key."""
        mock_audio = MagicMock()
        mock_audio.get.side_effect = (
            lambda k: ["lowercase-acoustid"] if k.lower() == "acoustid_id" else None
        )

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MutagenFile", return_value=mock_audio),
        ):
            result = extract_acoustid(Path("/fake/path.ogg"))

        # The function tries both ACOUSTID_ID and acoustid_id


class TestSaveAcoustidToFile:
    """Tests for save_acoustid_to_file function."""

    def test_returns_false_for_nonexistent_file(self):
        """Test returns False for file that doesn't exist."""
        result = save_acoustid_to_file(Path("/nonexistent/path.mp3"), "acoustid")
        assert result is False

    def test_returns_false_for_unsupported_extension(self):
        """Test returns False for unsupported file extension."""
        with patch("pathlib.Path.exists", return_value=True):
            result = save_acoustid_to_file(Path("/fake/path.wav"), "acoustid")
        assert result is False

    def test_save_to_mp3(self):
        """Test saving AcoustID to MP3 file."""
        mock_id3 = MagicMock()
        mock_id3.keys.return_value = []

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.ID3", return_value=mock_id3),
        ):
            result = save_acoustid_to_file(Path("/fake/path.mp3"), "test-acoustid")

        assert result is True
        mock_id3.add.assert_called_once()
        mock_id3.save.assert_called_once()

    def test_save_to_flac(self):
        """Test saving AcoustID to FLAC file."""
        mock_flac = MagicMock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.FLAC", return_value=mock_flac),
        ):
            result = save_acoustid_to_file(Path("/fake/path.flac"), "test-acoustid")

        assert result is True
        mock_flac.__setitem__.assert_called_with("ACOUSTID_ID", "test-acoustid")
        mock_flac.save.assert_called_once()

    def test_save_to_ogg(self):
        """Test saving AcoustID to OGG file."""
        mock_ogg = MagicMock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.OggVorbis", return_value=mock_ogg),
        ):
            result = save_acoustid_to_file(Path("/fake/path.ogg"), "test-acoustid")

        assert result is True
        mock_ogg.__setitem__.assert_called_with("ACOUSTID_ID", "test-acoustid")
        mock_ogg.save.assert_called_once()

    def test_save_to_opus(self):
        """Test saving AcoustID to Opus file."""
        mock_opus = MagicMock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.OggOpus", return_value=mock_opus),
        ):
            result = save_acoustid_to_file(Path("/fake/path.opus"), "test-acoustid")

        assert result is True
        mock_opus.__setitem__.assert_called_with("ACOUSTID_ID", "test-acoustid")
        mock_opus.save.assert_called_once()

    def test_save_to_m4a(self):
        """Test saving AcoustID to M4A file."""
        mock_mp4 = MagicMock()
        mock_mp4.tags = {}

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.MP4", return_value=mock_mp4),
        ):
            result = save_acoustid_to_file(Path("/fake/path.m4a"), "test-acoustid")

        assert result is True
        mock_mp4.save.assert_called_once()

    def test_handles_exception(self):
        """Test handles exception gracefully."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.utils.acoustid_tags.ID3", side_effect=OSError("Error")),
        ):
            result = save_acoustid_to_file(Path("/fake/path.mp3"), "acoustid")

        assert result is False


class TestSaveAcoustidToFolder:
    """Tests for save_acoustid_to_folder function."""

    def test_returns_zero_for_non_directory(self):
        """Test returns 0 for path that's not a directory."""
        with patch("pathlib.Path.is_dir", return_value=False):
            result = save_acoustid_to_folder(Path("/fake/file.mp3"), "acoustid")
        assert result == 0

    def test_saves_to_all_supported_files(self):
        """Test saves AcoustID to all supported files in folder."""
        mock_files = [
            MagicMock(is_file=MagicMock(return_value=True), suffix=".mp3"),
            MagicMock(is_file=MagicMock(return_value=True), suffix=".flac"),
            MagicMock(is_file=MagicMock(return_value=True), suffix=".txt"),  # Unsupported
        ]

        mock_folder = MagicMock()
        mock_folder.is_dir.return_value = True
        mock_folder.iterdir.return_value = mock_files

        with patch("src.utils.acoustid_tags.save_acoustid_to_file", return_value=True) as mock_save:
            result = save_acoustid_to_folder(mock_folder, "test-acoustid")

        # Should only save to mp3 and flac, not txt
        assert mock_save.call_count == 2
        assert result == 2

    def test_counts_only_successful_saves(self):
        """Test only counts successful saves."""
        mock_files = [
            MagicMock(is_file=MagicMock(return_value=True), suffix=".mp3"),
            MagicMock(is_file=MagicMock(return_value=True), suffix=".flac"),
        ]

        mock_folder = MagicMock()
        mock_folder.is_dir.return_value = True
        mock_folder.iterdir.return_value = mock_files

        # First save succeeds, second fails
        with patch("src.utils.acoustid_tags.save_acoustid_to_file", side_effect=[True, False]):
            result = save_acoustid_to_folder(mock_folder, "test-acoustid")

        assert result == 1

    def test_skips_directories(self):
        """Test skips subdirectories."""
        mock_files = [
            MagicMock(is_file=MagicMock(return_value=False)),  # Directory
            MagicMock(is_file=MagicMock(return_value=True), suffix=".mp3"),
        ]

        mock_folder = MagicMock()
        mock_folder.is_dir.return_value = True
        mock_folder.iterdir.return_value = mock_files

        with patch("src.utils.acoustid_tags.save_acoustid_to_file", return_value=True) as mock_save:
            result = save_acoustid_to_folder(mock_folder, "test-acoustid")

        assert mock_save.call_count == 1
        assert result == 1

    def test_handles_empty_folder(self):
        """Test handles empty folder."""
        mock_folder = MagicMock()
        mock_folder.is_dir.return_value = True
        mock_folder.iterdir.return_value = []

        result = save_acoustid_to_folder(mock_folder, "test-acoustid")

        assert result == 0
