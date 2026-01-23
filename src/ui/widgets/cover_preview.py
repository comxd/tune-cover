"""
Cover preview widget with zoom capability.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout

from ...i18n import tr


class CoverPreview(QLabel):
    """
    Cover preview widget that shows the album artwork
    with click-to-zoom functionality.
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._display_size = 200

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            CoverPreview {
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)

    def set_cover(self, pixmap: QPixmap):
        """Set the cover image."""
        self._pixmap = pixmap
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self._display_size,
                self._display_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)
        else:
            self.clear()
            self.setText(tr("No cover"))

    def set_cover_from_path(self, path: str):
        """Load and set cover from file path."""
        pixmap = QPixmap(path)
        self.set_cover(pixmap)

    def set_cover_from_data(self, data: bytes):
        """Load and set cover from raw data."""
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self.set_cover(pixmap)

    def set_display_size(self, size: int):
        """Set the display size."""
        self._display_size = size
        self.setFixedSize(size, size)
        if self._pixmap:
            self.set_cover(self._pixmap)

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press to open zoom dialog."""
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap:
            self.clicked.emit()
            self._show_zoom_dialog()
        super().mousePressEvent(event)

    def _show_zoom_dialog(self):
        """Show the zoom dialog."""
        if not self._pixmap or self._pixmap.isNull():
            return

        dialog = ZoomDialog(self._pixmap, self.window())
        dialog.exec()


class ZoomDialog(QDialog):
    """
    Dialog for viewing cover art at full size with zoom.
    """

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.zoom_level = 1.0
        self.min_zoom = 0.25
        self.max_zoom = 4.0

        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle(tr("Cover preview"))
        self.setModal(True)
        self.resize(600, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for zooming
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.scroll_area)

        # Image label
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.image_label)

        self._update_display()

    def _update_display(self):
        """Update the displayed image."""
        if self.pixmap.isNull():
            return

        width = int(self.pixmap.width() * self.zoom_level)
        height = int(self.pixmap.height() * self.zoom_level)

        scaled = self.pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming."""
        delta = event.angleDelta().y()

        if delta > 0:
            # Zoom in
            self.zoom_level = min(self.max_zoom, self.zoom_level * 1.1)
        else:
            # Zoom out
            self.zoom_level = max(self.min_zoom, self.zoom_level / 1.1)

        self._update_display()

    def keyPressEvent(self, event):
        """Handle key press."""
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        elif event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
            self.zoom_level = min(self.max_zoom, self.zoom_level * 1.2)
            self._update_display()
        elif event.key() == Qt.Key.Key_Minus:
            self.zoom_level = max(self.min_zoom, self.zoom_level / 1.2)
            self._update_display()
        elif event.key() == Qt.Key.Key_0:
            self.zoom_level = 1.0
            self._update_display()
        else:
            super().keyPressEvent(event)
