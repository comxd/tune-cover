"""
Batch AcoustID identification dialog.

This dialog provides a non-blocking UI for batch identifying albums
via audio fingerprinting with progress tracking, cancellation support,
and detailed logging.
"""

import logging
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ...core.models import AlbumInfo
from ...i18n import tr
from ...utils.acoustid_tags import (
    save_acoustid_to_folder,
    update_metadata_in_folder,
)
from ...utils.config import Config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchAcoustIdResult:
    """Result of batch AcoustID identification operation."""

    identified: int = 0
    saved: int = 0
    no_match: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


class BatchAcoustIdWorker(QThread):
    """Worker thread for batch AcoustID identification."""

    progress = Signal(int, int, str)  # current, total, album_name
    log_message = Signal(str)  # message for the log
    album_processed = Signal(AlbumInfo, bool, str, str)  # album, success, message, acoustid
    finished_with_result = Signal(BatchAcoustIdResult)

    def __init__(
        self,
        albums: list[AlbumInfo],
        config: Config,
        save_to_tags: bool = True,
        update_metadata: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.albums = albums
        self.config = config
        self.save_to_tags = save_to_tags
        self.update_metadata = update_metadata
        self._cancelled = False
        self._skipped = False

    def cancel(self):
        """Request cancellation of the batch operation."""
        self._cancelled = True

    def skip_current(self):
        """Request to skip the current album."""
        self._skipped = True

    def run(self):
        """Execute the batch AcoustID identification operation."""
        result = BatchAcoustIdResult()

        try:
            from ...core.fingerprint import BatchFingerprinter

            fingerprinter = BatchFingerprinter()
            if not fingerprinter.is_available:
                self.log_message.emit(tr("Error: fpcalc not found"))
                self.finished_with_result.emit(result)
                return
        except ImportError as e:
            self.log_message.emit(tr("Error: {error}").format(error=str(e)))
            self.finished_with_result.emit(result)
            return

        total = len(self.albums)
        self.log_message.emit(tr("Starting batch AcoustID identification..."))
        self.log_message.emit(tr("Albums to process: {count}").format(count=total))
        self.log_message.emit("-" * 40)

        for i, album in enumerate(self.albums):
            if self._cancelled:
                self.log_message.emit(tr("Operation cancelled by user."))
                break

            # Reset skip flag for this album
            self._skipped = False

            self.progress.emit(i + 1, total, album.display_name)
            self.log_message.emit(f"\n[{i + 1}/{total}] {album.display_name}")

            # Skip albums that already have AcoustID
            if album.acoustid:
                self.log_message.emit("  → " + tr("Skipped (already has AcoustID)"))
                self.album_processed.emit(album, False, tr("Already has AcoustID"), "")
                continue

            # Check if skip was requested during processing
            if self._skipped:
                self.log_message.emit("  → " + tr("Skipped by user"))
                result.no_match += 1
                self.album_processed.emit(album, False, tr("Skipped"), "")
                continue

            # Find a sample file to fingerprint
            sample_file = album.sample_file
            if not sample_file or not sample_file.exists():
                self.log_message.emit("  → " + tr("No audio file found"))
                result.errors += 1
                result.error_messages.append(f"{album.display_name}: No audio file")
                self.album_processed.emit(album, False, tr("No audio file"), "")
                continue

            try:
                # Generate fingerprint
                self.log_message.emit("  " + tr("Generating fingerprint..."))
                fp_result = fingerprinter.fingerprint_file(sample_file)

                if not fp_result or not fp_result.get("fingerprint"):
                    self.log_message.emit("  → " + tr("Failed to generate fingerprint"))
                    result.errors += 1
                    result.error_messages.append(f"{album.display_name}: Fingerprint failed")
                    self.album_processed.emit(album, False, tr("Fingerprint failed"), "")
                    continue

                # Look up in AcoustID database
                self.log_message.emit("  " + tr("Looking up in AcoustID database..."))
                lookup_result = fingerprinter.lookup_acoustid(
                    fp_result["fingerprint"],
                    fp_result["duration"],
                )

                if not lookup_result or not lookup_result.get("acoustid"):
                    self.log_message.emit("  → " + tr("No match found in AcoustID"))
                    result.no_match += 1
                    self.album_processed.emit(album, False, tr("No match"), "")
                    continue

                acoustid = lookup_result["acoustid"]
                score = lookup_result.get("score", 0)
                artist = lookup_result.get("artist")
                album_name = lookup_result.get("album")

                self.log_message.emit(
                    "  ✓ "
                    + tr("Found: {artist} - {album} (score: {score}%)").format(
                        artist=artist or "?",
                        album=album_name or "?",
                        score=int(score * 100) if score else "?",
                    )
                )

                result.identified += 1

                # Save to tags if requested
                if self.save_to_tags and album.path.is_dir():
                    saved_count = save_acoustid_to_folder(album.path, acoustid)
                    if saved_count > 0:
                        self.log_message.emit(
                            "  ✓ " + tr("Saved AcoustID to {count} files").format(count=saved_count)
                        )
                        result.saved += 1
                        album.acoustid = acoustid

                        # Update metadata if requested
                        if self.update_metadata and (artist or album_name):
                            updated = update_metadata_in_folder(
                                album.path,
                                artist=artist,
                                album=album_name,
                            )
                            if updated > 0:
                                self.log_message.emit(
                                    "  ✓ "
                                    + tr("Updated metadata in {count} files").format(count=updated)
                                )
                                if artist:
                                    album.artist = artist
                                if album_name:
                                    album.album = album_name

                self.album_processed.emit(
                    album,
                    True,
                    tr("Identified: {artist} - {album}").format(
                        artist=artist or "?", album=album_name or "?"
                    ),
                    acoustid,
                )

            except Exception as e:
                error_msg = str(e)
                self.log_message.emit("  → " + tr("Error: {error}").format(error=error_msg))
                result.errors += 1
                result.error_messages.append(f"{album.display_name}: {error_msg}")
                self.album_processed.emit(album, False, tr("Error"), "")

        self.log_message.emit("\n" + "-" * 40)
        self.log_message.emit(tr("Batch identification complete."))
        self.log_message.emit(
            tr(
                "Identified: {identified}, Saved: {saved}, No match: {no_match}, Errors: {errors}"
            ).format(
                identified=result.identified,
                saved=result.saved,
                no_match=result.no_match,
                errors=result.errors,
            )
        )

        self.finished_with_result.emit(result)


class BatchAcoustIdDialog(QDialog):
    """
    Dialog for batch AcoustID identification.

    Provides progress tracking, log output, and cancellation support.
    """

    album_updated = Signal(AlbumInfo)  # Emitted when an album's AcoustID is saved

    def __init__(
        self,
        albums: list[AlbumInfo],
        config: Config,
        parent=None,
    ):
        super().__init__(parent)
        self.albums = albums
        self.config = config
        self.worker: BatchAcoustIdWorker | None = None
        self.result: BatchAcoustIdResult | None = None

        self._setup_ui()
        self.setWindowTitle(tr("Batch AcoustID Identification"))
        self.setMinimumSize(600, 450)

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Options group
        options_group = QGroupBox(tr("Options"))
        options_layout = QVBoxLayout(options_group)

        self.save_tags_cb = QCheckBox(tr("Save AcoustID to audio file tags"))
        self.save_tags_cb.setChecked(True)
        options_layout.addWidget(self.save_tags_cb)

        self.update_metadata_cb = QCheckBox(tr("Update artist/album tags from identification"))
        self.update_metadata_cb.setChecked(False)
        self.update_metadata_cb.setToolTip(
            tr("If enabled, artist and album tags will be updated from AcoustID results")
        )
        options_layout.addWidget(self.update_metadata_cb)

        layout.addWidget(options_group)

        # Progress section
        progress_group = QGroupBox(tr("Progress"))
        progress_layout = QVBoxLayout(progress_group)

        # Current album label
        self.current_label = QLabel(tr("Ready to start"))
        progress_layout.addWidget(self.current_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(len(self.albums))
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(progress_group)

        # Log section
        log_group = QGroupBox(tr("Log"))
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group, 1)

        # Buttons
        button_layout = QHBoxLayout()

        self.skip_btn = QPushButton(tr("Skip"))
        self.skip_btn.setEnabled(False)
        self.skip_btn.clicked.connect(self._skip_current)
        button_layout.addWidget(self.skip_btn)

        button_layout.addStretch()

        self.start_btn = QPushButton(tr("Start"))
        self.start_btn.clicked.connect(self._start_batch)
        button_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self._cancel_or_close)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

    def _start_batch(self):
        """Start the batch identification process."""
        self.start_btn.setEnabled(False)
        self.skip_btn.setEnabled(True)
        self.save_tags_cb.setEnabled(False)
        self.update_metadata_cb.setEnabled(False)

        self.worker = BatchAcoustIdWorker(
            albums=self.albums,
            config=self.config,
            save_to_tags=self.save_tags_cb.isChecked(),
            update_metadata=self.update_metadata_cb.isChecked(),
            parent=self,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._on_log_message)
        self.worker.album_processed.connect(self._on_album_processed)
        self.worker.finished_with_result.connect(self._on_finished)
        self.worker.start()

    def _skip_current(self):
        """Skip the current album."""
        if self.worker:
            self.worker.skip_current()

    def _cancel_or_close(self):
        """Cancel the operation or close the dialog."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)  # Wait up to 2 seconds
        self.reject()

    def _on_progress(self, current: int, total: int, album_name: str):
        """Handle progress update."""
        self.progress_bar.setValue(current)
        self.current_label.setText(
            tr("Processing {current}/{total}: {name}").format(
                current=current, total=total, name=album_name
            )
        )

    def _on_log_message(self, message: str):
        """Handle log message."""
        self.log_text.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_album_processed(self, album: AlbumInfo, success: bool, message: str, acoustid: str):
        """Handle album processing completion."""
        if success and acoustid:
            self.album_updated.emit(album)

    def _on_finished(self, result: BatchAcoustIdResult):
        """Handle batch completion."""
        self.result = result
        self.start_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.cancel_btn.setText(tr("Close"))
        self.current_label.setText(tr("Complete"))

        # Show summary
        from ..widgets.toast_manager import ToastManager

        if result.identified > 0:
            ToastManager.get_instance().show_success(
                tr("{count} albums identified via AcoustID").format(count=result.identified)
            )

    def closeEvent(self, event):
        """Handle close event."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        super().closeEvent(event)
