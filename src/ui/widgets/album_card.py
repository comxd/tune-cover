"""
Album card widget for grid view display.
"""

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from ...core.embedder import extract_embedded_cover
from ...core.models import AlbumInfo, CoverStatus
from ...i18n import tr
from .loading_spinner import LoadingSpinner


class AlbumCard(QFrame):
    """
    Card widget for displaying an album in grid view.

    Supports lazy loading of cover images for improved performance
    when displaying large libraries.
    """

    clicked = Signal(AlbumInfo, object)  # album, modifiers
    double_clicked = Signal(AlbumInfo)

    CARD_SIZE = 150
    COVER_SIZE = 130
    TOOLTIP_PREVIEW_SIZE = 200

    def __init__(self, album: AlbumInfo, lazy_load: bool = True, parent=None):
        """
        Initialize the album card.

        Args:
            album: Album data to display
            lazy_load: If True, don't load cover immediately (default True)
            parent: Parent widget
        """
        super().__init__(parent)
        self.album = album
        self._selected = False
        self._hovered = False
        self._cover_loaded = False
        self._lazy_load = lazy_load

        self._setup_ui()

        if lazy_load:
            self._set_placeholder()
        else:
            self.load_cover()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        self.setFixedSize(self.CARD_SIZE, self.CARD_SIZE + 60)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(2)

        # Cover container with stacked layout for image/spinner
        self.cover_container = QFrame()
        self.cover_container.setFixedSize(self.COVER_SIZE, self.COVER_SIZE)
        self.cover_container.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 4px;
            }
        """)

        cover_layout = QStackedLayout(self.cover_container)
        cover_layout.setContentsMargins(0, 0, 0, 0)
        cover_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)

        # Cover image label
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(self.COVER_SIZE, self.COVER_SIZE)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_layout.addWidget(self.cover_label)

        # Loading spinner (overlayed on top)
        self._spinner = LoadingSpinner(size=32, color="#4a90d9")
        self._spinner.hide()
        cover_layout.addWidget(self._spinner)

        layout.addWidget(self.cover_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # Album title (max 3 lines, ~42px height for 11px font with line-height)
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumWidth(self.COVER_SIZE)
        self.title_label.setFixedHeight(42)
        self.title_label.setStyleSheet("font-size: 11px; line-height: 1.2;")
        layout.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Artist
        self.artist_label = QLabel()
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label.setMaximumWidth(self.COVER_SIZE)
        self.artist_label.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.artist_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._update_style()

    def _set_placeholder(self) -> None:
        """Set placeholder image and labels before cover is loaded."""
        # Placeholder pixmap
        pixmap = QPixmap(self.COVER_SIZE, self.COVER_SIZE)
        pixmap.fill(QColor("#2a2a2a"))
        self.cover_label.setPixmap(pixmap)

        # Update labels (these are fast, so do immediately)
        self._update_labels()

        self._cover_loaded = False

    def set_loading(self, loading: bool) -> None:
        """
        Show or hide loading spinner.

        Args:
            loading: True to show spinner, False to hide
        """
        if loading:
            self._spinner.move(
                (self.COVER_SIZE - self._spinner.width()) // 2,
                (self.COVER_SIZE - self._spinner.height()) // 2,
            )
            self._spinner.start()
        else:
            self._spinner.stop()

    def set_cover_pixmap(self, pixmap: QPixmap) -> None:
        """
        Set the cover pixmap directly (for lazy loading).

        This is called by the ThumbnailLoader when a cover finishes loading.

        Args:
            pixmap: The loaded cover pixmap
        """
        # Apply covers-differ indicator if needed
        final_pixmap = self._apply_cover_indicators(pixmap)
        self.cover_label.setPixmap(final_pixmap)
        self._cover_loaded = True
        self.set_loading(False)

        # Set tooltip
        tooltip_html = self._create_tooltip()
        self.setToolTip(tooltip_html)

    def load_cover(self) -> None:
        """
        Load the cover image synchronously.

        This is the original loading method for when lazy loading is disabled
        or when called from update_display().
        """
        pixmap = self._load_cover_pixmap()
        self.cover_label.setPixmap(pixmap)
        self._cover_loaded = True

        # Update labels
        self._update_labels()

        # Set tooltip
        tooltip_html = self._create_tooltip()
        self.setToolTip(tooltip_html)

    def update_display(self) -> None:
        """Update the display with current album data."""
        self.load_cover()

    def _update_labels(self) -> None:
        """Update title and artist labels."""
        # Title uses wordWrap with fixed height, no manual truncation needed
        title = self.album.album or tr("Unknown album")
        self.title_label.setText(title)

        # Artist label is single line, truncate if too long
        artist = self.album.artist or tr("Unknown artist")
        if len(artist) > 22:
            artist = artist[:20] + "..."
        self.artist_label.setText(artist)

    def is_cover_loaded(self) -> bool:
        """Check if the cover image has been loaded."""
        return self._cover_loaded

    def _load_cover_pixmap(self) -> QPixmap:
        """Load and return the cover pixmap."""
        pixmap = QPixmap(self.COVER_SIZE, self.COVER_SIZE)
        pixmap.fill(QColor("#2a2a2a"))

        has_cover = False

        # Try to load folder cover first
        if self.album.cover.folder_path and self.album.cover.folder_path.exists():
            loaded = QPixmap(str(self.album.cover.folder_path))
            if not loaded.isNull():
                pixmap = loaded.scaled(
                    self.COVER_SIZE,
                    self.COVER_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                has_cover = True

        # Try to load embedded cover if no folder cover
        if not has_cover and self.album.cover.has_embedded and self.album.sample_file:
            embedded_data = extract_embedded_cover(self.album.sample_file)
            if embedded_data:
                loaded = QPixmap()
                if loaded.loadFromData(embedded_data):
                    pixmap = loaded.scaled(
                        self.COVER_SIZE,
                        self.COVER_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    has_cover = True

        if not has_cover:
            # Draw status indicator for missing cover
            painter = QPainter(pixmap)
            try:
                painter.setPen(QColor("#666"))
                painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "?")
            finally:
                painter.end()

        # Apply indicators
        pixmap = self._apply_cover_indicators(pixmap)

        return pixmap

    def _apply_cover_indicators(self, pixmap: QPixmap) -> QPixmap:
        """Apply cover difference indicators if needed."""
        # Draw covers differ indicator (only when both exist but differ)
        if self.album.cover.covers_differ:
            # Determine if it's just dimension difference or complete difference
            same_image_diff_size = (
                self.album.cover.dimensions_differ and not self._is_completely_different_image()
            )
            pixmap = self._draw_covers_differ_indicator(pixmap, same_image_diff_size)
            self._set_cover_diff_tooltip()
        else:
            self.cover_label.setToolTip("")

        # Draw AcoustID indicator (top-left corner)
        if self.album.acoustid:
            pixmap = self._draw_acoustid_indicator(pixmap)

        # Draw single track indicator (top-right corner)
        if self.album.track_count == 1:
            pixmap = self._draw_single_track_indicator(pixmap)

        # Draw forced group indicator (bottom-left corner)
        if self.album.is_forced_group:
            pixmap = self._draw_forced_group_indicator(pixmap)

        return pixmap

    def _create_tooltip(self) -> str:
        """
        Create an HTML tooltip with album info and cover preview.

        Returns:
            HTML string for the tooltip
        """
        album_name = self.album.album or tr("Unknown album")
        artist_name = self.album.artist or tr("Unknown artist")
        year = self.album.year or ""

        # Get cover status info
        status = self.album.cover.status
        status_texts = {
            CoverStatus.NONE: tr("No cover"),
            CoverStatus.EMBEDDED_ONLY: tr("Embedded cover only"),
            CoverStatus.FOLDER_ONLY: tr("Folder cover only"),
            CoverStatus.BOTH: tr("Embedded and folder covers"),
        }
        status_text = status_texts.get(status, tr("Unknown status"))

        # Add dimensions info if available
        dimensions_info = ""
        if self.album.cover.embedded_dimensions:
            w, h = self.album.cover.embedded_dimensions
            dimensions_info += f"<br/>{tr('Tags')}: {w}x{h}"
        if self.album.cover.folder_dimensions:
            w, h = self.album.cover.folder_dimensions
            dimensions_info += f"<br/>{tr('File')}: {w}x{h}"

        # Add cover difference warning
        diff_warning = ""
        if self.album.cover.covers_differ:
            diff_warning = f"<br/><span style='color: #e67e22;'>{tr('Different images')}</span>"

        # Add AcoustID indicator
        acoustid_info = ""
        if self.album.acoustid:
            acoustid_info = "<br/><span style='color: #27ae60;'>AcoustID: ✓</span>"

        # Add forced group indicator
        forced_group_info = ""
        if self.album.is_forced_group:
            forced_group_text = tr("Manually grouped")
            forced_group_info = f"<br/><span style='color: #e67e22;'>🔗 {forced_group_text}</span>"

        # Add track count info
        track_info = ""
        if self.album.track_count == 1:
            single_track_text = tr("Single track")
            track_info = f"<br/><span style='color: #9b59b6;'>{single_track_text}</span>"
        elif self.album.track_count > 1:
            tracks_text = tr("{count} tracks").format(count=self.album.track_count)
            track_info = f"<br/>{tracks_text}"

        # Try to load cover for preview
        cover_html = ""
        preview_pixmap = self._load_tooltip_preview()

        if preview_pixmap and not preview_pixmap.isNull():
            base64_data = self._pixmap_to_base64(preview_pixmap)
            if base64_data:
                cover_html = f'<img src="data:image/png;base64,{base64_data}" /><br/>'

        # Build HTML tooltip
        year_str = f" ({year})" if year else ""
        html = f"""
        <div style="text-align: center; padding: 4px;">
            {cover_html}
            <b>{album_name}</b>{year_str}<br/>
            <span style="color: #888;">{artist_name}</span><br/>
            <span style="font-size: 10px; color: #666;">{status_text}{dimensions_info}{diff_warning}{acoustid_info}{forced_group_info}{track_info}</span>
        </div>
        """
        return html.strip()

    def _load_tooltip_preview(self) -> QPixmap:
        """
        Load and return a larger cover pixmap for tooltip preview.

        Returns:
            QPixmap scaled to TOOLTIP_PREVIEW_SIZE or None if no cover
        """
        preview_size = self.TOOLTIP_PREVIEW_SIZE

        # Try to load folder cover first
        if self.album.cover.folder_path and self.album.cover.folder_path.exists():
            loaded = QPixmap(str(self.album.cover.folder_path))
            if not loaded.isNull():
                return loaded.scaled(
                    preview_size,
                    preview_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

        # Try to load embedded cover
        if self.album.cover.has_embedded and self.album.sample_file:
            embedded_data = extract_embedded_cover(self.album.sample_file)
            if embedded_data:
                loaded = QPixmap()
                if loaded.loadFromData(embedded_data):
                    return loaded.scaled(
                        preview_size,
                        preview_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

        # No cover available
        return None

    def _pixmap_to_base64(self, pixmap: QPixmap) -> str:
        """
        Convert a QPixmap to a base64 encoded PNG string.

        Args:
            pixmap: The QPixmap to convert

        Returns:
            Base64 encoded string of the image, or empty string on failure
        """
        if pixmap is None or pixmap.isNull():
            return ""

        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)

        # Save pixmap to buffer as PNG
        if not pixmap.save(buffer, "PNG"):
            buffer.close()
            return ""

        buffer.close()

        # Convert to base64
        return base64.b64encode(byte_array.data()).decode("utf-8")

    def _is_completely_different_image(self) -> bool:
        """
        Heuristic to determine if images are completely different vs same image with different compression.
        Returns True if images are likely completely different.
        """
        # If dimensions are very different (aspect ratio change), likely different images
        if self.album.cover.embedded_dimensions and self.album.cover.folder_dimensions:
            e_w, e_h = self.album.cover.embedded_dimensions
            f_w, f_h = self.album.cover.folder_dimensions
            if e_w > 0 and e_h > 0 and f_w > 0 and f_h > 0:
                e_ratio = e_w / e_h
                f_ratio = f_w / f_h
                # If aspect ratios differ by more than 10%, likely different images
                if abs(e_ratio - f_ratio) > 0.1:
                    return True
                # If size difference is more than 4x, consider them different
                e_size = e_w * e_h
                f_size = f_w * f_h
                ratio = max(e_size, f_size) / max(min(e_size, f_size), 1)
                if ratio > 4:
                    return True
        return False

    def _set_cover_diff_tooltip(self) -> None:
        """Set tooltip with cover difference information."""
        embedded_dims = self.album.cover.embedded_dimensions
        folder_dims = self.album.cover.folder_dimensions

        e_str = f"{embedded_dims[0]}x{embedded_dims[1]}" if embedded_dims else "?"
        f_str = f"{folder_dims[0]}x{folder_dims[1]}" if folder_dims else "?"

        tooltip = tr("Different images") + f"\n{tr('Tags')}: {e_str}\n{tr('File')}: {f_str}"
        self.cover_label.setToolTip(tooltip)

    def _draw_covers_differ_indicator(
        self, pixmap: QPixmap, same_image_diff_size: bool = False
    ) -> QPixmap:
        """
        Draw an indicator overlay in bottom-right corner when covers differ.

        Args:
            pixmap: The cover pixmap to draw on
            same_image_diff_size: If True, use yellow (same image, different size).
                                  If False, use orange (completely different images).
        """
        # Create a copy to draw on
        result = QPixmap(pixmap)

        painter = QPainter(result)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Badge dimensions
            badge_size = 22
            margin = 4
            x = result.width() - badge_size - margin
            y = result.height() - badge_size - margin

            if same_image_diff_size:
                # Yellow for same image with different dimensions
                painter.setBrush(QBrush(QColor("#f1c40f")))  # Yellow
                painter.setPen(QPen(QColor("#d4ac0d"), 1))  # Darker yellow border
            else:
                # Orange for completely different images
                painter.setBrush(QBrush(QColor("#e67e22")))  # Orange
                painter.setPen(QPen(QColor("#d35400"), 1))  # Darker orange border

            painter.drawEllipse(x, y, badge_size, badge_size)

            # Draw "!=" symbol
            pen_color = QColor("#333333") if same_image_diff_size else QColor("#ffffff")
            painter.setPen(pen_color)
            font = QFont()
            font.setPixelSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(x, y, badge_size, badge_size, Qt.AlignmentFlag.AlignCenter, "!=")
        finally:
            painter.end()

        return result

    def _draw_acoustid_indicator(self, pixmap: QPixmap) -> QPixmap:
        """
        Draw an AcoustID indicator overlay in top-left corner.

        Shows a small badge indicating the album has been identified via AcoustID.
        """
        result = QPixmap(pixmap)

        painter = QPainter(result)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Badge dimensions (smaller than covers differ indicator)
            badge_size = 18
            margin = 4
            x = margin
            y = margin

            # Green color to indicate identified/verified
            painter.setBrush(QBrush(QColor("#27ae60")))  # Green
            painter.setPen(QPen(QColor("#1e8449"), 1))  # Darker green border

            painter.drawEllipse(x, y, badge_size, badge_size)

            # Draw fingerprint-like symbol (using "A" for AcoustID)
            painter.setPen(QColor("#ffffff"))
            font = QFont()
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(x, y, badge_size, badge_size, Qt.AlignmentFlag.AlignCenter, "A")
        finally:
            painter.end()

        return result

    def _draw_single_track_indicator(self, pixmap: QPixmap) -> QPixmap:
        """
        Draw a single track indicator overlay in top-right corner.

        Shows a purple "1" badge for individual files (single tracks).
        """
        result = QPixmap(pixmap)

        painter = QPainter(result)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Badge dimensions
            badge_size = 18
            margin = 4
            x = result.width() - badge_size - margin
            y = margin

            # Purple color for single track
            painter.setBrush(QBrush(QColor("#9b59b6")))  # Purple
            painter.setPen(QPen(QColor("#8e44ad"), 1))  # Darker purple border

            painter.drawEllipse(x, y, badge_size, badge_size)

            # Draw "1" symbol
            painter.setPen(QColor("#ffffff"))
            font = QFont()
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(x, y, badge_size, badge_size, Qt.AlignmentFlag.AlignCenter, "1")
        finally:
            painter.end()

        return result

    def _draw_forced_group_indicator(self, pixmap: QPixmap) -> QPixmap:
        """
        Draw a forced group indicator overlay in bottom-left corner.

        Shows an orange link/chain icon for manually grouped albums.
        """
        result = QPixmap(pixmap)

        painter = QPainter(result)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Badge dimensions
            badge_size = 18
            margin = 4
            x = margin
            y = result.height() - badge_size - margin

            # Orange color for forced group
            painter.setBrush(QBrush(QColor("#e67e22")))  # Orange
            painter.setPen(QPen(QColor("#d35400"), 1))  # Darker orange border

            painter.drawEllipse(x, y, badge_size, badge_size)

            # Draw link symbol (simplified chain icon)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            # Draw two interlocking circles to represent a link
            center_x = x + badge_size // 2
            center_y = y + badge_size // 2
            painter.drawArc(center_x - 5, center_y - 3, 8, 6, 0, 180 * 16)
            painter.drawArc(center_x - 3, center_y - 3, 8, 6, 180 * 16, 180 * 16)
        finally:
            painter.end()

        return result

    def set_selected(self, selected: bool) -> None:
        """Set the selection state."""
        self._selected = selected
        self._update_style()

    def _update_style(self) -> None:
        """Update the frame style based on state."""
        if self._selected:
            self.setStyleSheet("""
                AlbumCard {
                    border: 2px solid #4a90d9;
                    border-radius: 6px;
                    background-color: rgba(74, 144, 217, 0.1);
                }
            """)
        elif self._hovered:
            self.setStyleSheet("""
                AlbumCard {
                    border: 1px solid #555;
                    border-radius: 6px;
                    background-color: rgba(255, 255, 255, 0.03);
                }
            """)
        else:
            self.setStyleSheet("""
                AlbumCard {
                    border: 1px solid #333;
                    border-radius: 6px;
                    background-color: transparent;
                }
            """)

    def enterEvent(self, event) -> None:
        """Handle mouse enter."""
        self._hovered = True
        self._update_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """Handle mouse leave."""
        self._hovered = False
        self._update_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.album, event.modifiers())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Handle double click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.album)
        super().mouseDoubleClickEvent(event)
