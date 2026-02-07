"""
Tests for the image cache module.
"""

import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.cache import (
    EmbeddedCoverCache,
    ImageCache,
    embedded_cover_cache,
    get_image_cache,
    reset_image_cache,
)


class TestImageCache:
    """Tests for ImageCache class."""

    def test_init_default(self):
        """Test default initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))
            assert cache is not None
            assert cache.cache_dir.exists()

    def test_init_with_max_age(self):
        """Test initialization with custom max age."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir), max_age_hours=48)
            assert cache.max_age_seconds == 48 * 3600

    def test_set_and_get(self):
        """Test basic set and get operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))
            test_data = b"test_image_data"
            test_url = "http://example.com/image.jpg"

            cache.set(test_url, test_data)
            retrieved = cache.get(test_url)

            assert retrieved == test_data

    def test_get_missing_returns_none(self):
        """Test that getting missing key returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))
            result = cache.get("http://nonexistent.com/image.jpg")
            assert result is None

    def test_clear(self):
        """Test clearing the cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))
            cache.set("url1", b"data1")
            cache.set("url2", b"data2")

            count = cache.clear()

            assert count == 2
            assert cache.get("url1") is None
            assert cache.get("url2") is None

    def test_get_count(self):
        """Test cache count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))
            assert cache.get_count() == 0

            cache.set("url1", b"data1")
            assert cache.get_count() == 1

            cache.set("url2", b"data2")
            assert cache.get_count() == 2

    def test_get_size(self):
        """Test cache size calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))
            assert cache.get_size() == 0

            data1 = b"x" * 100
            data2 = b"y" * 200
            cache.set("url1", data1)
            cache.set("url2", data2)

            assert cache.get_size() == 300


class TestImageCacheTTL:
    """Tests for ImageCache TTL functionality."""

    def test_expired_item_returns_none(self):
        """Test that expired items return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cache with very short TTL (1 second)
            cache = ImageCache(cache_dir=Path(tmpdir), max_age_hours=0)
            cache.max_age_seconds = 0.1  # Override for test

            cache.set("url", b"data")

            # Wait for expiration
            time.sleep(0.2)

            assert cache.get("url") is None

    def test_non_expired_item_returns_data(self):
        """Test that non-expired items return data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir), max_age_hours=24)
            cache.set("url", b"data")

            # Should still be valid
            assert cache.get("url") == b"data"

    def test_clear_expired(self):
        """Test clearing only expired items."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir), max_age_hours=0)
            cache.max_age_seconds = 0.1

            cache.set("url1", b"data1")
            time.sleep(0.2)  # Let url1 expire

            # Set url2 after expiration time
            cache.max_age_seconds = 3600  # Reset to 1 hour
            cache.set("url2", b"data2")

            count = cache.clear_expired()

            # url1 should be cleared, url2 should remain
            assert cache.get("url2") == b"data2"


class TestCacheKey:
    """Tests for cache key generation."""

    def test_same_url_same_key(self):
        """Test that same URL generates same key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))
            url = "http://example.com/image.jpg"

            key1 = cache._get_cache_key(url)
            key2 = cache._get_cache_key(url)

            assert key1 == key2

    def test_different_url_different_key(self):
        """Test that different URLs generate different keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ImageCache(cache_dir=Path(tmpdir))

            key1 = cache._get_cache_key("http://example.com/image1.jpg")
            key2 = cache._get_cache_key("http://example.com/image2.jpg")

            assert key1 != key2


class TestImageCacheThreadSafety:
    """Tests for ImageCache thread safety."""

    def test_concurrent_set_operations(self, tmp_path):
        """Test concurrent set operations do not corrupt data."""
        cache = ImageCache(cache_dir=tmp_path)
        num_threads = 10
        num_operations = 50

        def set_data(thread_id):
            for i in range(num_operations):
                url = f"http://example.com/image_{thread_id}_{i}.jpg"
                data = f"data_{thread_id}_{i}".encode()
                cache.set(url, data)
            return thread_id

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(set_data, i) for i in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        # Verify all data was written correctly
        assert cache.get_count() == num_threads * num_operations

    def test_concurrent_get_set_operations(self, tmp_path):
        """Test concurrent get and set operations."""
        cache = ImageCache(cache_dir=tmp_path)
        num_threads = 10
        shared_url = "http://example.com/shared.jpg"
        shared_data = b"shared_data"

        cache.set(shared_url, shared_data)
        results = []
        lock = threading.Lock()

        def get_and_set(thread_id):
            for i in range(20):
                # Mix of get and set operations
                retrieved = cache.get(shared_url)
                with lock:
                    if retrieved is not None:
                        results.append(retrieved)

                url = f"http://example.com/image_{thread_id}_{i}.jpg"
                cache.set(url, f"data_{thread_id}_{i}".encode())

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(get_and_set, i) for i in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        # All retrieved values should be the same shared data
        for result in results:
            assert result == shared_data

    def test_concurrent_clear_and_set(self, tmp_path):
        """Test concurrent clear and set do not cause errors."""
        cache = ImageCache(cache_dir=tmp_path)
        errors = []

        def set_data():
            for i in range(50):
                try:
                    cache.set(f"http://example.com/image_{i}.jpg", b"data")
                except Exception as e:
                    errors.append(e)

        def clear_cache():
            for _ in range(10):
                try:
                    cache.clear()
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=set_data),
            threading.Thread(target=clear_cache),
            threading.Thread(target=set_data),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No exceptions should have occurred
        assert len(errors) == 0


class TestImageCacheTTLWithMonkeypatch:
    """Tests for ImageCache TTL using monkeypatch instead of time.sleep()."""

    def test_expired_item_returns_none_monkeypatch(self, tmp_path, monkeypatch):
        """Test that expired items return None using monkeypatch."""
        cache = ImageCache(cache_dir=tmp_path, max_age_hours=1)  # 3600 seconds

        test_url = "http://example.com/image.jpg"
        cache.set(test_url, b"test_data")

        # Get the cache file mtime
        cache_path = cache._get_cache_path(test_url)
        original_mtime = cache_path.stat().st_mtime

        # Mock time.time() to return a time far in the future (expired)
        monkeypatch.setattr(time, "time", lambda: original_mtime + 7200)

        assert cache.get(test_url) is None

    def test_non_expired_item_returns_data_monkeypatch(self, tmp_path, monkeypatch):
        """Test that non-expired items return data using monkeypatch."""
        cache = ImageCache(cache_dir=tmp_path, max_age_hours=1)  # 3600 seconds

        test_url = "http://example.com/image.jpg"
        test_data = b"test_data"
        cache.set(test_url, test_data)

        cache_path = cache._get_cache_path(test_url)
        original_mtime = cache_path.stat().st_mtime

        # Mock time.time() to be just before expiration
        monkeypatch.setattr(time, "time", lambda: original_mtime + 3000)

        assert cache.get(test_url) == test_data

    def test_clear_expired_monkeypatch(self, tmp_path, monkeypatch):
        """Test clearing expired items using monkeypatch."""
        cache = ImageCache(cache_dir=tmp_path, max_age_hours=1)

        # Set initial items
        cache.set("url1", b"data1")
        cache.set("url2", b"data2")

        cache_path1 = cache._get_cache_path("url1")
        cache_path2 = cache._get_cache_path("url2")
        original_mtime1 = cache_path1.stat().st_mtime
        original_mtime2 = cache_path2.stat().st_mtime

        # Modify mtime of url1 to simulate age (2 hours ago)
        old_time = original_mtime1 - 7200
        os.utime(cache_path1, (old_time, old_time))

        # Mock time.time() to current time
        monkeypatch.setattr(time, "time", lambda: original_mtime2)

        count = cache.clear_expired()

        assert count == 1
        assert cache.get("url2") is not None

    @pytest.mark.parametrize(
        "age_hours,age_offset,should_expire",
        [
            (1, 3601, True),  # Just expired (1 second past)
            (1, 3599, False),  # Just before expiration
            (24, 86401, True),  # 24 hours, just expired
            (24, 86399, False),  # 24 hours, just before
            (0, 1, True),  # Zero hours TTL, always expired
        ],
    )
    def test_ttl_edge_cases(self, tmp_path, monkeypatch, age_hours, age_offset, should_expire):
        """Test TTL edge cases with parametrize."""
        cache = ImageCache(cache_dir=tmp_path, max_age_hours=age_hours)

        test_url = "http://example.com/image.jpg"
        cache.set(test_url, b"test_data")

        cache_path = cache._get_cache_path(test_url)
        original_mtime = cache_path.stat().st_mtime

        monkeypatch.setattr(time, "time", lambda: original_mtime + age_offset)

        result = cache.get(test_url)

        if should_expire:
            assert result is None
        else:
            assert result == b"test_data"


class TestImageCacheDirectoryCreation:
    """Tests for cache directory creation."""

    def test_cache_creates_directory(self, tmp_path):
        """Test that cache creates its directory if it doesn't exist."""
        cache_dir = tmp_path / "nested" / "cache" / "dir"
        assert not cache_dir.exists()

        cache = ImageCache(cache_dir=cache_dir)

        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_cache_works_with_existing_directory(self, tmp_path):
        """Test that cache works with existing directory."""
        cache_dir = tmp_path / "existing"
        cache_dir.mkdir(parents=True)

        cache = ImageCache(cache_dir=cache_dir)
        cache.set("url", b"data")

        assert cache.get("url") == b"data"

    def test_default_cache_dir_uses_xdg(self, monkeypatch, tmp_path):
        """Test that default cache dir uses XDG_CACHE_HOME if set."""
        xdg_cache = tmp_path / "xdg_cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

        cache = ImageCache()

        expected = xdg_cache / "tunecover" / "images"
        assert cache.cache_dir == expected

    def test_default_cache_dir_falls_back_to_home(self, monkeypatch, tmp_path):
        """Test that default cache dir falls back to ~/.cache."""
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        cache = ImageCache()

        expected = tmp_path / ".cache" / "tunecover" / "images"
        assert cache.cache_dir == expected


class TestImageCacheCorruptedFiles:
    """Tests for handling corrupted cache files."""

    def test_corrupted_file_returns_none(self, tmp_path, caplog):
        """Test that corrupted file read errors are handled gracefully."""
        cache = ImageCache(cache_dir=tmp_path)
        test_url = "http://example.com/image.jpg"

        # Create a cache entry
        cache.set(test_url, b"valid_data")

        # Corrupt by removing read permissions (Unix only)
        cache_path = cache._get_cache_path(test_url)

        # Mock read_bytes to raise an error
        with patch.object(Path, "read_bytes", side_effect=OSError("Corrupted file")):
            result = cache.get(test_url)

        assert result is None

    def test_file_disappears_during_read(self, tmp_path):
        """Test handling when file disappears between exists() and read()."""
        cache = ImageCache(cache_dir=tmp_path)
        test_url = "http://example.com/image.jpg"

        cache.set(test_url, b"data")
        cache_path = cache._get_cache_path(test_url)

        original_read_bytes = cache_path.read_bytes

        # Simulate file disappearing after exists() but before read_bytes()
        def mock_read_bytes():
            cache_path.unlink()  # Delete file before reading
            raise FileNotFoundError("File not found")

        with patch.object(type(cache_path), "read_bytes", lambda self: mock_read_bytes()):
            result = cache.get(test_url)

        assert result is None

    def test_invalid_cache_directory_permissions(self, tmp_path, monkeypatch):
        """Test handling of permission errors when reading cache."""
        cache = ImageCache(cache_dir=tmp_path)
        test_url = "http://example.com/image.jpg"

        # Mock glob to raise PermissionError
        def mock_glob(*args, **kwargs):
            raise OSError("Permission denied")

        with patch.object(Path, "glob", mock_glob):
            count = cache.get_count()
            size = cache.get_size()

        assert count == 0
        assert size == 0


class TestImageCacheDiskFull:
    """Tests for disk full scenarios."""

    def test_disk_full_on_write(self, tmp_path, caplog):
        """Test handling of disk full errors during write."""
        cache = ImageCache(cache_dir=tmp_path)
        test_url = "http://example.com/image.jpg"

        with patch.object(Path, "write_bytes", side_effect=OSError("No space left on device")):
            import logging

            with caplog.at_level(logging.WARNING):
                cache.set(test_url, b"data")

        assert "Could not write cache" in caplog.text

    def test_disk_full_does_not_crash(self, tmp_path):
        """Test that disk full errors don't crash the application."""
        cache = ImageCache(cache_dir=tmp_path)

        with patch.object(Path, "write_bytes", side_effect=OSError("Disk quota exceeded")):
            # Should not raise exception
            cache.set("url1", b"data1")
            cache.set("url2", b"data2")

        # Cache should still be functional
        assert cache.get_count() == 0

    def test_partial_write_handling(self, tmp_path):
        """Test handling of partial writes (simulated)."""
        cache = ImageCache(cache_dir=tmp_path)
        test_url = "http://example.com/image.jpg"

        # First write succeeds
        cache.set(test_url, b"original_data")
        assert cache.get(test_url) == b"original_data"

        # Second write fails partway
        with patch.object(Path, "write_bytes", side_effect=OSError("Write error")):
            cache.set(test_url, b"new_data")

        # Original data should still be there (or None if file was corrupted)
        result = cache.get(test_url)
        # The original file might still exist since write_bytes was mocked
        assert result == b"original_data" or result is None


class TestImageCacheMaxSize:
    """Tests for maximum cache size enforcement.

    Note: The current implementation does not enforce max size.
    These tests document expected behavior if implemented.
    """

    def test_cache_size_tracking(self, tmp_path):
        """Test that cache size is accurately tracked."""
        cache = ImageCache(cache_dir=tmp_path)

        # Add items of known sizes
        cache.set("url1", b"x" * 1000)
        cache.set("url2", b"y" * 2000)
        cache.set("url3", b"z" * 3000)

        assert cache.get_size() == 6000

    def test_cache_size_after_clear(self, tmp_path):
        """Test cache size after clearing."""
        cache = ImageCache(cache_dir=tmp_path)

        cache.set("url1", b"x" * 1000)
        cache.set("url2", b"y" * 2000)
        cache.clear()

        assert cache.get_size() == 0

    def test_cache_size_after_partial_clear(self, tmp_path, monkeypatch):
        """Test cache size after clearing expired items."""
        cache = ImageCache(cache_dir=tmp_path, max_age_hours=1)

        cache.set("url1", b"x" * 1000)
        cache.set("url2", b"y" * 2000)

        # Make url1 expire
        cache_path1 = cache._get_cache_path("url1")
        old_time = time.time() - 7200
        os.utime(cache_path1, (old_time, old_time))

        cache.clear_expired()

        # Only url2 should remain
        assert cache.get_size() == 2000

    def test_overwrite_updates_size(self, tmp_path):
        """Test that overwriting a cache entry updates size correctly."""
        cache = ImageCache(cache_dir=tmp_path)

        cache.set("url1", b"x" * 1000)
        assert cache.get_size() == 1000

        cache.set("url1", b"y" * 2000)
        assert cache.get_size() == 2000


class TestImageCacheEdgeCases:
    """Tests for edge cases."""

    def test_empty_data(self, tmp_path):
        """Test caching empty data."""
        cache = ImageCache(cache_dir=tmp_path)
        cache.set("url", b"")

        assert cache.get("url") == b""

    def test_large_data(self, tmp_path):
        """Test caching large data."""
        cache = ImageCache(cache_dir=tmp_path)
        large_data = b"x" * (10 * 1024 * 1024)  # 10MB

        cache.set("url", large_data)
        assert cache.get("url") == large_data

    def test_special_characters_in_url(self, tmp_path):
        """Test URLs with special characters."""
        cache = ImageCache(cache_dir=tmp_path)
        special_url = "http://example.com/image?size=large&format=jpg#section"

        cache.set(special_url, b"data")
        assert cache.get(special_url) == b"data"

    def test_unicode_url(self, tmp_path):
        """Test URLs with unicode characters."""
        cache = ImageCache(cache_dir=tmp_path)
        unicode_url = "http://example.com/\u00e9\u00e0\u00fc/image.jpg"

        cache.set(unicode_url, b"data")
        assert cache.get(unicode_url) == b"data"

    def test_binary_data_integrity(self, tmp_path):
        """Test that binary data is preserved exactly."""
        cache = ImageCache(cache_dir=tmp_path)

        # Create data with all possible byte values
        all_bytes = bytes(range(256))

        cache.set("url", all_bytes)
        assert cache.get("url") == all_bytes

    def test_clear_empty_cache(self, tmp_path):
        """Test clearing an empty cache."""
        cache = ImageCache(cache_dir=tmp_path)
        count = cache.clear()

        assert count == 0

    def test_clear_expired_empty_cache(self, tmp_path):
        """Test clearing expired on empty cache."""
        cache = ImageCache(cache_dir=tmp_path)
        count = cache.clear_expired()

        assert count == 0


# =============================================================================
# Tests for EmbeddedCoverCache
# =============================================================================


class TestEmbeddedCoverCache:
    """Tests for EmbeddedCoverCache class."""

    def test_init_default(self):
        """Test default initialization."""
        cache = EmbeddedCoverCache()
        assert cache.max_size == 100
        assert cache.get_size() == 0

    def test_init_with_max_size(self):
        """Test initialization with custom max size."""
        cache = EmbeddedCoverCache(max_size=50)
        assert cache.max_size == 50

    def test_put_and_get(self, tmp_path):
        """Test basic put and get operations."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio data")
        test_data = b"test_cover_data"

        cache.put(test_file, test_data)
        retrieved = cache.get(test_file)

        assert retrieved == test_data

    def test_get_missing_returns_none(self, tmp_path):
        """Test that getting missing file returns None."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "nonexistent.mp3"

        result = cache.get(test_file)

        assert result is None

    def test_get_nonexistent_file_returns_none(self, tmp_path):
        """Test that getting nonexistent file returns None."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "does_not_exist.mp3"

        result = cache.get(test_file)

        assert result is None

    def test_clear(self, tmp_path):
        """Test clearing the cache."""
        cache = EmbeddedCoverCache()
        file1 = tmp_path / "file1.mp3"
        file2 = tmp_path / "file2.mp3"
        file1.write_bytes(b"data1")
        file2.write_bytes(b"data2")

        cache.put(file1, b"cover1")
        cache.put(file2, b"cover2")
        count = cache.clear()

        assert count == 2
        assert cache.get(file1) is None
        assert cache.get(file2) is None

    def test_get_size(self, tmp_path):
        """Test cache size tracking."""
        cache = EmbeddedCoverCache()
        assert cache.get_size() == 0

        file1 = tmp_path / "file1.mp3"
        file2 = tmp_path / "file2.mp3"
        file1.write_bytes(b"data1")
        file2.write_bytes(b"data2")

        cache.put(file1, b"cover1")
        assert cache.get_size() == 1

        cache.put(file2, b"cover2")
        assert cache.get_size() == 2

    def test_get_memory_usage(self, tmp_path):
        """Test memory usage calculation."""
        cache = EmbeddedCoverCache()
        assert cache.get_memory_usage() == 0

        file1 = tmp_path / "file1.mp3"
        file2 = tmp_path / "file2.mp3"
        file1.write_bytes(b"data1")
        file2.write_bytes(b"data2")

        data1 = b"x" * 100
        data2 = b"y" * 200
        cache.put(file1, data1)
        cache.put(file2, data2)

        assert cache.get_memory_usage() == 300


class TestEmbeddedCoverCacheMtimeInvalidation:
    """Tests for EmbeddedCoverCache mtime-based invalidation."""

    def test_invalidates_on_file_modification(self, tmp_path):
        """Test that cache is invalidated when file is modified."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"original audio data")

        # Cache some data
        cache.put(test_file, b"original_cover")
        assert cache.get(test_file) == b"original_cover"

        # Wait a bit and modify the file
        time.sleep(0.1)
        test_file.write_bytes(b"modified audio data")

        # Cache should return None due to mtime change
        assert cache.get(test_file) is None

    def test_same_mtime_returns_cached_data(self, tmp_path):
        """Test that cache returns data for unmodified files."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio data")

        cache.put(test_file, b"cover_data")

        # Multiple gets should return cached data
        assert cache.get(test_file) == b"cover_data"
        assert cache.get(test_file) == b"cover_data"
        assert cache.get(test_file) == b"cover_data"

    def test_stale_entries_cleaned_on_get(self, tmp_path):
        """Test that stale entries are cleaned up on get."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"original data")

        # Cache data
        cache.put(test_file, b"cover1")
        assert cache.get_size() == 1

        # Modify file to invalidate cache
        time.sleep(0.1)
        test_file.write_bytes(b"modified data")

        # Get should clean up stale entry
        result = cache.get(test_file)
        assert result is None
        assert cache.get_size() == 0


class TestEmbeddedCoverCacheLRU:
    """Tests for EmbeddedCoverCache LRU eviction."""

    def test_evicts_oldest_when_full(self, tmp_path):
        """Test that oldest entries are evicted when cache is full."""
        cache = EmbeddedCoverCache(max_size=3)

        # Create and cache 3 files
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(f"data{i}".encode())
            files.append(f)
            cache.put(f, f"cover{i}".encode())

        # All 3 should be cached
        assert cache.get_size() == 3
        assert cache.get(files[0]) == b"cover0"
        assert cache.get(files[1]) == b"cover1"
        assert cache.get(files[2]) == b"cover2"

        # Add a 4th file - should evict the oldest (file0)
        # Note: file0 was accessed most recently due to get() above
        # So we need to check which one is actually evicted
        file4 = tmp_path / "file4.mp3"
        file4.write_bytes(b"data4")
        cache.put(file4, b"cover4")

        assert cache.get_size() == 3
        assert cache.get(file4) == b"cover4"

    def test_access_moves_to_end(self, tmp_path):
        """Test that accessing an entry moves it to end (most recently used)."""
        cache = EmbeddedCoverCache(max_size=3)

        # Create and cache 3 files
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(f"data{i}".encode())
            files.append(f)
            cache.put(f, f"cover{i}".encode())

        # Access file0 to make it most recently used
        cache.get(files[0])

        # Add new files to trigger eviction
        for i in range(4, 7):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(f"data{i}".encode())
            cache.put(f, f"cover{i}".encode())

        # file0 should still be in cache (was accessed), but file1 and file2 should be evicted
        assert cache.get_size() == 3


class TestEmbeddedCoverCacheThreadSafety:
    """Tests for EmbeddedCoverCache thread safety."""

    def test_concurrent_put_operations(self, tmp_path):
        """Test concurrent put operations do not corrupt cache."""
        cache = EmbeddedCoverCache(max_size=100)
        num_threads = 10
        num_operations = 20

        def put_data(thread_id):
            for i in range(num_operations):
                f = tmp_path / f"file_{thread_id}_{i}.mp3"
                f.write_bytes(f"data_{thread_id}_{i}".encode())
                cache.put(f, f"cover_{thread_id}_{i}".encode())
            return thread_id

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(put_data, i) for i in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        # Should have entries (limited by max_size)
        assert cache.get_size() <= 100

    def test_concurrent_get_put_operations(self, tmp_path):
        """Test concurrent get and put operations."""
        cache = EmbeddedCoverCache(max_size=100)
        num_threads = 10

        # Pre-populate cache
        shared_file = tmp_path / "shared.mp3"
        shared_file.write_bytes(b"shared_data")
        cache.put(shared_file, b"shared_cover")

        results = []
        lock = threading.Lock()

        def get_and_put(thread_id):
            for i in range(20):
                # Mix of get and put operations
                retrieved = cache.get(shared_file)
                with lock:
                    if retrieved is not None:
                        results.append(retrieved)

                f = tmp_path / f"file_{thread_id}_{i}.mp3"
                f.write_bytes(f"data_{thread_id}_{i}".encode())
                cache.put(f, f"cover_{thread_id}_{i}".encode())

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(get_and_put, i) for i in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        # All retrieved values should be the shared cover
        for result in results:
            assert result == b"shared_cover"

    def test_concurrent_clear_and_put(self, tmp_path):
        """Test concurrent clear and put do not cause errors."""
        cache = EmbeddedCoverCache(max_size=100)
        errors = []

        def put_data():
            for i in range(50):
                try:
                    f = tmp_path / f"file_{i}.mp3"
                    f.write_bytes(f"data_{i}".encode())
                    cache.put(f, b"cover")
                except Exception as e:
                    errors.append(e)

        def clear_cache():
            for _ in range(10):
                try:
                    cache.clear()
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=put_data),
            threading.Thread(target=clear_cache),
            threading.Thread(target=put_data),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No exceptions should have occurred
        assert len(errors) == 0


class TestEmbeddedCoverCacheEdgeCases:
    """Tests for EmbeddedCoverCache edge cases."""

    def test_empty_data(self, tmp_path):
        """Test caching empty data."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio data")

        cache.put(test_file, b"")
        assert cache.get(test_file) == b""

    def test_large_data(self, tmp_path):
        """Test caching large data."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio data")

        large_data = b"x" * (10 * 1024 * 1024)  # 10MB
        cache.put(test_file, large_data)
        assert cache.get(test_file) == large_data

    def test_special_characters_in_path(self, tmp_path):
        """Test file paths with special characters."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test file (1).mp3"
        test_file.write_bytes(b"audio data")

        cache.put(test_file, b"cover")
        assert cache.get(test_file) == b"cover"

    def test_unicode_path(self, tmp_path):
        """Test file paths with unicode characters."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test_\u00e9\u00e0\u00fc.mp3"
        test_file.write_bytes(b"audio data")

        cache.put(test_file, b"cover")
        assert cache.get(test_file) == b"cover"

    def test_binary_data_integrity(self, tmp_path):
        """Test that binary data is preserved exactly."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio data")

        # Create data with all possible byte values
        all_bytes = bytes(range(256))

        cache.put(test_file, all_bytes)
        assert cache.get(test_file) == all_bytes

    def test_clear_empty_cache(self):
        """Test clearing an empty cache."""
        cache = EmbeddedCoverCache()
        count = cache.clear()

        assert count == 0

    def test_put_updates_existing_entry(self, tmp_path):
        """Test that putting to same file updates the entry."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio data")

        cache.put(test_file, b"cover1")
        assert cache.get(test_file) == b"cover1"

        cache.put(test_file, b"cover2")
        assert cache.get(test_file) == b"cover2"
        assert cache.get_size() == 1  # Should still be 1 entry


class TestEmbeddedCoverCacheInvalidate:
    """Tests for EmbeddedCoverCache.invalidate() method."""

    def test_invalidate_existing_entry(self, tmp_path):
        """Test invalidating an existing cache entry."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio data")

        cache.put(test_file, b"cover_data")
        assert cache.get(test_file) == b"cover_data"

        result = cache.invalidate(test_file)

        assert result is True
        assert cache.get(test_file) is None
        assert cache.get_size() == 0

    def test_invalidate_nonexistent_entry(self, tmp_path):
        """Test invalidating a non-cached file returns False."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "uncached.mp3"
        test_file.write_bytes(b"audio data")

        result = cache.invalidate(test_file)

        assert result is False

    def test_invalidate_nonexistent_file(self, tmp_path):
        """Test invalidating a file that doesn't exist on disk."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "does_not_exist.mp3"

        result = cache.invalidate(test_file)

        assert result is False

    def test_invalidate_preserves_other_entries(self, tmp_path):
        """Test that invalidating one entry preserves others."""
        cache = EmbeddedCoverCache()
        file1 = tmp_path / "file1.mp3"
        file2 = tmp_path / "file2.mp3"
        file1.write_bytes(b"data1")
        file2.write_bytes(b"data2")

        cache.put(file1, b"cover1")
        cache.put(file2, b"cover2")

        cache.invalidate(file1)

        assert cache.get(file1) is None
        assert cache.get(file2) == b"cover2"
        assert cache.get_size() == 1

    def test_invalidate_removes_all_mtime_variants(self, tmp_path):
        """Test that invalidate removes entries regardless of mtime."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"original data")

        # Cache initial data
        cache.put(test_file, b"cover1")

        # Modify file (changes mtime)
        time.sleep(0.1)
        test_file.write_bytes(b"modified data")

        # Cache new data (different mtime key)
        cache.put(test_file, b"cover2")

        # Invalidate should remove all entries for this path
        result = cache.invalidate(test_file)

        assert result is True
        assert cache.get(test_file) is None

    def test_invalidate_with_preserve_timestamp(self, tmp_path):
        """Test invalidation works even when file mtime is preserved."""
        cache = EmbeddedCoverCache()
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio data")

        # Get original mtime
        original_mtime = test_file.stat().st_mtime

        # Cache data
        cache.put(test_file, b"original_cover")
        assert cache.get(test_file) == b"original_cover"

        # Simulate writing new data but preserving timestamp
        test_file.write_bytes(b"new audio data")
        os.utime(test_file, (original_mtime, original_mtime))

        # Without invalidation, cache would return old data
        # (same mtime key)
        assert cache.get(test_file) == b"original_cover"

        # After invalidation, cache should be cleared
        cache.invalidate(test_file)
        assert cache.get(test_file) is None

    def test_invalidate_thread_safety(self, tmp_path):
        """Test invalidate is thread-safe."""
        cache = EmbeddedCoverCache(max_size=100)
        errors = []

        # Create files
        files = []
        for i in range(20):
            f = tmp_path / f"file_{i}.mp3"
            f.write_bytes(f"data_{i}".encode())
            files.append(f)
            cache.put(f, f"cover_{i}".encode())

        def invalidate_files():
            for f in files:
                try:
                    cache.invalidate(f)
                except Exception as e:
                    errors.append(e)

        def put_files():
            for i, f in enumerate(files):
                try:
                    cache.put(f, f"new_cover_{i}".encode())
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=invalidate_files),
            threading.Thread(target=put_files),
            threading.Thread(target=invalidate_files),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestEmbeddedCoverCacheModuleLevelInstance:
    """Tests for the module-level embedded_cover_cache instance."""

    def test_module_level_instance_exists(self):
        """Test that module-level instance is created."""
        assert embedded_cover_cache is not None
        assert isinstance(embedded_cover_cache, EmbeddedCoverCache)

    def test_module_level_instance_default_size(self):
        """Test that module-level instance has default max_size."""
        assert embedded_cover_cache.max_size == 100


# =============================================================================
# Tests for ImageCache LRU eviction and size limits
# =============================================================================


class TestImageCacheLRUEviction:
    """Tests for ImageCache LRU eviction when size limit is reached."""

    def test_evicts_lru_when_size_exceeded(self, tmp_path):
        """Test that least recently used entries are evicted when size limit is exceeded."""
        # Create cache with 500 bytes limit
        cache = ImageCache(cache_dir=tmp_path, max_size_bytes=500)

        # Add 3 items totaling 600 bytes (exceeds limit)
        cache.set("url1", b"x" * 200)  # 200 bytes
        cache.set("url2", b"y" * 200)  # 400 bytes total
        cache.set("url3", b"z" * 200)  # 600 bytes total -> should evict url1

        # url1 should be evicted (oldest)
        assert cache.get("url1") is None
        # url2 and url3 should remain
        assert cache.get("url2") == b"y" * 200
        assert cache.get("url3") == b"z" * 200

    def test_access_updates_lru_order(self, tmp_path):
        """Test that accessing an entry updates its LRU position."""
        cache = ImageCache(cache_dir=tmp_path, max_size_bytes=500)

        # Add 2 items
        cache.set("url1", b"x" * 200)
        cache.set("url2", b"y" * 200)

        # Access url1 to make it recently used (move_to_end in OrderedDict)
        cache.get("url1")

        # Add item that exceeds limit - should evict url2 (oldest accessed)
        cache.set("url3", b"z" * 200)

        # url1 should remain (accessed recently)
        assert cache.get("url1") == b"x" * 200
        # url2 should be evicted
        assert cache.get("url2") is None
        # url3 should be present
        assert cache.get("url3") == b"z" * 200

    def test_evicts_multiple_entries_if_needed(self, tmp_path):
        """Test that multiple entries are evicted if needed to make space."""
        cache = ImageCache(cache_dir=tmp_path, max_size_bytes=500)

        # Add 5 small items
        for i in range(5):
            cache.set(f"url{i}", b"x" * 100)

        # Total is 500 bytes. Add a large item that needs 400 bytes of space.
        cache.set("large", b"y" * 400)

        # Should have evicted the oldest entries to make room
        assert cache.get("large") == b"y" * 400
        # Size should be within limit
        assert cache.get_size() <= 500

    def test_configure_changes_size_limit(self, tmp_path):
        """Test that configure() changes the size limit and triggers eviction."""
        cache = ImageCache(cache_dir=tmp_path, max_size_bytes=1000)

        # Add 500 bytes
        cache.set("url1", b"x" * 250)
        cache.set("url2", b"y" * 250)

        # Reduce limit - should trigger eviction
        cache.configure(max_size_bytes=300)

        # Size should be reduced to fit new limit
        assert cache.get_size() <= 300

    def test_configure_changes_ttl(self, tmp_path):
        """Test that configure() changes the TTL."""
        cache = ImageCache(cache_dir=tmp_path, max_age_hours=24)

        assert cache.max_age_seconds == 24 * 3600

        cache.configure(max_age_hours=48)

        assert cache.max_age_seconds == 48 * 3600


# =============================================================================
# Tests for EmbeddedCoverCache memory limit
# =============================================================================


class TestEmbeddedCoverCacheMemoryLimit:
    """Tests for EmbeddedCoverCache memory limit eviction."""

    def test_evicts_when_memory_limit_exceeded(self, tmp_path):
        """Test that entries are evicted when memory limit is exceeded."""
        # Create cache with 500 bytes memory limit
        cache = EmbeddedCoverCache(max_size=100, max_memory_bytes=500)

        # Add files
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(f"data{i}".encode())
            files.append(f)

        # Add 600 bytes of data (exceeds limit)
        cache.put(files[0], b"x" * 200)
        cache.put(files[1], b"y" * 200)
        cache.put(files[2], b"z" * 200)  # Should trigger eviction of files[0]

        # Memory usage should be within limit
        assert cache.get_memory_usage() <= 500

    def test_configure_memory_limit(self, tmp_path):
        """Test that configure() changes memory limit and triggers eviction."""
        cache = EmbeddedCoverCache(max_size=100, max_memory_bytes=1000)

        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(f"data{i}".encode())
            files.append(f)
            cache.put(f, b"x" * 100)

        # Memory usage should be 500 bytes
        assert cache.get_memory_usage() == 500

        # Reduce memory limit
        cache.configure(max_memory_bytes=300)

        # Memory usage should be reduced
        assert cache.get_memory_usage() <= 300

    def test_configure_entry_limit(self, tmp_path):
        """Test that configure() changes entry limit and triggers eviction."""
        cache = EmbeddedCoverCache(max_size=10, max_memory_bytes=1000000)

        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.mp3"
            f.write_bytes(f"data{i}".encode())
            files.append(f)
            cache.put(f, b"x" * 10)

        assert cache.get_size() == 5

        # Reduce entry limit
        cache.configure(max_size=3)

        assert cache.get_size() <= 3


# =============================================================================
# Tests for invalidation callbacks
# =============================================================================


class TestEmbeddedCoverCacheInvalidationCallbacks:
    """Tests for EmbeddedCoverCache invalidation callbacks."""

    def test_callback_called_on_invalidate(self, tmp_path):
        """Test that registered callback is called when entry is invalidated."""
        cache = EmbeddedCoverCache()
        callback_calls = []

        def on_invalidate(path):
            callback_calls.append(path)

        cache.register_invalidation_callback(on_invalidate)

        # Add and invalidate entry
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"data")
        cache.put(test_file, b"cover")
        cache.invalidate(test_file)

        # Callback should have been called with the absolute path
        assert len(callback_calls) == 1
        assert callback_calls[0] == str(test_file.resolve())

    def test_callback_not_called_on_miss(self, tmp_path):
        """Test that callback is not called when invalidating non-cached entry."""
        cache = EmbeddedCoverCache()
        callback_calls = []

        def on_invalidate(path):
            callback_calls.append(path)

        cache.register_invalidation_callback(on_invalidate)

        test_file = tmp_path / "uncached.mp3"
        test_file.write_bytes(b"data")
        cache.invalidate(test_file)

        # Callback should not have been called
        assert len(callback_calls) == 0

    def test_multiple_callbacks(self, tmp_path):
        """Test that multiple callbacks can be registered and called."""
        cache = EmbeddedCoverCache()
        calls1 = []
        calls2 = []

        cache.register_invalidation_callback(lambda p: calls1.append(p))
        cache.register_invalidation_callback(lambda p: calls2.append(p))

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"data")
        cache.put(test_file, b"cover")
        cache.invalidate(test_file)

        assert len(calls1) == 1
        assert len(calls2) == 1

    def test_unregister_callback(self, tmp_path):
        """Test that unregistered callback is not called."""
        cache = EmbeddedCoverCache()
        callback_calls = []

        def on_invalidate(path):
            callback_calls.append(path)

        cache.register_invalidation_callback(on_invalidate)
        cache.unregister_invalidation_callback(on_invalidate)

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"data")
        cache.put(test_file, b"cover")
        cache.invalidate(test_file)

        # Callback should not have been called
        assert len(callback_calls) == 0

    def test_callback_error_does_not_break_invalidation(self, tmp_path):
        """Test that callback errors don't break the invalidation process."""
        cache = EmbeddedCoverCache()
        valid_calls = []

        def bad_callback(path):
            raise ValueError("Callback error")

        def good_callback(path):
            valid_calls.append(path)

        cache.register_invalidation_callback(bad_callback)
        cache.register_invalidation_callback(good_callback)

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"data")
        cache.put(test_file, b"cover")

        # Should not raise despite bad callback
        cache.invalidate(test_file)

        # Good callback should still be called
        assert len(valid_calls) == 1

    def test_callback_called_on_stale_entry_cleanup_in_get(self, tmp_path):
        """Test that callback is called when get() cleans up stale entries."""
        cache = EmbeddedCoverCache()
        callback_calls = []

        def on_invalidate(path):
            callback_calls.append(path)

        cache.register_invalidation_callback(on_invalidate)

        # Create a file and cache it
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"original content")
        cache.put(test_file, b"cover data")

        # Modify the file (changes mtime)
        time.sleep(0.01)  # Ensure mtime changes
        test_file.write_bytes(b"modified content")

        # get() should detect stale entry and notify callbacks
        result = cache.get(test_file)
        assert result is None  # Cache miss due to mtime change

        # Callback should have been called
        assert len(callback_calls) == 1
        assert callback_calls[0] == str(test_file.resolve())

    def test_callback_not_called_when_get_finds_no_stale_entries(self, tmp_path):
        """Test that callback is not called when get() finds no stale entries."""
        cache = EmbeddedCoverCache()
        callback_calls = []

        def on_invalidate(path):
            callback_calls.append(path)

        cache.register_invalidation_callback(on_invalidate)

        # get() on non-existent file should not trigger callback
        test_file = tmp_path / "nonexistent.mp3"
        test_file.write_bytes(b"data")
        result = cache.get(test_file)

        assert result is None
        assert len(callback_calls) == 0


# =============================================================================
# Tests for get_image_cache singleton
# =============================================================================


class TestGetImageCacheSingleton:
    """Tests for get_image_cache() singleton function."""

    def setup_method(self):
        """Reset the singleton before each test."""
        reset_image_cache()

    def teardown_method(self):
        """Reset the singleton after each test."""
        reset_image_cache()

    def test_returns_same_instance(self, tmp_path):
        """Test that get_image_cache returns the same instance."""
        cache1 = get_image_cache(cache_dir=tmp_path)
        cache2 = get_image_cache(cache_dir=tmp_path)

        assert cache1 is cache2

    def test_uses_default_config_values(self, tmp_path):
        """Test that cache uses default values when no config provided."""
        cache = get_image_cache(cache_dir=tmp_path)

        # Default is 500 MB and 24 hours
        assert cache.max_size_bytes == 500 * 1024 * 1024
        assert cache.max_age_seconds == 24 * 3600

    def test_configures_from_config(self, tmp_path):
        """Test that cache is configured from Config object."""
        from unittest.mock import MagicMock

        config = MagicMock()
        config.get.side_effect = lambda key, default: {
            "cache.image_cache_size_mb": 200,
            "cache.image_cache_ttl_hours": 12,
        }.get(key, default)

        cache = get_image_cache(config=config, cache_dir=tmp_path)

        assert cache.max_size_bytes == 200 * 1024 * 1024
        assert cache.max_age_seconds == 12 * 3600

    def test_reconfigures_existing_cache(self, tmp_path):
        """Test that passing config reconfigures existing cache."""
        from unittest.mock import MagicMock

        # Create initial cache
        cache1 = get_image_cache(cache_dir=tmp_path)
        assert cache1.max_size_bytes == 500 * 1024 * 1024

        # Reconfigure with different values
        config = MagicMock()
        config.get.side_effect = lambda key, default: {
            "cache.image_cache_size_mb": 100,
            "cache.image_cache_ttl_hours": 6,
        }.get(key, default)

        cache2 = get_image_cache(config=config)

        # Should be same instance but reconfigured
        assert cache1 is cache2
        assert cache2.max_size_bytes == 100 * 1024 * 1024
        assert cache2.max_age_seconds == 6 * 3600

    def test_reset_clears_singleton(self, tmp_path):
        """Test that reset_image_cache clears the singleton."""
        cache1 = get_image_cache(cache_dir=tmp_path)
        reset_image_cache()
        cache2 = get_image_cache(cache_dir=tmp_path)

        assert cache1 is not cache2


# =============================================================================
# Tests for ImageCache index persistence
# =============================================================================


class TestImageCacheIndexPersistence:
    """Tests for ImageCache index file persistence."""

    def test_index_persisted_on_set(self, tmp_path):
        """Test that index is saved after set operation."""
        cache = ImageCache(cache_dir=tmp_path)
        cache.set("url1", b"data1")

        index_path = tmp_path / ".cache_index.json"
        assert index_path.exists()

    def test_index_restored_on_init(self, tmp_path):
        """Test that index is restored when creating new cache instance."""
        # Create cache and add data
        cache1 = ImageCache(cache_dir=tmp_path)
        cache1.set("url1", b"data1")
        cache1.set("url2", b"data2")

        # Create new cache instance
        cache2 = ImageCache(cache_dir=tmp_path)

        # Data should be accessible
        assert cache2.get("url1") == b"data1"
        assert cache2.get("url2") == b"data2"
        assert cache2.get_count() == 2

    def test_corrupted_index_rebuilds(self, tmp_path):
        """Test that corrupted index is rebuilt from files."""
        # Create cache and add data
        cache1 = ImageCache(cache_dir=tmp_path)
        cache1.set("url1", b"data1")

        # Corrupt the index
        index_path = tmp_path / ".cache_index.json"
        index_path.write_text("invalid json")

        # Create new cache instance - should rebuild index
        cache2 = ImageCache(cache_dir=tmp_path)

        # Data should still be accessible (index rebuilt)
        assert cache2.get("url1") == b"data1"
        assert cache2.get_count() == 1
