"""
Statistics dialog for displaying library statistics.
"""

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ...core.models import AlbumInfo, CoverStatus
from ...i18n import tr

logger = logging.getLogger(__name__)


class StatisticsDialog(QDialog):
    """
    Dialog displaying statistics about the current album library.

    Shows:
    - Total album count
    - Cover status distribution (both, embedded only, folder only, none)
    - Albums with differing covers
    - Average cover dimensions
    - Format distribution (JPEG, PNG, etc.)
    - Size statistics (min, max, average)
    """

    def __init__(self, albums: list[AlbumInfo], parent=None):
        """
        Initialize the statistics dialog.

        Args:
            albums: List of AlbumInfo objects to compute statistics from
            parent: Parent widget
        """
        super().__init__(parent)
        self.albums = albums
        self.stats = self._compute_statistics()
        self._setup_ui()

    def _compute_statistics(self) -> dict[str, Any]:
        """Compute all statistics from the albums list."""
        stats = {
            "total_albums": len(self.albums),
            "cover_status": {
                CoverStatus.BOTH: 0,
                CoverStatus.EMBEDDED_ONLY: 0,
                CoverStatus.FOLDER_ONLY: 0,
                CoverStatus.NONE: 0,
            },
            "differing_covers": 0,
            "embedded_dimensions": [],
            "folder_dimensions": [],
            "embedded_formats": {},
            "folder_formats": {},
            "embedded_sizes": [],
            "folder_sizes": [],
        }

        for album in self.albums:
            cover = album.cover

            # Cover status
            status = cover.status
            stats["cover_status"][status] += 1

            # Differing covers
            if cover.covers_differ:
                stats["differing_covers"] += 1

            # Embedded cover info
            if cover.has_embedded:
                if cover.embedded_dimensions:
                    stats["embedded_dimensions"].append(cover.embedded_dimensions)
                if cover.embedded_mime_type:
                    fmt = self._mime_to_format(cover.embedded_mime_type)
                    stats["embedded_formats"][fmt] = stats["embedded_formats"].get(fmt, 0) + 1
                if cover.embedded_size_bytes:
                    stats["embedded_sizes"].append(cover.embedded_size_bytes)

            # Folder cover info
            if cover.has_folder:
                if cover.folder_dimensions:
                    stats["folder_dimensions"].append(cover.folder_dimensions)
                if cover.folder_mime_type:
                    fmt = self._mime_to_format(cover.folder_mime_type)
                    stats["folder_formats"][fmt] = stats["folder_formats"].get(fmt, 0) + 1
                elif cover.folder_file:
                    # Fallback to extension if mime type not available
                    ext = (
                        cover.folder_file.lower().split(".")[-1] if "." in cover.folder_file else ""
                    )
                    fmt = ext.upper() if ext else tr("Unknown")
                    stats["folder_formats"][fmt] = stats["folder_formats"].get(fmt, 0) + 1
                if cover.folder_size_bytes:
                    stats["folder_sizes"].append(cover.folder_size_bytes)

        return stats

    def _mime_to_format(self, mime_type: str) -> str:
        """Convert MIME type to human-readable format name."""
        mime_map = {
            "image/jpeg": "JPEG",
            "image/jpg": "JPEG",
            "image/png": "PNG",
            "image/gif": "GIF",
            "image/webp": "WebP",
            "image/bmp": "BMP",
            "image/tiff": "TIFF",
        }
        return mime_map.get(mime_type.lower(), mime_type.upper().replace("IMAGE/", ""))

    def _format_percentage(self, count: int, total: int) -> str:
        """Format count as percentage string."""
        if total == 0:
            return "0%"
        percentage = (count / total) * 100
        return f"{percentage:.1f}%"

    def _format_dimensions(self, dimensions: list[tuple[int, int]]) -> str:
        """Calculate and format average dimensions."""
        if not dimensions:
            return "-"
        avg_width = sum(d[0] for d in dimensions) / len(dimensions)
        avg_height = sum(d[1] for d in dimensions) / len(dimensions)
        return f"{avg_width:.0f} x {avg_height:.0f} px"

    def _format_size_stats(self, sizes: list[int]) -> str:
        """Format size statistics (min, max, average)."""
        if not sizes:
            return "-"
        min_kb = min(sizes) / 1024
        max_kb = max(sizes) / 1024
        avg_kb = sum(sizes) / len(sizes) / 1024
        return tr("Min: {min} KB / Max: {max} KB / Avg: {avg} KB").format(
            min=f"{min_kb:.0f}", max=f"{max_kb:.0f}", avg=f"{avg_kb:.0f}"
        )

    def _format_distribution(self, formats: dict[str, int]) -> str:
        """Format the format distribution as a string."""
        if not formats:
            return "-"
        parts = [f"{fmt}: {count}" for fmt, count in sorted(formats.items())]
        return ", ".join(parts)

    def _setup_ui(self):
        """Set up the dialog user interface."""
        self.setWindowTitle(tr("Library statistics"))
        self.setMinimumWidth(450)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Title
        title_label = QLabel(tr("<b>Library statistics</b>"))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(title_label)

        # General statistics group
        general_group = QGroupBox(tr("Overview"))
        general_layout = QFormLayout(general_group)
        general_layout.setSpacing(8)

        total = self.stats["total_albums"]
        general_layout.addRow(tr("Total albums:"), QLabel(str(total)))

        layout.addWidget(general_group)

        # Cover status group
        cover_group = QGroupBox(tr("Cover status"))
        cover_layout = QFormLayout(cover_group)
        cover_layout.setSpacing(8)

        status_counts = self.stats["cover_status"]

        # Both covers
        both_count = status_counts[CoverStatus.BOTH]
        both_label = QLabel(f"{both_count} ({self._format_percentage(both_count, total)})")
        cover_layout.addRow(tr("Tags + external file:"), both_label)

        # Embedded only
        embedded_count = status_counts[CoverStatus.EMBEDDED_ONLY]
        embedded_label = QLabel(
            f"{embedded_count} ({self._format_percentage(embedded_count, total)})"
        )
        cover_layout.addRow(tr("Tags only:"), embedded_label)

        # Folder only
        folder_count = status_counts[CoverStatus.FOLDER_ONLY]
        folder_label = QLabel(f"{folder_count} ({self._format_percentage(folder_count, total)})")
        cover_layout.addRow(tr("External file only:"), folder_label)

        # None
        none_count = status_counts[CoverStatus.NONE]
        none_label = QLabel(f"{none_count} ({self._format_percentage(none_count, total)})")
        none_label.setStyleSheet("color: #ff6b6b;" if none_count > 0 else "")
        cover_layout.addRow(tr("Without cover:"), none_label)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        cover_layout.addRow(separator)

        # Differing covers
        differing = self.stats["differing_covers"]
        differing_label = QLabel(f"{differing} ({self._format_percentage(differing, total)})")
        if differing > 0:
            differing_label.setStyleSheet("color: #ffa500;")
        cover_layout.addRow(tr("Different covers:"), differing_label)

        layout.addWidget(cover_group)

        # Dimensions group
        dimensions_group = QGroupBox(tr("Average dimensions"))
        dimensions_layout = QFormLayout(dimensions_group)
        dimensions_layout.setSpacing(8)

        embedded_dims = self._format_dimensions(self.stats["embedded_dimensions"])
        dimensions_layout.addRow(tr("Audio tags:"), QLabel(embedded_dims))

        folder_dims = self._format_dimensions(self.stats["folder_dimensions"])
        dimensions_layout.addRow(tr("External files:"), QLabel(folder_dims))

        layout.addWidget(dimensions_group)

        # Format distribution group
        format_group = QGroupBox(tr("Format distribution"))
        format_layout = QFormLayout(format_group)
        format_layout.setSpacing(8)

        embedded_formats = self._format_distribution(self.stats["embedded_formats"])
        embedded_format_label = QLabel(embedded_formats)
        embedded_format_label.setWordWrap(True)
        format_layout.addRow(tr("Audio tags:"), embedded_format_label)

        folder_formats = self._format_distribution(self.stats["folder_formats"])
        folder_format_label = QLabel(folder_formats)
        folder_format_label.setWordWrap(True)
        format_layout.addRow(tr("External files:"), folder_format_label)

        layout.addWidget(format_group)

        # Size statistics group
        size_group = QGroupBox(tr("File sizes"))
        size_layout = QFormLayout(size_group)
        size_layout.setSpacing(8)

        embedded_sizes = self._format_size_stats(self.stats["embedded_sizes"])
        embedded_size_label = QLabel(embedded_sizes)
        embedded_size_label.setWordWrap(True)
        size_layout.addRow(tr("Audio tags:"), embedded_size_label)

        folder_sizes = self._format_size_stats(self.stats["folder_sizes"])
        folder_size_label = QLabel(folder_sizes)
        folder_size_label.setWordWrap(True)
        size_layout.addRow(tr("External files:"), folder_size_label)

        layout.addWidget(size_group)

        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        close_btn = QPushButton(tr("Close"))
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Adjust size to fit content
        self.adjustSize()

    def keyPressEvent(self, event):
        """Handle key press events."""
        if (
            event.key() == Qt.Key.Key_Escape
            or event.key() == Qt.Key.Key_Return
            or event.key() == Qt.Key.Key_Enter
        ):
            self.accept()
        else:
            super().keyPressEvent(event)
