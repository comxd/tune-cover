"""
Integration tests for UI error handling with pytest-qt.

These tests verify that errors from API providers are properly displayed
in the search panel UI.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt

from src.api.base import handle_network_errors
from src.core.exceptions import NetworkError, RateLimitError


class TestSearchPanelConnectionStatus:
    """Test connection status display in the search panel."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a mock config for testing."""
        from src.utils.config import Config

        config_path = tmp_path / "config.json"
        config = Config(config_path)
        return config

    @pytest.fixture
    def mock_album(self):
        """Create a mock album for testing."""
        from pathlib import Path

        from src.core.models import AlbumInfo

        album = AlbumInfo(
            path=Path("/tmp/test_album"),
            artist="Test Artist",
            album="Test Album",
            year="2020",
        )
        return album

    @pytest.fixture
    def search_panel(self, qtbot, mock_album, mock_config):
        """Create a SearchPanel widget for testing."""
        from src.ui.search_panel import SearchPanel

        # Patch fingerprinting to avoid fpcalc issues in tests
        with patch("src.ui.search_panel.is_fingerprinting_available", return_value=False):
            panel = SearchPanel(mock_album, mock_config)
            qtbot.addWidget(panel)
            return panel

    def test_connection_status_label_exists(self, search_panel):
        """Test that connection status label exists in the panel."""
        assert hasattr(search_panel, "connection_status_label")
        assert search_panel.connection_status_label is not None

    def test_connection_status_initially_hidden(self, search_panel):
        """Test that connection status label is initially hidden."""
        assert not search_panel.connection_status_label.isVisible()

    def test_network_error_shows_red_status(self, search_panel):
        """Test that NetworkError displays red status label."""
        # Simulate connection_status signal with error
        search_panel._on_connection_status("Connection failed to musicbrainz.org", True)

        assert search_panel.connection_status_label.isVisible()
        assert "Connection failed" in search_panel.connection_status_label.text()
        # Check red styling
        style = search_panel.connection_status_label.styleSheet()
        assert "#ff6b6b" in style

    def test_rate_limit_error_shows_retry_info(self, search_panel):
        """Test that RateLimitError displays retry countdown."""
        search_panel._on_connection_status(
            "Rate limit exceeded on api.discogs.com (retry in 60s)", True
        )

        assert search_panel.connection_status_label.isVisible()
        assert "Rate limit" in search_panel.connection_status_label.text()
        assert "60s" in search_panel.connection_status_label.text()
        # Check error styling (red)
        style = search_panel.connection_status_label.styleSheet()
        assert "#ff6b6b" in style

    def test_timeout_error_shows_timeout_message(self, search_panel):
        """Test that timeout errors display appropriate message."""
        search_panel._on_connection_status("Connection timeout to musicbrainz.org", True)

        assert search_panel.connection_status_label.isVisible()
        assert "timeout" in search_panel.connection_status_label.text().lower()
        # Check error styling
        style = search_panel.connection_status_label.styleSheet()
        assert "#ff6b6b" in style

    def test_success_shows_green_status(self, search_panel):
        """Test that successful connection shows green status."""
        search_panel._on_connection_status("Connected to musicbrainz.org", False)

        assert search_panel.connection_status_label.isVisible()
        style = search_panel.connection_status_label.styleSheet()
        assert "#69db7c" in style

    def test_error_then_success_updates_color(self, search_panel):
        """Test that status color updates when state changes."""
        # First show error (red)
        search_panel._on_connection_status("Connection failed", True)
        style = search_panel.connection_status_label.styleSheet()
        assert "#ff6b6b" in style

        # Then show success (green)
        search_panel._on_connection_status("Connected", False)
        style = search_panel.connection_status_label.styleSheet()
        assert "#69db7c" in style


class TestSearchWorkerErrorSignals:
    """Test that SearchWorker emits correct error signals."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock provider that raises exceptions."""
        provider = Mock()
        provider.name = "TestProvider"
        provider.api_host = "test.example.com"
        return provider

    def test_worker_emits_error_on_network_failure(self, qtbot, mock_provider):
        """Test that SearchWorker emits error signal on NetworkError."""
        from src.ui.search_panel import SearchWorker

        mock_provider.search.side_effect = NetworkError("Connection failed")

        worker = SearchWorker(
            provider=mock_provider,
            artist="Test",
            album="Album",
            year=None,
            musicbrainz_albumid=None,
        )

        error_received = []
        worker.error.connect(lambda msg: error_received.append(msg))

        with qtbot.waitSignal(worker.error, timeout=5000):
            worker.run()

        assert len(error_received) == 1
        assert "Connection failed" in error_received[0]

    def test_worker_emits_connection_status_on_rate_limit(self, qtbot, mock_provider):
        """Test that SearchWorker emits connection_status on RateLimitError."""
        from src.ui.search_panel import SearchWorker

        mock_provider.search.side_effect = RateLimitError(
            "Rate limit exceeded", retry_after=30
        )

        worker = SearchWorker(
            provider=mock_provider,
            artist="Test",
            album="Album",
            year=None,
            musicbrainz_albumid=None,
        )

        status_received = []
        worker.connection_status.connect(
            lambda msg, is_err: status_received.append((msg, is_err))
        )

        with qtbot.waitSignal(worker.connection_status, timeout=5000):
            worker.run()

        # Should have at least one error status
        error_statuses = [s for s in status_received if s[1] is True]
        assert len(error_statuses) >= 1
        msg, is_error = error_statuses[-1]
        assert is_error is True
        # Check that message contains retry info
        assert "30" in msg or "Rate limit" in msg

    def test_worker_emits_connection_status_on_timeout(self, qtbot, mock_provider):
        """Test that SearchWorker emits connection_status on timeout."""
        from src.ui.search_panel import SearchWorker

        mock_provider.search.side_effect = NetworkError("Request timed out")

        worker = SearchWorker(
            provider=mock_provider,
            artist="Test",
            album="Album",
            year=None,
            musicbrainz_albumid=None,
        )

        status_received = []
        worker.connection_status.connect(
            lambda msg, is_err: status_received.append((msg, is_err))
        )

        with qtbot.waitSignal(worker.connection_status, timeout=5000):
            worker.run()

        # Find the error status
        error_statuses = [s for s in status_received if s[1] is True]
        assert len(error_statuses) >= 1
        msg, is_error = error_statuses[-1]
        assert is_error is True
        assert "timeout" in msg.lower()

    def test_worker_emits_success_status_on_success(self, qtbot, mock_provider):
        """Test that SearchWorker emits success connection_status on success."""
        from src.core.models import SearchResult
        from src.ui.search_panel import SearchWorker

        # Mock successful search
        mock_provider.search.return_value = [
            SearchResult(
                provider="TestProvider",
                mbid="test-123",
                artist="Test Artist",
                album="Test Album",
                score=95,
            )
        ]

        worker = SearchWorker(
            provider=mock_provider,
            artist="Test",
            album="Album",
            year=None,
            musicbrainz_albumid=None,
        )

        status_received = []
        worker.connection_status.connect(
            lambda msg, is_err: status_received.append((msg, is_err))
        )

        with qtbot.waitSignal(worker.results_ready, timeout=5000):
            worker.run()

        # Should have a success status (is_error=False)
        success_statuses = [s for s in status_received if s[1] is False]
        assert len(success_statuses) >= 1


class TestCircuitBreakerUIIntegration:
    """Test circuit breaker behavior in UI context."""

    def test_circuit_open_shows_unavailable_message(self, qtbot):
        """Test that circuit open state shows appropriate message in UI."""
        from src.api.circuit_breaker import CircuitBreakerRegistry, CircuitState
        from src.core.exceptions import NetworkError

        # Get a fresh breaker and open it
        registry = CircuitBreakerRegistry()
        registry._breakers.pop("UITestProvider", None)
        breaker = registry.get_breaker("UITestProvider", failure_threshold=1)
        breaker.record_failure()  # Open the circuit

        assert breaker.state == CircuitState.OPEN

        # Now trying to use handle_network_errors should raise immediately
        with pytest.raises(NetworkError) as exc_info:
            with handle_network_errors("UITestProvider"):
                pass  # Should not reach here

        assert "circuit open" in str(exc_info.value).lower()
        assert "temporarily unavailable" in str(exc_info.value).lower()

    def test_metrics_recorded_for_ui_operations(self):
        """Test that metrics are recorded during UI operations."""
        import requests

        from src.api.metrics import MetricsRegistry
        from src.core.exceptions import NetworkError

        registry = MetricsRegistry()
        metrics = registry.get_metrics("UIMetricsTestProvider")
        metrics.reset()

        # Simulate a failed request
        try:
            with handle_network_errors("UIMetricsTestProvider"):
                raise requests.exceptions.ConnectionError("Test error")
        except NetworkError:
            pass

        assert metrics.requests_total == 1
        assert metrics.requests_failed == 1
        assert metrics.success_rate == 0.0


class TestErrorMessageTranslation:
    """Test that error messages use the translation system."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a mock config for testing."""
        from src.utils.config import Config

        config_path = tmp_path / "config.json"
        config = Config(config_path)
        return config

    @pytest.fixture
    def mock_album(self):
        """Create a mock album for testing."""
        from pathlib import Path

        from src.core.models import AlbumInfo

        album = AlbumInfo(
            path=Path("/tmp/test_album"),
            artist="Test Artist",
            album="Test Album",
        )
        return album

    def test_search_error_uses_translation(self, qtbot, mock_album, mock_config):
        """Test that search error messages use tr() for translation."""
        from src.ui.search_panel import SearchPanel

        with patch("src.ui.search_panel.is_fingerprinting_available", return_value=False):
            panel = SearchPanel(mock_album, mock_config)
            qtbot.addWidget(panel)

            # Simulate an error
            panel._on_search_error("connection error")

            # Check that the no_results_label was updated with a user-friendly message
            label_text = panel.no_results_label.text()
            # The message should be user-friendly, not the raw error
            assert "error" in label_text.lower() or "connection" in label_text.lower()


class TestClearResultsTimerSafety:
    """
    Regression test for crash: QObject::killTimer: Timers cannot be stopped from another thread.

    Bug: When clearing search results, CoverResultCard widgets with active LoadingSpinner
    QTimers were scheduled for deletion via deleteLater() without stopping their timers first.
    This caused Qt to crash when the timers were destroyed on the wrong thread.

    Fix: _clear_results() now calls stop_loading() on each CoverResultCard before deleteLater()
    to ensure all QTimers are stopped on the main thread before widget destruction.
    """

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a mock config for testing."""
        from src.utils.config import Config

        config_path = tmp_path / "config.json"
        config = Config(config_path)
        return config

    @pytest.fixture
    def mock_album(self):
        """Create a mock album for testing."""
        from pathlib import Path

        from src.core.models import AlbumInfo

        album = AlbumInfo(
            path=Path("/tmp/test_album"),
            artist="Test Artist",
            album="Test Album",
        )
        return album

    @pytest.fixture
    def search_panel(self, qtbot, mock_album, mock_config):
        """Create a SearchPanel widget for testing."""
        from src.ui.search_panel import SearchPanel

        with patch("src.ui.search_panel.is_fingerprinting_available", return_value=False):
            panel = SearchPanel(mock_album, mock_config)
            qtbot.addWidget(panel)
            return panel

    def test_clear_results_stops_spinners_before_deletion(self, search_panel, qtbot):
        """
        Regression test: _clear_results() must stop active spinners before deleteLater().

        Without this fix, the app crashes with:
        QObject::killTimer: Timers cannot be stopped from another thread
        """
        from src.core.models import SearchResult
        from src.ui.search_panel import CoverResultCard

        # Simulate search results being displayed (cards with active spinners)
        results = [
            SearchResult(
                provider="TestProvider",
                mbid=f"test-{i}",
                artist="AC/DC",
                album="For those about to rock",
                score=90 - i,
            )
            for i in range(3)
        ]

        # Add cards to the results grid (simulating _on_results_ready)
        for i, result in enumerate(results):
            card = CoverResultCard(i, result)
            search_panel.result_cards.append(card)
            search_panel.results_grid.addWidget(card, 0, i)

        # Verify spinners are active before clearing
        for card in search_panel.result_cards:
            assert card.spinner.is_spinning(), "Spinner should be active before clear"

        # Store references to verify spinners are stopped
        old_cards = list(search_panel.result_cards)

        # Clear results - this should stop all spinners before deleteLater()
        search_panel._clear_results()

        # Verify all spinners were stopped
        for card in old_cards:
            assert not card.spinner.is_spinning(), (
                "Spinner must be stopped before widget deletion to prevent "
                "QObject::killTimer crash from another thread"
            )

    def test_start_search_disconnects_before_clear(self, search_panel):
        """
        Regression test: _start_search() must disconnect old worker signals and cancel
        thumbnail loading before clearing results, to prevent stale signal delivery
        to already-deleted widgets.
        """

        # Track the order of operations
        call_order = []

        original_disconnect = search_panel._disconnect_workers
        original_clear = search_panel._clear_results

        def tracked_disconnect():
            call_order.append("disconnect_workers")
            original_disconnect()

        def tracked_clear():
            call_order.append("clear_results")
            original_clear()

        search_panel._disconnect_workers = tracked_disconnect
        search_panel._clear_results = tracked_clear

        # Set up a mock active provider
        mock_provider = MagicMock()
        mock_provider.name = "TestProvider"
        search_panel._active_provider = mock_provider

        # Set search fields so _start_search proceeds
        search_panel.artist_input.setText("Test Artist")

        # Mock SearchWorker to prevent actual thread creation
        with patch("src.ui.search_panel.SearchWorker") as MockWorker:
            mock_worker = MagicMock()
            MockWorker.return_value = mock_worker

            search_panel._start_search()

        # Verify disconnect happens BEFORE clear_results
        assert "disconnect_workers" in call_order, "disconnect_workers should be called"
        assert "clear_results" in call_order, "clear_results should be called"
        disconnect_idx = call_order.index("disconnect_workers")
        clear_idx = call_order.index("clear_results")
        assert disconnect_idx < clear_idx, (
            "disconnect_workers must be called before clear_results to prevent "
            "stale signals from reaching deleted widgets"
        )
