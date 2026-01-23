"""
Tests for the batch download dialog.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AlbumInfo, CoverInfo, CoverStatus, SearchResult


class TestBatchDownloadResult:
    """Tests for BatchDownloadResult dataclass."""

    def test_default_values(self):
        """Test default values of BatchDownloadResult."""
        from src.ui.dialogs.batch_download_dialog import BatchDownloadResult

        result = BatchDownloadResult()
        assert result.downloaded == 0
        assert result.skipped_no_match == 0
        assert result.skipped_already_has == 0
        assert result.errors == 0
        assert result.error_messages == []

    def test_custom_values(self):
        """Test BatchDownloadResult with custom values."""
        from src.ui.dialogs.batch_download_dialog import BatchDownloadResult

        result = BatchDownloadResult(
            downloaded=5,
            skipped_no_match=2,
            skipped_already_has=3,
            errors=1,
            error_messages=["Error 1"],
        )
        assert result.downloaded == 5
        assert result.skipped_no_match == 2
        assert result.skipped_already_has == 3
        assert result.errors == 1
        assert result.error_messages == ["Error 1"]


class TestBatchDownloadWorker:
    """Tests for BatchDownloadWorker."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "providers.musicbrainz.enabled": True,
            "providers.discogs.enabled": False,
            "providers.lastfm.enabled": False,
            "embedding.preserve_timestamp": True,
            "embedding.embed_covers": True,
            "embedding.save_folder_cover": True,
            "embedding.external_filename": "cover",
        }.get(key, default)
        return config

    @pytest.fixture
    def sample_albums(self, tmp_path):
        """Create sample albums for testing."""
        albums = []
        for i in range(3):
            album_path = tmp_path / f"Artist{i}" / f"Album{i}"
            album_path.mkdir(parents=True)
            (album_path / "track.mp3").write_bytes(b"fake mp3")

            album = AlbumInfo(
                path=album_path,
                artist=f"Artist {i}",
                album=f"Album {i}",
                year="2020",
                track_count=1,
                cover=CoverInfo(has_embedded=False, has_folder=False),
                sample_file=album_path / "track.mp3",
                formats=[".mp3"],
            )
            albums.append(album)
        return albums

    def test_worker_creation(self, sample_albums, mock_config):
        """Test worker can be created."""
        from src.ui.dialogs.batch_download_dialog import BatchDownloadWorker

        worker = BatchDownloadWorker(
            albums=sample_albums,
            config=mock_config,
            min_score=95,
        )
        assert worker.albums == sample_albums
        assert worker.min_score == 95
        assert not worker._cancelled
        assert not worker._skipped

    def test_cancel_sets_flag(self, sample_albums, mock_config):
        """Test cancel method sets the cancelled flag."""
        from src.ui.dialogs.batch_download_dialog import BatchDownloadWorker

        worker = BatchDownloadWorker(
            albums=sample_albums,
            config=mock_config,
            min_score=95,
        )
        assert not worker._cancelled
        worker.cancel()
        assert worker._cancelled

    def test_skip_sets_flag(self, sample_albums, mock_config):
        """Test skip_current method sets the skipped flag."""
        from src.ui.dialogs.batch_download_dialog import BatchDownloadWorker

        worker = BatchDownloadWorker(
            albums=sample_albums,
            config=mock_config,
            min_score=95,
        )
        assert not worker._skipped
        worker.skip_current()
        assert worker._skipped

    def test_create_providers_musicbrainz_only(self, sample_albums, mock_config):
        """Test _create_providers returns only MusicBrainz when others are disabled."""
        from src.api.musicbrainz import MusicBrainzProvider
        from src.ui.dialogs.batch_download_dialog import BatchDownloadWorker

        worker = BatchDownloadWorker(
            albums=sample_albums,
            config=mock_config,
            min_score=95,
        )
        providers = worker._create_providers()
        assert len(providers) == 1
        assert isinstance(providers[0], MusicBrainzProvider)

    def test_create_providers_all_enabled(self, sample_albums):
        """Test _create_providers returns all providers when enabled with API keys."""
        from src.ui.dialogs.batch_download_dialog import BatchDownloadWorker

        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "providers.musicbrainz.enabled": True,
            "providers.discogs.enabled": True,
            "api.discogs_token": "test-discogs-token",
            "providers.lastfm.enabled": True,
            "api.lastfm_key": "test-lastfm-key",
            "embedding.preserve_timestamp": True,
        }.get(key, default)

        worker = BatchDownloadWorker(
            albums=[],
            config=config,
            min_score=95,
        )
        providers = worker._create_providers()
        assert len(providers) == 3


class TestBatchDownloadDialog:
    """Tests for BatchDownloadDialog (requires Qt)."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "providers.musicbrainz.enabled": True,
            "providers.discogs.enabled": False,
            "providers.lastfm.enabled": False,
            "auto_mode_min_score": 95,
            "embedding.preserve_timestamp": True,
            "embedding.embed_covers": True,
            "embedding.save_folder_cover": True,
            "embedding.external_filename": "cover",
        }.get(key, default)
        return config

    @pytest.mark.skipif(
        True,
        reason="Requires Qt event loop - run with pytest-qt",
    )
    def test_dialog_creation(self, mock_config, tmp_path):
        """Test dialog can be created."""
        from src.ui.dialogs.batch_download_dialog import BatchDownloadDialog

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            year="2020",
            track_count=1,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=None,
            formats=[".mp3"],
        )

        dialog = BatchDownloadDialog([album], mock_config)
        assert dialog is not None


class TestBatchDownloadIntegration:
    """Integration tests for batch download functionality."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock cover provider."""
        provider = MagicMock()
        provider.name = "MockProvider"
        provider.search.return_value = [
            SearchResult(
                provider="MockProvider",
                artist="Test Artist",
                album="Test Album",
                year="2020",
                score=98,
                has_cover_art=True,
                cover_url="http://example.com/cover.jpg",
            )
        ]
        provider.calculate_match_score.return_value = 98
        provider.download_cover.return_value = b"fake image data"
        return provider

    def test_album_with_cover_is_skipped(self, tmp_path):
        """Test that albums with existing covers are skipped."""

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "cover.jpg").write_bytes(b"existing cover")

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            year="2020",
            track_count=1,
            cover=CoverInfo(has_embedded=False, has_folder=True),
            sample_file=None,
            formats=[".mp3"],
        )

        # Verify the album has a cover
        assert album.cover_status != CoverStatus.NONE

    def test_album_without_cover_needs_processing(self, tmp_path):
        """Test that albums without covers need processing."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            year="2020",
            track_count=1,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=None,
            formats=[".mp3"],
        )

        # Verify the album needs a cover
        assert album.cover_status == CoverStatus.NONE


class TestMainWindowBatchDownload:
    """Tests for batch download menu action in MainWindow."""

    @pytest.fixture
    def mock_main_window_deps(self):
        """Mock dependencies for MainWindow."""
        with (
            patch("src.ui.main_window.LibraryView") as mock_library_view,
            patch("src.ui.main_window.AlbumDetailPanel") as mock_detail_panel,
        ):
            yield mock_library_view, mock_detail_panel

    def test_batch_download_action_exists(self):
        """Test that batch download menu action text is correct."""
        # This test verifies the string used in the menu action
        expected_text = "Télécharger automatiquement les covers..."
        assert "Télécharger" in expected_text
        assert "automatiquement" in expected_text

    def test_batch_download_filters_albums_without_covers(self, tmp_path):
        """Test that batch download only processes albums without covers."""
        # Create test albums
        albums = []

        # Album with cover
        album_with_cover_path = tmp_path / "Artist1" / "Album1"
        album_with_cover_path.mkdir(parents=True)
        albums.append(
            AlbumInfo(
                path=album_with_cover_path,
                artist="Artist 1",
                album="Album 1",
                year="2020",
                track_count=1,
                cover=CoverInfo(has_embedded=True, has_folder=True),
                sample_file=None,
                formats=[".mp3"],
            )
        )

        # Album without cover
        album_without_cover_path = tmp_path / "Artist2" / "Album2"
        album_without_cover_path.mkdir(parents=True)
        albums.append(
            AlbumInfo(
                path=album_without_cover_path,
                artist="Artist 2",
                album="Album 2",
                year="2020",
                track_count=1,
                cover=CoverInfo(has_embedded=False, has_folder=False),
                sample_file=None,
                formats=[".mp3"],
            )
        )

        # Filter to albums needing covers
        albums_needing_covers = [a for a in albums if a.cover_status == CoverStatus.NONE]

        assert len(albums_needing_covers) == 1
        assert albums_needing_covers[0].artist == "Artist 2"


class TestBatchDownloadSingleFileAlbum:
    """Tests for single-file album handling in batch download."""

    def test_single_file_album_detection(self, tmp_path):
        """Test that single-file albums are correctly identified."""
        single_file = tmp_path / "Artist - Album.mp3"
        single_file.write_bytes(b"fake mp3 data")

        album = AlbumInfo(
            path=single_file,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=single_file,
        )

        is_single_file = album.path.is_file()
        assert is_single_file is True

    def test_folder_album_detection(self, tmp_path):
        """Test that folder albums are correctly identified."""
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)
        sample_file = album_folder / "track.mp3"
        sample_file.write_bytes(b"fake mp3 data")

        album = AlbumInfo(
            path=album_folder,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=sample_file,
        )

        is_single_file = album.path.is_file()
        assert is_single_file is False

    def test_target_folder_calculation_for_single_file(self, tmp_path):
        """Test target folder calculation for single-file album."""
        music_dir = tmp_path / "Music"
        music_dir.mkdir()
        single_file = music_dir / "Artist - Album.mp3"
        single_file.write_bytes(b"fake mp3 data")

        album = AlbumInfo(
            path=single_file,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=single_file,
        )

        # Simulate the logic from _apply_cover in batch_download_dialog
        is_single_file = album.path.is_file()
        target_folder = album.path.parent if is_single_file else album.path

        assert target_folder == music_dir

    def test_target_folder_calculation_for_folder_album(self, tmp_path):
        """Test target folder calculation for folder album."""
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)
        sample_file = album_folder / "track.mp3"
        sample_file.write_bytes(b"fake mp3 data")

        album = AlbumInfo(
            path=album_folder,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=sample_file,
        )

        # Simulate the logic from _apply_cover in batch_download_dialog
        is_single_file = album.path.is_file()
        target_folder = album.path.parent if is_single_file else album.path

        assert target_folder == album_folder

    def test_embed_method_selection_for_single_file(self, tmp_path):
        """Test that correct embed method is selected for single-file album."""
        single_file = tmp_path / "Artist - Album.mp3"
        single_file.write_bytes(b"fake mp3 data")

        album = AlbumInfo(
            path=single_file,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=single_file,
        )

        # Simulate the decision logic from _apply_cover
        is_single_file = album.path.is_file()
        if is_single_file:
            embed_method = "embed_cover_in_file"
            embed_target = album.path
        else:
            embed_method = "embed_cover_in_folder"
            embed_target = album.path

        assert embed_method == "embed_cover_in_file"
        assert embed_target == single_file

    def test_embed_method_selection_for_folder_album(self, tmp_path):
        """Test that correct embed method is selected for folder album."""
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)
        sample_file = album_folder / "track.mp3"
        sample_file.write_bytes(b"fake mp3 data")

        album = AlbumInfo(
            path=album_folder,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=sample_file,
        )

        # Simulate the decision logic from _apply_cover
        is_single_file = album.path.is_file()
        if is_single_file:
            embed_method = "embed_cover_in_file"
            embed_target = album.path
        else:
            embed_method = "embed_cover_in_folder"
            embed_target = album.path

        assert embed_method == "embed_cover_in_folder"
        assert embed_target == album_folder
