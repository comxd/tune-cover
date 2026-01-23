"""
Thumbnail loading system with lazy loading support.

Provides background loading of album cover thumbnails with priority queue
and visibility-based loading.
"""

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QPixmap

from ...core.embedder import extract_embedded_cover
from ...core.models import AlbumInfo

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LoadRequest:
    """A request to load a thumbnail."""

    album_path: str
    album: AlbumInfo
    size: int
    priority: int = 0  # Higher = more important


class ThumbnailCache:
    """
    Thread-safe in-memory LRU cache for thumbnail QPixmaps.

    Caches scaled thumbnails to avoid repeated loading and scaling
    when scrolling through the album grid.
    """

    def __init__(self, max_size: int = 200):
        """
        Initialize the thumbnail cache.

        Args:
            max_size: Maximum number of thumbnails to cache.
        """
        self.max_size = max_size
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> QPixmap | None:
        """
        Get a cached thumbnail.

        Args:
            key: Cache key (typically album path)

        Returns:
            Cached QPixmap if available, None otherwise
        """
        with self._lock:
            if key in self._cache:
                # Move to end to mark as recently used
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: str, pixmap: QPixmap) -> None:
        """
        Store a thumbnail in the cache.

        Args:
            key: Cache key (typically album path)
            pixmap: The thumbnail QPixmap
        """
        with self._lock:
            # Remove existing entry if present
            if key in self._cache:
                del self._cache[key]

            # Evict oldest entries if at capacity
            while len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Evicted oldest thumbnail: {oldest_key}")

            self._cache[key] = pixmap

    def remove(self, key: str) -> bool:
        """
        Remove a thumbnail from the cache.

        Args:
            key: Cache key

        Returns:
            True if item was removed, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> int:
        """
        Clear all cached thumbnails.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def size(self) -> int:
        """Get number of cached thumbnails."""
        with self._lock:
            return len(self._cache)


class CoverLoadSignals(QObject):
    """Signals for cover load worker."""

    loaded = Signal(str, QPixmap)  # album_path, pixmap
    error = Signal(str, str)  # album_path, error_message


class CoverLoadWorker(QRunnable):
    """
    Worker that loads a cover image in a background thread.
    """

    def __init__(self, request: LoadRequest):
        """
        Initialize the worker.

        Args:
            request: The load request with album info
        """
        super().__init__()
        self.request = request
        self.signals = CoverLoadSignals()
        self._cancelled = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        """Mark this worker as cancelled."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        """Load the cover image."""
        if self._cancelled:
            return

        album = self.request.album
        size = self.request.size
        album_path = self.request.album_path

        try:
            pixmap = self._load_cover_pixmap(album, size)
            if not self._cancelled:
                self.signals.loaded.emit(album_path, pixmap)
        except Exception as e:
            logger.warning(f"Failed to load cover for {album_path}: {e}")
            if not self._cancelled:
                self.signals.error.emit(album_path, str(e))

    def _load_cover_pixmap(self, album: AlbumInfo, size: int) -> QPixmap:
        """Load and scale the cover pixmap."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter

        # Try to load folder cover first
        if album.cover.folder_path and album.cover.folder_path.exists():
            loaded = QPixmap(str(album.cover.folder_path))
            if not loaded.isNull():
                return loaded.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

        # Try to load embedded cover
        if album.cover.has_embedded and album.sample_file:
            embedded_data = extract_embedded_cover(album.sample_file)
            if embedded_data:
                loaded = QPixmap()
                if loaded.loadFromData(embedded_data):
                    return loaded.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

        # No cover found - return placeholder
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor("#2a2a2a"))
        painter = QPainter(pixmap)
        try:
            painter.setPen(QColor("#666"))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "?")
        finally:
            painter.end()

        return pixmap


class ThumbnailLoader(QObject):
    """
    Manages lazy loading of album thumbnails with priority queue.

    Features:
    - Background thread pool for loading
    - Priority queue favoring visible items
    - In-memory LRU cache
    - Cancellation of non-visible items
    """

    # Signal emitted when a thumbnail is ready
    thumbnail_ready = Signal(str, QPixmap)  # album_path, pixmap

    def __init__(self, max_workers: int = 2, cache_size: int = 200, parent=None):
        """
        Initialize the thumbnail loader.

        Args:
            max_workers: Maximum concurrent load workers
            cache_size: Maximum cached thumbnails
            parent: Parent QObject
        """
        super().__init__(parent)
        self._cache = ThumbnailCache(max_size=cache_size)
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(max_workers)

        # Pending requests and active workers
        self._pending: dict[str, LoadRequest] = {}  # album_path -> request
        self._active_workers: dict[str, CoverLoadWorker] = {}  # album_path -> worker
        self._lock = threading.RLock()

    def get_cached(self, album_path: str) -> QPixmap | None:
        """
        Get a thumbnail from cache without loading.

        Args:
            album_path: Path to the album

        Returns:
            Cached QPixmap if available, None otherwise
        """
        return self._cache.get(album_path)

    def request_thumbnail(self, album: AlbumInfo, size: int, priority: int = 0) -> QPixmap | None:
        """
        Request a thumbnail, returning cached version or queueing load.

        Args:
            album: Album to load thumbnail for
            size: Thumbnail size in pixels
            priority: Loading priority (higher = more important)

        Returns:
            Cached QPixmap if available immediately, None if loading queued
        """
        album_path = str(album.path)

        # Check cache first
        cached = self._cache.get(album_path)
        if cached is not None:
            return cached

        with self._lock:
            # Already loading?
            if album_path in self._active_workers:
                return None

            # Already pending? Update priority if higher
            if album_path in self._pending:
                if priority > self._pending[album_path].priority:
                    self._pending[album_path].priority = priority
                return None

            # Queue new request
            request = LoadRequest(album_path=album_path, album=album, size=size, priority=priority)
            self._pending[album_path] = request
            self._process_queue()

        return None

    def cancel_request(self, album_path: str) -> None:
        """
        Cancel a pending thumbnail request.

        Args:
            album_path: Path of album to cancel
        """
        with self._lock:
            # Remove from pending
            if album_path in self._pending:
                del self._pending[album_path]

            # Cancel active worker
            if album_path in self._active_workers:
                self._active_workers[album_path].cancel()
                del self._active_workers[album_path]

    def cancel_all_except(self, keep_paths: set[str]) -> None:
        """
        Cancel all requests except those in the keep set.

        Args:
            keep_paths: Set of album paths to keep loading
        """
        with self._lock:
            # Cancel pending requests not in keep set
            to_remove = [p for p in self._pending if p not in keep_paths]
            for path in to_remove:
                del self._pending[path]

            # Cancel active workers not in keep set
            to_cancel = [p for p in self._active_workers if p not in keep_paths]
            for path in to_cancel:
                self._active_workers[path].cancel()
                del self._active_workers[path]

    def invalidate_cache(self, album_path: str) -> None:
        """
        Invalidate a cached thumbnail (e.g., after cover update).

        Args:
            album_path: Path of album to invalidate
        """
        self._cache.remove(album_path)

    def clear_cache(self) -> None:
        """Clear all cached thumbnails."""
        self._cache.clear()

    def _process_queue(self) -> None:
        """Process pending requests, starting highest priority first."""
        with self._lock:
            # Get available slots
            available = self._thread_pool.maxThreadCount() - self._thread_pool.activeThreadCount()
            if available <= 0 or not self._pending:
                return

            # Sort by priority (highest first)
            sorted_requests = sorted(
                self._pending.items(), key=lambda x: x[1].priority, reverse=True
            )

            # Start workers for available slots
            for album_path, request in sorted_requests[:available]:
                del self._pending[album_path]
                self._start_worker(request)

    def _start_worker(self, request: LoadRequest) -> None:
        """Start a worker for a load request."""
        worker = CoverLoadWorker(request)
        worker.signals.loaded.connect(self._on_loaded)
        worker.signals.error.connect(self._on_error)

        self._active_workers[request.album_path] = worker
        self._thread_pool.start(worker)

    @Slot(str, QPixmap)
    def _on_loaded(self, album_path: str, pixmap: QPixmap) -> None:
        """Handle successful thumbnail load."""
        with self._lock:
            # Remove from active workers
            if album_path in self._active_workers:
                del self._active_workers[album_path]

            # Cache the result
            self._cache.put(album_path, pixmap)

            # Process more pending requests
            self._process_queue()

        # Emit signal
        self.thumbnail_ready.emit(album_path, pixmap)

    @Slot(str, str)
    def _on_error(self, album_path: str, error: str) -> None:
        """Handle thumbnail load error."""
        with self._lock:
            if album_path in self._active_workers:
                del self._active_workers[album_path]

            # Process more pending requests
            self._process_queue()

        logger.warning(f"Thumbnail load error for {album_path}: {error}")

    def shutdown(self) -> None:
        """Shutdown the loader and wait for workers to finish."""
        with self._lock:
            # Cancel all pending
            self._pending.clear()

            # Cancel all active workers
            for worker in self._active_workers.values():
                worker.cancel()
            self._active_workers.clear()

        # Wait for thread pool to finish
        self._thread_pool.waitForDone(1000)

        # Clear the thread pool explicitly
        self._thread_pool.clear()

        # Clear thumbnail cache
        self._cache.clear()
