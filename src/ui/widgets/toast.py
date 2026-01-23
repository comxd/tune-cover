"""
Toast notification widget.

Provides non-blocking notifications that appear in the corner of the window
and automatically dismiss after a configurable duration.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from ...i18n import tr

# Path to icon resources
_ICONS_DIR = Path(__file__).parent.parent.parent.parent / "resources" / "icons"


@dataclass(frozen=True, slots=True)
class ToastStyle:
    """Style configuration for a toast type."""

    background_color: str
    text_color: str
    icon_name: str  # SVG filename without extension


class ToastType(Enum):
    """Toast notification types with associated styles."""

    SUCCESS = ToastStyle("#4CAF50", "#FFFFFF", "toast-success")
    ERROR = ToastStyle("#f44336", "#FFFFFF", "toast-error")
    WARNING = ToastStyle("#ff9800", "#FFFFFF", "toast-warning")
    INFO = ToastStyle("#4a90d9", "#FFFFFF", "toast-info")


def _load_toast_icon(icon_name: str, color: str, size: int = 24) -> QPixmap:
    """
    Load an SVG icon and colorize it.

    Args:
        icon_name: Name of the icon (without .svg extension)
        color: Hex color to apply to the icon
        size: Size in pixels for the icon

    Returns:
        Colorized QPixmap of the icon
    """
    icon_path = _ICONS_DIR / f"{icon_name}.svg"

    if not icon_path.exists():
        # Fallback to empty pixmap if icon not found
        return QPixmap(size, size)

    # Load the icon
    icon = QIcon(str(icon_path))
    pixmap = icon.pixmap(size, size)

    # Colorize the pixmap
    colored_pixmap = QPixmap(pixmap.size())
    colored_pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(colored_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(colored_pixmap.rect(), QColor(color))
    painter.end()

    return colored_pixmap


# Default toast configuration
DEFAULT_DURATION_MS = 4000
FADE_DURATION_MS = 300
TOAST_WIDTH = 350
TOAST_MAX_HEIGHT = 150


class Toast(QFrame):
    """
    Individual toast notification widget.

    Displays a message with an icon and optional close button.
    Supports fade-in/fade-out animations and auto-dismiss.

    Signals:
        closed: Emitted when the toast is closed (manual or auto)
    """

    closed = Signal()

    def __init__(
        self,
        message: str,
        toast_type: ToastType = ToastType.INFO,
        duration_ms: int = DEFAULT_DURATION_MS,
        parent=None,
    ):
        """
        Initialize the toast notification.

        Args:
            message: Text message to display
            toast_type: Type of toast (affects color and icon)
            duration_ms: Auto-dismiss delay in milliseconds (0 = no auto-dismiss)
            parent: Parent widget
        """
        super().__init__(parent)
        self._message = message
        self._toast_type = toast_type
        self._duration_ms = duration_ms
        self._is_closing = False

        self._setup_ui()
        self._setup_animations()
        self._apply_style()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        self.setFixedWidth(TOAST_WIDTH)
        self.setMaximumHeight(TOAST_MAX_HEIGHT)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # Main layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 8, 10)
        layout.setSpacing(10)

        # Icon label
        style = self._toast_type.value
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        icon_pixmap = _load_toast_icon(style.icon_name, style.text_color, 20)
        self._icon_label.setPixmap(icon_pixmap)
        layout.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignTop)

        # Message label - calculate required height for word-wrapped text
        self._message_label = QLabel(self._message)
        self._message_label.setWordWrap(True)

        # Calculate available width for text (total - margins - icon - button - spacing)
        text_width = TOAST_WIDTH - 12 - 8 - 24 - 24 - 10 - 10  # margins, icon, button, spacing
        self._message_label.setFixedWidth(text_width)

        layout.addWidget(self._message_label, 1, Qt.AlignmentFlag.AlignVCenter)

        # Close button
        self._close_btn = QPushButton("×")  # noqa: RUF001
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip(tr("Close"))
        self._close_btn.clicked.connect(self._on_close_clicked)
        layout.addWidget(self._close_btn, 0, Qt.AlignmentFlag.AlignTop)

    def _setup_animations(self) -> None:
        """Set up fade animations using QGraphicsOpacityEffect."""
        # Opacity effect for fade animations
        # Note: Can't use both shadow effect and opacity effect
        # since Qt only supports one graphics effect per widget
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        # Fade in animation
        self._fade_in_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in_anim.setDuration(FADE_DURATION_MS)
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in_anim.finished.connect(self._on_fade_in_finished)

        # Fade out animation
        self._fade_out_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out_anim.setDuration(FADE_DURATION_MS)
        self._fade_out_anim.setStartValue(1.0)
        self._fade_out_anim.setEndValue(0.0)
        self._fade_out_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out_anim.finished.connect(self._on_fade_out_finished)

        # Auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.fade_out)

    def _apply_style(self) -> None:
        """Apply styling based on toast type."""
        style = self._toast_type.value

        self.setStyleSheet(f"""
            Toast {{
                background-color: {style.background_color};
                border: none;
                border-radius: 6px;
            }}
            QLabel {{
                color: {style.text_color};
                background-color: transparent;
                font-size: 13px;
            }}
            QPushButton {{
                background-color: transparent;
                color: {style.text_color};
                border: none;
                border-radius: 12px;
                font-size: 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.2);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.3);
            }}
        """)

    def fade_in(self) -> None:
        """Start fade-in animation and show the toast."""
        self.show()
        self._fade_in_anim.start()

    def fade_out(self) -> None:
        """Start fade-out animation."""
        if self._is_closing:
            return
        self._is_closing = True
        self._dismiss_timer.stop()
        self._fade_out_anim.start()

    def _on_fade_in_finished(self) -> None:
        """Handle fade-in animation completion."""
        if self._duration_ms > 0:
            self._dismiss_timer.start(self._duration_ms)

    def _on_fade_out_finished(self) -> None:
        """Handle fade-out animation completion."""
        self.closed.emit()
        self.deleteLater()

    def _on_close_clicked(self) -> None:
        """Handle close button click."""
        self.fade_out()

    @property
    def toast_type(self) -> ToastType:
        """Get the toast type."""
        return self._toast_type

    @property
    def message(self) -> str:
        """Get the toast message."""
        return self._message
