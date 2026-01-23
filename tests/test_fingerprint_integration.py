"""
Integration tests for batch fingerprinting workflow.

Tests the complete flow from album analysis to result selection,
including the interaction between components.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6 import __version__ as PYSIDE6_VERSION
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.core.fingerprint_batch import (
    AggregatedResult,
    BatchFingerprinter,
    BatchFingerprintResult,
    FingerprintMatch,
)
from src.core.identification_service import IdentificationService
from src.ui.fingerprint_dialog import FingerprintResultsDialog

# PySide6 6.9+ has a known segfault bug when connecting signals in certain
# widget configurations. Skip affected tests on these versions.
# See: https://github.com/spyder-ide/spyder/issues/24825
PYSIDE6_MAJOR_MINOR = tuple(map(int, PYSIDE6_VERSION.split(".")[:2]))
SKIP_PYSIDE6_DIALOG_TESTS = PYSIDE6_MAJOR_MINOR >= (6, 9)


@pytest.fixture
def mock_album(tmp_path):
    """Create a mock album with tracks.

    Uses real Path objects to avoid PySide6 segfaults with MagicMock magic methods.
    """
    album_path = tmp_path / "TestAlbum"
    album_path.mkdir()

    album = MagicMock()
    album.path = album_path
    album.display_name = "Test Album - Test Artist"
    album.track_count = 10

    # Create real track files and mock track objects
    tracks = []
    for i in range(10):
        track_path = album_path / f"track{i + 1}.mp3"
        track_path.write_bytes(b"fake audio data")  # Create real file

        track = MagicMock()
        track.path = track_path  # Use real Path object
        tracks.append(track)

    album.tracks = tracks
    return album


@pytest.fixture
def mock_fingerprint_result(mock_album):
    """Create a mock BatchFingerprintResult with aggregated results.

    Uses paths from mock_album for consistency with dialog tests.
    """
    album_path = mock_album.path
    tracks = mock_album.tracks

    # Create matches for first result (majority) - tracks 1, 2, 3
    matches1 = [
        FingerprintMatch(
            track_path=tracks[i].path,
            track_name=tracks[i].path.name,
            recording_id=f"rec-{i + 1}",
            title=f"Track {i + 1}",
            artist="Test Artist",
            album="Test Album",
            year=2020,
            mbid="mbid-release-123",
            score=0.95 - (i * 0.02),
        )
        for i in range(3)  # 3 matches
    ]

    # Create matches for second result (minority) - track 4
    matches2 = [
        FingerprintMatch(
            track_path=tracks[3].path,
            track_name=tracks[3].path.name,
            recording_id="rec-4",
            title="Track 4",
            artist="Other Artist",
            album="Other Album",
            year=2019,
            mbid="mbid-release-456",
            score=0.85,
        )
    ]

    result1 = AggregatedResult(
        mbid="mbid-release-123",
        title="Track 1",
        artist="Test Artist",
        album="Test Album",
        year=2020,
        matches=matches1,
    )

    result2 = AggregatedResult(
        mbid="mbid-release-456",
        title="Track 4",
        artist="Other Artist",
        album="Other Album",
        year=2019,
        matches=matches2,
    )

    return BatchFingerprintResult(
        album_path=album_path,
        total_tracks=10,
        analyzed_tracks=4,
        failed_tracks=0,
        results=[result1, result2],
        analyzed_paths={tracks[i].path for i in range(4)},
    )


class TestIdentificationServiceIntegration:
    """Integration tests for IdentificationService with batch fingerprinting."""

    def test_identification_service_has_batch_fingerprinter(self):
        """Test that IdentificationService has batch_fingerprinter property."""
        service = IdentificationService()

        # Access the batch_fingerprinter property (lazy init)
        batch_fp = service.batch_fingerprinter

        assert batch_fp is not None
        assert isinstance(batch_fp, BatchFingerprinter)

    def test_batch_fingerprint_method(self, mock_album):
        """Test batch_fingerprint method."""
        # Create a mock fingerprinter with both identify() and fingerprint()/lookup()
        mock_fp = MagicMock()
        mock_fp.is_available = True
        mock_fp.is_configured = True
        mock_fp.identify.return_value = [
            {"score": 0.9, "mbid": "mbid-123", "title": "Track", "artist": "Artist"}
        ]
        # Also mock fingerprint() and lookup() for parallel mode
        mock_fp.fingerprint.return_value = (180.5, "FINGERPRINT")
        mock_fp.lookup.return_value = [
            {"score": 0.9, "mbid": "mbid-123", "title": "Track", "artist": "Artist"}
        ]

        service = IdentificationService(fingerprinter=mock_fp)

        with patch.object(Path, "exists", return_value=True):
            result = service.batch_fingerprint(mock_album)

        assert isinstance(result, BatchFingerprintResult)

    def test_batch_fingerprint_with_callback(self, mock_album):
        """Test batch_fingerprint with progress callback."""
        mock_fp = MagicMock()
        mock_fp.is_available = True
        mock_fp.is_configured = True
        mock_fp.identify.return_value = [
            {"score": 0.9, "mbid": "mbid-123", "title": "Track", "artist": "Artist"}
        ]
        # Also mock fingerprint() and lookup() for parallel mode
        mock_fp.fingerprint.return_value = (180.5, "FINGERPRINT")
        mock_fp.lookup.return_value = [
            {"score": 0.9, "mbid": "mbid-123", "title": "Track", "artist": "Artist"}
        ]

        service = IdentificationService(fingerprinter=mock_fp)

        progress_callback = MagicMock()

        with patch.object(Path, "exists", return_value=True):
            service.batch_fingerprint(mock_album, progress_callback=progress_callback)

        # Progress callback should have been called
        # (The BatchFingerprinter will call it during analysis)

    def test_batch_fingerprint_more_method(self, mock_album, mock_fingerprint_result):
        """Test batch_fingerprint_more method."""
        mock_fp = MagicMock()
        mock_fp.is_available = True
        mock_fp.is_configured = True
        mock_fp.identify.return_value = [
            {"score": 0.9, "mbid": "mbid-123", "title": "Track", "artist": "Artist"}
        ]
        # Also mock fingerprint() and lookup() for parallel mode
        mock_fp.fingerprint.return_value = (180.5, "FINGERPRINT")
        mock_fp.lookup.return_value = [
            {"score": 0.9, "mbid": "mbid-123", "title": "Track", "artist": "Artist"}
        ]

        service = IdentificationService(fingerprinter=mock_fp)

        with patch.object(Path, "exists", return_value=True):
            result = service.batch_fingerprint_more(mock_album, mock_fingerprint_result)

        assert isinstance(result, BatchFingerprintResult)


@pytest.mark.skipif(
    SKIP_PYSIDE6_DIALOG_TESTS,
    reason="PySide6 6.9+ segfault during signal connection - known issue, see: "
    "https://github.com/spyder-ide/spyder/issues/24825",
)
class TestFingerprintDialogIntegration:
    """Integration tests for FingerprintResultsDialog.

    NOTE: These tests are skipped due to a segfault in PySide6 6.9+ when
    connecting signals in certain widget configurations. The FingerprintResultsDialog
    has been manually verified to work correctly in the GUI.
    See: https://github.com/spyder-ide/spyder/issues/24825
    """

    def test_dialog_displays_results(self, qtbot, mock_album, mock_fingerprint_result):
        """Test that dialog properly displays fingerprint results."""
        with patch.object(FingerprintResultsDialog, "_start_cover_fetch"):
            dialog = FingerprintResultsDialog(
                album=mock_album,
                batch_result=mock_fingerprint_result,
            )
            qtbot.addWidget(dialog)

            # Should have result widgets for each result
            assert len(dialog._result_widgets) == 2

            # First result widget should have its radio checked (highest vote count)
            assert dialog._result_widgets[0].radio.isChecked()

            # Verify result info is displayed
            # The first result has 3 votes, second has 1
            assert mock_fingerprint_result.results[0].vote_count == 3
            assert mock_fingerprint_result.results[1].vote_count == 1

    def test_dialog_selection_emits_signal(self, qtbot, mock_album, mock_fingerprint_result):
        """Test that selecting a result and confirming emits the correct signal."""
        with patch.object(FingerprintResultsDialog, "_start_cover_fetch"):
            dialog = FingerprintResultsDialog(
                album=mock_album,
                batch_result=mock_fingerprint_result,
            )
            qtbot.addWidget(dialog)

            # Set up signal spy
            with qtbot.waitSignal(dialog.result_selected, timeout=1000) as blocker:
                # Select second option
                dialog._result_widgets[1].radio.setChecked(True)

                # Emit the signal by simulating select button click
                dialog._select_btn.click()

            # Verify the correct result was emitted
            emitted_result = blocker.args[0]
            assert emitted_result.mbid == "mbid-release-456"

    def test_dialog_none_match_emits_signal(self, qtbot, mock_album, mock_fingerprint_result):
        """Test that 'None match' button emits the none_selected signal."""
        with patch.object(FingerprintResultsDialog, "_start_cover_fetch"):
            dialog = FingerprintResultsDialog(
                album=mock_album,
                batch_result=mock_fingerprint_result,
            )
            qtbot.addWidget(dialog)

            # Set up signal spy for none_selected
            with qtbot.waitSignal(dialog.none_selected, timeout=1000):
                dialog._none_match_btn.click()

    def test_dialog_scan_more_emits_signal(self, qtbot, mock_album, mock_fingerprint_result):
        """Test that 'Scan More' button emits the scan_more_requested signal."""
        with patch.object(FingerprintResultsDialog, "_start_cover_fetch"):
            dialog = FingerprintResultsDialog(
                album=mock_album,
                batch_result=mock_fingerprint_result,
            )
            qtbot.addWidget(dialog)

            # Set up signal spy
            with qtbot.waitSignal(dialog.scan_more_requested, timeout=1000):
                dialog._scan_more_btn.click()


class TestBatchFingerprintWorkflow:
    """End-to-end workflow tests for batch fingerprinting."""

    def test_complete_workflow_with_clear_winner(self, mock_album):
        """Test complete workflow when one result has clear majority."""
        # Create a mock fingerprinter
        mock_fp = MagicMock()
        mock_fp.identify.return_value = [
            {"score": 0.95, "mbid": "mbid-winner", "title": "Track", "artist": "Artist"}
        ]

        batch_fp = BatchFingerprinter(fingerprinter=mock_fp, parallel=False)

        # Analyze the album
        with patch.object(Path, "exists", return_value=True):
            result = batch_fp.analyze_album(mock_album)

        # Should have results
        assert result.has_results

        # Best result should have the most votes
        best = result.best_result
        assert best is not None
        assert best.mbid == "mbid-winner"

    def test_complete_workflow_with_mixed_results(self, mock_album):
        """Test workflow when tracks match different albums."""
        mock_fp = MagicMock()

        # Alternate between two different albums
        responses = [
            [{"score": 0.9, "mbid": "mbid-A", "title": "Track", "artist": "Artist A"}],
            [{"score": 0.85, "mbid": "mbid-B", "title": "Track", "artist": "Artist B"}],
            [{"score": 0.92, "mbid": "mbid-A", "title": "Track", "artist": "Artist A"}],
            [{"score": 0.88, "mbid": "mbid-B", "title": "Track", "artist": "Artist B"}],
        ]
        mock_fp.identify.side_effect = responses

        batch_fp = BatchFingerprinter(
            fingerprinter=mock_fp,
            min_floor=4,
            max_cap=4,
            parallel=False,
        )

        with patch.object(Path, "exists", return_value=True):
            result = batch_fp.analyze_album(mock_album)

        # Should have 2 different results
        assert len(result.results) == 2

        # Each should have 2 votes
        for r in result.results:
            assert r.vote_count == 2

    def test_workflow_with_failures(self, mock_album):
        """Test workflow when some tracks fail to fingerprint."""
        mock_fp = MagicMock()

        # Mix of successes and failures
        mock_fp.identify.side_effect = [
            None,  # Fail
            [{"score": 0.9, "mbid": "mbid-1", "title": "Track", "artist": "Artist"}],
            None,  # Fail
            [{"score": 0.9, "mbid": "mbid-1", "title": "Track", "artist": "Artist"}],
        ]

        batch_fp = BatchFingerprinter(
            fingerprinter=mock_fp,
            min_floor=2,  # Want 2 successful
            max_cap=4,
            parallel=False,
        )

        with patch.object(Path, "exists", return_value=True):
            result = batch_fp.analyze_album(mock_album)

        # Should have 2 successful analyses and 2 failures
        assert result.analyzed_tracks == 2
        assert result.failed_tracks == 2
        assert result.has_results

    def test_workflow_scan_more_adds_results(self, mock_album):
        """Test that scan_more adds new tracks to existing results."""
        mock_fp = MagicMock()
        mock_fp.identify.return_value = [
            {"score": 0.9, "mbid": "mbid-1", "title": "Track", "artist": "Artist"}
        ]

        batch_fp = BatchFingerprinter(
            fingerprinter=mock_fp,
            min_floor=2,
            max_cap=2,
            additional_count=2,
            parallel=False,
        )

        # Initial analysis
        with patch.object(Path, "exists", return_value=True):
            result1 = batch_fp.analyze_album(mock_album)

        initial_analyzed = len(result1.analyzed_paths)

        # Scan more
        with patch.object(Path, "exists", return_value=True):
            result2 = batch_fp.analyze_more(mock_album, result1)

        # Should have more analyzed tracks
        assert len(result2.analyzed_paths) > initial_analyzed


class TestCacheIntegration:
    """Integration tests for fingerprint caching."""

    def test_cache_prevents_redundant_fingerprinting(self):
        """Test that cache prevents redundant fingerprint calculations."""
        from src.core.fingerprint_cache import FingerprintCache

        cache = FingerprintCache()

        # Create a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test audio data")

        try:
            # First call: set fingerprint
            cache.set_fingerprint(filepath, 180.5, "FINGERPRINT123")

            # Second call: should return cached value
            result = cache.get_fingerprint(filepath)

            assert result is not None
            assert result == (180.5, "FINGERPRINT123")

            # Verify cache hit
            stats = cache.get_stats()
            assert stats["fingerprint_hits"] == 1
        finally:
            filepath.unlink()

    def test_cache_invalidates_on_file_change(self):
        """Test that cache invalidates when file is modified."""
        import time

        from src.core.fingerprint_cache import FingerprintCache

        cache = FingerprintCache()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            filepath = Path(f.name)
            f.write(b"original data")

        try:
            # Cache the fingerprint
            cache.set_fingerprint(filepath, 180.5, "FINGERPRINT_V1")

            # Modify the file
            time.sleep(0.1)  # Ensure mtime changes
            filepath.write_bytes(b"modified data")

            # Should return None (cache miss due to mtime)
            result = cache.get_fingerprint(filepath)
            assert result is None
        finally:
            filepath.unlink()

    def test_lookup_cache_works(self):
        """Test that lookup results are cached."""
        from src.core.fingerprint_cache import FingerprintCache

        cache = FingerprintCache()

        results = [{"score": 0.95, "mbid": "mbid-123", "title": "Test"}]

        # Cache lookup result
        cache.set_lookup("FINGERPRINT123", 180.5, results)

        # Retrieve from cache
        cached = cache.get_lookup("FINGERPRINT123", 180.5)

        assert cached == results

        stats = cache.get_stats()
        assert stats["lookup_hits"] == 1


class TestUseCoverFeature:
    """Tests for the 'Use this cover' feature in fingerprint results."""

    def test_result_widget_stores_cover_data(self, qtbot, mock_fingerprint_result):
        """Test that ResultItemWidget stores cover data when set_cover is called."""
        from src.ui.fingerprint_dialog import ResultItemWidget

        result = mock_fingerprint_result.results[0]
        widget = ResultItemWidget(result)
        qtbot.addWidget(widget)

        # Initially no cover data
        assert widget._cover_data is None

        # Set cover data
        test_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Fake PNG header
        widget.set_cover(test_data)

        # Cover data should be stored
        assert widget._cover_data == test_data

    def test_result_widget_shows_use_cover_button_when_cover_loaded(
        self, qtbot, mock_fingerprint_result
    ):
        """Test that 'Use this cover' button becomes visible when cover is loaded."""
        from src.ui.fingerprint_dialog import ResultItemWidget

        result = mock_fingerprint_result.results[0]
        widget = ResultItemWidget(result)
        qtbot.addWidget(widget)

        # Button should be hidden initially (use isHidden since widget not shown)
        assert widget._use_cover_btn is not None
        assert widget._use_cover_btn.isHidden()

        # Set cover data (data is stored even if image load fails)
        test_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        widget.set_cover(test_data)

        # Button should now be not hidden (visible when parent is shown)
        assert not widget._use_cover_btn.isHidden()

    def test_result_widget_hides_button_on_no_cover(self, qtbot, mock_fingerprint_result):
        """Test that 'Use this cover' button is hidden when set_no_cover is called."""
        from src.ui.fingerprint_dialog import ResultItemWidget

        result = mock_fingerprint_result.results[0]
        widget = ResultItemWidget(result)
        qtbot.addWidget(widget)

        # First set cover, then clear it
        test_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        widget.set_cover(test_data)
        assert not widget._use_cover_btn.isHidden()

        # Clear cover
        widget.set_no_cover()

        # Button should be hidden and data cleared
        assert widget._use_cover_btn.isHidden()
        assert widget._cover_data is None

    def test_result_widget_emits_cover_use_requested_signal(self, qtbot, mock_fingerprint_result):
        """Test that clicking 'Use this cover' emits the correct signal."""
        from src.ui.fingerprint_dialog import ResultItemWidget

        result = mock_fingerprint_result.results[0]
        widget = ResultItemWidget(result)
        qtbot.addWidget(widget)

        # Set cover data
        test_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        widget.set_cover(test_data)

        # Set up signal spy
        with qtbot.waitSignal(widget.cover_use_requested, timeout=1000) as blocker:
            widget._use_cover_btn.click()

        # Verify signal args
        emitted_result, emitted_data = blocker.args
        assert emitted_result == result
        assert emitted_data == test_data

    @pytest.mark.skipif(
        SKIP_PYSIDE6_DIALOG_TESTS,
        reason="PySide6 6.9+ segfault in FingerprintResultsDialog - see TestFingerprintDialogIntegration",
    )
    def test_dialog_emits_cover_selected_signal(self, qtbot, mock_album, mock_fingerprint_result):
        """Test that dialog emits cover_selected when 'Use this cover' is clicked."""
        with patch.object(FingerprintResultsDialog, "_start_cover_fetch"):
            dialog = FingerprintResultsDialog(
                album=mock_album,
                batch_result=mock_fingerprint_result,
            )
            qtbot.addWidget(dialog)

            # Simulate cover being loaded for first result
            test_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            dialog._result_widgets[0].set_cover(test_data)

            # Set up signal spy
            with qtbot.waitSignal(dialog.cover_selected, timeout=1000) as blocker:
                dialog._result_widgets[0]._use_cover_btn.click()

            # Verify signal args
            emitted_result, emitted_data = blocker.args
            assert emitted_result.mbid == "mbid-release-123"
            assert emitted_data == test_data
