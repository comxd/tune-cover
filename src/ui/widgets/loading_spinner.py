"""
Animated loading spinner widget.
"""

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class LoadingSpinner(QWidget):
    """
    Animated loading spinner widget.

    Displays a rotating arc that indicates loading state.
    Can be overlaid on other widgets or used standalone.
    """

    def __init__(self, size: int = 40, color: str = "#4a90d9", parent=None):
        """
        Initialize the loading spinner.

        Args:
            size: Diameter of the spinner in pixels
            color: Color of the spinner arc (hex color string)
            parent: Parent widget
        """
        super().__init__(parent)
        self._size = size
        self._color = QColor(color)
        self._angle = 0
        self._arc_length = 270  # Arc spans 270 degrees
        self._line_width = max(3, size // 10)

        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Animation timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.setInterval(16)  # ~60 FPS

    def start(self):
        """Start the spinner animation."""
        self._timer.start()
        self.show()

    def stop(self):
        """Stop the spinner animation and hide."""
        self._timer.stop()
        self.hide()

    def is_spinning(self) -> bool:
        """Check if the spinner is currently animating."""
        return self._timer.isActive()

    def set_color(self, color: str):
        """Set the spinner color."""
        self._color = QColor(color)
        self.update()

    def _rotate(self):
        """Rotate the spinner by one step."""
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event):
        """Paint the spinner arc."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Calculate the drawing rectangle
        margin = self._line_width // 2 + 1
        rect = QRectF(margin, margin, self._size - 2 * margin, self._size - 2 * margin)

        # Set up the pen
        pen = QPen(self._color)
        pen.setWidth(self._line_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Draw the arc
        # Qt uses 1/16th of a degree for angles
        start_angle = self._angle * 16
        span_angle = self._arc_length * 16
        painter.drawArc(rect, start_angle, span_angle)

        painter.end()
