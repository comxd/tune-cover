"""
Image caching for TuneCover.
Thread-safe file-based cache implementation.
"""

import contextlib
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from .constants import APP_NAME_SLUG

logger = logging.getLogger(__name__)


class ImageCache:
    """
    Thread-safe file-based image cache for cover art with LRU eviction.

    Enforces a maximum disk size limit and evicts least recently used
    entries when the limit is reached.
    """

    # Default max size: 500 MB
    DEFAULT_MAX_SIZE_BYTES = 500 * 1024 * 1024

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_age_hours: int = 24,
        max_size_bytes: int | None = None,
    ):
        """
        Initialize the image cache.

        Args:
            cache_dir: Directory for cached images. If None, uses default location.
            max_age_hours: Maximum age of cached images in hours.
            max_size_bytes: Maximum total cache size in bytes. Defaults to 500 MB.
        """
        if cache_dir is None:
            cache_dir = self._get_default_cache_dir()
        self.cache_dir = cache_dir
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            # Fall back to temp directory if cache dir cannot be created
            logger.warning(f"Could not create cache directory {self.cache_dir}: {e}")
            import tempfile

            self.cache_dir = Path(tempfile.mkdtemp(prefix="music-tagger-cache-"))
            logger.info(f"Using temporary cache directory: {self.cache_dir}")

        self.max_age_seconds = max_age_hours * 3600
        self.max_size_bytes = (
            max_size_bytes if max_size_bytes is not None else self.DEFAULT_MAX_SIZE_BYTES
        )
        self._lock = threading.RLock()

        # LRU tracking: OrderedDict preserves access order (oldest first).
        # Timestamps are kept for TTL checks but ordering relies on dict position.
        self._index: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._index_path = self.cache_dir / ".cache_index.json"
        self._load_index()

    def _get_default_cache_dir(self) -> Path:
        """Get the default cache directory."""
        xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache_home:
            return Path(xdg_cache_home) / APP_NAME_SLUG / "images"
        return Path.home() / ".cache" / APP_NAME_SLUG / "images"

    def _load_index(self) -> None:
        """Load the cache index from disk."""
        try:
            if self._index_path.exists():
                with self._index_path.open(encoding="utf-8") as f:
                    data = json.load(f)
                    # Convert lists back to tuples (JSON preserves insertion order)
                    self._index = OrderedDict((k, tuple(v)) for k, v in data.items())
                    # Validate index against actual files
                    self._sync_index()
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Could not load cache index: {e}")
            self._index = OrderedDict()
            self._rebuild_index()

    def _save_index(self) -> None:
        """Save the cache index to disk."""
        try:
            with self._index_path.open("w", encoding="utf-8") as f:
                json.dump(self._index, f)
        except OSError as e:
            logger.warning(f"Could not save cache index: {e}")

    def _sync_index(self) -> None:
        """Sync the index with actual files on disk."""
        # Remove entries for files that no longer exist
        to_remove = []
        for key in self._index:
            cache_path = self.cache_dir / f"{key}.cache"
            if not cache_path.exists():
                to_remove.append(key)

        for key in to_remove:
            del self._index[key]

        # Add entries for files not in index
        try:
            for cache_file in self.cache_dir.glob("*.cache"):
                key = cache_file.stem
                if key not in self._index:
                    try:
                        stat = cache_file.stat()
                        self._index[key] = (stat.st_size, stat.st_mtime)
                    except OSError:
                        pass
        except OSError:
            pass

        if to_remove:
            self._save_index()

    def _rebuild_index(self) -> None:
        """Rebuild the index from disk."""
        self._index = OrderedDict()
        try:
            for cache_file in self.cache_dir.glob("*.cache"):
                try:
                    stat = cache_file.stat()
                    key = cache_file.stem
                    self._index[key] = (stat.st_size, stat.st_mtime)
                except OSError:
                    pass
            self._save_index()
        except OSError:
            pass

    def _get_cache_key(self, url: str) -> str:
        """Generate a cache key from URL."""
        return hashlib.md5(url.encode()).hexdigest()

    def _get_cache_path(self, url: str) -> Path:
        """Get the cache file path for a URL."""
        key = self._get_cache_key(url)
        return self.cache_dir / f"{key}.cache"

    def _get_total_size(self) -> int:
        """Get total size of cache from index."""
        return sum(size for size, _ in self._index.values())

    def _evict_lru(self, needed_space: int) -> None:
        """
        Evict least recently used entries to free up space.

        Iterates from the front of the OrderedDict (oldest entries first).
        This is O(k) where k = entries evicted, vs O(n log n) for timestamp sorting.

        Args:
            needed_space: Minimum bytes to free
        """
        if not self._index:
            return

        freed = 0
        # Collect keys to evict (oldest are at the front of the OrderedDict)
        keys_to_evict = []
        for key, (size, _) in self._index.items():
            if freed >= needed_space:
                break
            keys_to_evict.append(key)
            freed += size

        for key in keys_to_evict:
            cache_path = self.cache_dir / f"{key}.cache"
            try:
                cache_path.unlink()
                logger.debug(f"Evicted cache entry: {key} ({self._index[key][0]} bytes)")
            except (OSError, FileNotFoundError):
                pass
            # Always remove from index regardless of file deletion result
            del self._index[key]

        if freed > 0:
            self._save_index()
            logger.debug(f"LRU eviction freed {freed} bytes")

    def get(self, url: str) -> bytes | None:
        """
        Get cached image data.

        Args:
            url: Image URL

        Returns:
            Cached image data if available and not expired, None otherwise
        """
        with self._lock:
            key = self._get_cache_key(url)
            cache_path = self._get_cache_path(url)

            try:
                if not cache_path.exists():
                    if key in self._index:
                        del self._index[key]
                    return None

                stat = cache_path.stat()

                # Check if cache is expired
                age = time.time() - stat.st_mtime
                if age > self.max_age_seconds:
                    try:
                        cache_path.unlink()
                        if key in self._index:
                            del self._index[key]
                            self._save_index()
                    except (OSError, FileNotFoundError):
                        pass
                    return None

                # Update access time and move to end of OrderedDict (most recent)
                self._index[key] = (stat.st_size, time.time())
                self._index.move_to_end(key)
                # Don't save index on every read for performance
                # It will be saved on next write or on shutdown

                return cache_path.read_bytes()
            except (OSError, FileNotFoundError) as e:
                logger.warning(f"Could not read cache: {e}")
                return None

    def set(self, url: str, data: bytes) -> None:
        """
        Cache image data.

        Args:
            url: Image URL
            data: Image data
        """
        with self._lock:
            key = self._get_cache_key(url)
            cache_path = self._get_cache_path(url)
            data_size = len(data)

            # Check if we need to evict entries
            current_size = self._get_total_size()
            existing_size = self._index.get(key, (0, 0))[0]
            new_total = current_size - existing_size + data_size

            if new_total > self.max_size_bytes:
                needed_space = new_total - self.max_size_bytes
                self._evict_lru(needed_space)

            try:
                cache_path.write_bytes(data)
                self._index[key] = (data_size, time.time())
                self._index.move_to_end(key)
                self._save_index()
            except OSError as e:
                logger.warning(f"Could not write cache: {e}")

    def clear(self) -> int:
        """
        Clear all cached images.

        Returns:
            Number of files deleted
        """
        with self._lock:
            count = 0
            try:
                for cache_file in self.cache_dir.glob("*.cache"):
                    try:
                        cache_file.unlink()
                        count += 1
                    except (OSError, FileNotFoundError):
                        pass
                # Also remove index file
                with contextlib.suppress(OSError, FileNotFoundError):
                    self._index_path.unlink()
            except OSError:
                pass
            self._index = OrderedDict()
            return count

    def clear_expired(self) -> int:
        """
        Clear expired cached images.

        Returns:
            Number of files deleted
        """
        with self._lock:
            count = 0
            current_time = time.time()

            try:
                for cache_file in self.cache_dir.glob("*.cache"):
                    try:
                        age = current_time - cache_file.stat().st_mtime
                        if age > self.max_age_seconds:
                            key = cache_file.stem
                            cache_file.unlink()
                            if key in self._index:
                                del self._index[key]
                            count += 1
                    except (OSError, FileNotFoundError):
                        pass

                if count > 0:
                    self._save_index()
            except OSError:
                pass

            return count

    def get_size(self) -> int:
        """
        Get total size of cache in bytes.

        Returns:
            Total cache size in bytes
        """
        with self._lock:
            return self._get_total_size()

    def get_count(self) -> int:
        """
        Get number of cached items.

        Returns:
            Number of cached items
        """
        with self._lock:
            return len(self._index)

    def configure(
        self, max_size_bytes: int | None = None, max_age_hours: int | None = None
    ) -> None:
        """
        Reconfigure cache limits. Triggers eviction if new limits are lower.

        Args:
            max_size_bytes: New maximum cache size in bytes
            max_age_hours: New maximum age in hours
        """
        with self._lock:
            if max_age_hours is not None:
                self.max_age_seconds = max_age_hours * 3600

            if max_size_bytes is not None:
                self.max_size_bytes = max_size_bytes
                # Evict if over new limit
                current_size = self._get_total_size()
                if current_size > self.max_size_bytes:
                    self._evict_lru(current_size - self.max_size_bytes)


class EmbeddedCoverCache:
    """
    Thread-safe in-memory LRU cache for embedded cover art extracted from audio files.

    Uses file path and modification time as cache key to automatically invalidate
    entries when files are modified. Enforces both entry count and memory limits.
    """

    # Default max memory: 100 MB
    DEFAULT_MAX_MEMORY_BYTES = 100 * 1024 * 1024

    def __init__(self, max_size: int = 100, max_memory_bytes: int | None = None):
        """
        Initialize the embedded cover cache.

        Args:
            max_size: Maximum number of entries to cache.
            max_memory_bytes: Maximum memory usage in bytes. Defaults to 100 MB.
        """
        self.max_size = max_size
        self.max_memory_bytes = (
            max_memory_bytes if max_memory_bytes is not None else self.DEFAULT_MAX_MEMORY_BYTES
        )
        self._cache: OrderedDict[tuple[str, float], bytes] = OrderedDict()
        self._lock = threading.RLock()
        self._invalidation_callbacks: list[Callable[[str], None]] = []

    def register_invalidation_callback(self, callback: Callable[[str], None]) -> None:
        """
        Register a callback to be called when a cache entry is invalidated.

        Args:
            callback: Function that receives the absolute file path being invalidated
        """
        with self._lock:
            self._invalidation_callbacks.append(callback)

    def unregister_invalidation_callback(self, callback: Callable[[str], None]) -> None:
        """
        Unregister an invalidation callback.

        Args:
            callback: The callback to remove
        """
        with self._lock:
            if callback in self._invalidation_callbacks:
                self._invalidation_callbacks.remove(callback)

    def _notify_invalidation(self, abs_path: str) -> None:
        """Notify all registered callbacks of an invalidation."""
        for callback in self._invalidation_callbacks:
            try:
                callback(abs_path)
            except (ValueError, TypeError, RuntimeError) as e:
                logger.warning(f"Invalidation callback error: {e}")

    def _get_cache_key(self, file_path: Path) -> tuple[str, float] | None:
        """
        Generate a cache key from file path and modification time.

        Args:
            file_path: Path to the audio file

        Returns:
            Tuple of (absolute path, mtime) or None if file doesn't exist
        """
        try:
            abs_path = str(file_path.resolve())
            mtime = file_path.stat().st_mtime
            return (abs_path, mtime)
        except (OSError, FileNotFoundError):
            return None

    def get(self, file_path: Path) -> bytes | None:
        """
        Get cached embedded cover data.

        Args:
            file_path: Path to the audio file

        Returns:
            Cached cover data if available and file hasn't been modified, None otherwise
        """
        with self._lock:
            cache_key = self._get_cache_key(file_path)
            if cache_key is None:
                return None

            # Check if exact key (path + mtime) exists
            if cache_key in self._cache:
                # Move to end to mark as recently used
                self._cache.move_to_end(cache_key)
                logger.debug(f"Cache hit for embedded cover: {file_path}")
                return self._cache[cache_key]

            # Clean up any stale entries for this path (different mtime)
            abs_path = cache_key[0]
            stale_keys = [k for k in self._cache if k[0] == abs_path]
            for stale_key in stale_keys:
                del self._cache[stale_key]
                logger.debug(f"Invalidated stale cache entry: {stale_key}")

            # Notify callbacks if stale entries were removed
            if stale_keys:
                self._notify_invalidation(abs_path)

            return None

    def put(self, file_path: Path, data: bytes) -> None:
        """
        Store embedded cover data in cache.

        Args:
            file_path: Path to the audio file
            data: Raw cover image data
        """
        with self._lock:
            cache_key = self._get_cache_key(file_path)
            if cache_key is None:
                return

            abs_path = cache_key[0]
            data_size = len(data)

            # Remove any existing entries for this path (different mtime)
            stale_keys = [k for k in self._cache if k[0] == abs_path]
            for stale_key in stale_keys:
                del self._cache[stale_key]

            # Evict oldest entries if at capacity (count or memory)
            while len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Evicted oldest cache entry (count limit): {oldest_key}")

            # Also check memory limit
            while self._cache and (self.get_memory_usage() + data_size > self.max_memory_bytes):
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Evicted oldest cache entry (memory limit): {oldest_key}")

            self._cache[cache_key] = data
            logger.debug(f"Cached embedded cover: {file_path}")

    def invalidate(self, file_path: Path) -> bool:
        """
        Invalidate cache entry for a specific file.

        Args:
            file_path: Path to the audio file

        Returns:
            True if an entry was removed, False otherwise
        """
        with self._lock:
            abs_path = str(file_path.resolve())
            # Find and remove all entries for this path (any mtime)
            keys_to_remove = [k for k in self._cache if k[0] == abs_path]
            for key in keys_to_remove:
                del self._cache[key]
                logger.debug(f"Invalidated cache entry for: {file_path}")

            # Notify callbacks
            if keys_to_remove:
                self._notify_invalidation(abs_path)

            return len(keys_to_remove) > 0

    def clear(self) -> int:
        """
        Clear all cached entries.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.debug(f"Cleared {count} embedded cover cache entries")
            return count

    def get_size(self) -> int:
        """
        Get number of cached entries.

        Returns:
            Number of cached entries
        """
        with self._lock:
            return len(self._cache)

    def get_memory_usage(self) -> int:
        """
        Get approximate memory usage of cached data in bytes.

        Returns:
            Total size of cached data in bytes
        """
        with self._lock:
            return sum(len(data) for data in self._cache.values())

    def configure(self, max_size: int | None = None, max_memory_bytes: int | None = None) -> None:
        """
        Reconfigure cache limits. Clears cache if limits are reduced significantly.

        Args:
            max_size: New maximum entry count
            max_memory_bytes: New maximum memory in bytes
        """
        with self._lock:
            if max_size is not None:
                self.max_size = max_size

            if max_memory_bytes is not None:
                self.max_memory_bytes = max_memory_bytes

            # Evict entries if over new limits
            while len(self._cache) > self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

            while self._cache and self.get_memory_usage() > self.max_memory_bytes:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]


# Module-level cache instances
embedded_cover_cache = EmbeddedCoverCache(max_size=100)

# Singleton for ImageCache
_image_cache: ImageCache | None = None
_image_cache_lock = threading.Lock()


def get_image_cache(
    config: "Config | None" = None,
    cache_dir: Path | None = None,
) -> ImageCache:
    """
    Get or create the shared ImageCache instance.

    Args:
        config: Optional Config instance to read settings from
        cache_dir: Optional cache directory (used for testing)

    Returns:
        The shared ImageCache instance
    """
    global _image_cache

    with _image_cache_lock:
        if _image_cache is None:
            # Get settings from config or use defaults
            if config is not None:
                size_mb = config.get("cache.image_cache_size_mb", 500)
                ttl_hours = config.get("cache.image_cache_ttl_hours", 24)
            else:
                size_mb = 500
                ttl_hours = 24

            _image_cache = ImageCache(
                cache_dir=cache_dir,
                max_size_bytes=size_mb * 1024 * 1024,
                max_age_hours=ttl_hours,
            )
        elif config is not None:
            # Reconfigure existing cache with new settings
            size_mb = config.get("cache.image_cache_size_mb", 500)
            ttl_hours = config.get("cache.image_cache_ttl_hours", 24)
            _image_cache.configure(
                max_size_bytes=size_mb * 1024 * 1024,
                max_age_hours=ttl_hours,
            )

        return _image_cache


def reset_image_cache() -> None:
    """Reset the singleton image cache. Used for testing."""
    global _image_cache
    with _image_cache_lock:
        _image_cache = None


# Type hint import for Config (avoid circular import)
if False:  # TYPE_CHECKING
    from .config import Config
