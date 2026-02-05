"""Tests for the ScanCache class."""

import json
import os
import time

import pytest

from src.core.models import AlbumInfo, CoverInfo
from src.core.scan_cache import CachedFolderInfo, ScanCache


@pytest.fixture
def temp_cache_path(tmp_path):
    """Create a temporary cache file path."""
    return tmp_path / "test_scan_cache.json"


@pytest.fixture
def sample_album(tmp_path):
    """Create a sample AlbumInfo for testing."""
    album_path = tmp_path / "Artist" / "Album"
    album_path.mkdir(parents=True, exist_ok=True)
    return AlbumInfo(
        path=album_path,
        artist="Test Artist",
        album="Test Album",
        year="2024",
        track_count=10,
        cover=CoverInfo(has_embedded=True, has_folder=False),
        sample_file=album_path / "track01.mp3",
        formats=[".mp3"],
    )


@pytest.fixture
def sample_album_dict(tmp_path):
    """Create a sample album data dictionary."""
    album_path = tmp_path / "Artist" / "Album"
    return {
        "path": str(album_path),
        "artist": "Test Artist",
        "album": "Test Album",
        "year": "2024",
        "track_count": 10,
        "cover": {"has_embedded": True, "has_folder": False},
        "sample_file": str(album_path / "track01.mp3"),
        "formats": [".mp3"],
    }


class TestCachedFolderInfo:
    """Tests for CachedFolderInfo dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        info = CachedFolderInfo(mtime=1234567890.0, album_data={"artist": "Test"})
        result = info.to_dict()

        assert result == {"mtime": 1234567890.0, "album_data": {"artist": "Test"}}

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {"mtime": 1234567890.0, "album_data": {"artist": "Test"}}
        info = CachedFolderInfo.from_dict(data)

        assert info.mtime == 1234567890.0
        assert info.album_data == {"artist": "Test"}

    def test_from_dict_missing_fields(self):
        """Test creation from dictionary with missing fields uses defaults."""
        info = CachedFolderInfo.from_dict({})

        assert info.mtime == 0.0
        assert info.album_data == {}


class TestScanCacheInit:
    """Tests for ScanCache initialization."""

    def test_init_with_custom_path(self, temp_cache_path):
        """Test initialization with custom cache path."""
        cache = ScanCache(cache_path=temp_cache_path)

        assert cache.cache_path == temp_cache_path
        assert cache.folder_count == 0

    def test_init_with_default_path(self, tmp_path, monkeypatch):
        """Test initialization uses XDG config path."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        cache = ScanCache()

        expected_path = tmp_path / "tunecover" / "scan_cache.json"
        assert cache.cache_path == expected_path

    def test_init_creates_config_dir(self, tmp_path, monkeypatch):
        """Test that initialization creates the config directory."""
        config_dir = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))

        cache = ScanCache()

        assert cache.cache_path.parent.exists()


class TestScanCacheLoadSave:
    """Tests for ScanCache load and save operations."""

    def test_save_and_load(self, temp_cache_path, sample_album):
        """Test saving and loading cache data."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)
        cache.save()

        # Create new cache instance and load
        cache2 = ScanCache(cache_path=temp_cache_path)
        result = cache2.load()

        assert result is True
        assert cache2.folder_count == 1

    def test_load_nonexistent_file(self, temp_cache_path):
        """Test loading when cache file doesn't exist."""
        cache = ScanCache(cache_path=temp_cache_path)
        result = cache.load()

        assert result is False
        assert cache.folder_count == 0

    def test_load_invalid_json(self, temp_cache_path):
        """Test loading invalid JSON file."""
        temp_cache_path.write_text("not valid json {{{")

        cache = ScanCache(cache_path=temp_cache_path)
        result = cache.load()

        assert result is False
        assert cache.folder_count == 0

    def test_load_version_mismatch(self, temp_cache_path):
        """Test loading cache with different version clears data."""
        cache_data = {"version": 999, "folders": {"test": {"mtime": 0, "album_data": {}}}}
        temp_cache_path.write_text(json.dumps(cache_data))

        cache = ScanCache(cache_path=temp_cache_path)
        result = cache.load()

        assert result is False
        assert cache.folder_count == 0

    def test_save_creates_file(self, temp_cache_path, sample_album):
        """Test that save creates the cache file."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)

        assert not temp_cache_path.exists()
        cache.save()
        assert temp_cache_path.exists()

    def test_save_atomic_write(self, temp_cache_path, sample_album):
        """Test that save uses atomic write (no temp files left behind)."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)
        cache.save()

        # Check no temp files left
        temp_files = list(temp_cache_path.parent.glob(".scan_cache_*.tmp"))
        assert len(temp_files) == 0


class TestScanCacheFolderOperations:
    """Tests for ScanCache folder operations."""

    def test_update_folder(self, temp_cache_path, sample_album):
        """Test updating a folder in the cache."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)

        assert cache.folder_count == 1
        assert cache.is_dirty is True

    def test_get_cached_album(self, temp_cache_path, sample_album):
        """Test getting cached album info."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)

        cached = cache.get_cached_album(sample_album.path)

        assert cached is not None
        assert cached.artist == sample_album.artist
        assert cached.album == sample_album.album

    def test_get_cached_album_not_found(self, temp_cache_path, tmp_path):
        """Test getting album that's not in cache returns None."""
        cache = ScanCache(cache_path=temp_cache_path)
        nonexistent_path = tmp_path / "nonexistent"

        cached = cache.get_cached_album(nonexistent_path)

        assert cached is None

    def test_is_folder_changed_not_in_cache(self, temp_cache_path, tmp_path):
        """Test folder not in cache is considered changed."""
        cache = ScanCache(cache_path=temp_cache_path)
        folder = tmp_path / "test_folder"
        folder.mkdir()

        assert cache.is_folder_changed(folder) is True

    def test_is_folder_changed_mtime_same(self, temp_cache_path, sample_album):
        """Test folder with same mtime is not considered changed."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)

        assert cache.is_folder_changed(sample_album.path) is False

    def test_is_folder_changed_mtime_different(self, temp_cache_path, sample_album):
        """Test folder with different mtime is considered changed."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)

        # Modify the folder's mtime
        os.utime(sample_album.path, (0, 0))

        assert cache.is_folder_changed(sample_album.path) is True

    def test_is_folder_changed_folder_doesnt_exist(self, temp_cache_path, tmp_path):
        """Test nonexistent folder is considered changed."""
        cache = ScanCache(cache_path=temp_cache_path)
        nonexistent = tmp_path / "doesnt_exist"

        assert cache.is_folder_changed(nonexistent) is True

    def test_remove_folder(self, temp_cache_path, sample_album):
        """Test removing a folder from cache."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)

        result = cache.remove_folder(sample_album.path)

        assert result is True
        assert cache.folder_count == 0

    def test_remove_folder_not_found(self, temp_cache_path, tmp_path):
        """Test removing nonexistent folder returns False."""
        cache = ScanCache(cache_path=temp_cache_path)
        nonexistent = tmp_path / "nonexistent"

        result = cache.remove_folder(nonexistent)

        assert result is False


class TestScanCacheClear:
    """Tests for ScanCache clear operation."""

    def test_clear(self, temp_cache_path, sample_album):
        """Test clearing all cache data."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)
        cache._dirty = False  # Reset dirty flag

        cache.clear()

        assert cache.folder_count == 0
        assert cache.is_dirty is True


class TestScanCachePrune:
    """Tests for ScanCache prune operation."""

    def test_prune_missing_folders(self, temp_cache_path, sample_album, tmp_path):
        """Test pruning removes entries for deleted folders."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)

        # Create and add another folder
        existing_folder = tmp_path / "existing"
        existing_folder.mkdir()
        existing_album = AlbumInfo(
            path=existing_folder,
            artist="Existing",
            album="Album",
            year="2024",
            track_count=5,
            cover=CoverInfo(),
            sample_file=existing_folder / "track.mp3",
            formats=[".mp3"],
        )
        cache.update_folder(existing_folder, existing_album)

        # Delete the first folder
        sample_album.path.rmdir()

        # Prune
        removed = cache.prune_missing_folders()

        assert removed == 1
        assert cache.folder_count == 1
        assert cache.is_dirty is True

    def test_prune_no_missing_folders(self, temp_cache_path, sample_album):
        """Test pruning when no folders are missing."""
        cache = ScanCache(cache_path=temp_cache_path)
        cache.update_folder(sample_album.path, sample_album)
        cache._dirty = False

        removed = cache.prune_missing_folders()

        assert removed == 0
        assert cache.is_dirty is False


class TestScanCacheProperties:
    """Tests for ScanCache properties."""

    def test_folder_count(self, temp_cache_path, sample_album, tmp_path):
        """Test folder_count property."""
        cache = ScanCache(cache_path=temp_cache_path)

        assert cache.folder_count == 0

        cache.update_folder(sample_album.path, sample_album)
        assert cache.folder_count == 1

        folder2 = tmp_path / "folder2"
        folder2.mkdir()
        album2 = AlbumInfo(
            path=folder2,
            artist="Artist2",
            album="Album2",
            year="2024",
            track_count=5,
            cover=CoverInfo(),
            sample_file=folder2 / "track.mp3",
            formats=[".mp3"],
        )
        cache.update_folder(folder2, album2)
        assert cache.folder_count == 2

    def test_is_dirty(self, temp_cache_path, sample_album):
        """Test is_dirty property."""
        cache = ScanCache(cache_path=temp_cache_path)

        assert cache.is_dirty is False

        cache.update_folder(sample_album.path, sample_album)
        assert cache.is_dirty is True

        cache.save()
        assert cache.is_dirty is False

    def test_get_cached_folders(self, temp_cache_path, sample_album, tmp_path):
        """Test get_cached_folders method."""
        cache = ScanCache(cache_path=temp_cache_path)

        assert cache.get_cached_folders() == set()

        cache.update_folder(sample_album.path, sample_album)

        folders = cache.get_cached_folders()
        assert len(folders) == 1
        assert str(sample_album.path.resolve()) in folders


class TestScanCacheIntegration:
    """Integration tests for ScanCache with real file operations."""

    def test_full_workflow(self, tmp_path):
        """Test complete workflow: create, save, load, modify, save."""
        cache_path = tmp_path / "cache.json"

        # Create album folder
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)

        # Create sample file
        sample_file = album_folder / "track.mp3"
        sample_file.write_bytes(b"dummy audio data")

        album = AlbumInfo(
            path=album_folder,
            artist="Test Artist",
            album="Test Album",
            year="2024",
            track_count=1,
            cover=CoverInfo(has_embedded=True),
            sample_file=sample_file,
            formats=[".mp3"],
        )

        # Create cache and add album
        cache1 = ScanCache(cache_path=cache_path)
        cache1.update_folder(album_folder, album)
        cache1.save()

        # Load in new instance
        cache2 = ScanCache(cache_path=cache_path)
        assert cache2.load() is True

        # Check folder is not changed
        assert cache2.is_folder_changed(album_folder) is False

        # Modify folder (with sleep to ensure mtime changes on all platforms)
        time.sleep(0.1)
        new_file = album_folder / "track2.mp3"
        new_file.write_bytes(b"more audio data")

        # Check folder is now changed
        assert cache2.is_folder_changed(album_folder) is True

    def test_cache_survives_restart(self, tmp_path):
        """Test that cache data survives application restart simulation."""
        cache_path = tmp_path / "cache.json"
        album_folder = tmp_path / "Music" / "Album"
        album_folder.mkdir(parents=True)

        album = AlbumInfo(
            path=album_folder,
            artist="Artist",
            album="Album",
            year="2023",
            track_count=5,
            cover=CoverInfo(),
            sample_file=album_folder / "track.mp3",
            formats=[".mp3"],
        )

        # First "session"
        cache1 = ScanCache(cache_path=cache_path)
        cache1.update_folder(album_folder, album)
        cache1.save()

        # Second "session" (new process)
        cache2 = ScanCache(cache_path=cache_path)
        cache2.load()

        cached_album = cache2.get_cached_album(album_folder)
        assert cached_album is not None
        assert cached_album.artist == "Artist"
        assert cached_album.album == "Album"
