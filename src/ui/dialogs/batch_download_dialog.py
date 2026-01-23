"""
Batch download dialog for automatic cover fetching.

This dialog provides a non-blocking UI for batch downloading covers
with progress tracking, cancellation support, and detailed logging.
"""

import contextlib
import logging
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ...api.base import CoverProvider
from ...api.discogs import DiscogsProvider
from ...api.lastfm import LastFmProvider
from ...api.musicbrainz import MusicBrainzProvider
from ...core.cover_save_strategy import CoverSaveStrategy
from ...core.embedder import CoverEmbedder, detect_image_mime_type, get_extension_for_mime
from ...core.models import AlbumInfo, CoverStatus, SearchResult
from ...i18n import tr
from ...utils.cache import get_image_cache
from ...utils.config import Config
from ..widgets.toast_manager import ToastManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchDownloadResult:
    """Result of batch download operation."""

    downloaded: int = 0
    skipped_no_match: int = 0
    skipped_already_has: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


class BatchDownloadWorker(QThread):
    """Worker thread for batch downloading covers."""

    progress = Signal(int, int, str)  # current, total, album_name
    log_message = Signal(str)  # message for the log
    album_processed = Signal(AlbumInfo, bool, str)  # album, success, message
    finished_with_result = Signal(BatchDownloadResult)

    def __init__(
        self,
        albums: list[AlbumInfo],
        config: Config,
        min_score: int,
        parent=None,
    ):
        super().__init__(parent)
        self.albums = albums
        self.config = config
        self.min_score = min_score
        self.cache = get_image_cache(config)
        self._cancelled = False
        self._skipped = False

    def cancel(self):
        """Request cancellation of the batch operation."""
        self._cancelled = True

    def skip_current(self):
        """Request to skip the current album."""
        self._skipped = True

    def _create_providers(self) -> list[CoverProvider]:
        """Create enabled provider instances."""
        providers = []

        # Get global contact email for User-Agent
        contact_email = self.config.get("app.contact_email", "")

        # MusicBrainz is always available (no API key required)
        if self.config.get("providers.musicbrainz.enabled", True):
            providers.append(MusicBrainzProvider(contact_email=contact_email))

        # Discogs requires API token
        if self.config.get("providers.discogs.enabled", False):
            api_token = self.config.get("api.discogs_token")
            if api_token:
                providers.append(
                    DiscogsProvider(api_token=api_token, user_email=contact_email)
                )

        # Last.fm requires API key
        if self.config.get("providers.lastfm.enabled", False):
            api_key = self.config.get("api.lastfm_key")
            if api_key:
                providers.append(LastFmProvider(api_key=api_key, user_email=contact_email))

        return providers

    def run(self):
        """Execute the batch download operation."""
        result = BatchDownloadResult()
        providers = self._create_providers()

        if not providers:
            self.log_message.emit(tr("No cover provider enabled."))
            self.finished_with_result.emit(result)
            return

        try:
            preserve_timestamp = self.config.get("embedding.preserve_timestamp", True)
            embedder = CoverEmbedder(preserve_timestamp=preserve_timestamp)
            save_strategy = CoverSaveStrategy(self.config)
            total = len(self.albums)

            provider_names = ", ".join(p.name for p in providers)
            self.log_message.emit(
                tr("Enabled providers: {providers}").format(providers=provider_names)
            )
            self.log_message.emit(tr("Minimum score: {score}%").format(score=self.min_score))
            self.log_message.emit("-" * 40)

            for i, album in enumerate(self.albums):
                if self._cancelled:
                    self.log_message.emit(tr("Operation cancelled by user."))
                    break

                # Reset skip flag for this album
                self._skipped = False

                self.progress.emit(i + 1, total, album.display_name)
                self.log_message.emit(f"\n[{i + 1}/{total}] {album.display_name}")

                # Skip albums that already have covers
                if album.cover_status != CoverStatus.NONE:
                    self.log_message.emit("  → " + tr("Skipped (already has cover)"))
                    result.skipped_already_has += 1
                    self.album_processed.emit(album, False, tr("Already has cover"))
                    continue

                # Check if skip was requested during processing
                if self._skipped:
                    self.log_message.emit("  → " + tr("Skipped by user"))
                    result.skipped_no_match += 1
                    self.album_processed.emit(album, False, tr("Skipped"))
                    continue

                # Try each provider until we find a match
                cover_applied = False
                for provider in providers:
                    if self._cancelled or self._skipped:
                        break

                    try:
                        best_result, cover_data = self._search_and_download(
                            provider, album, embedder
                        )

                        if best_result and cover_data:
                            # Apply cover
                            decision = save_strategy.evaluate(album)
                            if not decision.is_valid:
                                self.log_message.emit(
                                    "  → " + tr("Error: invalid save configuration")
                                )
                                continue

                            self._apply_cover(album, cover_data, best_result, decision, embedder)
                            cover_applied = True
                            result.downloaded += 1
                            self.log_message.emit(
                                "  → "
                                + tr("Cover applied ({provider}, score: {score}%)").format(
                                    provider=provider.name, score=best_result.score
                                )
                            )
                            self.album_processed.emit(album, True, tr("Cover applied"))
                            break

                    except Exception as e:
                        self.log_message.emit(
                            "  → "
                            + tr("Error ({provider}): {error}").format(
                                provider=provider.name, error=e
                            )
                        )
                        logger.exception(f"Error processing {album.display_name}")

                if not cover_applied and not self._cancelled and not self._skipped:
                    self.log_message.emit("  → " + tr("No sufficient result found"))
                    result.skipped_no_match += 1
                    self.album_processed.emit(album, False, tr("No match"))

            # Final summary
            self.log_message.emit("\n" + "=" * 40)
            self.log_message.emit(tr("Summary:"))
            self.log_message.emit(
                "  " + tr("Covers downloaded: {count}").format(count=result.downloaded)
            )
            self.log_message.emit(
                "  " + tr("Skipped (no match): {count}").format(count=result.skipped_no_match)
            )
            self.log_message.emit(
                "  "
                + tr("Skipped (already have cover): {count}").format(
                    count=result.skipped_already_has
                )
            )
            if result.errors > 0:
                self.log_message.emit("  " + tr("Errors: {count}").format(count=result.errors))

        finally:
            # Clean up provider resources (HTTP sessions)
            for provider in providers:
                with contextlib.suppress(Exception):
                    provider.close()

        self.finished_with_result.emit(result)

    def _search_and_download(
        self,
        provider: CoverProvider,
        album: AlbumInfo,
        embedder: CoverEmbedder,
    ) -> tuple:
        """
        Search for and download cover art for an album.

        Returns:
            Tuple of (SearchResult, cover_data) or (None, None) if no match found
        """
        best_result = None
        best_score = 0

        # Strategy 1: Direct lookup by MBID (most reliable)
        if album.musicbrainz_albumid and isinstance(provider, MusicBrainzProvider):
            self.log_message.emit(
                "  " + tr("MBID lookup on {provider}...").format(provider=provider.name)
            )
            result = provider.lookup_by_mbid(album.musicbrainz_albumid)
            if result:
                # MBID lookup is always a perfect match
                best_result = result
                best_score = 100

        # Strategy 2: Text search (fallback)
        if not best_result and (album.artist or album.album):
            self.log_message.emit(
                "  " + tr("Text search on {provider}...").format(provider=provider.name)
            )
            results = provider.search(
                album.artist or "",
                album.album or "",
                album.year,
            )

            for result in results:
                if self._cancelled or self._skipped:
                    return None, None

                score = provider.calculate_match_score(
                    album.artist or "",
                    album.album or "",
                    album.year,
                    result,
                )

                # Use the provider's score if higher
                effective_score = max(score, result.score)
                if effective_score > best_score:
                    best_score = effective_score
                    best_result = result

        # Check if best result meets minimum score threshold
        if not best_result or best_score < self.min_score:
            return None, None

        # Get cover URL
        cover_url = best_result.cover_url
        if not cover_url:
            cover_url = provider.get_cover_url(best_result)
            if not cover_url:
                return None, None

        # Download cover
        cover_data = self.cache.get(cover_url)
        if cover_data is None:
            cover_data = provider.download_cover(cover_url)
            if cover_data:
                self.cache.set(cover_url, cover_data)

        if not cover_data:
            return None, None

        return best_result, cover_data

    def _apply_cover(
        self,
        album: AlbumInfo,
        cover_data: bytes,
        result: SearchResult,
        decision,
        embedder: CoverEmbedder,
    ):
        """Apply cover to album using the save strategy."""
        mime_type = detect_image_mime_type(cover_data)
        extension = get_extension_for_mime(mime_type)
        filename = f"{decision.external_filename}{extension}"

        # Handle single file vs folder albums
        is_single_file = album.path.is_file()
        target_folder = album.path.parent if is_single_file else album.path

        # Save to folder if enabled
        if decision.save_external_file:
            embedder.save_cover_to_folder(cover_data, target_folder, filename)
            album.cover.has_folder = True
            album.cover.folder_file = filename
            album.cover.folder_path = target_folder / filename

        # Embed in tags if enabled
        if decision.embed_in_tags:
            if is_single_file:
                embedder.embed_cover_in_file(album.path, cover_data, mime_type)
            else:
                embedder.embed_cover_in_folder(cover_data, album.path, mime_type)
            album.cover.has_embedded = True


class BatchDownloadDialog(QDialog):
    """
    Dialog for batch downloading covers with progress tracking.

    Shows:
    - Current album being processed
    - Progress bar
    - Skip/Cancel buttons
    - Log of actions taken
    """

    cover_applied = Signal(AlbumInfo)

    def __init__(
        self,
        albums: list[AlbumInfo],
        config: Config,
        parent=None,
    ):
        super().__init__(parent)
        self.albums = albums
        self.config = config
        self.worker: BatchDownloadWorker | None = None
        self._result: BatchDownloadResult | None = None

        self._setup_ui()
        self._start_batch()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle(tr("Automatic cover download"))
        self.setMinimumSize(500, 400)
        self.resize(600, 500)

        layout = QVBoxLayout(self)

        # Progress section
        progress_group = QGroupBox(tr("Progress"))
        progress_layout = QVBoxLayout(progress_group)

        self.current_album_label = QLabel(tr("Preparing..."))
        self.current_album_label.setWordWrap(True)
        progress_layout.addWidget(self.current_album_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(self.albums))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m")
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(progress_group)

        # Log section
        log_group = QGroupBox(tr("Log"))
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: monospace; font-size: 11px;")
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group, 1)  # Take remaining space

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.skip_btn = QPushButton(tr("Skip"))
        self.skip_btn.setToolTip(tr("Skip to next album"))
        self.skip_btn.clicked.connect(self._skip_current)
        button_layout.addWidget(self.skip_btn)

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self._cancel)
        button_layout.addWidget(self.cancel_btn)

        self.close_btn = QPushButton(tr("Close"))
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setEnabled(False)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _start_batch(self):
        """Start the batch download operation."""
        min_score = self.config.get("search.min_auto_score", 95)

        self.worker = BatchDownloadWorker(
            self.albums,
            self.config,
            min_score,
            parent=self,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._on_log_message)
        self.worker.album_processed.connect(self._on_album_processed)
        self.worker.finished_with_result.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, current: int, total: int, album_name: str):
        """Handle progress update."""
        self.progress_bar.setValue(current)
        self.current_album_label.setText(
            tr("Album {current}/{total}: {name}").format(
                current=current, total=total, name=album_name
            )
        )

    def _on_log_message(self, message: str):
        """Handle log message."""
        self.log_text.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_album_processed(self, album: AlbumInfo, success: bool, message: str):
        """Handle album processing completion."""
        if success:
            self.cover_applied.emit(album)

    def _on_finished(self, result: BatchDownloadResult):
        """Handle batch completion."""
        self._result = result

        # Update UI
        self.skip_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self.current_album_label.setText(tr("Finished"))

        # Show summary dialog
        self._show_summary(result)

    def _skip_current(self):
        """Skip the current album."""
        if self.worker and self.worker.isRunning():
            self.worker.skip_current()

    def _cancel(self):
        """Cancel the batch operation."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(tr("Cancelling..."))

    def _show_summary(self, result: BatchDownloadResult):
        """Show summary dialog."""
        summary_lines = [
            tr("Covers downloaded: {count}").format(count=result.downloaded),
            tr("Albums skipped (no match): {count}").format(count=result.skipped_no_match),
            tr("Albums skipped (already have cover): {count}").format(
                count=result.skipped_already_has
            ),
        ]

        if result.errors > 0:
            summary_lines.append(tr("Errors: {count}").format(count=result.errors))

        # Show toast summary (use comma separator instead of newlines for toast)
        summary = " | ".join(summary_lines)
        ToastManager.get_instance().show_success(summary)

    def _disconnect_worker(self):
        """Safely disconnect signals from worker."""
        if self.worker:
            with contextlib.suppress(RuntimeError, TypeError):
                self.worker.progress.disconnect(self._on_progress)
            with contextlib.suppress(RuntimeError, TypeError):
                self.worker.log_message.disconnect(self._on_log_message)
            with contextlib.suppress(RuntimeError, TypeError):
                self.worker.album_processed.disconnect(self._on_album_processed)
            with contextlib.suppress(RuntimeError, TypeError):
                self.worker.finished_with_result.disconnect(self._on_finished)

    def closeEvent(self, event):
        """Handle close event - cleanup worker thread."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
            if self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(500)

        self._disconnect_worker()
        super().closeEvent(event)

    def reject(self):
        """Handle dialog rejection."""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                tr("Cancel download"),
                tr("A download is in progress. Do you want to cancel it?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._cancel()
                self.worker.wait(3000)
            else:
                return

        super().reject()
