"""
Tests for the cover hash module.
"""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.cover_hash import (
    compute_cover_hash,
    compute_embedded_hash,
    compute_folder_hash,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_image_data():
    """Sample image data for testing."""
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 100


@pytest.fixture
def another_image_data():
    """Different image data for testing."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100


@pytest.fixture
def temp_cover_file(tmp_path, sample_image_data):
    """Create a temporary cover file."""
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(sample_image_data)
    return cover_path


# =============================================================================
# Tests for compute_cover_hash()
# =============================================================================


class TestComputeCoverHash:
    """Tests for the compute_cover_hash function."""

    def test_returns_hex_string(self, sample_image_data):
        """Test that the function returns a hex string."""
        result = compute_cover_hash(sample_image_data)
        assert isinstance(result, str)
        assert all(c in "0123456789abcdef" for c in result)

    def test_consistent_hash(self, sample_image_data):
        """Test that the same data produces the same hash."""
        hash1 = compute_cover_hash(sample_image_data)
        hash2 = compute_cover_hash(sample_image_data)
        assert hash1 == hash2

    def test_different_data_different_hash(self, sample_image_data, another_image_data):
        """Test that different data produces different hashes."""
        hash1 = compute_cover_hash(sample_image_data)
        hash2 = compute_cover_hash(another_image_data)
        assert hash1 != hash2

    def test_matches_hashlib_sha256(self, sample_image_data):
        """Test that the hash matches hashlib SHA256."""
        expected = hashlib.sha256(sample_image_data).hexdigest()
        result = compute_cover_hash(sample_image_data)
        assert result == expected

    def test_hash_length_is_64_chars(self, sample_image_data):
        """Test that SHA256 hex digest is 64 characters."""
        result = compute_cover_hash(sample_image_data)
        assert len(result) == 64

    def test_empty_data(self):
        """Test hash of empty data."""
        result = compute_cover_hash(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected


# =============================================================================
# Tests for compute_embedded_hash()
# =============================================================================


class TestComputeEmbeddedHash:
    """Tests for the compute_embedded_hash function."""

    def test_returns_hash_when_cover_exists(self, tmp_path, sample_image_data):
        """Test that hash is returned when embedded cover exists."""
        audio_file = tmp_path / "test.mp3"
        audio_file.touch()

        with patch("src.utils.cover_hash.extract_embedded_cover") as mock_extract:
            mock_extract.return_value = sample_image_data
            result = compute_embedded_hash(audio_file)

            assert result is not None
            assert result == compute_cover_hash(sample_image_data)
            mock_extract.assert_called_once_with(audio_file, use_cache=False)

    def test_returns_none_when_no_cover(self, tmp_path):
        """Test that None is returned when no embedded cover."""
        audio_file = tmp_path / "test.mp3"
        audio_file.touch()

        with patch("src.utils.cover_hash.extract_embedded_cover") as mock_extract:
            mock_extract.return_value = None
            result = compute_embedded_hash(audio_file)

            assert result is None

    def test_returns_none_on_exception(self, tmp_path):
        """Test that None is returned on extraction error."""
        audio_file = tmp_path / "test.mp3"
        audio_file.touch()

        with patch("src.utils.cover_hash.extract_embedded_cover") as mock_extract:
            mock_extract.side_effect = OSError("Extraction error")
            result = compute_embedded_hash(audio_file)

            assert result is None

    def test_returns_none_for_empty_cover_data(self, tmp_path):
        """Test that None is returned for empty cover data (falsy)."""
        audio_file = tmp_path / "test.mp3"
        audio_file.touch()

        with patch("src.utils.cover_hash.extract_embedded_cover") as mock_extract:
            mock_extract.return_value = b""  # Empty bytes
            result = compute_embedded_hash(audio_file)

            assert result is None


# =============================================================================
# Tests for compute_folder_hash()
# =============================================================================


class TestComputeFolderHash:
    """Tests for the compute_folder_hash function."""

    def test_returns_hash_for_existing_file(self, temp_cover_file, sample_image_data):
        """Test that hash is returned for existing cover file."""
        result = compute_folder_hash(temp_cover_file)
        expected = compute_cover_hash(sample_image_data)
        assert result == expected

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        """Test that None is returned for non-existent file."""
        nonexistent = tmp_path / "nonexistent.jpg"
        result = compute_folder_hash(nonexistent)
        assert result is None

    def test_returns_none_on_read_error(self, tmp_path):
        """Test that None is returned on read error."""
        cover_path = tmp_path / "cover.jpg"
        cover_path.touch()

        with patch.object(Path, "read_bytes") as mock_read:
            mock_read.side_effect = OSError("Read error")
            result = compute_folder_hash(cover_path)
            assert result is None

    def test_returns_none_on_permission_error(self, tmp_path):
        """Test that None is returned on permission error."""
        cover_path = tmp_path / "cover.jpg"
        cover_path.touch()

        with patch.object(Path, "read_bytes") as mock_read:
            mock_read.side_effect = PermissionError("Permission denied")
            result = compute_folder_hash(cover_path)
            assert result is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestHashIntegration:
    """Integration tests for hash functions."""

    def test_same_image_same_hash_different_sources(self, tmp_path, sample_image_data):
        """Test that same image produces same hash regardless of source."""
        # Create folder cover
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(sample_image_data)

        # Simulate embedded cover with same data
        with patch("src.utils.cover_hash.extract_embedded_cover") as mock_extract:
            mock_extract.return_value = sample_image_data
            audio_file = tmp_path / "test.mp3"
            audio_file.touch()

            embedded_hash = compute_embedded_hash(audio_file)
            folder_hash = compute_folder_hash(cover_path)

            assert embedded_hash == folder_hash

    def test_different_images_different_hashes(
        self, tmp_path, sample_image_data, another_image_data
    ):
        """Test that different images produce different hashes."""
        # Create folder cover
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(sample_image_data)

        # Simulate embedded cover with different data
        with patch("src.utils.cover_hash.extract_embedded_cover") as mock_extract:
            mock_extract.return_value = another_image_data
            audio_file = tmp_path / "test.mp3"
            audio_file.touch()

            embedded_hash = compute_embedded_hash(audio_file)
            folder_hash = compute_folder_hash(cover_path)

            assert embedded_hash != folder_hash
