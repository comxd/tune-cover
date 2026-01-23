"""
Advanced filter widgets for library view.

Provides widgets for filtering albums by cover size and MIME type.
"""

from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSpinBox, QWidget

from ...i18n import tr


class SizeRangeFilter(QWidget):
    """Widget for filtering by cover file size range (in KB)."""

    filter_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel(tr("Size:")))

        self.min_spinbox = QSpinBox()
        self.min_spinbox.setRange(0, 10000)
        self.min_spinbox.setValue(0)
        self.min_spinbox.setSuffix(" KB")
        self.min_spinbox.setToolTip(tr("Minimum file size"))
        self.min_spinbox.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.min_spinbox)

        layout.addWidget(QLabel("-"))

        self.max_spinbox = QSpinBox()
        self.max_spinbox.setRange(0, 10000)
        self.max_spinbox.setValue(10000)
        self.max_spinbox.setSuffix(" KB")
        self.max_spinbox.setToolTip(tr("Maximum file size"))
        self.max_spinbox.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.max_spinbox)

    def _on_value_changed(self):
        """Emit filter_changed when values change."""
        self.filter_changed.emit()

    def get_range_kb(self):
        """Get size range in KB."""
        return (self.min_spinbox.value(), self.max_spinbox.value())

    def get_range_bytes(self):
        """Get size range in bytes."""
        min_kb, max_kb = self.get_range_kb()
        return (min_kb * 1024, max_kb * 1024)

    def matches(self, size_bytes):
        """
        Check if size is within the configured range.

        Args:
            size_bytes: File size in bytes

        Returns:
            True if size is within range, False otherwise
        """
        if size_bytes is None:
            return False
        min_bytes, max_bytes = self.get_range_bytes()
        return min_bytes <= size_bytes <= max_bytes


class MimeTypeFilter(QWidget):
    """Widget for filtering by cover MIME type with multi-select and invert option."""

    filter_changed = Signal()

    MIME_TYPES: ClassVar[list[tuple[str, str]]] = [
        ("image/jpeg", "JPEG"),
        ("image/png", "PNG"),
        ("image/gif", "GIF"),
        ("image/webp", "WebP"),
        ("image/bmp", "BMP"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkboxes = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel(tr("Type:")))

        # MIME type checkboxes
        for mime_type, label in self.MIME_TYPES:
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._on_checkbox_changed)
            self.checkboxes[mime_type] = checkbox
            layout.addWidget(checkbox)

        # Separator
        layout.addSpacing(8)

        # Invert checkbox (exclusion mode)
        self.invert_checkbox = QCheckBox(tr("Exclude"))
        self.invert_checkbox.setToolTip(
            tr("Invert filter: show albums that do NOT match selected types")
        )
        self.invert_checkbox.toggled.connect(self._on_checkbox_changed)
        layout.addWidget(self.invert_checkbox)

    def _on_checkbox_changed(self):
        """Emit filter_changed when any checkbox changes."""
        self.filter_changed.emit()

    def get_selected_types(self):
        """Get list of selected MIME types."""
        return [mime for mime, cb in self.checkboxes.items() if cb.isChecked()]

    def is_inverted(self):
        """Check if filter is in exclusion mode."""
        return self.invert_checkbox.isChecked()

    def matches(self, mime_type):
        """
        Check if MIME type matches the filter.

        Args:
            mime_type: MIME type string (e.g., 'image/jpeg')

        Returns:
            True if matches filter criteria, False otherwise
        """
        if mime_type is None:
            return False

        selected = self.get_selected_types()
        if not selected:
            # No types selected - show nothing (or everything if inverted)
            return self.is_inverted()

        is_match = mime_type in selected
        return not is_match if self.is_inverted() else is_match

    def select_all(self):
        """Select all MIME types."""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)

    def select_none(self):
        """Deselect all MIME types."""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)
