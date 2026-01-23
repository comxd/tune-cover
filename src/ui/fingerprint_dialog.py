"""
Fingerprint results dialog for user selection.

This dialog displays aggregated fingerprint results and allows
the user to select the correct album match or scan additional tracks.
"""

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr

if TYPE_CHECKING:
    from ..core.fingerprint_batch import AggregatedResult, BatchFingerprintResult
    from ..core.models import AlbumInfo

logger = logging.getLogger(__name__)

# Cover thumbnail size in pixels
COVER_THUMBNAIL_SIZE = 80


class CoverFetchWorker(QObject):
    """Worker to fetch cover art in background."""

    cover_ready = Signal(str, bytes)  # mbid, image_data
    error = Signal(str, str)  # mbid, error_message
    finished = Signal()

    def __init__(self, mbids: list[str]):
        super().__init__()
        self.mbids = mbids
        self._should_stop = False

    def stop(self):
        """Stop the worker."""
        self._should_stop = True

    def run(self):
        """Fetch covers for all MBIDs."""
        try:
            from ..api.musicbrainz import MusicBrainzProvider

            provider = MusicBrainzProvider()

            for mbid in self.mbids:
                if self._should_stop:
                    break

                try:
                    # Get cover URL
                    url = provider.get_cover_url_direct(mbid)
                    if url:
                        # Download the image
                        data = provider.download_cover(url)
                        if data:
                            self.cover_ready.emit(mbid, data)
                        else:
                            self.error.emit(mbid, "Download failed")
                    else:
                        self.error.emit(mbid, "No cover found")
                except Exception as e:
                    logger.debug(f"Error fetching cover for {mbid}: {e}")
                    self.error.emit(mbid, str(e))

        except Exception as e:
            logger.error(f"CoverFetchWorker error: {e}")
        finally:
            self.finished.emit()


class ClickableCoverLabel(QLabel):
    """A label that displays a cover thumbnail and shows full size on click."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setFixedSize(COVER_THUMBNAIL_SIZE, COVER_THUMBNAIL_SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            ClickableCoverLabel {
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 4px;
            }
            ClickableCoverLabel:hover {
                border-color: #666;
            }
            ClickableCoverLabel[coverState="loading"] {
                color: #888;
                font-size: 10px;
            }
            ClickableCoverLabel[coverState="nocover"] {
                color: #666;
                font-size: 9px;
            }
        """)
        self._set_placeholder()

    def _set_placeholder(self):
        """Set placeholder text with loading state."""
        self.setText(tr("Loading..."))
        self.setProperty("coverState", "loading")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_cover(self, pixmap: QPixmap):
        """Set the cover image."""
        self._pixmap = pixmap
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                COVER_THUMBNAIL_SIZE,
                COVER_THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            super().setPixmap(scaled)
            self._reset_cover_state()
        else:
            self._set_no_cover()

    def set_cover_from_data(self, data: bytes):
        """Load and set cover from raw data."""
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self.set_cover(pixmap)

    def _set_no_cover(self):
        """Set no cover placeholder with nocover state."""
        self._pixmap = None
        self.clear()
        self.setText(tr("No cover"))
        self.setProperty("coverState", "nocover")
        self.style().unpolish(self)
        self.style().polish(self)

    def _reset_cover_state(self):
        """Reset cover state when a cover is loaded."""
        self.setProperty("coverState", "")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        """Handle mouse press to open zoom dialog."""
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap:
            self.clicked.emit()
            self._show_zoom_dialog()
        super().mousePressEvent(event)

    def _show_zoom_dialog(self):
        """Show the zoom dialog."""
        if not self._pixmap or self._pixmap.isNull():
            return

        from .widgets.cover_preview import ZoomDialog

        dialog = ZoomDialog(self._pixmap, self.window())
        dialog.exec()


class ResultItemWidget(QFrame):
    """Widget displaying a single fingerprint result with vote count and cover."""

    # Signal emitted when user clicks "Use this cover" button
    # Emits (AggregatedResult, cover_data_bytes)
    cover_use_requested = Signal(object, bytes)

    def __init__(
        self,
        result: "AggregatedResult",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.result = result
        self._cover_label: ClickableCoverLabel | None = None
        self._cover_data: bytes | None = None
        self._use_cover_btn: QPushButton | None = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the result item UI."""
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            ResultItemWidget {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 8px;
            }
            ResultItemWidget:hover {
                background-color: palette(alternateBase);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Radio button for selection
        self.radio = QRadioButton()
        layout.addWidget(self.radio)

        # Cover thumbnail
        self._cover_label = ClickableCoverLabel()
        layout.addWidget(self._cover_label)

        # Album info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        # Album/Title and artist
        album = self.result.album
        title = self.result.title
        artist = self.result.artist or tr("Unknown artist")
        year = f" ({self.result.year})" if self.result.year else ""

        # Log what we're displaying
        logger.info(f"[DIALOG] Displaying result: title={title!r}, album={album!r}")

        # For single track results, prioritize showing the track title
        # Show: Title (bold) if available, else Album (bold)
        # Then show Album on second line if we have both and they're different
        if title:
            # We have a track title - show it prominently
            title_label = QLabel(f"<b>{title}</b>")
            title_label.setWordWrap(True)
            info_layout.addWidget(title_label)

            # Show album separately if available and different from title
            if album and album.lower() != title.lower():
                album_label = QLabel(tr("Album: {album}{year}").format(album=album, year=year))
                album_label.setStyleSheet("color: #5dade2; font-size: 11px;")
                album_label.setWordWrap(True)
                info_layout.addWidget(album_label)
            elif year:
                # Just show year if no album or same as title
                year_label = QLabel(year.strip(" ()"))
                year_label.setStyleSheet("color: #888; font-size: 10px;")
                info_layout.addWidget(year_label)
        else:
            # No track title - show album as main display
            display_title = album or tr("Unknown album")
            title_label = QLabel(f"<b>{display_title}</b>{year}")
            title_label.setWordWrap(True)
            info_layout.addWidget(title_label)

        artist_label = QLabel(artist)
        artist_label.setStyleSheet("color: #666;")
        info_layout.addWidget(artist_label)

        # Matched tracks
        track_names = ", ".join(self.result.track_names[:5])
        if len(self.result.track_names) > 5:
            track_names += f" (+{len(self.result.track_names) - 5})"

        tracks_label = QLabel(tr("Matched tracks: {tracks}").format(tracks=track_names))
        tracks_label.setStyleSheet("color: #888; font-size: 11px;")
        tracks_label.setWordWrap(True)
        info_layout.addWidget(tracks_label)

        layout.addLayout(info_layout, 1)

        # Vote count badge
        vote_layout = QVBoxLayout()
        vote_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        vote_count = self.result.vote_count
        vote_label = QLabel(f"<b>{vote_count}</b>")
        vote_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vote_label.setStyleSheet("""
            background-color: #4CAF50;
            color: white;
            border-radius: 12px;
            padding: 4px 12px;
            font-size: 14px;
        """)
        vote_label.setToolTip(tr("{count} track(s) matched this release").format(count=vote_count))
        vote_layout.addWidget(vote_label)

        # Average score
        score_pct = int(self.result.average_score * 100)
        score_label = QLabel(tr("{score}% match").format(score=score_pct))
        score_label.setStyleSheet("color: #888; font-size: 10px;")
        score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vote_layout.addWidget(score_label)

        # "Use this cover" button (hidden by default, shown when cover is loaded)
        self._use_cover_btn = QPushButton(tr("Use this cover"))
        self._use_cover_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #1565C0;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        self._use_cover_btn.setToolTip(tr("Apply this cover directly without searching"))
        self._use_cover_btn.setVisible(False)
        self._use_cover_btn.clicked.connect(self._on_use_cover_clicked)
        vote_layout.addWidget(self._use_cover_btn)

        layout.addLayout(vote_layout)

    def set_cover(self, data: bytes):
        """Set the cover image from data and enable the 'Use this cover' button."""
        self._cover_data = data
        if self._cover_label:
            self._cover_label.set_cover_from_data(data)
        if self._use_cover_btn:
            self._use_cover_btn.setVisible(True)

    def set_no_cover(self):
        """Set no cover placeholder."""
        self._cover_data = None
        if self._cover_label:
            self._cover_label._set_no_cover()
        if self._use_cover_btn:
            self._use_cover_btn.setVisible(False)

    def _on_use_cover_clicked(self):
        """Handle click on 'Use this cover' button."""
        if self._cover_data:
            self.cover_use_requested.emit(self.result, self._cover_data)


class FingerprintResultsDialog(QDialog):
    """
    Dialog for displaying and selecting fingerprint results.

    Shows aggregated results from batch fingerprinting with vote counts,
    allowing the user to select the correct match or scan more tracks.
    """

    # Signal emitted when user selects a result (metadata only)
    result_selected = Signal(object)  # AggregatedResult

    # Signal emitted when user wants to scan more tracks
    scan_more_requested = Signal()

    # Signal emitted when user clicks "None match"
    none_selected = Signal()

    # Signal emitted when user clicks "Use this cover" on a result
    # Emits (AggregatedResult, cover_data_bytes)
    cover_selected = Signal(object, bytes)

    def __init__(
        self,
        album: "AlbumInfo",
        batch_result: "BatchFingerprintResult",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.album = album
        self.batch_result = batch_result
        self._result_widgets: list[ResultItemWidget] = []
        self._button_group = QButtonGroup(self)
        self._scanning = False
        self._cover_thread: QThread | None = None
        self._cover_worker: CoverFetchWorker | None = None
        self._mbid_to_widget: dict[str, ResultItemWidget] = {}

        self._setup_ui()
        self._populate_results()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle(tr("Fingerprint Identification Results"))
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setMinimumHeight(450)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header with album info
        header = self._create_header()
        layout.addWidget(header)

        # Results scroll area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setFrameStyle(QFrame.Shape.NoFrame)

        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setSpacing(8)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.addStretch()

        self._scroll_area.setWidget(self._results_container)
        layout.addWidget(self._scroll_area, 1)

        # Progress bar (hidden by default)
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # No results message (hidden by default)
        self._no_results_label = QLabel(
            tr("No fingerprint matches found. Try scanning more tracks.")
        )
        self._no_results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_results_label.setStyleSheet("color: #888; padding: 20px;")
        self._no_results_label.setVisible(False)
        layout.addWidget(self._no_results_label)

        # Button bar
        button_layout = QHBoxLayout()

        # Scan more button
        remaining = len(self.batch_result.get_remaining_tracks([t.path for t in self.album.tracks]))
        self._scan_more_btn = QPushButton(
            tr("Scan {count} more tracks").format(count=min(3, remaining))
        )
        self._scan_more_btn.setEnabled(remaining > 0)
        self._scan_more_btn.clicked.connect(self._on_scan_more)
        button_layout.addWidget(self._scan_more_btn)

        button_layout.addStretch()

        # None match button
        self._none_match_btn = QPushButton(tr("None of these match"))
        self._none_match_btn.clicked.connect(self._on_none_match)
        button_layout.addWidget(self._none_match_btn)

        # Cancel button
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        # Select button
        self._select_btn = QPushButton(tr("Select"))
        self._select_btn.setDefault(True)
        self._select_btn.setEnabled(False)
        self._select_btn.clicked.connect(self._on_select)
        button_layout.addWidget(self._select_btn)

        layout.addLayout(button_layout)

    def _create_header(self) -> QWidget:
        """Create the header widget with album info and stats."""
        header = QWidget()
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 8)

        # Album name
        album_name = self.album.display_name
        album_label = QLabel(f"<b>{album_name}</b>")
        album_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(album_label)

        # Stats
        total = self.batch_result.total_tracks
        analyzed = self.batch_result.analyzed_tracks
        failed = self.batch_result.failed_tracks

        stats_text = tr("Analyzed: {analyzed}/{total} tracks").format(
            analyzed=analyzed, total=total
        )
        if failed > 0:
            stats_text += " • " + tr("{failed} failed").format(failed=failed)

        self._stats_label = QLabel(stats_text)
        self._stats_label.setStyleSheet("color: #666;")
        layout.addWidget(self._stats_label)

        # Separator
        separator = QFrame()
        separator.setFrameStyle(QFrame.Shape.HLine | QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        return header

    def _populate_results(self):
        """Populate the results list."""
        # Stop any running cover fetch
        self._stop_cover_fetch()

        # Clear existing
        for widget in self._result_widgets:
            self._results_layout.removeWidget(widget)
            widget.deleteLater()
        self._result_widgets.clear()
        self._mbid_to_widget.clear()

        # Remove stretch if present
        for i in range(self._results_layout.count()):
            item = self._results_layout.itemAt(i)
            if item.spacerItem():
                self._results_layout.removeItem(item)
                break

        if not self.batch_result.results:
            self._no_results_label.setVisible(True)
            self._select_btn.setEnabled(False)
            self._none_match_btn.setEnabled(False)
            return

        self._no_results_label.setVisible(False)
        self._none_match_btn.setEnabled(True)

        # Add result widgets
        mbids_to_fetch = []
        for i, result in enumerate(self.batch_result.results):
            widget = ResultItemWidget(result, self._results_container)
            widget.radio.toggled.connect(self._on_selection_changed)
            widget.cover_use_requested.connect(self._on_cover_use_requested)
            self._button_group.addButton(widget.radio, i)
            self._results_layout.insertWidget(self._results_layout.count(), widget)
            self._result_widgets.append(widget)

            # Track MBID for cover fetching
            if result.mbid:
                self._mbid_to_widget[result.mbid] = widget
                mbids_to_fetch.append(result.mbid)

            # Select first by default
            if i == 0:
                widget.radio.setChecked(True)

        # Add stretch at end
        self._results_layout.addStretch()

        # Start fetching covers
        if mbids_to_fetch:
            self._start_cover_fetch(mbids_to_fetch)

    def _start_cover_fetch(self, mbids: list[str]):
        """Start fetching covers in background."""
        self._cover_thread = QThread()
        self._cover_worker = CoverFetchWorker(mbids)
        self._cover_worker.moveToThread(self._cover_thread)

        self._cover_thread.started.connect(self._cover_worker.run)
        self._cover_worker.cover_ready.connect(self._on_cover_ready)
        self._cover_worker.error.connect(self._on_cover_error)
        self._cover_worker.finished.connect(self._on_cover_fetch_finished)

        self._cover_thread.start()

    def _stop_cover_fetch(self):
        """Stop any running cover fetch."""
        if self._cover_worker:
            self._cover_worker.stop()
        if self._cover_thread and self._cover_thread.isRunning():
            self._cover_thread.quit()
            if not self._cover_thread.wait(2000):
                logger.warning("Cover fetch thread did not stop gracefully, terminating")
                self._cover_thread.terminate()
                self._cover_thread.wait()

    def _on_cover_ready(self, mbid: str, data: bytes):
        """Handle cover ready from worker."""
        widget = self._mbid_to_widget.get(mbid)
        if widget:
            widget.set_cover(data)

    def _on_cover_error(self, mbid: str, error: str):
        """Handle cover fetch error."""
        widget = self._mbid_to_widget.get(mbid)
        if widget:
            widget.set_no_cover()
        logger.debug(f"Cover fetch error for {mbid}: {error}")

    def _on_cover_fetch_finished(self):
        """Handle cover fetch completion."""
        if self._cover_thread:
            self._cover_thread.quit()
            self._cover_thread.wait()
            self._cover_thread = None
            self._cover_worker = None

    def _on_selection_changed(self, checked: bool):
        """Handle radio button selection change."""
        if checked:
            self._select_btn.setEnabled(True)

    def _on_select(self):
        """Handle select button click."""
        checked_id = self._button_group.checkedId()
        if checked_id >= 0 and checked_id < len(self.batch_result.results):
            selected_result = self.batch_result.results[checked_id]
            self.result_selected.emit(selected_result)
            self.accept()

    def _on_cover_use_requested(self, result: "AggregatedResult", cover_data: bytes):
        """Handle 'Use this cover' button click from a result widget."""
        self.cover_selected.emit(result, cover_data)
        self.accept()

    def _on_none_match(self):
        """Handle none match button click."""
        self.none_selected.emit()
        self.reject()

    def _on_scan_more(self):
        """Handle scan more button click."""
        self._scanning = True
        self._scan_more_btn.setEnabled(False)
        self._select_btn.setEnabled(False)
        self._none_match_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat(tr("Scanning..."))
        self.scan_more_requested.emit()

    def update_results(self, new_result: "BatchFingerprintResult"):
        """Update the dialog with new batch results."""
        self.batch_result = new_result
        self._scanning = False

        # Update stats
        total = new_result.total_tracks
        analyzed = new_result.analyzed_tracks
        failed = new_result.failed_tracks

        stats_text = tr("Analyzed: {analyzed}/{total} tracks").format(
            analyzed=analyzed, total=total
        )
        if failed > 0:
            stats_text += " • " + tr("{failed} failed").format(failed=failed)

        self._stats_label.setText(stats_text)

        # Update scan more button
        remaining = len(new_result.get_remaining_tracks([t.path for t in self.album.tracks]))
        self._scan_more_btn.setText(tr("Scan {count} more tracks").format(count=min(3, remaining)))
        self._scan_more_btn.setEnabled(remaining > 0)

        # Hide progress
        self._progress_bar.setVisible(False)

        # Re-enable none match button
        self._none_match_btn.setEnabled(True)

        # Repopulate results
        self._populate_results()

    def update_progress(self, current: int, total: int, track_name: str):
        """Update the progress bar during scanning."""
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._progress_bar.setFormat(tr("Scanning: {track}").format(track=track_name))

    def get_selected_result(self) -> "AggregatedResult | None":
        """Get the currently selected result."""
        checked_id = self._button_group.checkedId()
        if checked_id >= 0 and checked_id < len(self.batch_result.results):
            return self.batch_result.results[checked_id]
        return None

    def closeEvent(self, event):
        """Handle dialog close."""
        self._stop_cover_fetch()
        super().closeEvent(event)

    def reject(self):
        """Handle dialog rejection."""
        self._stop_cover_fetch()
        super().reject()
