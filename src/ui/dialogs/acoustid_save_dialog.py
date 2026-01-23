"""
Dialog for confirming AcoustID save to audio file tags.
"""

import logging
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)

from ...i18n import tr

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AcoustIdSaveResult:
    """Result data from the AcoustID save dialog."""

    acoustid: str
    update_artist: bool = False
    artist: str | None = None
    update_album: bool = False
    album: str | None = None


class AcoustIdSaveDialog(QDialog):
    """
    Dialog to confirm saving an AcoustID to audio file tags.

    Shows the identified artist/album and confidence score,
    and asks user to confirm before modifying file tags.
    Optionally allows updating artist/album metadata from identification.
    """

    # Emits the AcoustID when approved (for backward compatibility)
    acoustid_approved = Signal(str)
    # Emits full result with metadata options
    save_requested = Signal(object)  # AcoustIdSaveResult

    def __init__(
        self,
        acoustid: str,
        artist: str | None = None,
        album: str | None = None,
        score: int | None = None,
        current_artist: str | None = None,
        current_album: str | None = None,
        parent=None,
    ):
        """
        Initialize the AcoustID save dialog.

        Args:
            acoustid: The AcoustID to save
            artist: Identified artist name (optional)
            album: Identified album name (optional)
            score: Confidence score as percentage (optional)
            current_artist: Current artist tag value (for comparison)
            current_album: Current album tag value (for comparison)
            parent: Parent widget
        """
        super().__init__(parent)
        self.acoustid = acoustid
        self.artist = artist
        self.album = album
        self.score = score
        self.current_artist = current_artist
        self.current_album = current_album

        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle(tr("Save AcoustID"))
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Title
        title_label = QLabel(tr("Save this AcoustID to the audio files?"))
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)

        # Info section
        info_layout = QFormLayout()
        info_layout.setSpacing(8)

        # Show identified metadata if available
        if self.artist:
            artist_label = QLabel(self.artist)
            artist_label.setStyleSheet("color: #5dade2;")
            info_layout.addRow(tr("Artist:"), artist_label)

        if self.album:
            album_label = QLabel(self.album)
            album_label.setStyleSheet("color: #5dade2;")
            info_layout.addRow(tr("Album:"), album_label)

        if self.score is not None:
            score_text = f"{self.score}%"
            if self.score >= 90:
                score_style = "color: #27ae60;"  # Green
            elif self.score >= 70:
                score_style = "color: #f39c12;"  # Orange
            else:
                score_style = "color: #e74c3c;"  # Red
            score_label = QLabel(score_text)
            score_label.setStyleSheet(score_style)
            info_layout.addRow(tr("Confidence:"), score_label)

        # AcoustID value (truncated for display)
        acoustid_display = self.acoustid
        if len(acoustid_display) > 40:
            acoustid_display = acoustid_display[:37] + "..."
        acoustid_label = QLabel(acoustid_display)
        acoustid_label.setStyleSheet("font-family: monospace; font-size: 10px; color: #888;")
        acoustid_label.setToolTip(self.acoustid)
        info_layout.addRow("AcoustID:", acoustid_label)

        layout.addLayout(info_layout)

        # Metadata update options (only if artist or album identified)
        if self.artist or self.album:
            metadata_group = QGroupBox(tr("Update metadata"))
            metadata_layout = QVBoxLayout(metadata_group)
            metadata_layout.setSpacing(8)

            # Artist checkbox
            if self.artist:
                self.update_artist_cb = QCheckBox(
                    tr("Update artist tag to: {artist}").format(artist=self.artist)
                )
                # Check by default if different from current
                if self.current_artist and self.current_artist != self.artist:
                    self.update_artist_cb.setChecked(True)
                    self.update_artist_cb.setToolTip(
                        tr("Current: {current}").format(current=self.current_artist)
                    )
                metadata_layout.addWidget(self.update_artist_cb)
            else:
                self.update_artist_cb = None

            # Album checkbox
            if self.album:
                self.update_album_cb = QCheckBox(
                    tr("Update album tag to: {album}").format(album=self.album)
                )
                # Check by default if different from current
                if self.current_album and self.current_album != self.album:
                    self.update_album_cb.setChecked(True)
                    self.update_album_cb.setToolTip(
                        tr("Current: {current}").format(current=self.current_album)
                    )
                metadata_layout.addWidget(self.update_album_cb)
            else:
                self.update_album_cb = None

            layout.addWidget(metadata_group)
        else:
            self.update_artist_cb = None
            self.update_album_cb = None

        # Warning message
        warning_label = QLabel(tr("This will modify the tags of the audio files."))
        warning_label.setStyleSheet("color: #e67e22; font-size: 11px;")
        layout.addWidget(warning_label)

        # Buttons
        button_box = QDialogButtonBox()
        self.save_btn = button_box.addButton(tr("Save"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_btn = button_box.addButton(tr("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)

        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)

        layout.addWidget(button_box)

    def _on_save(self):
        """Handle save button click."""
        # Build result with metadata options
        result = AcoustIdSaveResult(
            acoustid=self.acoustid,
            update_artist=self.update_artist_cb.isChecked() if self.update_artist_cb else False,
            artist=self.artist if self.update_artist_cb else None,
            update_album=self.update_album_cb.isChecked() if self.update_album_cb else False,
            album=self.album if self.update_album_cb else None,
        )

        # Emit both signals for backward compatibility
        self.acoustid_approved.emit(self.acoustid)
        self.save_requested.emit(result)
        self.accept()

    def get_result(self) -> AcoustIdSaveResult:
        """Get the dialog result after execution."""
        return AcoustIdSaveResult(
            acoustid=self.acoustid,
            update_artist=self.update_artist_cb.isChecked() if self.update_artist_cb else False,
            artist=self.artist,
            update_album=self.update_album_cb.isChecked() if self.update_album_cb else False,
            album=self.album,
        )
