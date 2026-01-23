"""
Cover zoom dialog for side-by-side comparison of embedded and folder covers.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ..widgets.image_info import ImageInfoLabel

logger = logging.getLogger(__name__)


# Constants
COVER_DISPLAY_SIZE = 400
MIN_ZOOM = 0.25
MAX_ZOOM = 4.0
ZOOM_STEP = 0.1


class ZoomableGraphicsView(QGraphicsView):
    """
    QGraphicsView with zoom and pan capabilities.

    Supports mouse wheel zoom, click-drag panning, and programmatic zoom control.
    """

    zoom_changed = Signal(float)  # Emitted when zoom level changes

    def __init__(self, parent: QWidget | None = None):
        """
        Initialize the zoomable graphics view.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._zoom_factor = 1.0
        self._is_panning = False
        self._pan_start_x = 0
        self._pan_start_y = 0

        # Setup view properties
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet("QGraphicsView { background-color: #1e1e1e; border: 1px solid #444; }")

    @property
    def zoom_factor(self) -> float:
        """Get the current zoom factor."""
        return self._zoom_factor

    def set_zoom(self, factor: float) -> None:
        """
        Set the zoom level.

        Args:
            factor: Zoom factor (1.0 = 100%)
        """
        factor = max(MIN_ZOOM, min(MAX_ZOOM, factor))
        if factor != self._zoom_factor:
            scale_ratio = factor / self._zoom_factor
            self.scale(scale_ratio, scale_ratio)
            self._zoom_factor = factor
            self.zoom_changed.emit(factor)

    def zoom_in(self) -> None:
        """Zoom in by one step."""
        self.set_zoom(self._zoom_factor + ZOOM_STEP)

    def zoom_out(self) -> None:
        """Zoom out by one step."""
        self.set_zoom(self._zoom_factor - ZOOM_STEP)

    def fit_to_view(self) -> None:
        """Fit the image to the view bounds."""
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        # Calculate the actual zoom factor after fitting
        if self.scene() and self.scene().sceneRect().width() > 0:
            view_rect = self.viewport().rect()
            scene_rect = self.sceneRect()
            x_ratio = view_rect.width() / scene_rect.width()
            y_ratio = view_rect.height() / scene_rect.height()
            self._zoom_factor = min(x_ratio, y_ratio)
            self.zoom_changed.emit(self._zoom_factor)

    def reset_zoom(self) -> None:
        """Reset zoom to 100%."""
        self.resetTransform()
        self._zoom_factor = 1.0
        self.zoom_changed.emit(self._zoom_factor)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel for zooming."""
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_in()
        elif delta < 0:
            self.zoom_out()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start panning on middle or left mouse button press."""
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._is_panning = True
            self._pan_start_x = event.position().x()
            self._pan_start_y = event.position().y()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle panning while mouse button is held."""
        if self._is_panning:
            delta_x = event.position().x() - self._pan_start_x
            delta_y = event.position().y() - self._pan_start_y
            self._pan_start_x = event.position().x()
            self._pan_start_y = event.position().y()

            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(int(h_bar.value() - delta_x))
            v_bar.setValue(int(v_bar.value() - delta_y))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Stop panning on mouse button release."""
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)


class CoverViewPanel(QWidget):
    """
    Panel displaying a zoomable cover image with metadata.

    Shows the cover image in a ZoomableGraphicsView with dimensions,
    file size, and format information below.
    """

    def __init__(self, title: str, parent: QWidget | None = None):
        """
        Initialize the cover view panel.

        Args:
            title: Title label for the panel
            parent: Parent widget
        """
        super().__init__(parent)
        self._title = title
        self._pixmap: QPixmap | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Title
        self.title_label = QLabel(self._title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self.title_label)

        # Graphics view for zoomable image
        self.graphics_view = ZoomableGraphicsView()
        self.graphics_view.setFixedSize(COVER_DISPLAY_SIZE, COVER_DISPLAY_SIZE)
        self.scene = QGraphicsScene()
        self.graphics_view.setScene(self.scene)
        self.pixmap_item: QGraphicsPixmapItem | None = None
        layout.addWidget(self.graphics_view, alignment=Qt.AlignmentFlag.AlignCenter)

        # Image info
        self.info_label = ImageInfoLabel()
        layout.addWidget(self.info_label)

        # Format label
        self.format_label = QLabel()
        self.format_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.format_label.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.format_label)

    def set_cover_from_bytes(self, data: bytes, format_hint: str | None = None) -> bool:
        """
        Load and display cover from bytes.

        Args:
            data: Raw image bytes
            format_hint: Optional format hint (e.g., 'image/jpeg')

        Returns:
            True if image was loaded successfully
        """
        self._pixmap = QPixmap()
        if not self._pixmap.loadFromData(data):
            self._show_no_image(tr("Invalid image"))
            return False

        self._display_pixmap()
        self.info_label.set_image_info(self._pixmap.width(), self._pixmap.height(), len(data))

        # Set format label
        if format_hint:
            fmt = self._mime_to_format(format_hint)
            self.format_label.setText(fmt)
        else:
            self.format_label.setText("")

        return True

    def set_cover_from_path(self, path: Path) -> bool:
        """
        Load and display cover from a file path.

        Args:
            path: Path to the image file

        Returns:
            True if image was loaded successfully
        """
        if not path.exists():
            self._show_no_image(tr("File not found"))
            return False

        self._pixmap = QPixmap(str(path))
        if self._pixmap.isNull():
            self._show_no_image(tr("Invalid image"))
            return False

        self._display_pixmap()

        # Get file info
        try:
            size_bytes = path.stat().st_size
            self.info_label.set_image_info(self._pixmap.width(), self._pixmap.height(), size_bytes)
        except OSError:
            self.info_label.set_dimensions(self._pixmap.width(), self._pixmap.height())

        # Set format based on extension
        ext = path.suffix.lower().lstrip(".")
        fmt_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WebP"}
        self.format_label.setText(fmt_map.get(ext, ext.upper()))

        return True

    def _display_pixmap(self) -> None:
        """Display the current pixmap in the graphics view."""
        self.scene.clear()
        if self._pixmap and not self._pixmap.isNull():
            self.pixmap_item = QGraphicsPixmapItem(self._pixmap)
            self.scene.addItem(self.pixmap_item)
            self.scene.setSceneRect(self._pixmap.rect().toRectF())
            self.graphics_view.fit_to_view()

    def _show_no_image(self, message: str) -> None:
        """Show a message when no image is available."""
        self.scene.clear()
        text_item = self.scene.addText(message)
        text_item.setDefaultTextColor(Qt.GlobalColor.gray)
        self.info_label.clear_info()
        self.format_label.setText("")

    def _mime_to_format(self, mime_type: str) -> str:
        """Convert MIME type to human-readable format."""
        mime_map = {
            "image/jpeg": "JPEG",
            "image/jpg": "JPEG",
            "image/png": "PNG",
            "image/gif": "GIF",
            "image/webp": "WebP",
            "image/bmp": "BMP",
        }
        return mime_map.get(mime_type.lower(), mime_type.split("/")[-1].upper())

    def set_border_style(self, is_larger: bool) -> None:
        """
        Set the border style based on whether this cover is larger.

        Args:
            is_larger: True if this cover is the larger one
        """
        if is_larger:
            self.graphics_view.setStyleSheet(
                "QGraphicsView { background-color: #1e1e1e; border: 3px solid #27ae60; }"
            )
        else:
            self.graphics_view.setStyleSheet(
                "QGraphicsView { background-color: #1e1e1e; border: 1px solid #444; }"
            )

    def get_pixel_count(self) -> int:
        """Get the total pixel count of the image."""
        if self._pixmap and not self._pixmap.isNull():
            return self._pixmap.width() * self._pixmap.height()
        return 0

    def get_dimensions(self) -> tuple | None:
        """Get the image dimensions as (width, height)."""
        if self._pixmap and not self._pixmap.isNull():
            return (self._pixmap.width(), self._pixmap.height())
        return None


class CoverZoomDialog(QDialog):
    """
    Dialog for enlarged side-by-side cover comparison.

    Shows embedded and folder covers at 400x400 with:
    - Zoom controls (zoom in/out, fit to window)
    - Synchronized zoom between both images
    - Click-drag panning
    - Keyboard shortcuts (+/- for zoom, Escape to close)
    - Visual indicator showing which cover is larger (green border)
    """

    def __init__(
        self,
        album_name: str,
        embedded_data: bytes | None,
        folder_path: Path | None,
        embedded_mime: str | None = None,
        parent: QWidget | None = None,
    ):
        """
        Initialize the cover zoom dialog.

        Args:
            album_name: Name of the album (for title)
            embedded_data: Raw bytes of embedded cover (or None)
            folder_path: Path to folder cover file (or None)
            embedded_mime: MIME type of embedded cover
            parent: Parent widget
        """
        super().__init__(parent)
        self.album_name = album_name
        self.embedded_data = embedded_data
        self.folder_path = folder_path
        self.embedded_mime = embedded_mime

        self._setup_ui()
        self._load_covers()
        self._update_larger_indicator()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.setWindowTitle(tr("Cover comparison - {name}").format(name=self.album_name))
        self.setMinimumSize(900, 600)
        self.resize(950, 650)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Album name header
        album_label = QLabel(f"<b>{self.album_name}</b>")
        album_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        album_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(album_label)

        # Cover panels side by side
        panels_layout = QHBoxLayout()
        panels_layout.setSpacing(24)

        # Embedded cover panel
        self.embedded_panel = CoverViewPanel(tr("Audio tags"))
        panels_layout.addWidget(self.embedded_panel)

        # Folder cover panel
        self.folder_panel = CoverViewPanel(tr("External file"))
        panels_layout.addWidget(self.folder_panel)

        layout.addLayout(panels_layout)

        # Zoom controls
        controls_group = QGroupBox(tr("Zoom controls"))
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(12)

        # Zoom out button
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setFixedWidth(40)
        self.zoom_out_btn.setToolTip(tr("Zoom out (- key)"))
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        controls_layout.addWidget(self.zoom_out_btn)

        # Zoom slider
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(int(MIN_ZOOM * 100))
        self.zoom_slider.setMaximum(int(MAX_ZOOM * 100))
        self.zoom_slider.setValue(100)
        self.zoom_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.zoom_slider.setTickInterval(50)
        self.zoom_slider.valueChanged.connect(self._on_slider_changed)
        controls_layout.addWidget(self.zoom_slider)

        # Zoom in button
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedWidth(40)
        self.zoom_in_btn.setToolTip(tr("Zoom in (+ key)"))
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        controls_layout.addWidget(self.zoom_in_btn)

        # Zoom percentage label
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(50)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(self.zoom_label)

        # Fit button
        self.fit_btn = QPushButton(tr("Fit"))
        self.fit_btn.setToolTip(tr("Fit to window"))
        self.fit_btn.clicked.connect(self._fit_to_view)
        controls_layout.addWidget(self.fit_btn)

        # Reset button
        self.reset_btn = QPushButton("100%")
        self.reset_btn.setToolTip(tr("Reset zoom to 100%"))
        self.reset_btn.clicked.connect(self._reset_zoom)
        controls_layout.addWidget(self.reset_btn)

        layout.addWidget(controls_group)

        # Difference indicator
        self.diff_label = QLabel()
        self.diff_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diff_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.diff_label)

        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        close_btn = QPushButton(tr("Close"))
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Connect zoom signals for synchronization
        self.embedded_panel.graphics_view.zoom_changed.connect(self._on_embedded_zoom)
        self.folder_panel.graphics_view.zoom_changed.connect(self._on_folder_zoom)

    def _load_covers(self) -> None:
        """Load the cover images into the panels."""
        # Load embedded cover
        if self.embedded_data:
            self.embedded_panel.set_cover_from_bytes(self.embedded_data, self.embedded_mime)
        else:
            self.embedded_panel._show_no_image(tr("No cover"))

        # Load folder cover
        if self.folder_path and self.folder_path.exists():
            self.folder_panel.set_cover_from_path(self.folder_path)
        else:
            self.folder_panel._show_no_image(tr("No cover"))

    def _update_larger_indicator(self) -> None:
        """Update the visual indicator showing which cover is larger."""
        embedded_pixels = self.embedded_panel.get_pixel_count()
        folder_pixels = self.folder_panel.get_pixel_count()

        embedded_dims = self.embedded_panel.get_dimensions()
        folder_dims = self.folder_panel.get_dimensions()

        if embedded_pixels > 0 and folder_pixels > 0:
            if embedded_pixels > folder_pixels:
                self.embedded_panel.set_border_style(is_larger=True)
                self.folder_panel.set_border_style(is_larger=False)
                diff_percent = ((embedded_pixels - folder_pixels) / folder_pixels) * 100
                self.diff_label.setText(
                    f'<span style="color: #27ae60;">{tr("Audio tags larger")}</span> '
                    f"({embedded_dims[0]}x{embedded_dims[1]} vs {folder_dims[0]}x{folder_dims[1]}, "
                    f"+{diff_percent:.1f}% " + tr("pixels") + ")"
                )
            elif folder_pixels > embedded_pixels:
                self.embedded_panel.set_border_style(is_larger=False)
                self.folder_panel.set_border_style(is_larger=True)
                diff_percent = ((folder_pixels - embedded_pixels) / embedded_pixels) * 100
                self.diff_label.setText(
                    f'<span style="color: #27ae60;">{tr("External file larger")}</span> '
                    f"({folder_dims[0]}x{folder_dims[1]} vs {embedded_dims[0]}x{embedded_dims[1]}, "
                    f"+{diff_percent:.1f}% " + tr("pixels") + ")"
                )
            else:
                # Same size
                self.embedded_panel.set_border_style(is_larger=False)
                self.folder_panel.set_border_style(is_larger=False)
                self.diff_label.setText(
                    tr("Same sizes") + f" ({embedded_dims[0]}x{embedded_dims[1]})"
                )
        elif embedded_pixels > 0:
            self.embedded_panel.set_border_style(is_larger=True)
            self.diff_label.setText(tr("Only audio tags cover is available"))
        elif folder_pixels > 0:
            self.folder_panel.set_border_style(is_larger=True)
            self.diff_label.setText(tr("Only external file cover is available"))
        else:
            self.diff_label.setText(tr("No cover available"))

    def _zoom_in(self) -> None:
        """Zoom in both panels."""
        current = self.embedded_panel.graphics_view.zoom_factor
        new_zoom = min(current + ZOOM_STEP, MAX_ZOOM)
        self._set_both_zoom(new_zoom)

    def _zoom_out(self) -> None:
        """Zoom out both panels."""
        current = self.embedded_panel.graphics_view.zoom_factor
        new_zoom = max(current - ZOOM_STEP, MIN_ZOOM)
        self._set_both_zoom(new_zoom)

    def _fit_to_view(self) -> None:
        """Fit both images to their views."""
        self.embedded_panel.graphics_view.fit_to_view()
        self.folder_panel.graphics_view.fit_to_view()
        # Update slider with average zoom
        avg_zoom = (
            self.embedded_panel.graphics_view.zoom_factor
            + self.folder_panel.graphics_view.zoom_factor
        ) / 2
        self._update_zoom_ui(avg_zoom)

    def _reset_zoom(self) -> None:
        """Reset zoom to 100% for both panels."""
        self._set_both_zoom(1.0)

    def _set_both_zoom(self, factor: float) -> None:
        """Set zoom level for both panels."""
        # Block signals to avoid feedback loop
        self.embedded_panel.graphics_view.blockSignals(True)
        self.folder_panel.graphics_view.blockSignals(True)

        self.embedded_panel.graphics_view.set_zoom(factor)
        self.folder_panel.graphics_view.set_zoom(factor)

        self.embedded_panel.graphics_view.blockSignals(False)
        self.folder_panel.graphics_view.blockSignals(False)

        self._update_zoom_ui(factor)

    def _on_slider_changed(self, value: int) -> None:
        """Handle zoom slider change."""
        factor = value / 100.0
        self._set_both_zoom(factor)

    def _on_embedded_zoom(self, factor: float) -> None:
        """Sync folder panel zoom when embedded panel zooms."""
        self.folder_panel.graphics_view.blockSignals(True)
        self.folder_panel.graphics_view.set_zoom(factor)
        self.folder_panel.graphics_view.blockSignals(False)
        self._update_zoom_ui(factor)

    def _on_folder_zoom(self, factor: float) -> None:
        """Sync embedded panel zoom when folder panel zooms."""
        self.embedded_panel.graphics_view.blockSignals(True)
        self.embedded_panel.graphics_view.set_zoom(factor)
        self.embedded_panel.graphics_view.blockSignals(False)
        self._update_zoom_ui(factor)

    def _update_zoom_ui(self, factor: float) -> None:
        """Update zoom slider and label."""
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(factor * 100))
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{int(factor * 100)}%")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts."""
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_Plus or key == Qt.Key.Key_Equal:
            self._zoom_in()
        elif key == Qt.Key.Key_Minus:
            self._zoom_out()
        elif key == Qt.Key.Key_0:
            self._reset_zoom()
        elif key == Qt.Key.Key_F:
            self._fit_to_view()
        else:
            super().keyPressEvent(event)
