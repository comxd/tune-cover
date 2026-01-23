"""
Toast notification manager.

Manages the lifecycle and positioning of toast notifications.
Provides a simple API for showing toasts from anywhere in the application.
"""

import logging
from weakref import ref

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QMainWindow

from .toast import DEFAULT_DURATION_MS, Toast, ToastType

logger = logging.getLogger(__name__)

# Toast positioning configuration
TOAST_MARGIN = 20  # Distance from window edge
TOAST_SPACING = 10  # Spacing between stacked toasts
MAX_VISIBLE_TOASTS = 5


class ToastManager(QObject):
    """
    Manages toast notifications for a main window.

    Handles toast creation, positioning, stacking, and lifecycle management.
    Toasts are displayed in the bottom-right corner of the parent window
    and stack vertically when multiple are visible.

    Usage:
        manager = ToastManager(main_window)
        manager.show_success("Operation completed!")
        manager.show_error("Something went wrong")
    """

    _instance: "ToastManager | None" = None

    def __init__(self, parent_window: QMainWindow):
        """
        Initialize the toast manager.

        Args:
            parent_window: Main window where toasts will be displayed
        """
        super().__init__(parent_window)
        self._parent_window_ref = ref(parent_window)
        self._toasts: list[Toast] = []
        self._queue: list[tuple] = []  # Queued toasts when max is reached

        # Install event filter to handle window resize
        parent_window.installEventFilter(self)

    @classmethod
    def get_instance(cls, parent_window: QMainWindow | None = None) -> "ToastManager":
        """
        Get the singleton instance of ToastManager.

        Args:
            parent_window: Main window (required on first call)

        Returns:
            The ToastManager instance

        Raises:
            ValueError: If no instance exists and parent_window is not provided
        """
        if cls._instance is None:
            if parent_window is None:
                raise ValueError("parent_window is required when creating ToastManager instance")
            cls._instance = cls(parent_window)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Primarily for testing."""
        cls._instance = None

    @property
    def _parent_window(self) -> QMainWindow | None:
        """Get the parent window, or None if it was deleted."""
        return self._parent_window_ref()

    def show(
        self,
        message: str,
        toast_type: ToastType = ToastType.INFO,
        duration_ms: int = DEFAULT_DURATION_MS,
    ) -> Toast | None:
        """
        Show a toast notification.

        Args:
            message: Text message to display
            toast_type: Type of toast (SUCCESS, ERROR, WARNING, INFO)
            duration_ms: Auto-dismiss delay in milliseconds

        Returns:
            The created Toast widget, or None if queued/failed
        """
        parent = self._parent_window
        if parent is None:
            logger.warning("Cannot show toast: parent window no longer exists")
            return None

        # Queue toast if at max capacity
        if len(self._toasts) >= MAX_VISIBLE_TOASTS:
            self._queue.append((message, toast_type, duration_ms))
            # Remove oldest toast to make room
            if self._toasts:
                self._toasts[0].fade_out()
            return None

        return self._create_toast(message, toast_type, duration_ms)

    def _create_toast(
        self,
        message: str,
        toast_type: ToastType,
        duration_ms: int,
    ) -> Toast | None:
        """Create and display a toast notification."""
        parent = self._parent_window
        if parent is None:
            return None

        # Create toast widget
        toast = Toast(message, toast_type, duration_ms, parent)
        toast.closed.connect(lambda: self._on_toast_closed(toast))

        # Add to list and position
        self._toasts.append(toast)
        self._reposition_toasts()

        # Start fade-in animation
        toast.fade_in()

        return toast

    def _on_toast_closed(self, toast: Toast) -> None:
        """Handle toast closure."""
        if toast in self._toasts:
            self._toasts.remove(toast)

        # Reposition remaining toasts
        self._reposition_toasts()

        # Show queued toast if any
        if self._queue:
            message, toast_type, duration_ms = self._queue.pop(0)
            # Delay slightly to allow animation to complete
            QTimer.singleShot(50, lambda: self._create_toast(message, toast_type, duration_ms))

    def _reposition_toasts(self) -> None:
        """Reposition all visible toasts in the bottom-right corner."""
        parent = self._parent_window
        if parent is None:
            return

        # Get parent geometry (use central widget if available)
        if hasattr(parent, "centralWidget") and parent.centralWidget():
            container = parent.centralWidget()
            # Map to global coordinates then back to parent
            global_pos = container.mapToGlobal(QPoint(0, 0))
            local_pos = parent.mapFromGlobal(global_pos)
            container_x = local_pos.x()
            container_y = local_pos.y()
            container_width = container.width()
            container_height = container.height()
        else:
            container_x = 0
            container_y = 0
            container_width = parent.width()
            container_height = parent.height()

        # Position toasts from bottom-right, stacking upward
        current_y = container_y + container_height - TOAST_MARGIN

        for toast in reversed(self._toasts):
            toast.adjustSize()
            toast_height = toast.sizeHint().height()

            # Calculate position
            x = container_x + container_width - toast.width() - TOAST_MARGIN
            y = current_y - toast_height

            toast.move(x, y)
            toast.raise_()

            current_y = y - TOAST_SPACING

    def eventFilter(self, obj: QObject, event) -> bool:
        """Handle parent window events."""
        if obj == self._parent_window and event.type() == QEvent.Type.Resize:
            self._reposition_toasts()

        return super().eventFilter(obj, event)

    # Convenience methods for common toast types

    def show_success(self, message: str, duration_ms: int = DEFAULT_DURATION_MS) -> Toast | None:
        """Show a success toast (green)."""
        return self.show(message, ToastType.SUCCESS, duration_ms)

    def show_error(self, message: str, duration_ms: int = DEFAULT_DURATION_MS) -> Toast | None:
        """Show an error toast (red)."""
        return self.show(message, ToastType.ERROR, duration_ms)

    def show_warning(self, message: str, duration_ms: int = DEFAULT_DURATION_MS) -> Toast | None:
        """Show a warning toast (orange)."""
        return self.show(message, ToastType.WARNING, duration_ms)

    def show_info(self, message: str, duration_ms: int = DEFAULT_DURATION_MS) -> Toast | None:
        """Show an info toast (blue)."""
        return self.show(message, ToastType.INFO, duration_ms)

    def clear_all(self) -> None:
        """Close all visible toasts immediately."""
        self._queue.clear()
        for toast in self._toasts[:]:  # Copy list to avoid modification during iteration
            toast.fade_out()
