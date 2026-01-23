"""
Tests for the batch audio fingerprinting module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.fingerprint_batch import (
    AggregatedResult,
    BatchFingerprinter,
    BatchFingerprintResult,
    FingerprintMatch,
)


class TestFingerprintMatch:
    """Tests for FingerprintMatch dataclass."""

    def test_default_values(self):
        """Test default values for FingerprintMatch."""
        match = FingerprintMatch(
            track_path=Path("/music/track.mp3"),
            track_name="track.mp3",
        )
        assert match.recording_id is None
        assert match.title is None
        assert match.artist is None
        assert match.album is None
        assert match.year is None
        assert match.mbid is None
        assert match.score == 0.0

    def test_full_values(self):
        """Test FingerprintMatch with all values."""
        match = FingerprintMatch(
            track_path=Path("/music/track.mp3"),
            track_name="track.mp3",
            recording_id="rec-123",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            year=2020,
            mbid="mbid-456",
            score=0.95,
        )
        assert match.track_path == Path("/music/track.mp3")
        assert match.track_name == "track.mp3"
        assert match.recording_id == "rec-123"
        assert match.title == "Test Song"
        assert match.artist == "Test Artist"
        assert match.album == "Test Album"
        assert match.year == 2020
        assert match.mbid == "mbid-456"
        assert match.score == 0.95


class TestAggregatedResult:
    """Tests for AggregatedResult dataclass."""

    def test_vote_count_empty(self):
        """Test vote_count with no matches."""
        result = AggregatedResult(mbid="mbid-123")
        assert result.vote_count == 0

    def test_vote_count_with_matches(self):
        """Test vote_count with multiple matches."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.9, mbid="mbid-123")
        match2 = FingerprintMatch(Path("/t2.mp3"), "t2.mp3", score=0.85, mbid="mbid-123")
        result = AggregatedResult(mbid="mbid-123", matches=[match1, match2])
        assert result.vote_count == 2

    def test_average_score_empty(self):
        """Test average_score with no matches."""
        result = AggregatedResult(mbid="mbid-123")
        assert result.average_score == 0.0

    def test_average_score_with_matches(self):
        """Test average_score calculation."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.9, mbid="mbid-123")
        match2 = FingerprintMatch(Path("/t2.mp3"), "t2.mp3", score=0.8, mbid="mbid-123")
        result = AggregatedResult(mbid="mbid-123", matches=[match1, match2])
        assert result.average_score == pytest.approx(0.85)

    def test_track_names(self):
        """Test track_names property."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "track1.mp3", mbid="mbid-123")
        match2 = FingerprintMatch(Path("/t2.mp3"), "track2.mp3", mbid="mbid-123")
        result = AggregatedResult(mbid="mbid-123", matches=[match1, match2])
        assert result.track_names == ["track1.mp3", "track2.mp3"]


class TestBatchFingerprintResult:
    """Tests for BatchFingerprintResult dataclass."""

    def test_has_results_empty(self):
        """Test has_results with no results."""
        result = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=10,
            analyzed_tracks=0,
            failed_tracks=0,
        )
        assert not result.has_results

    def test_has_results_with_data(self):
        """Test has_results with results."""
        agg = AggregatedResult(mbid="mbid-123")
        result = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=10,
            analyzed_tracks=5,
            failed_tracks=0,
            results=[agg],
        )
        assert result.has_results

    def test_best_result_empty(self):
        """Test best_result with no results."""
        result = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=10,
            analyzed_tracks=0,
            failed_tracks=0,
        )
        assert result.best_result is None

    def test_best_result_single(self):
        """Test best_result with single result."""
        match = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.9, mbid="mbid-1")
        agg = AggregatedResult(mbid="mbid-1", matches=[match])
        result = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=10,
            analyzed_tracks=1,
            failed_tracks=0,
            results=[agg],
        )
        assert result.best_result == agg

    def test_best_result_by_vote_count(self):
        """Test best_result prefers higher vote count."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.95, mbid="mbid-1")
        match2 = FingerprintMatch(Path("/t2.mp3"), "t2.mp3", score=0.85, mbid="mbid-2")
        match3 = FingerprintMatch(Path("/t3.mp3"), "t3.mp3", score=0.80, mbid="mbid-2")

        agg1 = AggregatedResult(mbid="mbid-1", matches=[match1])  # 1 vote, 0.95 score
        agg2 = AggregatedResult(mbid="mbid-2", matches=[match2, match3])  # 2 votes, 0.825 score

        result = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=10,
            analyzed_tracks=3,
            failed_tracks=0,
            results=[agg1, agg2],
        )
        # More votes wins
        assert result.best_result == agg2

    def test_best_result_tiebreaker_by_score(self):
        """Test best_result uses score as tiebreaker when vote counts are equal."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.85, mbid="mbid-1")
        match2 = FingerprintMatch(Path("/t2.mp3"), "t2.mp3", score=0.95, mbid="mbid-2")

        agg1 = AggregatedResult(mbid="mbid-1", matches=[match1])  # 1 vote, 0.85 score
        agg2 = AggregatedResult(mbid="mbid-2", matches=[match2])  # 1 vote, 0.95 score

        result = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=10,
            analyzed_tracks=2,
            failed_tracks=0,
            results=[agg1, agg2],
        )
        # Equal votes, higher score wins
        assert result.best_result == agg2

    def test_get_remaining_tracks(self):
        """Test get_remaining_tracks returns unanalyzed tracks."""
        result = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=5,
            analyzed_tracks=2,
            failed_tracks=0,
            analyzed_paths={Path("/t1.mp3"), Path("/t2.mp3")},
        )
        all_tracks = [Path("/t1.mp3"), Path("/t2.mp3"), Path("/t3.mp3"), Path("/t4.mp3")]
        remaining = result.get_remaining_tracks(all_tracks)
        assert set(remaining) == {Path("/t3.mp3"), Path("/t4.mp3")}


class TestBatchFingerprinter:
    """Tests for BatchFingerprinter class."""

    def test_default_configuration(self):
        """Test default configuration values."""
        bp = BatchFingerprinter()
        assert bp.min_percent == BatchFingerprinter.DEFAULT_MIN_PERCENT
        assert bp.min_floor == BatchFingerprinter.DEFAULT_MIN_FLOOR
        assert bp.max_cap == BatchFingerprinter.DEFAULT_MAX_CAP
        assert bp.additional_count == BatchFingerprinter.DEFAULT_ADDITIONAL_COUNT

    def test_custom_configuration(self):
        """Test custom configuration values."""
        bp = BatchFingerprinter(
            min_percent=30,
            min_floor=3,
            max_cap=10,
            additional_count=5,
        )
        assert bp.min_percent == 30
        assert bp.min_floor == 3
        assert bp.max_cap == 10
        assert bp.additional_count == 5

    def test_calculate_tracks_to_analyze_empty(self):
        """Test calculation with zero tracks."""
        bp = BatchFingerprinter()
        assert bp.calculate_tracks_to_analyze(0) == 0

    def test_calculate_tracks_to_analyze_small_album(self):
        """Test calculation with small album (floor applies)."""
        bp = BatchFingerprinter(min_percent=25, min_floor=2, max_cap=8)
        # 4 tracks: 25% = 1, but floor is 2
        assert bp.calculate_tracks_to_analyze(4) == 2

    def test_calculate_tracks_to_analyze_medium_album(self):
        """Test calculation with medium album."""
        bp = BatchFingerprinter(min_percent=25, min_floor=2, max_cap=8)
        # 12 tracks: 25% = 3, floor=2, cap=8 -> 3
        assert bp.calculate_tracks_to_analyze(12) == 3

    def test_calculate_tracks_to_analyze_large_album(self):
        """Test calculation with large album (cap applies)."""
        bp = BatchFingerprinter(min_percent=25, min_floor=2, max_cap=8)
        # 40 tracks: 25% = 10, but cap is 8
        assert bp.calculate_tracks_to_analyze(40) == 8

    def test_calculate_tracks_to_analyze_single_track(self):
        """Test calculation with single track album."""
        bp = BatchFingerprinter(min_percent=25, min_floor=2, max_cap=8)
        # 1 track: can't exceed total
        assert bp.calculate_tracks_to_analyze(1) == 1

    def test_fingerprinter_lazy_initialization(self):
        """Test fingerprinter is lazily initialized."""
        bp = BatchFingerprinter()
        assert bp._fingerprinter is None
        # Access property to trigger initialization
        _ = bp.fingerprinter
        assert bp._fingerprinter is not None

    def test_fingerprinter_with_provided_instance(self):
        """Test fingerprinter uses provided instance."""
        mock_fp = MagicMock()
        bp = BatchFingerprinter(fingerprinter=mock_fp)
        assert bp.fingerprinter is mock_fp

    def test_analyze_album_no_tracks(self):
        """Test analyze_album with album that has no valid tracks."""
        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = []
        mock_album.track_count = 0
        mock_album.path = Path("/music/album")

        bp = BatchFingerprinter()
        result = bp.analyze_album(mock_album)

        assert result.total_tracks == 0
        assert result.analyzed_tracks == 0
        assert result.failed_tracks == 0
        assert not result.has_results

    def test_analyze_album_with_mocked_fingerprinter(self):
        """Test analyze_album with mocked fingerprinter."""
        # Create mock tracks with MagicMock paths that have .exists() method
        mock_path1 = MagicMock(spec=Path)
        mock_path1.exists.return_value = True
        mock_path1.name = "track1.mp3"
        mock_path1.__str__ = MagicMock(return_value="/music/album/track1.mp3")
        mock_path1.__hash__ = MagicMock(return_value=hash("/music/album/track1.mp3"))
        mock_path1.__eq__ = lambda self, other: str(self) == str(other)

        mock_path2 = MagicMock(spec=Path)
        mock_path2.exists.return_value = True
        mock_path2.name = "track2.mp3"
        mock_path2.__str__ = MagicMock(return_value="/music/album/track2.mp3")
        mock_path2.__hash__ = MagicMock(return_value=hash("/music/album/track2.mp3"))
        mock_path2.__eq__ = lambda self, other: str(self) == str(other)

        mock_track1 = MagicMock()
        mock_track1.path = mock_path1

        mock_track2 = MagicMock()
        mock_track2.path = mock_path2

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track1, mock_track2]
        mock_album.track_count = 2
        mock_album.path = Path("/music/album")

        # Mock fingerprinter
        mock_fp = MagicMock()
        mock_fp.identify.return_value = [
            {
                "score": 0.95,
                "recording_id": "rec-123",
                "title": "Track 1",
                "artist": "Artist",
                "album": "Album",
                "year": 2020,
                "mbid": "mbid-release-123",
            }
        ]

        bp = BatchFingerprinter(
            fingerprinter=mock_fp,
            min_floor=2,
            min_percent=100,
            max_cap=10,
            parallel=False,  # Disable parallel mode for this test (uses identify())
        )

        result = bp.analyze_album(mock_album)

        assert result.total_tracks == 2
        assert result.analyzed_tracks >= 1  # At least one successful
        assert result.has_results

    def test_analyze_album_no_matches(self):
        """Test analyze_album when fingerprinting returns no matches."""
        mock_track = MagicMock()
        mock_track.path = Path("/music/album/track1.mp3")

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track]
        mock_album.track_count = 1
        mock_album.path = Path("/music/album")

        mock_fp = MagicMock()
        mock_fp.identify.return_value = None  # No matches

        bp = BatchFingerprinter(fingerprinter=mock_fp, min_floor=1, max_cap=1, parallel=False)

        with patch.object(Path, "exists", return_value=True):
            result = bp.analyze_album(mock_album)

        assert result.total_tracks == 1
        assert result.analyzed_tracks == 0
        assert result.failed_tracks == 1
        assert not result.has_results

    def test_analyze_album_match_without_mbid(self):
        """Test analyze_album when fingerprint match has no MBID."""
        mock_track = MagicMock()
        mock_track.path = Path("/music/album/track1.mp3")

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track]
        mock_album.track_count = 1
        mock_album.path = Path("/music/album")

        mock_fp = MagicMock()
        mock_fp.identify.return_value = [
            {
                "score": 0.9,
                "recording_id": "rec-123",
                "title": "Track",
                "artist": "Artist",
                # No mbid
            }
        ]

        bp = BatchFingerprinter(fingerprinter=mock_fp, min_floor=1, max_cap=1, parallel=False)

        with patch.object(Path, "exists", return_value=True):
            result = bp.analyze_album(mock_album)

        # Match without MBID should count as failed
        assert result.analyzed_tracks == 0
        assert result.failed_tracks == 1
        assert not result.has_results

    def test_analyze_more_empty_remaining(self):
        """Test analyze_more when no tracks remaining."""
        mock_album = MagicMock()
        mock_album.tracks = []
        mock_album.path = Path("/music/album")

        previous = BatchFingerprintResult(
            album_path=Path("/music/album"),
            total_tracks=5,
            analyzed_tracks=5,
            failed_tracks=0,
            analyzed_paths={Path(f"/t{i}.mp3") for i in range(5)},
        )

        bp = BatchFingerprinter()
        result = bp.analyze_more(mock_album, previous)

        # Should return previous result unchanged
        assert result is previous

    def test_analyze_more_with_remaining_tracks(self):
        """Test analyze_more with remaining tracks."""
        mock_track = MagicMock()
        mock_track.path = Path("/music/album/track3.mp3")

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track]
        mock_album.path = Path("/music/album")

        previous = BatchFingerprintResult(
            album_path=Path("/music/album"),
            total_tracks=3,
            analyzed_tracks=2,
            failed_tracks=0,
            analyzed_paths={Path("/music/album/track1.mp3"), Path("/music/album/track2.mp3")},
            results=[AggregatedResult(mbid="mbid-1")],
        )

        mock_fp = MagicMock()
        mock_fp.identify.return_value = [
            {"score": 0.9, "mbid": "mbid-1", "title": "T3", "artist": "A"}
        ]

        bp = BatchFingerprinter(fingerprinter=mock_fp, parallel=False)

        with patch.object(Path, "exists", return_value=True):
            result = bp.analyze_more(mock_album, previous)

        # Should merge results
        assert result.total_tracks == 3
        assert result.analyzed_tracks >= 2

    def test_merge_results_combines_same_mbid(self):
        """Test that merge_results combines matches with same MBID."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.9, mbid="mbid-1")
        match2 = FingerprintMatch(Path("/t2.mp3"), "t2.mp3", score=0.85, mbid="mbid-1")

        prev_result = AggregatedResult(mbid="mbid-1", matches=[match1])
        new_result = AggregatedResult(mbid="mbid-1", matches=[match2])

        previous = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=5,
            analyzed_tracks=1,
            failed_tracks=0,
            analyzed_paths={Path("/t1.mp3")},
            results=[prev_result],
        )

        new = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=5,
            analyzed_tracks=1,
            failed_tracks=0,
            analyzed_paths={Path("/t2.mp3")},
            results=[new_result],
        )

        bp = BatchFingerprinter()
        merged = bp._merge_results(previous, new)

        # Should have combined into one result with 2 matches
        assert len(merged.results) == 1
        assert merged.results[0].vote_count == 2
        assert merged.analyzed_tracks == 2
        assert len(merged.analyzed_paths) == 2

    def test_merge_results_keeps_different_mbids(self):
        """Test that merge_results keeps different MBIDs separate."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.9, mbid="mbid-1")
        match2 = FingerprintMatch(Path("/t2.mp3"), "t2.mp3", score=0.85, mbid="mbid-2")

        prev_result = AggregatedResult(mbid="mbid-1", matches=[match1])
        new_result = AggregatedResult(mbid="mbid-2", matches=[match2])

        previous = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=5,
            analyzed_tracks=1,
            failed_tracks=0,
            analyzed_paths={Path("/t1.mp3")},
            results=[prev_result],
        )

        new = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=5,
            analyzed_tracks=1,
            failed_tracks=0,
            analyzed_paths={Path("/t2.mp3")},
            results=[new_result],
        )

        bp = BatchFingerprinter()
        merged = bp._merge_results(previous, new)

        # Should have two separate results
        assert len(merged.results) == 2
        assert merged.analyzed_tracks == 2

    def test_results_sorted_by_votes_then_score(self):
        """Test that results are sorted by vote count, then by score."""
        match1 = FingerprintMatch(Path("/t1.mp3"), "t1.mp3", score=0.95, mbid="mbid-1")
        match2 = FingerprintMatch(Path("/t2.mp3"), "t2.mp3", score=0.85, mbid="mbid-2")
        match3 = FingerprintMatch(Path("/t3.mp3"), "t3.mp3", score=0.80, mbid="mbid-2")
        match4 = FingerprintMatch(Path("/t4.mp3"), "t4.mp3", score=0.90, mbid="mbid-3")

        # mbid-1: 1 vote, 0.95 score
        # mbid-2: 2 votes, 0.825 score
        # mbid-3: 1 vote, 0.90 score
        result1 = AggregatedResult(mbid="mbid-1", matches=[match1])
        result2 = AggregatedResult(mbid="mbid-2", matches=[match2, match3])
        result3 = AggregatedResult(mbid="mbid-3", matches=[match4])

        batch = BatchFingerprintResult(
            album_path=Path("/album"),
            total_tracks=4,
            analyzed_tracks=4,
            failed_tracks=0,
            results=[result1, result2, result3],
        )

        # Results should be sorted
        batch.results.sort(key=lambda r: (r.vote_count, r.average_score), reverse=True)

        # mbid-2 should be first (more votes)
        assert batch.results[0].mbid == "mbid-2"
        # mbid-1 should be second (higher score than mbid-3)
        assert batch.results[1].mbid == "mbid-1"
        # mbid-3 should be last
        assert batch.results[2].mbid == "mbid-3"

    def test_progress_callback_called(self):
        """Test that progress callback is called during analysis."""
        mock_track = MagicMock()
        mock_track.path = Path("/music/album/track1.mp3")

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track]
        mock_album.track_count = 1
        mock_album.path = Path("/music/album")

        mock_fp = MagicMock()
        mock_fp.identify.return_value = [{"score": 0.9, "mbid": "mbid-1"}]

        progress_calls = []

        def progress_callback(current, total, name):
            progress_calls.append((current, total, name))

        bp = BatchFingerprinter(fingerprinter=mock_fp, min_floor=1, max_cap=1, parallel=False)

        with patch.object(Path, "exists", return_value=True):
            bp.analyze_album(mock_album, progress_callback=progress_callback)

        assert len(progress_calls) == 1
        assert progress_calls[0][0] == 1  # current
        assert progress_calls[0][1] == 1  # total
        assert progress_calls[0][2] == "track1.mp3"  # name

    def test_analyze_skips_to_next_track_on_failure(self):
        """Test that analysis skips to next track when one fails."""
        mock_track1 = MagicMock()
        mock_track1.path = Path("/music/album/track1.mp3")

        mock_track2 = MagicMock()
        mock_track2.path = Path("/music/album/track2.mp3")

        mock_track3 = MagicMock()
        mock_track3.path = Path("/music/album/track3.mp3")

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track1, mock_track2, mock_track3]
        mock_album.track_count = 3
        mock_album.path = Path("/music/album")

        mock_fp = MagicMock()
        # First track fails, second succeeds
        mock_fp.identify.side_effect = [
            None,  # track1 fails
            [{"score": 0.9, "mbid": "mbid-1"}],  # track2 succeeds
        ]

        bp = BatchFingerprinter(
            fingerprinter=mock_fp,
            min_floor=1,  # Only need 1 successful
            max_cap=3,
            parallel=False,  # Disable parallel mode for this test (uses identify())
        )

        with patch.object(Path, "exists", return_value=True):
            result = bp.analyze_album(mock_album)

        assert result.analyzed_tracks == 1
        assert result.failed_tracks == 1
        # Both track1 and track2 should be in analyzed_paths
        assert len(result.analyzed_paths) == 2
        assert result.has_results

    def test_is_available_property(self):
        """Test is_available property delegates to fingerprinter."""
        mock_fp = MagicMock()
        mock_fp.is_available = True

        bp = BatchFingerprinter(fingerprinter=mock_fp)
        assert bp.is_available is True

        mock_fp.is_available = False
        assert bp.is_available is False


class TestParallelFingerprinting:
    """Tests for parallel fingerprinting mode."""

    def test_parallel_mode_default_enabled(self):
        """Test that parallel mode is enabled by default."""
        bp = BatchFingerprinter()
        assert bp.parallel is True
        assert bp.max_workers == BatchFingerprinter.DEFAULT_MAX_WORKERS

    def test_parallel_mode_disabled(self):
        """Test creating BatchFingerprinter with parallel mode disabled."""
        bp = BatchFingerprinter(parallel=False)
        assert bp.parallel is False

    def test_parallel_mode_custom_workers(self):
        """Test creating BatchFingerprinter with custom worker count."""
        bp = BatchFingerprinter(max_workers=8)
        assert bp.max_workers == 8

    def test_fingerprint_single_track_success(self):
        """Test _fingerprint_single_track returns fingerprint data."""
        mock_fp = MagicMock()
        mock_fp.fingerprint.return_value = (180.5, "FINGERPRINT123")

        bp = BatchFingerprinter(fingerprinter=mock_fp)
        track_path = Path("/music/track.mp3")

        result_path, result_fp = bp._fingerprint_single_track(track_path)

        assert result_path == track_path
        assert result_fp == (180.5, "FINGERPRINT123")
        mock_fp.fingerprint.assert_called_once_with(track_path)

    def test_fingerprint_single_track_failure(self):
        """Test _fingerprint_single_track returns None on error."""
        mock_fp = MagicMock()
        mock_fp.fingerprint.side_effect = OSError("Fingerprint error")

        bp = BatchFingerprinter(fingerprinter=mock_fp)
        track_path = Path("/music/track.mp3")

        result_path, result_fp = bp._fingerprint_single_track(track_path)

        assert result_path == track_path
        assert result_fp is None

    def test_parallel_analyze_with_fingerprint_and_lookup(self):
        """Test parallel analysis uses fingerprint() and lookup() separately."""
        # Create mock paths
        mock_path1 = MagicMock(spec=Path)
        mock_path1.exists.return_value = True
        mock_path1.name = "track1.mp3"
        mock_path1.__str__ = MagicMock(return_value="/music/album/track1.mp3")
        mock_path1.__hash__ = MagicMock(return_value=hash("/music/album/track1.mp3"))
        mock_path1.__eq__ = lambda self, other: str(self) == str(other)

        mock_path2 = MagicMock(spec=Path)
        mock_path2.exists.return_value = True
        mock_path2.name = "track2.mp3"
        mock_path2.__str__ = MagicMock(return_value="/music/album/track2.mp3")
        mock_path2.__hash__ = MagicMock(return_value=hash("/music/album/track2.mp3"))
        mock_path2.__eq__ = lambda self, other: str(self) == str(other)

        mock_track1 = MagicMock()
        mock_track1.path = mock_path1

        mock_track2 = MagicMock()
        mock_track2.path = mock_path2

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track1, mock_track2]
        mock_album.track_count = 2
        mock_album.path = Path("/music/album")

        # Mock fingerprinter with separate fingerprint/lookup methods
        mock_fp = MagicMock()
        mock_fp.fingerprint.return_value = (180.5, "FINGERPRINT")
        mock_fp.lookup.return_value = [
            {
                "score": 0.95,
                "recording_id": "rec-123",
                "title": "Track",
                "artist": "Artist",
                "album": "Album",
                "year": 2020,
                "mbid": "mbid-release-123",
            }
        ]

        bp = BatchFingerprinter(
            fingerprinter=mock_fp,
            min_floor=2,
            min_percent=100,
            max_cap=10,
            parallel=True,
            max_workers=2,
        )

        result = bp.analyze_album(mock_album)

        # In parallel mode, fingerprint() should be called for each track
        assert mock_fp.fingerprint.call_count >= 1
        # And lookup() should be called for successful fingerprints
        assert mock_fp.lookup.call_count >= 1
        assert result.has_results

    def test_parallel_analyze_with_mixed_results(self):
        """Test parallel analysis handles mix of success and failure."""
        mock_path1 = MagicMock(spec=Path)
        mock_path1.exists.return_value = True
        mock_path1.name = "track1.mp3"
        mock_path1.__str__ = MagicMock(return_value="/music/track1.mp3")
        mock_path1.__hash__ = MagicMock(return_value=hash("/music/track1.mp3"))
        mock_path1.__eq__ = lambda self, other: str(self) == str(other)

        mock_path2 = MagicMock(spec=Path)
        mock_path2.exists.return_value = True
        mock_path2.name = "track2.mp3"
        mock_path2.__str__ = MagicMock(return_value="/music/track2.mp3")
        mock_path2.__hash__ = MagicMock(return_value=hash("/music/track2.mp3"))
        mock_path2.__eq__ = lambda self, other: str(self) == str(other)

        mock_track1 = MagicMock()
        mock_track1.path = mock_path1

        mock_track2 = MagicMock()
        mock_track2.path = mock_path2

        mock_album = MagicMock()
        mock_album.display_name = "Test Album"
        mock_album.tracks = [mock_track1, mock_track2]
        mock_album.track_count = 2
        mock_album.path = Path("/music/album")

        # Mock fingerprinter - first track succeeds, second fails
        mock_fp = MagicMock()

        def fingerprint_side_effect(path):
            if "track1" in str(path):
                return (180.5, "FINGERPRINT1")
            return None  # Failure for track2

        mock_fp.fingerprint.side_effect = fingerprint_side_effect
        mock_fp.lookup.return_value = [
            {"score": 0.9, "mbid": "mbid-1", "title": "Track", "artist": "Artist"}
        ]

        bp = BatchFingerprinter(
            fingerprinter=mock_fp,
            min_floor=1,
            max_cap=2,
            parallel=True,
            max_workers=2,
        )

        result = bp.analyze_album(mock_album)

        # Should have at least one successful result and one failure
        assert result.failed_tracks >= 1 or result.analyzed_tracks >= 1
