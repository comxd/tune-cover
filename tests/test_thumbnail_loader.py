"""
Tests for the thumbnail loading system.

Note: These tests mock Qt components to avoid requiring a QApplication.
For full GUI tests, use pytest-qt.
"""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.models import AlbumInfo


class TestLoadRequest:
    """Tests for LoadRequest dataclass."""

    def test_create_load_request(self):
        """Test creating a LoadRequest."""
        from src.ui.widgets.thumbnail_loader import LoadRequest

        album = MagicMock(spec=AlbumInfo)
        request = LoadRequest(
            album_path="/music/artist/album",
            album=album,
            size=150,
            priority=5,
        )

        assert request.album_path == "/music/artist/album"
        assert request.album == album
        assert request.size == 150
        assert request.priority == 5

    def test_load_request_default_priority(self):
        """Test LoadRequest has default priority of 0."""
        from src.ui.widgets.thumbnail_loader import LoadRequest

        album = MagicMock(spec=AlbumInfo)
        request = LoadRequest(
            album_path="/music/artist/album",
            album=album,
            size=150,
        )

        assert request.priority == 0


class TestThumbnailCache:
    """Tests for ThumbnailCache."""

    def test_cache_initialization(self):
        """Test cache is initialized correctly."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache(max_size=100)
        assert cache.max_size == 100
        assert cache.size() == 0

    def test_cache_default_size(self):
        """Test cache has default max size of 200."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()
        assert cache.max_size == 200

    def test_put_and_get(self):
        """Test putting and getting items from cache."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()
        mock_pixmap = MagicMock()

        cache.put("key1", mock_pixmap)
        result = cache.get("key1")

        assert result == mock_pixmap
        assert cache.size() == 1

    def test_get_nonexistent_returns_none(self):
        """Test getting nonexistent key returns None."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()
        result = cache.get("nonexistent")

        assert result is None

    def test_get_moves_to_end_lru(self):
        """Test getting an item moves it to end (most recently used)."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache(max_size=3)
        cache.put("key1", MagicMock())
        cache.put("key2", MagicMock())
        cache.put("key3", MagicMock())

        # Access key1 - should move it to end
        cache.get("key1")

        # Get keys in order (first should be key2 now, as key1 moved to end)
        keys = list(cache._cache.keys())
        assert keys[0] == "key2"
        assert keys[-1] == "key1"

    def test_put_updates_existing_key(self):
        """Test putting existing key updates the value."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()
        pixmap1 = MagicMock()
        pixmap2 = MagicMock()

        cache.put("key1", pixmap1)
        cache.put("key1", pixmap2)

        assert cache.get("key1") == pixmap2
        assert cache.size() == 1

    def test_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache(max_size=3)
        cache.put("key1", MagicMock())
        cache.put("key2", MagicMock())
        cache.put("key3", MagicMock())

        # Adding a 4th item should evict key1 (oldest)
        cache.put("key4", MagicMock())

        assert cache.size() == 3
        assert cache.get("key1") is None
        assert cache.get("key2") is not None
        assert cache.get("key4") is not None

    def test_remove_existing_key(self):
        """Test removing an existing key."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()
        cache.put("key1", MagicMock())

        result = cache.remove("key1")

        assert result is True
        assert cache.size() == 0
        assert cache.get("key1") is None

    def test_remove_nonexistent_key(self):
        """Test removing nonexistent key returns False."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()

        result = cache.remove("nonexistent")

        assert result is False

    def test_clear(self):
        """Test clearing the cache."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()
        cache.put("key1", MagicMock())
        cache.put("key2", MagicMock())
        cache.put("key3", MagicMock())

        count = cache.clear()

        assert count == 3
        assert cache.size() == 0

    def test_clear_empty_cache(self):
        """Test clearing an empty cache."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache()

        count = cache.clear()

        assert count == 0

    def test_thread_safety(self):
        """Test cache is thread-safe for concurrent access."""
        from src.ui.widgets.thumbnail_loader import ThumbnailCache

        cache = ThumbnailCache(max_size=1000)
        errors = []

        def writer(start):
            try:
                for i in range(100):
                    cache.put(f"key_{start}_{i}", MagicMock())
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    for i in range(10):
                        cache.get(f"key_0_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(0,)),
            threading.Thread(target=writer, args=(1,)),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestCoverLoadWorker:
    """Tests for CoverLoadWorker."""

    def test_worker_creation(self):
        """Test worker can be created."""
        from src.ui.widgets.thumbnail_loader import CoverLoadWorker, LoadRequest

        album = MagicMock(spec=AlbumInfo)
        request = LoadRequest(
            album_path="/music/artist/album",
            album=album,
            size=150,
        )

        worker = CoverLoadWorker(request)

        assert worker.request == request
        assert worker._cancelled is False

    def test_worker_cancel(self):
        """Test worker can be cancelled."""
        from src.ui.widgets.thumbnail_loader import CoverLoadWorker, LoadRequest

        album = MagicMock(spec=AlbumInfo)
        request = LoadRequest(
            album_path="/music/artist/album",
            album=album,
            size=150,
        )

        worker = CoverLoadWorker(request)
        worker.cancel()

        assert worker._cancelled is True

    def test_worker_run_cancelled(self):
        """Test worker run does nothing when cancelled."""
        from src.ui.widgets.thumbnail_loader import CoverLoadWorker, LoadRequest

        album = MagicMock(spec=AlbumInfo)
        request = LoadRequest(
            album_path="/music/artist/album",
            album=album,
            size=150,
        )

        worker = CoverLoadWorker(request)
        worker.cancel()

        # Mock the signals
        worker.signals.loaded = MagicMock()
        worker.signals.error = MagicMock()

        worker.run()

        worker.signals.loaded.emit.assert_not_called()
        worker.signals.error.emit.assert_not_called()


class TestCoverLoadSignals:
    """Tests for CoverLoadSignals."""

    def test_signals_exist(self):
        """Test signals are defined."""
        from src.ui.widgets.thumbnail_loader import CoverLoadSignals

        signals = CoverLoadSignals()

        assert hasattr(signals, "loaded")
        assert hasattr(signals, "error")


class TestThumbnailLoaderLogic:
    """Tests for ThumbnailLoader business logic without Qt event loop."""

    def test_get_cached_returns_none_when_empty(self):
        """Test get_cached returns None for missing items."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool"):
            loader = ThumbnailLoader()
            result = loader.get_cached("/nonexistent/path")

            assert result is None

    def test_get_cached_returns_cached_item(self):
        """Test get_cached returns cached pixmap."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool"):
            loader = ThumbnailLoader()
            mock_pixmap = MagicMock()

            # Directly put in cache
            loader._cache.put("/music/album", mock_pixmap)

            result = loader.get_cached("/music/album")

            assert result == mock_pixmap

    def test_request_thumbnail_returns_cached(self):
        """Test request_thumbnail returns cached pixmap immediately."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool"):
            loader = ThumbnailLoader()
            mock_pixmap = MagicMock()
            album_path = Path("/music/artist/album")

            # Pre-cache using str(Path) to match what request_thumbnail uses internally
            # This ensures cross-platform consistency (Windows vs Unix path separators)
            loader._cache.put(str(album_path), mock_pixmap)

            album = MagicMock(spec=AlbumInfo)
            album.path = album_path

            result = loader.request_thumbnail(album, size=150)

            assert result == mock_pixmap

    def test_request_thumbnail_queues_new_request(self):
        """Test request_thumbnail queues new request when not cached."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 2
            mock_pool.activeThreadCount.return_value = 0
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()
            album = MagicMock(spec=AlbumInfo)
            album.path = Path("/music/artist/album")

            result = loader.request_thumbnail(album, size=150)

            # Should return None (loading queued)
            assert result is None
            # Worker should be started
            assert mock_pool.start.called

    def test_request_thumbnail_updates_priority_if_higher(self):
        """Test request_thumbnail updates priority for pending request."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 0  # No slots available
            mock_pool.activeThreadCount.return_value = 0
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()
            album = MagicMock(spec=AlbumInfo)
            album.path = Path("/music/artist/album")

            # First request with low priority
            loader.request_thumbnail(album, size=150, priority=1)
            assert loader._pending[str(album.path)].priority == 1

            # Second request with higher priority
            loader.request_thumbnail(album, size=150, priority=10)
            assert loader._pending[str(album.path)].priority == 10

    def test_cancel_request_removes_pending(self):
        """Test cancel_request removes from pending."""
        from src.ui.widgets.thumbnail_loader import LoadRequest, ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 0
            mock_pool.activeThreadCount.return_value = 0
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()

            # Add pending request directly
            album = MagicMock(spec=AlbumInfo)
            request = LoadRequest(
                album_path="/music/album",
                album=album,
                size=150,
            )
            loader._pending["/music/album"] = request

            loader.cancel_request("/music/album")

            assert "/music/album" not in loader._pending

    def test_cancel_request_cancels_active_worker(self):
        """Test cancel_request cancels active worker."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool"):
            loader = ThumbnailLoader()

            # Add active worker
            mock_worker = MagicMock()
            loader._active_workers["/music/album"] = mock_worker

            loader.cancel_request("/music/album")

            mock_worker.cancel.assert_called_once()
            assert "/music/album" not in loader._active_workers

    def test_cancel_all_except_keeps_specified(self):
        """Test cancel_all_except keeps specified paths."""
        from src.ui.widgets.thumbnail_loader import LoadRequest, ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool"):
            loader = ThumbnailLoader()

            album = MagicMock(spec=AlbumInfo)

            # Add multiple pending requests
            for path in ["/music/album1", "/music/album2", "/music/album3"]:
                loader._pending[path] = LoadRequest(
                    album_path=path,
                    album=album,
                    size=150,
                )

            # Add active workers
            for path in ["/music/album4", "/music/album5"]:
                loader._active_workers[path] = MagicMock()

            # Keep only album1 and album4
            keep = {"/music/album1", "/music/album4"}
            loader.cancel_all_except(keep)

            assert "/music/album1" in loader._pending
            assert "/music/album2" not in loader._pending
            assert "/music/album3" not in loader._pending
            assert "/music/album4" in loader._active_workers
            assert "/music/album5" not in loader._active_workers

    def test_invalidate_cache(self):
        """Test invalidate_cache removes specific item."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool"):
            loader = ThumbnailLoader()

            loader._cache.put("/music/album1", MagicMock())
            loader._cache.put("/music/album2", MagicMock())

            loader.invalidate_cache("/music/album1")

            assert loader._cache.get("/music/album1") is None
            assert loader._cache.get("/music/album2") is not None

    def test_clear_cache(self):
        """Test clear_cache removes all items."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool"):
            loader = ThumbnailLoader()

            loader._cache.put("/music/album1", MagicMock())
            loader._cache.put("/music/album2", MagicMock())

            loader.clear_cache()

            assert loader._cache.size() == 0

    def test_shutdown_clears_state(self):
        """Test shutdown clears pending and active workers."""
        from src.ui.widgets.thumbnail_loader import LoadRequest, ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()

            album = MagicMock(spec=AlbumInfo)

            # Add pending request
            loader._pending["/music/album1"] = LoadRequest(
                album_path="/music/album1",
                album=album,
                size=150,
            )

            # Add active worker
            mock_worker = MagicMock()
            loader._active_workers["/music/album2"] = mock_worker

            loader.shutdown()

            assert len(loader._pending) == 0
            assert len(loader._active_workers) == 0
            mock_worker.cancel.assert_called_once()
            mock_pool.waitForDone.assert_called_once_with(1000)
            mock_pool.clear.assert_called_once()

    def test_process_queue_respects_max_threads(self):
        """Test _process_queue respects max thread count."""
        from src.ui.widgets.thumbnail_loader import LoadRequest, ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 2
            mock_pool.activeThreadCount.return_value = 2  # All slots busy
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()

            album = MagicMock(spec=AlbumInfo)
            loader._pending["/music/album1"] = LoadRequest(
                album_path="/music/album1",
                album=album,
                size=150,
            )

            loader._process_queue()

            # Should not start new worker when all slots busy
            mock_pool.start.assert_not_called()

    def test_process_queue_prioritizes_high_priority(self):
        """Test _process_queue processes high priority first."""
        from src.ui.widgets.thumbnail_loader import LoadRequest, ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 1  # Only 1 slot
            mock_pool.activeThreadCount.return_value = 0
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()

            album = MagicMock(spec=AlbumInfo)

            # Add low priority
            loader._pending["/music/low"] = LoadRequest(
                album_path="/music/low",
                album=album,
                size=150,
                priority=1,
            )

            # Add high priority
            loader._pending["/music/high"] = LoadRequest(
                album_path="/music/high",
                album=album,
                size=150,
                priority=10,
            )

            loader._process_queue()

            # High priority should be processed first and removed from pending
            assert "/music/high" not in loader._pending
            assert "/music/low" in loader._pending


class TestThumbnailLoaderInit:
    """Tests for ThumbnailLoader initialization."""

    def test_init_default_values(self):
        """Test default initialization values."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()

            mock_pool.setMaxThreadCount.assert_called_once_with(2)
            assert loader._cache.max_size == 200

    def test_init_custom_values(self):
        """Test custom initialization values."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader(max_workers=4, cache_size=500)

            mock_pool.setMaxThreadCount.assert_called_once_with(4)
            assert loader._cache.max_size == 500


class TestOnLoadedCallback:
    """Tests for _on_loaded callback."""

    def test_on_loaded_caches_pixmap(self):
        """Test _on_loaded caches the pixmap."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 2
            mock_pool.activeThreadCount.return_value = 0
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()
            loader.thumbnail_ready = MagicMock()

            # Add a fake active worker
            loader._active_workers["/music/album"] = MagicMock()

            mock_pixmap = MagicMock()
            loader._on_loaded("/music/album", mock_pixmap)

            assert loader._cache.get("/music/album") == mock_pixmap
            assert "/music/album" not in loader._active_workers

    def test_on_loaded_emits_signal(self):
        """Test _on_loaded emits thumbnail_ready signal."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 2
            mock_pool.activeThreadCount.return_value = 0
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()
            loader.thumbnail_ready = MagicMock()
            loader._active_workers["/music/album"] = MagicMock()

            mock_pixmap = MagicMock()
            loader._on_loaded("/music/album", mock_pixmap)

            loader.thumbnail_ready.emit.assert_called_once_with("/music/album", mock_pixmap)


class TestOnErrorCallback:
    """Tests for _on_error callback."""

    def test_on_error_removes_active_worker(self):
        """Test _on_error removes the active worker."""
        from src.ui.widgets.thumbnail_loader import ThumbnailLoader

        with patch("src.ui.widgets.thumbnail_loader.QThreadPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool.maxThreadCount.return_value = 2
            mock_pool.activeThreadCount.return_value = 0
            mock_pool_class.return_value = mock_pool

            loader = ThumbnailLoader()
            loader._active_workers["/music/album"] = MagicMock()

            loader._on_error("/music/album", "Test error")

            assert "/music/album" not in loader._active_workers
