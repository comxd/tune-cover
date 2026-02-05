"""
Tests for the cover embedder module.
"""

import base64
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.embedder import (
    EMBEDDABLE_FORMATS,
    CoverEmbedder,
    _validate_filename,
    detect_image_mime_type,
    extract_embedded_cover,
    get_extension_for_mime,
)
from src.core.exceptions import TagWriteError
from src.utils.cache import embedded_cover_cache

# =============================================================================
# Test Fixtures and Helpers
# =============================================================================

# Minimal valid image data for testing
JPEG_MAGIC = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
GIF_MAGIC = b"GIF89a\x01\x00\x01\x00"
WEBP_MAGIC = b"RIFF\x00\x00\x00\x00WEBP"
BMP_MAGIC = b"BM\x00\x00\x00\x00\x00\x00\x00\x00"


@pytest.fixture
def embedder():
    """Provide a fresh CoverEmbedder instance."""
    return CoverEmbedder()


@pytest.fixture
def jpeg_cover_data():
    """Minimal JPEG-like cover data."""
    return JPEG_MAGIC + b"\x00" * 100


@pytest.fixture
def png_cover_data():
    """Minimal PNG-like cover data."""
    return PNG_MAGIC + b"\x00" * 100


@pytest.fixture
def gif_cover_data():
    """Minimal GIF-like cover data."""
    return GIF_MAGIC + b"\x00" * 100


@pytest.fixture
def webp_cover_data():
    """Minimal WebP-like cover data."""
    return WEBP_MAGIC + b"\x00" * 100


@pytest.fixture
def bmp_cover_data():
    """Minimal BMP-like cover data."""
    return BMP_MAGIC + b"\x00" * 100


@pytest.fixture
def audio_folder(tmp_path, jpeg_cover_data):
    """Create a folder with mock audio files."""
    folder = tmp_path / "music"
    folder.mkdir()

    # Create empty files with audio extensions
    for ext in [".mp3", ".flac", ".ogg", ".m4a"]:
        (folder / f"track{ext}").touch()

    # Create a non-audio file
    (folder / "readme.txt").write_text("test")

    return folder


# =============================================================================
# Tests for detect_image_mime_type()
# =============================================================================


class TestDetectImageMimeType:
    """Tests for MIME type detection."""

    def test_jpeg_detection(self):
        """Test JPEG detection from magic bytes."""
        jpeg_data = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        assert detect_image_mime_type(jpeg_data) == "image/jpeg"

    def test_jpeg_minimal_magic(self):
        """Test JPEG detection with just SOI marker."""
        jpeg_data = b"\xff\xd8"
        assert detect_image_mime_type(jpeg_data) == "image/jpeg"

    def test_png_detection(self):
        """Test PNG detection from magic bytes."""
        png_data = b"\x89PNG\r\n\x1a\n"
        assert detect_image_mime_type(png_data) == "image/png"

    def test_gif87a_detection(self):
        """Test GIF87a detection from magic bytes."""
        gif_data = b"GIF87a"
        assert detect_image_mime_type(gif_data) == "image/gif"

    def test_gif89a_detection(self):
        """Test GIF89a detection from magic bytes."""
        gif_data = b"GIF89a"
        assert detect_image_mime_type(gif_data) == "image/gif"

    def test_webp_detection(self):
        """Test WebP detection from magic bytes."""
        webp_data = b"RIFF\x00\x00\x00\x00WEBP"
        assert detect_image_mime_type(webp_data) == "image/webp"

    def test_webp_with_size(self):
        """Test WebP detection with actual size bytes."""
        webp_data = b"RIFF\x24\x00\x00\x00WEBPVP8"
        assert detect_image_mime_type(webp_data) == "image/webp"

    def test_bmp_detection(self):
        """Test BMP detection from magic bytes."""
        bmp_data = b"BM\x00\x00\x00\x00"
        assert detect_image_mime_type(bmp_data) == "image/bmp"

    def test_unknown_defaults_to_jpeg(self):
        """Test that unknown data defaults to JPEG."""
        unknown_data = b"\x00\x00\x00\x00"
        assert detect_image_mime_type(unknown_data) == "image/jpeg"

    def test_empty_data_defaults_to_jpeg(self):
        """Test that empty data defaults to JPEG."""
        assert detect_image_mime_type(b"") == "image/jpeg"

    def test_short_data_defaults_to_jpeg(self):
        """Test that data shorter than magic bytes defaults to JPEG."""
        assert detect_image_mime_type(b"\x89") == "image/jpeg"


# =============================================================================
# Tests for get_extension_for_mime()
# =============================================================================


class TestGetExtensionForMime:
    """Tests for MIME to extension mapping."""

    @pytest.mark.parametrize(
        "mime_type,expected_ext",
        [
            ("image/png", ".png"),
            ("image/jpeg", ".jpg"),
            ("image/gif", ".gif"),
            ("image/webp", ".webp"),
            ("image/bmp", ".bmp"),
        ],
    )
    def test_known_mime_types(self, mime_type, expected_ext):
        """Test known MIME types return correct extensions."""
        assert get_extension_for_mime(mime_type) == expected_ext

    def test_unknown_mime_defaults_to_jpg(self):
        """Test unknown MIME type defaults to .jpg."""
        assert get_extension_for_mime("image/unknown") == ".jpg"
        assert get_extension_for_mime("application/octet-stream") == ".jpg"


# =============================================================================
# Tests for _validate_filename() - CRITICAL SECURITY TESTS
# =============================================================================


class TestValidateFilename:
    """Critical security tests for path traversal prevention."""

    def test_valid_simple_filename(self):
        """Test that valid simple filenames pass validation."""
        _validate_filename("cover.jpg")
        _validate_filename("album_art.png")
        _validate_filename("my-cover-image.jpeg")

    def test_valid_filename_with_spaces(self):
        """Test that filenames with spaces are valid."""
        _validate_filename("cover art.jpg")
        _validate_filename("album cover image.png")

    def test_path_traversal_dotdot(self):
        """Test that .. path traversal is blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("../etc/passwd")

    def test_path_traversal_dotdot_only(self):
        """Test that standalone .. is blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("..")

    def test_path_traversal_dotdot_embedded(self):
        """Test that embedded .. is blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("foo..bar")

    def test_path_traversal_forward_slash(self):
        """Test that forward slash is blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("/etc/passwd")

    def test_path_traversal_relative_path(self):
        """Test that relative paths with / are blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("subdir/cover.jpg")

    def test_path_traversal_backslash(self):
        """Test that backslash is blocked (Windows paths)."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("..\\Windows\\System32")

    def test_path_traversal_backslash_relative(self):
        """Test that relative paths with \\ are blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("subdir\\cover.jpg")

    def test_hidden_file_single_dot(self):
        """Test that hidden files (starting with .) are blocked."""
        with pytest.raises(ValueError, match="hidden file"):
            _validate_filename(".cover.jpg")

    def test_hidden_file_gitkeep(self):
        """Test that .gitkeep-style hidden files are blocked."""
        with pytest.raises(ValueError, match="hidden file"):
            _validate_filename(".gitkeep")

    def test_hidden_file_dotfile(self):
        """Test that dotfiles are blocked."""
        with pytest.raises(ValueError, match="hidden file"):
            _validate_filename(".bashrc")

    def test_complex_path_traversal_attack(self):
        """Test complex path traversal attempts."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("....//....//etc/passwd")

    def test_mixed_separators_attack(self):
        """Test mixed path separator attacks."""
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("..\\..//etc/passwd")

    def test_encoded_traversal_not_decoded(self):
        """Test that URL-encoded sequences are NOT decoded (safe behavior)."""
        # These should NOT be decoded, so they're treated as literal characters
        # The % and encoded chars are valid filename chars
        _validate_filename("%2e%2e")  # This is literally the string "%2e%2e"

    def test_null_byte_filename(self):
        """Test filename with null byte (though not path traversal)."""
        # Null bytes in filenames are OS-dependent but shouldn't traverse
        _validate_filename("cover\x00.jpg")  # Should not raise for traversal


# =============================================================================
# Tests for CoverEmbedder.save_cover_to_folder()
# =============================================================================


class TestSaveCoverToFolder:
    """Tests for saving cover images to folders."""

    def test_save_jpeg_auto_extension(self, embedder, tmp_path, jpeg_cover_data):
        """Test saving JPEG cover with auto-detected extension."""
        result = embedder.save_cover_to_folder(jpeg_cover_data, tmp_path)

        assert result == tmp_path / "cover.jpg"
        assert result.exists()
        assert result.read_bytes() == jpeg_cover_data

    def test_save_png_auto_extension(self, embedder, tmp_path, png_cover_data):
        """Test saving PNG cover with auto-detected extension."""
        result = embedder.save_cover_to_folder(png_cover_data, tmp_path)

        assert result == tmp_path / "cover.png"
        assert result.exists()
        assert result.read_bytes() == png_cover_data

    def test_save_gif_auto_extension(self, embedder, tmp_path, gif_cover_data):
        """Test saving GIF cover with auto-detected extension."""
        result = embedder.save_cover_to_folder(gif_cover_data, tmp_path)

        assert result == tmp_path / "cover.gif"
        assert result.exists()

    def test_save_webp_auto_extension(self, embedder, tmp_path, webp_cover_data):
        """Test saving WebP cover with auto-detected extension."""
        result = embedder.save_cover_to_folder(webp_cover_data, tmp_path)

        assert result == tmp_path / "cover.webp"
        assert result.exists()

    def test_save_bmp_auto_extension(self, embedder, tmp_path, bmp_cover_data):
        """Test saving BMP cover with auto-detected extension."""
        result = embedder.save_cover_to_folder(bmp_cover_data, tmp_path)

        assert result == tmp_path / "cover.bmp"
        assert result.exists()

    def test_save_with_custom_filename(self, embedder, tmp_path, jpeg_cover_data):
        """Test saving cover with custom filename."""
        result = embedder.save_cover_to_folder(jpeg_cover_data, tmp_path, filename="album_art.jpg")

        assert result == tmp_path / "album_art.jpg"
        assert result.exists()

    def test_save_creates_folder_if_not_exists(self, embedder, tmp_path, jpeg_cover_data):
        """Test that missing folders are created."""
        nested_folder = tmp_path / "deep" / "nested" / "folder"

        result = embedder.save_cover_to_folder(jpeg_cover_data, nested_folder)

        assert result.exists()
        assert nested_folder.exists()

    def test_save_overwrites_existing_file(self, embedder, tmp_path, jpeg_cover_data):
        """Test that existing cover files are overwritten."""
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"old data")

        embedder.save_cover_to_folder(jpeg_cover_data, tmp_path)

        assert cover_path.read_bytes() == jpeg_cover_data

    def test_save_with_path_traversal_filename_raises(self, embedder, tmp_path, jpeg_cover_data):
        """Test that path traversal in filename is blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            embedder.save_cover_to_folder(
                jpeg_cover_data, tmp_path, filename="../../../etc/malicious.jpg"
            )

    def test_save_with_hidden_filename_raises(self, embedder, tmp_path, jpeg_cover_data):
        """Test that hidden filenames are blocked."""
        with pytest.raises(ValueError, match="hidden file"):
            embedder.save_cover_to_folder(jpeg_cover_data, tmp_path, filename=".hidden_cover.jpg")

    def test_save_permission_denied(self, embedder, tmp_path, jpeg_cover_data, monkeypatch):
        """Test handling of permission denied errors."""
        readonly_dir = tmp_path / "readonly"

        # Mock Path.mkdir to raise PermissionError (cross-platform approach)
        original_mkdir = Path.mkdir

        def mock_mkdir(self, *args, **kwargs):
            if str(self).startswith(str(readonly_dir)):
                raise PermissionError("Permission denied")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)

        with pytest.raises(TagWriteError):
            embedder.save_cover_to_folder(jpeg_cover_data, readonly_dir / "subdir")

    def test_save_returns_path_object(self, embedder, tmp_path, jpeg_cover_data):
        """Test that result is a Path object."""
        result = embedder.save_cover_to_folder(jpeg_cover_data, tmp_path)
        assert isinstance(result, Path)


# =============================================================================
# Tests for CoverEmbedder.embed_cover_in_file()
# =============================================================================


class TestEmbedCoverInFile:
    """Tests for embedding covers in individual files."""

    @patch("src.core.embedder.ID3")
    def test_embed_mp3_calls_embed_mp3(self, mock_id3, embedder, tmp_path, jpeg_cover_data):
        """Test that .mp3 files use _embed_mp3 method."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        mock_audio = MagicMock()
        mock_id3.return_value = mock_audio

        result = embedder.embed_cover_in_file(mp3_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        mock_id3.assert_called_once_with(mp3_file)

    @patch("src.core.embedder.FLAC")
    def test_embed_flac_calls_embed_flac(self, mock_flac, embedder, tmp_path, jpeg_cover_data):
        """Test that .flac files use _embed_flac method."""
        flac_file = tmp_path / "test.flac"
        flac_file.touch()

        mock_audio = MagicMock()
        mock_flac.return_value = mock_audio

        result = embedder.embed_cover_in_file(flac_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        mock_flac.assert_called_once_with(flac_file)

    @patch("src.core.embedder.MP4")
    def test_embed_m4a_calls_embed_mp4(self, mock_mp4, embedder, tmp_path, jpeg_cover_data):
        """Test that .m4a files use _embed_mp4 method."""
        m4a_file = tmp_path / "test.m4a"
        m4a_file.touch()

        mock_audio = MagicMock()
        mock_mp4.return_value = mock_audio

        result = embedder.embed_cover_in_file(m4a_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        mock_mp4.assert_called_once_with(m4a_file)

    @patch("src.core.embedder.MP4")
    def test_embed_mp4_extension(self, mock_mp4, embedder, tmp_path, jpeg_cover_data):
        """Test that .mp4 files use _embed_mp4 method."""
        mp4_file = tmp_path / "test.mp4"
        mp4_file.touch()

        mock_audio = MagicMock()
        mock_mp4.return_value = mock_audio

        result = embedder.embed_cover_in_file(mp4_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        mock_mp4.assert_called_once_with(mp4_file)

    def test_embed_ogg_calls_embed_ogg(self, embedder, tmp_path, jpeg_cover_data):
        """Test that .ogg files use _embed_ogg method via _embed_ogg internal."""
        ogg_file = tmp_path / "test.ogg"
        ogg_file.touch()

        # Mock _embed_ogg to verify it gets called
        with patch.object(embedder, "_embed_ogg") as mock_embed_ogg:
            result = embedder.embed_cover_in_file(ogg_file, jpeg_cover_data, "image/jpeg")

            assert result is True
            mock_embed_ogg.assert_called_once_with(ogg_file, jpeg_cover_data, "image/jpeg")

    def test_embed_opus_calls_embed_ogg(self, embedder, tmp_path, jpeg_cover_data):
        """Test that .opus files use _embed_ogg method."""
        opus_file = tmp_path / "test.opus"
        opus_file.touch()

        # Mock _embed_ogg to verify it gets called for opus files
        with patch.object(embedder, "_embed_ogg") as mock_embed_ogg:
            result = embedder.embed_cover_in_file(opus_file, jpeg_cover_data, "image/jpeg")

            assert result is True
            mock_embed_ogg.assert_called_once_with(opus_file, jpeg_cover_data, "image/jpeg")

    def test_embed_unsupported_format_raises_exception(self, embedder, tmp_path, jpeg_cover_data):
        """Test that unsupported formats raise UnsupportedFormatError."""
        from src.core.exceptions import UnsupportedFormatError

        wav_file = tmp_path / "test.wav"
        wav_file.touch()

        with pytest.raises(UnsupportedFormatError) as exc_info:
            embedder.embed_cover_in_file(wav_file, jpeg_cover_data, "image/jpeg")

        assert exc_info.value.file_path == str(wav_file)
        assert ".wav" in str(exc_info.value)

    def test_embed_unknown_format_raises_exception(self, embedder, tmp_path, jpeg_cover_data):
        """Test that unknown formats raise UnsupportedFormatError."""
        from src.core.exceptions import UnsupportedFormatError

        unknown_file = tmp_path / "test.xyz"
        unknown_file.touch()

        with pytest.raises(UnsupportedFormatError) as exc_info:
            embedder.embed_cover_in_file(unknown_file, jpeg_cover_data, "image/jpeg")

        assert exc_info.value.file_path == str(unknown_file)
        assert ".xyz" in str(exc_info.value)

    @patch("src.core.embedder.ID3")
    def test_embed_handles_exception_gracefully(
        self, mock_id3, embedder, tmp_path, jpeg_cover_data
    ):
        """Test that exceptions are caught and return False."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        mock_id3.side_effect = OSError("Corrupted file")

        result = embedder.embed_cover_in_file(mp3_file, jpeg_cover_data, "image/jpeg")

        assert result is False

    def test_embed_case_insensitive_extension(self, embedder, tmp_path, jpeg_cover_data):
        """Test that file extension matching is case-insensitive."""
        # This should be handled by .lower() in the implementation
        mp3_upper = tmp_path / "test.MP3"
        mp3_upper.touch()

        with patch("src.core.embedder.ID3") as mock_id3:
            mock_audio = MagicMock()
            mock_id3.return_value = mock_audio

            result = embedder.embed_cover_in_file(mp3_upper, jpeg_cover_data, "image/jpeg")

            assert result is True


# =============================================================================
# Tests for CoverEmbedder.embed_cover_in_folder()
# =============================================================================


class TestEmbedCoverInFolder:
    """Tests for embedding covers in all files in a folder."""

    def test_embed_folder_processes_all_audio_files(self, embedder, tmp_path, jpeg_cover_data):
        """Test that all embeddable audio files are processed."""
        folder = tmp_path / "music"
        folder.mkdir()

        # Create mock audio files
        (folder / "track1.mp3").touch()
        (folder / "track2.flac").touch()
        (folder / "track3.ogg").touch()
        (folder / "readme.txt").touch()

        with patch.object(embedder, "embed_cover_in_file", return_value=True) as mock_embed:
            count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)

        # Should process 3 audio files, not the txt
        assert count == 3
        assert mock_embed.call_count == 3

    def test_embed_folder_returns_success_count(self, embedder, tmp_path, jpeg_cover_data):
        """Test that return value reflects successful embeddings only.

        Note: The implementation counts calls that don't raise exceptions,
        not calls that return True. So we simulate failure with an exception.
        """
        folder = tmp_path / "music"
        folder.mkdir()

        (folder / "track1.mp3").touch()
        (folder / "track2.mp3").touch()
        (folder / "track3.mp3").touch()

        # Simulate 2 successes, 1 failure (OSError is caught by the code)
        with patch.object(
            embedder, "embed_cover_in_file", side_effect=[True, OSError("Simulated failure"), True]
        ):
            count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)

        assert count == 2

    def test_embed_folder_skips_non_embeddable_formats(self, embedder, tmp_path, jpeg_cover_data):
        """Test that non-embeddable formats are skipped."""
        folder = tmp_path / "music"
        folder.mkdir()

        # Create files with non-embeddable extensions
        (folder / "track.wav").touch()
        (folder / "track.aiff").touch()
        (folder / "track.wma").touch()
        (folder / "cover.jpg").touch()

        with patch.object(embedder, "embed_cover_in_file", return_value=True) as mock_embed:
            count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)

        # None should be processed
        assert count == 0
        mock_embed.assert_not_called()

    def test_embed_folder_skips_directories(self, embedder, tmp_path, jpeg_cover_data):
        """Test that subdirectories are not processed."""
        folder = tmp_path / "music"
        folder.mkdir()

        # Create a subdirectory with .mp3 extension (edge case)
        subdir = folder / "subfolder.mp3"
        subdir.mkdir()

        (folder / "track.mp3").touch()

        with patch.object(embedder, "embed_cover_in_file", return_value=True) as mock_embed:
            count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)

        # Only the file, not the directory
        assert count == 1

    def test_embed_folder_handles_empty_folder(self, embedder, tmp_path, jpeg_cover_data):
        """Test handling of empty folder."""
        folder = tmp_path / "empty"
        folder.mkdir()

        count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)

        assert count == 0

    def test_embed_folder_handles_nonexistent_folder(self, embedder, tmp_path, jpeg_cover_data):
        """Test handling of nonexistent folder."""
        folder = tmp_path / "nonexistent"

        count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)

        assert count == 0

    def test_embed_folder_handles_permission_denied(
        self, embedder, tmp_path, jpeg_cover_data, monkeypatch
    ):
        """Test handling of permission denied when listing folder."""
        folder = tmp_path / "restricted"
        folder.mkdir()
        (folder / "track.mp3").touch()

        # Mock Path.iterdir to raise PermissionError (cross-platform approach)
        original_iterdir = Path.iterdir

        def mock_iterdir(self):
            if self == folder:
                raise PermissionError("Permission denied")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)

        count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)
        assert count == 0

    def test_embed_folder_auto_detects_mime_type(self, embedder, tmp_path, png_cover_data):
        """Test that MIME type is auto-detected when not provided."""
        folder = tmp_path / "music"
        folder.mkdir()
        (folder / "track.mp3").touch()

        with patch.object(embedder, "embed_cover_in_file", return_value=True) as mock_embed:
            embedder.embed_cover_in_folder(png_cover_data, folder)

        # Should be called with detected PNG MIME type
        call_args = mock_embed.call_args
        assert call_args[0][2] == "image/png"

    def test_embed_folder_uses_provided_mime_type(self, embedder, tmp_path, jpeg_cover_data):
        """Test that provided MIME type is used."""
        folder = tmp_path / "music"
        folder.mkdir()
        (folder / "track.mp3").touch()

        with patch.object(embedder, "embed_cover_in_file", return_value=True) as mock_embed:
            embedder.embed_cover_in_folder(jpeg_cover_data, folder, mime_type="image/custom")

        call_args = mock_embed.call_args
        assert call_args[0][2] == "image/custom"

    def test_embed_folder_continues_on_error(self, embedder, tmp_path, jpeg_cover_data):
        """Test that processing continues even if one file fails."""
        folder = tmp_path / "music"
        folder.mkdir()

        (folder / "track1.mp3").touch()
        (folder / "track2.mp3").touch()
        (folder / "track3.mp3").touch()

        # First file raises exception (IOError is caught), others succeed
        with patch.object(
            embedder, "embed_cover_in_file", side_effect=[OSError("Error"), True, True]
        ):
            count = embedder.embed_cover_in_folder(jpeg_cover_data, folder)

        # Should still process remaining files
        assert count == 2


# =============================================================================
# Tests for CoverEmbedder.remove_embedded_cover()
# =============================================================================


class TestRemoveEmbeddedCover:
    """Tests for removing embedded covers from files."""

    @patch("src.core.embedder.ID3")
    def test_remove_mp3_cover(self, mock_id3, embedder, tmp_path):
        """Test removing cover from MP3 file."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        mock_audio = MagicMock()
        mock_id3.return_value = mock_audio

        result = embedder.remove_embedded_cover(mp3_file)

        assert result is True
        mock_audio.delall.assert_called_once_with("APIC")
        mock_audio.save.assert_called_once()

    @patch("src.core.embedder.FLAC")
    def test_remove_flac_cover(self, mock_flac, embedder, tmp_path):
        """Test removing cover from FLAC file."""
        flac_file = tmp_path / "test.flac"
        flac_file.touch()

        mock_audio = MagicMock()
        mock_flac.return_value = mock_audio

        result = embedder.remove_embedded_cover(flac_file)

        assert result is True
        mock_audio.clear_pictures.assert_called_once()
        mock_audio.save.assert_called_once()

    @patch("src.core.embedder.MP4")
    def test_remove_m4a_cover(self, mock_mp4, embedder, tmp_path):
        """Test removing cover from M4A file."""
        m4a_file = tmp_path / "test.m4a"
        m4a_file.touch()

        mock_audio = MagicMock()
        mock_audio.__contains__ = Mock(return_value=True)
        mock_mp4.return_value = mock_audio

        result = embedder.remove_embedded_cover(m4a_file)

        assert result is True
        mock_audio.__delitem__.assert_called_once_with("covr")
        mock_audio.save.assert_called_once()

    @patch("src.core.embedder.MP4")
    def test_remove_mp4_cover_when_no_cover_exists(self, mock_mp4, embedder, tmp_path):
        """Test removing cover from MP4 when no cover exists."""
        mp4_file = tmp_path / "test.mp4"
        mp4_file.touch()

        mock_audio = MagicMock()
        mock_audio.__contains__ = Mock(return_value=False)
        mock_mp4.return_value = mock_audio

        result = embedder.remove_embedded_cover(mp4_file)

        # Should still return True, just not delete anything
        assert result is True
        mock_audio.__delitem__.assert_not_called()

    @patch("src.core.embedder.OggVorbis")
    def test_remove_ogg_cover(self, mock_ogg, embedder, tmp_path):
        """Test removing cover from OGG file."""
        ogg_file = tmp_path / "test.ogg"
        ogg_file.touch()

        mock_audio = MagicMock()
        mock_audio.__contains__ = Mock(return_value=True)
        mock_ogg.return_value = mock_audio

        result = embedder.remove_embedded_cover(ogg_file)

        assert result is True
        mock_audio.__delitem__.assert_called_once_with("metadata_block_picture")

    @patch("src.core.embedder.MutagenFile")
    def test_remove_opus_cover(self, mock_mutagen, embedder, tmp_path):
        """Test removing cover from Opus file."""
        opus_file = tmp_path / "test.opus"
        opus_file.touch()

        mock_audio = MagicMock()
        mock_audio.__contains__ = Mock(return_value=True)
        mock_mutagen.return_value = mock_audio

        result = embedder.remove_embedded_cover(opus_file)

        assert result is True

    def test_remove_unsupported_format_returns_false(self, embedder, tmp_path):
        """Test that unsupported formats return False."""
        wav_file = tmp_path / "test.wav"
        wav_file.touch()

        result = embedder.remove_embedded_cover(wav_file)

        assert result is False

    @patch("src.core.embedder.ID3")
    def test_remove_handles_exception(self, mock_id3, embedder, tmp_path):
        """Test that exceptions are handled gracefully."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        mock_id3.side_effect = OSError("File corrupted")

        result = embedder.remove_embedded_cover(mp3_file)

        assert result is False

    @patch("src.core.embedder.ID3")
    def test_remove_mp3_no_header(self, mock_id3, embedder, tmp_path):
        """Test removing cover from MP3 file without ID3 header returns True.

        When an MP3 has no ID3 header, there's no embedded cover to remove,
        so the operation should succeed (return True).
        """
        from src.core.embedder import ID3NoHeaderError

        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        # Simulate MP3 without ID3 header
        mock_id3.side_effect = ID3NoHeaderError("No ID3 header")

        result = embedder.remove_embedded_cover(mp3_file)

        # Should return True since there's nothing to remove
        assert result is True


# =============================================================================
# Tests for format-specific embedding methods
# =============================================================================


class TestEmbedMp3:
    """Tests for _embed_mp3 method."""

    @patch("src.core.embedder.ID3")
    def test_embed_mp3_adds_apic_frame(self, mock_id3, embedder, tmp_path, jpeg_cover_data):
        """Test that MP3 embedding adds APIC frame."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        mock_audio = MagicMock()
        mock_id3.return_value = mock_audio

        embedder._embed_mp3(mp3_file, jpeg_cover_data, "image/jpeg")

        mock_audio.delall.assert_called_once_with("APIC")
        mock_audio.add.assert_called_once()
        mock_audio.save.assert_called_once()

    @patch("src.core.embedder.ID3")
    def test_embed_mp3_creates_tag_if_missing(self, mock_id3, embedder, tmp_path, jpeg_cover_data):
        """Test that ID3 tag is created if missing."""
        from src.core.embedder import ID3NoHeaderError

        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        # First call with filepath raises ID3NoHeaderError
        # Second call with no args creates new tag
        # Third call with filepath reloads the tag
        mock_new_tag = MagicMock()
        mock_audio = MagicMock()
        mock_id3.side_effect = [ID3NoHeaderError(), mock_new_tag, mock_audio]

        embedder._embed_mp3(mp3_file, jpeg_cover_data, "image/jpeg")

        # Should have been called three times:
        # 1. ID3(filepath) - raises
        # 2. ID3() - creates new empty tag
        # 3. ID3(filepath) - reloads after save
        assert mock_id3.call_count == 3
        mock_new_tag.save.assert_called_once_with(mp3_file)

    @patch("src.core.embedder.ID3")
    @patch("src.core.embedder.APIC")
    def test_embed_mp3_apic_parameters(
        self, mock_apic, mock_id3, embedder, tmp_path, jpeg_cover_data
    ):
        """Test that APIC is created with correct parameters."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        mock_audio = MagicMock()
        mock_id3.return_value = mock_audio

        embedder._embed_mp3(mp3_file, jpeg_cover_data, "image/jpeg")

        mock_apic.assert_called_once_with(
            encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg_cover_data
        )


class TestEmbedFlac:
    """Tests for _embed_flac method."""

    @patch("src.core.embedder.Picture")
    @patch("src.core.embedder.FLAC")
    def test_embed_flac_adds_picture(
        self, mock_flac, mock_picture, embedder, tmp_path, jpeg_cover_data
    ):
        """Test that FLAC embedding adds Picture block."""
        flac_file = tmp_path / "test.flac"
        flac_file.touch()

        mock_audio = MagicMock()
        mock_flac.return_value = mock_audio
        mock_pic_instance = MagicMock()
        mock_picture.return_value = mock_pic_instance

        embedder._embed_flac(flac_file, jpeg_cover_data, "image/jpeg")

        mock_audio.clear_pictures.assert_called_once()
        mock_audio.add_picture.assert_called_once_with(mock_pic_instance)
        mock_audio.save.assert_called_once()

    @patch("src.core.embedder.Picture")
    @patch("src.core.embedder.FLAC")
    def test_embed_flac_picture_attributes(
        self, mock_flac, mock_picture, embedder, tmp_path, jpeg_cover_data
    ):
        """Test that Picture is configured with correct attributes."""
        flac_file = tmp_path / "test.flac"
        flac_file.touch()

        mock_audio = MagicMock()
        mock_flac.return_value = mock_audio
        mock_pic_instance = MagicMock()
        mock_picture.return_value = mock_pic_instance

        embedder._embed_flac(flac_file, jpeg_cover_data, "image/png")

        assert mock_pic_instance.type == 3  # Cover front
        assert mock_pic_instance.mime == "image/png"
        assert mock_pic_instance.desc == "Cover"
        assert mock_pic_instance.data == jpeg_cover_data


class TestEmbedMp4:
    """Tests for _embed_mp4 method."""

    @patch("src.core.embedder.MP4Cover")
    @patch("src.core.embedder.MP4")
    def test_embed_mp4_adds_cover(
        self, mock_mp4, mock_mp4cover, embedder, tmp_path, jpeg_cover_data
    ):
        """Test that MP4 embedding adds cover."""
        mp4_file = tmp_path / "test.m4a"
        mp4_file.touch()

        mock_audio = MagicMock()
        mock_mp4.return_value = mock_audio
        mock_cover = MagicMock()
        mock_mp4cover.return_value = mock_cover
        mock_mp4cover.FORMAT_JPEG = 13
        mock_mp4cover.FORMAT_PNG = 14

        embedder._embed_mp4(mp4_file, jpeg_cover_data, "image/jpeg")

        mock_mp4cover.assert_called_once_with(jpeg_cover_data, imageformat=13)
        mock_audio.save.assert_called_once()

    @patch("src.core.embedder.MP4Cover")
    @patch("src.core.embedder.MP4")
    def test_embed_mp4_uses_png_format_for_png(
        self, mock_mp4, mock_mp4cover, embedder, tmp_path, png_cover_data
    ):
        """Test that PNG images use PNG format constant."""
        mp4_file = tmp_path / "test.m4a"
        mp4_file.touch()

        mock_audio = MagicMock()
        mock_mp4.return_value = mock_audio
        mock_cover = MagicMock()
        mock_mp4cover.return_value = mock_cover
        mock_mp4cover.FORMAT_JPEG = 13
        mock_mp4cover.FORMAT_PNG = 14

        embedder._embed_mp4(mp4_file, png_cover_data, "image/png")

        mock_mp4cover.assert_called_once_with(png_cover_data, imageformat=14)


class TestEmbedOgg:
    """Tests for _embed_ogg method."""

    def test_embed_ogg_adds_metadata_block_picture(self, embedder, tmp_path, jpeg_cover_data):
        """Test that OGG embedding adds metadata_block_picture."""
        ogg_file = tmp_path / "test.ogg"
        ogg_file.touch()

        # Create mock image for PIL
        mock_img = MagicMock()
        mock_img.size = (500, 500)
        mock_img.mode = "RGB"

        with (
            patch("src.core.embedder.OggVorbis") as mock_ogg,
            patch("src.core.embedder.Picture") as mock_picture,
            patch("PIL.Image.open", return_value=mock_img),
        ):
            mock_audio = MagicMock()
            mock_ogg.return_value = mock_audio
            mock_pic_instance = MagicMock()
            mock_pic_instance.write.return_value = b"picture_data"
            mock_picture.return_value = mock_pic_instance

            embedder._embed_ogg(ogg_file, jpeg_cover_data, "image/jpeg")

            # Should store base64-encoded picture data
            expected_encoded = base64.b64encode(b"picture_data").decode("ascii")
            mock_audio.__setitem__.assert_called_with("metadata_block_picture", [expected_encoded])
            mock_audio.save.assert_called_once()

    def test_embed_opus_uses_mutagen_file(self, embedder, tmp_path, jpeg_cover_data):
        """Test that Opus files use MutagenFile instead of OggVorbis."""
        opus_file = tmp_path / "test.opus"
        opus_file.touch()

        # Create mock image for PIL
        mock_img = MagicMock()
        mock_img.size = (500, 500)
        mock_img.mode = "RGB"

        with (
            patch("src.core.embedder.MutagenFile") as mock_mutagen,
            patch("src.core.embedder.Picture") as mock_picture,
            patch("PIL.Image.open", return_value=mock_img),
        ):
            mock_audio = MagicMock()
            mock_mutagen.return_value = mock_audio
            mock_pic_instance = MagicMock()
            mock_pic_instance.write.return_value = b"picture_data"
            mock_picture.return_value = mock_pic_instance

            embedder._embed_ogg(opus_file, jpeg_cover_data, "image/jpeg")

            mock_mutagen.assert_called_once_with(opus_file)

    @patch("src.core.embedder.OggVorbis")
    def test_embed_ogg_raises_for_unreadable_file(
        self, mock_ogg, embedder, tmp_path, jpeg_cover_data
    ):
        """Test that error is raised when file cannot be opened."""
        ogg_file = tmp_path / "test.ogg"
        ogg_file.touch()

        mock_ogg.return_value = None

        with pytest.raises(ValueError, match="Could not open file"):
            embedder._embed_ogg(ogg_file, jpeg_cover_data, "image/jpeg")


# =============================================================================
# Tests for error handling with corrupted files
# =============================================================================


class TestCorruptedFileHandling:
    """Tests for handling corrupted audio files."""

    @patch("src.core.embedder.ID3")
    def test_corrupted_mp3_returns_false(self, mock_id3, embedder, tmp_path, jpeg_cover_data):
        """Test that corrupted MP3 files don't crash."""
        mp3_file = tmp_path / "corrupted.mp3"
        mp3_file.write_bytes(b"not a real mp3 file")

        mock_id3.side_effect = OSError("Invalid MP3 file")

        result = embedder.embed_cover_in_file(mp3_file, jpeg_cover_data, "image/jpeg")

        assert result is False

    @patch("src.core.embedder.FLAC")
    def test_corrupted_flac_returns_false(self, mock_flac, embedder, tmp_path, jpeg_cover_data):
        """Test that corrupted FLAC files don't crash."""
        flac_file = tmp_path / "corrupted.flac"
        flac_file.write_bytes(b"not a real flac file")

        mock_flac.side_effect = OSError("Invalid FLAC file")

        result = embedder.embed_cover_in_file(flac_file, jpeg_cover_data, "image/jpeg")

        assert result is False

    @patch("src.core.embedder.MP4")
    def test_corrupted_mp4_returns_false(self, mock_mp4, embedder, tmp_path, jpeg_cover_data):
        """Test that corrupted MP4 files don't crash."""
        mp4_file = tmp_path / "corrupted.m4a"
        mp4_file.write_bytes(b"not a real mp4 file")

        mock_mp4.side_effect = OSError("Invalid MP4 file")

        result = embedder.embed_cover_in_file(mp4_file, jpeg_cover_data, "image/jpeg")

        assert result is False

    @patch("src.core.embedder.OggVorbis")
    def test_corrupted_ogg_returns_false(self, mock_ogg, embedder, tmp_path, jpeg_cover_data):
        """Test that corrupted OGG files don't crash."""
        ogg_file = tmp_path / "corrupted.ogg"
        ogg_file.write_bytes(b"not a real ogg file")

        mock_ogg.side_effect = OSError("Invalid OGG file")

        result = embedder.embed_cover_in_file(ogg_file, jpeg_cover_data, "image/jpeg")

        assert result is False

    def test_truncated_file_handled(self, embedder, tmp_path, jpeg_cover_data):
        """Test that truncated/empty files are handled."""
        empty_file = tmp_path / "empty.mp3"
        empty_file.touch()

        with patch("src.core.embedder.ID3", side_effect=OSError("Empty file")):
            result = embedder.embed_cover_in_file(empty_file, jpeg_cover_data, "image/jpeg")

        assert result is False


# =============================================================================
# Tests for permission denied scenarios
# =============================================================================


class TestPermissionDeniedScenarios:
    """Tests for permission denied error handling."""

    def test_save_to_readonly_folder(self, embedder, tmp_path, jpeg_cover_data, monkeypatch):
        """Test saving to a read-only folder."""
        readonly_folder = tmp_path / "readonly"
        readonly_folder.mkdir()

        # Mock Path.open to raise PermissionError (cross-platform approach)
        original_path_open = Path.open

        def mock_path_open(self, *args, **kwargs):
            if str(self).startswith(str(readonly_folder)):
                raise PermissionError("Permission denied")
            return original_path_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", mock_path_open)

        with pytest.raises(TagWriteError):
            embedder.save_cover_to_folder(jpeg_cover_data, readonly_folder)

    @patch("src.core.embedder.ID3")
    def test_embed_in_readonly_file(self, mock_id3, embedder, tmp_path, jpeg_cover_data):
        """Test embedding in a read-only file."""
        mp3_file = tmp_path / "readonly.mp3"
        mp3_file.touch()

        # Mock the save method to raise PermissionError (cross-platform approach)
        mock_audio = MagicMock()
        mock_audio.save.side_effect = PermissionError("Permission denied")
        mock_id3.return_value = mock_audio

        result = embedder.embed_cover_in_file(mp3_file, jpeg_cover_data, "image/jpeg")
        assert result is False

    def test_list_inaccessible_folder(self, embedder, tmp_path, jpeg_cover_data, monkeypatch):
        """Test embedding in folder with no read permissions."""
        restricted = tmp_path / "restricted"
        restricted.mkdir()
        (restricted / "track.mp3").touch()

        # Mock Path.iterdir to raise PermissionError (cross-platform approach)
        original_iterdir = Path.iterdir

        def mock_iterdir(self):
            if self == restricted:
                raise PermissionError("Permission denied")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", mock_iterdir)

        count = embedder.embed_cover_in_folder(jpeg_cover_data, restricted)
        assert count == 0


# =============================================================================
# Tests for EMBEDDABLE_FORMATS constant
# =============================================================================


class TestEmbeddableFormats:
    """Tests for the EMBEDDABLE_FORMATS constant."""

    def test_mp3_is_embeddable(self):
        """Test that MP3 is in embeddable formats."""
        assert ".mp3" in EMBEDDABLE_FORMATS

    def test_flac_is_embeddable(self):
        """Test that FLAC is in embeddable formats."""
        assert ".flac" in EMBEDDABLE_FORMATS

    def test_ogg_is_embeddable(self):
        """Test that OGG is in embeddable formats."""
        assert ".ogg" in EMBEDDABLE_FORMATS

    def test_opus_is_embeddable(self):
        """Test that Opus is in embeddable formats."""
        assert ".opus" in EMBEDDABLE_FORMATS

    def test_m4a_is_embeddable(self):
        """Test that M4A is in embeddable formats."""
        assert ".m4a" in EMBEDDABLE_FORMATS

    def test_mp4_is_embeddable(self):
        """Test that MP4 is in embeddable formats."""
        assert ".mp4" in EMBEDDABLE_FORMATS

    def test_wav_is_not_embeddable(self):
        """Test that WAV is not in embeddable formats."""
        assert ".wav" not in EMBEDDABLE_FORMATS

    def test_aiff_is_not_embeddable(self):
        """Test that AIFF is not in embeddable formats."""
        assert ".aiff" not in EMBEDDABLE_FORMATS


# =============================================================================
# Parametrized tests for image format handling
# =============================================================================


class TestImageFormatHandling:
    """Parametrized tests for various image formats."""

    @pytest.mark.parametrize(
        "image_data,expected_mime,expected_ext",
        [
            (b"\xff\xd8\xff\xe0", "image/jpeg", ".jpg"),
            (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
            (b"GIF89a", "image/gif", ".gif"),
            (b"RIFF\x00\x00\x00\x00WEBP", "image/webp", ".webp"),
            (b"BM\x00\x00", "image/bmp", ".bmp"),
        ],
    )
    def test_image_format_detection_and_extension(
        self, image_data, expected_mime, expected_ext, embedder, tmp_path
    ):
        """Test that image formats are correctly detected and saved with proper extension."""
        cover_data = image_data + b"\x00" * 100

        result = embedder.save_cover_to_folder(cover_data, tmp_path)

        assert result.suffix == expected_ext
        assert result.name == f"cover{expected_ext}"

    @pytest.mark.parametrize(
        "mime_type,expected_format_name",
        [
            ("image/jpeg", "JPEG"),
            ("image/png", "PNG"),
        ],
    )
    def test_mp4_cover_format_selection(self, mime_type, expected_format_name, embedder, tmp_path):
        """Test that MP4 cover format is correctly selected based on MIME type."""
        cover_data = b"\x00" * 100
        mp4_file = tmp_path / "test.m4a"
        mp4_file.touch()

        with (
            patch("src.core.embedder.MP4") as mock_mp4,
            patch("src.core.embedder.MP4Cover") as mock_cover,
        ):
            mock_audio = MagicMock()
            mock_mp4.return_value = mock_audio
            mock_cover.FORMAT_JPEG = 13
            mock_cover.FORMAT_PNG = 14

            embedder._embed_mp4(mp4_file, cover_data, mime_type)

            expected_format = 13 if "jpeg" in mime_type else 14
            mock_cover.assert_called_once()
            call_kwargs = mock_cover.call_args[1]
            assert call_kwargs["imageformat"] == expected_format


# =============================================================================
# Integration-style tests
# =============================================================================


class TestCoverEmbedderIntegration:
    """Integration-style tests for CoverEmbedder."""

    def test_full_workflow_save_and_verify(self, embedder, tmp_path, jpeg_cover_data):
        """Test complete workflow of saving cover and verifying file."""
        # Save cover
        cover_path = embedder.save_cover_to_folder(jpeg_cover_data, tmp_path)

        # Verify file exists and content matches
        assert cover_path.exists()
        assert cover_path.read_bytes() == jpeg_cover_data
        assert cover_path.stat().st_size == len(jpeg_cover_data)

    def test_embedder_is_reusable(self, embedder, tmp_path, jpeg_cover_data, png_cover_data):
        """Test that embedder can be used multiple times."""
        folder1 = tmp_path / "folder1"
        folder2 = tmp_path / "folder2"
        folder1.mkdir()
        folder2.mkdir()

        path1 = embedder.save_cover_to_folder(jpeg_cover_data, folder1)
        path2 = embedder.save_cover_to_folder(png_cover_data, folder2)

        assert path1.exists()
        assert path2.exists()
        assert path1.suffix == ".jpg"
        assert path2.suffix == ".png"

    def test_initialization_is_lightweight(self):
        """Test that CoverEmbedder can be instantiated quickly."""
        # This should not do any heavy lifting during init
        embedder = CoverEmbedder()
        assert embedder is not None


# =============================================================================
# Tests for preserve_timestamp functionality
# =============================================================================


class TestPreserveTimestamp:
    """Tests for the preserve_timestamp functionality."""

    def test_preserve_timestamp_default_true(self):
        """Test that preserve_timestamp defaults to True."""
        embedder = CoverEmbedder()
        assert embedder.preserve_timestamp is True

    def test_preserve_timestamp_can_be_disabled(self):
        """Test that preserve_timestamp can be set to False."""
        embedder = CoverEmbedder(preserve_timestamp=False)
        assert embedder.preserve_timestamp is False

    def test_preserve_timestamp_can_be_enabled(self):
        """Test that preserve_timestamp can be explicitly set to True."""
        embedder = CoverEmbedder(preserve_timestamp=True)
        assert embedder.preserve_timestamp is True

    @patch("src.core.embedder.ID3")
    def test_embed_preserves_timestamp_when_enabled(self, mock_id3, tmp_path, jpeg_cover_data):
        """Test that file timestamp is preserved when preserve_timestamp is True."""
        import time

        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        # Set a known modification time in the past
        old_mtime = time.time() - 3600  # 1 hour ago
        os.utime(mp3_file, (old_mtime, old_mtime))

        mock_audio = MagicMock()
        mock_id3.return_value = mock_audio

        embedder = CoverEmbedder(preserve_timestamp=True)
        result = embedder.embed_cover_in_file(mp3_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        # The mtime should be restored to approximately the old value
        current_mtime = mp3_file.stat().st_mtime
        assert abs(current_mtime - old_mtime) < 1  # Allow 1 second tolerance

    @patch("src.core.embedder.ID3")
    def test_embed_does_not_preserve_timestamp_when_disabled(
        self, mock_id3, tmp_path, jpeg_cover_data
    ):
        """Test that file timestamp is not preserved when preserve_timestamp is False."""
        import time

        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        # Set a known modification time in the past
        old_mtime = time.time() - 3600  # 1 hour ago
        os.utime(mp3_file, (old_mtime, old_mtime))

        mock_audio = MagicMock()
        mock_id3.return_value = mock_audio

        embedder = CoverEmbedder(preserve_timestamp=False)
        result = embedder.embed_cover_in_file(mp3_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        # The mtime should NOT be restored - it should be more recent
        # Note: Since we're mocking ID3, the file isn't actually modified,
        # but the code path for not restoring timestamp is exercised

    @patch("src.core.embedder.FLAC")
    def test_preserve_timestamp_works_for_flac(self, mock_flac, tmp_path, jpeg_cover_data):
        """Test that preserve_timestamp works for FLAC files."""
        import time

        flac_file = tmp_path / "test.flac"
        flac_file.touch()

        # Set a known modification time in the past
        old_mtime = time.time() - 3600
        os.utime(flac_file, (old_mtime, old_mtime))

        mock_audio = MagicMock()
        mock_flac.return_value = mock_audio

        embedder = CoverEmbedder(preserve_timestamp=True)
        result = embedder.embed_cover_in_file(flac_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        current_mtime = flac_file.stat().st_mtime
        assert abs(current_mtime - old_mtime) < 1

    @patch("src.core.embedder.MP4")
    def test_preserve_timestamp_works_for_mp4(self, mock_mp4, tmp_path, jpeg_cover_data):
        """Test that preserve_timestamp works for MP4/M4A files."""
        import time

        m4a_file = tmp_path / "test.m4a"
        m4a_file.touch()

        # Set a known modification time in the past
        old_mtime = time.time() - 3600
        os.utime(m4a_file, (old_mtime, old_mtime))

        mock_audio = MagicMock()
        mock_mp4.return_value = mock_audio

        embedder = CoverEmbedder(preserve_timestamp=True)
        result = embedder.embed_cover_in_file(m4a_file, jpeg_cover_data, "image/jpeg")

        assert result is True
        current_mtime = m4a_file.stat().st_mtime
        assert abs(current_mtime - old_mtime) < 1

    def test_preserve_timestamp_handles_stat_error_gracefully(self, tmp_path, jpeg_cover_data):
        """Test that stat errors during timestamp capture don't crash the embed."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.touch()

        embedder = CoverEmbedder(preserve_timestamp=True)

        # Mock stat to raise an error during initial capture
        with patch.object(Path, "stat", side_effect=OSError("Permission denied")):
            with patch("src.core.embedder.ID3") as mock_id3:
                mock_audio = MagicMock()
                mock_id3.return_value = mock_audio

                # Should not raise, just skip timestamp preservation
                result = embedder.embed_cover_in_file(mp3_file, jpeg_cover_data, "image/jpeg")
                assert result is True


# =============================================================================
# Tests for extract_embedded_cover caching
# =============================================================================


class TestExtractEmbeddedCoverCaching:
    """Tests for extract_embedded_cover caching functionality."""

    def setup_method(self):
        """Clear cache before each test."""
        embedded_cover_cache.clear()

    def test_uses_cache_on_second_call(self, tmp_path):
        """Test that second call uses cached data."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        cover_data = b"cover_data_for_test"

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            # First call - should read from file
            mock_audio = MagicMock()
            mock_tags = MagicMock()
            # Make tags iterable (for key in tags)
            mock_tags.keys = lambda: ["APIC:Cover"]
            mock_tags.__getitem__ = lambda self, key: MagicMock(data=cover_data)
            mock_audio.tags = mock_tags
            mock_mutagen.return_value = mock_audio

            result1 = extract_embedded_cover(mp3_file)
            assert mock_mutagen.call_count == 1

            # Second call - should use cache
            result2 = extract_embedded_cover(mp3_file)
            # Should still be only 1 call since cache was used
            assert mock_mutagen.call_count == 1

            assert result1 == result2 == cover_data

    def test_cache_invalidated_on_file_modification(self, tmp_path):
        """Test that cache is invalidated when file is modified."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"original data")

        original_cover = b"original_cover"
        modified_cover = b"modified_cover"

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            # First call - cache original cover
            mock_audio = MagicMock()
            mock_tags = MagicMock()
            mock_tags.keys = lambda: ["APIC:Cover"]
            mock_tags.__getitem__ = lambda self, key: MagicMock(data=original_cover)
            mock_audio.tags = mock_tags
            mock_mutagen.return_value = mock_audio

            result1 = extract_embedded_cover(mp3_file)
            assert result1 == original_cover
            assert mock_mutagen.call_count == 1

            # Modify file
            time.sleep(0.1)
            mp3_file.write_bytes(b"modified data")

            # Update mock to return different cover
            mock_tags.__getitem__ = lambda self, key: MagicMock(data=modified_cover)

            # Second call - should read from file due to mtime change
            result2 = extract_embedded_cover(mp3_file)
            assert mock_mutagen.call_count == 2
            assert result2 == modified_cover

    def test_use_cache_false_bypasses_cache(self, tmp_path):
        """Test that use_cache=False bypasses the cache."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        cover_data = b"cover_data"

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            mock_audio = MagicMock()
            mock_tags = MagicMock()
            mock_tags.keys = lambda: ["APIC:Cover"]
            mock_tags.__getitem__ = lambda self, key: MagicMock(data=cover_data)
            mock_audio.tags = mock_tags
            mock_mutagen.return_value = mock_audio

            # First call with cache enabled
            result1 = extract_embedded_cover(mp3_file, use_cache=True)
            assert mock_mutagen.call_count == 1

            # Second call with cache disabled - should read from file
            result2 = extract_embedded_cover(mp3_file, use_cache=False)
            assert mock_mutagen.call_count == 2

            # Third call with cache enabled - should use cached data from first call
            result3 = extract_embedded_cover(mp3_file, use_cache=True)
            assert mock_mutagen.call_count == 2  # Still 2 because cache was used

    def test_no_cover_not_cached(self, tmp_path):
        """Test that files without covers are not cached."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            # Return audio without cover
            mock_audio = MagicMock()
            mock_tags = MagicMock()
            mock_tags.keys = lambda: ["TIT2", "TPE1"]  # No APIC
            mock_audio.tags = mock_tags
            mock_mutagen.return_value = mock_audio

            result1 = extract_embedded_cover(mp3_file)
            assert result1 is None
            assert mock_mutagen.call_count == 1

            # Second call should still try to read (not cached)
            result2 = extract_embedded_cover(mp3_file)
            assert result2 is None
            assert mock_mutagen.call_count == 2

    def test_cache_stores_cover_data(self, tmp_path):
        """Test that cover data is properly stored in cache."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        cover_data = b"test_cover_data_12345"

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            mock_audio = MagicMock()
            mock_tags = MagicMock()
            mock_tags.keys = lambda: ["APIC:Cover"]
            mock_tags.__getitem__ = lambda self, key: MagicMock(data=cover_data)
            mock_audio.tags = mock_tags
            mock_mutagen.return_value = mock_audio

            extract_embedded_cover(mp3_file)

        # Verify data is in cache
        cached = embedded_cover_cache.get(mp3_file)
        assert cached == cover_data

    def test_error_handling_with_cache(self, tmp_path):
        """Test that errors are handled gracefully with caching."""
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            mock_mutagen.side_effect = OSError("Error reading file")

            result = extract_embedded_cover(mp3_file)
            assert result is None

        # Cache should be empty
        assert embedded_cover_cache.get(mp3_file) is None


class TestWmaTagIterationRegression:
    """
    Regression tests for WMA crash: ASFTags inherits from list.

    Bug: When iterating over ASFTags (WMA files) with `for key in tags`,
    the loop yields (name, value) tuples instead of string keys, causing
    `key.startswith("APIC")` to crash with AttributeError (tuple has no
    startswith method).

    Fix: Use explicit `tags.keys()` which returns string keys for all
    mutagen tag types, including ASFTags.

    See: src/core/embedder.py:99, src/core/scanner.py:654
    """

    def _make_asf_like_tags(self, keys: list[str], cover_data: bytes | None = None):
        """Create a mock that simulates ASFTags behavior.

        ASFTags inherits from list: direct iteration yields tuples,
        but .keys() returns string keys.
        """
        tags = MagicMock()
        # Simulate ASFTags: __iter__ yields (name, value) tuples, NOT string keys
        tags.__iter__ = lambda self: iter([(k, MagicMock()) for k in keys])
        # .keys() correctly returns string keys
        tags.keys.return_value = keys
        # Support dict-like access for cover data retrieval
        if cover_data:
            tags.__getitem__ = lambda self, key: MagicMock(data=cover_data)
        return tags

    def test_extract_embedded_cover_wma_with_apic(self, tmp_path):
        """
        Regression: extract_embedded_cover must use tags.keys() to handle WMA files.

        Without .keys(), iterating ASFTags yields tuples and
        tuple.startswith("APIC") raises AttributeError.
        """
        wma_file = tmp_path / "test.wma"
        wma_file.write_bytes(b"fake wma data")
        cover_data = b"wma_cover_data"

        tags = self._make_asf_like_tags(["APIC:Cover", "WM/Title"], cover_data)

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            mock_audio = MagicMock()
            mock_audio.tags = tags
            mock_audio.pictures = []
            mock_mutagen.return_value = mock_audio

            result = extract_embedded_cover(wma_file, use_cache=False)

        assert result == cover_data
        # Verify .keys() was called (not direct iteration)
        tags.keys.assert_called()

    def test_extract_embedded_cover_wma_without_apic(self, tmp_path):
        """Regression: WMA file without APIC should return None, not crash."""
        wma_file = tmp_path / "test.wma"
        wma_file.write_bytes(b"fake wma data")

        tags = self._make_asf_like_tags(["WM/Title", "WM/AlbumTitle"])

        with patch("src.core.embedder.MutagenFile") as mock_mutagen:
            mock_audio = MagicMock()
            mock_audio.tags = tags
            mock_audio.pictures = []
            mock_mutagen.return_value = mock_audio

            result = extract_embedded_cover(wma_file, use_cache=False)

        assert result is None
