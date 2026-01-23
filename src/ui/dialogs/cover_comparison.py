"""
Cover comparison dialog for before/after preview.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.cover_save_strategy import CoverSaveDecision
from ...core.models import AlbumInfo, SearchResult
from ...i18n import tr
from ..widgets.cover_preview import ZoomDialog
from ..widgets.image_info import ImageInfoLabel

logger = logging.getLogger(__name__)


class ClickableImageLabel(QLabel):
    """A QLabel that shows a zoom dialog when double-clicked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_original_pixmap(self, pixmap: QPixmap):
        """Store the original pixmap for zoom."""
        self._pixmap = pixmap

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double-click to show zoom dialog."""
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._pixmap
            and not self._pixmap.isNull()
        ):
            dialog = ZoomDialog(self._pixmap, self.window())
            dialog.exec()
        super().mouseDoubleClickEvent(event)


class CoverPanel(QFrame):
    """Panel displaying a cover image with metadata."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box)
        self._setup_ui(title)

    def _setup_ui(self, title: str):
        """Set up the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Title label
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self.title_label)

        # Cover image (clickable for zoom)
        self.cover_label = ClickableImageLabel()
        self.cover_label.setFixedSize(200, 200)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444; border-radius: 4px;"
        )
        self.cover_label.setToolTip(tr("Double-click to zoom"))
        layout.addWidget(self.cover_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Image info
        self.info_label = ImageInfoLabel()
        layout.addWidget(self.info_label)

        # Source info
        self.source_label = QLabel()
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_label.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(self.source_label)

    def set_cover_from_path(self, path: Path | None):
        """Load and display cover from a file path."""
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._set_pixmap(pixmap)
                # Get file size
                try:
                    size_bytes = path.stat().st_size
                    self.info_label.set_image_info(pixmap.width(), pixmap.height(), size_bytes)
                except OSError:
                    self.info_label.set_dimensions(pixmap.width(), pixmap.height())
                self.source_label.setText(path.name)
                return

        # No cover case
        self.cover_label.setText(tr("No cover"))
        self.cover_label.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444; border-radius: 4px; color: #666;"
        )
        self.info_label.clear_info()
        self.source_label.setText("")

    def set_cover_from_bytes(self, data: bytes, source: str = ""):
        """Load and display cover from bytes."""
        if data:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self._set_pixmap(pixmap)
                self.info_label.set_image_info(pixmap.width(), pixmap.height(), len(data))
                self.source_label.setText(source)
                return

        # Invalid data case
        self.cover_label.setText(tr("Invalid image"))
        self.cover_label.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444; border-radius: 4px; color: #666;"
        )
        self.info_label.clear_info()
        self.source_label.setText("")

    def _set_pixmap(self, pixmap: QPixmap):
        """Scale and set a pixmap on the cover label."""
        # Store original for zoom
        self.cover_label.set_original_pixmap(pixmap)
        scaled = pixmap.scaled(
            200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.cover_label.setPixmap(scaled)
        self.cover_label.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444; border-radius: 4px;"
        )


class SmallCoverPanel(QFrame):
    """Smaller panel for displaying a cover image with minimal metadata."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box)
        self._setup_ui(title)

    def _setup_ui(self, title: str):
        """Set up the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Title label
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 10px;")
        layout.addWidget(self.title_label)

        # Cover image (smaller, clickable for zoom)
        self.cover_label = ClickableImageLabel()
        self.cover_label.setFixedSize(100, 100)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444; border-radius: 4px;"
        )
        self.cover_label.setToolTip(tr("Double-click to zoom"))
        layout.addWidget(self.cover_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Image info
        self.info_label = ImageInfoLabel()
        layout.addWidget(self.info_label)

    def set_cover_from_path(self, path: Path):
        """Load and display cover from a file path."""
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._set_pixmap(pixmap)
            try:
                size_bytes = path.stat().st_size
                self.info_label.set_image_info(pixmap.width(), pixmap.height(), size_bytes)
            except OSError:
                self.info_label.set_dimensions(pixmap.width(), pixmap.height())

    def set_cover_from_bytes(self, data: bytes):
        """Load and display cover from bytes."""
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self._set_pixmap(pixmap)
            self.info_label.set_image_info(pixmap.width(), pixmap.height(), len(data))

    def _set_pixmap(self, pixmap: QPixmap):
        """Scale and set a pixmap on the cover label."""
        # Store original for zoom
        self.cover_label.set_original_pixmap(pixmap)
        scaled = pixmap.scaled(
            100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.cover_label.setPixmap(scaled)
        self.cover_label.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444; border-radius: 4px;"
        )


class CoverComparisonDialog(QDialog):
    """
    Dialog for comparing current and new cover art before applying.

    Shows a side-by-side comparison with image metadata and
    the save strategy that will be applied.
    """

    cover_approved = Signal(bytes, SearchResult, CoverSaveDecision)  # Emitted when user approves

    def __init__(
        self,
        album: AlbumInfo,
        current_cover_path: Path | None,
        new_cover_data: bytes,
        search_result: SearchResult,
        save_decision: CoverSaveDecision,
        parent=None,
        embedded_cover_data: bytes | None = None,
    ):
        """
        Initialize the comparison dialog.

        Args:
            album: Album being modified
            current_cover_path: Path to current folder cover file (or None)
            new_cover_data: Raw bytes of the new cover
            search_result: Search result for the new cover
            save_decision: How the cover will be saved
            parent: Parent widget
            embedded_cover_data: Raw bytes of current embedded cover (or None)
        """
        super().__init__(parent)
        self.album = album
        self.current_cover_path = current_cover_path
        self.embedded_cover_data = embedded_cover_data
        self.new_cover_data = new_cover_data
        self.search_result = search_result
        self.save_decision = save_decision

        self._setup_ui()
        self._load_covers()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle(tr("Preview before applying"))
        self.setMinimumSize(500, 400)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Album name header
        album_label = QLabel(f"<b>{self.album.display_name}</b>")
        album_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(album_label)

        # Determine what current covers we have
        has_embedded = bool(self.embedded_cover_data)
        has_folder = bool(self.current_cover_path and self.current_cover_path.exists())
        has_both = has_embedded and has_folder

        # Comparison panels
        panels_layout = QHBoxLayout()
        panels_layout.setSpacing(16)

        if has_both:
            # Show both current covers in a vertical layout
            current_container = QWidget()
            current_layout = QVBoxLayout(current_container)
            current_layout.setContentsMargins(0, 0, 0, 0)
            current_layout.setSpacing(8)

            # Header for current section
            current_header = QLabel(tr("Current covers"))
            current_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            current_header.setStyleSheet("font-weight: bold; font-size: 12px;")
            current_layout.addWidget(current_header)

            # Two small panels side by side
            small_panels_layout = QHBoxLayout()
            small_panels_layout.setSpacing(8)

            self.embedded_panel = SmallCoverPanel(tr("Audio tags"))
            small_panels_layout.addWidget(self.embedded_panel)

            self.folder_panel = SmallCoverPanel(tr("External file"))
            small_panels_layout.addWidget(self.folder_panel)

            current_layout.addLayout(small_panels_layout)
            panels_layout.addWidget(current_container)

            # We won't use the single current_panel in this case
            self.current_panel = None
        else:
            # Single current cover panel
            self.current_panel = CoverPanel(tr("Current cover"))
            panels_layout.addWidget(self.current_panel)
            self.embedded_panel = None
            self.folder_panel = None

        # Arrow indicator
        arrow_label = QLabel("\u2192")  # Right arrow
        arrow_label.setStyleSheet("font-size: 24px; color: #4a90d9;")
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panels_layout.addWidget(arrow_label)

        # New cover panel
        self.new_panel = CoverPanel(tr("New cover"))
        panels_layout.addWidget(self.new_panel)

        layout.addLayout(panels_layout)

        # Save options (editable checkboxes)
        options_group = QGroupBox(tr("Save options"))
        options_layout = QVBoxLayout(options_group)

        # Embed checkbox
        self.embed_checkbox = QCheckBox(tr("Embed in audio tags"))
        self.embed_checkbox.setChecked(self.save_decision.embed_in_tags)
        self.embed_checkbox.stateChanged.connect(self._on_option_changed)
        options_layout.addWidget(self.embed_checkbox)

        # Save external file checkbox
        filename = f"{self.save_decision.external_filename}.jpg"
        self.save_file_checkbox = QCheckBox(
            tr("Save as external file ({filename})").format(filename=filename)
        )
        # For single tracks, default to unchecked even if save_external_file is True in preferences
        if self.album.track_count == 1:
            self.save_file_checkbox.setChecked(False)
        else:
            self.save_file_checkbox.setChecked(self.save_decision.save_external_file)
        self.save_file_checkbox.stateChanged.connect(self._on_option_changed)
        options_layout.addWidget(self.save_file_checkbox)

        # Show reason (from initial strategy evaluation)
        reason_label = QLabel(
            tr("<i>Suggestion: {reason}</i>").format(reason=self.save_decision.reason)
        )
        reason_label.setStyleSheet("font-size: 10px; color: #888;")
        reason_label.setWordWrap(True)
        options_layout.addWidget(reason_label)

        layout.addWidget(options_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton(tr("Apply"))
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._on_apply)
        # Disable if no save action will be performed (based on checkbox states)
        self._update_apply_button_state()
        btn_layout.addWidget(self.apply_btn)

        layout.addLayout(btn_layout)

        # Adjust dialog size based on whether we show both covers
        has_embedded = bool(self.embedded_cover_data)
        has_folder = bool(self.current_cover_path and self.current_cover_path.exists())
        if has_embedded and has_folder:
            self.resize(600, 480)
        else:
            self.resize(550, 450)

    def _load_covers(self):
        """Load cover images into the panels."""
        has_embedded = bool(self.embedded_cover_data)
        has_folder = bool(self.current_cover_path and self.current_cover_path.exists())

        if has_embedded and has_folder:
            # Both covers exist - show in separate small panels
            self.embedded_panel.set_cover_from_bytes(self.embedded_cover_data)
            self.folder_panel.set_cover_from_path(self.current_cover_path)
        elif self.current_panel:
            # Single panel mode
            if has_embedded:
                self.current_panel.set_cover_from_bytes(self.embedded_cover_data, tr("Audio tags"))
            elif has_folder:
                self.current_panel.set_cover_from_path(self.current_cover_path)
            else:
                # No current cover
                self.current_panel.set_cover_from_path(None)

        # New cover
        source = f"{self.search_result.provider}: {self.search_result.display_name}"
        self.new_panel.set_cover_from_bytes(self.new_cover_data, source)

    def _on_option_changed(self):
        """Handle checkbox state change."""
        self._update_apply_button_state()

    def _update_apply_button_state(self):
        """Update the apply button enabled state based on checkboxes."""
        at_least_one_checked = (
            self.embed_checkbox.isChecked() or self.save_file_checkbox.isChecked()
        )
        self.apply_btn.setEnabled(at_least_one_checked)

    def _create_modified_decision(self) -> CoverSaveDecision:
        """Create a CoverSaveDecision based on current checkbox states."""
        return CoverSaveDecision(
            embed_in_tags=self.embed_checkbox.isChecked(),
            save_external_file=self.save_file_checkbox.isChecked(),
            external_filename=self.save_decision.external_filename,
            reason=tr("Options modified by user"),
        )

    def _on_apply(self):
        """Handle apply button click."""
        modified_decision = self._create_modified_decision()
        self.cover_approved.emit(self.new_cover_data, self.search_result, modified_decision)
        self.accept()

    def keyPressEvent(self, event):
        """Handle key press events."""
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if self.apply_btn.isEnabled():
                self._on_apply()
        else:
            super().keyPressEvent(event)
