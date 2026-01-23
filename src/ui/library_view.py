"""
Library view widget for displaying albums in grid or list format.
"""

import logging

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QIcon,
    QKeyEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.models import AlbumInfo, CoverStatus
from ..i18n import tr
from ..utils.config import Config
from .theme import Styles
from .widgets.album_card import AlbumCard
from .widgets.thumbnail_loader import ThumbnailLoader

logger = logging.getLogger(__name__)

# Debounce delay for resize events (milliseconds)
RESIZE_DEBOUNCE_MS = 150

# Debounce delay for scroll events (milliseconds)
SCROLL_DEBOUNCE_MS = 50

# Extra margin (in pixels) around viewport for preloading
PRELOAD_MARGIN = 100

# Priority boost for visible items
VISIBLE_PRIORITY = 10


class LibraryView(QWidget):
    """
    Widget for displaying the album library in grid or list view.

    Implements lazy loading of album covers for improved performance
    with large libraries.
    """

    album_selected = Signal(AlbumInfo)
    albums_selected = Signal(list)
    find_identical_requested = Signal(str)  # hash to search for
    acoustid_identify_requested = Signal(AlbumInfo)  # album to identify via AcoustID
    search_cover_requested = Signal(AlbumInfo)  # request cover search for album
    remove_cover_requested = Signal(AlbumInfo)  # request cover removal for album
    files_dropped = Signal(list)  # list of dropped file/folder paths
    group_as_album_requested = Signal(list)  # list of albums to group together
    ungroup_album_requested = Signal(AlbumInfo)  # album to ungroup back to individual files
    add_to_group_requested = Signal(AlbumInfo, list)  # (target_group, albums_to_add)

    def __init__(self, config: Config | None = None, parent=None):
        super().__init__(parent)
        self.config = config
        self.albums: list[AlbumInfo] = []
        self.selected_albums: list[AlbumInfo] = []
        self.album_cards: dict = {}  # path -> AlbumCard
        self.view_mode = "grid"
        self._last_column_count = 0  # Track column count to avoid unnecessary refreshes
        self._last_clicked_index: int | None = None  # Track last clicked for range selection

        # Debounce timer for resize events
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._on_resize_debounced)

        # Debounce timer for scroll events
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._on_scroll_debounced)

        # Thumbnail loader for lazy loading
        cache_size = self.config.thumbnail_cache_count if self.config else 1500
        self._thumbnail_loader = ThumbnailLoader(max_workers=2, cache_size=cache_size, parent=self)
        self._thumbnail_loader.thumbnail_ready.connect(self._on_thumbnail_ready)

        # Track cards currently being loaded
        self._loading_cards: set[str] = set()

        self._setup_ui()

        # Enable keyboard focus for shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Enable drag and drop
        self.setAcceptDrops(True)

        # Set object name for targeted CSS styling
        self.setObjectName("libraryView")

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Stacked widget for grid/list views
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Grid view
        self.grid_widget = QWidget()
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setWidget(self.grid_widget)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.stack.addWidget(self.grid_scroll)

        # Install event filter on viewport to detect resize
        self.grid_scroll.viewport().installEventFilter(self)

        # Connect scroll event
        self.grid_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # List view
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._on_list_selection_changed)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_list_context_menu)
        self.stack.addWidget(self.list_widget)

        # Empty state
        self._default_empty_message = tr("Open a folder to scan your music library")
        self._filter_empty_message = tr("No album matches the current filter")
        self.empty_label = QLabel(self._default_empty_message)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; font-size: 14px;")
        self.stack.addWidget(self.empty_label)

        # Start with empty state
        self.stack.setCurrentWidget(self.empty_label)

    def set_albums(self, albums: list[AlbumInfo], is_filtered_empty: bool = False) -> None:
        """Set the albums to display.

        Args:
            albums: List of albums to display
            is_filtered_empty: If True and albums is empty, show "no filter results"
                              message instead of "open folder" message
        """
        self.albums = albums
        self.selected_albums = []
        self._last_column_count = 0  # Force refresh when albums change
        self._last_clicked_index = None  # Reset range selection anchor
        self._loading_cards.clear()

        # Update empty message based on context
        if not albums:
            if is_filtered_empty:
                self.empty_label.setText(self._filter_empty_message)
            else:
                self.empty_label.setText(self._default_empty_message)

        self._refresh_view()

    def set_view_mode(self, mode: str) -> None:
        """Set the view mode ('grid' or 'list')."""
        if mode in ("grid", "list"):
            self.view_mode = mode
            self._refresh_view()

    def _refresh_view(self) -> None:
        """Refresh the current view."""
        if not self.albums:
            self.stack.setCurrentWidget(self.empty_label)
            return

        if self.view_mode == "grid":
            # Switch to grid view first so viewport gets its correct size
            self.stack.setCurrentWidget(self.grid_scroll)
            # Defer grid population to next event loop iteration
            # Qt guarantees the viewport has correct size after show/resize events
            QTimer.singleShot(0, self._deferred_populate_grid)
        else:
            self._populate_list()
            self.stack.setCurrentWidget(self.list_widget)

    def _deferred_populate_grid(self) -> None:
        """Populate grid after viewport has correct size (called via QTimer.singleShot(0))."""
        if self.view_mode != "grid" or not self.albums:
            return
        self._populate_grid()
        self.grid_widget.updateGeometry()
        self._update_card_selection()
        QTimer.singleShot(0, self._check_visible_cards)

    def _force_grid_recalculate(self) -> None:
        """Force grid recalculation - use for explicit recalculation requests."""
        if self.view_mode == "grid" and self.albums:
            new_columns = self._calculate_columns()
            if new_columns != self._last_column_count:
                logger.debug(
                    f"Force recalculating grid: {self._last_column_count} -> {new_columns} columns"
                )
                self._last_column_count = 0  # Force full recalculation
                self._populate_grid()
                self.grid_widget.updateGeometry()
                # Reapply selection state to new cards
                self._update_card_selection()
                QTimer.singleShot(0, self._check_visible_cards)

    def _calculate_columns(self) -> int:
        """Calculate number of columns based on current width."""
        card_width = 150
        spacing = 12
        available_width = self.grid_scroll.viewport().width() - 20
        return max(1, available_width // (card_width + spacing))

    def recalculate_grid(self) -> None:
        """Public method to trigger grid recalculation (e.g., after splitter move)."""
        if self.view_mode == "grid" and self.albums:
            self._resize_timer.start(RESIZE_DEBOUNCE_MS)

    def _populate_grid(self, force_refresh: bool = False) -> None:
        """Populate the grid view with lazy-loaded album cards."""
        columns = self._calculate_columns()

        # Skip if column count hasn't changed and not forcing refresh
        if not force_refresh and columns == self._last_column_count and self.album_cards:
            return

        old_column_count = self._last_column_count
        self._last_column_count = columns

        # If we have existing cards and just need to reposition them
        if self.album_cards and old_column_count > 0 and not force_refresh:
            self._reposition_cards(columns)
            return

        # Full rebuild: Clear existing cards
        self.album_cards.clear()
        self._loading_cards.clear()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add cards with lazy loading enabled
        for i, album in enumerate(self.albums):
            card = AlbumCard(album, lazy_load=True)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(
                lambda pos, a=album, c=card: self._show_card_context_menu(pos, a, c)
            )

            row = i // columns
            col = i % columns
            self.grid_layout.addWidget(card, row, col)
            self.album_cards[str(album.path)] = card

        # Add stretch at bottom
        self._update_row_stretch(columns)

        # Ensure the grid widget updates its size for proper scrolling
        self.grid_widget.updateGeometry()
        self.grid_widget.adjustSize()

    def _reposition_cards(self, columns: int) -> None:
        """Reposition existing cards without recreating them."""
        # Remove all widgets from layout without deleting them
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)

        # Re-add cards in new positions
        for i, album in enumerate(self.albums):
            path_str = str(album.path)
            if path_str in self.album_cards:
                card = self.album_cards[path_str]
                row = i // columns
                col = i % columns
                self.grid_layout.addWidget(card, row, col)

        # Update stretch
        self._update_row_stretch(columns)

        # Ensure the grid widget updates its size for proper scrolling
        self.grid_widget.updateGeometry()
        self.grid_widget.adjustSize()

    def _update_row_stretch(self, columns: int) -> None:
        """Update row stretch for the grid layout."""
        # Reset all row stretches
        for i in range(self.grid_layout.rowCount()):
            self.grid_layout.setRowStretch(i, 0)
        # Add stretch at bottom
        self.grid_layout.setRowStretch(len(self.albums) // columns + 1, 1)

    def _populate_list(self) -> None:
        """Populate the list view."""
        self.list_widget.clear()

        for album in self.albums:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, album)

            # Create display text
            artist = album.artist or tr("Unknown artist")
            title = album.album or tr("Unknown album")
            year = f" ({album.year})" if album.year else ""

            # Status indicator
            status_map = {
                CoverStatus.NONE: "[X]",
                CoverStatus.EMBEDDED_ONLY: "[E]",
                CoverStatus.FOLDER_ONLY: "[F]",
                CoverStatus.BOTH: "[OK]",
            }
            status = status_map.get(album.cover_status, "[?]")

            # AcoustID indicator
            acoustid_indicator = "[A]" if album.acoustid else ""

            # Single track indicator
            track_indicator = "[1]" if album.track_count == 1 else ""

            item.setText(f"{status}{acoustid_indicator}{track_indicator} {artist} - {title}{year}")

            # Set icon from cover if available
            if album.cover.folder_path and album.cover.folder_path.exists():
                pixmap = QPixmap(str(album.cover.folder_path))
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio)))

            self.list_widget.addItem(item)

    def _on_scroll(self) -> None:
        """Handle scroll event - debounce and check visibility."""
        self._scroll_timer.start(SCROLL_DEBOUNCE_MS)

    def _on_scroll_debounced(self) -> None:
        """Handle scroll after debounce delay."""
        self._check_visible_cards()

    def _check_visible_cards(self) -> None:
        """Check which cards are visible and trigger loading for them."""
        if self.view_mode != "grid" or not self.album_cards:
            return

        viewport = self.grid_scroll.viewport()
        viewport_rect = viewport.rect()

        # Expand viewport rect by preload margin
        expanded_rect = viewport_rect.adjusted(
            -PRELOAD_MARGIN, -PRELOAD_MARGIN, PRELOAD_MARGIN, PRELOAD_MARGIN
        )

        visible_paths: set[str] = set()
        cards_to_load: list[tuple] = []  # (album_path, card, priority)

        for album_path, card in self.album_cards.items():
            # Get card position relative to viewport
            card_pos = card.mapTo(viewport, card.rect().topLeft())
            card_rect = card.rect()
            card_rect.moveTopLeft(card_pos)

            # Check if card intersects with expanded viewport
            if expanded_rect.intersects(card_rect):
                visible_paths.add(album_path)

                # Only queue loading if not already loaded and not already loading
                if not card.is_cover_loaded() and album_path not in self._loading_cards:
                    # Higher priority for cards actually visible (not just preload zone)
                    is_visible = viewport_rect.intersects(card_rect)
                    priority = VISIBLE_PRIORITY if is_visible else 0
                    cards_to_load.append((album_path, card, priority))

        # Cancel loading for cards that scrolled out of view
        self._thumbnail_loader.cancel_all_except(visible_paths)
        self._loading_cards &= visible_paths

        # Sort by priority (highest first) and queue loading
        cards_to_load.sort(key=lambda x: x[2], reverse=True)

        for album_path, card, priority in cards_to_load:
            # Try to get from cache first
            cached = self._thumbnail_loader.request_thumbnail(
                card.album, AlbumCard.COVER_SIZE, priority
            )

            if cached is not None:
                # Immediately set cached pixmap
                card.set_cover_pixmap(cached)
            else:
                # Mark as loading and show spinner
                self._loading_cards.add(album_path)
                card.set_loading(True)

    @Slot(str, QPixmap)
    def _on_thumbnail_ready(self, album_path: str, pixmap: QPixmap) -> None:
        """Handle thumbnail loaded from background thread."""
        # Remove from loading set
        self._loading_cards.discard(album_path)

        # Update the card if it still exists
        if album_path in self.album_cards:
            card = self.album_cards[album_path]
            card.set_cover_pixmap(pixmap)

    def _on_card_clicked(self, album: AlbumInfo, modifiers) -> None:
        """Handle card click."""
        # Find the index of the clicked album
        try:
            clicked_index = self.albums.index(album)
        except ValueError:
            return

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            # Toggle selection
            if album in self.selected_albums:
                self.selected_albums.remove(album)
            else:
                self.selected_albums.append(album)
            # Update last clicked for potential future range selection
            self._last_clicked_index = clicked_index
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Range selection
            if self._last_clicked_index is not None:
                # Select all albums between last clicked and current clicked
                start_idx = min(self._last_clicked_index, clicked_index)
                end_idx = max(self._last_clicked_index, clicked_index)
                # Add all albums in range to selection (without clearing existing)
                for idx in range(start_idx, end_idx + 1):
                    if self.albums[idx] not in self.selected_albums:
                        self.selected_albums.append(self.albums[idx])
            else:
                # No previous anchor, just select this album
                if album not in self.selected_albums:
                    self.selected_albums.append(album)
                self._last_clicked_index = clicked_index
        else:
            # Single selection
            self.selected_albums = [album]
            self._last_clicked_index = clicked_index

        self._update_card_selection()

        if len(self.selected_albums) == 1:
            self.album_selected.emit(self.selected_albums[0])
        else:
            self.albums_selected.emit(self.selected_albums)

    def _on_card_double_clicked(self, album: AlbumInfo) -> None:
        """Handle card double click."""
        # Could open in file manager or trigger search

    def _show_card_context_menu(self, pos, album: AlbumInfo, card: AlbumCard) -> None:
        """Show context menu for an album card."""
        # Check for multi-selection
        if len(self.selected_albums) > 1 and album in self.selected_albums:
            menu = self._build_multi_selection_context_menu()
        else:
            menu = self._build_album_context_menu(album)
        if menu.actions():
            menu.exec(card.mapToGlobal(pos))

    def _show_list_context_menu(self, pos: QPoint) -> None:
        """Show context menu for list view item."""
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        album = item.data(Qt.ItemDataRole.UserRole)
        if not album:
            return

        # Check for multi-selection
        if len(self.selected_albums) > 1 and album in self.selected_albums:
            menu = self._build_multi_selection_context_menu()
        else:
            menu = self._build_album_context_menu(album)
        if menu.actions():
            menu.exec(self.list_widget.mapToGlobal(pos))

    def _can_group_as_album(self) -> bool:
        """
        Check if selected albums can be grouped as a single album.

        Albums can be grouped if:
        - At least 2 albums are selected
        - All selected albums are individual files (track_count == 1)
        - All selected albums share the same parent folder
        - No forced groups are included
        """
        if len(self.selected_albums) < 2:
            return False

        # Check no forced groups are included
        if any(a.is_forced_group for a in self.selected_albums):
            return False

        # Check all are individual files
        if not all(a.track_count == 1 for a in self.selected_albums):
            return False

        # Check all share the same parent folder
        # For individual files, path is the file itself, so we check parent
        parents = set()
        for album in self.selected_albums:
            parent = album.path.parent if album.path.is_file() else album.path
            parents.add(parent)

        return len(parents) == 1

    def _get_add_to_group_info(self) -> tuple:
        """
        Check if selected albums can be added to an existing group.

        Returns:
            tuple: (can_add, target_group, individual_files, error_message)
            - can_add: True if files can be added to a group
            - target_group: The AlbumInfo of the group to add to (or None)
            - individual_files: List of individual files to add (or [])
            - error_message: Error message if can_add is False (or None)
        """
        if len(self.selected_albums) < 2:
            return (False, None, [], None)

        # Find forced groups and individual files
        forced_groups = [a for a in self.selected_albums if a.is_forced_group]
        individual_files = [
            a for a in self.selected_albums if a.track_count == 1 and not a.is_forced_group
        ]

        # Multiple groups selected
        if len(forced_groups) > 1:
            return (False, None, [], tr("Select only one group to add files to"))

        # Exactly one group and at least one individual file
        if len(forced_groups) == 1 and len(individual_files) >= 1:
            target_group = forced_groups[0]

            # Check all individual files are in the same folder as the group
            group_folder = target_group.path
            for album in individual_files:
                file_parent = album.path.parent if album.path.is_file() else album.path
                if file_parent != group_folder:
                    return (False, None, [], tr("Files must be in the same folder as the group"))

            return (True, target_group, individual_files, None)

        return (False, None, [], None)

    def _build_multi_selection_context_menu(self) -> QMenu:
        """Build a context menu for multiple selected albums."""
        menu = QMenu(self)

        # Group as album option (only for individual files)
        if self._can_group_as_album():
            group_action = menu.addAction(tr("Group as album"))
            group_action.setToolTip(tr("Combine selected files into a single album entry"))
            group_action.triggered.connect(
                lambda: self.group_as_album_requested.emit(list(self.selected_albums))
            )

        # Add to group option (one group + individual files)
        can_add, target_group, files_to_add, error_msg = self._get_add_to_group_info()
        if can_add and target_group:
            add_action = menu.addAction(tr("Add to group"))
            add_action.setToolTip(tr("Add selected files to the existing group"))
            # Capture values in lambda closure
            add_action.triggered.connect(
                lambda checked=False,
                tg=target_group,
                fa=files_to_add: self.add_to_group_requested.emit(tg, fa)
            )
        elif error_msg:
            # Show disabled action with error message
            error_action = menu.addAction(tr("Add to group"))
            error_action.setEnabled(False)
            error_action.setToolTip(error_msg)

        return menu

    def _build_album_context_menu(self, album: AlbumInfo) -> QMenu:
        """Build a context menu for an album with all available actions."""
        menu = QMenu(self)

        # === File operations section ===
        # Open in file manager
        open_fm_action = menu.addAction(tr("Open in file manager"))
        open_fm_action.triggered.connect(lambda: self._open_album_in_file_manager(album))

        # Open terminal here
        open_term_action = menu.addAction(tr("Open terminal here"))
        open_term_action.triggered.connect(lambda: self._open_terminal_at_album(album))

        # Copy path
        copy_path_action = menu.addAction(tr("Copy path"))
        copy_path_action.triggered.connect(lambda: self._copy_album_path(album))

        menu.addSeparator()

        # === Cover operations section ===
        # Search for cover
        search_action = menu.addAction(tr("Search for a cover..."))
        search_action.triggered.connect(lambda: self.search_cover_requested.emit(album))

        # Remove cover (only if has cover)
        if album.has_any_cover:
            remove_action = menu.addAction(tr("Remove cover"))
            remove_action.triggered.connect(lambda: self.remove_cover_requested.emit(album))

        # Find identical covers action
        if album.has_any_cover:
            cover = album.cover
            has_embedded = cover.has_embedded and album.sample_file
            has_folder = cover.folder_path and cover.folder_path.exists()

            menu.addSeparator()

            if has_embedded and has_folder:
                # Submenu to choose which cover to use
                find_menu = menu.addMenu(tr("Find identical covers"))
                embedded_action = find_menu.addAction(tr("By audio tags cover"))
                embedded_action.triggered.connect(lambda: self._find_identical_by_embedded(album))
                folder_action = find_menu.addAction(tr("By file cover"))
                folder_action.triggered.connect(lambda: self._find_identical_by_folder(album))
            elif has_embedded:
                action = menu.addAction(tr("Find identical covers"))
                action.triggered.connect(lambda: self._find_identical_by_embedded(album))
            elif has_folder:
                action = menu.addAction(tr("Find identical covers"))
                action.triggered.connect(lambda: self._find_identical_by_folder(album))

        # AcoustID identification option (if sample file available and fingerprinting is available)
        from ..core.fingerprint import is_fingerprinting_available

        if album.sample_file and album.sample_file.exists() and is_fingerprinting_available():
            if not album.has_any_cover:
                menu.addSeparator()
            acoustid_action = menu.addAction(tr("Identify via AcoustID"))
            acoustid_action.setToolTip(tr("Use audio fingerprinting to identify this album"))
            acoustid_action.triggered.connect(lambda: self.acoustid_identify_requested.emit(album))

        # Ungroup option (only for forced groups)
        if album.is_forced_group:
            menu.addSeparator()
            ungroup_action = menu.addAction(tr("Ungroup album"))
            ungroup_action.setToolTip(tr("Split back into individual file entries"))
            ungroup_action.triggered.connect(lambda: self.ungroup_album_requested.emit(album))

        return menu

    def _open_album_in_file_manager(self, album: AlbumInfo) -> None:
        """Open the album's folder in the system file manager."""
        from ..utils.file_manager import open_in_file_manager
        from .widgets.toast_manager import ToastManager

        success = open_in_file_manager(album.path)
        if not success:
            ToastManager.get_instance().show_error(tr("Unable to open file manager"))

    def _open_terminal_at_album(self, album: AlbumInfo) -> None:
        """Open a terminal at the album's folder."""
        from ..utils.file_manager import open_terminal_at
        from .widgets.toast_manager import ToastManager

        # Get directory (parent if path is a file)
        target_dir = album.path if album.path.is_dir() else album.path.parent
        success = open_terminal_at(target_dir)
        if not success:
            ToastManager.get_instance().show_error(tr("Unable to open terminal"))

    def _copy_album_path(self, album: AlbumInfo) -> None:
        """Copy the album's path to clipboard."""
        from .widgets.toast_manager import ToastManager

        clipboard = QApplication.clipboard()
        clipboard.setText(str(album.path))
        ToastManager.get_instance().show_info(tr("Path copied to clipboard"))

    def _find_identical_by_embedded(self, album: AlbumInfo) -> None:
        """Find albums with identical embedded cover."""
        # Use cached hash if available
        if album.cover.embedded_hash:
            self.find_identical_requested.emit(album.cover.embedded_hash)
            return

        from ..utils.cover_hash import compute_embedded_hash

        if album.sample_file:
            cover_hash = compute_embedded_hash(album.sample_file)
            if cover_hash:
                album.cover.embedded_hash = cover_hash
                self.find_identical_requested.emit(cover_hash)

    def _find_identical_by_folder(self, album: AlbumInfo) -> None:
        """Find albums with identical folder cover."""
        # Use cached hash if available
        if album.cover.folder_hash:
            self.find_identical_requested.emit(album.cover.folder_hash)
            return

        from ..utils.cover_hash import compute_folder_hash

        if album.cover.folder_path:
            cover_hash = compute_folder_hash(album.cover.folder_path)
            if cover_hash:
                album.cover.folder_hash = cover_hash
                self.find_identical_requested.emit(cover_hash)

    def _on_list_selection_changed(self) -> None:
        """Handle list selection change."""
        self.selected_albums = []
        for item in self.list_widget.selectedItems():
            album = item.data(Qt.ItemDataRole.UserRole)
            if album:
                self.selected_albums.append(album)

        if len(self.selected_albums) == 1:
            self.album_selected.emit(self.selected_albums[0])
        elif len(self.selected_albums) > 1:
            self.albums_selected.emit(self.selected_albums)

    def _update_card_selection(self) -> None:
        """Update card selection visual state."""
        for _path, card in self.album_cards.items():
            card.set_selected(card.album in self.selected_albums)

    def select_all(self) -> None:
        """Select all albums."""
        if self.view_mode == "grid":
            self.selected_albums = list(self.albums)
            self._update_card_selection()
        else:
            self.list_widget.selectAll()

        self.albums_selected.emit(self.selected_albums)

    def clear_selection(self) -> None:
        """Clear selection."""
        self.selected_albums = []
        self._last_clicked_index = None
        if self.view_mode == "grid":
            self._update_card_selection()
        else:
            self.list_widget.clearSelection()
        # Emit signal to notify that selection is cleared
        self.albums_selected.emit([])

    def get_selected_albums(self) -> list[AlbumInfo]:
        """Get list of currently selected albums."""
        return list(self.selected_albums)

    def refresh_album(self, album: AlbumInfo) -> None:
        """Refresh the display of a specific album."""
        path_str = str(album.path)

        # Invalidate cached thumbnail
        self._thumbnail_loader.invalidate_cache(path_str)

        if path_str in self.album_cards:
            self.album_cards[path_str].update_display()

        # Also update list view if visible
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item_album = item.data(Qt.ItemDataRole.UserRole)
            if item_album and str(item_album.path) == path_str:
                # Update the item display
                self._update_list_item(item, album)
                break

    def _update_list_item(self, item: QListWidgetItem, album: AlbumInfo) -> None:
        """Update a list item display."""
        artist = album.artist or tr("Unknown artist")
        title = album.album or tr("Unknown album")
        year = f" ({album.year})" if album.year else ""

        status_map = {
            CoverStatus.NONE: "[X]",
            CoverStatus.EMBEDDED_ONLY: "[E]",
            CoverStatus.FOLDER_ONLY: "[F]",
            CoverStatus.BOTH: "[OK]",
        }
        status = status_map.get(album.cover_status, "[?]")

        # AcoustID indicator
        acoustid_indicator = "[A]" if album.acoustid else ""

        # Single track indicator
        track_indicator = "[1]" if album.track_count == 1 else ""

        item.setText(f"{status}{acoustid_indicator}{track_indicator} {artist} - {title}{year}")
        item.setData(Qt.ItemDataRole.UserRole, album)

    def eventFilter(self, watched, event) -> bool:
        """Filter events from the viewport to detect resize."""
        if (
            watched == self.grid_scroll.viewport()
            and event.type() == QEvent.Type.Resize
            and self.view_mode == "grid"
            and self.albums
        ):
            # Debounce: restart timer on each resize event
            self._resize_timer.start(RESIZE_DEBOUNCE_MS)
        return super().eventFilter(watched, event)

    def _on_resize_debounced(self) -> None:
        """Handle resize after debounce delay."""
        if self.view_mode == "grid" and self.albums:
            # Only refresh if column count would change
            new_columns = self._calculate_columns()
            if new_columns != self._last_column_count:
                self._populate_grid()
                # Re-check visible cards after layout change
                QTimer.singleShot(0, self._check_visible_cards)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+A: Select all visible albums
            self.select_all()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            # Escape: Clear selection
            self.clear_selection()
            event.accept()
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drag events for files and folders with visual feedback."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            # Visual feedback: semi-transparent blue overlay with border
            self.stack.setStyleSheet(f"QStackedWidget {{ {Styles.DROP_ZONE_ACTIVE} }}")
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Remove visual feedback when drag leaves."""
        self.stack.setStyleSheet("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle dropped files and folders."""
        # Remove visual feedback
        self.stack.setStyleSheet("")
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
        event.ignore()

    def showEvent(self, event) -> None:
        """Handle show event - trigger visibility check and column recalculation."""
        super().showEvent(event)
        if self.view_mode == "grid" and self.albums:
            # Recalculate columns after show (viewport size is now valid)
            QTimer.singleShot(0, self._on_resize_debounced)
            QTimer.singleShot(0, self._check_visible_cards)

    def closeEvent(self, event) -> None:
        """Handle close event - cleanup timers and loader."""
        if self._resize_timer.isActive():
            self._resize_timer.stop()
        if self._scroll_timer.isActive():
            self._scroll_timer.stop()
        self._thumbnail_loader.shutdown()
        super().closeEvent(event)
