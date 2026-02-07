"""
Cover search panel dialog.
"""

import contextlib
import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..api.base import CoverProvider
from ..api.discogs import DiscogsProvider
from ..api.musicbrainz import MusicBrainzProvider
from ..core.exceptions import NetworkError, RateLimitError
from ..core.fingerprint import AudioFingerprinter, is_fingerprinting_available
from ..core.fingerprint_batch import BatchFingerprinter, BatchFingerprintResult
from ..core.models import AlbumInfo, SearchResult
from ..i18n import tr
from ..utils.cache import ImageCache, get_image_cache
from ..utils.config import Config
from .fingerprint_dialog import FingerprintResultsDialog
from .search_criteria_manager import SearchCriteriaManager
from .widgets.cover_preview import ZoomDialog
from .widgets.image_info import ImageInfoLabel
from .widgets.loading_spinner import LoadingSpinner
from .widgets.source_selector import SourceSelector

logger = logging.getLogger(__name__)

# Default number of concurrent thumbnail downloads (CDN has no rate limit)
DEFAULT_CONCURRENT_DOWNLOADS = 4


class SearchWorker(QThread):
    """Worker thread for searching covers."""

    results_ready = Signal(list)  # list of SearchResult
    error = Signal(str)
    status_update = Signal(str)  # status message for UI
    connection_status = Signal(str, bool)  # (message, is_error) for connection status display

    def __init__(
        self,
        provider,
        artist: str,
        album: str,
        year: str | None,
        musicbrainz_albumid: str | None = None,
        isrc: str | None = None,
        barcode: str | None = None,
        fingerprinter: AudioFingerprinter | None = None,
        sample_file=None,
    ):
        super().__init__()
        self.provider = provider
        self.artist = artist
        self.album = album
        self.year = year
        self.musicbrainz_albumid = musicbrainz_albumid
        self.isrc = isrc
        self.barcode = barcode
        self.fingerprinter = fingerprinter
        self.sample_file = sample_file

    def run(self):
        try:
            results = []
            api_host = self.provider.api_host if self.provider else "?"
            logger.debug(
                f"SearchWorker.run() started: artist={self.artist!r}, album={self.album!r}, mbid={self.musicbrainz_albumid!r}, isrc={self.isrc!r}, barcode={self.barcode!r}"
            )

            # Emit connection status
            self.connection_status.emit(tr("Connecting to {host}...").format(host=api_host), False)

            # Strategy 1: Direct lookup by MBID (most reliable)
            if self.musicbrainz_albumid and isinstance(self.provider, MusicBrainzProvider):
                self.status_update.emit(tr("Direct MBID lookup..."))
                logger.info(f"Trying direct MBID lookup: {self.musicbrainz_albumid}")
                result = self.provider.lookup_by_mbid(self.musicbrainz_albumid)
                if result:
                    results.append(result)
                    logger.info(f"Direct MBID lookup successful: {result.artist} - {result.album}")
                else:
                    logger.warning(f"MBID lookup returned no result for {self.musicbrainz_albumid}")

            # Strategy 2: ISRC lookup (MusicBrainz only)
            if not results and self.isrc and isinstance(self.provider, MusicBrainzProvider):
                self.status_update.emit(tr("ISRC lookup..."))
                logger.info(f"Trying ISRC lookup: {self.isrc}")
                result = self.provider.lookup_by_isrc(self.isrc)
                if result:
                    results.append(result)
                    logger.info(f"ISRC lookup successful: {result.artist} - {result.album}")
                else:
                    logger.info(f"ISRC lookup returned no result for {self.isrc}")

            # Strategy 3: Barcode lookup (MusicBrainz and Discogs)
            if not results and self.barcode:
                if isinstance(self.provider, MusicBrainzProvider):
                    self.status_update.emit(tr("Barcode lookup..."))
                    logger.info(f"Trying MusicBrainz barcode lookup: {self.barcode}")
                    result = self.provider.lookup_by_barcode(self.barcode)
                    if result:
                        results.append(result)
                        logger.info(
                            f"MusicBrainz barcode lookup successful: {result.artist} - {result.album}"
                        )
                    else:
                        logger.info(
                            f"MusicBrainz barcode lookup returned no result for {self.barcode}"
                        )
                elif isinstance(self.provider, DiscogsProvider):
                    self.status_update.emit(tr("Barcode lookup..."))
                    logger.info(f"Trying Discogs barcode lookup: {self.barcode}")
                    result = self.provider.lookup_by_barcode(self.barcode)
                    if result:
                        results.append(result)
                        logger.info(
                            f"Discogs barcode lookup successful: {result.artist} - {result.album}"
                        )
                    else:
                        logger.info(f"Discogs barcode lookup returned no result for {self.barcode}")

            # Strategy 4: Text search (fallback)
            if not results and (self.artist or self.album):
                self.status_update.emit(tr("Text search..."))
                logger.info(f"Text search: artist={self.artist!r}, album={self.album!r}")
                search_results = self.provider.search(self.artist, self.album, self.year)
                logger.info(f"Text search returned {len(search_results)} results")
                results.extend(search_results)

            # Strategy 5: Fingerprint identification (last resort)
            if (
                not results
                and self.fingerprinter
                and self.sample_file
                and self.fingerprinter.is_configured
                and self.sample_file.exists()
            ):
                self.status_update.emit(tr("Trying audio fingerprinting..."))
                logger.info(f"Fingerprint fallback: {self.sample_file}")
                try:
                    matches = self.fingerprinter.identify(self.sample_file)
                    if matches:
                        # Use ranking with metadata comparison for better accuracy
                        # Import here to avoid circular imports
                        from src.core.fingerprint import (
                            extract_file_metadata,
                            rank_recordings,
                        )

                        file_metadata = extract_file_metadata(self.sample_file)
                        ranked = rank_recordings(matches, file_metadata, min_sources=2)
                        best_match = ranked[0] if ranked else matches[0]

                        fp_artist = best_match.get("artist", "")
                        # Use single_titles as fallback when title is None
                        fp_title = best_match.get("title", "")
                        if not fp_title:
                            single_titles = best_match.get("single_titles", [])
                            if single_titles:
                                fp_title = single_titles[0]
                        fp_album = best_match.get("album", "")
                        fp_score = best_match.get("score", 0)
                        fp_sources = best_match.get("sources", 0)
                        logger.info(
                            f"Fingerprint match: {fp_artist} - {fp_title} "
                            f"(album: {fp_album}, score: {fp_score:.2f}, sources: {fp_sources})"
                        )
                        # Use identified artist to search for covers
                        if fp_artist:
                            self.status_update.emit(
                                tr("Fingerprint found: {artist}. Searching covers...").format(
                                    artist=fp_artist
                                )
                            )
                            # Search with fingerprinted artist and album if available
                            fp_results = self.provider.search(fp_artist, fp_album or "", None)
                            logger.info(
                                f"Fingerprint-based search returned {len(fp_results)} results"
                            )
                            results.extend(fp_results)
                except Exception as e:
                    logger.warning(f"Fingerprint fallback failed: {e}")

            if not results and not (self.artist or self.album):
                logger.warning(f"No search performed: artist={self.artist!r}, album={self.album!r}")

            # Emit connection success
            self.connection_status.emit(tr("Connected to {host}").format(host=api_host), False)

            # Emit results immediately - cover URLs will be loaded in ThumbnailWorker
            logger.debug(f"Emitting {len(results)} results")
            self.results_ready.emit(results)
        except RateLimitError as e:
            api_host = self.provider.api_host if self.provider else "?"
            retry_info = f" (retry in {e.retry_after}s)" if e.retry_after else ""
            error_msg = tr("Rate limit exceeded on {host}{retry}").format(
                host=api_host, retry=retry_info
            )
            self.connection_status.emit(error_msg, True)
            logger.warning(f"Search rate limited: {e}")
            self.error.emit(str(e))
        except NetworkError as e:
            api_host = self.provider.api_host if self.provider else "?"
            if "timed out" in str(e).lower():
                error_msg = tr("Connection timeout to {host}").format(host=api_host)
            else:
                error_msg = tr("Connection failed to {host}").format(host=api_host)
            self.connection_status.emit(error_msg, True)
            logger.warning(f"Search network error: {e}")
            self.error.emit(str(e))
        except requests.exceptions.HTTPError as e:
            api_host = self.provider.api_host if self.provider else "?"
            status_code = e.response.status_code if e.response is not None else "?"
            error_msg = tr("Communication error with {host} (HTTP {code})").format(
                host=api_host, code=status_code
            )
            self.connection_status.emit(error_msg, True)
            logger.exception("Search HTTP error")
            self.error.emit(str(e))
        except requests.exceptions.ConnectionError as e:
            api_host = self.provider.api_host if self.provider else "?"
            error_msg = tr("Connection failed to {host}").format(host=api_host)
            self.connection_status.emit(error_msg, True)
            logger.exception("Search connection error")
            self.error.emit(str(e))
        except requests.exceptions.Timeout as e:
            api_host = self.provider.api_host if self.provider else "?"
            error_msg = tr("Connection timeout to {host}").format(host=api_host)
            self.connection_status.emit(error_msg, True)
            logger.exception("Search timeout error")
            self.error.emit(str(e))
        except Exception as e:
            api_host = self.provider.api_host if self.provider else "?"
            error_msg = tr("Error communicating with {host}").format(host=api_host)
            self.connection_status.emit(error_msg, True)
            logger.exception("Search error")
            self.error.emit(str(e))


class ThumbnailWorker(QThread):
    """Worker thread for loading cover URLs and thumbnails in parallel."""

    thumbnail_ready = Signal(int, bytes, int, int)  # index, data, width, height
    cover_url_ready = Signal(int, str)  # index, url
    progress = Signal(int, int)  # completed, total
    finished = Signal()  # emitted when all thumbnails are loaded or cancelled

    def __init__(
        self,
        provider,
        results: list[SearchResult],
        cache: ImageCache,
        max_workers: int = DEFAULT_CONCURRENT_DOWNLOADS,
    ):
        super().__init__()
        self.provider = provider
        self.results = results
        self.cache = cache
        self.max_workers = max_workers
        self._cancelled = False

    def cancel(self):
        """Request cancellation of thumbnail loading."""
        self._cancelled = True

    def run(self):
        """Load thumbnails in parallel using ThreadPoolExecutor."""
        total = len(self.results)
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            futures = {}
            for i, result in enumerate(self.results):
                if self._cancelled:
                    break
                future = executor.submit(self._process_thumbnail, i, result)
                futures[future] = i

            # Collect results as they complete
            for future in as_completed(futures):
                if self._cancelled:
                    break
                try:
                    future.result()  # Signals are emitted in _process_thumbnail
                except Exception as e:
                    logger.warning(f"Thumbnail error for index {futures[future]}: {e}")
                finally:
                    completed += 1
                    self.progress.emit(completed, total)

        self.finished.emit()

    def _process_thumbnail(self, index: int, result: "SearchResult"):
        """Process a single thumbnail (called from thread pool)."""
        if self._cancelled:
            return

        # Determine the cover URL (use existing or fetch it)
        url = result.cover_url
        if not url:
            url = self.provider.get_cover_url(result)
            if url:
                # Emit signal - main thread will update the result object
                self.cover_url_ready.emit(index, url)

        if not url or self._cancelled:
            return

        # Download thumbnail
        data = self.cache.get(url)
        if data is None:
            data = self.provider.download_cover(url)
            if data:
                self.cache.set(url, data)

        if data and not self._cancelled:
            # Extract image dimensions
            width, height = self._get_image_dimensions(data)
            # Emit signal - main thread will update the result object
            self.thumbnail_ready.emit(index, data, width, height)

    def _get_image_dimensions(self, data: bytes) -> tuple:
        """Extract image dimensions from bytes.

        Uses QImage instead of QPixmap because this method is called
        from ThreadPoolExecutor worker threads, and QPixmap is not thread-safe.
        """
        image = QImage()
        if image.loadFromData(data):
            return image.width(), image.height()
        return 0, 0


class CoverDownloadWorker(QThread):
    """Worker thread for downloading a single cover (non-blocking)."""

    download_ready = Signal(int, bytes)  # index, data
    download_error = Signal(int, str)  # index, error message

    def __init__(self, provider, index: int, url: str, cache: ImageCache):
        super().__init__()
        self.provider = provider
        self.index = index
        self.url = url
        self.cache = cache

    def run(self):
        try:
            # Try cache first
            data = self.cache.get(self.url)
            if data is None:
                data = self.provider.download_cover(self.url)
                if data:
                    self.cache.set(self.url, data)
            if data:
                self.download_ready.emit(self.index, data)
            else:
                self.download_error.emit(self.index, tr("Download failed"))
        except Exception as e:
            self.download_error.emit(self.index, str(e))


class FingerprintWorker(QThread):
    """Worker thread for audio fingerprinting via AcoustID."""

    # Signal emitted with identification results: (artist, title, album, recording_id, score)
    identification_ready = Signal(dict)  # dict with keys: artist, title, recording_id, score
    error = Signal(str)
    status_update = Signal(str)

    def __init__(self, fingerprinter: AudioFingerprinter, audio_file):
        super().__init__()
        self.fingerprinter = fingerprinter
        self.audio_file = audio_file

    def run(self):
        try:
            self.status_update.emit(tr("Generating audio fingerprint..."))

            # Generate fingerprint
            fp_result = self.fingerprinter.fingerprint(self.audio_file)
            if fp_result is None:
                self.error.emit(tr("Failed to generate fingerprint. Is chromaprint installed?"))
                return

            duration, fingerprint = fp_result
            logger.info(f"Generated fingerprint for {self.audio_file}: duration={duration:.1f}s")

            self.status_update.emit(tr("Looking up fingerprint in AcoustID database..."))

            # Lookup in AcoustID
            # Returns: list of matches, empty list for no matches, None for error
            matches = self.fingerprinter.lookup(fingerprint, duration)
            if matches is None:
                # None means an error occurred (API error, invalid key, etc.)
                self.error.emit(tr("AcoustID lookup failed. Check your API key in Preferences."))
                return
            if not matches:
                # Empty list means no matches found
                self.error.emit(tr("No matches found in AcoustID database"))
                return

            # Use ranking with metadata comparison for better accuracy
            # This prioritizes results with high 'sources' count (reliability indicator)
            from pathlib import Path

            from src.core.fingerprint import extract_file_metadata, rank_recordings

            audio_path = (
                Path(self.audio_file) if not isinstance(self.audio_file, Path) else self.audio_file
            )
            file_metadata = extract_file_metadata(audio_path)
            ranked = rank_recordings(matches, file_metadata, min_sources=2)
            best_match = ranked[0] if ranked else matches[0]

            # Get title from single_titles if not available directly
            title = best_match.get("title", "")
            if not title:
                single_titles = best_match.get("single_titles", [])
                if single_titles:
                    title = single_titles[0]

            logger.info(
                f"AcoustID match: {best_match.get('artist')} - {title} "
                f"(album: {best_match.get('album')}, score: {best_match.get('score', 0):.2f}, "
                f"sources: {best_match.get('sources', 0)})"
            )

            # Add resolved title to the match dict before emitting
            best_match["resolved_title"] = title
            self.identification_ready.emit(best_match)

        except Exception as e:
            logger.exception("Fingerprint error")
            self.error.emit(str(e))


class BatchFingerprintWorker(QThread):
    """Worker thread for batch audio fingerprinting."""

    # Signal emitted with batch results
    batch_ready = Signal(object)  # BatchFingerprintResult
    progress = Signal(int, int, str)  # current, total, track_name
    error = Signal(str)
    status_update = Signal(str)

    def __init__(
        self,
        batch_fingerprinter: BatchFingerprinter,
        album: AlbumInfo,
        previous_result: BatchFingerprintResult | None = None,
    ):
        super().__init__()
        self.batch_fingerprinter = batch_fingerprinter
        self.album = album
        self.previous_result = previous_result
        self._cancelled = False

    def cancel(self):
        """Request cancellation."""
        self._cancelled = True

    def run(self):
        try:
            self.status_update.emit(tr("Analyzing audio fingerprints..."))

            def progress_callback(current: int, total: int, track_name: str):
                if self._cancelled:
                    raise InterruptedError("Cancelled")
                self.progress.emit(current, total, track_name)

            if self.previous_result:
                # Scan more tracks
                result = self.batch_fingerprinter.analyze_more(
                    self.album,
                    self.previous_result,
                    progress_callback=progress_callback,
                )
            else:
                # Initial batch analysis
                result = self.batch_fingerprinter.analyze_album(
                    self.album,
                    progress_callback=progress_callback,
                )

            if self._cancelled:
                return

            self.batch_ready.emit(result)

        except InterruptedError:
            logger.info("Batch fingerprint cancelled")
        except Exception as e:
            logger.exception("Batch fingerprint error")
            self.error.emit(str(e))


class CoverResultCard(QFrame):
    """Card widget for a cover search result."""

    clicked = Signal(int)  # index
    double_clicked = Signal(int)  # index

    def __init__(self, index: int, result: SearchResult, parent=None):
        super().__init__(parent)
        self.index = index
        self.result = result
        self._selected = False
        self._image_data: bytes | None = None
        self._pixmap: QPixmap | None = None

        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setFixedSize(140, 195)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Container for thumbnail and spinner overlay
        thumb_container = QWidget()
        thumb_container.setFixedSize(120, 120)
        # Make container transparent to mouse events so they reach the card
        thumb_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Thumbnail
        self.thumb_label = QLabel(thumb_container)
        self.thumb_label.setFixedSize(120, 120)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #2a2a2a; border-radius: 2px;")
        # Make label transparent to mouse events so they reach the card
        self.thumb_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Loading spinner (centered on thumbnail)
        self.spinner = LoadingSpinner(size=30, parent=thumb_container)
        self.spinner.move(45, 45)  # Center the 30px spinner in 120px container
        self.spinner.start()

        layout.addWidget(thumb_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # Score
        score_text = f"{self.result.score}%"
        if self.result.has_cover_art:
            score_text += " " + tr("[Cover]")
        self.score_label = QLabel(score_text)
        self.score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self.score_label)

        # Image info (dimensions + size)
        self.image_info_label = ImageInfoLabel()
        layout.addWidget(self.image_info_label)

        # Artist/Album (truncated only if needed)
        artist = self.result.artist
        info = artist[:15] + "..." if len(artist) > 15 else artist
        self.info_label = QLabel(info)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("font-size: 9px; color: #888;")
        layout.addWidget(self.info_label)

        self._update_style()

    def set_thumbnail(self, data: bytes, width: int = 0, height: int = 0):
        """Set the thumbnail image with optional metadata."""
        # Stop the loading spinner
        self.spinner.stop()

        # Store original data and pixmap for zoom
        self._image_data = data
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self._pixmap = pixmap
            scaled = pixmap.scaled(
                120,
                120,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumb_label.setPixmap(scaled)
            self.thumb_label.setToolTip(tr("Double-click to zoom"))

            # Update image info
            img_width = width if width > 0 else pixmap.width()
            img_height = height if height > 0 else pixmap.height()
            self.image_info_label.set_image_info(img_width, img_height, len(data))
        else:
            self.thumb_label.setText("?")
            self.image_info_label.clear_info()

    def set_has_cover(self, has_cover: bool):
        """Update the cover availability indicator."""
        if has_cover:
            self.result.has_cover_art = True
            score_text = f"{self.result.score}% {tr('[Cover]')}"
            self.score_label.setText(score_text)

    def set_selected(self, selected: bool):
        """Set selection state."""
        self._selected = selected
        self._update_style()

    def stop_loading(self):
        """Stop the loading spinner and show a cancelled state."""
        # Use is_spinning() (checks timer.isActive()) instead of isVisible()
        # because isVisible() returns False when parent hierarchy is hidden,
        # but the timer may still be active and must be stopped to prevent
        # "QObject::killTimer: Timers cannot be stopped from another thread" crash.
        if self.spinner.is_spinning():
            self.spinner.stop()
            # Show a placeholder indicating loading was cancelled
            self.thumb_label.setText("—")
            self.thumb_label.setStyleSheet(
                "background-color: #2a2a2a; border-radius: 2px; color: #666; font-size: 20px;"
            )

    def is_loading(self) -> bool:
        """Check if the card is still loading its thumbnail."""
        return self.spinner.is_spinning()

    def _update_style(self):
        """Update the frame style."""
        if self._selected:
            self.setStyleSheet("""
                CoverResultCard {
                    border: 2px solid #4a90d9;
                    border-radius: 4px;
                    background-color: rgba(74, 144, 217, 0.1);
                }
            """)
        else:
            self.setStyleSheet("""
                CoverResultCard {
                    border: 1px solid #444;
                    border-radius: 4px;
                    background-color: transparent;
                }
                CoverResultCard:hover {
                    border: 1px solid #666;
                    background-color: rgba(255, 255, 255, 0.03);
                }
            """)

    def mousePressEvent(self, event):
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to show zoom dialog."""
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap:
            self._show_zoom_dialog()
        super().mouseDoubleClickEvent(event)

    def _show_zoom_dialog(self):
        """Show the zoom dialog for this cover."""
        if not self._pixmap or self._pixmap.isNull():
            return
        dialog = ZoomDialog(self._pixmap, self.window())
        dialog.exec()


class SearchPanel(QDialog):
    """
    Dialog for searching and selecting cover art.
    """

    cover_selected = Signal(bytes, SearchResult)  # cover_data, result

    def __init__(
        self, album: AlbumInfo, config: Config, parent=None, auto_fingerprint: bool = False
    ):
        super().__init__(parent)
        self.album = album
        self.config = config
        self.cache = get_image_cache(config)
        self.results: list[SearchResult] = []
        self.selected_index: int = -1
        self.result_cards: list[CoverResultCard] = []
        self.search_worker: SearchWorker | None = None
        self.thumb_worker: ThumbnailWorker | None = None
        self.preview_worker: CoverDownloadWorker | None = None
        self._apply_worker: CoverDownloadWorker | None = None
        self._fingerprint_worker: FingerprintWorker | None = None
        self._batch_fingerprint_worker: BatchFingerprintWorker | None = None
        self._fingerprint_dialog: FingerprintResultsDialog | None = None
        self._batch_result: BatchFingerprintResult | None = None
        self._acoustid_mbid: str = ""  # MBID from AcoustID identification
        self._cached_cover_data: dict = {}  # index -> bytes
        self._active_provider: CoverProvider | None = None  # Provider used for current search
        self._auto_fingerprint = auto_fingerprint  # Auto-start fingerprinting on show

        # Setup fingerprinter if available (app key is built-in, user key is optional for submissions)
        self._fingerprinter: AudioFingerprinter | None = None
        self._batch_fingerprinter: BatchFingerprinter | None = None
        if is_fingerprinting_available():
            # User key is optional - only needed for fingerprint submissions
            user_key = config.get("api.acoustid_user_key", "") or None
            self._fingerprinter = AudioFingerprinter(user_key=user_key)
            self._batch_fingerprinter = BatchFingerprinter(fingerprinter=self._fingerprinter)

        # Smart search criteria manager
        self.criteria_manager = SearchCriteriaManager(config)

        self._setup_ui()

    @property
    def provider(self) -> CoverProvider:
        """Get the currently selected provider."""
        return self.source_selector.get_current_provider()

    def _setup_ui(self):
        """Set up the user interface with two-column layout."""
        self.setWindowTitle(tr("Cover search: {name}").format(name=self.album.display_name))
        self.setMinimumSize(750, 550)

        # Restore saved size or use default (950x750)
        width = self.config.get("ui.search_dialog_width", 950)
        height = self.config.get("ui.search_dialog_height", 750)
        self.resize(width, height)

        main_layout = QVBoxLayout(self)

        # 1. Source selector (top row - full width)
        self.source_selector = SourceSelector(self.config)
        self.source_selector.source_changed.connect(self._on_source_changed)
        main_layout.addWidget(self.source_selector)

        # 2. Content area (two columns)
        content_layout = QHBoxLayout()

        # ============================================
        # 2a. LEFT COLUMN: Search criteria (fixed width)
        # ============================================
        left_column = QVBoxLayout()
        left_column.setSpacing(8)

        # Search mode indicator (at the top of left column)
        # Add top spacing to align with the "Results" group box title on the right
        left_column.addSpacing(8)

        self.has_mbid = bool(self.album.musicbrainz_albumid)
        self.force_text_search = False

        mode_widget = QWidget()
        mode_layout = QVBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(4)

        self.search_mode_label = QLabel()
        self.search_mode_label.setStyleSheet(
            "font-size: 10px; padding: 4px 6px; border-radius: 4px;"
        )
        self.search_mode_label.setWordWrap(True)
        mode_layout.addWidget(self.search_mode_label)

        # Checkbox to force text search when MBID is available
        self.force_text_check = QCheckBox(tr("Force text search"))
        self.force_text_check.setToolTip(
            tr(
                "Ignore MBID and perform text-based search.\n"
                "Useful if MBID doesn't give satisfactory results."
            )
        )
        self.force_text_check.setVisible(self.has_mbid)
        self.force_text_check.toggled.connect(self._on_force_text_toggled)
        mode_layout.addWidget(self.force_text_check)

        left_column.addWidget(mode_widget)

        # Add spacing after mode indicator, before search criteria
        left_column.addSpacing(12)

        self._update_search_mode_indicator()

        # Search form with separate fields and checkboxes
        search_group = QGroupBox(tr("Search criteria"))
        search_form_layout = QGridLayout(search_group)
        search_form_layout.setSpacing(4)

        # Artist field with checkbox
        self.artist_check = QCheckBox(tr("Artist:"))
        search_form_layout.addWidget(self.artist_check, 0, 0)
        self.artist_input = QLineEdit()
        self.artist_input.setPlaceholderText(tr("Artist name"))
        self.artist_input.returnPressed.connect(self._start_search)
        search_form_layout.addWidget(self.artist_input, 0, 1)

        # Album field with checkbox
        self.album_check = QCheckBox(tr("Album:"))
        search_form_layout.addWidget(self.album_check, 1, 0)
        self.album_input = QLineEdit()
        self.album_input.setPlaceholderText(tr("Album title"))
        self.album_input.returnPressed.connect(self._start_search)
        search_form_layout.addWidget(self.album_input, 1, 1)

        # Year field with checkbox (unchecked by default)
        self.year_check = QCheckBox(tr("Year:"))
        search_form_layout.addWidget(self.year_check, 2, 0)
        self.year_input = QLineEdit()
        self.year_input.setPlaceholderText(tr("(optional)"))
        self.year_input.setMaximumWidth(80)
        self.year_input.returnPressed.connect(self._start_search)
        search_form_layout.addWidget(self.year_input, 2, 1)

        # Title field with checkbox (only for single files)
        self.title_check = QCheckBox(tr("Title:"))
        search_form_layout.addWidget(self.title_check, 3, 0)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText(tr("Track title"))
        self.title_input.returnPressed.connect(self._start_search)
        search_form_layout.addWidget(self.title_input, 3, 1)

        # Hide title row for multi-file albums
        self.is_single_file = self.album.track_count == 1 and self.album.path.is_file()
        self.title_check.setVisible(self.is_single_file)
        self.title_input.setVisible(self.is_single_file)

        # ISRC field with checkbox
        self.isrc_check = QCheckBox(tr("ISRC:"))
        search_form_layout.addWidget(self.isrc_check, 4, 0)
        self.isrc_input = QLineEdit()
        self.isrc_input.setPlaceholderText(tr("ISRC"))
        self.isrc_input.setMaximumWidth(150)
        self.isrc_input.returnPressed.connect(self._start_search)
        search_form_layout.addWidget(self.isrc_input, 4, 1)

        # Barcode field with checkbox
        self.barcode_check = QCheckBox(tr("Barcode:"))
        search_form_layout.addWidget(self.barcode_check, 5, 0)
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText(tr("UPC/EAN"))
        self.barcode_input.setMaximumWidth(150)
        self.barcode_input.returnPressed.connect(self._start_search)
        search_form_layout.addWidget(self.barcode_input, 5, 1)

        # Add vertical spacer before buttons
        search_form_layout.setRowMinimumHeight(6, 12)

        # Search buttons row (stacked vertically for narrow column)
        btn_row_layout = QVBoxLayout()
        btn_row_layout.setSpacing(4)

        # AcoustID button (only if fingerprinting is available and we have a sample file)
        self.acoustid_btn = QPushButton(tr("AcoustID"))
        self.acoustid_btn.setToolTip(
            tr(
                "Use audio fingerprinting to identify this track.\n"
                "Fills in artist/album fields from AcoustID database."
            )
        )
        can_fingerprint = (
            self._fingerprinter is not None
            and self._fingerprinter.is_configured
            and self.album.sample_file is not None
            and self.album.sample_file.exists()
        )
        self.acoustid_btn.setEnabled(can_fingerprint)
        if not can_fingerprint:
            if not is_fingerprinting_available():
                self.acoustid_btn.setToolTip(
                    tr("Fingerprinting unavailable.\nInstall chromaprint/fpcalc and pyacoustid.")
                )
            elif not self.album.sample_file:
                self.acoustid_btn.setToolTip(tr("No audio file available for fingerprinting."))
        self.acoustid_btn.clicked.connect(self._start_fingerprint)
        btn_row_layout.addWidget(self.acoustid_btn)

        self.search_btn = QPushButton(tr("Search"))
        self.search_btn.clicked.connect(self._start_search)
        btn_row_layout.addWidget(self.search_btn)
        search_form_layout.addLayout(btn_row_layout, 7, 0, 1, 2)

        left_column.addWidget(search_group)

        # Progress bar (in left column)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(False)
        left_column.addWidget(self.progress_bar)

        # Push content to top
        left_column.addStretch()

        # Create left widget with fixed width (290px)
        left_widget = QWidget()
        left_widget.setLayout(left_column)
        left_widget.setFixedWidth(290)

        # Set initial checkbox values (without triggering signals)
        self.artist_check.setChecked(self.config.get("search.use_artist", True))
        self.album_check.setChecked(self.config.get("search.use_album", True))
        self.year_check.setChecked(self.config.get("search.use_year", False))
        self.title_check.setChecked(self.config.get("search.use_title", False))
        self.isrc_check.setChecked(self.config.get("search.use_isrc", False))
        self.barcode_check.setChecked(self.config.get("search.use_barcode", False))

        # Populate fields and update states
        self._populate_search_fields()

        # Connect signals AFTER initial setup is complete
        self.artist_check.toggled.connect(self._on_field_checkbox_toggled)
        self.album_check.toggled.connect(self._on_field_checkbox_toggled)
        self.year_check.toggled.connect(self._on_field_checkbox_toggled)
        self.title_check.toggled.connect(self._on_field_checkbox_toggled)
        self.isrc_check.toggled.connect(self._on_field_checkbox_toggled)
        self.barcode_check.toggled.connect(self._on_field_checkbox_toggled)

        # ============================================
        # 2b. RIGHT COLUMN: Results + Selection (expandable)
        # ============================================
        right_column = QVBoxLayout()
        right_column.setSpacing(8)

        # Results area
        results_group = QGroupBox(tr("Results"))
        results_layout = QVBoxLayout(results_group)

        # Connection status label (shows API connection state)
        self.connection_status_label = QLabel()
        self.connection_status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.connection_status_label.setStyleSheet(
            "font-size: 10px; padding: 2px 6px; color: #888;"
        )
        self.connection_status_label.setVisible(False)
        results_layout.addWidget(self.connection_status_label)

        # Stop button for thumbnail loading (hidden by default)
        stop_layout = QHBoxLayout()
        stop_layout.addStretch()
        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.setToolTip(tr("Stop loading thumbnails"))
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop_thumbnail_loading)
        stop_layout.addWidget(self.stop_btn)
        results_layout.addLayout(stop_layout)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.results_widget = QWidget()
        self.results_grid = QGridLayout(self.results_widget)
        self.results_grid.setSpacing(8)
        self.results_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.results_scroll.setWidget(self.results_widget)

        # Install event filter to handle resize events
        self.results_scroll.viewport().installEventFilter(self)

        results_layout.addWidget(self.results_scroll)

        self.no_results_label = QLabel(tr("Start a search to find covers"))
        self.no_results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_results_label.setStyleSheet("color: #888;")
        results_layout.addWidget(self.no_results_label)

        right_column.addWidget(results_group, 1)  # Stretch factor 1

        # Selected result info (below results in right column)
        # Hidden by default, shown with animation when a result is selected
        self.info_group = QGroupBox(tr("Selection"))
        self.info_group.setMaximumHeight(0)  # Start collapsed
        self.info_group.setVisible(False)
        info_layout = QHBoxLayout(self.info_group)

        self.selected_thumb = QLabel()
        self.selected_thumb.setFixedSize(80, 80)
        self.selected_thumb.setStyleSheet("background-color: #2a2a2a; border-radius: 4px;")
        info_layout.addWidget(self.selected_thumb)

        self.selected_info = QLabel(tr("No selection"))
        self.selected_info.setWordWrap(True)
        info_layout.addWidget(self.selected_info, 1)

        right_column.addWidget(self.info_group)  # Fixed height

        # Animation for selection panel
        self._selection_animation = QPropertyAnimation(self.info_group, b"maximumHeight")
        self._selection_animation.setDuration(200)
        self._selection_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Add columns to content layout
        content_layout.addWidget(left_widget)
        content_layout.addLayout(right_column, 1)  # Right column expands

        main_layout.addLayout(content_layout, 1)  # Content area expands

        # 3. Bottom buttons (full width)
        # Add spacing before buttons
        main_layout.addSpacing(12)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton(tr("Apply"))
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply_selection)
        btn_layout.addWidget(self.apply_btn)

        main_layout.addLayout(btn_layout)

    def _show_selection_panel(self):
        """Show the selection panel with animation."""
        if self.info_group.isVisible() and self.info_group.maximumHeight() > 0:
            return  # Already visible

        self.info_group.setVisible(True)
        # Calculate target height based on content
        # Reset max height temporarily to get the natural size
        self.info_group.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        target_height = self.info_group.sizeHint().height()
        self.info_group.setMaximumHeight(0)  # Reset to collapsed

        self._selection_animation.stop()
        self._selection_animation.setStartValue(0)
        self._selection_animation.setEndValue(target_height)
        self._selection_animation.start()

    def _hide_selection_panel(self):
        """Hide the selection panel with animation."""
        if not self.info_group.isVisible():
            return  # Already hidden

        self._selection_animation.stop()
        self._selection_animation.setStartValue(self.info_group.maximumHeight())
        self._selection_animation.setEndValue(0)
        self._selection_animation.finished.connect(self._on_selection_hide_finished)
        self._selection_animation.start()

    def _on_selection_hide_finished(self):
        """Called when hide animation finishes."""
        self._selection_animation.finished.disconnect(self._on_selection_hide_finished)
        if self.info_group.maximumHeight() == 0:
            self.info_group.setVisible(False)

    def _update_search_mode_indicator(self):
        """Update the search mode indicator label."""
        use_mbid = self.has_mbid and not self.force_text_search

        if use_mbid:
            self.search_mode_label.setText(
                tr("Mode: MBID Lookup ({mbid}...)").format(mbid=self.album.musicbrainz_albumid[:8])
            )
            self.search_mode_label.setStyleSheet(
                "font-size: 11px; padding: 4px 8px; border-radius: 4px; "
                "background-color: #2E7D32; color: white;"
            )
            self.search_mode_label.setToolTip(
                tr(
                    "MusicBrainz Album ID: {mbid}\n\n"
                    "Search uses the unique MusicBrainz identifier.\n"
                    "This is the most reliable method (exact match)."
                ).format(mbid=self.album.musicbrainz_albumid)
            )
        else:
            self.search_mode_label.setText(tr("Mode: Text search"))
            self.search_mode_label.setStyleSheet(
                "font-size: 11px; padding: 4px 8px; border-radius: 4px; "
                "background-color: #1976D2; color: white;"
            )
            self.search_mode_label.setToolTip(
                tr("Search uses artist/album text.\nResults depend on text matching.")
            )

    def _on_field_checkbox_toggled(self):
        """Handle checkbox toggle - update field enabled state."""
        self._update_field_states()

    def _update_field_states(self):
        """Update field enabled states based on checkboxes."""
        use_mbid = self.has_mbid and not self.force_text_search
        disabled_style = "background-color: #3a3a3a; color: #888;"

        if use_mbid:
            # Disable all fields in MBID mode
            for check, field in [
                (self.artist_check, self.artist_input),
                (self.album_check, self.album_input),
                (self.year_check, self.year_input),
                (self.title_check, self.title_input),
                (self.isrc_check, self.isrc_input),
                (self.barcode_check, self.barcode_input),
            ]:
                check.setEnabled(False)
                field.setEnabled(False)
                field.setStyleSheet(disabled_style)
        else:
            # Enable checkboxes, and enable fields based on checkbox state
            for check, field in [
                (self.artist_check, self.artist_input),
                (self.album_check, self.album_input),
                (self.year_check, self.year_input),
                (self.title_check, self.title_input),
                (self.isrc_check, self.isrc_input),
                (self.barcode_check, self.barcode_input),
            ]:
                check.setEnabled(True)
                is_checked = check.isChecked()
                field.setEnabled(is_checked)
                if is_checked:
                    field.setStyleSheet("")
                else:
                    field.setStyleSheet(disabled_style)

    def _populate_search_fields(self):
        """Populate search fields with album metadata and smart defaults."""
        use_mbid = self.has_mbid and not self.force_text_search

        if use_mbid:
            # Clear fields in MBID mode - checkboxes stay at saved values
            self.artist_input.setText("")
            self.album_input.setText("")
            self.year_input.setText("")
            self.title_input.setText("")
            # Reset to saved preferences in MBID mode
            self.artist_check.setChecked(self.config.get("search.use_artist", True))
            self.album_check.setChecked(self.config.get("search.use_album", True))
            self.year_check.setChecked(self.config.get("search.use_year", False))
            self.title_check.setChecked(self.config.get("search.use_title", False))
        else:
            # Use SearchCriteriaManager for smart defaults
            criteria = self.criteria_manager.compute_criteria(
                album=self.album,
                is_single_file=self.is_single_file,
                force_text_search=self.force_text_search,
            )

            # Apply computed values
            self.artist_input.setText(criteria.artist_value)
            self.album_input.setText(criteria.album_value)
            self.year_input.setText(criteria.year_value)
            self.title_input.setText(criteria.title_value)

            # Apply computed checkbox states
            self.artist_check.setChecked(criteria.artist_enabled)
            self.album_check.setChecked(criteria.album_enabled)
            self.year_check.setChecked(criteria.year_enabled)
            self.title_check.setChecked(criteria.title_enabled)

            # Show info message if available (as extended tooltip on mode label)
            if criteria.info_message:
                current_tooltip = self.search_mode_label.toolTip()
                self.search_mode_label.setToolTip(f"{current_tooltip}\n\n{criteria.info_message}")

        # Always populate ISRC and Barcode from album metadata (not from criteria manager)
        self.isrc_input.setText(self.album.isrc or "")
        self.barcode_input.setText(self.album.barcode or "")
        self.isrc_check.setChecked(self.config.get("search.use_isrc", False))
        self.barcode_check.setChecked(self.config.get("search.use_barcode", False))

        self._update_field_states()

    def _on_force_text_toggled(self, checked: bool):
        """Handle force text search checkbox toggle."""
        self.force_text_search = checked
        self._update_search_mode_indicator()
        self._populate_search_fields()

    def _on_source_changed(self, source_name: str):
        """Handle source provider change."""
        logger.debug(f"Source changed to: {source_name}")
        # Clear previous results when source changes
        self._clear_results()

    def _start_fingerprint(self):
        """Start audio fingerprinting to identify the track."""
        if not self._batch_fingerprinter or not self._batch_fingerprinter.is_available:
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

        if not self.album.tracks:
            QMessageBox.warning(
                self, tr("Error"), tr("No audio files available for fingerprinting.")
            )
            return

        # Show progress
        self.progress_bar.setVisible(True)
        self.acoustid_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.no_results_label.setText(tr("Analyzing audio fingerprints..."))
        self.no_results_label.setVisible(True)

        # Start batch fingerprint worker
        self._batch_fingerprint_worker = BatchFingerprintWorker(
            self._batch_fingerprinter, self.album
        )
        self._batch_fingerprint_worker.batch_ready.connect(self._on_batch_fingerprint_ready)
        self._batch_fingerprint_worker.error.connect(self._on_fingerprint_error)
        self._batch_fingerprint_worker.status_update.connect(self._on_status_update)
        self._batch_fingerprint_worker.progress.connect(self._on_batch_progress)
        self._batch_fingerprint_worker.start()

    def _on_fingerprint_ready(self, match: dict):
        """Handle successful fingerprint identification."""
        self.progress_bar.setVisible(False)
        self.acoustid_btn.setEnabled(True)
        self.search_btn.setEnabled(True)

        artist = match.get("artist", "")
        title = match.get("title", "")
        album = match.get("album", "")
        year = match.get("year")
        mbid = match.get("mbid", "")
        score = match.get("score", 0)

        logger.info(
            f"Fingerprint identified: {artist} - {album} ({year}) "
            f"[MBID: {mbid}] (score: {score:.2f})"
        )

        # Fill in the form fields with identified data
        if artist:
            self.artist_input.setText(artist)
            self.artist_check.setChecked(True)

        # Use album name for album field, title for single files
        if album:
            self.album_input.setText(album)
            self.album_check.setChecked(True)
        elif title and self.is_single_file:
            self.title_input.setText(title)
            self.title_check.setChecked(True)

        # Fill in year if available
        if year:
            self.year_input.setText(str(year))
            self.year_check.setChecked(True)

        # Store MBID for direct MusicBrainz lookup (optional enhancement)
        self._acoustid_mbid = mbid

        # Show success message with identified info
        score_percent = int(score * 100) if score <= 1 else int(score)
        display_title = album or title or "?"
        self.no_results_label.setText(
            tr(
                "Identified via AcoustID: {artist} - {title} ({score}%% confidence).\n"
                "Click 'Search' to find covers."
            ).format(artist=artist or "?", title=display_title, score=score_percent)
        )
        self.no_results_label.setVisible(True)

        # Enable text search mode since AcoustID doesn't give us MBID
        if self.has_mbid:
            self.force_text_check.setChecked(True)

    def _on_fingerprint_error(self, error: str):
        """Handle fingerprint error."""
        self.progress_bar.setVisible(False)
        self.acoustid_btn.setEnabled(True)
        self.search_btn.setEnabled(True)

        logger.error(f"Fingerprint error: {error}")
        self.no_results_label.setText(tr("AcoustID error: {error}").format(error=error))
        self.no_results_label.setVisible(True)

        QMessageBox.warning(
            self,
            tr("Identification error"),
            tr("Could not identify via AcoustID:\n{error}").format(error=error),
        )

    def _on_batch_progress(self, current: int, total: int, track_name: str):
        """Handle batch fingerprint progress update."""
        self.no_results_label.setText(
            tr("Analyzing track {current}/{total}: {name}").format(
                current=current, total=total, name=track_name
            )
        )

    def _on_batch_fingerprint_ready(self, result: BatchFingerprintResult):
        """Handle batch fingerprint results."""
        self.progress_bar.setVisible(False)
        self.acoustid_btn.setEnabled(True)
        self.search_btn.setEnabled(True)

        self._batch_result = result

        if not result.has_results:
            self.no_results_label.setText(
                tr("No fingerprint matches found ({analyzed} tracks analyzed).").format(
                    analyzed=result.analyzed_tracks
                )
            )
            self.no_results_label.setVisible(True)
            return

        # Show the fingerprint results dialog
        self._fingerprint_dialog = FingerprintResultsDialog(self.album, result, self)
        self._fingerprint_dialog.result_selected.connect(self._on_fingerprint_result_selected)
        self._fingerprint_dialog.scan_more_requested.connect(self._on_scan_more_requested)
        self._fingerprint_dialog.cover_selected.connect(self._on_acoustid_cover_selected)
        self._fingerprint_dialog.exec()

    def _on_fingerprint_result_selected(self, aggregated_result):
        """Handle user selection from fingerprint dialog."""
        from ..core.fingerprint_batch import AggregatedResult

        if not isinstance(aggregated_result, AggregatedResult):
            return

        logger.info(
            f"User selected fingerprint result: {aggregated_result.artist} - {aggregated_result.album} "
            f"(MBID: {aggregated_result.mbid}, votes: {aggregated_result.vote_count})"
        )

        # Fill in the form fields with selected data
        if aggregated_result.artist:
            self.artist_input.setText(aggregated_result.artist)
            self.artist_check.setChecked(True)

        if aggregated_result.album:
            self.album_input.setText(aggregated_result.album)
            self.album_check.setChecked(True)
        elif aggregated_result.title:
            self.album_input.setText(aggregated_result.title)
            self.album_check.setChecked(True)

        if aggregated_result.year:
            self.year_input.setText(str(aggregated_result.year))
            self.year_check.setChecked(True)

        # Store MBID for direct MusicBrainz lookup
        self._acoustid_mbid = aggregated_result.mbid or ""

        # Show success message
        display_title = aggregated_result.album or aggregated_result.title or "?"
        self.no_results_label.setText(
            tr(
                "Selected: {artist} - {title} ({votes} tracks matched).\n"
                "Click 'Search' to find covers."
            ).format(
                artist=aggregated_result.artist or "?",
                title=display_title,
                votes=aggregated_result.vote_count,
            )
        )
        self.no_results_label.setVisible(True)

        # Enable text search mode
        if self.has_mbid:
            self.force_text_check.setChecked(True)

    def _on_acoustid_cover_selected(self, aggregated_result, cover_data: bytes):
        """Handle direct cover selection from fingerprint dialog."""
        from ..core.fingerprint_batch import AggregatedResult

        if not isinstance(aggregated_result, AggregatedResult):
            return

        logger.info(
            f"User selected cover from AcoustID result: {aggregated_result.artist} - "
            f"{aggregated_result.album} (MBID: {aggregated_result.mbid})"
        )

        # Create a SearchResult from the AggregatedResult
        search_result = SearchResult(
            provider="MusicBrainz (AcoustID)",
            mbid=aggregated_result.mbid,
            artist=aggregated_result.artist or "",
            album=aggregated_result.album or aggregated_result.title or "",
            year=str(aggregated_result.year) if aggregated_result.year else None,
            score=int(aggregated_result.average_score * 100),
            has_cover_art=True,
        )

        # Emit the cover selection and close the search panel
        self.cover_selected.emit(cover_data, search_result)
        self.accept()

    def _on_scan_more_requested(self):
        """Handle request to scan more tracks."""
        if not self._batch_fingerprinter or not self._batch_result:
            return

        # Start worker for additional tracks
        self._batch_fingerprint_worker = BatchFingerprintWorker(
            self._batch_fingerprinter,
            self.album,
            previous_result=self._batch_result,
        )
        self._batch_fingerprint_worker.batch_ready.connect(self._on_scan_more_ready)
        self._batch_fingerprint_worker.error.connect(self._on_scan_more_error)
        self._batch_fingerprint_worker.progress.connect(self._on_scan_more_progress)
        self._batch_fingerprint_worker.start()

    def _on_scan_more_progress(self, current: int, total: int, track_name: str):
        """Handle progress during scan more."""
        if self._fingerprint_dialog:
            self._fingerprint_dialog.update_progress(current, total, track_name)

    def _on_scan_more_ready(self, new_batch_result: BatchFingerprintResult):
        """Handle scan more results."""
        self._batch_result = new_batch_result
        if self._fingerprint_dialog:
            self._fingerprint_dialog.update_results(new_batch_result)

    def _on_scan_more_error(self, error: str):
        """Handle scan more error."""
        logger.error(f"Scan more error: {error}")
        if self._fingerprint_dialog:
            self._fingerprint_dialog.update_results(self._batch_result)
        QMessageBox.warning(
            self,
            tr("Scan error"),
            tr("Error scanning additional tracks:\n{error}").format(error=error),
        )

    def _on_status_update(self, message: str):
        """Handle status update from search worker."""
        self.no_results_label.setText(message)
        self.no_results_label.setVisible(True)

    def _on_connection_status(self, message: str, is_error: bool):
        """Handle connection status update from search worker."""
        self.connection_status_label.setText(message)
        self.connection_status_label.setVisible(True)
        if is_error:
            self.connection_status_label.setStyleSheet(
                "font-size: 10px; padding: 2px 6px; color: #ff6b6b; "
                "background-color: rgba(255, 107, 107, 0.1); border-radius: 3px;"
            )
        else:
            self.connection_status_label.setStyleSheet(
                "font-size: 10px; padding: 2px 6px; color: #69db7c; "
                "background-color: rgba(105, 219, 124, 0.1); border-radius: 3px;"
            )

    def _start_search(self):
        """Start the search."""
        # Store the current provider at the start of the search
        # This ensures the provider is preserved throughout the search operation
        self._active_provider = self.provider
        logger.info(f"_start_search called, provider={self._active_provider}")
        if not self._active_provider:
            logger.warning("No provider available")
            self.no_results_label.setText(tr("No source available"))
            self.no_results_label.setVisible(True)
            return

        # Check if provider requires API key
        if self._active_provider.requires_api_key and not self._active_provider.is_configured():
            QMessageBox.warning(
                self,
                tr("Configuration required"),
                tr(
                    "Provider {name} requires an API key.\n\n"
                    "Please configure the API key in preferences\n"
                    "(Menu Edit -> Preferences)."
                ).format(name=self._active_provider.name),
            )
            return

        # Determine if we should use MBID
        use_mbid = self.has_mbid and not self.force_text_search
        mbid_to_use = self.album.musicbrainz_albumid if use_mbid else None

        # Get search parameters from form fields (only if checkbox is checked)
        artist = self.artist_input.text().strip() if self.artist_check.isChecked() else ""
        album = self.album_input.text().strip() if self.album_check.isChecked() else ""
        year = self.year_input.text().strip() if self.year_check.isChecked() else None
        isrc = self.isrc_input.text().strip() if self.isrc_check.isChecked() else None
        barcode = self.barcode_input.text().strip() if self.barcode_check.isChecked() else None

        # Include title in album search for single files if checked
        if self.is_single_file and self.title_check.isChecked():
            title = self.title_input.text().strip()
            if title and not album:
                # Use title as album name if no album
                album = title

        # For text search, we need at least artist or album (or ISRC/barcode)
        if not use_mbid and not artist and not album and not isrc and not barcode:
            self.no_results_label.setText(tr("Enter at least an artist or album"))
            self.no_results_label.setVisible(True)
            return

        logger.debug(
            f"_start_search: artist={artist!r}, album={album!r}, year={year!r}, isrc={isrc!r}, barcode={barcode!r}, use_mbid={use_mbid}"
        )

        # Disconnect signals first, then cancel worker, then clear results.
        # This order matches _cleanup_workers() and ensures no stale signal delivery.
        self._disconnect_workers()
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.cancel()
        self._clear_results()

        self.progress_bar.setVisible(True)
        self.search_btn.setEnabled(False)

        # Show appropriate status message
        provider_name = self._active_provider.name if self._active_provider else "?"
        if use_mbid:
            self.no_results_label.setText(
                tr("MBID lookup on {provider}...").format(provider=provider_name)
            )
            logger.info(f"Starting search with MBID: {self.album.musicbrainz_albumid}")
        else:
            # Build search description
            search_desc = []
            if artist:
                search_desc.append(tr("artist='{artist}'").format(artist=artist))
            if album:
                search_desc.append(tr("album='{album}'").format(album=album))
            if year:
                search_desc.append(tr("year={year}").format(year=year))
            criteria_text = ", ".join(search_desc) if search_desc else "..."
            self.no_results_label.setText(
                tr("Searching on {provider}: {desc}...").format(
                    provider=provider_name, desc=criteria_text, criteria=criteria_text
                )
            )
            logger.info(
                f"Starting text search on {provider_name}: artist={artist!r}, album={album!r}, year={year!r}"
            )

        # Start search worker (with or without MBID based on mode)
        # Use the year from the form field, not from album metadata
        self.search_worker = SearchWorker(
            self._active_provider,
            artist,
            album,
            year,  # User-provided year from form
            musicbrainz_albumid=mbid_to_use,
            isrc=isrc,
            barcode=barcode,
            fingerprinter=self._fingerprinter,
            sample_file=self.album.sample_file,
        )
        self.search_worker.results_ready.connect(self._on_results_ready)
        self.search_worker.error.connect(self._on_search_error)
        self.search_worker.status_update.connect(self._on_status_update)
        self.search_worker.connection_status.connect(self._on_connection_status)
        self.search_worker.start()

    def _clear_results(self):
        """Clear the results grid."""
        self.results = []
        self.result_cards = []
        self.selected_index = -1
        self._cached_cover_data = {}

        # Hide stop button and connection status when clearing results
        self.stop_btn.setVisible(False)
        self.connection_status_label.setVisible(False)

        while self.results_grid.count():
            item = self.results_grid.takeAt(0)
            widget = item.widget()
            if widget:
                # Stop active spinner timers before deletion to prevent
                # "QObject::killTimer: Timers cannot be stopped from another thread"
                # crash when Qt processes deleteLater() later in the event loop.
                if isinstance(widget, CoverResultCard):
                    widget.stop_loading()
                widget.deleteLater()

        # Hide selection panel with animation
        self._hide_selection_panel()
        self.selected_thumb.clear()
        self.selected_info.setText(tr("No selection"))
        self.apply_btn.setEnabled(False)

    def _on_results_ready(self, results: list[SearchResult]):
        """Handle search results."""
        # Use the stored provider from when the search started
        provider = self._active_provider
        logger.info(
            f"_on_results_ready: received {len(results)} results from {provider.name if provider else '?'}"
        )
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        self.results = results

        if not results:
            provider_name = provider.name if provider else "?"
            logger.info(f"No results to display from {provider_name}")
            self.no_results_label.setText(
                tr("No results found on {provider}").format(provider=provider_name)
            )
            self.no_results_label.setVisible(True)
            return

        self.no_results_label.setVisible(False)

        # Create result cards
        for i, result in enumerate(results):
            card = CoverResultCard(i, result)
            card.clicked.connect(self._on_card_clicked)
            self.result_cards.append(card)

        # Layout cards based on available width
        self._reorganize_grid()

        # Start loading cover URLs and thumbnails
        max_workers = self.config.get("ui.max_concurrent_downloads", DEFAULT_CONCURRENT_DOWNLOADS)
        self.thumb_worker = ThumbnailWorker(provider, results, self.cache, max_workers)
        self.thumb_worker.cover_url_ready.connect(self._on_cover_url_ready)
        self.thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.thumb_worker.progress.connect(self._on_thumbnail_progress)
        self.thumb_worker.finished.connect(self._on_thumbnails_finished)
        self.stop_btn.setVisible(True)
        # Show determinate progress bar for thumbnail loading
        self.progress_bar.setRange(0, len(results))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.thumb_worker.start()

    def _on_search_error(self, error: str):
        """Handle search error."""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        # User-friendly error message
        error_lower = error.lower()
        if "connection" in error_lower or "timeout" in error_lower:
            user_message = tr("Connection error. Check your internet connection.")
        elif "unauthorized" in error_lower or "401" in error:
            user_message = tr("Invalid or expired API key. Check your credentials in preferences.")
        elif "rate limit" in error_lower or "429" in error:
            user_message = tr("Too many requests. Please wait before trying again.")
        else:
            user_message = tr("API communication error:\n{error}").format(error=error)

        self.no_results_label.setText(user_message)
        self.no_results_label.setVisible(True)

        # Also show a message box for visibility
        QMessageBox.warning(self, tr("Search error"), user_message)

    def _on_cover_url_ready(self, index: int, url: str):
        """Handle cover URL loaded."""
        if index < len(self.result_cards):
            self.result_cards[index].set_has_cover(True)
            self.results[index].cover_url = url
            self.results[index].has_cover_art = True
            # If this is the currently selected card, enable the apply button
            if index == self.selected_index:
                self.apply_btn.setEnabled(True)

    def _on_thumbnail_ready(self, index: int, data: bytes, width: int, height: int):
        """Handle thumbnail loaded with metadata."""
        if index < len(self.result_cards):
            self.result_cards[index].set_thumbnail(data, width, height)
            # Cache the data for selection preview
            self._cached_cover_data[index] = data
            # Update result metadata
            if index < len(self.results):
                self.results[index].image_width = width
                self.results[index].image_height = height
                self.results[index].image_size_bytes = len(data)

    def _on_thumbnail_progress(self, completed: int, total: int):
        """Handle thumbnail loading progress update."""
        self.progress_bar.setValue(completed)

    def _on_thumbnails_finished(self):
        """Handle thumbnail loading completion or cancellation."""
        self.stop_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        # Reset to indeterminate mode for next search
        self.progress_bar.setRange(0, 0)

    def _stop_thumbnail_loading(self):
        """Stop the thumbnail loading worker and clear loading indicators."""
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.cancel()
            self.stop_btn.setVisible(False)
            # Stop all loading spinners on cards that haven't loaded yet
            for card in self.result_cards:
                if card.is_loading():
                    card.stop_loading()

    def _calculate_columns(self) -> int:
        """Calculate number of columns based on available width."""
        # Card width is 140px + 8px spacing
        card_width = 148
        # Get viewport width, with a minimum
        viewport_width = self.results_scroll.viewport().width()
        if viewport_width < card_width:
            return 1
        columns = max(1, viewport_width // card_width)
        return columns

    def _reorganize_grid(self):
        """Reorganize the grid layout based on current width."""
        if not self.result_cards:
            return

        columns = self._calculate_columns()

        # Remove all widgets from grid without deleting them
        for i in reversed(range(self.results_grid.count())):
            self.results_grid.itemAt(i).widget()
            self.results_grid.takeAt(i)

        # Re-add all cards with new layout
        for i, card in enumerate(self.result_cards):
            row = i // columns
            col = i % columns
            self.results_grid.addWidget(card, row, col)

    def eventFilter(self, watched, event):
        """Handle events from watched objects."""
        if (
            watched == self.results_scroll.viewport()
            and event.type() == QEvent.Type.Resize
            and self.result_cards
        ):
            # Reorganize grid when viewport is resized
            self._reorganize_grid()
        return super().eventFilter(watched, event)

    def _on_card_clicked(self, index: int):
        """Handle card click."""
        # Update selection
        if self.selected_index >= 0 and self.selected_index < len(self.result_cards):
            self.result_cards[self.selected_index].set_selected(False)

        self.selected_index = index
        self.result_cards[index].set_selected(True)

        # Show selection panel with animation
        self._show_selection_panel()

        # Update selection info
        result = self.results[index]
        info_lines = [
            f"<b>{result.artist}</b> - {result.album}",
            tr("Year: {year} | Score: {score}%").format(
                year=result.year or "?", score=result.score
            ),
        ]
        # Add image metadata if available
        if result.image_width and result.image_height:
            size_info = result.image_info_str
            if size_info:
                info_lines.append(tr("Image: {info}").format(info=size_info))
        self.selected_info.setText("<br>".join(info_lines))

        # Use cached data if available, otherwise download in background
        if index in self._cached_cover_data:
            self._update_selection_thumbnail(self._cached_cover_data[index])
        elif result.cover_url:
            # Show loading state
            self.selected_thumb.setText("...")
            # Download in background worker (non-blocking)
            # Use _active_provider to ensure consistency with search results
            self.preview_worker = CoverDownloadWorker(
                self._active_provider, index, result.cover_url, self.cache
            )
            self.preview_worker.download_ready.connect(self._on_preview_ready)
            self.preview_worker.download_error.connect(self._on_preview_error)
            self.preview_worker.start()

        self.apply_btn.setEnabled(result.has_cover_art)

    def _update_selection_thumbnail(self, data: bytes):
        """Update the selection thumbnail with image data."""
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(
                80,
                80,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.selected_thumb.setPixmap(scaled)

    def _on_preview_ready(self, index: int, data: bytes):
        """Handle preview download completion."""
        # Only update if still selected
        if index == self.selected_index:
            self._cached_cover_data[index] = data
            self._update_selection_thumbnail(data)

    def _on_preview_error(self, index: int, error: str):
        """Handle preview download error."""
        if index == self.selected_index:
            self.selected_thumb.setText("?")

    def _apply_selection(self):
        """Apply the selected cover."""
        if self.selected_index < 0 or self.selected_index >= len(self.results):
            return

        result = self.results[self.selected_index]
        if not result.cover_url:
            QMessageBox.warning(self, tr("Error"), tr("This cover is not available."))
            return

        # Use cached data if available
        if self.selected_index in self._cached_cover_data:
            cover_data = self._cached_cover_data[self.selected_index]
            self.cover_selected.emit(cover_data, result)
            self.accept()
            return

        # Download full cover in background (non-blocking)
        self.progress_bar.setVisible(True)
        self.apply_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        # Use _active_provider to ensure consistency with search results
        self._apply_worker = CoverDownloadWorker(
            self._active_provider, self.selected_index, result.cover_url, self.cache
        )
        self._apply_worker.download_ready.connect(self._on_apply_download_ready)
        self._apply_worker.download_error.connect(self._on_apply_download_error)
        self._apply_worker.start()

    def _on_apply_download_ready(self, index: int, data: bytes):
        """Handle successful download for apply action."""
        self.progress_bar.setVisible(False)
        self.apply_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

        if index == self.selected_index and index < len(self.results):
            result = self.results[index]
            self._cached_cover_data[index] = data
            self.cover_selected.emit(data, result)
            self.accept()

    def _on_apply_download_error(self, index: int, error: str):
        """Handle download error for apply action."""
        self.progress_bar.setVisible(False)
        self.apply_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

        QMessageBox.critical(
            self, tr("Error"), tr("Error downloading cover:\n{error}").format(error=error)
        )

    def _disconnect_workers(self):
        """Safely disconnect signals from all workers."""
        # Suppress Qt warnings about failed disconnects (expected when signals already processed)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*disconnect.*")

            if self.search_worker:
                with contextlib.suppress(RuntimeError, TypeError):
                    self.search_worker.results_ready.disconnect(self._on_results_ready)
                with contextlib.suppress(RuntimeError, TypeError):
                    self.search_worker.error.disconnect(self._on_search_error)
                with contextlib.suppress(RuntimeError, TypeError):
                    self.search_worker.status_update.disconnect(self._on_status_update)
                with contextlib.suppress(RuntimeError, TypeError):
                    self.search_worker.connection_status.disconnect(self._on_connection_status)

            if self.thumb_worker:
                with contextlib.suppress(RuntimeError, TypeError):
                    self.thumb_worker.cover_url_ready.disconnect(self._on_cover_url_ready)
                with contextlib.suppress(RuntimeError, TypeError):
                    self.thumb_worker.thumbnail_ready.disconnect(self._on_thumbnail_ready)
                with contextlib.suppress(RuntimeError, TypeError):
                    self.thumb_worker.progress.disconnect(self._on_thumbnail_progress)
                with contextlib.suppress(RuntimeError, TypeError):
                    self.thumb_worker.finished.disconnect(self._on_thumbnails_finished)

            if self.preview_worker:
                with contextlib.suppress(RuntimeError, TypeError):
                    self.preview_worker.download_ready.disconnect(self._on_preview_ready)
                with contextlib.suppress(RuntimeError, TypeError):
                    self.preview_worker.download_error.disconnect(self._on_preview_error)

            if self._apply_worker:
                with contextlib.suppress(RuntimeError, TypeError):
                    self._apply_worker.download_ready.disconnect(self._on_apply_download_ready)
                with contextlib.suppress(RuntimeError, TypeError):
                    self._apply_worker.download_error.disconnect(self._on_apply_download_error)

            if self._fingerprint_worker:
                with contextlib.suppress(RuntimeError, TypeError):
                    self._fingerprint_worker.identification_ready.disconnect(
                        self._on_fingerprint_ready
                    )
                with contextlib.suppress(RuntimeError, TypeError):
                    self._fingerprint_worker.error.disconnect(self._on_fingerprint_error)
                with contextlib.suppress(RuntimeError, TypeError):
                    self._fingerprint_worker.status_update.disconnect(self._on_status_update)

            if self._batch_fingerprint_worker:
                with contextlib.suppress(RuntimeError, TypeError):
                    self._batch_fingerprint_worker.batch_ready.disconnect(
                        self._on_batch_fingerprint_ready
                    )
                with contextlib.suppress(RuntimeError, TypeError):
                    self._batch_fingerprint_worker.progress.disconnect(self._on_batch_progress)
                with contextlib.suppress(RuntimeError, TypeError):
                    self._batch_fingerprint_worker.error.disconnect(self._on_fingerprint_error)
                with contextlib.suppress(RuntimeError, TypeError):
                    self._batch_fingerprint_worker.status_update.disconnect(self._on_status_update)

    def _cleanup_workers(self):
        """Stop and cleanup all running worker threads."""
        # First disconnect signals
        self._disconnect_workers()

        # Cancel thumbnail worker gracefully
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.cancel()

        # Then wait/terminate workers
        workers = [
            self.search_worker,
            self.thumb_worker,
            self.preview_worker,
            self._apply_worker,
            self._fingerprint_worker,
            self._batch_fingerprint_worker,
        ]
        for worker in workers:
            if worker and worker.isRunning():
                worker.wait(1000)
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(500)  # Wait for termination to complete

    def showEvent(self, event):
        """Handle show event - auto-start fingerprinting if requested."""
        super().showEvent(event)
        if self._auto_fingerprint:
            self._auto_fingerprint = False  # Only trigger once
            # Use a short delay to let the dialog fully render first
            from PySide6.QtCore import QTimer

            QTimer.singleShot(100, self._start_fingerprint)

    def closeEvent(self, event):
        """Handle close event - save size, preferences, and cleanup threads."""
        # Save window size
        self.config.set("ui.search_dialog_width", self.width())
        self.config.set("ui.search_dialog_height", self.height())

        # Save checkbox states
        self.config.set("search.use_artist", self.artist_check.isChecked())
        self.config.set("search.use_album", self.album_check.isChecked())
        self.config.set("search.use_year", self.year_check.isChecked())
        self.config.set("search.use_title", self.title_check.isChecked())
        self.config.set("search.use_isrc", self.isrc_check.isChecked())
        self.config.set("search.use_barcode", self.barcode_check.isChecked())
        self.config.save()

        self._cleanup_workers()
        super().closeEvent(event)

    def reject(self):
        """Handle dialog rejection - cleanup before closing."""
        self._cleanup_workers()
        super().reject()
