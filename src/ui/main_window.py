"""
Main window for TuneCover.
"""

import contextlib
import json
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core.embedder import extract_embedded_cover
from ..core.filter_context import FilterContext, FilterContextManager
from ..core.models import AlbumInfo, CoverInfo, CoverStatus, TrackInfo
from ..core.scan_cache import ScanCache
from ..core.scanner import (
    AUDIO_EXTENSIONS,
    COVER_EXTENSIONS,
    COVER_FILENAMES,
    MusicScanner,
    _get_image_dimensions_from_bytes,
)
from ..i18n import tr
from ..utils.cache import embedded_cover_cache, get_image_cache
from ..utils.config import Config
from ..utils.constants import APP_NAME, AUTHOR, VERSION
from ..utils.metadata import extract_musicbrainz_ids
from .album_detail import AlbumDetailPanel
from .dialogs import BatchDownloadDialog, StatisticsDialog
from .library_view import LibraryView
from .preferences import PreferencesDialog
from .widgets.filter_widgets import MimeTypeFilter, SizeRangeFilter
from .widgets.toast_manager import ToastManager

logger = logging.getLogger(__name__)

# Debounce delay for search input (milliseconds)
SEARCH_DEBOUNCE_MS = 300


def _create_album_from_file(filepath: Path) -> AlbumInfo | None:
    """Create an AlbumInfo from a single audio file."""
    from mutagen import File as MutagenFile

    try:
        audio = MutagenFile(filepath, easy=True)
        if audio is None:
            return None

        metadata = {
            "artist": None,
            "album": None,
            "year": None,
            "musicbrainz_albumid": None,
            "musicbrainz_releasegroupid": None,
            "musicbrainz_artistid": None,
        }

        tags = None
        if hasattr(audio, "tags") and audio.tags:
            tags = audio.tags

            # Artist
            for key in ["albumartist", "artist", "performer"]:
                if tags.get(key):
                    metadata["artist"] = tags[key][0]
                    break

            # Album
            if tags.get("album"):
                metadata["album"] = tags["album"][0]

            # Year
            for key in ["date", "year", "originaldate"]:
                if tags.get(key):
                    year_str = tags[key][0]
                    if year_str:
                        metadata["year"] = year_str[:4]
                    break

        # MusicBrainz IDs - use shared extraction function
        mbids = extract_musicbrainz_ids(filepath, tags)
        metadata.update(mbids)

        # Check for embedded cover in this file
        has_embedded = False
        embedded_data = None
        embedded_dimensions = None
        embedded_size_bytes = None
        embedded_mime_type = None
        try:
            embedded_data = extract_embedded_cover(filepath)
            if embedded_data:
                has_embedded = True
                embedded_dimensions = _get_image_dimensions_from_bytes(embedded_data)
                embedded_size_bytes = len(embedded_data)
                # Detect MIME type from bytes
                if embedded_data[:8] == b"\x89PNG\r\n\x1a\n":
                    embedded_mime_type = "image/png"
                elif embedded_data[:2] == b"\xff\xd8":
                    embedded_mime_type = "image/jpeg"
                elif embedded_data[:4] == b"RIFF" and embedded_data[8:12] == b"WEBP":
                    embedded_mime_type = "image/webp"
        except OSError:
            pass

        # Check for folder cover in the parent directory
        has_folder = False
        folder_file = None
        folder_path = None
        folder_dimensions = None
        folder_size_bytes = None
        folder_mime_type = None
        folder_data = None
        parent_folder = filepath.parent
        try:
            for item in parent_folder.iterdir():
                if item.is_file():
                    stem = item.stem.lower()
                    suffix = item.suffix.lower()
                    if suffix in COVER_EXTENSIONS and (
                        stem in COVER_FILENAMES or any(name in stem for name in COVER_FILENAMES)
                    ):
                        has_folder = True
                        folder_file = item.name
                        folder_path = item
                        # Extract folder cover dimensions
                        try:
                            folder_data = item.read_bytes()
                            folder_dimensions = _get_image_dimensions_from_bytes(folder_data)
                            folder_size_bytes = len(folder_data)
                            # Detect MIME type from extension
                            mime_map = {
                                ".jpg": "image/jpeg",
                                ".jpeg": "image/jpeg",
                                ".png": "image/png",
                                ".webp": "image/webp",
                                ".gif": "image/gif",
                                ".bmp": "image/bmp",
                            }
                            folder_mime_type = mime_map.get(suffix, "image/jpeg")
                        except OSError:
                            pass
                        break
        except (PermissionError, OSError) as e:
            logger.debug(f"Error checking folder cover in {parent_folder}: {e}")

        # Determine if covers differ (when both exist)
        covers_differ = False
        if embedded_data and folder_data:
            covers_differ = embedded_data != folder_data

        cover_info = CoverInfo(
            has_embedded=has_embedded,
            has_folder=has_folder,
            folder_file=folder_file,
            folder_path=folder_path,
            covers_differ=covers_differ,
            embedded_dimensions=embedded_dimensions,
            folder_dimensions=folder_dimensions,
            embedded_size_bytes=embedded_size_bytes,
            folder_size_bytes=folder_size_bytes,
            embedded_mime_type=embedded_mime_type,
            folder_mime_type=folder_mime_type,
        )

        # Create TrackInfo for this file (required for AcoustID fingerprinting)
        track_info = TrackInfo(
            path=filepath,
            filename=filepath.name,
            format=filepath.suffix.lower(),
            has_embedded_cover=has_embedded,
            artist=metadata["artist"],
            album=metadata["album"],
            year=metadata["year"],
            musicbrainz_albumid=metadata["musicbrainz_albumid"],
            musicbrainz_releasegroupid=metadata["musicbrainz_releasegroupid"],
            musicbrainz_artistid=metadata["musicbrainz_artistid"],
        )

        # For single-file entries, use the file path itself as the unique key
        # This ensures each file has a distinct identity in the library view
        return AlbumInfo(
            path=filepath,  # Use file path as unique identifier for single files
            artist=metadata["artist"],
            album=metadata["album"],
            year=metadata["year"],
            track_count=1,
            tracks=[track_info],  # Include track for AcoustID fingerprinting
            cover=cover_info,
            sample_file=filepath,
            formats=[filepath.suffix.lower()],
            musicbrainz_albumid=metadata["musicbrainz_albumid"],
            musicbrainz_releasegroupid=metadata["musicbrainz_releasegroupid"],
            musicbrainz_artistid=metadata["musicbrainz_artistid"],
        )
    except OSError as e:
        logger.error(f"Error creating album from file {filepath}: {e}")
        return None


def _create_album_from_files(filepaths: list[Path]) -> AlbumInfo | None:
    """Create an AlbumInfo from multiple audio files in the same folder."""
    if not filepaths:
        return None

    from mutagen import File as MutagenFile

    folder = filepaths[0].parent
    formats = set()

    # Collect all formats
    for fp in filepaths:
        formats.add(fp.suffix.lower())

    # Get metadata from first file
    metadata = {
        "artist": None,
        "album": None,
        "year": None,
        "musicbrainz_albumid": None,
        "musicbrainz_releasegroupid": None,
        "musicbrainz_artistid": None,
    }

    sample_file = filepaths[0]
    try:
        audio = MutagenFile(sample_file, easy=True)
        if audio and hasattr(audio, "tags") and audio.tags:
            tags = audio.tags

            # Artist
            for key in ["albumartist", "artist", "performer"]:
                if tags.get(key):
                    metadata["artist"] = tags[key][0]
                    break

            # Album
            if tags.get("album"):
                metadata["album"] = tags["album"][0]

            # Year
            for key in ["date", "year", "originaldate"]:
                if tags.get(key):
                    year_str = tags[key][0]
                    if year_str:
                        metadata["year"] = year_str[:4]
                    break

        # MusicBrainz IDs
        mbids = extract_musicbrainz_ids(sample_file, audio.tags if audio else None)
        metadata.update(mbids)
    except OSError as e:
        logger.debug(f"Error reading metadata from {sample_file}: {e}")

    # Check for embedded cover (check first 3 files)
    has_embedded = False
    for fp in filepaths[:3]:
        try:
            embedded_data = extract_embedded_cover(fp)
            if embedded_data:
                has_embedded = True
                break
        except OSError:
            pass

    # Check for folder cover
    has_folder = False
    folder_file = None
    folder_path = None
    try:
        for item in folder.iterdir():
            if item.is_file():
                stem = item.stem.lower()
                suffix = item.suffix.lower()
                if suffix in COVER_EXTENSIONS and (
                    stem in COVER_FILENAMES or any(name in stem for name in COVER_FILENAMES)
                ):
                    has_folder = True
                    folder_file = item.name
                    folder_path = item
                    break
    except (PermissionError, OSError) as e:
        logger.debug(f"Error checking folder cover in {folder}: {e}")

    cover_info = CoverInfo(
        has_embedded=has_embedded,
        has_folder=has_folder,
        folder_file=folder_file,
        folder_path=folder_path,
    )

    # Create TrackInfo for each file (required for AcoustID fingerprinting)
    tracks = []
    for fp in filepaths:
        try:
            file_audio = MutagenFile(fp, easy=True)
            file_tags = file_audio.tags if file_audio and hasattr(file_audio, "tags") else {}

            file_artist = None
            for key in ["albumartist", "artist", "performer"]:
                if file_tags and file_tags.get(key):
                    file_artist = file_tags[key][0]
                    break

            file_album = file_tags.get("album", [None])[0] if file_tags else None
            file_title = file_tags.get("title", [None])[0] if file_tags else None
            file_year = None
            for key in ["date", "year", "originaldate"]:
                if file_tags and file_tags.get(key):
                    year_str = file_tags[key][0]
                    if year_str:
                        file_year = year_str[:4]
                    break

            file_mbids = extract_musicbrainz_ids(fp, file_tags)

            track_info = TrackInfo(
                path=fp,
                filename=fp.name,
                format=fp.suffix.lower(),
                has_embedded_cover=extract_embedded_cover(fp) is not None,
                artist=file_artist,
                album=file_album,
                title=file_title,
                year=file_year,
                musicbrainz_albumid=file_mbids.get("musicbrainz_albumid"),
                musicbrainz_releasegroupid=file_mbids.get("musicbrainz_releasegroupid"),
                musicbrainz_artistid=file_mbids.get("musicbrainz_artistid"),
            )
            tracks.append(track_info)
        except Exception as e:
            logger.debug(f"Error creating track info for {fp}: {e}")
            # Still add a basic track info even if metadata extraction fails
            tracks.append(
                TrackInfo(
                    path=fp,
                    filename=fp.name,
                    format=fp.suffix.lower(),
                )
            )

    return AlbumInfo(
        path=folder,
        artist=metadata["artist"],
        album=metadata["album"],
        year=metadata["year"],
        track_count=len(filepaths),
        tracks=tracks,
        cover=cover_info,
        sample_file=sample_file,
        formats=list(formats),
        musicbrainz_albumid=metadata["musicbrainz_albumid"],
        musicbrainz_releasegroupid=metadata["musicbrainz_releasegroupid"],
        musicbrainz_artistid=metadata["musicbrainz_artistid"],
    )


class ScanWorker(QThread):
    """Worker thread for scanning music library."""

    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(list, int, int)  # list of AlbumInfo, scanned_count, cached_count
    error = Signal(str)

    def __init__(
        self,
        path: Path,
        exclude_patterns: list[str],
        scan_cache: ScanCache | None = None,
    ):
        super().__init__()
        self.path = path
        self.exclude_patterns = exclude_patterns
        self.scan_cache = scan_cache
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the scan."""
        self._cancelled = True

    def run(self):
        try:
            # Track which folders were already cached before scanning
            cached_folders_before = set()
            if self.scan_cache is not None:
                cached_folders_before = self.scan_cache.get_cached_folders()

            scanner = MusicScanner(
                exclude_patterns=self.exclude_patterns,
                progress_callback=self._on_progress,
                cancelled_callback=lambda: self._cancelled,
            )
            albums = scanner.scan_library(self.path, scan_cache=self.scan_cache)

            # Count cached vs scanned based on which were in cache before scan
            scanned_count = 0
            cached_count = 0
            if self.scan_cache is not None:
                for album in albums:
                    folder_key = str(album.path.resolve())
                    if folder_key in cached_folders_before:
                        cached_count += 1
                    else:
                        scanned_count += 1
                # Save the cache after scan
                self.scan_cache.save()
            else:
                scanned_count = len(albums)

            if not self._cancelled:
                self.finished.emit(albums, scanned_count, cached_count)
        except Exception as e:
            if not self._cancelled:
                logger.exception("Scan error")
                self.error.emit(str(e))

    def _on_progress(self, current: int, total: int, message: str):
        if not self._cancelled:
            self.progress.emit(current, total, message)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.albums: list[AlbumInfo] = []
        self.filtered_albums: list[AlbumInfo] = []
        self.scan_worker: ScanWorker | None = None

        # Initialize scan cache for incremental scanning
        self.scan_cache = ScanCache()
        self.scan_cache.load()

        # Initialize image cache with config and clean up expired entries
        self._image_cache = get_image_cache(config)
        expired_count = self._image_cache.clear_expired()
        if expired_count > 0:
            logger.info(f"Cleared {expired_count} expired image cache entries at startup")

        # Configure embedded cover cache from config
        embedded_cache_mb = config.get("cache.embedded_cache_size_mb", 100)
        embedded_cover_cache.configure(max_memory_bytes=embedded_cache_mb * 1024 * 1024)

        # Flag to force full rescan (ignoring cache)
        self._force_full_scan = False

        # Hash filter for finding identical covers (temporary filter)
        self._hash_filter: str | None = None

        # Filter context manager: tracks WHERE each album matched the hash filter
        # (embedded, folder, or both) to enable context-aware actions like "delete from source"
        self.filter_context_manager = FilterContextManager()

        # Scanner for rescanning individual albums
        self._scanner = MusicScanner(exclude_patterns=config.exclude_patterns)

        # Debounce timer for search input
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_filters)

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._restore_geometry()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle(tr("TuneCover"))
        self.setMinimumSize(800, 600)

        # Enable drag and drop
        self.setAcceptDrops(True)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter for library view and detail panel
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter)

        # Left side: Library view
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 4, 8)

        # Filter bar
        filter_bar = self._create_filter_bar()
        left_layout.addLayout(filter_bar)

        # Library view
        self.library_view = LibraryView(config=self.config)
        self.library_view.album_selected.connect(self._on_album_selected)
        self.library_view.albums_selected.connect(self._on_albums_selected)
        self.library_view.find_identical_requested.connect(self._on_identical_covers_requested)
        self.library_view.acoustid_identify_requested.connect(self._on_acoustid_identify_requested)
        self.library_view.search_cover_requested.connect(self._on_search_cover_from_context)
        self.library_view.remove_cover_requested.connect(self._on_remove_cover_from_context)
        self.library_view.files_dropped.connect(self._on_files_dropped)
        self.library_view.group_as_album_requested.connect(self._on_group_as_album)
        self.library_view.ungroup_album_requested.connect(self._on_ungroup_album)
        self.library_view.add_to_group_requested.connect(self._on_add_to_group)
        left_layout.addWidget(self.library_view)

        # Register cache coherence callback: invalidate thumbnails when embedded covers change
        embedded_cover_cache.register_invalidation_callback(
            lambda path: self.library_view._thumbnail_loader.invalidate_cache(path)
        )

        self.splitter.addWidget(left_panel)

        # Connect splitter resize to library view grid recalculation
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        # Right side: Detail panel
        self.detail_panel = AlbumDetailPanel(self.config)
        self.detail_panel.cover_applied.connect(self._on_cover_applied)
        self.detail_panel.identical_covers_requested.connect(self._on_identical_covers_requested)
        self.detail_panel.ungroup_album_requested.connect(self._on_ungroup_album)
        self.splitter.addWidget(self.detail_panel)
        # Hide detail panel initially (shown when albums are loaded)
        self.detail_panel.setVisible(False)

        # Set splitter sizes (70% library, 30% detail)
        self.splitter.setSizes([700, 300])

        # Toast notification manager
        self.toast_manager = ToastManager.get_instance(self)

    def _create_filter_bar(self) -> QVBoxLayout:
        """Create the filter bar layout."""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(4)

        # First row: search, filter combo, dimension spinbox, sort
        row1 = QHBoxLayout()

        # Search box with debounced input
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("Search..."))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        row1.addWidget(self.search_box)

        # Filter combo
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(tr("All albums"), None)
        self.filter_combo.addItem(tr("Without cover"), CoverStatus.NONE)
        self.filter_combo.addItem(tr("Partial cover"), "partial")
        self.filter_combo.addItem(tr("With cover"), "has_cover")
        self.filter_combo.addItem(tr("Different images"), "covers_differ")
        self.filter_combo.addItem(tr("Small covers <"), "small_covers")
        self.filter_combo.addItem(tr("Covers to improve"), "needs_improvement")
        self.filter_combo.addItem(tr("By size"), "by_size")
        self.filter_combo.addItem(tr("By type"), "by_type")
        self.filter_combo.addItem(tr("Identical covers"), "identical_covers")
        self.filter_combo.addItem(tr("Without AcoustID"), "no_acoustid")
        self.filter_combo.addItem(tr("Single tracks"), "single_tracks")
        self.filter_combo.addItem(tr("Albums (multi-track)"), "albums")

        # Add tooltips for all filter options
        filter_tooltips = [
            tr("Show all albums in the library"),
            tr("Albums without any cover (embedded or external)"),
            tr("Albums with only embedded OR only external cover"),
            tr("Albums with at least one cover"),
            tr("Albums where embedded and external covers differ"),
            tr("Albums with covers smaller than the specified dimension"),
            tr("Albums with low-quality or small covers that could be improved"),
            tr("Filter albums by cover file size range"),
            tr("Filter albums by cover image format (JPEG, PNG, etc.)"),
            tr("Albums sharing the same cover image (grouped by hash)"),
            tr("Albums without audio fingerprint identifier"),
            tr("Individual audio files (single track, not in album folder)"),
            tr("Albums containing multiple tracks"),
        ]
        for i, tooltip in enumerate(filter_tooltips):
            self.filter_combo.setItemData(i, tooltip, Qt.ItemDataRole.ToolTipRole)

        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        row1.addWidget(self.filter_combo)

        # Clear filter button (visible when a filter is active)
        self.clear_filter_btn = QPushButton("✕")
        self.clear_filter_btn.setFixedSize(24, 24)
        self.clear_filter_btn.setToolTip(tr("Clear filter"))
        self.clear_filter_btn.clicked.connect(self._clear_all_filters)
        self.clear_filter_btn.setVisible(False)
        row1.addWidget(self.clear_filter_btn)

        # Dimension threshold spinbox (for small covers filter)
        self.dimension_spinbox = QSpinBox()
        self.dimension_spinbox.setRange(100, 2000)
        self.dimension_spinbox.setValue(500)
        self.dimension_spinbox.setSuffix(" px")
        self.dimension_spinbox.setToolTip(tr("Minimum dimension (width or height)"))
        self.dimension_spinbox.valueChanged.connect(self._apply_filters)
        self.dimension_spinbox.setVisible(False)  # Hidden by default
        row1.addWidget(self.dimension_spinbox)

        # Sort combo
        self.sort_combo = QComboBox()
        self.sort_combo.addItem(tr("Sort by: Artist"), "artist")
        self.sort_combo.addItem(tr("Sort by: Album"), "album")
        self.sort_combo.addItem(tr("Sort by: Year"), "year")
        self.sort_combo.addItem(tr("Sort by: Dimension"), "dimension")
        self.sort_combo.addItem(tr("Sort by: Path"), "path")
        self.sort_combo.currentIndexChanged.connect(self._apply_filters)
        row1.addWidget(self.sort_combo)

        main_layout.addLayout(row1)

        # Second row: advanced filters (size range, MIME type) - hidden by default
        row2 = QHBoxLayout()

        # Size range filter
        self.size_filter = SizeRangeFilter()
        self.size_filter.filter_changed.connect(self._apply_filters)
        self.size_filter.setVisible(False)
        row2.addWidget(self.size_filter)

        # MIME type filter
        self.mime_filter = MimeTypeFilter()
        self.mime_filter.filter_changed.connect(self._apply_filters)
        self.mime_filter.setVisible(False)
        row2.addWidget(self.mime_filter)

        # Clear hash filter button (for identical covers)
        self.clear_hash_filter_btn = QPushButton(tr("Clear filter"))
        self.clear_hash_filter_btn.setToolTip(tr("Clear identical covers filter"))
        self.clear_hash_filter_btn.clicked.connect(self._clear_hash_filter)
        self.clear_hash_filter_btn.setVisible(False)
        row2.addWidget(self.clear_hash_filter_btn)

        row2.addStretch()

        main_layout.addLayout(row2)

        return main_layout

    def _on_search_text_changed(self):
        """Handle search text change with debouncing."""
        self._search_timer.start(SEARCH_DEBOUNCE_MS)

    def _on_filter_changed(self):
        """Handle filter combo change - show/hide conditional widgets."""
        filter_value = self.filter_combo.currentData()

        # Show/hide clear filter button (visible when any filter is active)
        self.clear_filter_btn.setVisible(filter_value is not None)

        # Show/hide dimension spinbox
        self.dimension_spinbox.setVisible(filter_value in ("small_covers", "needs_improvement"))

        # Show/hide size filter
        self.size_filter.setVisible(filter_value == "by_size")

        # Show/hide MIME type filter
        self.mime_filter.setVisible(filter_value == "by_type")

        # Show/hide clear hash filter button
        self.clear_hash_filter_btn.setVisible(
            filter_value == "identical_covers" and self._hash_filter is not None
        )

        # Clear hash filter and context if switching away from identical covers
        if filter_value != "identical_covers" and self._hash_filter is not None:
            self._hash_filter = None
            self.filter_context_manager.clear()

        self._apply_filters()

    def _setup_menu(self):
        """Set up the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu(tr("&File"))

        open_action = QAction(tr("&Open folder..."), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_folder)
        file_menu.addAction(open_action)

        rescan_action = QAction(tr("&Rescan (incremental)"), self)
        rescan_action.setShortcut("F5")
        rescan_action.triggered.connect(self._rescan)
        file_menu.addAction(rescan_action)

        full_rescan_action = QAction(tr("Full rescan"), self)
        full_rescan_action.setShortcut("Shift+F5")
        full_rescan_action.triggered.connect(self._full_rescan)
        file_menu.addAction(full_rescan_action)

        file_menu.addSeparator()

        export_action = QAction(tr("&Export list..."), self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._export_albums)
        file_menu.addAction(export_action)

        import_action = QAction(tr("&Import list..."), self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._import_albums)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        clear_action = QAction(tr("&Clear library"), self)
        clear_action.setShortcut("Ctrl+Shift+Delete")
        clear_action.triggered.connect(self._clear_library)
        file_menu.addAction(clear_action)

        file_menu.addSeparator()

        quit_action = QAction(tr("&Quit"), self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Edit menu
        edit_menu = menubar.addMenu(tr("&Edit"))

        select_all_action = QAction(tr("Select all"), self)
        select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all_action.triggered.connect(self.library_view.select_all)
        edit_menu.addAction(select_all_action)

        deselect_action = QAction(tr("Deselect all"), self)
        deselect_action.triggered.connect(self.library_view.clear_selection)
        edit_menu.addAction(deselect_action)

        edit_menu.addSeparator()

        batch_download_action = QAction(tr("Auto download covers..."), self)
        batch_download_action.setShortcut("Ctrl+Shift+D")
        batch_download_action.triggered.connect(self._batch_download_covers)
        edit_menu.addAction(batch_download_action)

        edit_menu.addSeparator()

        preferences_action = QAction(tr("&Preferences..."), self)
        preferences_action.setShortcut(QKeySequence.StandardKey.Preferences)
        preferences_action.triggered.connect(self._show_preferences)
        edit_menu.addAction(preferences_action)

        # View menu
        view_menu = menubar.addMenu(tr("&View"))

        grid_action = QAction(tr("Grid view"), self)
        grid_action.triggered.connect(lambda: self.library_view.set_view_mode("grid"))
        view_menu.addAction(grid_action)

        list_action = QAction(tr("List view"), self)
        list_action.triggered.connect(lambda: self.library_view.set_view_mode("list"))
        view_menu.addAction(list_action)

        view_menu.addSeparator()

        statistics_action = QAction(tr("Statistics..."), self)
        statistics_action.triggered.connect(self._show_statistics)
        view_menu.addAction(statistics_action)

        # Tools menu
        tools_menu = menubar.addMenu(tr("&Tools"))

        auto_fetch_action = QAction(tr("Auto fetch..."), self)
        auto_fetch_action.triggered.connect(self._auto_fetch)
        tools_menu.addAction(auto_fetch_action)

        batch_acoustid_action = QAction(tr("Batch AcoustID identification..."), self)
        batch_acoustid_action.triggered.connect(self._batch_acoustid_identification)
        tools_menu.addAction(batch_acoustid_action)

        # Help menu
        help_menu = menubar.addMenu(tr("&Help"))

        about_action = QAction(tr("About"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self):
        """Set up the toolbar."""
        toolbar = QToolBar("Main toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)

        # Open folder
        open_action = QAction(tr("Open"), self)
        open_action.setToolTip(tr("Open a music folder"))
        open_action.triggered.connect(self._open_folder)
        toolbar.addAction(open_action)

        # Note: Scan button removed from toolbar. Use menu actions instead:
        # - "Rescan (incremental)" (F5) for quick rescan
        # - "Full rescan" (Shift+F5) for complete rescan
        # Cache is now properly invalidated when covers are applied.

        # Clear
        self.clear_action = QAction(tr("Clear"), self)
        self.clear_action.setToolTip(tr("Clear library"))
        self.clear_action.triggered.connect(self._clear_library)
        toolbar.addAction(self.clear_action)

        toolbar.addSeparator()

        # Auto fetch
        self.auto_fetch_action = QAction(tr("Auto Fetch"), self)
        self.auto_fetch_action.setToolTip(tr("Automatically fetch missing covers"))
        self.auto_fetch_action.setEnabled(False)
        self.auto_fetch_action.triggered.connect(self._auto_fetch)
        toolbar.addAction(self.auto_fetch_action)

    def _setup_statusbar(self):
        """Set up the status bar."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        self.status_label = QLabel(tr("Ready"))
        self.statusbar.addWidget(self.status_label, 1)

        # Scan progress widget (non-blocking, in status bar)
        self.scan_progress_widget = QWidget()
        scan_progress_layout = QHBoxLayout(self.scan_progress_widget)
        scan_progress_layout.setContentsMargins(0, 0, 0, 0)
        scan_progress_layout.setSpacing(4)

        self.scan_progress_label = QLabel(tr("Scan:"))
        scan_progress_layout.addWidget(self.scan_progress_label)

        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setMaximumWidth(200)
        self.scan_progress_bar.setMinimumWidth(150)
        self.scan_progress_bar.setTextVisible(True)
        self.scan_progress_bar.setFormat("%v/%m")
        scan_progress_layout.addWidget(self.scan_progress_bar)

        self.scan_cancel_btn = QPushButton(tr("Cancel"))
        self.scan_cancel_btn.setMaximumWidth(70)
        self.scan_cancel_btn.clicked.connect(self._cancel_scan)
        scan_progress_layout.addWidget(self.scan_cancel_btn)

        self.scan_progress_widget.setVisible(False)
        self.statusbar.addPermanentWidget(self.scan_progress_widget)

        self.count_label = QLabel()
        self.statusbar.addPermanentWidget(self.count_label)

    def _restore_geometry(self):
        """Restore window geometry from config."""
        width = self.config.get("ui.window_width", 1200)
        height = self.config.get("ui.window_height", 800)
        self.resize(width, height)

    def _save_geometry(self):
        """Save window geometry to config."""
        self.config.set("ui.window_width", self.width())
        self.config.set("ui.window_height", self.height())
        self.config.save()

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event for folder or audio file drop."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    # Accept directories
                    if path.is_dir():
                        event.acceptProposedAction()
                        return
                    # Accept audio files
                    if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        """Handle drop event for folder scanning or file loading."""
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths and self._process_dropped_paths(paths):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_files_dropped(self, paths: list):
        """Handle files dropped on the library view.

        Args:
            paths: List of file/folder path strings
        """
        self._process_dropped_paths(paths)

    def _process_dropped_paths(self, paths: list) -> bool:
        """Process dropped file/folder paths.

        Args:
            paths: List of file/folder path strings

        Returns:
            True if any files/folders were processed, False otherwise
        """
        directories = []
        audio_files = []

        for path_str in paths:
            path = Path(path_str)
            if path.is_dir():
                directories.append(path)
            elif path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(path)

        logger.info(
            f"Processing drop: {len(directories)} directories, {len(audio_files)} audio files"
        )

        # Handle directory drops
        if directories:
            if len(directories) == 1:
                self.config.last_directory = directories[0]
                self.config.save()
                self._scan_folder(directories[0])
            else:
                self._scan_multiple_folders(directories)
            return True

        # Handle audio file drops
        if audio_files:
            added_albums = []
            existing_paths = {str(a.path) for a in self.albums}

            for filepath in audio_files:
                album = _create_album_from_file(filepath)
                if album:
                    path_key = str(album.path)
                    if path_key in existing_paths:
                        self.albums = [a if str(a.path) != path_key else album for a in self.albums]
                    else:
                        self.albums.append(album)
                        existing_paths.add(path_key)
                    added_albums.append(album)

            if added_albums:
                self._apply_filters()
                self._update_count_label()
                if len(added_albums) == 1:
                    album = added_albums[0]
                    if album.musicbrainz_albumid:
                        self.status_label.setText(
                            tr("File loaded (MBID: {mbid}...)").format(
                                mbid=album.musicbrainz_albumid[:8]
                            )
                        )
                    else:
                        self.status_label.setText(
                            tr("File loaded: {name}").format(name=album.display_name)
                        )
                else:
                    self.status_label.setText(
                        tr("{count} files loaded").format(count=len(added_albums))
                    )
                return True

        return False

    def _on_group_as_album(self, albums_to_group: list[AlbumInfo]):
        """
        Group multiple individual files into a single album entry.

        This is useful when files in a folder have different or missing album tags
        but the user wants to treat them as a single album.
        """
        if len(albums_to_group) < 2:
            return

        # Defensive validation: ensure all albums share the same parent folder
        parents = set()
        for album in albums_to_group:
            parent = album.path.parent if album.path.is_file() else album.path
            parents.add(parent)

        if len(parents) != 1:
            from .widgets.toast_manager import ToastManager

            logger.error(f"Cannot group albums from different folders: {parents}")
            ToastManager.get_instance().show_error(
                tr("Cannot group: selected files must be in the same folder")
            )
            return

        parent_folder = parents.pop()

        # Collect all audio files from the grouped albums
        audio_files = []
        for album in albums_to_group:
            if album.path.is_file():
                audio_files.append(album.path)

        if not audio_files:
            return

        # Determine album metadata
        # Use the folder name as album title
        album_name = parent_folder.name

        # Find most common artist, or use "Various Artists"
        artists = [a.artist for a in albums_to_group if a.artist]
        if artists:
            from collections import Counter

            artist_counts = Counter(artists)
            most_common_artist, count = artist_counts.most_common(1)[0]
            # Use most common if it's at least 50% of tracks, otherwise Various Artists
            if count >= len(albums_to_group) / 2:
                artist = most_common_artist
            else:
                artist = tr("Various Artists")
        else:
            artist = tr("Various Artists")

        # Find any year from the files
        years = [a.year for a in albums_to_group if a.year]
        year = years[0] if years else None

        # Merge cover info - prefer embedded, then folder
        has_embedded = any(a.cover.has_embedded for a in albums_to_group)
        has_folder = any(a.cover.has_folder for a in albums_to_group)

        # Get cover details from first album that has them
        cover_info = None
        for album in albums_to_group:
            if album.cover.has_embedded or album.cover.has_folder:
                cover_info = album.cover
                break

        if cover_info is None:
            from ..core.models import CoverInfo

            cover_info = CoverInfo(has_embedded=False, has_folder=False)
        else:
            # Create a new CoverInfo with merged info
            from ..core.models import CoverInfo

            cover_info = CoverInfo(
                has_embedded=has_embedded,
                has_folder=has_folder,
                folder_path=cover_info.folder_path,
                embedded_dimensions=cover_info.embedded_dimensions,
                folder_dimensions=cover_info.folder_dimensions,
                embedded_size_bytes=cover_info.embedded_size_bytes,
                folder_size_bytes=cover_info.folder_size_bytes,
                embedded_mime_type=cover_info.embedded_mime_type,
                folder_mime_type=cover_info.folder_mime_type,
            )

        # Create the grouped album
        from ..core.models import AlbumInfo

        grouped_album = AlbumInfo(
            path=parent_folder,
            artist=artist,
            album=album_name,
            year=year,
            cover=cover_info,
            track_count=len(audio_files),
            sample_file=audio_files[0],  # Use first file as sample
            is_forced_group=True,
            forced_group_files=audio_files,
        )

        # Remove individual entries from albums list
        paths_to_remove = {str(a.path) for a in albums_to_group}
        self.albums = [a for a in self.albums if str(a.path) not in paths_to_remove]

        # Add the grouped album
        self.albums.append(grouped_album)

        # Refresh the view
        self._apply_filters()
        self._update_count_label()

        # Select the new grouped album in detail panel
        self._on_album_selected(grouped_album)

        # Show status message
        self.status_label.setText(
            tr('{count} files grouped as album "{name}"').format(
                count=len(audio_files), name=album_name
            )
        )
        logger.info(f"Grouped {len(audio_files)} files as album: {album_name}")

    def _on_ungroup_album(self, album: AlbumInfo):
        """
        Ungroup a forced group album back into individual file entries.

        Restores the original individual file entries that were grouped.
        """
        if not album.is_forced_group or not album.forced_group_files:
            return

        # Remove the grouped album
        self.albums = [a for a in self.albums if str(a.path) != str(album.path)]

        # Recreate individual entries for each file
        total_files = len(album.forced_group_files)
        added_count = 0
        missing_count = 0

        for filepath in album.forced_group_files:
            if filepath.exists():
                individual_album = _create_album_from_file(filepath)
                if individual_album:
                    self.albums.append(individual_album)
                    added_count += 1
            else:
                missing_count += 1

        # Refresh the view
        self._apply_filters()
        self._update_count_label()

        # Clear selection in detail panel
        self.detail_panel.clear()

        # Show status message with warning if files are missing
        if missing_count > 0:
            from .widgets.toast_manager import ToastManager

            ToastManager.get_instance().show_warning(
                tr("{missing} files not found on disk").format(missing=missing_count)
            )
            self.status_label.setText(
                tr("Album ungrouped: {restored} of {total} files restored").format(
                    restored=added_count, total=total_files
                )
            )
            logger.warning(
                f"Ungrouped album: {added_count}/{total_files} files restored, "
                f"{missing_count} files missing"
            )
        else:
            self.status_label.setText(
                tr("Album ungrouped: {count} individual files restored").format(count=added_count)
            )
            logger.info(f"Ungrouped album: {added_count} individual files restored")

    def _on_add_to_group(self, target_group: AlbumInfo, albums_to_add: list[AlbumInfo]):
        """
        Add individual files to an existing forced group.

        Args:
            target_group: The existing forced group to add files to
            albums_to_add: List of individual file albums to add to the group
        """
        if not target_group.is_forced_group:
            logger.error("Target is not a forced group")
            return

        if not albums_to_add:
            return

        # Collect file paths to add
        files_to_add = []
        for album in albums_to_add:
            if album.path.is_file():
                files_to_add.append(album.path)

        if not files_to_add:
            return

        # Defensive validation: ensure all files are in the same folder as the group
        group_folder = target_group.path
        for filepath in files_to_add:
            if filepath.parent != group_folder:
                from .widgets.toast_manager import ToastManager

                logger.error(
                    f"Cannot add file from different folder: {filepath.parent} != {group_folder}"
                )
                ToastManager.get_instance().show_error(
                    tr("Cannot add: files must be in the same folder as the group")
                )
                return

        # Update the target group with new files
        new_files = list(target_group.forced_group_files) + files_to_add
        new_track_count = target_group.track_count + len(files_to_add)

        # Update cover info if any new files have covers
        has_embedded = target_group.cover.has_embedded or any(
            a.cover.has_embedded for a in albums_to_add
        )
        has_folder = target_group.cover.has_folder or any(a.cover.has_folder for a in albums_to_add)

        # Create updated cover info
        from ..core.models import CoverInfo

        updated_cover = CoverInfo(
            has_embedded=has_embedded,
            has_folder=has_folder,
            folder_path=target_group.cover.folder_path,
            embedded_dimensions=target_group.cover.embedded_dimensions,
            folder_dimensions=target_group.cover.folder_dimensions,
            embedded_size_bytes=target_group.cover.embedded_size_bytes,
            folder_size_bytes=target_group.cover.folder_size_bytes,
            embedded_mime_type=target_group.cover.embedded_mime_type,
            folder_mime_type=target_group.cover.folder_mime_type,
        )

        # Create updated group album
        from ..core.models import AlbumInfo

        updated_group = AlbumInfo(
            path=target_group.path,
            artist=target_group.artist,
            album=target_group.album,
            year=target_group.year,
            cover=updated_cover,
            track_count=new_track_count,
            sample_file=target_group.sample_file,
            is_forced_group=True,
            forced_group_files=new_files,
            musicbrainz_albumid=target_group.musicbrainz_albumid,
            musicbrainz_releasegroupid=target_group.musicbrainz_releasegroupid,
            musicbrainz_artistid=target_group.musicbrainz_artistid,
            acoustid=target_group.acoustid,
        )

        # Remove individual entries and old group from albums list
        paths_to_remove = {str(a.path) for a in albums_to_add}
        paths_to_remove.add(str(target_group.path))
        self.albums = [a for a in self.albums if str(a.path) not in paths_to_remove]

        # Add the updated group
        self.albums.append(updated_group)

        # Refresh the view
        self._apply_filters()
        self._update_count_label()

        # Select the updated group in detail panel
        self._on_album_selected(updated_group)

        # Show status message
        self.status_label.setText(
            tr('{count} files added to group "{name}"').format(
                count=len(files_to_add), name=target_group.album or target_group.path.name
            )
        )
        logger.info(
            f"Added {len(files_to_add)} files to group: {target_group.album or target_group.path.name}"
        )

    def closeEvent(self, event):
        """Handle window close event."""
        # Stop the search debounce timer
        if self._search_timer.isActive():
            self._search_timer.stop()

        # Cancel and cleanup any running scan worker
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.cancel()
            self.scan_worker.wait(5000)  # Wait up to 5 seconds
            if self.scan_worker.isRunning():
                self.scan_worker.terminate()  # Force terminate if still running
                self.scan_worker.wait(500)  # Wait for termination to complete

        # Disconnect signals to prevent memory leaks
        self._disconnect_scan_worker()

        self._save_geometry()
        super().closeEvent(event)

    def _open_folder(self):
        """Open a folder for scanning."""
        start_dir = str(self.config.last_directory or Path.home())
        folder = QFileDialog.getExistingDirectory(self, tr("Select a music folder"), start_dir)

        if folder:
            self.config.last_directory = Path(folder)
            self.config.save()
            self._scan_folder(Path(folder))

    def _rescan(self):
        """Rescan the current folder (incremental - uses cache)."""
        if self.config.last_directory and self.config.last_directory.exists():
            self._force_full_scan = False
            self._scan_folder(self.config.last_directory)

    def _full_rescan(self):
        """Perform a full rescan, ignoring the cache."""
        if self.config.last_directory and self.config.last_directory.exists():
            self._force_full_scan = True
            self.scan_cache.clear()
            self._scan_folder(self.config.last_directory)
        else:
            self.toast_manager.show_info(tr("No folder to scan. Open a music folder first."))

    def _clear_library(self):
        """Clear all albums from the library."""
        self.albums = []
        self.filtered_albums = []
        self.library_view.set_albums([])
        self.detail_panel.clear()
        self.detail_panel.setVisible(False)  # Hide panel when no albums
        self.filter_context_manager.clear()  # Clear filter contexts to prevent memory leak
        self._update_count_label()
        self.status_label.setText(tr("Library cleared"))

    def _export_albums(self):
        """Export current album list to a JSON file."""
        if not self.albums:
            self.toast_manager.show_info(tr("No album to export."))
            return

        # Get save file path
        start_dir = str(self.config.last_directory or Path.home())
        file_path, _ = QFileDialog.getSaveFileName(
            self, tr("Export album list"), start_dir, "JSON (*.json)"
        )

        if not file_path:
            return

        # Ensure .json extension
        if not file_path.endswith(".json"):
            file_path += ".json"

        try:
            export_data = {
                "version": "1.0",
                "export_date": datetime.now().isoformat(),
                "total_count": len(self.albums),
                "albums": [album.to_dict() for album in self.albums],
            }

            with Path(file_path).open("w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            self.status_label.setText(
                tr("Exported {count} albums to {filename}").format(
                    count=len(self.albums), filename=Path(file_path).name
                )
            )
            logger.info(f"Exported {len(self.albums)} albums to {file_path}")

        except Exception as e:
            logger.exception("Error exporting albums")
            QMessageBox.critical(
                self, tr("Export error"), tr("Error during export:\n{error}").format(error=str(e))
            )

    def _import_albums(self):
        """Import album list from a JSON file."""
        # Get file path
        start_dir = str(self.config.last_directory or Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("Import album list"), start_dir, "JSON (*.json)"
        )

        if not file_path:
            return

        try:
            with Path(file_path).open(encoding="utf-8") as f:
                import_data = json.load(f)

            # Validate format
            if "albums" not in import_data:
                raise ValueError("Invalid format: 'albums' key missing")

            albums_data = import_data["albums"]
            if not isinstance(albums_data, list):
                raise ValueError("Invalid format: 'albums' must be a list")

            # Convert to AlbumInfo objects
            imported_albums = []
            for album_dict in albums_data:
                try:
                    album = AlbumInfo.from_dict(album_dict)
                    imported_albums.append(album)
                except Exception as e:
                    logger.warning(f"Skipping invalid album entry: {e}")
                    continue

            if not imported_albums:
                QMessageBox.warning(self, tr("Import"), tr("No valid album found in file."))
                return

            # Merge with existing albums (replace by path if duplicate)
            existing_paths = {str(a.path): i for i, a in enumerate(self.albums)}
            added_count = 0
            updated_count = 0

            for album in imported_albums:
                path_str = str(album.path)
                if path_str in existing_paths:
                    self.albums[existing_paths[path_str]] = album
                    updated_count += 1
                else:
                    self.albums.append(album)
                    existing_paths[path_str] = len(self.albums) - 1
                    added_count += 1

            self._apply_filters()
            self._update_count_label()

            # Update UI state
            self.auto_fetch_action.setEnabled(len(self.albums) > 0)

            status_msg = tr("Imported: {added} added, {updated} updated").format(
                added=added_count, updated=updated_count
            )
            self.status_label.setText(status_msg)
            logger.info(f"Imported from {file_path}: {added_count} added, {updated_count} updated")

        except json.JSONDecodeError as e:
            logger.exception("JSON decode error during import")
            QMessageBox.critical(
                self,
                tr("Import error"),
                tr("File is not valid JSON:\n{error}").format(error=str(e)),
            )
        except Exception as e:
            logger.exception("Error importing albums")
            QMessageBox.critical(
                self, tr("Import error"), tr("Error during import:\n{error}").format(error=str(e))
            )

    def _disconnect_scan_worker(self):
        """Safely disconnect signals from scan worker."""
        if self.scan_worker:
            with contextlib.suppress(RuntimeError):
                self.scan_worker.progress.disconnect(self._on_scan_progress)
            with contextlib.suppress(RuntimeError):
                self.scan_worker.finished.disconnect(self._on_scan_finished)
            with contextlib.suppress(RuntimeError):
                self.scan_worker.error.disconnect(self._on_scan_error)

    def _scan_folder(self, path: Path):
        """Scan a folder for albums (non-blocking with status bar progress)."""
        if self.scan_worker and self.scan_worker.isRunning():
            return

        # Disconnect previous worker signals to prevent memory leaks
        self._disconnect_scan_worker()

        # Show the non-blocking progress indicator in status bar
        self.scan_progress_bar.setValue(0)
        self.scan_progress_bar.setMaximum(100)
        self.scan_progress_widget.setVisible(True)

        # Determine scan type and prepare cache
        if self._force_full_scan:
            scan_cache = None
            scan_type = tr("full")
        else:
            scan_cache = self.scan_cache
            scan_type = tr("incremental")

        # Update progress label to show scan type
        self.scan_progress_label.setText(tr("Scan ({type}):").format(type=scan_type))

        # Create and start worker
        self.scan_worker = ScanWorker(path, self.config.exclude_patterns, scan_cache=scan_cache)
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.error.connect(self._on_scan_error)
        self.scan_worker.start()

        self.status_label.setText(
            tr("Scan ({type}) of {path}...").format(type=scan_type, path=path)
        )

    def _scan_multiple_folders(self, folders: list[Path]):
        """Scan multiple folders recursively for albums."""
        from ..core.scanner import MusicScanner

        if self.scan_worker and self.scan_worker.isRunning():
            QMessageBox.warning(
                self, tr("Scan in progress"), tr("A scan is already in progress. Please wait.")
            )
            return

        scanner = MusicScanner(exclude_patterns=self.config.exclude_patterns)
        new_albums = []

        # Create progress dialog
        progress = QProgressDialog(tr("Scanning folders..."), tr("Cancel"), 0, len(folders), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        for i, folder in enumerate(folders):
            if progress.wasCanceled():
                break

            progress.setValue(i)
            progress.setLabelText(tr("Scanning {name}...").format(name=folder.name))

            # Scan the folder recursively (finds all album subfolders)
            folder_albums = scanner.scan_library(folder)
            new_albums.extend(folder_albums)

        progress.setValue(len(folders))
        progress.close()

        if new_albums:
            # Add to existing albums, replacing duplicates by path
            existing_paths = {str(a.path) for a in self.albums}
            for album in new_albums:
                if str(album.path) in existing_paths:
                    self.albums = [
                        a if str(a.path) != str(album.path) else album for a in self.albums
                    ]
                else:
                    self.albums.append(album)

            self._apply_filters()
            self._update_count_label()
            self.status_label.setText(tr("{count} albums added").format(count=len(new_albums)))
            logger.info(f"Added {len(new_albums)} albums from dropped folders")
        else:
            self.status_label.setText(tr("No album found in folders"))

    def _cancel_scan(self):
        """Cancel the current scan operation."""
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.cancel()
            self.scan_progress_widget.setVisible(False)
            self.status_label.setText(tr("Scan cancelled"))
            logger.info("Scan cancelled by user")

    def _on_scan_progress(self, current: int, total: int, message: str):
        """Handle scan progress update (non-blocking status bar progress)."""
        # Update the progress bar in the status bar
        self.scan_progress_bar.setMaximum(total)
        self.scan_progress_bar.setValue(current)
        self.status_label.setText(tr("Scan: {message}").format(message=message))

    def _on_scan_finished(self, albums: list[AlbumInfo], scanned_count: int, cached_count: int):
        """Handle scan completion."""
        # Hide the non-blocking progress indicator
        self.scan_progress_widget.setVisible(False)

        # Reset full scan flag
        self._force_full_scan = False

        # Merge new albums with existing (replace duplicates by path)
        existing_paths = {str(a.path): i for i, a in enumerate(self.albums)}
        for album in albums:
            path_str = str(album.path)
            if path_str in existing_paths:
                self.albums[existing_paths[path_str]] = album
            else:
                self.albums.append(album)
        self._apply_filters()

        # Update UI state
        self.auto_fetch_action.setEnabled(len(self.albums) > 0)

        # Update status with scan type info
        missing_count = len([a for a in albums if a.cover_status == CoverStatus.NONE])
        if cached_count > 0:
            status_msg = tr(
                "Scan complete: {total} albums ({scanned} scanned, {cached} cached)"
            ).format(total=len(albums), scanned=scanned_count, cached=cached_count)
        else:
            status_msg = tr("Scan complete: {count} albums found").format(count=len(albums))
        self.status_label.setText(status_msg)
        self._update_count_label()

        logger.info(
            f"Scan complete: {len(albums)} albums ({scanned_count} scanned, "
            f"{cached_count} cached), {missing_count} without covers"
        )

    def _on_scan_error(self, error: str):
        """Handle scan error."""
        # Hide the non-blocking progress indicator
        self.scan_progress_widget.setVisible(False)

        QMessageBox.critical(
            self, tr("Error"), tr("Error during scan:\n{error}").format(error=error)
        )
        self.status_label.setText(tr("Error during scan"))

    def _apply_filters(self):
        """Apply search and filter to albums."""
        search_text = self.search_box.text().lower().strip()
        filter_value = self.filter_combo.currentData()

        self.filtered_albums = []

        for album in self.albums:
            # Apply search filter (matches artist, album, year, or folder path)
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
                elif filter_value == "has_cover":
                    if not album.has_any_cover:
                        continue
                elif filter_value == "covers_differ":
                    if not album.cover.covers_differ:
                        continue
                elif filter_value == "small_covers":
                    if not self._has_small_cover(album):
                        continue
                elif filter_value == "needs_improvement":
                    # Show albums that need improvement: small covers OR covers differ OR partial
                    is_partial = album.cover_status in (
                        CoverStatus.EMBEDDED_ONLY,
                        CoverStatus.FOLDER_ONLY,
                    )
                    needs_improvement = (
                        self._has_small_cover(album) or album.cover.covers_differ or is_partial
                    )
                    if not needs_improvement:
                        continue
                elif filter_value == "by_size":
                    if not self._matches_size_filter(album):
                        continue
                elif filter_value == "by_type":
                    if not self._matches_type_filter(album):
                        continue
                elif filter_value == "identical_covers":
                    if not self._matches_hash_filter(album):
                        continue
                elif filter_value == "no_acoustid":
                    if album.acoustid:
                        continue
                elif filter_value == "single_tracks":
                    if album.track_count != 1:
                        continue
                elif filter_value == "albums" and album.track_count <= 1:
                    continue

            self.filtered_albums.append(album)

        # Apply sorting based on sort_combo value
        sort_key = self.sort_combo.currentData()
        if sort_key == "artist":
            # Sort by artist, None values at end
            self.filtered_albums.sort(key=lambda a: (a.artist is None, (a.artist or "").lower()))
        elif sort_key == "album":
            # Sort by album name
            self.filtered_albums.sort(key=lambda a: (a.album is None, (a.album or "").lower()))
        elif sort_key == "year":
            # Sort by year descending (newest first), None values at end
            self.filtered_albums.sort(
                key=lambda a: (a.year is None, -(int(a.year) if a.year else 0))
            )
        elif sort_key == "dimension":
            # Sort by max cover dimension (largest first)
            self.filtered_albums.sort(key=lambda a: -self._get_max_cover_dimension(a))
        elif sort_key == "path":
            # Sort by path
            self.filtered_albums.sort(key=lambda a: str(a.path).lower())

        # Pass is_filtered_empty when albums exist but filter returns no results
        is_filtered_empty = bool(self.albums) and not self.filtered_albums
        self.library_view.set_albums(self.filtered_albums, is_filtered_empty=is_filtered_empty)
        self._update_count_label()

        # Show detail panel when albums are loaded, hide when empty
        self.detail_panel.setVisible(bool(self.albums))

    def _has_small_cover(self, album: AlbumInfo) -> bool:
        """Check if album has any cover smaller than the threshold."""
        threshold = self.dimension_spinbox.value()
        cover = album.cover

        # Check embedded cover dimensions
        if cover.has_embedded and cover.embedded_dimensions:
            width, height = cover.embedded_dimensions
            if width < threshold or height < threshold:
                return True

        # Check folder cover dimensions
        if cover.has_folder and cover.folder_dimensions:
            width, height = cover.folder_dimensions
            if width < threshold or height < threshold:
                return True

        return False

    def _get_max_cover_dimension(self, album: AlbumInfo) -> int:
        """Get the maximum cover dimension for sorting (larger of embedded or folder)."""
        max_dim = 0
        cover = album.cover

        # Check embedded cover dimensions
        if cover.has_embedded and cover.embedded_dimensions:
            width, height = cover.embedded_dimensions
            max_dim = max(max_dim, width, height)

        # Check folder cover dimensions
        if cover.has_folder and cover.folder_dimensions:
            width, height = cover.folder_dimensions
            max_dim = max(max_dim, width, height)

        return max_dim

    def _update_count_label(self):
        """Update the count label in status bar."""
        total = len(self.albums)
        filtered = len(self.filtered_albums)
        missing = len([a for a in self.albums if a.cover_status == CoverStatus.NONE])
        search_text = self.search_box.text().strip()

        if total == filtered:
            self.count_label.setText(
                tr("Albums: {total} | Without cover: {missing}").format(
                    total=total, missing=missing
                )
            )
        elif search_text:
            self.count_label.setText(
                tr("Search: {filtered} result(s) of {total} | Without cover: {missing}").format(
                    filtered=filtered, total=total, missing=missing
                )
            )
        else:
            self.count_label.setText(
                tr("Displayed: {filtered}/{total} | Without cover: {missing}").format(
                    filtered=filtered, total=total, missing=missing
                )
            )

    def _on_album_selected(self, album: AlbumInfo):
        """Handle single album selection."""
        # Get filter context if hash filter is active
        context = self.filter_context_manager.get_context(album) if self._hash_filter else None
        logger.debug(
            f"_on_album_selected: album={album.display_name}, hash_filter={self._hash_filter is not None}, context={context}"
        )
        self.detail_panel.set_album(album, context)

    def _on_albums_selected(self, albums: list[AlbumInfo]):
        """Handle multiple album selection."""
        logger.debug(
            f"_on_albums_selected: count={len(albums)}, hash_filter={self._hash_filter is not None}"
        )
        if len(albums) == 1:
            context = (
                self.filter_context_manager.get_context(albums[0]) if self._hash_filter else None
            )
            self.detail_panel.set_album(albums[0], context)
        else:
            # Collect contexts for all selected albums (keyed by path string)
            contexts = {}
            if self._hash_filter:
                for album in albums:
                    ctx = self.filter_context_manager.get_context(album)
                    if ctx:
                        contexts[str(album.path)] = ctx
            self.detail_panel.set_albums(albums, contexts if contexts else None)

    def _on_cover_applied(self, album: AlbumInfo):
        """
        Handle cover applied to album.

        Invalidates scan cache and rescans album covers to ensure
        incremental scans reflect the updated cover status.

        Args:
            album: Album with newly applied/modified cover
        """
        # 1. Invalidate scan cache for this folder
        if album.path.is_dir():
            removed = self.scan_cache.remove_folder(album.path)
            if removed:
                logger.debug(f"Invalidated scan cache for folder: {album.path}")
        else:
            # Album is a single file - invalidate parent folder
            parent_folder = album.path.parent
            removed = self.scan_cache.remove_folder(parent_folder)
            if removed:
                logger.debug(f"Invalidated scan cache for parent folder: {parent_folder}")

        # 2. Re-scan album covers to update metadata immediately
        try:
            self._scanner.rescan_album_covers(album)
            logger.debug(f"Rescanned covers for album: {album.display_name}")
        except Exception as e:
            logger.warning(f"Failed to rescan covers for {album.display_name}: {e}")

        # 3. Update scan cache with fresh data (only for folder-based albums)
        if album.path.is_dir():
            self.scan_cache.update_folder(album.path, album)

        # 4. Save cache if modified
        if self.scan_cache.is_dirty:
            self.scan_cache.save()

        # 5. Refresh the album in the library view
        self.library_view.refresh_album(album)

        # 6. Update count label to reflect cover status changes
        self._update_count_label()

    def _auto_fetch(self):
        """Start automatic cover fetching."""
        missing_albums = [a for a in self.filtered_albums if a.cover_status == CoverStatus.NONE]

        if not missing_albums:
            self.toast_manager.show_info(tr("No album without cover in current selection."))
            return

        reply = QMessageBox.question(
            self,
            tr("Auto fetch"),
            tr(
                "Automatically search covers for {count} albums?\n\n"
                "Only matches with a high score will be automatically applied."
            ).format(count=len(missing_albums)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.detail_panel.start_batch_fetch(missing_albums)

    def _batch_download_covers(self):
        """Open batch download dialog for automatic cover fetching."""
        # Get selected albums from library view
        selected_albums = self.library_view.get_selected_albums()

        # If no selection, use all visible (filtered) albums
        albums_to_process = selected_albums if selected_albums else self.filtered_albums

        # Filter to albums that need covers (missing covers only)
        albums_needing_covers = [a for a in albums_to_process if a.cover_status == CoverStatus.NONE]

        if not albums_needing_covers:
            self.toast_manager.show_info(
                tr(
                    "No album without cover in current selection. "
                    "Select albums without cover or use the 'Without cover' filter "
                    "to display only affected albums."
                )
            )
            return

        # Show confirmation with count
        if selected_albums:
            message = tr("Automatically download covers for {count} selected album(s)?").format(
                count=len(albums_needing_covers)
            )
        else:
            message = tr("Automatically download covers for {count} visible album(s)?").format(
                count=len(albums_needing_covers)
            )

        min_score = self.config.get("auto_mode_min_score", 95)
        message += tr(
            "\n\nOnly results with a score >= {score}% will be automatically applied."
        ).format(score=min_score)

        reply = QMessageBox.question(
            self,
            tr("Auto download"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Open batch download dialog
        dialog = BatchDownloadDialog(albums_needing_covers, self.config, self)
        dialog.cover_applied.connect(self._on_cover_applied)
        dialog.exec()

        # Refresh the view after dialog closes
        self._apply_filters()
        self._update_count_label()

    def _batch_acoustid_identification(self):
        """Start batch AcoustID identification for albums without AcoustID."""
        # Check if fingerprinting is available
        try:
            from ..core.fingerprint import BatchFingerprinter

            fingerprinter = BatchFingerprinter()
            if not fingerprinter.is_available:
                raise ImportError("fpcalc not found")
        except ImportError:
            QMessageBox.warning(
                self,
                tr("Fingerprinting unavailable"),
                tr(
                    "Audio fingerprinting requires chromaprint to be installed.\n\n"
                    "On Linux: sudo apt install libchromaprint-tools\n"
                    "On macOS: brew install chromaprint\n"
                    "On Windows: Download fpcalc.exe from acoustid.org"
                ),
            )
            return

        # Get albums without AcoustID
        albums_without_acoustid = [a for a in self.filtered_albums if not a.acoustid]

        if not albums_without_acoustid:
            QMessageBox.information(
                self,
                tr("Batch AcoustID identification"),
                tr("All albums in the current view already have an AcoustID."),
            )
            return

        # Open batch AcoustID dialog
        from .dialogs import BatchAcoustIdDialog

        dialog = BatchAcoustIdDialog(albums_without_acoustid, self.config, self)
        dialog.album_updated.connect(self._on_album_acoustid_updated)
        dialog.exec()

        # Refresh the view after dialog closes
        self._apply_filters()
        self._update_count_label()

    def _on_album_acoustid_updated(self, album: AlbumInfo):
        """Handle album AcoustID update from batch identification."""
        self.library_view.refresh_album(album)

    def _show_preferences(self):
        """Show preferences dialog."""
        dialog = PreferencesDialog(self.config, self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()

    def _on_settings_changed(self):
        """Handle settings change."""
        logger.info("Settings changed, reloading configuration")
        # Reload any settings that affect the UI

    def _on_splitter_moved(self, pos: int, index: int):
        """Handle splitter movement to recalculate grid columns."""
        self.library_view.recalculate_grid()

    def _show_about(self):
        """Show about dialog."""
        year = datetime.now().year
        QMessageBox.about(
            self,
            tr("about.title").format(app=APP_NAME),
            tr("about.content").format(app=APP_NAME, version=VERSION, author=AUTHOR, year=year),
        )

    def _matches_size_filter(self, album: AlbumInfo) -> bool:
        """Check if album matches the size range filter."""
        cover = album.cover

        # Check embedded cover size
        if (
            cover.has_embedded
            and cover.embedded_size_bytes is not None
            and self.size_filter.matches(cover.embedded_size_bytes)
        ):
            return True

        # Check folder cover size
        return (
            cover.has_folder
            and cover.folder_size_bytes is not None
            and self.size_filter.matches(cover.folder_size_bytes)
        )

    def _matches_type_filter(self, album: AlbumInfo) -> bool:
        """Check if album matches the MIME type filter."""
        cover = album.cover

        # Check embedded cover type
        if (
            cover.has_embedded
            and cover.embedded_mime_type
            and self.mime_filter.matches(cover.embedded_mime_type)
        ):
            return True

        # Check folder cover type
        return (
            cover.has_folder
            and cover.folder_mime_type
            and self.mime_filter.matches(cover.folder_mime_type)
        )

    def _matches_hash_filter(self, album: AlbumInfo) -> bool:
        """Check if album has a cover matching the hash filter.

        Also records WHERE the match occurred (embedded, folder, or both)
        in the filter context manager for context-aware actions.
        """
        if self._hash_filter is None:
            return True  # No hash filter active, show all

        # Use FilterContextManager to compute match source and store context
        match_source = self.filter_context_manager.compute_hash_match_source(
            album, self._hash_filter
        )

        if match_source:
            # Store context for this album
            context = FilterContext(match_source=match_source, matched_hash=self._hash_filter)
            self.filter_context_manager.set_context(album, context)
            return True
        else:
            # Remove any stale context if album no longer matches
            self.filter_context_manager.remove_context(album)
            return False

    def _on_identical_covers_requested(self, cover_hash: str):
        """Handle request to find albums with identical covers."""
        self._hash_filter = cover_hash

        # Switch to identical covers filter
        # Note: This triggers _on_filter_changed which calls _apply_filters()
        # and shows the clear button (since _hash_filter is already set)
        for i in range(self.filter_combo.count()):
            if self.filter_combo.itemData(i) == "identical_covers":
                self.filter_combo.setCurrentIndex(i)
                break

        # Update detail panel with context if current album is in filtered results
        # This ensures the "Delete from source" button appears without re-selecting
        current_album = self.detail_panel.current_album
        if current_album and current_album in self.filtered_albums:
            context = self.filter_context_manager.get_context(current_album)
            if context:
                self.detail_panel.set_album(current_album, context)

        # Show result count
        count = len(self.filtered_albums)
        if count == 0:
            self.status_label.setText(tr("No album with identical cover found"))
        elif count == 1:
            self.status_label.setText(tr("1 album with identical cover"))
        else:
            self.status_label.setText(tr("{count} albums with identical cover").format(count=count))

    def _clear_hash_filter(self):
        """Clear the hash filter and return to all albums."""
        self._hash_filter = None
        self.filter_context_manager.clear()
        self.clear_hash_filter_btn.setVisible(False)

        # Reset to "All albums"
        self.filter_combo.setCurrentIndex(0)
        self._apply_filters()

    def _clear_all_filters(self):
        """Clear all active filters and return to showing all albums."""
        # Reset to "All albums" - this triggers _on_filter_changed which handles:
        # - Hiding clear_filter_btn
        # - Hiding clear_hash_filter_btn
        # - Clearing hash filter and context if needed
        # - Calling _apply_filters
        self.filter_combo.setCurrentIndex(0)

    def _on_acoustid_identify_requested(self, album: AlbumInfo):
        """Handle request to identify album via AcoustID fingerprinting."""
        from .search_panel import SearchPanel

        # Open search panel with auto-fingerprint enabled
        search_panel = SearchPanel(album, self.config, self, auto_fingerprint=True)
        search_panel.cover_selected.connect(self._on_cover_selected_from_search)
        search_panel.exec()

    def _on_cover_selected_from_search(self, cover_data: bytes, result):
        """Handle cover selection from search panel opened via context menu."""
        # Forward to detail panel if it has the same album
        if self.detail_panel.current_album:
            self.detail_panel._on_cover_selected(cover_data, result)

    def _on_search_cover_from_context(self, album: AlbumInfo):
        """Handle search cover request from library view context menu."""
        from .search_panel import SearchPanel

        # Select the album in the detail panel first
        self.detail_panel.set_album(album)

        # Open search panel for this album
        search_panel = SearchPanel(album, self.config, self)
        search_panel.cover_selected.connect(self._on_cover_selected_from_search)
        search_panel.exec()

    def _on_remove_cover_from_context(self, album: AlbumInfo):
        """Handle remove cover request from library view context menu."""
        if not album.has_any_cover:
            return

        from ..core.embedder import CoverEmbedder

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            tr("Remove cover"),
            tr(
                'Remove the cover from "{name}"?\n\nThis will remove both the embedded '
                "cover and the folder image file."
            ).format(name=album.display_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        embedder = CoverEmbedder()

        try:
            # Remove folder cover
            if album.cover.folder_path and album.cover.folder_path.exists():
                album.cover.folder_path.unlink()
                album.cover.has_folder = False
                album.cover.folder_file = None
                album.cover.folder_path = None
                album.cover.folder_hash = None

            # Remove embedded covers
            if album.cover.has_embedded:
                if album.path.is_file():
                    # Single file
                    embedder.remove_embedded_cover(album.path)
                elif album.track_count == 1 and album.sample_file and album.sample_file.exists():
                    # Single file in folder
                    embedder.remove_embedded_cover(album.sample_file)
                elif album.path.is_dir():
                    # Multi-file album
                    for track in album.path.iterdir():
                        if track.is_file() and track.suffix.lower() in {
                            ".mp3",
                            ".flac",
                            ".ogg",
                            ".m4a",
                            ".mp4",
                            ".opus",
                        }:
                            embedder.remove_embedded_cover(track)
                album.cover.has_embedded = False
                album.cover.embedded_hash = None

            # Invalidate caches
            if album.sample_file:
                embedded_cover_cache.invalidate(album.sample_file)

            # Update UI
            self._on_cover_applied(album)
            self.toast_manager.show_success(
                tr('Cover removed from "{name}"').format(name=album.display_name)
            )

        except Exception as e:
            logger.exception(f"Error removing cover from {album.display_name}")
            QMessageBox.warning(
                self, tr("Error"), tr("Error removing cover:\n{error}").format(error=str(e))
            )

    def _show_statistics(self):
        """Show statistics dialog."""
        dialog = StatisticsDialog(self.albums, self)
        dialog.exec()
