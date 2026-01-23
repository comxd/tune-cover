"""Tests for fingerprint cache module."""

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.fingerprint_cache import (
    CachedFingerprint,
    CachedLookup,
    FingerprintCache,
    clear_fingerprint_cache,
    get_fingerprint_cache,
)


class TestCachedFingerprint:
    """Tests for CachedFingerprint dataclass."""

    def test_create_cached_fingerprint(self):
        """Test creating a CachedFingerprint."""
        cached = CachedFingerprint(
            filepath="/path/to/file.mp3",
            mtime=1234567890.0,
            duration=180.5,
            fingerprint="AQAA...",
        )
        assert cached.filepath == "/path/to/file.mp3"
        assert cached.mtime == 1234567890.0
        assert cached.duration == 180.5
        assert cached.fingerprint == "AQAA..."


class TestCachedLookup:
    """Tests for CachedLookup dataclass."""

    def test_create_cached_lookup(self):
        """Test creating a CachedLookup."""
        results = [{"score": 0.9, "title": "Test"}]
        cached = CachedLookup(
            fingerprint_hash="abc123",
            duration=180.5,
            results=results,
            timestamp=1234567890.0,
        )
        assert cached.fingerprint_hash == "abc123"
        assert cached.duration == 180.5
        assert cached.results == results
        assert cached.timestamp == 1234567890.0

    def test_default_timestamp(self):
        """Test that timestamp defaults to 0.0."""
        cached = CachedLookup(
            fingerprint_hash="abc123",
            duration=180.5,
            results=[],
        )
        assert cached.timestamp == 0.0


class TestFingerprintCache:
    """Tests for FingerprintCache class."""

    def test_init_default_sizes(self):
        """Test default cache sizes."""
        cache = FingerprintCache()
        stats = cache.get_stats()
        assert stats["fingerprint_max_size"] == 500
        assert stats["lookup_max_size"] == 200

    def test_init_custom_sizes(self):
        """Test custom cache sizes."""
        cache = FingerprintCache(max_fingerprints=100, max_lookups=50)
        stats = cache.get_stats()
        assert stats["fingerprint_max_size"] == 100
        assert stats["lookup_max_size"] == 50

    def test_get_fingerprint_miss(self):
        """Test cache miss for fingerprint."""
        cache = FingerprintCache()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test data")

        try:
            result = cache.get_fingerprint(filepath)
            assert result is None
            stats = cache.get_stats()
            assert stats["fingerprint_misses"] == 1
        finally:
            filepath.unlink()

    def test_set_and_get_fingerprint(self):
        """Test setting and getting a fingerprint."""
        cache = FingerprintCache()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test data")

        try:
            # Set fingerprint
            cache.set_fingerprint(filepath, 180.5, "AQAA...")

            # Get it back
            result = cache.get_fingerprint(filepath)
            assert result is not None
            duration, fingerprint = result
            assert duration == 180.5
            assert fingerprint == "AQAA..."

            # Check stats
            stats = cache.get_stats()
            assert stats["fingerprint_hits"] == 1
            assert stats["fingerprint_cache_size"] == 1
        finally:
            filepath.unlink()

    def test_fingerprint_cache_invalidation_on_mtime_change(self):
        """Test that cache is invalidated when file mtime changes."""
        cache = FingerprintCache()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test data")

        try:
            # Set fingerprint
            cache.set_fingerprint(filepath, 180.5, "AQAA...")

            # Modify file
            time.sleep(0.1)
            filepath.write_bytes(b"modified data")

            # Should be cache miss due to mtime change
            result = cache.get_fingerprint(filepath)
            assert result is None
        finally:
            filepath.unlink()

    def test_fingerprint_cache_lru_eviction(self):
        """Test LRU eviction for fingerprint cache."""
        cache = FingerprintCache(max_fingerprints=2)

        # Create temp files
        files = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                filepath = Path(f.name)
                f.write(f"test data {i}".encode())
                files.append(filepath)

        try:
            # Add 3 fingerprints (max is 2)
            for i, filepath in enumerate(files):
                cache.set_fingerprint(filepath, float(i), f"FP{i}")

            # First file should be evicted
            assert cache.get_fingerprint(files[0]) is None
            # Second and third should still be there
            assert cache.get_fingerprint(files[1]) is not None
            assert cache.get_fingerprint(files[2]) is not None
        finally:
            for f in files:
                f.unlink()

    def test_get_lookup_miss(self):
        """Test cache miss for lookup."""
        cache = FingerprintCache()
        result = cache.get_lookup("fingerprint", 180.5)
        assert result is None
        stats = cache.get_stats()
        assert stats["lookup_misses"] == 1

    def test_set_and_get_lookup(self):
        """Test setting and getting a lookup result."""
        cache = FingerprintCache()
        results = [{"score": 0.9, "title": "Test Song"}]

        # Set lookup
        cache.set_lookup("fingerprint123", 180.5, results)

        # Get it back
        cached = cache.get_lookup("fingerprint123", 180.5)
        assert cached is not None
        assert cached == results

        # Check stats
        stats = cache.get_stats()
        assert stats["lookup_hits"] == 1
        assert stats["lookup_cache_size"] == 1

    def test_lookup_cache_lru_eviction(self):
        """Test LRU eviction for lookup cache."""
        cache = FingerprintCache(max_lookups=2)

        # Add 3 lookups (max is 2)
        for i in range(3):
            cache.set_lookup(f"fingerprint{i}", float(i), [{"score": 0.9}])

        # First lookup should be evicted
        assert cache.get_lookup("fingerprint0", 0.0) is None
        # Second and third should still be there
        assert cache.get_lookup("fingerprint1", 1.0) is not None
        assert cache.get_lookup("fingerprint2", 2.0) is not None

    def test_clear_cache(self):
        """Test clearing the cache."""
        cache = FingerprintCache()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test data")

        try:
            cache.set_fingerprint(filepath, 180.5, "AQAA...")
            cache.set_lookup("fingerprint", 180.5, [{"score": 0.9}])

            assert len(cache) == 2

            cache.clear()

            assert len(cache) == 0
            assert cache.get_fingerprint(filepath) is None
            assert cache.get_lookup("fingerprint", 180.5) is None
        finally:
            filepath.unlink()

    def test_get_stats(self):
        """Test getting cache statistics."""
        cache = FingerprintCache(max_fingerprints=100, max_lookups=50)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test data")

        try:
            # Generate some hits and misses
            cache.get_fingerprint(filepath)  # miss
            cache.set_fingerprint(filepath, 180.5, "AQAA...")
            cache.get_fingerprint(filepath)  # hit

            cache.get_lookup("fp1", 100.0)  # miss
            cache.set_lookup("fp1", 100.0, [])
            cache.get_lookup("fp1", 100.0)  # hit
            cache.get_lookup("fp2", 100.0)  # miss

            stats = cache.get_stats()
            assert stats["fingerprint_cache_size"] == 1
            assert stats["fingerprint_max_size"] == 100
            assert stats["fingerprint_hits"] == 1
            assert stats["fingerprint_misses"] == 1
            assert stats["fingerprint_hit_rate"] == 0.5
            assert stats["lookup_cache_size"] == 1
            assert stats["lookup_max_size"] == 50
            assert stats["lookup_hits"] == 1
            assert stats["lookup_misses"] == 2
            assert stats["lookup_hit_rate"] == pytest.approx(1 / 3)
        finally:
            filepath.unlink()

    def test_len(self):
        """Test __len__ method."""
        cache = FingerprintCache()
        assert len(cache) == 0

        cache.set_lookup("fp1", 100.0, [])
        assert len(cache) == 1

        cache.set_lookup("fp2", 100.0, [])
        assert len(cache) == 2


class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_fingerprint_cache_singleton(self):
        """Test that get_fingerprint_cache returns a singleton."""
        # Clear any existing cache
        clear_fingerprint_cache()

        cache1 = get_fingerprint_cache()
        cache2 = get_fingerprint_cache()
        assert cache1 is cache2

    def test_clear_fingerprint_cache(self):
        """Test clearing the global cache."""
        cache = get_fingerprint_cache()
        cache.set_lookup("fp1", 100.0, [{"score": 0.9}])

        clear_fingerprint_cache()

        # After clearing, should be empty
        cache = get_fingerprint_cache()
        assert cache.get_lookup("fp1", 100.0) is None


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_fingerprint_access(self):
        """Test concurrent access to fingerprint cache."""
        import concurrent.futures

        cache = FingerprintCache()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test data")

        try:

            def write_read(i):
                cache.set_fingerprint(filepath, float(i), f"FP{i}")
                return cache.get_fingerprint(filepath)

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(write_read, i) for i in range(100)]
                results = [f.result() for f in futures]

            # All results should be valid
            for result in results:
                assert result is not None
        finally:
            filepath.unlink()

    def test_concurrent_lookup_access(self):
        """Test concurrent access to lookup cache."""
        import concurrent.futures

        cache = FingerprintCache()

        def write_read(i):
            cache.set_lookup(f"fp{i}", float(i), [{"score": 0.9}])
            return cache.get_lookup(f"fp{i}", float(i))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_read, i) for i in range(100)]
            results = [f.result() for f in futures]

        # All results should be valid
        for result in results:
            assert result is not None
