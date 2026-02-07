"""
pytest-qt integration tests for LibraryView drag and drop functionality.

These tests verify the drag and drop handling in LibraryView including:
- Accepting valid file URLs
- Visual feedback on drag enter/leave
- Signal emission on drop
- Rejection of invalid mime data
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from src.ui.library_view import LibraryView


def normalize_path(path_str: str) -> str:
    """Normalize a path string for cross-platform comparison.

    QUrl.toLocalFile() returns forward slashes on all platforms,
    while str(Path) returns OS-native separators. This function
    normalizes to forward slashes for consistent comparison.
    """
    return str(Path(path_str).as_posix())


@pytest.fixture
def library_view(qtbot):
    """Create a LibraryView widget for testing."""
    view = LibraryView()
    qtbot.addWidget(view)
    view.show()
    return view


@pytest.fixture
def mime_data_with_urls(tmp_path):
    """Create QMimeData with file URLs."""
    # Create test files/folders
    test_file = tmp_path / "test_album" / "track.mp3"
    test_file.parent.mkdir(parents=True)
    test_file.write_bytes(b"fake mp3 data")

    test_folder = tmp_path / "another_album"
    test_folder.mkdir()
    (test_folder / "song.flac").write_bytes(b"fake flac data")

    # Create mime data with URLs
    mime_data = QMimeData()
    urls = [
        QUrl.fromLocalFile(str(test_file.parent)),
        QUrl.fromLocalFile(str(test_folder)),
    ]
    mime_data.setUrls(urls)

    return mime_data, [str(test_file.parent), str(test_folder)]


@pytest.fixture
def mime_data_with_single_file(tmp_path):
    """Create QMimeData with a single file URL."""
    test_file = tmp_path / "single_track.mp3"
    test_file.write_bytes(b"fake mp3 data")

    mime_data = QMimeData()
    urls = [QUrl.fromLocalFile(str(test_file))]
    mime_data.setUrls(urls)

    return mime_data, [str(test_file)]


@pytest.fixture
def mime_data_without_urls():
    """Create QMimeData without URLs (text only)."""
    mime_data = QMimeData()
    mime_data.setText("This is plain text, not a file URL")
    return mime_data


@pytest.fixture
def mime_data_empty():
    """Create empty QMimeData."""
    return QMimeData()


class TestDragEnterEvent:
    """Tests for dragEnterEvent handling."""

    def test_accepts_drag_with_valid_urls(self, library_view, qtbot, mime_data_with_urls):
        """Test that LibraryView accepts drag enter with valid file URLs."""
        mime_data, _ = mime_data_with_urls

        # Verify widget accepts drops
        assert library_view.acceptDrops() is True

        # Create and execute drag enter event
        event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dragEnterEvent(event)

        # Event should be accepted for valid URLs
        assert event.isAccepted() is True

    def test_visual_feedback_applied_on_drag_enter(self, library_view, qtbot, mime_data_with_urls):
        """Test that visual feedback (blue overlay with border) is applied on drag enter.

        Bug fix: Drag and drop was not providing visual feedback when files
        were dragged over the LibraryView. Now a blue overlay with dashed border is shown.
        """
        mime_data, _ = mime_data_with_urls

        # Initial state: no special style on stack widget
        assert library_view.stack.styleSheet() == ""

        # Create drag enter event with the mime data
        event = QDragEnterEvent(
            QPoint(50, 50),  # Position
            Qt.DropAction.CopyAction,  # Drop action
            mime_data,  # Mime data
            Qt.MouseButton.LeftButton,  # Mouse button
            Qt.KeyboardModifier.NoModifier,  # Keyboard modifiers
        )

        library_view.dragEnterEvent(event)

        # Event should be accepted
        assert event.isAccepted() is True

        # After drag enter with URLs, stack should have visual feedback style
        style = library_view.stack.styleSheet()
        assert "dashed" in style
        assert "#5dade2" in style

    def test_rejects_drag_without_urls(self, library_view, qtbot, mime_data_without_urls):
        """Test that LibraryView rejects drag enter without URLs."""
        event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data_without_urls,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dragEnterEvent(event)

        # Event should be rejected
        assert event.isAccepted() is False

        # Should NOT have visual feedback (drag was rejected)
        assert library_view.stack.styleSheet() == ""

    def test_rejects_drag_with_empty_mime_data(self, library_view, qtbot, mime_data_empty):
        """Test that LibraryView rejects drag enter with empty mime data."""
        event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data_empty,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dragEnterEvent(event)

        # Event should be rejected
        assert event.isAccepted() is False

        # Should NOT have visual feedback
        assert library_view.stack.styleSheet() == ""


class TestDragLeaveEvent:
    """Tests for dragLeaveEvent handling."""

    def test_visual_feedback_removed_on_drag_leave(self, library_view, qtbot, mime_data_with_urls):
        """Test that visual feedback is removed when drag leaves the widget."""
        mime_data, _ = mime_data_with_urls

        # First, simulate drag enter to apply visual feedback
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        # Verify feedback was applied
        assert "dashed" in library_view.stack.styleSheet()

        # Now simulate drag leave
        leave_event = QDragLeaveEvent()
        library_view.dragLeaveEvent(leave_event)

        # Visual feedback should be removed
        assert library_view.stack.styleSheet() == ""

    def test_multiple_drag_enter_leave_cycles(self, library_view, qtbot, mime_data_with_urls):
        """Test that visual feedback works correctly across multiple drag cycles."""
        mime_data, _ = mime_data_with_urls

        for _ in range(3):
            # Drag enter
            enter_event = QDragEnterEvent(
                QPoint(50, 50),
                Qt.DropAction.CopyAction,
                mime_data,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            library_view.dragEnterEvent(enter_event)
            assert "dashed" in library_view.stack.styleSheet()

            # Drag leave
            leave_event = QDragLeaveEvent()
            library_view.dragLeaveEvent(leave_event)
            assert library_view.stack.styleSheet() == ""


class TestDropEvent:
    """Tests for dropEvent handling and signal emission."""

    def test_files_dropped_signal_emitted_on_valid_drop(
        self, library_view, qtbot, mime_data_with_urls
    ):
        """Test that files_dropped signal is emitted with correct paths on drop."""
        mime_data, expected_paths = mime_data_with_urls

        # Track emitted signal
        received_paths = []

        def on_files_dropped(paths):
            received_paths.extend(paths)

        library_view.files_dropped.connect(on_files_dropped)

        # First do drag enter (required for proper state)
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        # Create and execute drop event
        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        # Verify signal was emitted with correct paths
        # Normalize paths for cross-platform comparison (Windows vs Unix separators)
        assert len(received_paths) == len(expected_paths)
        received_normalized = [normalize_path(p) for p in received_paths]
        for path in expected_paths:
            assert normalize_path(path) in received_normalized

    def test_files_dropped_signal_with_single_file(
        self, library_view, qtbot, mime_data_with_single_file
    ):
        """Test files_dropped signal with a single file."""
        mime_data, expected_paths = mime_data_with_single_file

        received_paths = []
        library_view.files_dropped.connect(lambda paths: received_paths.extend(paths))

        # First do drag enter (required for proper state, matches real user interaction)
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        # Then drop
        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        assert len(received_paths) == 1
        # Normalize paths for cross-platform comparison
        assert normalize_path(received_paths[0]) == normalize_path(expected_paths[0])

    def test_visual_feedback_removed_on_drop(self, library_view, qtbot, mime_data_with_urls):
        """Test that visual feedback is removed after drop event."""
        mime_data, _ = mime_data_with_urls

        # Apply visual feedback via drag enter
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)
        assert "dashed" in library_view.stack.styleSheet()

        # Drop event
        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        # Visual feedback should be removed
        assert library_view.stack.styleSheet() == ""

    def test_drop_without_urls_does_not_emit_signal(
        self, library_view, qtbot, mime_data_without_urls
    ):
        """Test that drop without URLs does not emit files_dropped signal."""

        signal_received = False

        def on_signal(_):
            nonlocal signal_received
            signal_received = True

        library_view.files_dropped.connect(on_signal)

        # Simulate drag enter first (matches real user interaction)
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data_without_urls,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data_without_urls,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        # Signal should not have been emitted
        assert signal_received is False

    def test_drop_with_empty_mime_data_does_not_emit_signal(
        self, library_view, qtbot, mime_data_empty
    ):
        """Test that drop with empty mime data does not emit files_dropped signal."""

        signal_received = False

        def on_signal(_):
            nonlocal signal_received
            signal_received = True

        library_view.files_dropped.connect(on_signal)

        # Simulate drag enter first (matches real user interaction)
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data_empty,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data_empty,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        assert signal_received is False

    def test_files_dropped_signal_with_qtbot_wait_signal(
        self, library_view, qtbot, mime_data_with_urls
    ):
        """Test files_dropped signal emission using qtbot.waitSignal."""
        mime_data, expected_paths = mime_data_with_urls

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        with qtbot.waitSignal(library_view.files_dropped, timeout=1000) as blocker:
            library_view.dropEvent(drop_event)

        # Verify the signal args contain the expected paths
        assert blocker.args is not None
        received_paths = blocker.args[0]
        assert len(received_paths) == len(expected_paths)


class TestDropEventWithNonLocalUrls:
    """Tests for handling non-local URLs in drop events."""

    def test_drop_ignores_non_local_urls(self, library_view, qtbot):
        """Test that non-local URLs (http://, etc.) are filtered out."""

        mime_data = QMimeData()
        # Mix of local and non-local URLs
        urls = [
            QUrl("http://example.com/music.mp3"),
            QUrl("https://example.com/album.zip"),
            QUrl("ftp://server.com/file.flac"),
        ]
        mime_data.setUrls(urls)

        signal_received = False

        def on_signal(paths):
            nonlocal signal_received
            signal_received = True

        library_view.files_dropped.connect(on_signal)

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        # Signal should not be emitted (no local files in the URLs)
        assert signal_received is False

    def test_drop_filters_non_local_from_mixed_urls(self, library_view, qtbot, tmp_path):
        """Test that only local URLs are included when mixed with non-local."""

        # Create a real local file
        local_file = tmp_path / "local_track.mp3"
        local_file.write_bytes(b"fake data")

        mime_data = QMimeData()
        urls = [
            QUrl("http://example.com/remote.mp3"),  # Non-local
            QUrl.fromLocalFile(str(local_file)),  # Local
            QUrl("https://example.com/another.mp3"),  # Non-local
        ]
        mime_data.setUrls(urls)

        received_paths = []
        library_view.files_dropped.connect(lambda paths: received_paths.extend(paths))

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        # Only the local file should be in the received paths
        assert len(received_paths) == 1
        # Normalize paths for cross-platform comparison
        assert normalize_path(received_paths[0]) == normalize_path(str(local_file))


class TestAcceptDrops:
    """Tests for acceptDrops configuration."""

    def test_library_view_accepts_drops_by_default(self, library_view, qtbot):
        """Test that LibraryView is configured to accept drops."""
        assert library_view.acceptDrops() is True

    def test_accept_drops_can_be_toggled(self, library_view, qtbot):
        """Test that acceptDrops can be toggled."""
        library_view.setAcceptDrops(False)
        assert library_view.acceptDrops() is False

        library_view.setAcceptDrops(True)
        assert library_view.acceptDrops() is True


class TestDragDropWithSpecialPaths:
    """Tests for drag and drop with special path characters."""

    def test_drop_paths_with_spaces(self, library_view, qtbot, tmp_path):
        """Test dropping files with spaces in the path."""

        # Create file with spaces in path
        folder_with_spaces = tmp_path / "My Music Library" / "Best Album Ever"
        folder_with_spaces.mkdir(parents=True)
        (folder_with_spaces / "track 01.mp3").write_bytes(b"fake data")

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(folder_with_spaces))])

        received_paths = []
        library_view.files_dropped.connect(lambda paths: received_paths.extend(paths))

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        assert len(received_paths) == 1
        assert "My Music Library" in received_paths[0]
        assert "Best Album Ever" in received_paths[0]

    def test_drop_paths_with_special_characters(self, library_view, qtbot, tmp_path):
        """Test dropping files with special characters in the path."""

        # Create file with special characters
        folder = tmp_path / "Artist (Special)" / "Album [2024]"
        folder.mkdir(parents=True)
        (folder / "track.mp3").write_bytes(b"fake data")

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(folder))])

        received_paths = []
        library_view.files_dropped.connect(lambda paths: received_paths.extend(paths))

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        assert len(received_paths) == 1
        assert "(Special)" in received_paths[0]
        assert "[2024]" in received_paths[0]

    def test_drop_paths_with_unicode_characters(self, library_view, qtbot, tmp_path):
        """Test dropping files with unicode characters in the path."""

        # Create file with unicode characters
        folder = tmp_path / "アーティスト" / "アルバム 音楽"
        folder.mkdir(parents=True)
        (folder / "曲.mp3").write_bytes(b"fake data")

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(folder))])

        received_paths = []
        library_view.files_dropped.connect(lambda paths: received_paths.extend(paths))

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        assert len(received_paths) == 1
        assert "アーティスト" in received_paths[0]


class TestDragDropMultipleFiles:
    """Tests for dropping multiple files at once."""

    def test_drop_multiple_folders(self, library_view, qtbot, tmp_path):
        """Test dropping multiple folders at once."""

        # Create multiple folders
        folders = []
        for i in range(5):
            folder = tmp_path / f"Album_{i}"
            folder.mkdir()
            (folder / "track.mp3").write_bytes(b"fake data")
            folders.append(folder)

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(f)) for f in folders])

        received_paths = []
        library_view.files_dropped.connect(lambda paths: received_paths.extend(paths))

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        assert len(received_paths) == 5
        for i in range(5):
            assert any(f"Album_{i}" in path for path in received_paths)

    def test_drop_mixed_files_and_folders(self, library_view, qtbot, tmp_path):
        """Test dropping a mix of files and folders."""

        # Create folder
        folder = tmp_path / "Album"
        folder.mkdir()
        (folder / "track.mp3").write_bytes(b"fake data")

        # Create single file
        single_file = tmp_path / "single.mp3"
        single_file.write_bytes(b"fake data")

        mime_data = QMimeData()
        mime_data.setUrls(
            [
                QUrl.fromLocalFile(str(folder)),
                QUrl.fromLocalFile(str(single_file)),
            ]
        )

        received_paths = []
        library_view.files_dropped.connect(lambda paths: received_paths.extend(paths))

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        assert len(received_paths) == 2
        # Normalize paths for cross-platform comparison
        received_normalized = [normalize_path(p) for p in received_paths]
        assert normalize_path(str(folder)) in received_normalized
        assert normalize_path(str(single_file)) in received_normalized


class TestFilesDroppedSignal:
    """Tests for the files_dropped signal definition and behavior."""

    def test_files_dropped_signal_exists(self):
        """Test that LibraryView has a files_dropped signal.

        Bug fix: Drag and drop was not working on the empty state area because
        child widgets intercepted mouse events. Now LibraryView handles drag/drop
        directly and emits a files_dropped signal.
        """
        assert hasattr(LibraryView, "files_dropped")

    def test_files_dropped_signal_is_list_type(self, library_view, qtbot):
        """Test that files_dropped signal emits a list."""

        received_args = []

        def on_signal(paths):
            received_args.append(type(paths))
            received_args.append(paths)

        library_view.files_dropped.connect(on_signal)

        # Create minimal valid drop
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/tmp/test")])

        # Simulate drag enter first
        enter_event = QDragEnterEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        library_view.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPoint(50, 50),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        library_view.dropEvent(drop_event)

        # Verify the type of the emitted argument
        assert len(received_args) >= 2
        assert received_args[0] is list
