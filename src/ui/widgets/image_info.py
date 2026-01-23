"""
Image information label widget.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class ImageInfoLabel(QLabel):
    """
    Label displaying image dimensions and file size.

    Displays formatted information like "1000x1000 - 245 KB"
    in a compact, styled format.
    """

    def __init__(self, parent=None):
        """
        Initialize the image info label.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font-size: 9px; color: #888;")
        self._width = None
        self._height = None
        self._size_bytes = None

    def set_image_info(self, width: int, height: int, size_bytes: int):
        """
        Update the displayed image information.

        Args:
            width: Image width in pixels
            height: Image height in pixels
            size_bytes: Image file size in bytes
        """
        self._width = width
        self._height = height
        self._size_bytes = size_bytes
        self._update_text()

    def set_dimensions(self, width: int, height: int):
        """
        Update only the dimensions.

        Args:
            width: Image width in pixels
            height: Image height in pixels
        """
        self._width = width
        self._height = height
        self._update_text()

    def set_size(self, size_bytes: int):
        """
        Update only the file size.

        Args:
            size_bytes: Image file size in bytes
        """
        self._size_bytes = size_bytes
        self._update_text()

    def clear_info(self):
        """Clear the displayed information."""
        self._width = None
        self._height = None
        self._size_bytes = None
        self.clear()

    def _update_text(self):
        """Update the label text based on current values."""
        parts = []

        if self._width and self._height:
            parts.append(f"{self._width}x{self._height}")

        if self._size_bytes:
            size_kb = self._size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                parts.append(f"{size_mb:.1f} MB")
            else:
                parts.append(f"{size_kb:.0f} KB")

        self.setText(" - ".join(parts))

    @property
    def dimensions_str(self) -> str:
        """Get the dimensions as a string."""
        if self._width and self._height:
            return f"{self._width}x{self._height}"
        return ""

    @property
    def size_str(self) -> str:
        """Get the size as a formatted string."""
        if self._size_bytes:
            size_kb = self._size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                return f"{size_mb:.1f} MB"
            return f"{size_kb:.0f} KB"
        return ""
