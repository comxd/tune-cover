"""
Album detail panel for displaying and editing album information.
"""

import contextlib
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..api.musicbrainz import MusicBrainzProvider
from ..core.cover_save_strategy import CoverSaveDecision, CoverSaveStrategy
from ..core.embedder import (
    CoverEmbedder,
    detect_image_mime_type,
    extract_embedded_cover,
    get_extension_for_mime,
)
from ..core.filter_context import FilterContext, MatchSource
from ..core.models import AlbumInfo, SearchResult
from ..core.scanner import _get_image_dimensions_from_bytes
from ..i18n import tr
from ..utils.config import Config
from .dialogs.cover_comparison import CoverComparisonDialog
from .dialogs.cover_zoom_dialog import CoverZoomDialog
from .search_panel import SearchPanel
from .widgets.toast_manager import ToastManager

logger = logging.getLogger(__name__)


class ClickablePathLabel(QLabel):
    """
    A clickable QLabel for displaying file paths with hover effect.

    Features:
    - Click to open in file manager
    - Hover effect (underline on mouse over)
    """

    # Signals
    path_clicked = Signal(Path)

    # Style constants
    STYLE_NORMAL = "font-size: 10px; color: #5dade2;"
    STYLE_HOVER = "font-size: 10px; color: #5dade2; text-decoration: underline;"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: Path | None = None

        # Setup appearance
        self.setStyleSheet(self.STYLE_NORMAL)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setWordWrap(True)

    def set_path(self, path: Path, display_text: str, tooltip: str):
        """Set the path and display text."""
        self._path = path
        self.setText(display_text)
        self.setToolTip(tooltip)

    def get_path(self) -> Path | None:
        """Get the current path."""
        return self._path

    def enterEvent(self, event):
        """Mouse enters - show underline."""
        self.setStyleSheet(self.STYLE_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Mouse leaves - remove underline."""
        self.setStyleSheet(self.STYLE_NORMAL)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse click - open in file manager on left click."""
        if event.button() == Qt.MouseButton.LeftButton and self._path:
            self.path_clicked.emit(self._path)
        super().mousePressEvent(event)


class FetchWorker(QThread):
    """Worker thread for fetching covers."""

    progress = Signal(int, int, str)  # current, total, message
    # album, success, message, cover_update_dict (for thread-safe updates)
    album_done = Signal(AlbumInfo, bool, str, dict)
    finished = Signal()

    def __init__(self, albums: list[AlbumInfo], config: Config):
        super().__init__()
        self.albums = albums
        self.config = config
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        contact_email = self.config.get("app.contact_email", "")
        provider = MusicBrainzProvider(contact_email=contact_email)
        preserve_timestamp = self.config.get("embedding.preserve_timestamp", True)
        embedder = CoverEmbedder(preserve_timestamp=preserve_timestamp)
        total = len(self.albums)

        for i, album in enumerate(self.albums):
            if self._cancelled:
                break

            self.progress.emit(i + 1, total, album.display_name)

            try:
                best_result = None
                best_score = 0

                # Strategy 1: Direct lookup by MBID (most reliable)
                if album.musicbrainz_albumid:
                    logger.info(
                        f"Trying direct MBID lookup for {album.display_name}: {album.musicbrainz_albumid}"
                    )
                    result = provider.lookup_by_mbid(album.musicbrainz_albumid)
                    if result:
                        best_result = result
                        best_score = 100
                        logger.info("Direct MBID lookup successful")

                # Strategy 2: Text search (fallback)
                if not best_result:
                    logger.info(f"Falling back to text search for {album.display_name}")
                    results = provider.search(album.artist or "", album.album or "", album.year)

                    if not results:
                        self.album_done.emit(album, False, tr("No result"), {})
                        continue

                    # Find best match with high score
                    for result in results:
                        score = provider.calculate_match_score(
                            album.artist or "", album.album or "", album.year, result
                        )
                        if score > best_score and result.score >= 90:
                            best_score = score
                            best_result = result

                if not best_result or best_score < 60:
                    self.album_done.emit(album, False, tr("No sufficient match"), {})
                    continue

                # Get cover URL
                cover_url = provider.get_cover_url(best_result)
                if not cover_url:
                    self.album_done.emit(album, False, tr("No cover available"), {})
                    continue

                # Download cover
                cover_data = provider.download_cover(cover_url)
                if not cover_data:
                    self.album_done.emit(album, False, tr("Download error"), {})
                    continue

                # Save cover using the save strategy
                mime_type = detect_image_mime_type(cover_data)
                cover_update = {}

                # Use the cover save strategy to determine what to do
                from ..core.cover_save_strategy import CoverSaveStrategy

                strategy = CoverSaveStrategy(self.config)
                decision = strategy.evaluate(album)

                # Handle single file vs folder albums
                is_single_file = album.path.is_file()

                # Save external file if strategy allows
                if decision.save_external_file:
                    target_folder = album.path.parent if is_single_file else album.path
                    embedder.save_cover_to_folder(cover_data, target_folder)
                    cover_update["has_folder"] = True
                    cover_update["folder_file"] = "cover.jpg"
                    cover_update["folder_path"] = str(target_folder / "cover.jpg")

                # Embed in tags if strategy allows
                if decision.embed_in_tags:
                    if is_single_file:
                        embedder.embed_cover_in_file(album.path, cover_data, mime_type)
                        cover_update["has_embedded"] = True
                    else:
                        embedder.embed_cover_in_folder(cover_data, album.path, mime_type)
                        cover_update["has_embedded"] = True

                self.album_done.emit(album, True, tr("Cover applied"), cover_update)

            except Exception as e:
                logger.exception(f"Error processing {album.display_name}")
                self.album_done.emit(album, False, str(e), {})

        self.finished.emit()


class AlbumDetailPanel(QWidget):
    """
    Panel for displaying album details and cover search functionality.
    """

    cover_applied = Signal(AlbumInfo)
    identical_covers_requested = Signal(str)  # hash to search for
    ungroup_album_requested = Signal(AlbumInfo)  # request to ungroup forced group

    # Style for destructive action buttons (delete/remove)
    DESTRUCTIVE_BUTTON_STYLE = """
        QPushButton {
            background-color: #8b0000;
            color: white;
            border: 1px solid #a00000;
            border-radius: 3px;
            padding: 4px 8px;
        }
        QPushButton:hover {
            background-color: #a00000;
            border: 1px solid #c00000;
        }
        QPushButton:pressed {
            background-color: #6b0000;
        }
        QPushButton:disabled {
            background-color: #4a4a4a;
            color: #888;
            border: 1px solid #555;
        }
    """

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.current_album: AlbumInfo | None = None
        self.selected_albums: list[AlbumInfo] = []
        # Filter context for context-aware actions (e.g., "delete from source")
        # Keyed by album path string since AlbumInfo is not hashable
        self.current_context: FilterContext | None = None
        self.selected_contexts: dict[str, FilterContext] = {}
        preserve_timestamp = config.get("embedding.preserve_timestamp", True)
        self.embedder = CoverEmbedder(preserve_timestamp=preserve_timestamp)
        self.save_strategy = CoverSaveStrategy(config)
        self.fetch_worker: FetchWorker | None = None

        self._setup_ui()
        # Show empty state initially (no album selected at startup)
        self._show_empty_state()

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Stacked widget to switch between detail view and multi-selection view
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Multi-selection view
        self.multi_select_widget = QWidget()
        multi_layout = QVBoxLayout(self.multi_select_widget)
        multi_layout.setContentsMargins(8, 8, 8, 8)

        # Selection count label
        self.multi_select_label = QLabel()
        self.multi_select_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.multi_select_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        multi_layout.addWidget(self.multi_select_label)

        # Statistics label
        self.multi_stats_label = QLabel()
        self.multi_stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.multi_stats_label.setStyleSheet("font-size: 12px; color: #888;")
        multi_layout.addWidget(self.multi_stats_label)

        multi_layout.addSpacing(20)

        # Batch actions group
        batch_actions_group = QGroupBox(tr("Batch actions"))
        batch_actions_layout = QVBoxLayout(batch_actions_group)

        self.multi_auto_fetch_btn = QPushButton(tr("Auto download covers"))
        self.multi_auto_fetch_btn.clicked.connect(self._start_multi_fetch)
        batch_actions_layout.addWidget(self.multi_auto_fetch_btn)

        self.multi_remove_btn = QPushButton(tr("Remove covers"))
        self.multi_remove_btn.setStyleSheet(self.DESTRUCTIVE_BUTTON_STYLE)
        self.multi_remove_btn.clicked.connect(self._remove_cover)
        batch_actions_layout.addWidget(self.multi_remove_btn)

        # Checkboxes for selective deletion in multi-selection
        multi_remove_options = QHBoxLayout()
        multi_remove_options.setContentsMargins(20, 0, 0, 0)

        self.multi_remove_embedded_cb = QCheckBox(tr("Audio tags"))
        self.multi_remove_embedded_cb.setChecked(True)
        multi_remove_options.addWidget(self.multi_remove_embedded_cb)

        self.multi_remove_folder_cb = QCheckBox(tr("File"))
        self.multi_remove_folder_cb.setChecked(True)
        multi_remove_options.addWidget(self.multi_remove_folder_cb)

        multi_remove_options.addStretch()
        batch_actions_layout.addLayout(multi_remove_options)

        # Delete from source button for multi-selection (visible only with contexts)
        self.multi_remove_from_source_btn = QPushButton(tr("Delete from source"))
        self.multi_remove_from_source_btn.setStyleSheet(self.DESTRUCTIVE_BUTTON_STYLE)
        self.multi_remove_from_source_btn.setToolTip(
            tr("Delete covers from their matched source for each album")
        )
        self.multi_remove_from_source_btn.clicked.connect(self._remove_from_source_multi)
        self.multi_remove_from_source_btn.setEnabled(False)
        self.multi_remove_from_source_btn.setVisible(False)
        batch_actions_layout.addWidget(self.multi_remove_from_source_btn)

        multi_layout.addWidget(batch_actions_group)

        # Batch progress group (for multi-selection view)
        self.multi_batch_group = QGroupBox(tr("Processing in progress"))
        multi_batch_layout = QVBoxLayout(self.multi_batch_group)

        self.multi_batch_label = QLabel("0/0")
        multi_batch_layout.addWidget(self.multi_batch_label)

        self.multi_batch_progress = QProgressBar()
        multi_batch_layout.addWidget(self.multi_batch_progress)

        self.multi_batch_cancel_btn = QPushButton(tr("Cancel"))
        self.multi_batch_cancel_btn.clicked.connect(self._cancel_batch)
        multi_batch_layout.addWidget(self.multi_batch_cancel_btn)

        self.multi_batch_group.setVisible(False)
        multi_layout.addWidget(self.multi_batch_group)

        multi_layout.addStretch()
        self.stack.addWidget(self.multi_select_widget)

        # Scroll area for single album content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.stack.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Cover previews (two sources side by side)
        cover_group = QGroupBox(tr("Covers (click to enlarge)"))
        cover_group_layout = QVBoxLayout(cover_group)

        # Horizontal layout for both covers
        covers_row = QHBoxLayout()
        covers_row.setSpacing(12)

        # Embedded cover (from tags)
        embedded_container = QVBoxLayout()
        self.embedded_cover_label = QLabel()
        self.embedded_cover_label.setFixedSize(120, 120)
        self.embedded_cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.embedded_cover_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.embedded_cover_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 4px;
            }
            QLabel:hover {
                border: 1px solid #666;
            }
        """)
        self.embedded_cover_label.mousePressEvent = self._on_embedded_cover_clicked
        embedded_container.addWidget(
            self.embedded_cover_label, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.embedded_source_label = QLabel(tr("Audio tags"))
        self.embedded_source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.embedded_source_label.setStyleSheet("font-size: 10px; color: #888;")
        embedded_container.addWidget(self.embedded_source_label)

        covers_row.addLayout(embedded_container)

        # Folder cover (external file)
        folder_container = QVBoxLayout()
        self.folder_cover_label = QLabel()
        self.folder_cover_label.setFixedSize(120, 120)
        self.folder_cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.folder_cover_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_cover_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 4px;
            }
            QLabel:hover {
                border: 1px solid #666;
            }
        """)
        self.folder_cover_label.mousePressEvent = self._on_folder_cover_clicked
        folder_container.addWidget(self.folder_cover_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.folder_source_label = QLabel(tr("File"))
        self.folder_source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.folder_source_label.setStyleSheet("font-size: 10px; color: #888;")
        folder_container.addWidget(self.folder_source_label)

        covers_row.addLayout(folder_container)

        cover_group_layout.addLayout(covers_row)
        content_layout.addWidget(cover_group)

        # Album info
        info_group = QGroupBox(tr("Information"))
        info_layout = QFormLayout(info_group)

        self.artist_label = QLabel("-")
        info_layout.addRow(tr("Artist:"), self.artist_label)

        self.album_label = QLabel("-")
        info_layout.addRow(tr("Album:"), self.album_label)

        self.year_label = QLabel("-")
        info_layout.addRow(tr("Year:"), self.year_label)

        self.tracks_label = QLabel("-")
        info_layout.addRow(tr("Tracks:"), self.tracks_label)

        # Forced group row with ungroup button (only visible for forced groups)
        self.forced_group_container = QWidget()
        forced_group_layout = QHBoxLayout(self.forced_group_container)
        forced_group_layout.setContentsMargins(0, 0, 0, 0)
        forced_group_layout.setSpacing(8)

        self.forced_group_label = QLabel()
        self.forced_group_label.setStyleSheet("color: #e67e22; font-weight: bold;")
        forced_group_layout.addWidget(self.forced_group_label, 1)

        self.ungroup_btn = QPushButton(tr("Ungroup"))
        self.ungroup_btn.setToolTip(tr("Split back into individual file entries"))
        self.ungroup_btn.clicked.connect(self._on_ungroup_clicked)
        forced_group_layout.addWidget(self.ungroup_btn)

        info_layout.addRow("", self.forced_group_container)
        self.forced_group_container.setVisible(False)

        # Path field (clickable to open in file manager)
        self.path_label = ClickablePathLabel()
        self.path_label.path_clicked.connect(self._on_path_clicked)
        info_layout.addRow(tr("Path:"), self.path_label)

        # Cover status with detailed info (two rows)
        self.cover_tags_label = QLabel("-")
        self.cover_tags_label.setTextFormat(Qt.TextFormat.RichText)
        info_layout.addRow(tr("Audio tags:"), self.cover_tags_label)

        self.cover_file_label = QLabel("-")
        self.cover_file_label.setTextFormat(Qt.TextFormat.RichText)
        info_layout.addRow(tr("File:"), self.cover_file_label)

        self.mbid_label = QLabel("-")
        self.mbid_label.setStyleSheet("font-size: 10px; color: #888;")
        self.mbid_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addRow(tr("MBID:"), self.mbid_label)

        # AcoustID row with identify button
        self.acoustid_container = QWidget()
        acoustid_layout = QHBoxLayout(self.acoustid_container)
        acoustid_layout.setContentsMargins(0, 0, 0, 0)
        acoustid_layout.setSpacing(8)

        self.acoustid_label = QLabel("-")
        self.acoustid_label.setStyleSheet("font-size: 10px; color: #888;")
        self.acoustid_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        acoustid_layout.addWidget(self.acoustid_label, 1)

        self.fingerprint_btn = QPushButton(tr("Identify"))
        self.fingerprint_btn.setToolTip(tr("Identify the album via audio fingerprint"))
        self.fingerprint_btn.setFixedWidth(80)
        self.fingerprint_btn.clicked.connect(self._launch_fingerprint)
        self.fingerprint_btn.setEnabled(False)
        acoustid_layout.addWidget(self.fingerprint_btn)

        info_layout.addRow(tr("AcoustID:"), self.acoustid_container)

        self.isrc_label = QLabel("-")
        self.isrc_label.setStyleSheet("font-size: 10px; color: #888;")
        self.isrc_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addRow(tr("ISRC:"), self.isrc_label)

        self.barcode_label = QLabel("-")
        self.barcode_label.setStyleSheet("font-size: 10px; color: #888;")
        self.barcode_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addRow(tr("Barcode:"), self.barcode_label)

        content_layout.addWidget(info_group)

        # Actions
        actions_group = QGroupBox(tr("Actions"))
        actions_layout = QVBoxLayout(actions_group)

        self.search_btn = QPushButton(tr("Search for a cover..."))
        self.search_btn.clicked.connect(self._open_search)
        self.search_btn.setEnabled(False)
        actions_layout.addWidget(self.search_btn)

        self.import_btn = QPushButton(tr("Import an image..."))
        self.import_btn.clicked.connect(self._import_image)
        self.import_btn.setEnabled(False)
        actions_layout.addWidget(self.import_btn)

        self.remove_btn = QPushButton(tr("Remove cover"))
        self.remove_btn.setStyleSheet(self.DESTRUCTIVE_BUTTON_STYLE)
        self.remove_btn.clicked.connect(self._remove_cover)
        self.remove_btn.setEnabled(False)
        actions_layout.addWidget(self.remove_btn)

        # Checkboxes for selective deletion (Feature 1)
        remove_options_layout = QHBoxLayout()
        remove_options_layout.setContentsMargins(20, 0, 0, 0)  # Indent

        self.remove_embedded_cb = QCheckBox(tr("Audio tags"))
        self.remove_embedded_cb.setChecked(True)
        self.remove_embedded_cb.toggled.connect(self._update_remove_button_state)
        remove_options_layout.addWidget(self.remove_embedded_cb)

        self.remove_folder_cb = QCheckBox(tr("File"))
        self.remove_folder_cb.setChecked(True)
        self.remove_folder_cb.toggled.connect(self._update_remove_button_state)
        remove_options_layout.addWidget(self.remove_folder_cb)

        remove_options_layout.addStretch()
        actions_layout.addLayout(remove_options_layout)

        # Delete from source button (visible only when hash filter is active)
        # This button deletes covers only from the location(s) that matched the hash filter
        # Positioned before "Find identical covers" for better visibility when active
        # Note: We use setMaximumHeight(0) instead of setVisible(False) to hide the button
        # because Qt may not properly show a widget that was initially hidden in some cases
        self.remove_from_source_btn = QPushButton(tr("Delete from source"))
        self.remove_from_source_btn.setStyleSheet(self.DESTRUCTIVE_BUTTON_STYLE)
        self.remove_from_source_btn.setToolTip(
            tr("Delete cover only from the location that matched the filter")
        )
        self.remove_from_source_btn.clicked.connect(self._remove_from_source)
        self.remove_from_source_btn.setEnabled(False)
        self.remove_from_source_btn.setMaximumHeight(0)  # Hidden by zero height
        actions_layout.addWidget(self.remove_from_source_btn)

        # Find identical covers button (Feature 3)
        self.find_identical_btn = QPushButton(tr("Find identical covers"))
        self.find_identical_btn.setToolTip(tr("Find other albums with the same cover image"))
        self.find_identical_btn.clicked.connect(self._find_identical_covers)
        self.find_identical_btn.setEnabled(False)
        actions_layout.addWidget(self.find_identical_btn)

        content_layout.addWidget(actions_group)

        # Sync actions group (visible only when covers differ)
        self.sync_group = QGroupBox(tr("Synchronization"))
        sync_layout = QVBoxLayout(self.sync_group)

        self.sync_to_file_btn = QPushButton(tr("Tags -> External file"))
        self.sync_to_file_btn.setToolTip(tr("Copy cover from tags to external file"))
        self.sync_to_file_btn.clicked.connect(self._sync_embedded_to_file)
        sync_layout.addWidget(self.sync_to_file_btn)

        self.sync_to_tags_btn = QPushButton(tr("External file -> Tags"))
        self.sync_to_tags_btn.setToolTip(tr("Copy external file to audio tags"))
        self.sync_to_tags_btn.clicked.connect(self._sync_file_to_embedded)
        sync_layout.addWidget(self.sync_to_tags_btn)

        self.sync_to_largest_btn = QPushButton(tr("Keep largest"))
        self.sync_to_largest_btn.setToolTip(tr("Replace smaller with larger"))
        self.sync_to_largest_btn.clicked.connect(self._sync_to_largest)
        sync_layout.addWidget(self.sync_to_largest_btn)

        self.compare_btn = QPushButton(tr("Compare"))
        self.compare_btn.setToolTip(tr("Compare covers in detail (zoom and pan)"))
        self.compare_btn.clicked.connect(self._open_comparison_dialog)
        sync_layout.addWidget(self.compare_btn)

        self.sync_group.setVisible(False)
        content_layout.addWidget(self.sync_group)

        # Batch progress (hidden by default)
        self.batch_group = QGroupBox(tr("Processing in progress"))
        batch_layout = QVBoxLayout(self.batch_group)

        self.batch_label = QLabel("0/0")
        batch_layout.addWidget(self.batch_label)

        self.batch_progress = QProgressBar()
        batch_layout.addWidget(self.batch_progress)

        self.batch_cancel_btn = QPushButton(tr("Cancel"))
        self.batch_cancel_btn.clicked.connect(self._cancel_batch)
        batch_layout.addWidget(self.batch_cancel_btn)

        self.batch_group.setVisible(False)
        content_layout.addWidget(self.batch_group)

        # Stretch at bottom
        content_layout.addStretch()

        # Empty state (index 2 in stack)
        self.empty_label = QLabel(tr("Select an album"))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; font-size: 14px;")
        self.stack.addWidget(self.empty_label)

    def set_album(self, album: AlbumInfo, context: FilterContext | None = None):
        """Set the album to display.

        Args:
            album: The album to display
            context: Optional filter context for context-aware actions
        """
        logger.debug(f"set_album: album={album.display_name}, context={context}")
        self.current_album = album
        self.current_context = context
        self.selected_albums = [album]
        self.selected_contexts = {str(album.path): context} if context else {}
        self._update_display()

    def set_albums(self, albums: list[AlbumInfo], contexts: dict[str, FilterContext] | None = None):
        """Set multiple albums (for batch operations).

        Args:
            albums: List of albums to display/operate on
            contexts: Optional dict mapping album paths (str) to their filter contexts
        """
        self.selected_albums = albums
        self.selected_contexts = contexts or {}
        if len(albums) == 1:
            self.current_album = albums[0]
            self.current_context = self.selected_contexts.get(str(albums[0].path))
        else:
            self.current_album = None
            self.current_context = None
        self._update_display()

    def clear(self):
        """Clear the panel, resetting to empty state."""
        self.current_album = None
        self.current_context = None
        self.selected_albums = []
        self.selected_contexts = {}
        self._show_empty_state()

    def _update_display(self):
        """Update the display with current album data."""
        # Check for multi-selection first
        if len(self.selected_albums) > 1:
            self._show_multi_selection_state()
            return

        if not self.current_album:
            self._show_empty_state()
            return

        # Show single album detail view
        self.stack.setCurrentIndex(1)  # Scroll area with details

        album = self.current_album

        # Update cover
        self._update_cover_display()

        # Update info labels
        self.artist_label.setText(album.artist or tr("Unknown"))
        self.album_label.setText(album.album or tr("Unknown"))
        self.year_label.setText(album.year or "-")
        self.tracks_label.setText(str(album.track_count))

        # Update forced group display
        if album.is_forced_group:
            self.forced_group_label.setText(
                tr("Manually grouped ({count} files)").format(count=len(album.forced_group_files))
            )
            self.forced_group_container.setVisible(True)
        else:
            self.forced_group_container.setVisible(False)

        # Update path display
        from ..utils.file_manager import truncate_path

        path_display = truncate_path(album.path, max_length=80)
        tooltip = tr("Click to open in file manager") + f"\n{album.path}"
        self.path_label.set_path(album.path, path_display, tooltip)

        # Update cover status with detailed info
        self._update_cover_info_labels(album)

        # Update MBID
        if album.musicbrainz_albumid:
            self.mbid_label.setText(album.musicbrainz_albumid)
        else:
            self.mbid_label.setText(tr("Not detected"))

        # Update AcoustID
        self._update_acoustid_display()

        # Update ISRC
        if album.isrc:
            self.isrc_label.setText(album.isrc)
        else:
            self.isrc_label.setText("-")

        # Update Barcode
        if album.barcode:
            self.barcode_label.setText(album.barcode)
        else:
            self.barcode_label.setText("-")

        # Enable/disable buttons
        self.search_btn.setEnabled(True)
        self.import_btn.setEnabled(True)

        # Update checkboxes based on what covers exist
        # Enable and check only if corresponding cover exists
        self.remove_embedded_cb.setEnabled(album.cover.has_embedded)
        self.remove_embedded_cb.setChecked(album.cover.has_embedded)

        self.remove_folder_cb.setEnabled(album.cover.has_folder)
        self.remove_folder_cb.setChecked(album.cover.has_folder)

        # Enable remove button based on checkbox state and cover availability
        self._update_remove_button_state()

        # Enable find identical button if album has any cover
        self.find_identical_btn.setEnabled(album.has_any_cover)

        # Update context-aware actions (e.g., "Delete from source" button)
        self._update_context_actions()

    def _on_path_clicked(self, path: Path):
        """Open the given path in the system file manager."""
        from ..utils.file_manager import open_in_file_manager

        success = open_in_file_manager(path)

        if not success:
            ToastManager.get_instance().show_error(tr("Unable to open file manager"))

    def _on_ungroup_clicked(self):
        """Handle click on ungroup button."""
        if self.current_album and self.current_album.is_forced_group:
            self.ungroup_album_requested.emit(self.current_album)

    def _update_cover_display(self):
        """Update both cover image displays."""
        cover_size = 120

        # Default empty pixmaps
        empty_pixmap = QPixmap(cover_size, cover_size)
        empty_pixmap.fill(QColor("#2a2a2a"))

        embedded_pixmap = QPixmap(empty_pixmap)
        folder_pixmap = QPixmap(empty_pixmap)

        if self.current_album:
            # Load embedded cover
            if self.current_album.cover.has_embedded and self.current_album.sample_file:
                embedded_data = extract_embedded_cover(self.current_album.sample_file)
                if embedded_data:
                    loaded = QPixmap()
                    if loaded.loadFromData(embedded_data):
                        embedded_pixmap = loaded.scaled(
                            cover_size,
                            cover_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )

            # Load folder cover
            if (
                self.current_album.cover.folder_path
                and self.current_album.cover.folder_path.exists()
            ):
                loaded = QPixmap(str(self.current_album.cover.folder_path))
                if not loaded.isNull():
                    folder_pixmap = loaded.scaled(
                        cover_size,
                        cover_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

        self.embedded_cover_label.setPixmap(embedded_pixmap)
        self.folder_cover_label.setPixmap(folder_pixmap)

        # Update border style based on whether covers differ
        covers_differ = self.current_album and self.current_album.cover.covers_differ

        if covers_differ:
            # Orange border to indicate covers are different
            border_style = """
                QLabel {
                    background-color: #2a2a2a;
                    border: 2px solid #e67e22;
                    border-radius: 4px;
                }
                QLabel:hover {
                    border: 2px solid #f39c12;
                }
            """
        else:
            # Normal border
            border_style = """
                QLabel {
                    background-color: #2a2a2a;
                    border: 1px solid #444;
                    border-radius: 4px;
                }
                QLabel:hover {
                    border: 1px solid #666;
                }
            """

        self.embedded_cover_label.setStyleSheet(border_style)
        self.folder_cover_label.setStyleSheet(border_style)

    def _update_cover_info_labels(self, album: AlbumInfo):
        """Update the cover info labels with detailed information."""
        cover = album.cover

        # Format embedded (tags) cover info
        if cover.has_embedded:
            tags_text = self._format_cover_info(
                True, cover.embedded_dimensions, cover.embedded_size_bytes, cover.embedded_mime_type
            )
        else:
            tags_text = '<span style="color: #888;">\u2717 ' + tr("Absent") + "</span>"

        self.cover_tags_label.setText(tags_text)

        # Format folder (file) cover info
        if cover.has_folder:
            file_text = self._format_cover_info(
                True, cover.folder_dimensions, cover.folder_size_bytes, cover.folder_mime_type
            )
            # Add warning if covers differ
            if cover.covers_differ:
                file_text += ' <span style="color: #e67e22;">\u26a0 ' + tr("different") + "</span>"
        else:
            file_text = '<span style="color: #888;">\u2717 ' + tr("Absent") + "</span>"

        self.cover_file_label.setText(file_text)

        # Update sync group visibility and button states
        self._update_sync_group(cover)

    def _update_sync_group(self, cover):
        """Update sync group visibility, title, and button states based on cover availability.

        The sync group is shown when:
        - Only embedded cover exists (can copy to file)
        - Only folder cover exists (can copy to tags)
        - Both exist but are different (can sync either direction)

        The sync group is hidden when:
        - Neither cover exists (nothing to sync)
        - Both exist and are identical (already in sync)
        """
        has_embedded = cover.has_embedded
        has_folder = cover.has_folder
        covers_differ = cover.covers_differ

        # Determine if we should show the sync group
        only_embedded = has_embedded and not has_folder
        only_folder = has_folder and not has_embedded
        both_different = has_embedded and has_folder and covers_differ

        show_sync = only_embedded or only_folder or both_different

        if not show_sync:
            self.sync_group.setVisible(False)
            return

        # Update group title based on context
        if both_different:
            self.sync_group.setTitle(tr("Synchronization"))
        else:
            self.sync_group.setTitle(tr("Copy cover"))

        # Update button states
        # "Tags -> External file" - needs embedded to exist
        self.sync_to_file_btn.setEnabled(has_embedded)
        self.sync_to_file_btn.setVisible(True)

        # "External file -> Tags" - needs folder to exist
        self.sync_to_tags_btn.setEnabled(has_folder)
        self.sync_to_tags_btn.setVisible(True)

        # "Keep largest" and "Compare" - need both covers to exist
        self.sync_to_largest_btn.setVisible(both_different)
        self.compare_btn.setVisible(both_different)

        self.sync_group.setVisible(True)

    def _format_cover_info(
        self, exists: bool, dimensions: tuple, size_bytes: int, mime_type: str
    ) -> str:
        """Format cover info as a rich text string."""
        if not exists:
            return '<span style="color: #888;">\u2717 ' + tr("Absent") + "</span>"

        parts = ['<span style="color: #27ae60;">✓</span>']

        # Dimensions
        if dimensions:
            parts.append(f"{dimensions[0]}x{dimensions[1]}")
        else:
            parts.append("?x?")

        # File size
        if size_bytes:
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{size_bytes / 1024:.0f} KB"
            parts.append(size_str)

        # File type (simplified from MIME)
        if mime_type:
            type_map = {
                "image/jpeg": "JPEG",
                "image/png": "PNG",
                "image/gif": "GIF",
                "image/webp": "WebP",
                "image/bmp": "BMP",
            }
            type_str = type_map.get(mime_type, mime_type.split("/")[-1].upper())
            parts.append(type_str)

        # Join with bullet separator
        return " • ".join(parts)

    def _show_empty_state(self):
        """Show the empty state."""
        self.stack.setCurrentIndex(2)  # Show empty label

    def _show_multi_selection_state(self):
        """Show the multi-selection state with statistics and batch actions."""
        count = len(self.selected_albums)
        self.multi_select_label.setText(
            tr("Multiple selection\n{count} albums").format(count=count)
        )

        # Compute statistics
        without_cover = sum(1 for a in self.selected_albums if not a.has_any_cover)
        with_embedded = sum(1 for a in self.selected_albums if a.cover.has_embedded)
        with_folder = sum(1 for a in self.selected_albums if a.cover.has_folder)
        with_any_cover = sum(1 for a in self.selected_albums if a.has_any_cover)

        stats_lines = []
        if without_cover > 0:
            stats_lines.append(tr("{n} without cover").format(n=without_cover))
        if with_any_cover > 0:
            stats_lines.append(tr("{n} with cover").format(n=with_any_cover))

        self.multi_stats_label.setText(" | ".join(stats_lines) if stats_lines else "")

        # Enable/disable buttons based on selection
        self.multi_auto_fetch_btn.setEnabled(without_cover > 0)
        self.multi_remove_btn.setEnabled(with_any_cover > 0)

        # Enable checkboxes based on what covers exist in selection
        self.multi_remove_embedded_cb.setEnabled(with_embedded > 0)
        self.multi_remove_embedded_cb.setChecked(with_embedded > 0)
        self.multi_remove_folder_cb.setEnabled(with_folder > 0)
        self.multi_remove_folder_cb.setChecked(with_folder > 0)

        # Show "Delete from source" button if any albums have filter context AND
        # still have covers at their matched source (so deletion is actually possible)
        albums_with_deletable_context = 0
        for album in self.selected_albums:
            ctx = self.selected_contexts.get(str(album.path))
            if ctx and ctx.match_source:
                # Check if album still has cover at the matched source
                cover = album.cover
                if (
                    (ctx.match_source == MatchSource.EMBEDDED and cover.has_embedded)
                    or (ctx.match_source == MatchSource.FOLDER and cover.has_folder)
                    or (
                        ctx.match_source == MatchSource.BOTH
                        and (cover.has_embedded or cover.has_folder)
                    )
                ):
                    albums_with_deletable_context += 1

        if albums_with_deletable_context > 0:
            self.multi_remove_from_source_btn.setVisible(True)
            self.multi_remove_from_source_btn.setEnabled(True)
            self.multi_remove_from_source_btn.setToolTip(
                tr("Delete covers from their matched source ({n} albums with context)").format(
                    n=albums_with_deletable_context
                )
            )
            # Hide the generic remove button and checkboxes to avoid UX confusion
            self.multi_remove_btn.setVisible(False)
            self.multi_remove_embedded_cb.setVisible(False)
            self.multi_remove_folder_cb.setVisible(False)
        else:
            self.multi_remove_from_source_btn.setVisible(False)
            # Show the generic remove button and checkboxes
            self.multi_remove_btn.setVisible(True)
            self.multi_remove_embedded_cb.setVisible(True)
            self.multi_remove_folder_cb.setVisible(True)

        self.stack.setCurrentIndex(0)  # Show multi-selection view

    def _on_embedded_cover_clicked(self, event):
        """Show the embedded cover in a larger dialog when clicked."""
        if not self.current_album or not self.current_album.cover.has_embedded:
            return

        if not self.current_album.sample_file:
            return

        embedded_data = extract_embedded_cover(self.current_album.sample_file)
        if not embedded_data:
            return

        full_pixmap = QPixmap()
        if not full_pixmap.loadFromData(embedded_data):
            return

        self._show_cover_dialog(full_pixmap, tr("Audio tags"))

    def _on_folder_cover_clicked(self, event):
        """Show the folder cover in a larger dialog when clicked."""
        if not self.current_album:
            return

        cover_path = None
        if self.current_album.cover.folder_path and self.current_album.cover.folder_path.exists():
            cover_path = self.current_album.cover.folder_path

        if not cover_path:
            return

        # Load the full-size image
        full_pixmap = QPixmap(str(cover_path))
        if full_pixmap.isNull():
            return

        self._show_cover_dialog(full_pixmap, tr("File"))

    def _show_cover_dialog(self, pixmap: QPixmap, source_label: str):
        """Show a cover in an enlarged dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle(
            tr("Cover ({source}) - {name}").format(
                source=source_label, name=self.current_album.display_name
            )
        )
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scale the image to a reasonable size while keeping aspect ratio
        max_size = 600
        if pixmap.width() > max_size or pixmap.height() > max_size:
            scaled_pixmap = pixmap.scaled(
                max_size,
                max_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            scaled_pixmap = pixmap

        cover_label = QLabel()
        cover_label.setPixmap(scaled_pixmap)
        cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(cover_label)

        # Show image dimensions and source
        dimensions = tr("{width} x {height} pixels").format(
            width=pixmap.width(), height=pixmap.height()
        )
        info_label = QLabel(f"{source_label} • {dimensions}")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet("padding: 8px; color: #888;")
        layout.addWidget(info_label)

        dialog.adjustSize()
        dialog.exec()

    def _open_search(self):
        """Open the cover search dialog."""
        if not self.current_album:
            return

        search_panel = SearchPanel(self.current_album, self.config, self)
        search_panel.cover_selected.connect(self._on_cover_selected)
        search_panel.exec()

    def _on_cover_selected(self, cover_data: bytes, result: SearchResult):
        """Handle cover selection from search - show comparison dialog."""
        if not self.current_album:
            return

        # Get current cover path (if exists)
        current_cover_path = None
        if self.current_album.cover.folder_path and self.current_album.cover.folder_path.exists():
            current_cover_path = self.current_album.cover.folder_path

        # Get embedded cover (if exists)
        embedded_cover_data = None
        if self.current_album.cover.has_embedded and self.current_album.sample_file:
            embedded_cover_data = extract_embedded_cover(self.current_album.sample_file)

        # Evaluate save strategy
        decision = self.save_strategy.evaluate(self.current_album)

        # Note: We no longer block here if decision is invalid.
        # The comparison dialog allows the user to modify options on the fly.

        # Show comparison dialog
        dialog = CoverComparisonDialog(
            self.current_album,
            current_cover_path,
            cover_data,
            result,
            decision,
            self,
            embedded_cover_data=embedded_cover_data,
        )
        dialog.cover_approved.connect(self._on_cover_approved)
        dialog.exec()

    def _on_cover_approved(
        self, cover_data: bytes, result: SearchResult, decision: CoverSaveDecision
    ):
        """Handle cover approval from comparison dialog."""
        self._apply_cover(cover_data, result, decision)

    def _apply_cover(self, cover_data: bytes, result: SearchResult, decision: CoverSaveDecision):
        """Apply cover using the provided save decision."""
        if not self.current_album:
            return

        try:
            mime_type = detect_image_mime_type(cover_data)
            extension = get_extension_for_mime(mime_type)
            filename = f"{decision.external_filename}{extension}"

            # Get image dimensions once (used for both folder and embedded)
            dimensions = _get_image_dimensions_from_bytes(cover_data)
            cover_size = len(cover_data)

            # Save to folder if enabled
            if decision.save_external_file:
                # For single-file entries, save to parent folder
                target_folder = (
                    self.current_album.path.parent
                    if self.current_album.path.is_file()
                    else self.current_album.path
                )
                self.embedder.save_cover_to_folder(cover_data, target_folder, filename)
                self.current_album.cover.has_folder = True
                self.current_album.cover.folder_file = filename
                self.current_album.cover.folder_path = target_folder / filename
                self.current_album.cover.folder_dimensions = dimensions
                self.current_album.cover.folder_size_bytes = cover_size
                self.current_album.cover.folder_mime_type = mime_type

            # Embed in tags if enabled
            if decision.embed_in_tags:
                embed_success = False
                # Handle single file albums vs folder albums
                if self.current_album.path.is_file():
                    # Single file album - embed directly in the file
                    embed_success = self.embedder.embed_cover_in_file(
                        self.current_album.path, cover_data, mime_type
                    )
                else:
                    # Folder album - embed in all files
                    embed_count = self.embedder.embed_cover_in_folder(
                        cover_data, self.current_album.path, mime_type
                    )
                    embed_success = embed_count > 0

                if embed_success:
                    self.current_album.cover.has_embedded = True
                    self.current_album.cover.embedded_dimensions = dimensions
                    self.current_album.cover.embedded_size_bytes = cover_size
                    self.current_album.cover.embedded_mime_type = mime_type

            # Update covers_differ flag
            self.current_album.cover.covers_differ = (
                self.current_album.cover.has_embedded
                and self.current_album.cover.has_folder
                and self.current_album.cover.embedded_dimensions
                != self.current_album.cover.folder_dimensions
            )

            # Update display and emit signal
            self._update_display()
            self.cover_applied.emit(self.current_album)

            # Build success message
            actions = []
            if decision.save_external_file:
                actions.append(tr("file {filename}").format(filename=filename))
            if decision.embed_in_tags:
                actions.append(tr("audio tags"))
            action_str = tr(" and ").join(actions)

            ToastManager.get_instance().show_success(
                tr("Cover saved for {name} ({actions})").format(
                    name=self.current_album.display_name, actions=action_str
                )
            )

        except Exception as e:
            logger.exception("Error applying cover")
            QMessageBox.critical(
                self, tr("Error"), tr("Error applying cover:\n{error}").format(error=e)
            )

    def _import_image(self):
        """Import a local image as cover."""
        if not self.current_album:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select an image"),
            str(Path.home()),
            tr("Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp)"),
        )

        if not file_path:
            return

        try:
            with Path(file_path).open("rb") as f:
                cover_data = f.read()

            # Create a pseudo SearchResult for the imported image
            result = SearchResult(
                provider=tr("Local import"),
                artist=self.current_album.artist or "",
                album=self.current_album.album or "",
                score=100,
                has_cover_art=True,
            )

            # Get current cover path (if exists)
            current_cover_path = None
            if (
                self.current_album.cover.folder_path
                and self.current_album.cover.folder_path.exists()
            ):
                current_cover_path = self.current_album.cover.folder_path

            # Get embedded cover (if exists)
            embedded_cover_data = None
            if self.current_album.cover.has_embedded and self.current_album.sample_file:
                embedded_cover_data = extract_embedded_cover(self.current_album.sample_file)

            # Evaluate save strategy
            decision = self.save_strategy.evaluate(self.current_album)

            # Note: We no longer block here if decision is invalid.
            # The comparison dialog allows the user to modify options on the fly.

            # Show comparison dialog
            dialog = CoverComparisonDialog(
                self.current_album,
                current_cover_path,
                cover_data,
                result,
                decision,
                self,
                embedded_cover_data=embedded_cover_data,
            )
            dialog.cover_approved.connect(self._on_cover_approved)
            dialog.exec()

        except Exception as e:
            logger.exception("Error importing image")
            QMessageBox.critical(
                self, tr("Error"), tr("Error during import:\n{error}").format(error=e)
            )

    def _update_remove_button_state(self):
        """Update remove button state based on checkbox selections."""
        if not self.current_album:
            self.remove_btn.setEnabled(False)
            return

        # At least one checkbox must be checked AND corresponding cover must exist
        can_remove_embedded = (
            self.remove_embedded_cb.isChecked() and self.current_album.cover.has_embedded
        )
        can_remove_folder = (
            self.remove_folder_cb.isChecked() and self.current_album.cover.has_folder
        )

        self.remove_btn.setEnabled(can_remove_embedded or can_remove_folder)

    def _update_context_actions(self):
        """Update visibility and state of context-aware action buttons.

        The "Delete from source" button is only shown when:
        1. Single album is selected
        2. Has filter context (hash filter is active)
        3. Album has cover at the matched source
        """
        logger.debug(
            f"_update_context_actions: album={self.current_album.display_name if self.current_album else None}, context={self.current_context}"
        )
        if not self.current_album or not self.current_context:
            self._hide_source_button()
            return

        match_source = self.current_context.match_source
        if match_source is None:
            self._hide_source_button()
            return

        # Check if album still has cover at the matched source
        can_delete = False
        cover = self.current_album.cover

        button_text = ""
        tooltip = ""

        if match_source == MatchSource.EMBEDDED:
            can_delete = cover.has_embedded
            button_text = tr("Delete from audio tags")
            tooltip = tr("Delete cover from audio tags (matched source)")
        elif match_source == MatchSource.FOLDER:
            can_delete = cover.has_folder
            button_text = tr("Delete from file")
            tooltip = tr("Delete cover from external file (matched source)")
        elif match_source == MatchSource.BOTH:
            can_delete = cover.has_embedded or cover.has_folder
            button_text = tr("Delete from both sources")
            tooltip = tr("Delete cover from audio tags and file (both matched)")
        else:
            logger.warning(f"Unknown match_source: {match_source}")
            self._hide_source_button()
            return

        logger.debug(f"Showing source button: enabled={can_delete}, text='{button_text}'")
        self.remove_from_source_btn.setText(button_text)
        self.remove_from_source_btn.setToolTip(tooltip)
        self.remove_from_source_btn.setEnabled(can_delete)
        # Show button by restoring its maximum height
        self.remove_from_source_btn.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        self.remove_from_source_btn.setVisible(True)

        # Hide the generic remove button and checkboxes to avoid UX confusion
        # The context-aware button already specifies exactly what will be deleted
        self.remove_btn.setVisible(False)
        self.remove_embedded_cb.setVisible(False)
        self.remove_folder_cb.setVisible(False)

        # Force layout recalculation
        parent = self.remove_from_source_btn.parentWidget()
        if parent and parent.layout():
            parent.layout().invalidate()
            parent.layout().activate()
            parent.updateGeometry()

    def _hide_source_button(self):
        """Hide the 'Delete from source' button and restore generic remove UI."""
        # Hide by setting maximum height to 0 (more reliable than setVisible)
        if self.remove_from_source_btn.maximumHeight() > 0:
            self.remove_from_source_btn.setMaximumHeight(0)

        # Restore the generic remove button and checkboxes
        self.remove_btn.setVisible(True)
        self.remove_embedded_cb.setVisible(True)
        self.remove_folder_cb.setVisible(True)

        # Force layout recalculation to reclaim space
        parent = self.remove_from_source_btn.parentWidget()
        if parent and parent.layout():
            parent.layout().invalidate()
            parent.layout().activate()
            parent.updateGeometry()

    def _remove_from_source(self):
        """Remove cover based on filter match source (context-aware deletion).

        This method deletes covers only from the location(s) that matched
        the hash filter, as recorded in the filter context.
        """
        if not self.current_album or not self.current_context:
            return

        match_source = self.current_context.match_source
        if match_source is None:
            return

        # Determine what to delete based on match source
        remove_embedded = match_source in (MatchSource.EMBEDDED, MatchSource.BOTH)
        remove_folder = match_source in (MatchSource.FOLDER, MatchSource.BOTH)

        # Build confirmation message
        targets = []
        if remove_embedded:
            targets.append(tr("audio tags"))
        if remove_folder:
            targets.append(tr("external file"))
        targets_str = tr(" and ").join(targets)

        message = tr(
            "This album matched the filter via {targets}.\n\nDelete cover from {targets}?"
        ).format(targets=targets_str)

        reply = QMessageBox.question(
            self,
            tr("Delete from source"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform deletion
        try:
            album = self.current_album

            # Remove folder cover if targeted
            if remove_folder and album.cover.folder_path and album.cover.folder_path.exists():
                album.cover.folder_path.unlink()
                album.cover.has_folder = False
                album.cover.folder_file = None
                album.cover.folder_path = None
                album.cover.folder_hash = None
                album.cover.folder_dimensions = None
                album.cover.folder_size_bytes = None
                album.cover.folder_mime_type = None

            # Remove embedded covers if targeted
            if remove_embedded and album.cover.has_embedded:
                removal_success = False
                if album.path.is_file():
                    removal_success = self.embedder.remove_embedded_cover(album.path)
                elif album.track_count == 1 and album.sample_file and album.sample_file.exists():
                    removal_success = self.embedder.remove_embedded_cover(album.sample_file)
                elif album.path.is_dir():
                    all_success = True
                    for track in album.path.iterdir():
                        if (
                            track.is_file()
                            and track.suffix.lower()
                            in {".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".opus"}
                            and not self.embedder.remove_embedded_cover(track)
                        ):
                            all_success = False
                    removal_success = all_success

                if removal_success:
                    album.cover.has_embedded = False
                    album.cover.embedded_hash = None
                    album.cover.embedded_dimensions = None
                    album.cover.embedded_size_bytes = None
                    album.cover.embedded_mime_type = None

            # Update state
            album.cover.covers_differ = False
            self.cover_applied.emit(album)
            self._update_display()

            ToastManager.get_instance().show_success(
                tr("Cover deleted from {targets}").format(targets=targets_str)
            )

        except Exception as e:
            logger.exception(f"Error removing cover from source: {e}")
            QMessageBox.critical(
                self, tr("Error"), tr("Error deleting cover:\n{error}").format(error=str(e))
            )

    def _remove_from_source_multi(self):
        """Remove covers from their respective matched sources for multiple albums.

        Each album's cover is deleted only from the location(s) that matched
        the hash filter for that specific album.
        """
        if not self.selected_contexts:
            return

        # Get albums that have context (keyed by path string)
        albums_with_context = [
            (album, self.selected_contexts[str(album.path)])
            for album in self.selected_albums
            if str(album.path) in self.selected_contexts and album.has_any_cover
        ]

        if not albums_with_context:
            return

        # Build confirmation message
        # Count how many albums for each source type
        embedded_count = sum(
            1
            for _, ctx in albums_with_context
            if ctx.match_source in (MatchSource.EMBEDDED, MatchSource.BOTH)
        )
        folder_count = sum(
            1
            for _, ctx in albums_with_context
            if ctx.match_source in (MatchSource.FOLDER, MatchSource.BOTH)
        )

        details = []
        if embedded_count > 0:
            details.append(tr("{n} from audio tags").format(n=embedded_count))
        if folder_count > 0:
            details.append(tr("{n} from external file").format(n=folder_count))

        message = tr(
            "Delete covers from their matched sources?\n\n"
            "{count} albums will be processed:\n{details}"
        ).format(count=len(albums_with_context), details="\n".join(f"  - {d}" for d in details))

        reply = QMessageBox.question(
            self,
            tr("Delete from source"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform deletion for each album based on its context
        errors = []
        success_count = 0

        for album, context in albums_with_context:
            try:
                match_source = context.match_source
                remove_embedded = match_source in (MatchSource.EMBEDDED, MatchSource.BOTH)
                remove_folder = match_source in (MatchSource.FOLDER, MatchSource.BOTH)

                # Remove folder cover if targeted
                if remove_folder and album.cover.folder_path and album.cover.folder_path.exists():
                    album.cover.folder_path.unlink()
                    album.cover.has_folder = False
                    album.cover.folder_file = None
                    album.cover.folder_path = None
                    album.cover.folder_hash = None
                    album.cover.folder_dimensions = None
                    album.cover.folder_size_bytes = None
                    album.cover.folder_mime_type = None

                # Remove embedded covers if targeted
                if remove_embedded and album.cover.has_embedded:
                    removal_success = False
                    if album.path.is_file():
                        removal_success = self.embedder.remove_embedded_cover(album.path)
                    elif (
                        album.track_count == 1 and album.sample_file and album.sample_file.exists()
                    ):
                        removal_success = self.embedder.remove_embedded_cover(album.sample_file)
                    elif album.path.is_dir():
                        all_success = True
                        for track in album.path.iterdir():
                            if (
                                track.is_file()
                                and track.suffix.lower()
                                in {".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".opus"}
                                and not self.embedder.remove_embedded_cover(track)
                            ):
                                all_success = False
                        removal_success = all_success

                    if removal_success:
                        album.cover.has_embedded = False
                        album.cover.embedded_hash = None
                        album.cover.embedded_dimensions = None
                        album.cover.embedded_size_bytes = None
                        album.cover.embedded_mime_type = None

                album.cover.covers_differ = False
                self.cover_applied.emit(album)
                success_count += 1

            except Exception as e:
                logger.exception(f"Error removing cover from {album.display_name}")
                errors.append(f"{album.display_name}: {e}")

        # Update display
        self._update_display()

        # Show result
        if errors:
            QMessageBox.warning(
                self,
                tr("Errors"),
                tr("Deleted covers from {success} albums.\n\nErrors:\n{errors}").format(
                    success=success_count, errors="\n".join(errors)
                ),
            )
        else:
            ToastManager.get_instance().show_success(
                tr("Covers deleted from {count} albums").format(count=success_count)
            )

    def _remove_cover(self):
        """Remove the cover from selected albums (selective based on checkboxes)."""
        albums_to_process = (
            self.selected_albums if len(self.selected_albums) > 1 else [self.current_album]
        )
        albums_to_process = [a for a in albums_to_process if a and a.has_any_cover]

        if not albums_to_process:
            return

        # Get deletion options from the correct checkboxes based on view
        is_multi = len(self.selected_albums) > 1
        if is_multi:
            remove_embedded = self.multi_remove_embedded_cb.isChecked()
            remove_folder = self.multi_remove_folder_cb.isChecked()
        else:
            remove_embedded = self.remove_embedded_cb.isChecked()
            remove_folder = self.remove_folder_cb.isChecked()

        if not remove_embedded and not remove_folder:
            return

        # Build confirmation message with details
        targets = []
        if remove_embedded:
            targets.append(tr("audio tags"))
        if remove_folder:
            targets.append(tr("external file"))
        targets_str = tr(" and ").join(targets)

        if len(albums_to_process) == 1:
            message = tr("Remove cover ({targets}) from {name}?").format(
                targets=targets_str, name=albums_to_process[0].display_name
            )
        else:
            message = tr("Remove covers ({targets}) from {count} albums?").format(
                targets=targets_str, count=len(albums_to_process)
            )

        reply = QMessageBox.question(
            self,
            tr("Remove cover"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        errors = []
        for album in albums_to_process:
            try:
                # Remove folder cover if selected
                if remove_folder and album.cover.folder_path and album.cover.folder_path.exists():
                    album.cover.folder_path.unlink()
                    album.cover.has_folder = False
                    album.cover.folder_file = None
                    album.cover.folder_path = None
                    album.cover.folder_hash = None
                    album.cover.folder_dimensions = None
                    album.cover.folder_size_bytes = None
                    album.cover.folder_mime_type = None

                # Remove embedded covers if selected
                if remove_embedded and album.cover.has_embedded:
                    # Handle different album types:
                    # 1. Single file (album.path is the file itself)
                    # 2. Single file in folder (album.track_count == 1)
                    # 3. Multi-file album (iterate folder)
                    removal_attempted = False
                    removal_success = False
                    if album.path.is_file():
                        # album.path is the audio file itself
                        removal_attempted = True
                        removal_success = self.embedder.remove_embedded_cover(album.path)
                    elif (
                        album.track_count == 1 and album.sample_file and album.sample_file.exists()
                    ):
                        # Single file album with folder structure
                        removal_attempted = True
                        removal_success = self.embedder.remove_embedded_cover(album.sample_file)
                    elif album.path.is_dir():
                        # Multi-file album - iterate over folder
                        removal_attempted = True
                        all_success = True
                        for track in album.path.iterdir():
                            if (
                                track.is_file()
                                and track.suffix.lower()
                                in {".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".opus"}
                                and not self.embedder.remove_embedded_cover(track)
                            ):
                                all_success = False
                        removal_success = all_success
                    # Only update state if removal was attempted and at least partially successful
                    if removal_attempted and removal_success:
                        album.cover.has_embedded = False
                        album.cover.embedded_hash = None
                        album.cover.embedded_dimensions = None
                        album.cover.embedded_size_bytes = None
                        album.cover.embedded_mime_type = None

                # Update covers_differ flag
                album.cover.covers_differ = False

                self.cover_applied.emit(album)

            except Exception as e:
                logger.exception(f"Error removing cover from {album.display_name}")
                errors.append(f"{album.display_name}: {e}")

        self._update_display()

        if errors:
            QMessageBox.warning(
                self, tr("Errors"), tr("Errors during removal:\n") + "\n".join(errors)
            )

    def _find_identical_covers(self):
        """Find albums with identical cover images."""
        if not self.current_album:
            return

        cover = self.current_album.cover
        has_embedded = cover.has_embedded and self.current_album.sample_file
        has_folder = cover.folder_path and cover.folder_path.exists()

        if not has_embedded and not has_folder:
            return

        # Import hash utilities
        from ..utils.cover_hash import compute_embedded_hash, compute_folder_hash

        # If both covers exist, show menu to choose
        if has_embedded and has_folder:
            menu = QMenu(self)
            embedded_action = menu.addAction(tr("Search by audio tags cover"))
            folder_action = menu.addAction(tr("Search by file cover"))

            action = menu.exec(
                self.find_identical_btn.mapToGlobal(self.find_identical_btn.rect().bottomLeft())
            )

            if action == embedded_action:
                # Use cached hash if available, otherwise compute
                if cover.embedded_hash:
                    self.identical_covers_requested.emit(cover.embedded_hash)
                else:
                    cover_hash = compute_embedded_hash(self.current_album.sample_file)
                    if cover_hash:
                        cover.embedded_hash = cover_hash
                        self.identical_covers_requested.emit(cover_hash)
            elif action == folder_action:
                # Use cached hash if available, otherwise compute
                if cover.folder_hash:
                    self.identical_covers_requested.emit(cover.folder_hash)
                else:
                    cover_hash = compute_folder_hash(cover.folder_path)
                    if cover_hash:
                        cover.folder_hash = cover_hash
                        self.identical_covers_requested.emit(cover_hash)
        elif has_embedded:
            # Use cached hash if available, otherwise compute
            if cover.embedded_hash:
                self.identical_covers_requested.emit(cover.embedded_hash)
            else:
                cover_hash = compute_embedded_hash(self.current_album.sample_file)
                if cover_hash:
                    cover.embedded_hash = cover_hash
                    self.identical_covers_requested.emit(cover_hash)
        elif has_folder:
            # Use cached hash if available, otherwise compute
            if cover.folder_hash:
                self.identical_covers_requested.emit(cover.folder_hash)
            else:
                cover_hash = compute_folder_hash(cover.folder_path)
                if cover_hash:
                    cover.folder_hash = cover_hash
                    self.identical_covers_requested.emit(cover_hash)

    def _sync_embedded_to_file(self):
        """Copy embedded cover to external file."""
        if not self.current_album or not self.current_album.sample_file:
            return

        try:
            # Extract embedded cover
            embedded_data = extract_embedded_cover(self.current_album.sample_file)
            if not embedded_data:
                QMessageBox.warning(
                    self, tr("Error"), tr("Unable to extract cover from audio tags.")
                )
                return

            # Determine filename
            mime_type = detect_image_mime_type(embedded_data)
            extension = get_extension_for_mime(mime_type)
            filename = f"cover{extension}"

            # For single-file entries, save to parent folder
            target_folder = (
                self.current_album.path.parent
                if self.current_album.path.is_file()
                else self.current_album.path
            )

            # Check if this is a shared folder - warn but allow manual sync
            if self.current_album.is_shared_folder:
                reply = QMessageBox.warning(
                    self,
                    tr("Warning"),
                    tr(
                        "This file is in a shared folder with other unrelated files.\n"
                        "Saving an external cover file may affect other files.\n\n"
                        "Continue anyway?"
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Save to folder
            self.embedder.save_cover_to_folder(embedded_data, target_folder, filename)

            # Update album info
            self.current_album.cover.has_folder = True
            self.current_album.cover.folder_file = filename
            self.current_album.cover.folder_path = target_folder / filename
            self.current_album.cover.covers_differ = False

            self._update_display()
            self.cover_applied.emit(self.current_album)

            ToastManager.get_instance().show_success(
                tr("Cover copied to {filename}").format(filename=filename)
            )

        except Exception as e:
            logger.exception("Error syncing embedded to file")
            QMessageBox.critical(
                self, tr("Error"), tr("Error during synchronization:\n{error}").format(error=e)
            )

    def _sync_file_to_embedded(self):
        """Copy external file cover to embedded tags."""
        if not self.current_album:
            return

        if (
            not self.current_album.cover.folder_path
            or not self.current_album.cover.folder_path.exists()
        ):
            QMessageBox.warning(self, tr("Error"), tr("No external cover file found."))
            return

        try:
            # Read file cover
            with self.current_album.cover.folder_path.open("rb") as f:
                cover_data = f.read()

            mime_type = detect_image_mime_type(cover_data)

            # Embed in audio files (handle single file vs folder)
            embed_success = False
            if self.current_album.path.is_file():
                embed_success = self.embedder.embed_cover_in_file(
                    self.current_album.path, cover_data, mime_type
                )
            else:
                embed_count = self.embedder.embed_cover_in_folder(
                    cover_data, self.current_album.path, mime_type
                )
                embed_success = embed_count > 0

            if not embed_success:
                raise RuntimeError(tr("No files were updated"))

            # Update album info
            self.current_album.cover.has_embedded = True
            self.current_album.cover.covers_differ = False

            self._update_display()
            self.cover_applied.emit(self.current_album)

            ToastManager.get_instance().show_success(tr("Cover copied to audio tags."))

        except Exception as e:
            logger.exception("Error syncing file to embedded")
            QMessageBox.critical(
                self, tr("Error"), tr("Error during synchronization:\n{error}").format(error=e)
            )

    def _sync_to_largest(self):
        """Sync to the largest cover (by pixel count)."""
        if not self.current_album:
            return

        cover = self.current_album.cover
        embedded_dimensions = cover.embedded_dimensions
        folder_dimensions = cover.folder_dimensions

        # Calculate pixel counts
        embedded_pixels = 0
        folder_pixels = 0

        if embedded_dimensions:
            embedded_pixels = embedded_dimensions[0] * embedded_dimensions[1]

        if folder_dimensions:
            folder_pixels = folder_dimensions[0] * folder_dimensions[1]

        # Determine which is larger
        if embedded_pixels > 0 and folder_pixels > 0:
            if embedded_pixels > folder_pixels:
                # Embedded is larger - copy to file
                logger.info(
                    f"Embedded cover ({embedded_dimensions[0]}x{embedded_dimensions[1]}) is larger "
                    f"than folder cover ({folder_dimensions[0]}x{folder_dimensions[1]}), syncing to file"
                )
                self._sync_embedded_to_file()
            elif folder_pixels > embedded_pixels:
                # Folder is larger - copy to tags
                logger.info(
                    f"Folder cover ({folder_dimensions[0]}x{folder_dimensions[1]}) is larger "
                    f"than embedded cover ({embedded_dimensions[0]}x{embedded_dimensions[1]}), syncing to tags"
                )
                self._sync_file_to_embedded()
            else:
                # Equal size - ask user to choose
                ToastManager.get_instance().show_info(
                    tr(
                        "Both covers have the same size ({w}x{h}). "
                        "Please manually choose which one to keep."
                    ).format(w=embedded_dimensions[0], h=embedded_dimensions[1])
                )
        elif embedded_pixels > 0:
            # Only embedded exists (shouldn't happen if covers_differ, but handle it)
            ToastManager.get_instance().show_info(
                tr(
                    "Only the audio tags cover is available. "
                    "Use 'Tags -> External file' to copy it."
                )
            )
        elif folder_pixels > 0:
            # Only folder exists (shouldn't happen if covers_differ, but handle it)
            ToastManager.get_instance().show_info(
                tr(
                    "Only the external file cover is available. "
                    "Use 'External file -> Tags' to copy it."
                )
            )
        else:
            # Can't determine dimensions for either
            ToastManager.get_instance().show_info(
                tr(
                    "Unable to determine cover dimensions. "
                    "Please manually choose which one to keep."
                )
            )

    def _open_comparison_dialog(self):
        """Open the cover comparison zoom dialog."""
        if not self.current_album:
            return

        # Check that both covers exist
        has_embedded = self.current_album.cover.has_embedded and self.current_album.sample_file
        has_folder = (
            self.current_album.cover.folder_path and self.current_album.cover.folder_path.exists()
        )

        if not (has_embedded and has_folder):
            ToastManager.get_instance().show_info(
                tr("Both covers (audio tags and external file) must be present to use comparison.")
            )
            return

        # Extract embedded cover data
        embedded_data = extract_embedded_cover(self.current_album.sample_file)
        if not embedded_data:
            QMessageBox.warning(self, tr("Error"), tr("Unable to extract cover from audio tags."))
            return

        # Get embedded MIME type
        embedded_mime = self.current_album.cover.embedded_mime_type

        # Open the zoom dialog
        dialog = CoverZoomDialog(
            album_name=self.current_album.display_name,
            embedded_data=embedded_data,
            folder_path=self.current_album.cover.folder_path,
            embedded_mime=embedded_mime,
            parent=self,
        )
        dialog.exec()

    def _disconnect_fetch_worker(self):
        """Safely disconnect signals from fetch worker."""
        if self.fetch_worker:
            with contextlib.suppress(RuntimeError):
                self.fetch_worker.progress.disconnect(self._on_batch_progress)
            with contextlib.suppress(RuntimeError):
                self.fetch_worker.album_done.disconnect(self._on_album_done)
            with contextlib.suppress(RuntimeError):
                self.fetch_worker.finished.disconnect(self._on_batch_finished)

    def _start_multi_fetch(self):
        """Start batch fetch for albums in the current multi-selection."""
        # Filter to albums without covers
        albums_to_fetch = [a for a in self.selected_albums if not a.has_any_cover]
        if albums_to_fetch:
            self.start_batch_fetch(albums_to_fetch)

    def start_batch_fetch(self, albums: list[AlbumInfo]):
        """Start batch fetching covers for multiple albums."""
        if self.fetch_worker and self.fetch_worker.isRunning():
            return

        # Disconnect previous worker signals to prevent memory leaks
        self._disconnect_fetch_worker()

        # Show progress in appropriate view
        is_multi = len(self.selected_albums) > 1
        if is_multi:
            self.multi_batch_group.setVisible(True)
            self.multi_batch_progress.setRange(0, len(albums))
            self.multi_batch_progress.setValue(0)
            self.multi_batch_label.setText(f"0/{len(albums)}")
        else:
            self.batch_group.setVisible(True)
            self.batch_progress.setRange(0, len(albums))
            self.batch_progress.setValue(0)
            self.batch_label.setText(f"0/{len(albums)}")

        self.fetch_worker = FetchWorker(albums, self.config)
        self.fetch_worker.progress.connect(self._on_batch_progress)
        self.fetch_worker.album_done.connect(self._on_album_done)
        self.fetch_worker.finished.connect(self._on_batch_finished)
        self.fetch_worker.start()

    def _on_batch_progress(self, current: int, total: int, message: str):
        """Handle batch progress update."""
        # Update both progress bars (one will be visible depending on view)
        self.batch_progress.setValue(current)
        self.batch_label.setText(f"{current}/{total}: {message}")
        self.multi_batch_progress.setValue(current)
        self.multi_batch_label.setText(f"{current}/{total}: {message}")

    def _on_album_done(self, album: AlbumInfo, success: bool, message: str, cover_update: dict):
        """Handle album processing completion (runs in main thread)."""
        if success and cover_update:
            # Apply cover updates in main thread for thread safety
            album.cover.has_folder = cover_update.get("has_folder", False)
            album.cover.folder_file = cover_update.get("folder_file")
            if cover_update.get("folder_path"):
                album.cover.folder_path = Path(cover_update["folder_path"])
            if cover_update.get("has_embedded"):
                album.cover.has_embedded = True
            self.cover_applied.emit(album)

    def _on_batch_finished(self):
        """Handle batch processing completion."""
        self.batch_group.setVisible(False)
        self.multi_batch_group.setVisible(False)

        # Update multi-selection stats if in multi view
        if len(self.selected_albums) > 1:
            self._show_multi_selection_state()

        ToastManager.get_instance().show_success(tr("Automatic processing is complete."))

    def _cancel_batch(self):
        """Cancel batch processing."""
        if self.fetch_worker and self.fetch_worker.isRunning():
            self.fetch_worker.cancel()

    def _update_acoustid_display(self):
        """Update the AcoustID display and button state."""
        if not self.current_album:
            self.acoustid_label.setText("-")
            self.fingerprint_btn.setEnabled(False)
            return

        if self.current_album.acoustid:
            # Truncate long AcoustIDs for display
            acoustid = self.current_album.acoustid
            display_text = acoustid[:27] + "..." if len(acoustid) > 30 else acoustid
            self.acoustid_label.setText(display_text)
            self.acoustid_label.setToolTip(acoustid)
            # Already have an AcoustID - disable identify button
            self.fingerprint_btn.setEnabled(False)
            self.fingerprint_btn.setToolTip(tr("AcoustID already present"))
        else:
            self.acoustid_label.setText(tr("Fingerprint not calculated"))
            self.acoustid_label.setToolTip("")
            # Enable identify button if we have a sample file
            has_sample = self.current_album.sample_file is not None
            self.fingerprint_btn.setEnabled(has_sample)
            self.fingerprint_btn.setToolTip(
                tr("Identify the album via audio fingerprint")
                if has_sample
                else tr("No audio file available")
            )

    def _launch_fingerprint(self):
        """Launch audio fingerprint identification via SearchPanel."""
        if not self.current_album:
            return

        # Open search panel with auto-fingerprint enabled
        # This reuses the same implementation as the context menu
        search_panel = SearchPanel(self.current_album, self.config, self, auto_fingerprint=True)
        search_panel.cover_selected.connect(self._on_cover_selected)
        search_panel.exec()

    def closeEvent(self, event):
        """Handle close event - cleanup threads."""
        if self.fetch_worker and self.fetch_worker.isRunning():
            self.fetch_worker.cancel()
            self.fetch_worker.wait(2000)  # Wait max 2 seconds
            if self.fetch_worker.isRunning():
                self.fetch_worker.terminate()
                self.fetch_worker.wait(500)  # Wait for termination to complete

        # Disconnect signals to prevent memory leaks
        self._disconnect_fetch_worker()

        super().closeEvent(event)
