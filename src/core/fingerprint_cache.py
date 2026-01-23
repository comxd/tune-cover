"""
Fingerprint cache for avoiding redundant fingerprint calculations.

Caches both fingerprint generation results and AcoustID lookup results
to improve performance when re-analyzing the same tracks.
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CachedFingerprint:
    """Cached fingerprint data for a file."""

    filepath: str
    mtime: float  # File modification time for invalidation
    duration: float
    fingerprint: str


@dataclass(slots=True)
class CachedLookup:
    """Cached AcoustID lookup results."""

    fingerprint_hash: str  # Hash of fingerprint for key
    duration: float
    results: list[dict[str, Any]]
    timestamp: float = 0.0


class FingerprintCache:
    """
    LRU cache for fingerprints and lookup results.

    Thread-safe implementation using locks for concurrent access.
    """

    def __init__(
        self,
        max_fingerprints: int = 500,
        max_lookups: int = 200,
    ):
        """
        Initialize the cache.

        Args:
            max_fingerprints: Maximum number of file fingerprints to cache
            max_lookups: Maximum number of AcoustID lookup results to cache
        """
        self._max_fingerprints = max_fingerprints
        self._max_lookups = max_lookups

        # Fingerprint cache: filepath -> CachedFingerprint
        self._fingerprints: OrderedDict[str, CachedFingerprint] = OrderedDict()
        self._fp_lock = threading.Lock()

        # Lookup cache: fingerprint_hash -> CachedLookup
        self._lookups: OrderedDict[str, CachedLookup] = OrderedDict()
        self._lookup_lock = threading.Lock()

        # Statistics
        self._fp_hits = 0
        self._fp_misses = 0
        self._lookup_hits = 0
        self._lookup_misses = 0

    def _fingerprint_hash(self, fingerprint: str, duration: float) -> str:
        """Create a hash key for a fingerprint + duration combination."""
        key = f"{fingerprint}:{duration:.2f}"
        return hashlib.sha256(key.encode()).hexdigest()

    def get_fingerprint(self, filepath: Path) -> tuple[float, str] | None:
        """
        Get cached fingerprint for a file.

        Args:
            filepath: Path to the audio file

        Returns:
            Tuple of (duration, fingerprint) if cached and valid, None otherwise
        """
        key = str(filepath.absolute())

        with self._fp_lock:
            cached = self._fingerprints.get(key)

            if cached is None:
                self._fp_misses += 1
                return None

            # Check if file has been modified
            try:
                current_mtime = filepath.stat().st_mtime
                if current_mtime != cached.mtime:
                    # File changed, invalidate cache
                    del self._fingerprints[key]
                    self._fp_misses += 1
                    logger.debug(f"Cache invalidated (mtime changed): {filepath.name}")
                    return None
            except OSError:
                # File doesn't exist or can't be accessed
                del self._fingerprints[key]
                self._fp_misses += 1
                return None

            # Move to end (LRU)
            self._fingerprints.move_to_end(key)
            self._fp_hits += 1
            logger.debug(f"Cache hit for fingerprint: {filepath.name}")
            return (cached.duration, cached.fingerprint)

    def set_fingerprint(self, filepath: Path, duration: float, fingerprint: str) -> None:
        """
        Cache a fingerprint for a file.

        Args:
            filepath: Path to the audio file
            duration: Duration in seconds
            fingerprint: The fingerprint string
        """
        key = str(filepath.absolute())

        try:
            mtime = filepath.stat().st_mtime
        except OSError:
            logger.debug(f"Cannot cache fingerprint, file not accessible: {filepath}")
            return

        with self._fp_lock:
            # Remove oldest if at capacity
            while len(self._fingerprints) >= self._max_fingerprints:
                oldest = next(iter(self._fingerprints))
                del self._fingerprints[oldest]
                logger.debug("Evicted oldest fingerprint from cache")

            self._fingerprints[key] = CachedFingerprint(
                filepath=key,
                mtime=mtime,
                duration=duration,
                fingerprint=fingerprint,
            )
            logger.debug(f"Cached fingerprint: {filepath.name}")

    def get_lookup(self, fingerprint: str, duration: float) -> list[dict[str, Any]] | None:
        """
        Get cached AcoustID lookup results.

        Args:
            fingerprint: The fingerprint string
            duration: Duration in seconds

        Returns:
            List of lookup results if cached, None otherwise
        """
        key = self._fingerprint_hash(fingerprint, duration)

        with self._lookup_lock:
            cached = self._lookups.get(key)

            if cached is None:
                self._lookup_misses += 1
                return None

            # Move to end (LRU)
            self._lookups.move_to_end(key)
            self._lookup_hits += 1
            logger.debug("Cache hit for AcoustID lookup")
            return cached.results

    def set_lookup(
        self,
        fingerprint: str,
        duration: float,
        results: list[dict[str, Any]],
    ) -> None:
        """
        Cache AcoustID lookup results.

        Args:
            fingerprint: The fingerprint string
            duration: Duration in seconds
            results: The lookup results to cache
        """
        key = self._fingerprint_hash(fingerprint, duration)

        with self._lookup_lock:
            # Remove oldest if at capacity
            while len(self._lookups) >= self._max_lookups:
                oldest = next(iter(self._lookups))
                del self._lookups[oldest]
                logger.debug("Evicted oldest lookup from cache")

            self._lookups[key] = CachedLookup(
                fingerprint_hash=key,
                duration=duration,
                results=results,
                timestamp=time.time(),
            )
            logger.debug("Cached AcoustID lookup results")

    def clear(self) -> None:
        """Clear all cached data."""
        with self._fp_lock:
            self._fingerprints.clear()
        with self._lookup_lock:
            self._lookups.clear()
        logger.info("Fingerprint cache cleared")

    def clear_lookups(self) -> None:
        """Clear only the AcoustID lookup cache (keep fingerprints)."""
        with self._lookup_lock:
            count = len(self._lookups)
            self._lookups.clear()
            self._lookup_hits = 0
            self._lookup_misses = 0
        logger.info(f"Cleared {count} cached AcoustID lookups")

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with hit/miss rates and cache sizes
        """
        with self._fp_lock:
            fp_total = self._fp_hits + self._fp_misses
            fp_hit_rate = self._fp_hits / fp_total if fp_total > 0 else 0.0

        with self._lookup_lock:
            lookup_total = self._lookup_hits + self._lookup_misses
            lookup_hit_rate = self._lookup_hits / lookup_total if lookup_total > 0 else 0.0

        return {
            "fingerprint_cache_size": len(self._fingerprints),
            "fingerprint_max_size": self._max_fingerprints,
            "fingerprint_hits": self._fp_hits,
            "fingerprint_misses": self._fp_misses,
            "fingerprint_hit_rate": fp_hit_rate,
            "lookup_cache_size": len(self._lookups),
            "lookup_max_size": self._max_lookups,
            "lookup_hits": self._lookup_hits,
            "lookup_misses": self._lookup_misses,
            "lookup_hit_rate": lookup_hit_rate,
        }

    def __len__(self) -> int:
        """Return total number of cached items."""
        return len(self._fingerprints) + len(self._lookups)


# Module-level singleton
_default_cache: FingerprintCache | None = None
_cache_lock = threading.Lock()


def get_fingerprint_cache() -> FingerprintCache:
    """
    Get the default fingerprint cache singleton.

    Returns:
        FingerprintCache instance
    """
    global _default_cache
    with _cache_lock:
        if _default_cache is None:
            _default_cache = FingerprintCache()
        return _default_cache


def clear_fingerprint_cache() -> None:
    """Clear the default fingerprint cache."""
    global _default_cache
    with _cache_lock:
        if _default_cache is not None:
            _default_cache.clear()


def clear_acoustid_lookup_cache() -> None:
    """Clear only the AcoustID lookup cache (keep fingerprints)."""
    global _default_cache
    with _cache_lock:
        if _default_cache is not None:
            _default_cache.clear_lookups()
