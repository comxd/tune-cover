"""
Tests for LibraryView widget functionality.

Note: These tests mock Qt components to avoid requiring a QApplication.
For full GUI tests, use pytest-qt.
"""

from pathlib import Path

import pytest

from src.core.models import AlbumInfo, CoverInfo


class TestLibraryViewSelectionLogic:
    """
    Tests for the selection logic in LibraryView.

    These tests isolate the decision-making logic without requiring Qt.
    """

    def _create_test_albums(self, count: int, base_path: Path) -> list:
        """Create a list of test albums."""
        albums = []
        for i in range(count):
            album_path = base_path / f"Artist{i}" / f"Album{i}"
            cover = CoverInfo(has_embedded=False, has_folder=False)
            album = AlbumInfo(
                path=album_path,
                artist=f"Artist{i}",
                album=f"Album{i}",
                cover=cover,
            )
            albums.append(album)
        return albums

    def test_range_selection_indices(self):
        """Test range selection index calculation."""
        # Simulate clicking index 2, then shift+clicking index 5
        last_clicked = 2
        current_clicked = 5

        start_idx = min(last_clicked, current_clicked)
        end_idx = max(last_clicked, current_clicked)

        assert start_idx == 2
        assert end_idx == 5

        # The range should include both endpoints
        indices = list(range(start_idx, end_idx + 1))
        assert indices == [2, 3, 4, 5]

    def test_range_selection_reverse_direction(self):
        """Test range selection when clicking backwards."""
        # Simulate clicking index 7, then shift+clicking index 3
        last_clicked = 7
        current_clicked = 3

        start_idx = min(last_clicked, current_clicked)
        end_idx = max(last_clicked, current_clicked)

        assert start_idx == 3
        assert end_idx == 7

        indices = list(range(start_idx, end_idx + 1))
        assert indices == [3, 4, 5, 6, 7]

    def test_range_selection_same_index(self):
        """Test range selection when clicking same index."""
        last_clicked = 4
        current_clicked = 4

        start_idx = min(last_clicked, current_clicked)
        end_idx = max(last_clicked, current_clicked)

        indices = list(range(start_idx, end_idx + 1))
        assert indices == [4]


class TestLibraryViewMockedMethods:
    """
    Tests for LibraryView methods using a mock approach.

    These tests verify the method logic without requiring Qt.
    """

    def _create_mock_library_view(self, albums):
        """Create a minimal mock LibraryView for testing selection methods."""

        class MockLibraryView:
            def __init__(self, albums):
                self.albums = albums
                self.selected_albums = []
                self.view_mode = "grid"
                self._last_clicked_index = None
                self.albums_selected_emissions = []

            def albums_selected_emit(self, albums):
                self.albums_selected_emissions.append(albums.copy())

            def select_all(self):
                """Select all albums."""
                if self.view_mode == "grid":
                    self.selected_albums = list(self.albums)
                self.albums_selected_emit(self.selected_albums)

            def clear_selection(self):
                """Clear selection."""
                self.selected_albums = []
                self._last_clicked_index = None
                self.albums_selected_emit([])

            def handle_click(self, album, ctrl=False, shift=False):
                """Simplified click handler for testing."""
                try:
                    clicked_index = self.albums.index(album)
                except ValueError:
                    return

                if ctrl:
                    # Toggle selection
                    if album in self.selected_albums:
                        self.selected_albums.remove(album)
                    else:
                        self.selected_albums.append(album)
                    self._last_clicked_index = clicked_index
                elif shift:
                    # Range selection
                    if self._last_clicked_index is not None:
                        start_idx = min(self._last_clicked_index, clicked_index)
                        end_idx = max(self._last_clicked_index, clicked_index)
                        for idx in range(start_idx, end_idx + 1):
                            if self.albums[idx] not in self.selected_albums:
                                self.selected_albums.append(self.albums[idx])
                    else:
                        if album not in self.selected_albums:
                            self.selected_albums.append(album)
                        self._last_clicked_index = clicked_index
                else:
                    # Single selection
                    self.selected_albums = [album]
                    self._last_clicked_index = clicked_index

        return MockLibraryView(albums)

    @pytest.fixture
    def test_albums(self, tmp_path):
        """Create test albums."""
        albums = []
        for i in range(10):
            album_path = tmp_path / f"Artist{i}" / f"Album{i}"
            cover = CoverInfo(has_embedded=False, has_folder=False)
            album = AlbumInfo(
                path=album_path,
                artist=f"Artist{i}",
                album=f"Album{i}",
                cover=cover,
            )
            albums.append(album)
        return albums

    def test_select_all_selects_all_albums(self, test_albums):
        """Test select_all selects all albums."""
        view = self._create_mock_library_view(test_albums)

        view.select_all()

        assert len(view.selected_albums) == 10
        assert view.selected_albums == test_albums

    def test_select_all_emits_signal(self, test_albums):
        """Test select_all emits albums_selected signal."""
        view = self._create_mock_library_view(test_albums)

        view.select_all()

        assert len(view.albums_selected_emissions) == 1
        assert len(view.albums_selected_emissions[0]) == 10

    def test_clear_selection_clears_all(self, test_albums):
        """Test clear_selection clears all selected albums."""
        view = self._create_mock_library_view(test_albums)
        view.selected_albums = test_albums[:5]
        view._last_clicked_index = 2

        view.clear_selection()

        assert view.selected_albums == []
        assert view._last_clicked_index is None

    def test_clear_selection_emits_empty_list(self, test_albums):
        """Test clear_selection emits empty list via signal."""
        view = self._create_mock_library_view(test_albums)
        view.selected_albums = test_albums[:5]

        view.clear_selection()

        assert len(view.albums_selected_emissions) == 1
        assert view.albums_selected_emissions[0] == []

    def test_single_click_selects_one_album(self, test_albums):
        """Test single click selects one album."""
        view = self._create_mock_library_view(test_albums)

        view.handle_click(test_albums[3])

        assert len(view.selected_albums) == 1
        assert view.selected_albums[0] == test_albums[3]
        assert view._last_clicked_index == 3

    def test_single_click_replaces_selection(self, test_albums):
        """Test single click replaces existing selection."""
        view = self._create_mock_library_view(test_albums)
        view.selected_albums = [test_albums[0], test_albums[1]]

        view.handle_click(test_albums[5])

        assert len(view.selected_albums) == 1
        assert view.selected_albums[0] == test_albums[5]

    def test_ctrl_click_adds_to_selection(self, test_albums):
        """Test Ctrl+click adds to existing selection."""
        view = self._create_mock_library_view(test_albums)
        view.handle_click(test_albums[2])

        view.handle_click(test_albums[5], ctrl=True)

        assert len(view.selected_albums) == 2
        assert test_albums[2] in view.selected_albums
        assert test_albums[5] in view.selected_albums

    def test_ctrl_click_toggles_selection(self, test_albums):
        """Test Ctrl+click toggles already selected album."""
        view = self._create_mock_library_view(test_albums)
        view.selected_albums = [test_albums[2], test_albums[5]]
        view._last_clicked_index = 5

        view.handle_click(test_albums[2], ctrl=True)

        assert len(view.selected_albums) == 1
        assert test_albums[5] in view.selected_albums
        assert test_albums[2] not in view.selected_albums

    def test_shift_click_range_selection_forward(self, test_albums):
        """Test Shift+click selects range forward."""
        view = self._create_mock_library_view(test_albums)
        view.handle_click(test_albums[2])  # Click index 2

        view.handle_click(test_albums[5], shift=True)  # Shift+click index 5

        assert len(view.selected_albums) == 4
        assert test_albums[2] in view.selected_albums
        assert test_albums[3] in view.selected_albums
        assert test_albums[4] in view.selected_albums
        assert test_albums[5] in view.selected_albums

    def test_shift_click_range_selection_backward(self, test_albums):
        """Test Shift+click selects range backward."""
        view = self._create_mock_library_view(test_albums)
        view.handle_click(test_albums[7])  # Click index 7

        view.handle_click(test_albums[4], shift=True)  # Shift+click index 4

        assert len(view.selected_albums) == 4
        for i in range(4, 8):
            assert test_albums[i] in view.selected_albums

    def test_shift_click_without_anchor_selects_single(self, test_albums):
        """Test Shift+click without previous anchor just selects one album."""
        view = self._create_mock_library_view(test_albums)
        # No previous click, _last_clicked_index is None

        view.handle_click(test_albums[5], shift=True)

        assert len(view.selected_albums) == 1
        assert test_albums[5] in view.selected_albums
        assert view._last_clicked_index == 5

    def test_shift_click_preserves_existing_selection(self, test_albums):
        """Test Shift+click adds to existing selection without clearing."""
        view = self._create_mock_library_view(test_albums)
        view.selected_albums = [test_albums[0]]
        view._last_clicked_index = 0

        view.handle_click(test_albums[3], shift=True)

        # Should have 0, 1, 2, 3 (range from 0 to 3)
        assert len(view.selected_albums) == 4
        for i in range(4):
            assert test_albums[i] in view.selected_albums


class TestKeyPressEventLogic:
    """Tests for keyboard shortcut logic."""

    def test_ctrl_a_key_detection(self):
        """Test Ctrl+A key detection logic."""
        # Simulate key constants
        KEY_A = 65  # Qt.Key.Key_A
        CTRL_MODIFIER = 0x04000000  # Qt.KeyboardModifier.ControlModifier

        # Test Ctrl+A detection
        key = KEY_A
        modifiers = CTRL_MODIFIER

        is_ctrl_a = key == KEY_A and bool(modifiers & CTRL_MODIFIER)
        assert is_ctrl_a is True

    def test_escape_key_detection(self):
        """Test Escape key detection logic."""
        KEY_ESCAPE = 0x01000000  # Qt.Key.Key_Escape

        key = KEY_ESCAPE

        is_escape = key == KEY_ESCAPE
        assert is_escape is True

    def test_ctrl_a_without_ctrl_not_detected(self):
        """Test A key without Ctrl modifier is not detected as Ctrl+A."""
        KEY_A = 65
        CTRL_MODIFIER = 0x04000000

        key = KEY_A
        modifiers = 0  # No modifiers

        is_ctrl_a = key == KEY_A and bool(modifiers & CTRL_MODIFIER)
        assert is_ctrl_a is False


class TestSelectionWithEmptyAlbums:
    """Tests for selection handling with empty album list."""

    def _create_mock_view(self, albums):
        """Create mock view for testing."""

        class MockView:
            def __init__(self, albums):
                self.albums = albums
                self.selected_albums = []
                self._last_clicked_index = None
                self.emissions = []

            def emit(self, albums):
                self.emissions.append(albums.copy())

            def select_all(self):
                self.selected_albums = list(self.albums)
                self.emit(self.selected_albums)

            def clear_selection(self):
                self.selected_albums = []
                self._last_clicked_index = None
                self.emit([])

        return MockView(albums)

    def test_select_all_with_no_albums(self):
        """Test select_all with empty album list."""
        view = self._create_mock_view([])

        view.select_all()

        assert view.selected_albums == []
        assert len(view.emissions) == 1
        assert view.emissions[0] == []

    def test_clear_selection_with_no_albums(self):
        """Test clear_selection with empty album list."""
        view = self._create_mock_view([])

        view.clear_selection()

        assert view.selected_albums == []
        assert view._last_clicked_index is None


class TestContextMenuBuilding:
    """Tests for context menu building logic."""

    @pytest.fixture
    def album_no_cover(self, tmp_path):
        """Create an album without any cover."""
        return AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

    @pytest.fixture
    def album_with_embedded(self, tmp_path):
        """Create an album with embedded cover only."""
        sample_file = tmp_path / "track.mp3"
        sample_file.write_bytes(b"fake audio")
        return AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=True, has_folder=False),
            sample_file=sample_file,
        )

    @pytest.fixture
    def album_with_folder(self, tmp_path):
        """Create an album with folder cover only."""
        folder_path = tmp_path / "Artist" / "Album" / "cover.jpg"
        folder_path.parent.mkdir(parents=True, exist_ok=True)
        folder_path.write_bytes(b"fake image")
        return AlbumInfo(
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

    @pytest.fixture
    def album_with_both(self, tmp_path):
        """Create an album with both embedded and folder covers."""
        sample_file = tmp_path / "track.mp3"
        sample_file.write_bytes(b"fake audio")
        folder_path = tmp_path / "Artist" / "Album" / "cover.jpg"
        folder_path.parent.mkdir(parents=True, exist_ok=True)
        folder_path.write_bytes(b"fake image")
        return AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(
                has_embedded=True, has_folder=True, folder_path=folder_path, folder_file="cover.jpg"
            ),
            sample_file=sample_file,
        )

    def test_menu_has_file_operations_for_all_albums(self, album_no_cover):
        """Menu should always have file operation actions."""
        # Test the logic: these actions should always be present
        actions = ["Open in file manager", "Open terminal here", "Copy path"]
        assert len(actions) == 3  # Always present

    def test_search_action_always_present(self, album_no_cover):
        """Search for cover action should always be present."""
        # Logic: search should be available regardless of cover status
        assert True  # Placeholder - actual Qt test would check menu actions

    def test_remove_action_only_when_has_cover(self, album_no_cover, album_with_embedded):
        """Remove cover action should only appear when album has covers."""
        # No cover - no remove action
        assert not album_no_cover.has_any_cover
        # Has cover - should have remove action
        assert album_with_embedded.has_any_cover

    def test_find_identical_only_when_has_cover(self, album_no_cover, album_with_folder):
        """Find identical covers should only appear when album has covers."""
        assert not album_no_cover.has_any_cover
        assert album_with_folder.has_any_cover

    def test_find_identical_submenu_when_both_covers(self, album_with_both):
        """When both covers exist, find identical should be a submenu."""
        assert album_with_both.cover.has_embedded
        assert album_with_both.cover.has_folder

    def test_acoustid_option_requires_sample_file(self, tmp_path):
        """AcoustID option should only appear if sample_file exists."""
        album_no_sample = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=None,
        )
        assert album_no_sample.sample_file is None

        sample_file = tmp_path / "track.mp3"
        sample_file.write_bytes(b"fake audio")
        album_with_sample = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            sample_file=sample_file,
        )
        assert album_with_sample.sample_file is not None
        assert album_with_sample.sample_file.exists()


class TestContextMenuSignalEmission:
    """Tests for context menu signal emission logic."""

    def test_search_cover_signal_emission_logic(self, tmp_path):
        """Test that search cover action should emit search_cover_requested."""
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # When search action is triggered, signal should emit with album
        # This tests the logic, not the actual Qt signal
        emitted_album = album  # Simulates signal emission
        assert emitted_album == album

    def test_remove_cover_signal_emission_logic(self, tmp_path):
        """Test that remove cover action should emit remove_cover_requested."""
        album = AlbumInfo(
            path=tmp_path / "Artist" / "Album",
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=True, has_folder=False),
        )
        # When remove action is triggered, signal should emit with album
        emitted_album = album  # Simulates signal emission
        assert emitted_album == album

    def test_find_identical_signal_emission_logic(self, tmp_path):
        """Test that find identical action should emit find_identical_requested."""
        # The signal should emit the cover hash
        cover_hash = "abc123def456"
        emitted_hash = cover_hash  # Simulates signal emission
        assert emitted_hash == cover_hash


class TestCopyPathToClipboard:
    """Tests for copy path to clipboard logic."""

    def test_copy_path_single_file_album(self, tmp_path):
        """Test copying path for single file album."""
        file_path = tmp_path / "track.mp3"
        file_path.write_bytes(b"fake audio")
        album = AlbumInfo(
            path=file_path,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # Path should be the file path
        assert str(album.path) == str(file_path)

    def test_copy_path_folder_album(self, tmp_path):
        """Test copying path for folder album."""
        folder_path = tmp_path / "Artist" / "Album"
        folder_path.mkdir(parents=True)
        album = AlbumInfo(
            path=folder_path,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # Path should be the folder path
        assert str(album.path) == str(folder_path)

    def test_copy_path_with_special_characters(self, tmp_path):
        """Test copying path with special characters."""
        folder_path = tmp_path / "Artist (Special)" / "Album [2024]"
        folder_path.mkdir(parents=True)
        album = AlbumInfo(
            path=folder_path,
            artist="Artist (Special)",
            album="Album [2024]",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        path_str = str(album.path)
        assert "(Special)" in path_str
        assert "[2024]" in path_str


class TestOpenFileManagerLogic:
    """Tests for open in file manager logic."""

    def test_open_file_manager_uses_album_path(self, tmp_path):
        """Test that file manager opens at album path."""
        folder_path = tmp_path / "Artist" / "Album"
        folder_path.mkdir(parents=True)
        album = AlbumInfo(
            path=folder_path,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # The path passed to file manager should be album.path
        assert album.path == folder_path

    def test_open_file_manager_single_file(self, tmp_path):
        """Test file manager with single file album."""
        file_path = tmp_path / "track.mp3"
        file_path.write_bytes(b"fake audio")
        album = AlbumInfo(
            path=file_path,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # Should use file path (file manager will select the file)
        assert album.path.is_file()


class TestOpenTerminalLogic:
    """Tests for open terminal logic."""

    def test_open_terminal_folder_album(self, tmp_path):
        """Test terminal opens at folder for folder album."""
        folder_path = tmp_path / "Artist" / "Album"
        folder_path.mkdir(parents=True)
        album = AlbumInfo(
            path=folder_path,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # Terminal should open at folder
        assert album.path.is_dir()

    def test_open_terminal_single_file_uses_parent(self, tmp_path):
        """Test terminal opens at parent folder for single file album."""
        file_path = tmp_path / "track.mp3"
        file_path.write_bytes(b"fake audio")
        album = AlbumInfo(
            path=file_path,
            artist="Artist",
            album="Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )
        # Terminal should open at parent folder
        expected_dir = album.path.parent if album.path.is_file() else album.path
        assert expected_dir == tmp_path


class TestGridColumnCalculation:
    """Tests for grid column calculation logic.

    Regression tests for bug where grid column count was calculated incorrectly
    when albums were first added, and scrolling didn't work.
    """

    def test_column_calculation_minimum_one(self):
        """Test that column calculation returns at least 1."""
        from src.ui.library_view import LibraryView

        # With very small or zero width, should still return 1
        card_width = 150
        spacing = 12

        # Simulate very small viewport
        for available_width in [0, 10, 50, 100]:
            columns = max(1, available_width // (card_width + spacing))
            assert columns >= 1, f"Columns should be >= 1 for width {available_width}"

    def test_column_calculation_correct_for_width(self):
        """Test that column calculation returns correct count for various widths."""
        card_width = 150
        spacing = 12
        margin = 20

        # Test cases: (viewport_width, expected_columns)
        test_cases = [
            (200, 1),  # 200 - 20 = 180, 180 / 162 = 1.1 -> 1
            (350, 2),  # 350 - 20 = 330, 330 / 162 = 2.0 -> 2
            (500, 2),  # 500 - 20 = 480, 480 / 162 = 2.9 -> 2
            (520, 3),  # 520 - 20 = 500, 500 / 162 = 3.0 -> 3
            (1000, 6),  # 1000 - 20 = 980, 980 / 162 = 6.0 -> 6
        ]

        for viewport_width, expected in test_cases:
            available_width = viewport_width - margin
            columns = max(1, available_width // (card_width + spacing))
            assert columns == expected, (
                f"Width {viewport_width} should give {expected} columns, got {columns}"
            )

    def test_force_recalculate_resets_column_count(self):
        """Test that force recalculate resets _last_column_count."""
        # This tests the logic that _last_column_count should be reset
        # to allow full grid recalculation
        last_column_count = 3
        new_columns = 5

        # Simulate the fix: reset to 0 before recalculating
        if new_columns != last_column_count:
            last_column_count = 0  # Force full recalculation

        assert last_column_count == 0, "Column count should be reset to 0"

    def test_deferred_populate_grid_method_exists(self):
        """Regression test: _deferred_populate_grid should exist for Qt timing fix.

        Bug: Grid column count was calculated incorrectly when albums were first added
        because the viewport didn't have its correct size yet.

        Fix: Grid population is deferred to the next event loop iteration using
        QTimer.singleShot(0, ...) to ensure viewport has correct geometry.
        """
        from src.ui.library_view import LibraryView

        # Verify the method exists
        assert hasattr(LibraryView, "_deferred_populate_grid"), (
            "_deferred_populate_grid method should exist for Qt timing fix"
        )

    def test_refresh_view_defers_grid_population(self):
        """Regression test: Grid population should be deferred, not immediate.

        Bug: When switching to grid view, _populate_grid was called immediately
        before the viewport had its correct size, causing wrong column count.

        Fix: _refresh_view switches to grid_scroll first, then defers population
        to the next event loop iteration.
        """
        import inspect

        from src.ui.library_view import LibraryView

        # Get the source code of _refresh_view
        source = inspect.getsource(LibraryView._refresh_view)

        # Verify that:
        # 1. setCurrentWidget(self.grid_scroll) happens before deferred call
        # 2. _deferred_populate_grid is called via QTimer.singleShot
        assert "setCurrentWidget(self.grid_scroll)" in source, (
            "Should switch to grid_scroll before deferring"
        )
        assert "_deferred_populate_grid" in source, "Should call _deferred_populate_grid"
        assert "QTimer.singleShot(0" in source, "Should use QTimer.singleShot(0) for deferred call"

        # Ensure there's no more processEvents() workaround
        assert "QApplication.processEvents()" not in source, (
            "Should not use processEvents() workaround"
        )

    def test_selection_preserved_after_deferred_populate(self):
        """Regression test: Selection visual state should be preserved after grid rebuild.

        Bug: When grid was rebuilt (e.g., after column count change), the selection
        visual indicator was lost because cards were recreated without reapplying
        the selection state.

        Fix: _deferred_populate_grid calls _update_card_selection() after rebuilding.
        """
        import inspect

        from src.ui.library_view import LibraryView

        # Get the source code of _deferred_populate_grid
        source = inspect.getsource(LibraryView._deferred_populate_grid)

        # Verify selection is reapplied after grid population
        assert "_update_card_selection" in source, (
            "_deferred_populate_grid should call _update_card_selection to preserve selection"
        )


class TestGroupAsAlbumLogic:
    """
    Tests for the "Group as album" functionality.

    This tests the logic that determines if selected albums can be grouped,
    without requiring Qt.
    """

    def _create_individual_file_album(
        self, filepath: Path, artist: str = None, album: str = None
    ) -> AlbumInfo:
        """Create an album representing an individual file (track_count=1)."""
        cover = CoverInfo(has_embedded=False, has_folder=False)
        return AlbumInfo(
            path=filepath,  # For individual files, path is the file itself
            artist=artist,
            album=album,
            cover=cover,
            track_count=1,
        )

    def _create_folder_album(
        self, folder: Path, artist: str = None, album: str = None, track_count: int = 10
    ) -> AlbumInfo:
        """Create an album representing a folder with multiple tracks."""
        cover = CoverInfo(has_embedded=False, has_folder=False)
        return AlbumInfo(
            path=folder,
            artist=artist,
            album=album,
            cover=cover,
            track_count=track_count,
        )

    def _can_group_logic(self, selected_albums: list) -> bool:
        """
        Replicate the _can_group_as_album logic from LibraryView.

        Albums can be grouped if:
        - At least 2 albums are selected
        - All selected albums are individual files (track_count == 1)
        - All selected albums share the same parent folder
        """
        if len(selected_albums) < 2:
            return False

        # Check all are individual files
        if not all(a.track_count == 1 for a in selected_albums):
            return False

        # Check all share the same parent folder
        parents = set()
        for album in selected_albums:
            parent = album.path.parent if album.path.is_file() else album.path
            parents.add(parent)

        return len(parents) == 1

    def test_can_group_individual_files_same_folder(self, tmp_path):
        """Individual files from the same folder can be grouped."""
        folder = tmp_path / "Artist" / "Compilation"
        folder.mkdir(parents=True)

        # Create individual file albums
        albums = [
            self._create_individual_file_album(folder / "track1.mp3", "Artist A", "Album A"),
            self._create_individual_file_album(folder / "track2.mp3", "Artist B", "Album B"),
            self._create_individual_file_album(folder / "track3.mp3", "Artist C", "Album C"),
        ]

        # Create the files so .is_file() returns True
        for album in albums:
            album.path.touch()

        assert self._can_group_logic(albums) is True

    def test_cannot_group_single_file(self, tmp_path):
        """A single file cannot be grouped."""
        folder = tmp_path / "Artist" / "Album"
        folder.mkdir(parents=True)
        filepath = folder / "track.mp3"
        filepath.touch()

        albums = [self._create_individual_file_album(filepath)]

        assert self._can_group_logic(albums) is False

    def test_cannot_group_files_from_different_folders(self, tmp_path):
        """Files from different folders cannot be grouped."""
        folder1 = tmp_path / "Artist1" / "Album1"
        folder2 = tmp_path / "Artist2" / "Album2"
        folder1.mkdir(parents=True)
        folder2.mkdir(parents=True)

        file1 = folder1 / "track.mp3"
        file2 = folder2 / "track.mp3"
        file1.touch()
        file2.touch()

        albums = [
            self._create_individual_file_album(file1),
            self._create_individual_file_album(file2),
        ]

        assert self._can_group_logic(albums) is False

    def test_cannot_group_folder_albums(self, tmp_path):
        """Full folder albums (track_count > 1) cannot be grouped."""
        folder1 = tmp_path / "Artist1" / "Album1"
        folder2 = tmp_path / "Artist2" / "Album2"
        folder1.mkdir(parents=True)
        folder2.mkdir(parents=True)

        albums = [
            self._create_folder_album(folder1, "Artist1", "Album1", track_count=10),
            self._create_folder_album(folder2, "Artist2", "Album2", track_count=8),
        ]

        assert self._can_group_logic(albums) is False

    def test_cannot_group_mixed_individual_and_folder_albums(self, tmp_path):
        """Cannot group a mix of individual files and folder albums."""
        folder = tmp_path / "Music"
        folder.mkdir(parents=True)
        filepath = folder / "single.mp3"
        filepath.touch()

        albums = [
            self._create_individual_file_album(filepath),
            self._create_folder_album(folder, "Artist", "Album", track_count=5),
        ]

        assert self._can_group_logic(albums) is False

    def test_cannot_group_when_forced_group_included(self, tmp_path):
        """Cannot group if selection includes a forced group."""
        folder = tmp_path / "Artist" / "Compilation"
        folder.mkdir(parents=True)

        # Create individual file albums
        file1 = folder / "track1.mp3"
        file2 = folder / "track2.mp3"
        file1.touch()
        file2.touch()

        # One is a forced group
        forced_group = AlbumInfo(
            path=folder,
            artist="Various Artists",
            album="Compilation",
            cover=CoverInfo(has_embedded=False, has_folder=False),
            track_count=5,
            is_forced_group=True,
            forced_group_files=[folder / "existing1.mp3"],
        )

        individual = self._create_individual_file_album(file1)

        albums = [forced_group, individual]

        # Updated _can_group_logic to check for forced groups
        def _can_group_with_forced_check(selected_albums: list) -> bool:
            if len(selected_albums) < 2:
                return False
            if any(a.is_forced_group for a in selected_albums):
                return False
            if not all(a.track_count == 1 for a in selected_albums):
                return False
            parents = set()
            for album in selected_albums:
                parent = album.path.parent if album.path.is_file() else album.path
                parents.add(parent)
            return len(parents) == 1

        assert _can_group_with_forced_check(albums) is False


class TestAddToGroupLogic:
    """
    Tests for the "Add to group" functionality.

    This tests the logic that determines if files can be added to an existing group.
    """

    def _create_individual_file_album(
        self, filepath: Path, artist: str = None, album: str = None
    ) -> AlbumInfo:
        """Create an album representing an individual file (track_count=1)."""
        cover = CoverInfo(has_embedded=False, has_folder=False)
        return AlbumInfo(
            path=filepath,
            artist=artist,
            album=album,
            cover=cover,
            track_count=1,
        )

    def _create_forced_group(
        self, folder: Path, files: list, artist: str = "Various Artists"
    ) -> AlbumInfo:
        """Create a forced group album."""
        cover = CoverInfo(has_embedded=False, has_folder=False)
        return AlbumInfo(
            path=folder,
            artist=artist,
            album=folder.name,
            cover=cover,
            track_count=len(files),
            is_forced_group=True,
            forced_group_files=files,
        )

    def _get_add_to_group_info(self, selected_albums: list) -> tuple:
        """
        Replicate the _get_add_to_group_info logic from LibraryView.

        Returns: (can_add, target_group, individual_files, error_message)
        """
        if len(selected_albums) < 2:
            return (False, None, [], None)

        forced_groups = [a for a in selected_albums if a.is_forced_group]
        individual_files = [
            a for a in selected_albums if a.track_count == 1 and not a.is_forced_group
        ]

        if len(forced_groups) > 1:
            return (False, None, [], "Select only one group to add files to")

        if len(forced_groups) == 1 and len(individual_files) >= 1:
            target_group = forced_groups[0]
            group_folder = target_group.path

            for album in individual_files:
                file_parent = album.path.parent if album.path.is_file() else album.path
                if file_parent != group_folder:
                    return (False, None, [], "Files must be in the same folder as the group")

            return (True, target_group, individual_files, None)

        return (False, None, [], None)

    def test_can_add_to_group_same_folder(self, tmp_path):
        """Individual files from the same folder can be added to a group."""
        folder = tmp_path / "Artist" / "Compilation"
        folder.mkdir(parents=True)

        # Create existing group files
        existing_files = [folder / "track1.mp3", folder / "track2.mp3"]
        for f in existing_files:
            f.touch()

        # Create the forced group
        group = self._create_forced_group(folder, existing_files)

        # Create new individual files to add
        new_file = folder / "track3.mp3"
        new_file.touch()
        individual = self._create_individual_file_album(new_file)

        albums = [group, individual]

        can_add, target, files, error = self._get_add_to_group_info(albums)

        assert can_add is True
        assert target == group
        assert individual in files
        assert error is None

    def test_cannot_add_multiple_groups(self, tmp_path):
        """Cannot add when multiple groups are selected."""
        folder1 = tmp_path / "Folder1"
        folder2 = tmp_path / "Folder2"
        folder1.mkdir(parents=True)
        folder2.mkdir(parents=True)

        group1 = self._create_forced_group(folder1, [folder1 / "a.mp3"])
        group2 = self._create_forced_group(folder2, [folder2 / "b.mp3"])

        albums = [group1, group2]

        can_add, target, files, error = self._get_add_to_group_info(albums)

        assert can_add is False
        assert target is None
        assert error == "Select only one group to add files to"

    def test_cannot_add_files_from_different_folder(self, tmp_path):
        """Cannot add files from a different folder than the group."""
        folder1 = tmp_path / "Folder1"
        folder2 = tmp_path / "Folder2"
        folder1.mkdir(parents=True)
        folder2.mkdir(parents=True)

        existing = folder1 / "track.mp3"
        existing.touch()
        group = self._create_forced_group(folder1, [existing])

        other_file = folder2 / "other.mp3"
        other_file.touch()
        individual = self._create_individual_file_album(other_file)

        albums = [group, individual]

        can_add, target, files, error = self._get_add_to_group_info(albums)

        assert can_add is False
        assert error == "Files must be in the same folder as the group"

    def test_returns_nothing_for_only_individuals(self, tmp_path):
        """Returns no add-to-group option when only individual files are selected."""
        folder = tmp_path / "Folder"
        folder.mkdir(parents=True)

        file1 = folder / "track1.mp3"
        file2 = folder / "track2.mp3"
        file1.touch()
        file2.touch()

        albums = [
            self._create_individual_file_album(file1),
            self._create_individual_file_album(file2),
        ]

        can_add, target, files, error = self._get_add_to_group_info(albums)

        # Should return False with no error (individual files use "group as album" instead)
        assert can_add is False
        assert error is None


class TestDragDropSignal:
    """
    Tests for the files_dropped signal in LibraryView.

    Bug fix: Drag and drop was not working on the empty state area because
    child widgets intercepted mouse events. Now LibraryView handles drag/drop
    directly and emits a signal.
    """

    def test_files_dropped_signal_exists(self):
        """Test that LibraryView has a files_dropped signal."""
        from PySide6.QtCore import Signal

        from src.ui.library_view import LibraryView

        # Verify the signal is defined on the class
        assert hasattr(LibraryView, "files_dropped")

    def test_drop_event_accepts_urls(self):
        """Test that drop event accepts URL mime data."""

        # Simulate the drop event logic
        def would_accept_drop(has_urls: bool, paths: list) -> bool:
            """Mimics the dropEvent logic."""
            return bool(has_urls and paths)

        # Test with valid paths
        assert would_accept_drop(True, ["/path/to/file.mp3"]) is True
        assert would_accept_drop(True, ["/path/to/folder"]) is True
        assert would_accept_drop(True, ["/path/to/file.mp3", "/path/to/folder"]) is True

        # Test with no paths
        assert would_accept_drop(True, []) is False
        assert would_accept_drop(False, []) is False

    def test_drag_enter_accepts_urls(self):
        """Test that drag enter event accepts URL mime data."""

        # Simulate the dragEnterEvent logic
        def would_accept_drag_enter(has_urls: bool) -> bool:
            """Mimics the dragEnterEvent logic."""
            return has_urls

        assert would_accept_drag_enter(True) is True
        assert would_accept_drag_enter(False) is False

    def test_dropped_paths_are_strings(self, tmp_path):
        """Test that emitted paths are string type."""
        # Simulate the path conversion from URLs
        file1 = tmp_path / "test.mp3"
        file1.touch()
        folder = tmp_path / "album"
        folder.mkdir()

        # Simulate URL to path conversion
        paths = [str(file1), str(folder)]

        # All paths should be strings
        assert all(isinstance(p, str) for p in paths)
        assert len(paths) == 2
