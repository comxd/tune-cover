"""
Tests for filter context tracking module.

Tests the FilterContext dataclass, MatchSource enum, and FilterContextManager
that tracks how albums match filters to enable source-aware operations.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.filter_context import FilterContext, FilterContextManager, MatchSource
from src.core.models import AlbumInfo, CoverInfo


class TestMatchSource:
    """Tests for MatchSource enum."""

    def test_embedded_value(self):
        """Test EMBEDDED enum value exists."""
        assert MatchSource.EMBEDDED is not None
        assert MatchSource.EMBEDDED.name == "EMBEDDED"

    def test_folder_value(self):
        """Test FOLDER enum value exists."""
        assert MatchSource.FOLDER is not None
        assert MatchSource.FOLDER.name == "FOLDER"

    def test_both_value(self):
        """Test BOTH enum value exists."""
        assert MatchSource.BOTH is not None
        assert MatchSource.BOTH.name == "BOTH"

    def test_enum_values_unique(self):
        """Test all enum values are unique."""
        values = [e.value for e in MatchSource]
        assert len(values) == len(set(values))

    def test_enum_has_three_members(self):
        """Test enum has exactly three members."""
        assert len(MatchSource) == 3


class TestFilterContext:
    """Tests for FilterContext dataclass."""

    def test_create_default(self):
        """Test creating FilterContext with defaults."""
        context = FilterContext()
        assert context.match_source is None
        assert context.matched_hash is None

    def test_create_with_embedded_source(self):
        """Test creating FilterContext with EMBEDDED source."""
        context = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="abc123")
        assert context.match_source == MatchSource.EMBEDDED
        assert context.matched_hash == "abc123"

    def test_create_with_folder_source(self):
        """Test creating FilterContext with FOLDER source."""
        context = FilterContext(match_source=MatchSource.FOLDER, matched_hash="def456")
        assert context.match_source == MatchSource.FOLDER
        assert context.matched_hash == "def456"

    def test_create_with_both_source(self):
        """Test creating FilterContext with BOTH source."""
        context = FilterContext(match_source=MatchSource.BOTH, matched_hash="ghi789")
        assert context.match_source == MatchSource.BOTH
        assert context.matched_hash == "ghi789"

    def test_equality(self):
        """Test FilterContext equality."""
        ctx1 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        ctx2 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        assert ctx1 == ctx2

    def test_inequality_different_source(self):
        """Test FilterContext inequality with different source."""
        ctx1 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        ctx2 = FilterContext(match_source=MatchSource.FOLDER, matched_hash="hash1")
        assert ctx1 != ctx2

    def test_inequality_different_hash(self):
        """Test FilterContext inequality with different hash."""
        ctx1 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        ctx2 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash2")
        assert ctx1 != ctx2


class TestFilterContextManager:
    """Tests for FilterContextManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh FilterContextManager for each test."""
        return FilterContextManager()

    @pytest.fixture
    def album(self):
        """Create a test album."""
        return AlbumInfo(
            path=Path("/music/artist/album"),
            artist="Test Artist",
            album="Test Album",
            track_count=10,
            cover=CoverInfo(),
        )

    @pytest.fixture
    def album2(self):
        """Create a second test album."""
        return AlbumInfo(
            path=Path("/music/artist/album2"),
            artist="Test Artist",
            album="Test Album 2",
            track_count=5,
            cover=CoverInfo(),
        )

    def test_init_empty(self, manager):
        """Test manager initializes empty."""
        assert len(manager) == 0

    def test_set_and_get_context(self, manager, album):
        """Test setting and getting context."""
        context = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        manager.set_context(album, context)

        retrieved = manager.get_context(album)
        assert retrieved == context

    def test_get_context_not_found(self, manager, album):
        """Test getting context that doesn't exist."""
        result = manager.get_context(album)
        assert result is None

    def test_has_context_true(self, manager, album):
        """Test has_context returns True when context exists."""
        context = FilterContext(match_source=MatchSource.FOLDER, matched_hash="hash2")
        manager.set_context(album, context)

        assert manager.has_context(album) is True

    def test_has_context_false(self, manager, album):
        """Test has_context returns False when context doesn't exist."""
        assert manager.has_context(album) is False

    def test_remove_context(self, manager, album):
        """Test removing context."""
        context = FilterContext(match_source=MatchSource.BOTH, matched_hash="hash3")
        manager.set_context(album, context)
        assert manager.has_context(album) is True

        manager.remove_context(album)
        assert manager.has_context(album) is False
        assert manager.get_context(album) is None

    def test_remove_context_nonexistent(self, manager, album):
        """Test removing context that doesn't exist (should not raise)."""
        # Should not raise any exception
        manager.remove_context(album)
        assert manager.has_context(album) is False

    def test_clear(self, manager, album, album2):
        """Test clearing all contexts."""
        ctx1 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        ctx2 = FilterContext(match_source=MatchSource.FOLDER, matched_hash="hash2")

        manager.set_context(album, ctx1)
        manager.set_context(album2, ctx2)
        assert len(manager) == 2

        manager.clear()
        assert len(manager) == 0
        assert manager.get_context(album) is None
        assert manager.get_context(album2) is None

    def test_clear_empty(self, manager):
        """Test clearing empty manager."""
        manager.clear()  # Should not raise
        assert len(manager) == 0

    def test_len(self, manager, album, album2):
        """Test __len__ method."""
        assert len(manager) == 0

        manager.set_context(album, FilterContext())
        assert len(manager) == 1

        manager.set_context(album2, FilterContext())
        assert len(manager) == 2

        manager.remove_context(album)
        assert len(manager) == 1

    def test_get_album_paths_with_context(self, manager, album, album2):
        """Test getting set of album paths with context."""
        ctx1 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        ctx2 = FilterContext(match_source=MatchSource.FOLDER, matched_hash="hash2")

        manager.set_context(album, ctx1)
        manager.set_context(album2, ctx2)

        paths = manager.get_album_paths_with_context()
        assert isinstance(paths, set)
        assert len(paths) == 2
        assert str(album.path) in paths
        assert str(album2.path) in paths

    def test_get_album_paths_with_context_empty(self, manager):
        """Test getting paths when empty."""
        paths = manager.get_album_paths_with_context()
        assert paths == set()

    def test_update_existing_context(self, manager, album):
        """Test updating an existing context."""
        ctx1 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="hash1")
        ctx2 = FilterContext(match_source=MatchSource.FOLDER, matched_hash="hash2")

        manager.set_context(album, ctx1)
        assert manager.get_context(album).match_source == MatchSource.EMBEDDED

        manager.set_context(album, ctx2)
        assert manager.get_context(album).match_source == MatchSource.FOLDER
        assert len(manager) == 1  # Should not create duplicate


class TestFilterContextManagerComputeHashMatchSource:
    """Tests for compute_hash_match_source method."""

    @pytest.fixture
    def manager(self):
        """Create a fresh FilterContextManager."""
        return FilterContextManager()

    @pytest.fixture
    def album_embedded_only(self):
        """Create an album with only embedded cover."""
        return AlbumInfo(
            path=Path("/music/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            sample_file=Path("/music/album/track.mp3"),
            cover=CoverInfo(has_embedded=True, has_folder=False, embedded_hash="embedded_hash_123"),
        )

    @pytest.fixture
    def album_folder_only(self):
        """Create an album with only folder cover."""
        return AlbumInfo(
            path=Path("/music/album2"),
            artist="Artist",
            album="Album 2",
            track_count=1,
            cover=CoverInfo(
                has_embedded=False,
                has_folder=True,
                folder_path=Path("/music/album2"),
                folder_hash="folder_hash_456",
            ),
        )

    @pytest.fixture
    def album_both_covers(self):
        """Create an album with both covers."""
        return AlbumInfo(
            path=Path("/music/album3"),
            artist="Artist",
            album="Album 3",
            track_count=1,
            sample_file=Path("/music/album3/track.mp3"),
            cover=CoverInfo(
                has_embedded=True,
                has_folder=True,
                folder_path=Path("/music/album3"),
                embedded_hash="same_hash",
                folder_hash="same_hash",
            ),
        )

    @pytest.fixture
    def album_both_different_hashes(self):
        """Create an album with both covers but different hashes."""
        return AlbumInfo(
            path=Path("/music/album4"),
            artist="Artist",
            album="Album 4",
            track_count=1,
            sample_file=Path("/music/album4/track.mp3"),
            cover=CoverInfo(
                has_embedded=True,
                has_folder=True,
                folder_path=Path("/music/album4"),
                embedded_hash="embedded_hash",
                folder_hash="folder_hash",
            ),
        )

    def test_match_embedded_cached(self, manager, album_embedded_only):
        """Test matching embedded hash with cached value."""
        result = manager.compute_hash_match_source(album_embedded_only, "embedded_hash_123")
        assert result == MatchSource.EMBEDDED

    def test_match_folder_cached(self, manager, album_folder_only):
        """Test matching folder hash with cached value."""
        result = manager.compute_hash_match_source(album_folder_only, "folder_hash_456")
        assert result == MatchSource.FOLDER

    def test_match_both_same_hash(self, manager, album_both_covers):
        """Test matching when both covers have same hash."""
        result = manager.compute_hash_match_source(album_both_covers, "same_hash")
        assert result == MatchSource.BOTH

    def test_match_embedded_only_from_both(self, manager, album_both_different_hashes):
        """Test matching only embedded when both covers exist."""
        result = manager.compute_hash_match_source(album_both_different_hashes, "embedded_hash")
        assert result == MatchSource.EMBEDDED

    def test_match_folder_only_from_both(self, manager, album_both_different_hashes):
        """Test matching only folder when both covers exist."""
        result = manager.compute_hash_match_source(album_both_different_hashes, "folder_hash")
        assert result == MatchSource.FOLDER

    def test_no_match(self, manager, album_embedded_only):
        """Test no match when hash doesn't match."""
        result = manager.compute_hash_match_source(album_embedded_only, "different_hash")
        assert result is None

    def test_no_covers(self, manager):
        """Test with album that has no covers."""
        album = AlbumInfo(
            path=Path("/music/empty"),
            artist="Artist",
            album="Empty Album",
            track_count=1,
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        result = manager.compute_hash_match_source(album, "any_hash")
        assert result is None

    @patch("src.utils.cover_hash.compute_embedded_hash")
    def test_computes_hash_when_not_cached(self, mock_compute, manager):
        """Test that hash is computed when not cached."""
        album = AlbumInfo(
            path=Path("/music/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            sample_file=Path("/music/album/track.mp3"),
            cover=CoverInfo(
                has_embedded=True,
                has_folder=False,
                embedded_hash=None,  # Not cached
            ),
        )
        mock_compute.return_value = "computed_hash"

        result = manager.compute_hash_match_source(album, "computed_hash")

        mock_compute.assert_called_once_with(Path("/music/album/track.mp3"))
        assert result == MatchSource.EMBEDDED
        # Verify hash was cached
        assert album.cover.embedded_hash == "computed_hash"

    @patch("src.utils.cover_hash.compute_folder_hash")
    def test_computes_folder_hash_when_not_cached(self, mock_compute, manager):
        """Test that folder hash is computed when not cached."""
        album = AlbumInfo(
            path=Path("/music/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            cover=CoverInfo(
                has_embedded=False,
                has_folder=True,
                folder_path=Path("/music/album"),
                folder_hash=None,  # Not cached
            ),
        )
        mock_compute.return_value = "computed_folder_hash"

        result = manager.compute_hash_match_source(album, "computed_folder_hash")

        mock_compute.assert_called_once_with(Path("/music/album"))
        assert result == MatchSource.FOLDER
        # Verify hash was cached
        assert album.cover.folder_hash == "computed_folder_hash"

    @patch("src.utils.cover_hash.compute_embedded_hash")
    def test_handles_hash_computation_failure(self, mock_compute, manager):
        """Test handling when hash computation returns None."""
        album = AlbumInfo(
            path=Path("/music/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            sample_file=Path("/music/album/track.mp3"),
            cover=CoverInfo(has_embedded=True, has_folder=False, embedded_hash=None),
        )
        mock_compute.return_value = None  # Computation failed

        result = manager.compute_hash_match_source(album, "any_hash")

        assert result is None
        # Hash should not be cached on failure
        assert album.cover.embedded_hash is None


class TestFilterContextManagerEdgeCases:
    """Edge case tests for FilterContextManager."""

    @pytest.fixture
    def manager(self):
        """Create a fresh FilterContextManager."""
        return FilterContextManager()

    def test_album_path_as_string_key(self, manager):
        """Test that album path is correctly converted to string key."""
        album = AlbumInfo(
            path=Path("/path/with/special chars/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            cover=CoverInfo(),
        )
        context = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="h")
        manager.set_context(album, context)

        # Should be retrievable with same album
        assert manager.get_context(album) == context

        # Check the actual key used
        paths = manager.get_album_paths_with_context()
        assert str(album.path) in paths

    def test_different_albums_same_content(self, manager):
        """Test albums with same path are treated as same key."""
        album1 = AlbumInfo(
            path=Path("/same/path"),
            artist="Artist 1",
            album="Album 1",
            track_count=1,
            cover=CoverInfo(),
        )
        album2 = AlbumInfo(
            path=Path("/same/path"),
            artist="Artist 2",  # Different artist
            album="Album 2",  # Different album name
            track_count=5,
            cover=CoverInfo(),
        )

        ctx1 = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="h1")
        ctx2 = FilterContext(match_source=MatchSource.FOLDER, matched_hash="h2")

        manager.set_context(album1, ctx1)
        manager.set_context(album2, ctx2)

        # Should only have one entry (same path key)
        assert len(manager) == 1

        # Context should be the last one set
        assert manager.get_context(album1).match_source == MatchSource.FOLDER
        assert manager.get_context(album2).match_source == MatchSource.FOLDER

    def test_unicode_path(self, manager):
        """Test album with unicode characters in path."""
        album = AlbumInfo(
            path=Path("/music/日本語/アルバム"),
            artist="アーティスト",
            album="アルバム",
            track_count=1,
            cover=CoverInfo(),
        )
        context = FilterContext(match_source=MatchSource.BOTH, matched_hash="hash")

        manager.set_context(album, context)
        retrieved = manager.get_context(album)

        assert retrieved == context
        assert len(manager) == 1

    def test_has_embedded_but_no_sample_file(self, manager):
        """Test album with has_embedded=True but sample_file=None (inconsistent state).

        This tests defensive handling of inconsistent data where the cover
        claims to have embedded art but no sample file is available.
        """
        album = AlbumInfo(
            path=Path("/music/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            sample_file=None,  # Missing despite has_embedded=True
            cover=CoverInfo(
                has_embedded=True,  # Inconsistent!
                has_folder=False,
                embedded_hash="some_hash",
            ),
        )
        result = manager.compute_hash_match_source(album, "some_hash")
        # Should return None because sample_file is missing
        assert result is None

    def test_has_folder_but_no_folder_path(self, manager):
        """Test album with has_folder=True but folder_path=None (inconsistent state).

        This tests defensive handling of inconsistent data where the cover
        claims to have folder art but no folder path is available.
        """
        album = AlbumInfo(
            path=Path("/music/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            cover=CoverInfo(
                has_embedded=False,
                has_folder=True,  # Inconsistent!
                folder_path=None,  # Missing despite has_folder=True
                folder_hash="some_hash",
            ),
        )
        result = manager.compute_hash_match_source(album, "some_hash")
        # Should return None because folder_path is missing
        assert result is None

    @patch("src.utils.cover_hash.compute_embedded_hash")
    def test_caches_hash_even_when_no_match(self, mock_compute, manager):
        """Test that computed hash is cached even when it doesn't match target.

        This ensures caching behavior is consistent regardless of match result,
        which is important for performance on subsequent lookups.
        """
        album = AlbumInfo(
            path=Path("/music/album"),
            artist="Artist",
            album="Album",
            track_count=1,
            sample_file=Path("/music/album/track.mp3"),
            cover=CoverInfo(
                has_embedded=True,
                has_folder=False,
                embedded_hash=None,  # Not cached
            ),
        )
        mock_compute.return_value = "computed_hash"

        # Try to match against different hash
        result = manager.compute_hash_match_source(album, "different_hash")

        mock_compute.assert_called_once()
        assert result is None  # No match
        # Hash should still be cached for future lookups
        assert album.cover.embedded_hash == "computed_hash"

    def test_album_with_minimal_attributes(self, manager):
        """Test handling of album with minimal/None attributes."""
        album = AlbumInfo(
            path=Path("/music/test"), artist=None, album=None, track_count=0, cover=CoverInfo()
        )
        context = FilterContext(match_source=MatchSource.EMBEDDED, matched_hash="h")

        # Should handle gracefully
        manager.set_context(album, context)
        assert manager.get_context(album) == context
        assert len(manager) == 1
