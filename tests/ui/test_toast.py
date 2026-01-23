"""
Tests for the toast notification system.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QMainWindow

from src.ui.widgets.toast import (
    _ICONS_DIR,
    DEFAULT_DURATION_MS,
    FADE_DURATION_MS,
    Toast,
    ToastStyle,
    ToastType,
    _load_toast_icon,
)
from src.ui.widgets.toast_manager import (
    MAX_VISIBLE_TOASTS,
    TOAST_MARGIN,
    TOAST_SPACING,
    ToastManager,
)


class TestToastType:
    """Tests for ToastType enum."""

    def test_toast_types_have_styles(self):
        """All toast types should have valid styles."""
        for toast_type in ToastType:
            style = toast_type.value
            assert isinstance(style, ToastStyle)
            assert style.background_color.startswith("#")
            assert style.text_color.startswith("#")
            assert len(style.icon_name) > 0

    def test_success_is_green(self):
        """Success toast should be green."""
        assert ToastType.SUCCESS.value.background_color == "#4CAF50"

    def test_error_is_red(self):
        """Error toast should be red."""
        assert ToastType.ERROR.value.background_color == "#f44336"

    def test_warning_is_orange(self):
        """Warning toast should be orange."""
        assert ToastType.WARNING.value.background_color == "#ff9800"

    def test_info_is_blue(self):
        """Info toast should be blue."""
        assert ToastType.INFO.value.background_color == "#4a90d9"


class TestToastIcons:
    """Tests for toast SVG icons."""

    def test_icons_directory_exists(self):
        """Icons directory should exist."""
        assert _ICONS_DIR.exists()
        assert _ICONS_DIR.is_dir()

    def test_all_toast_icons_exist(self):
        """All toast type icons should exist as SVG files."""
        for toast_type in ToastType:
            icon_name = toast_type.value.icon_name
            icon_path = _ICONS_DIR / f"{icon_name}.svg"
            assert icon_path.exists(), f"Missing icon: {icon_path}"

    def test_load_toast_icon_returns_pixmap(self, qtbot):
        """_load_toast_icon should return a QPixmap."""
        pixmap = _load_toast_icon("toast-info", "#FFFFFF", 24)
        assert isinstance(pixmap, QPixmap)
        assert not pixmap.isNull()

    def test_load_toast_icon_respects_size(self, qtbot):
        """_load_toast_icon should create pixmap of specified size."""
        pixmap = _load_toast_icon("toast-success", "#FFFFFF", 32)
        assert pixmap.width() == 32
        assert pixmap.height() == 32

    def test_load_toast_icon_missing_returns_empty_pixmap(self, qtbot):
        """_load_toast_icon should return empty pixmap for missing icons."""
        pixmap = _load_toast_icon("nonexistent-icon", "#FFFFFF", 24)
        assert isinstance(pixmap, QPixmap)
        # Should return an empty pixmap of the requested size
        assert pixmap.width() == 24
        assert pixmap.height() == 24

    def test_load_toast_icon_all_types(self, qtbot):
        """All toast types should load icons successfully."""
        for toast_type in ToastType:
            style = toast_type.value
            pixmap = _load_toast_icon(style.icon_name, style.text_color, 20)
            assert isinstance(pixmap, QPixmap)
            assert not pixmap.isNull(), f"Failed to load icon for {toast_type.name}"


class TestToast:
    """Tests for Toast widget."""

    def test_create_toast(self, qtbot):
        """Test basic toast creation."""
        toast = Toast("Test message", ToastType.INFO)
        qtbot.addWidget(toast)

        assert toast.message == "Test message"
        assert toast.toast_type == ToastType.INFO

    def test_toast_types(self, qtbot):
        """Test creating toasts of different types."""
        for toast_type in ToastType:
            toast = Toast("Test", toast_type)
            qtbot.addWidget(toast)
            assert toast.toast_type == toast_type

    def test_toast_fade_in(self, qtbot):
        """Test fade-in animation starts."""
        toast = Toast("Test", ToastType.SUCCESS)
        qtbot.addWidget(toast)

        toast.fade_in()
        assert toast.isVisible()

    def test_toast_fade_out_emits_closed(self, qtbot):
        """Test fade-out emits closed signal."""
        toast = Toast("Test", ToastType.INFO, duration_ms=0)
        qtbot.addWidget(toast)

        toast.show()
        toast._opacity_effect.setOpacity(1.0)

        with qtbot.waitSignal(toast.closed, timeout=FADE_DURATION_MS + 500):
            toast.fade_out()

    def test_toast_auto_dismiss(self, qtbot):
        """Test toast auto-dismisses after duration."""
        # Use short duration for faster test
        duration = 100
        toast = Toast("Test", ToastType.INFO, duration_ms=duration)
        qtbot.addWidget(toast)

        with qtbot.waitSignal(toast.closed, timeout=duration + FADE_DURATION_MS + 500):
            toast.fade_in()

    def test_toast_no_auto_dismiss_when_duration_zero(self, qtbot):
        """Test toast doesn't auto-dismiss when duration is 0."""
        toast = Toast("Test", ToastType.INFO, duration_ms=0)
        qtbot.addWidget(toast)

        toast.fade_in()

        # Wait to ensure no auto-dismiss
        qtbot.wait(200)
        # Toast should still be visible (not closing)
        assert not toast._is_closing

    def test_close_button_triggers_fade_out(self, qtbot):
        """Test close button click triggers fade out."""
        toast = Toast("Test", ToastType.INFO, duration_ms=0)
        qtbot.addWidget(toast)
        toast.show()
        toast._opacity_effect.setOpacity(1.0)

        with qtbot.waitSignal(toast.closed, timeout=FADE_DURATION_MS + 500):
            toast._close_btn.click()

    def test_toast_word_wrap_enabled(self, qtbot):
        """Test message label has word wrap enabled."""
        toast = Toast("Test message", ToastType.INFO)
        qtbot.addWidget(toast)

        assert toast._message_label.wordWrap() is True

    def test_toast_height_adapts_to_long_text(self, qtbot):
        """Test toast height increases for long multi-line messages."""
        short_toast = Toast("Short", ToastType.INFO)
        qtbot.addWidget(short_toast)
        short_toast.show()
        short_toast.adjustSize()

        long_message = (
            "This is a very long message that should wrap to multiple lines "
            "and cause the toast to increase its height to accommodate all the text."
        )
        long_toast = Toast(long_message, ToastType.INFO)
        qtbot.addWidget(long_toast)
        long_toast.show()
        long_toast.adjustSize()

        # Long toast should be taller than short toast
        assert long_toast.sizeHint().height() > short_toast.sizeHint().height()

    def test_toast_respects_max_height(self, qtbot):
        """Test toast doesn't exceed maximum height."""
        from src.ui.widgets.toast import TOAST_MAX_HEIGHT

        very_long_message = "Very long message. " * 50
        toast = Toast(very_long_message, ToastType.INFO)
        qtbot.addWidget(toast)
        toast.show()
        toast.adjustSize()

        assert toast.height() <= TOAST_MAX_HEIGHT

    def test_toast_has_fixed_width(self, qtbot):
        """Test toast maintains fixed width regardless of message length."""
        from src.ui.widgets.toast import TOAST_WIDTH

        short_toast = Toast("Hi", ToastType.INFO)
        qtbot.addWidget(short_toast)
        short_toast.show()

        long_toast = Toast("A" * 200, ToastType.INFO)
        qtbot.addWidget(long_toast)
        long_toast.show()

        assert short_toast.width() == TOAST_WIDTH
        assert long_toast.width() == TOAST_WIDTH

    def test_toast_icon_aligned_top(self, qtbot):
        """Test icon stays at top for multi-line messages."""
        long_message = "Line 1\nLine 2\nLine 3\nLine 4"
        toast = Toast(long_message, ToastType.INFO)
        qtbot.addWidget(toast)
        toast.show()
        toast.adjustSize()

        # Icon should be near the top of the toast
        icon_top = toast._icon_label.y()
        toast_top = toast.contentsMargins().top()
        # Icon should be within reasonable distance from top (layout margins)
        assert icon_top <= toast_top + 15


class TestToastManager:
    """Tests for ToastManager."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        ToastManager.reset_instance()
        yield
        ToastManager.reset_instance()

    def test_singleton_pattern(self, qtbot):
        """Test ToastManager is a singleton."""
        window = QMainWindow()
        qtbot.addWidget(window)

        manager1 = ToastManager.get_instance(window)
        manager2 = ToastManager.get_instance()

        assert manager1 is manager2

    def test_singleton_requires_window_first_call(self):
        """Test first call to get_instance requires window."""
        with pytest.raises(ValueError):
            ToastManager.get_instance()

    def test_show_toast(self, qtbot):
        """Test showing a toast."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)
        toast = manager.show("Test message", ToastType.INFO)

        assert toast is not None
        assert toast.message == "Test message"
        assert len(manager._toasts) == 1

    def test_convenience_methods(self, qtbot):
        """Test convenience methods create correct toast types."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)

        # Test each convenience method
        toast_success = manager.show_success("Success")
        assert toast_success.toast_type == ToastType.SUCCESS

        toast_error = manager.show_error("Error")
        assert toast_error.toast_type == ToastType.ERROR

        toast_warning = manager.show_warning("Warning")
        assert toast_warning.toast_type == ToastType.WARNING

        toast_info = manager.show_info("Info")
        assert toast_info.toast_type == ToastType.INFO

    def test_max_visible_toasts(self, qtbot):
        """Test max visible toasts limit."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)

        # Show more than max toasts
        for i in range(MAX_VISIBLE_TOASTS + 2):
            manager.show(f"Toast {i}", ToastType.INFO, duration_ms=0)

        # Wait for animations
        qtbot.wait(100)

        # Should be limited to max (minus ones that were removed)
        assert len(manager._toasts) <= MAX_VISIBLE_TOASTS

    def test_toast_queue(self, qtbot):
        """Test toasts are queued when max is reached."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)

        # Fill up visible toasts
        for i in range(MAX_VISIBLE_TOASTS):
            manager.show(f"Toast {i}", ToastType.INFO, duration_ms=0)

        # Add one more - should be queued
        manager.show("Queued toast", ToastType.INFO, duration_ms=0)

        # Queue should have one item or oldest should be fading out
        # (exact behavior depends on timing)
        total = len(manager._toasts) + len(manager._queue)
        assert total >= MAX_VISIBLE_TOASTS

    def test_clear_all(self, qtbot):
        """Test clearing all toasts."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)

        # Show some toasts
        for i in range(3):
            manager.show(f"Toast {i}", ToastType.INFO, duration_ms=0)

        qtbot.wait(50)

        # Clear all
        manager.clear_all()

        # Wait for fade out animations
        qtbot.wait(FADE_DURATION_MS + 100)

        assert len(manager._toasts) == 0
        assert len(manager._queue) == 0

    def test_toast_positioning(self, qtbot):
        """Test toasts are positioned in bottom-right corner."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)
        toast = manager.show("Test", ToastType.INFO, duration_ms=0)

        qtbot.wait(50)

        # Toast should be near the right edge
        assert toast.x() > window.width() // 2

        # Toast should be near the bottom
        assert toast.y() > window.height() // 2

    def test_toast_stacking(self, qtbot):
        """Test multiple toasts stack vertically."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)

        toast1 = manager.show("Toast 1", ToastType.INFO, duration_ms=0)
        toast2 = manager.show("Toast 2", ToastType.INFO, duration_ms=0)

        qtbot.wait(50)

        # First toast should be above second (newest at bottom, stacking up)
        assert toast1.y() < toast2.y()

    def test_reposition_on_window_resize(self, qtbot):
        """Test toasts reposition when window is resized."""
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qtbot.addWidget(window)

        manager = ToastManager.get_instance(window)
        toast = manager.show("Test", ToastType.INFO, duration_ms=0)

        qtbot.wait(50)
        initial_x = toast.x()

        # Resize window
        window.resize(1000, 600)
        qtbot.wait(50)

        # Toast should have moved right
        assert toast.x() > initial_x
