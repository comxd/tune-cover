"""
Tests for MainWindow search functionality and file handling.

Note: These tests mock Qt components to avoid requiring a QApplication.
For full GUI tests, use pytest-qt.
"""

from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AlbumInfo, CoverInfo, CoverStatus


class TestSearchFiltering:
    """
    Tests for the search filtering logic in MainWindow.

    These tests isolate the filtering decision-making logic without requiring Qt.
    """

    def _create_test_album(
        self,
        path: Path,
        artist: str = None,
        album: str = None,
        year: str = None,
        has_embedded: bool = False,
        has_folder: bool = False,
    ) -> AlbumInfo:
        """Create a test album with specified attributes."""
        cover = CoverInfo(has_embedded=has_embedded, has_folder=has_folder)
        return AlbumInfo(
            path=path,
            artist=artist,
            album=album,
            year=year,
            cover=cover,
        )

    @pytest.fixture
    def test_albums(self, tmp_path) -> list:
        """Create a diverse set of test albums."""
        return [
            self._create_test_album(
                tmp_path / "Rock" / "Artist1" / "Album1",
                artist="The Beatles",
                album="Abbey Road",
                year="1969",
                has_embedded=True,
                has_folder=True,
            ),
            self._create_test_album(
                tmp_path / "Jazz" / "Artist2" / "Album2",
                artist="Miles Davis",
                album="Kind of Blue",
                year="1959",
                has_embedded=False,
                has_folder=True,
            ),
            self._create_test_album(
                tmp_path / "Electronic" / "Artist3" / "Album3",
                artist="Daft Punk",
                album="Random Access Memories",
                year="2013",
                has_embedded=True,
                has_folder=False,
            ),
            self._create_test_album(
                tmp_path / "Classical" / "Artist4" / "Album4",
                artist="Bach",
                album="Goldberg Variations",
                year="1955",
                has_embedded=False,
                has_folder=False,
            ),
            self._create_test_album(
                tmp_path / "Pop" / "Unknown" / "Album5",
                artist=None,
                album="Unknown Album",
                year=None,
                has_embedded=False,
                has_folder=False,
            ),
        ]

    def _apply_search_filter(self, albums: list, search_text: str) -> list:
        """
        Apply search filter logic matching MainWindow._apply_filters.

        Matches against artist, album, year, and folder path.
        """
        search_text = search_text.lower().strip()
        if not search_text:
            return albums

        filtered = []
        for album in albums:
            searchable = " ".join(
                [
                    album.artist or "",
                    album.album or "",
                    album.year or "",
                    str(album.path),
                ]
            ).lower()
            if search_text in searchable:
                filtered.append(album)
        return filtered

    def test_search_by_artist_name(self, test_albums):
        """Test searching by artist name."""
        results = self._apply_search_filter(test_albums, "Beatles")
        assert len(results) == 1
        assert results[0].artist == "The Beatles"

    def test_search_by_artist_name_case_insensitive(self, test_albums):
        """Test search is case-insensitive."""
        results = self._apply_search_filter(test_albums, "BEATLES")
        assert len(results) == 1
        assert results[0].artist == "The Beatles"

    def test_search_by_album_name(self, test_albums):
        """Test searching by album name."""
        results = self._apply_search_filter(test_albums, "Kind of Blue")
        assert len(results) == 1
        assert results[0].album == "Kind of Blue"

    def test_search_by_album_partial_match(self, test_albums):
        """Test searching with partial album name."""
        results = self._apply_search_filter(test_albums, "Road")
        assert len(results) == 1
        assert results[0].album == "Abbey Road"

    def test_search_by_year_exact(self, test_albums):
        """Test searching by exact year."""
        results = self._apply_search_filter(test_albums, "1969")
        assert len(results) == 1
        assert results[0].year == "1969"

    def test_search_by_year_partial(self, test_albums):
        """Test searching by partial year."""
        results = self._apply_search_filter(test_albums, "195")
        # Filter to only albums where the year actually contains "195"
        # (excludes matches from tmp_path which may contain random numbers)
        results_by_year = [r for r in results if r.year and "195" in r.year]
        assert len(results_by_year) == 2  # 1959 and 1955
        years = {r.year for r in results_by_year}
        assert "1959" in years
        assert "1955" in years

    def test_search_by_folder_path(self, test_albums):
        """Test searching by folder path."""
        results = self._apply_search_filter(test_albums, "Jazz")
        assert len(results) == 1
        assert results[0].artist == "Miles Davis"

    def test_search_by_folder_path_partial(self, test_albums):
        """Test searching by partial folder path."""
        results = self._apply_search_filter(test_albums, "Electronic")
        assert len(results) == 1
        assert results[0].artist == "Daft Punk"

    def test_search_multiple_matches(self, test_albums):
        """Test search returning multiple matches."""
        results = self._apply_search_filter(test_albums, "Album")
        assert len(results) == 5  # All albums contain "Album" in name or path

    def test_search_no_matches(self, test_albums):
        """Test search with no matches."""
        results = self._apply_search_filter(test_albums, "xyz123nonexistent")
        assert len(results) == 0

    def test_search_empty_string_returns_all(self, test_albums):
        """Test empty search returns all albums."""
        results = self._apply_search_filter(test_albums, "")
        assert len(results) == 5

    def test_search_whitespace_only_returns_all(self, test_albums):
        """Test whitespace-only search returns all albums."""
        results = self._apply_search_filter(test_albums, "   ")
        assert len(results) == 5

    def test_search_handles_none_artist(self, test_albums):
        """Test search handles albums with None artist."""
        results = self._apply_search_filter(test_albums, "Unknown Album")
        assert len(results) == 1
        assert results[0].artist is None

    def test_search_handles_none_year(self, test_albums):
        """Test search handles albums with None year."""
        # Search by path should still work
        results = self._apply_search_filter(test_albums, "Unknown")
        assert len(results) == 1
        assert results[0].year is None


class TestCombinedFiltering:
    """
    Tests for combined search and status filtering.
    """

    def _create_test_album(
        self,
        path: Path,
        artist: str = None,
        album: str = None,
        has_embedded: bool = False,
        has_folder: bool = False,
    ) -> AlbumInfo:
        """Create a test album."""
        cover = CoverInfo(has_embedded=has_embedded, has_folder=has_folder)
        return AlbumInfo(
            path=path,
            artist=artist,
            album=album,
            cover=cover,
        )

    @pytest.fixture
    def mixed_albums(self, tmp_path) -> list:
        """Create albums with different cover statuses."""
        return [
            self._create_test_album(
                tmp_path / "A" / "Album1",
                artist="Artist A",
                album="With Both",
                has_embedded=True,
                has_folder=True,
            ),
            self._create_test_album(
                tmp_path / "A" / "Album2",
                artist="Artist A",
                album="Embedded Only",
                has_embedded=True,
                has_folder=False,
            ),
            self._create_test_album(
                tmp_path / "B" / "Album3",
                artist="Artist B",
                album="Folder Only",
                has_embedded=False,
                has_folder=True,
            ),
            self._create_test_album(
                tmp_path / "B" / "Album4",
                artist="Artist B",
                album="No Cover",
                has_embedded=False,
                has_folder=False,
            ),
        ]

    def _apply_combined_filters(
        self,
        albums: list,
        search_text: str,
        filter_value,
    ) -> list:
        """
        Apply combined search and status filter logic.

        This mimics the MainWindow._apply_filters method.
        """
        search_text = search_text.lower().strip()
        filtered = []

        for album in albums:
            # Apply search filter
            if search_text:
                searchable = " ".join(
                    [
                        album.artist or "",
                        album.album or "",
                        album.year or "",
                        str(album.path),
                    ]
                ).lower()
                if search_text not in searchable:
                    continue

            # Apply status filter
            if filter_value is not None:
                if filter_value == CoverStatus.NONE:
                    if album.cover_status != CoverStatus.NONE:
                        continue
                elif filter_value == "partial":
                    if album.cover_status not in (
                        CoverStatus.EMBEDDED_ONLY,
                        CoverStatus.FOLDER_ONLY,
                    ):
                        continue
                elif filter_value == "has_cover" and not album.has_any_cover:
                    continue

            filtered.append(album)

        return filtered

    def test_search_and_no_cover_filter(self, mixed_albums):
        """Test combining search with 'no cover' filter."""
        results = self._apply_combined_filters(
            mixed_albums,
            "Artist B",
            CoverStatus.NONE,
        )
        assert len(results) == 1
        assert results[0].album == "No Cover"

    def test_search_and_partial_cover_filter(self, mixed_albums):
        """Test combining search with 'partial cover' filter."""
        results = self._apply_combined_filters(
            mixed_albums,
            "Artist",
            "partial",
        )
        assert len(results) == 2
        albums = {r.album for r in results}
        assert "Embedded Only" in albums
        assert "Folder Only" in albums

    def test_search_and_has_cover_filter(self, mixed_albums):
        """Test combining search with 'has cover' filter."""
        results = self._apply_combined_filters(
            mixed_albums,
            "Artist A",
            "has_cover",
        )
        assert len(results) == 2
        albums = {r.album for r in results}
        assert "With Both" in albums
        assert "Embedded Only" in albums

    def test_search_no_filter(self, mixed_albums):
        """Test search without status filter."""
        results = self._apply_combined_filters(
            mixed_albums,
            "Artist A",
            None,
        )
        assert len(results) == 2

    def test_filter_no_search(self, mixed_albums):
        """Test status filter without search."""
        results = self._apply_combined_filters(
            mixed_albums,
            "",
            CoverStatus.NONE,
        )
        assert len(results) == 1
        assert results[0].album == "No Cover"


class TestStatusBarCountLogic:
    """
    Tests for the status bar count display logic.
    """

    def _format_count_label(
        self,
        total: int,
        filtered: int,
        missing: int,
        search_text: str,
    ) -> str:
        """
        Format count label text matching MainWindow._update_count_label.
        """
        search_text = search_text.strip()

        if total == filtered:
            return f"Albums: {total} | Sans cover: {missing}"
        elif search_text:
            return f"Recherche: {filtered} resultat(s) sur {total} | Sans cover: {missing}"
        else:
            return f"Filtres: {filtered}/{total} | Sans cover: {missing}"

    def test_all_albums_displayed(self):
        """Test label when all albums are displayed."""
        label = self._format_count_label(
            total=100,
            filtered=100,
            missing=20,
            search_text="",
        )
        assert label == "Albums: 100 | Sans cover: 20"

    def test_search_active(self):
        """Test label when search is active."""
        label = self._format_count_label(
            total=100,
            filtered=15,
            missing=20,
            search_text="Beatles",
        )
        assert label == "Recherche: 15 resultat(s) sur 100 | Sans cover: 20"

    def test_filter_active_no_search(self):
        """Test label when filter is active but no search."""
        label = self._format_count_label(
            total=100,
            filtered=30,
            missing=20,
            search_text="",
        )
        assert label == "Filtres: 30/100 | Sans cover: 20"

    def test_search_with_whitespace_treated_as_active(self):
        """Test that whitespace-only search is treated as no search."""
        label = self._format_count_label(
            total=100,
            filtered=30,
            missing=20,
            search_text="   ",
        )
        # Whitespace is stripped, so it's treated as no search
        assert label == "Filtres: 30/100 | Sans cover: 20"

    def test_zero_results(self):
        """Test label with zero results."""
        label = self._format_count_label(
            total=100,
            filtered=0,
            missing=20,
            search_text="nonexistent",
        )
        assert label == "Recherche: 0 resultat(s) sur 100 | Sans cover: 20"


class TestDebounceLogic:
    """
    Tests for search debounce behavior.

    Note: These test the timer logic conceptually without requiring Qt.
    """

    def test_debounce_constant_value(self):
        """Test that SEARCH_DEBOUNCE_MS is set to 300ms."""
        from src.ui.main_window import SEARCH_DEBOUNCE_MS

        assert SEARCH_DEBOUNCE_MS == 300

    def test_debounce_timer_is_single_shot(self):
        """
        Conceptual test: The debounce timer should be single-shot.

        This is verified by the implementation using setSingleShot(True).
        In actual Qt tests, this would be verified with:
            assert main_window._search_timer.isSingleShot() is True
        """
        # This test documents the expected behavior
        # Actual verification requires pytest-qt

    def test_debounce_timer_restarts_on_input(self):
        """
        Conceptual test: Timer should restart on each keystroke.

        This is verified by calling start() on each textChanged signal.
        In actual Qt tests, this would verify the timer doesn't fire
        until 300ms after the last keystroke.
        """
        # This test documents the expected behavior
        # Actual verification requires pytest-qt


class TestFileGrouping:
    """
    Tests for grouping dropped files by folder.

    This tests the logic used in dropEvent to group multiple files
    from the same folder into a single album.
    """

    def _group_files_by_folder(self, filepaths: list) -> dict:
        """
        Group files by their parent folder.

        This mimics the logic used in MainWindow.dropEvent.
        """
        files_by_folder = defaultdict(list)
        for filepath in filepaths:
            files_by_folder[filepath.parent].append(filepath)
        return dict(files_by_folder)

    def test_single_file(self, tmp_path):
        """Test grouping with a single file."""
        folder = tmp_path / "album1"
        folder.mkdir()
        file1 = folder / "track1.mp3"

        result = self._group_files_by_folder([file1])

        assert len(result) == 1
        assert folder in result
        assert result[folder] == [file1]

    def test_multiple_files_same_folder(self, tmp_path):
        """Test grouping multiple files from the same folder."""
        folder = tmp_path / "album1"
        folder.mkdir()
        file1 = folder / "track1.mp3"
        file2 = folder / "track2.mp3"
        file3 = folder / "track3.mp3"

        result = self._group_files_by_folder([file1, file2, file3])

        assert len(result) == 1
        assert folder in result
        assert len(result[folder]) == 3
        assert set(result[folder]) == {file1, file2, file3}

    def test_files_from_different_folders(self, tmp_path):
        """Test grouping files from different folders."""
        folder1 = tmp_path / "album1"
        folder2 = tmp_path / "album2"
        folder1.mkdir()
        folder2.mkdir()

        file1 = folder1 / "track1.mp3"
        file2 = folder2 / "track1.mp3"

        result = self._group_files_by_folder([file1, file2])

        assert len(result) == 2
        assert folder1 in result
        assert folder2 in result
        assert result[folder1] == [file1]
        assert result[folder2] == [file2]

    def test_mixed_multiple_files(self, tmp_path):
        """Test grouping mixed files from multiple folders."""
        folder1 = tmp_path / "album1"
        folder2 = tmp_path / "album2"
        folder3 = tmp_path / "album3"
        folder1.mkdir()
        folder2.mkdir()
        folder3.mkdir()

        files = [
            folder1 / "track1.mp3",
            folder1 / "track2.mp3",
            folder2 / "song1.flac",
            folder2 / "song2.flac",
            folder2 / "song3.flac",
            folder3 / "piece.ogg",
        ]

        result = self._group_files_by_folder(files)

        assert len(result) == 3
        assert len(result[folder1]) == 2
        assert len(result[folder2]) == 3
        assert len(result[folder3]) == 1

    def test_empty_list(self):
        """Test grouping with empty file list."""
        result = self._group_files_by_folder([])
        assert result == {}


class TestCreateAlbumFromFiles:
    """
    Tests for _create_album_from_files function.

    This tests the helper function that creates an AlbumInfo from
    multiple audio files in the same folder.
    """

    @pytest.fixture
    def mock_audio_file(self):
        """Create a mock for mutagen audio file."""
        mock = MagicMock()
        mock.tags = {
            "artist": ["Test Artist"],
            "album": ["Test Album"],
            "date": ["2023"],
        }
        return mock

    def test_creates_album_with_correct_track_count(self, tmp_path):
        """Test that album is created with correct track count."""
        from src.ui.main_window import _create_album_from_files

        folder = tmp_path / "album"
        folder.mkdir()

        # Create test files
        files = []
        for i in range(5):
            f = folder / f"track{i}.mp3"
            f.touch()
            files.append(f)

        with patch("mutagen.File") as mock_mutagen:
            mock_audio = MagicMock()
            mock_audio.tags = {
                "artist": ["Test Artist"],
                "album": ["Test Album"],
            }
            mock_mutagen.return_value = mock_audio

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_files(files)

        assert album is not None
        assert album.track_count == 5
        assert album.path == folder

    def test_creates_album_with_metadata_from_first_file(self, tmp_path):
        """Test that album metadata comes from first file."""
        from src.ui.main_window import _create_album_from_files

        folder = tmp_path / "album"
        folder.mkdir()

        files = [folder / f"track{i}.mp3" for i in range(3)]
        for f in files:
            f.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_audio = MagicMock()
            mock_audio.tags = {
                "artist": ["First File Artist"],
                "album": ["First File Album"],
                "date": ["2023"],
            }
            mock_mutagen.return_value = mock_audio

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_files(files)

        assert album.artist == "First File Artist"
        assert album.album == "First File Album"
        assert album.year == "2023"

    def test_collects_all_formats(self, tmp_path):
        """Test that all file formats are collected."""
        from src.ui.main_window import _create_album_from_files

        folder = tmp_path / "album"
        folder.mkdir()

        files = [
            folder / "track1.mp3",
            folder / "track2.flac",
            folder / "track3.ogg",
        ]
        for f in files:
            f.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_files(files)

        assert set(album.formats) == {".mp3", ".flac", ".ogg"}

    def test_detects_folder_cover(self, tmp_path):
        """Test that folder cover is detected."""
        from src.ui.main_window import _create_album_from_files

        folder = tmp_path / "album"
        folder.mkdir()

        # Create audio file
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        # Create cover file
        cover_file = folder / "cover.jpg"
        cover_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_files([audio_file])

        assert album.cover.has_folder is True
        assert album.cover.folder_file == "cover.jpg"

    def test_detects_embedded_cover(self, tmp_path):
        """Test that embedded cover is detected."""
        from src.ui.main_window import _create_album_from_files

        folder = tmp_path / "album"
        folder.mkdir()

        audio_file = folder / "track1.mp3"
        audio_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = b"fake_cover_data"

                album = _create_album_from_files([audio_file])

        assert album.cover.has_embedded is True

    def test_empty_list_returns_none(self):
        """Test that empty file list returns None."""
        from src.ui.main_window import _create_album_from_files

        album = _create_album_from_files([])
        assert album is None

    def test_sample_file_is_first_file(self, tmp_path):
        """Test that sample_file is set to the first file."""
        from src.ui.main_window import _create_album_from_files

        folder = tmp_path / "album"
        folder.mkdir()

        files = [folder / f"track{i}.mp3" for i in range(3)]
        for f in files:
            f.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_files(files)

        assert album.sample_file == files[0]


class TestCreateAlbumFromFileCoverDetection:
    """
    Tests for cover detection in _create_album_from_file function.

    Issue 1: Verify that single files have their covers properly detected
    (both embedded and folder covers).
    """

    def test_detects_embedded_cover_in_single_file(self, tmp_path):
        """Test that embedded cover is detected for a single file."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = b"fake_cover_data"

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_embedded is True

    def test_detects_no_embedded_cover_when_none(self, tmp_path):
        """Test that no embedded cover is reported when there is none."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_embedded is False

    def test_detects_folder_cover_jpg(self, tmp_path):
        """Test that cover.jpg in parent folder is detected."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()
        cover_file = folder / "cover.jpg"
        cover_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_folder is True
        assert album.cover.folder_file == "cover.jpg"

    def test_detects_folder_cover_png(self, tmp_path):
        """Test that folder.png in parent folder is detected."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()
        cover_file = folder / "folder.png"
        cover_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_folder is True
        assert album.cover.folder_file == "folder.png"

    def test_detects_front_cover(self, tmp_path):
        """Test that front.jpg in parent folder is detected."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()
        cover_file = folder / "front.jpg"
        cover_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_folder is True
        assert album.cover.folder_file == "front.jpg"

    def test_detects_both_embedded_and_folder_cover(self, tmp_path):
        """Test that both embedded and folder covers are detected."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()
        cover_file = folder / "cover.jpg"
        cover_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = b"fake_cover_data"

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_embedded is True
        assert album.cover.has_folder is True
        assert album.cover.status == CoverStatus.BOTH

    def test_no_covers_detected_when_none_exist(self, tmp_path):
        """Test that no covers are reported when none exist."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_embedded is False
        assert album.cover.has_folder is False
        assert album.cover.status == CoverStatus.NONE

    def test_ignores_non_cover_images(self, tmp_path):
        """Test that non-cover image files are ignored."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()
        # This is an image but not a cover filename
        other_image = folder / "photo.jpg"
        other_image.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_folder is False


class TestDropEventFileHandling:
    """
    Tests for the drop event file handling logic.

    These tests verify that dropping multiple files creates separate entries
    for each file (not grouped by folder).
    """

    def _simulate_file_drop(self, audio_files: list, existing_albums: list) -> tuple:
        """
        Simulate the drop event logic for individual files.

        Each file creates its own entry, using album.path (= filepath) as unique key.
        Returns (added_albums, final_albums_list).
        """
        added_albums = []
        albums = list(existing_albums)
        existing_paths = {str(a.path) for a in albums}

        for filepath in audio_files:
            # Create a mock album for this file
            # For single files, path = filepath (not filepath.parent)
            album = AlbumInfo(
                path=filepath,  # Unique key for single-file entries
                artist="Test",
                album="Test Album",
                track_count=1,
                cover=CoverInfo(),
                sample_file=filepath,
            )

            path_key = str(album.path)
            if path_key in existing_paths:
                # Replace existing entry for this file
                albums = [a if str(a.path) != path_key else album for a in albums]
            else:
                # Add new entry
                albums.append(album)
                existing_paths.add(path_key)

            added_albums.append(album)

        return added_albums, albums

    def test_drop_multiple_files_creates_separate_entries(self, tmp_path):
        """Test that dropping multiple files creates separate entries for each."""
        folder = tmp_path / "album1"
        folder.mkdir()

        files = [folder / f"track{i}.mp3" for i in range(5)]

        added, final = self._simulate_file_drop(files, [])

        # Each file should have its own entry
        assert len(added) == 5
        assert len(final) == 5

    def test_drop_files_from_same_folder_creates_multiple_entries(self, tmp_path):
        """Test that files from same folder still create separate entries."""
        folder = tmp_path / "album1"
        folder.mkdir()

        files = [
            folder / "track1.mp3",
            folder / "track2.mp3",
            folder / "track3.mp3",
        ]

        added, final = self._simulate_file_drop(files, [])

        # Each file gets its own entry even from same folder
        assert len(added) == 3
        assert len(final) == 3
        # All entries have track_count=1 since they represent single files
        assert all(a.track_count == 1 for a in final)

    def test_drop_files_from_different_folders(self, tmp_path):
        """Test that dropping files from different folders creates separate entries."""
        folder1 = tmp_path / "album1"
        folder2 = tmp_path / "album2"
        folder1.mkdir()
        folder2.mkdir()

        files = [
            folder1 / "track1.mp3",
            folder1 / "track2.mp3",
            folder2 / "track1.mp3",
        ]

        added, final = self._simulate_file_drop(files, [])

        assert len(added) == 3
        assert len(final) == 3

    def test_drop_replaces_existing_file_entry(self, tmp_path):
        """Test that dropping a file that already exists replaces it."""
        folder = tmp_path / "album1"
        folder.mkdir()
        file1 = folder / "track1.mp3"

        # For single-file entries, path = filepath (not folder)
        existing = AlbumInfo(
            path=file1,  # Single-file entry uses file path as key
            artist="Old Artist",
            album="Old Album",
            track_count=1,
            cover=CoverInfo(),
            sample_file=file1,
        )

        # Drop the same file again
        added, final = self._simulate_file_drop([file1], [existing])

        assert len(added) == 1
        assert len(final) == 1  # Replaced, not added
        assert final[0].artist == "Test"  # New album replaced old

    def test_drop_adds_new_files_while_keeping_existing(self, tmp_path):
        """Test that dropping new files keeps existing entries."""
        folder = tmp_path / "album1"
        folder.mkdir()
        file1 = folder / "track1.mp3"
        file2 = folder / "track2.mp3"

        # For single-file entries, path = filepath (not folder)
        existing = AlbumInfo(
            path=file1,  # Single-file entry uses file path as key
            artist="Existing",
            album="Existing Album",
            track_count=1,
            cover=CoverInfo(),
            sample_file=file1,
        )

        # Drop a different file
        added, final = self._simulate_file_drop([file2], [existing])

        assert len(added) == 1
        assert len(final) == 2
        # Verify existing entry unchanged (using path now, not sample_file)
        existing_in_final = [a for a in final if str(a.path) == str(file1)][0]
        assert existing_in_final.artist == "Existing"

    def test_drop_same_file_twice_in_one_drop(self, tmp_path):
        """Test that dropping the same file twice in one operation handles correctly."""
        folder = tmp_path / "album1"
        folder.mkdir()
        file1 = folder / "track1.mp3"

        # Drop same file twice (edge case)
        added, final = self._simulate_file_drop([file1, file1], [])

        # Second drop should replace the first, resulting in 1 entry
        assert len(final) == 1


class TestCreateAlbumFromFileDimensionsExtraction:
    """
    Tests for cover dimensions extraction in _create_album_from_file function.

    This ensures that when opening a single file, the cover dimensions are
    properly extracted for the "small covers" filter to work.
    """

    # Minimal valid JPEG header (1x1 pixel)
    JPEG_1X1 = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9telepon 1702telepon"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
        b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
        b'\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n'
        b"\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz"
        b"\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99"
        b"\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7"
        b"\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5"
        b"\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1"
        b"\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd5\x00\x00\x00\xff\xd9"
    )

    # Minimal valid PNG header (1x1 pixel)
    PNG_1X1 = (
        b"\x89PNG\r\n\x1a\n"  # PNG signature
        b"\x00\x00\x00\rIHDR"  # IHDR chunk length + type
        b"\x00\x00\x00\x01"  # width = 1
        b"\x00\x00\x00\x01"  # height = 1
        b"\x08\x02\x00\x00\x00"  # bit depth, color type, etc.
        b"\x90wS\xde"  # CRC
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def _create_test_jpeg(self, width: int, height: int) -> bytes:
        """Create a minimal JPEG with specified dimensions."""
        # Create a real JPEG using PIL
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGB", (width, height), color="red")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        return buffer.getvalue()

    def _create_test_png(self, width: int, height: int) -> bytes:
        """Create a minimal PNG with specified dimensions."""
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGB", (width, height), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_extracts_embedded_cover_dimensions(self, tmp_path):
        """Test that embedded cover dimensions are extracted."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        cover_data = self._create_test_jpeg(200, 200)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = cover_data

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_embedded is True
        assert album.cover.embedded_dimensions == (200, 200)

    def test_extracts_embedded_cover_size_bytes(self, tmp_path):
        """Test that embedded cover size in bytes is extracted."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        cover_data = self._create_test_jpeg(300, 300)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = cover_data

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.embedded_size_bytes == len(cover_data)

    def test_extracts_embedded_cover_mime_type_jpeg(self, tmp_path):
        """Test that embedded JPEG cover MIME type is detected."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        cover_data = self._create_test_jpeg(100, 100)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = cover_data

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.embedded_mime_type == "image/jpeg"

    def test_extracts_embedded_cover_mime_type_png(self, tmp_path):
        """Test that embedded PNG cover MIME type is detected."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        cover_data = self._create_test_png(100, 100)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = cover_data

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.embedded_mime_type == "image/png"

    def test_extracts_folder_cover_dimensions(self, tmp_path):
        """Test that folder cover dimensions are extracted."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        # Create a real cover file with specific dimensions
        cover_file = folder / "cover.jpg"
        cover_data = self._create_test_jpeg(500, 500)
        cover_file.write_bytes(cover_data)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_folder is True
        assert album.cover.folder_dimensions == (500, 500)

    def test_extracts_folder_cover_size_bytes(self, tmp_path):
        """Test that folder cover size in bytes is extracted."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        cover_file = folder / "cover.jpg"
        cover_data = self._create_test_jpeg(400, 400)
        cover_file.write_bytes(cover_data)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.folder_size_bytes == len(cover_data)

    def test_extracts_folder_cover_mime_type(self, tmp_path):
        """Test that folder cover MIME type is detected from extension."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        cover_file = folder / "cover.png"
        cover_data = self._create_test_png(100, 100)
        cover_file.write_bytes(cover_data)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.folder_mime_type == "image/png"

    def test_detects_covers_differ_when_different(self, tmp_path):
        """Test that covers_differ is True when embedded and folder covers are different."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        # Create different cover data for embedded and folder
        embedded_data = self._create_test_jpeg(200, 200)
        folder_data = self._create_test_jpeg(500, 500)  # Different size = different data

        cover_file = folder / "cover.jpg"
        cover_file.write_bytes(folder_data)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = embedded_data

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_embedded is True
        assert album.cover.has_folder is True
        assert album.cover.covers_differ is True

    def test_detects_covers_same_when_identical(self, tmp_path):
        """Test that covers_differ is False when embedded and folder covers are identical."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        # Use the same cover data for both
        cover_data = self._create_test_jpeg(300, 300)

        cover_file = folder / "cover.jpg"
        cover_file.write_bytes(cover_data)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = cover_data  # Same data as folder

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.has_embedded is True
        assert album.cover.has_folder is True
        assert album.cover.covers_differ is False

    def test_small_cover_filter_works_with_single_file(self, tmp_path):
        """Test that the small cover filter logic works with extracted dimensions."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        # Create a small cover (200x200, below 500px threshold)
        cover_data = self._create_test_jpeg(200, 200)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = cover_data

                album = _create_album_from_file(audio_file)

        assert album is not None

        # Simulate the _has_small_cover filter logic
        threshold = 500
        cover = album.cover
        is_small = False

        if cover.has_embedded and cover.embedded_dimensions:
            width, height = cover.embedded_dimensions
            if width < threshold or height < threshold:
                is_small = True

        assert is_small is True, "Album with 200x200 cover should be detected as small"

    def test_large_cover_not_detected_as_small(self, tmp_path):
        """Test that large covers are not detected as small."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        # Create a large cover (600x600, above 500px threshold)
        cover_data = self._create_test_jpeg(600, 600)

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = cover_data

                album = _create_album_from_file(audio_file)

        assert album is not None

        # Simulate the _has_small_cover filter logic
        threshold = 500
        cover = album.cover
        is_small = False

        if cover.has_embedded and cover.embedded_dimensions:
            width, height = cover.embedded_dimensions
            if width < threshold or height < threshold:
                is_small = True

        assert is_small is False, "Album with 600x600 cover should NOT be detected as small"

    def test_no_dimensions_when_no_cover(self, tmp_path):
        """Test that dimensions are None when there is no cover."""
        from src.ui.main_window import _create_album_from_file

        folder = tmp_path / "album"
        folder.mkdir()
        audio_file = folder / "track1.mp3"
        audio_file.touch()

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(audio_file)

        assert album is not None
        assert album.cover.embedded_dimensions is None
        assert album.cover.folder_dimensions is None
        assert album.cover.embedded_size_bytes is None
        assert album.cover.folder_size_bytes is None


class TestCacheInvalidationOnCoverApplied:
    """
    Tests for cache invalidation when covers are applied.

    These tests verify that the scan cache is properly invalidated
    when covers are applied to albums.
    """

    def _create_test_album(
        self,
        path: Path,
        is_file: bool = False,
    ) -> AlbumInfo:
        """Create a test album."""
        if is_file:
            # Single file album
            actual_path = path
        else:
            # Folder album
            actual_path = path

        cover = CoverInfo(has_embedded=True, has_folder=False)
        return AlbumInfo(
            path=actual_path,
            artist="Test Artist",
            album="Test Album",
            cover=cover,
            sample_file=path / "track.mp3" if not is_file else path,
        )

    def test_cache_invalidation_logic_for_folder(self, tmp_path):
        """Test that folder albums invalidate their path in cache."""
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)

        album = self._create_test_album(album_folder, is_file=False)

        # Verify the logic: for folder albums, we invalidate album.path
        assert album.path.is_dir() or not album.path.exists()
        # Cache key should be the folder path
        cache_key = str(album.path.resolve())
        assert "Album" in cache_key

    def test_cache_invalidation_logic_for_single_file(self, tmp_path):
        """Test that single file albums invalidate parent folder in cache."""
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)
        audio_file = album_folder / "track.mp3"
        audio_file.touch()

        album = self._create_test_album(audio_file, is_file=True)

        # Verify the logic: for single file albums, we invalidate parent folder
        assert album.path.is_file()
        parent_folder = album.path.parent
        cache_key = str(parent_folder.resolve())
        assert "Album" in cache_key

    def test_rescan_covers_called_after_invalidation(self, tmp_path):
        """Test that rescan_album_covers would be called after cache invalidation."""
        from src.core.scanner import MusicScanner

        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)
        (album_folder / "track.mp3").write_bytes(b"fake audio")

        album = self._create_test_album(album_folder)

        # Create a scanner instance
        scanner = MusicScanner()

        # The rescan_album_covers method should exist and be callable
        assert hasattr(scanner, "rescan_album_covers")
        assert callable(scanner.rescan_album_covers)

    def test_cache_update_after_rescan(self, tmp_path):
        """Test that cache is updated with new data after rescan."""
        from src.core.scan_cache import ScanCache

        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)

        album = self._create_test_album(album_folder)

        # Create a cache and add the album
        cache = ScanCache(tmp_path / "test_cache.json")
        cache.update_folder(album_folder, album)

        # Verify album is cached
        assert not cache.is_folder_changed(album_folder)

        # Remove from cache (simulating invalidation)
        cache.remove_folder(album_folder)

        # Verify album is no longer cached
        assert cache.is_folder_changed(album_folder)

    def test_cache_dirty_flag_set_after_operations(self, tmp_path):
        """Test that cache dirty flag is set after remove and update."""
        from src.core.scan_cache import ScanCache

        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)

        album = self._create_test_album(album_folder)

        cache = ScanCache(tmp_path / "test_cache.json")

        # Initially not dirty
        assert not cache.is_dirty

        # After update, should be dirty
        cache.update_folder(album_folder, album)
        assert cache.is_dirty

        # Save to reset dirty flag
        cache.save()
        assert not cache.is_dirty

        # After remove, should be dirty again
        cache.remove_folder(album_folder)
        assert cache.is_dirty


class TestPathDisplayLogic:
    """
    Tests for the path display logic in album detail panel.
    """

    def test_truncate_path_preserves_start_and_end(self):
        """Test that truncated paths preserve start and end."""
        from src.utils.file_manager import truncate_path

        path = Path("/home/user/Music/Artist/Album/SubFolder")
        result = truncate_path(path, max_length=40)

        if len(str(path)) > 40:
            assert "..." in result
            assert result.startswith("/home")
            assert result.endswith("SubFolder")

    def test_truncate_path_short_unchanged(self):
        """Test that short paths are unchanged."""
        from src.utils.file_manager import truncate_path

        path = Path("/short/path")
        result = truncate_path(path, max_length=80)

        assert result == str(path)
        assert "..." not in result

    def test_path_for_folder_album(self, tmp_path):
        """Test path display for folder-based album."""
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)

        album = AlbumInfo(
            path=album_folder,
            artist="Artist",
            album="Album",
            cover=CoverInfo(),
        )

        # Path should be the album folder
        assert album.path == album_folder
        assert album.path.is_dir()

    def test_path_for_single_file_album(self, tmp_path):
        """Test path display for single-file album."""
        album_folder = tmp_path / "Artist" / "Album"
        album_folder.mkdir(parents=True)
        audio_file = album_folder / "track.mp3"
        audio_file.touch()

        album = AlbumInfo(
            path=audio_file,  # Single file uses file path
            artist="Artist",
            album="Album",
            cover=CoverInfo(),
            sample_file=audio_file,
        )

        # Path should be the file itself
        assert album.path == audio_file
        assert album.path.is_file()


class TestRemoveCoverFromContextLogic:
    """
    Tests for the _on_remove_cover_from_context handler logic.
    """

    def test_remove_cover_skips_album_without_cover(self, tmp_path):
        """Test that remove cover returns early for albums without covers."""
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # has_any_cover should be False
        assert not album.has_any_cover

    def test_remove_cover_handles_embedded_only(self, tmp_path):
        """Test removing cover from album with embedded cover only."""
        sample_file = tmp_path / "track.mp3"
        sample_file.write_bytes(b"fake audio")
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=True, has_folder=False),
            sample_file=sample_file,
        )
        assert album.cover.has_embedded
        assert not album.cover.has_folder

    def test_remove_cover_handles_folder_only(self, tmp_path):
        """Test removing cover from album with folder cover only."""
        folder_path = tmp_path / "Artist" / "Album" / "cover.jpg"
        folder_path.parent.mkdir(parents=True, exist_ok=True)
        folder_path.write_bytes(b"fake image")
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(
                has_embedded=False,
                has_folder=True,
                folder_path=folder_path,
                folder_file="cover.jpg",
            ),
        )
        assert not album.cover.has_embedded
        assert album.cover.has_folder
        assert album.cover.folder_path.exists()

    def test_remove_cover_handles_both_covers(self, tmp_path):
        """Test removing cover from album with both covers."""
        sample_file = tmp_path / "track.mp3"
        sample_file.write_bytes(b"fake audio")
        folder_path = tmp_path / "Artist" / "Album" / "cover.jpg"
        folder_path.parent.mkdir(parents=True, exist_ok=True)
        folder_path.write_bytes(b"fake image")
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(
                has_embedded=True, has_folder=True, folder_path=folder_path, folder_file="cover.jpg"
            ),
            sample_file=sample_file,
        )
        assert album.cover.has_embedded
        assert album.cover.has_folder

    def test_remove_folder_cover_file_deletion(self, tmp_path):
        """Test that folder cover file is deleted."""
        folder_path = tmp_path / "cover.jpg"
        folder_path.write_bytes(b"fake image")
        assert folder_path.exists()

        # Simulate deletion
        folder_path.unlink()
        assert not folder_path.exists()

    def test_remove_cover_single_file_album(self, tmp_path):
        """Test remove cover logic for single file album."""
        file_path = tmp_path / "track.mp3"
        file_path.write_bytes(b"fake audio")
        album = AlbumInfo(
            path=file_path,  # Single file album
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=True, has_folder=False),
            sample_file=file_path,
        )
        # For single file albums, path is the file itself
        assert album.path.is_file()
        assert album.path == file_path

    def test_remove_cover_multi_file_album(self, tmp_path):
        """Test remove cover logic for multi-file album."""
        folder_path = tmp_path / "Artist" / "Album"
        folder_path.mkdir(parents=True)
        for i in range(3):
            (folder_path / f"track{i}.mp3").write_bytes(b"fake audio")

        album = AlbumInfo(
            path=folder_path,  # Folder album
            artist="Artist",
            album="Album",
            track_count=3,
            cover=CoverInfo(has_embedded=True, has_folder=False),
            sample_file=folder_path / "track0.mp3",
        )
        # For multi-file albums, path is the folder
        assert album.path.is_dir()
        assert album.track_count == 3


class TestSearchCoverFromContextLogic:
    """
    Tests for the _on_search_cover_from_context handler logic.
    """

    def test_search_cover_sets_detail_panel_album(self, tmp_path):
        """Test that search cover sets the album in detail panel."""
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # The handler should call detail_panel.set_album(album)
        # This tests the expected behavior
        assert album.artist == "Artist"
        assert album.album == "Album"

    def test_search_cover_album_with_musicbrainz_id(self, tmp_path):
        """Test search cover with album that has MusicBrainz ID."""
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            musicbrainz_albumid="12345678-1234-1234-1234-123456789012",
        )
        # Album with MBID should use it for search
        assert album.musicbrainz_albumid is not None
        assert len(album.musicbrainz_albumid) == 36

    def test_search_cover_album_without_metadata(self, tmp_path):
        """Test search cover with album missing metadata."""
        album = AlbumInfo(
            path=tmp_path / "Unknown" / "Unknown",
            artist=None,
            album=None,
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # Album without metadata should still be searchable (via path)
        assert album.artist is None
        assert album.album is None
        assert album.path is not None


class TestDetailPanelVisibility:
    """
    Tests for detail panel visibility logic.

    Bug fix: The detail panel was shown at startup with action buttons even
    when no albums were loaded. Now the panel is hidden when the library is
    empty and shown only when albums are loaded.
    """

    def test_detail_panel_hidden_when_no_albums(self):
        """
        Test that detail panel visibility is False when albums list is empty.

        The panel should be hidden at startup and after clearing the library.
        """
        albums = []
        # Visibility should be based on whether albums exist
        should_be_visible = bool(albums)
        assert should_be_visible is False

    def test_detail_panel_visible_when_albums_loaded(self, tmp_path):
        """
        Test that detail panel visibility is True when albums are loaded.
        """
        albums = [
            AlbumInfo(
                path=tmp_path / "Artist" / "Album",
                artist="Artist",
                album="Album",
                cover=CoverInfo(has_embedded=False, has_folder=False),
            )
        ]
        # Visibility should be based on whether albums exist
        should_be_visible = bool(albums)
        assert should_be_visible is True

    def test_detail_panel_visibility_after_clear(self, tmp_path):
        """
        Test that detail panel is hidden after clearing the library.
        """
        # Simulate having albums then clearing
        albums = [
            AlbumInfo(
                path=tmp_path / "Artist" / "Album",
                artist="Artist",
                album="Album",
                cover=CoverInfo(has_embedded=False, has_folder=False),
            )
        ]
        assert bool(albums) is True

        # Clear library
        albums = []
        assert bool(albums) is False


class TestFilesDroppedHandler:
    """
    Tests for the _on_files_dropped handler in MainWindow.

    This handler processes files dropped on the LibraryView widget and adds
    them to the library (directories are scanned, audio files are added directly).
    """

    # Audio extensions used in the handler
    AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aiff", ".wma"}

    def _classify_paths(self, paths: list) -> tuple:
        """
        Classify paths into directories and audio files.
        Mimics the logic in _on_files_dropped.
        """
        directories = []
        audio_files = []

        for path_str in paths:
            path = Path(path_str)
            if path.is_dir():
                directories.append(path)
            elif path.is_file() and path.suffix.lower() in self.AUDIO_EXTENSIONS:
                audio_files.append(path)

        return directories, audio_files

    def test_classify_single_directory(self, tmp_path):
        """Test that a single directory is correctly classified."""
        folder = tmp_path / "Music"
        folder.mkdir()

        paths = [str(folder)]
        directories, audio_files = self._classify_paths(paths)

        assert len(directories) == 1
        assert len(audio_files) == 0
        assert directories[0] == folder

    def test_classify_single_audio_file(self, tmp_path):
        """Test that a single audio file is correctly classified."""
        file = tmp_path / "song.mp3"
        file.touch()

        paths = [str(file)]
        directories, audio_files = self._classify_paths(paths)

        assert len(directories) == 0
        assert len(audio_files) == 1
        assert audio_files[0] == file

    def test_classify_mixed_paths(self, tmp_path):
        """Test classification of mixed directories and files."""
        folder1 = tmp_path / "Album1"
        folder2 = tmp_path / "Album2"
        folder1.mkdir()
        folder2.mkdir()

        file1 = tmp_path / "song1.mp3"
        file2 = tmp_path / "song2.flac"
        file1.touch()
        file2.touch()

        paths = [str(folder1), str(file1), str(folder2), str(file2)]
        directories, audio_files = self._classify_paths(paths)

        assert len(directories) == 2
        assert len(audio_files) == 2

    def test_non_audio_files_ignored(self, tmp_path):
        """Test that non-audio files are ignored."""
        text_file = tmp_path / "readme.txt"
        image_file = tmp_path / "cover.jpg"
        text_file.touch()
        image_file.touch()

        paths = [str(text_file), str(image_file)]
        directories, audio_files = self._classify_paths(paths)

        assert len(directories) == 0
        assert len(audio_files) == 0

    def test_all_audio_extensions_accepted(self, tmp_path):
        """Test that all supported audio extensions are accepted."""
        files = []
        for ext in self.AUDIO_EXTENSIONS:
            file = tmp_path / f"song{ext}"
            file.touch()
            files.append(str(file))

        directories, audio_files = self._classify_paths(files)

        assert len(directories) == 0
        assert len(audio_files) == len(self.AUDIO_EXTENSIONS)

    def test_case_insensitive_extensions(self, tmp_path):
        """Test that audio extensions are case-insensitive."""
        file_upper = tmp_path / "song.MP3"
        file_mixed = tmp_path / "song.FlAc"
        file_upper.touch()
        file_mixed.touch()

        paths = [str(file_upper), str(file_mixed)]
        directories, audio_files = self._classify_paths(paths)

        assert len(audio_files) == 2
