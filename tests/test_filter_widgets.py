"""
Tests for the filter widgets.

Includes tests for SizeRangeFilter and MimeTypeFilter widgets.
"""

import pytest

# =============================================================================
# Tests for SizeRangeFilter Logic (without Qt)
# =============================================================================


class TestSizeRangeFilterLogic:
    """Tests for SizeRangeFilter business logic without Qt dependencies."""

    def test_get_range_bytes_conversion(self):
        """Test KB to bytes conversion logic."""

        # Simulate the conversion logic
        def get_range_bytes(min_kb, max_kb):
            return (min_kb * 1024, max_kb * 1024)

        assert get_range_bytes(0, 100) == (0, 102400)
        assert get_range_bytes(50, 500) == (51200, 512000)
        assert get_range_bytes(1, 1) == (1024, 1024)

    def test_matches_within_range(self):
        """Test matching logic for values within range."""

        def matches(size_bytes, min_kb, max_kb):
            if size_bytes is None:
                return False
            min_bytes = min_kb * 1024
            max_bytes = max_kb * 1024
            return min_bytes <= size_bytes <= max_bytes

        # 100 KB = 102400 bytes
        assert matches(102400, 50, 500) is True
        assert matches(51200, 50, 500) is True  # Exactly min
        assert matches(512000, 50, 500) is True  # Exactly max

    def test_matches_outside_range(self):
        """Test matching logic for values outside range."""

        def matches(size_bytes, min_kb, max_kb):
            if size_bytes is None:
                return False
            min_bytes = min_kb * 1024
            max_bytes = max_kb * 1024
            return min_bytes <= size_bytes <= max_bytes

        assert matches(10240, 50, 500) is False  # 10 KB < 50 KB
        assert matches(1024000, 50, 500) is False  # 1000 KB > 500 KB

    def test_matches_none_returns_false(self):
        """Test matching logic with None returns False."""

        def matches(size_bytes, min_kb, max_kb):
            if size_bytes is None:
                return False
            min_bytes = min_kb * 1024
            max_bytes = max_kb * 1024
            return min_bytes <= size_bytes <= max_bytes

        assert matches(None, 0, 10000) is False

    def test_matches_zero_range(self):
        """Test matching with zero as minimum."""

        def matches(size_bytes, min_kb, max_kb):
            if size_bytes is None:
                return False
            min_bytes = min_kb * 1024
            max_bytes = max_kb * 1024
            return min_bytes <= size_bytes <= max_bytes

        assert matches(0, 0, 100) is True
        assert matches(1, 0, 100) is True
        assert matches(102400, 0, 100) is True


# =============================================================================
# Tests for MimeTypeFilter Logic (without Qt)
# =============================================================================


class TestMimeTypeFilterLogic:
    """Tests for MimeTypeFilter business logic without Qt dependencies."""

    def test_matches_with_selected_type(self):
        """Test matching with selected MIME types."""

        def matches(mime_type, selected_types, is_inverted):
            if mime_type is None:
                return False
            if not selected_types:
                return is_inverted
            is_match = mime_type in selected_types
            return not is_match if is_inverted else is_match

        selected = ["image/jpeg", "image/png"]

        assert matches("image/jpeg", selected, False) is True
        assert matches("image/png", selected, False) is True
        assert matches("image/gif", selected, False) is False

    def test_matches_with_inverted_filter(self):
        """Test matching with inverted (exclusion) filter."""

        def matches(mime_type, selected_types, is_inverted):
            if mime_type is None:
                return False
            if not selected_types:
                return is_inverted
            is_match = mime_type in selected_types
            return not is_match if is_inverted else is_match

        selected = ["image/jpeg", "image/png"]

        # Inverted - should match types NOT in selection
        assert matches("image/jpeg", selected, True) is False
        assert matches("image/png", selected, True) is False
        assert matches("image/gif", selected, True) is True
        assert matches("image/webp", selected, True) is True

    def test_matches_with_no_selected_types(self):
        """Test matching with no types selected."""

        def matches(mime_type, selected_types, is_inverted):
            if mime_type is None:
                return False
            if not selected_types:
                return is_inverted
            is_match = mime_type in selected_types
            return not is_match if is_inverted else is_match

        # No types selected, not inverted - show nothing
        assert matches("image/jpeg", [], False) is False
        assert matches("image/png", [], False) is False

        # No types selected, inverted - show everything
        assert matches("image/jpeg", [], True) is True
        assert matches("image/png", [], True) is True

    def test_matches_with_none_mime_type(self):
        """Test matching with None MIME type."""

        def matches(mime_type, selected_types, is_inverted):
            if mime_type is None:
                return False
            if not selected_types:
                return is_inverted
            is_match = mime_type in selected_types
            return not is_match if is_inverted else is_match

        assert matches(None, ["image/jpeg"], False) is False
        assert matches(None, ["image/jpeg"], True) is False
        assert matches(None, [], False) is False
        assert matches(None, [], True) is False

    def test_all_mime_types_supported(self):
        """Test all supported MIME types."""
        mime_types = [
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/bmp",
        ]

        def matches(mime_type, selected_types, is_inverted):
            if mime_type is None:
                return False
            if not selected_types:
                return is_inverted
            is_match = mime_type in selected_types
            return not is_match if is_inverted else is_match

        # All types selected
        for mime_type in mime_types:
            assert matches(mime_type, mime_types, False) is True


# =============================================================================
# Tests with Qt (using pytest-qt)
# =============================================================================


@pytest.fixture
def size_filter(qtbot):
    """Create SizeRangeFilter widget."""
    from src.ui.widgets.filter_widgets import SizeRangeFilter

    widget = SizeRangeFilter()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def mime_filter(qtbot):
    """Create MimeTypeFilter widget."""
    from src.ui.widgets.filter_widgets import MimeTypeFilter

    widget = MimeTypeFilter()
    qtbot.addWidget(widget)
    return widget


class TestSizeRangeFilterWidget:
    """Tests for SizeRangeFilter widget with Qt."""

    def test_initial_values(self, size_filter):
        """Test initial spinbox values."""
        assert size_filter.min_spinbox.value() == 0
        assert size_filter.max_spinbox.value() == 10000

    def test_get_range_kb(self, size_filter):
        """Test get_range_kb returns correct tuple."""
        size_filter.min_spinbox.setValue(50)
        size_filter.max_spinbox.setValue(500)
        assert size_filter.get_range_kb() == (50, 500)

    def test_get_range_bytes(self, size_filter):
        """Test get_range_bytes returns correct values."""
        size_filter.min_spinbox.setValue(50)
        size_filter.max_spinbox.setValue(500)
        assert size_filter.get_range_bytes() == (51200, 512000)

    def test_matches_within_range(self, size_filter):
        """Test matches method with value in range."""
        size_filter.min_spinbox.setValue(50)
        size_filter.max_spinbox.setValue(500)
        # 100 KB = 102400 bytes
        assert size_filter.matches(102400) is True

    def test_matches_outside_range(self, size_filter):
        """Test matches method with value outside range."""
        size_filter.min_spinbox.setValue(50)
        size_filter.max_spinbox.setValue(500)
        # 10 KB = 10240 bytes
        assert size_filter.matches(10240) is False
        # 1000 KB = 1024000 bytes
        assert size_filter.matches(1024000) is False

    def test_matches_none_returns_false(self, size_filter):
        """Test matches method with None."""
        assert size_filter.matches(None) is False

    def test_filter_changed_signal(self, size_filter, qtbot):
        """Test that filter_changed signal is emitted on value change."""
        with qtbot.waitSignal(size_filter.filter_changed, timeout=1000):
            size_filter.min_spinbox.setValue(100)

    def test_spinbox_range(self, size_filter):
        """Test spinbox range constraints."""
        assert size_filter.min_spinbox.minimum() == 0
        assert size_filter.min_spinbox.maximum() == 10000
        assert size_filter.max_spinbox.minimum() == 0
        assert size_filter.max_spinbox.maximum() == 10000


class TestMimeTypeFilterWidget:
    """Tests for MimeTypeFilter widget with Qt."""

    def test_initial_all_checked(self, mime_filter):
        """Test that all checkboxes are initially checked."""
        for checkbox in mime_filter.checkboxes.values():
            assert checkbox.isChecked() is True

    def test_invert_initially_unchecked(self, mime_filter):
        """Test that invert checkbox is initially unchecked."""
        assert mime_filter.invert_checkbox.isChecked() is False

    def test_get_selected_types_all(self, mime_filter):
        """Test get_selected_types when all are selected."""
        selected = mime_filter.get_selected_types()
        expected = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]
        assert set(selected) == set(expected)

    def test_get_selected_types_partial(self, mime_filter):
        """Test get_selected_types with partial selection."""
        mime_filter.checkboxes["image/gif"].setChecked(False)
        mime_filter.checkboxes["image/webp"].setChecked(False)
        selected = mime_filter.get_selected_types()
        assert "image/jpeg" in selected
        assert "image/png" in selected
        assert "image/gif" not in selected
        assert "image/webp" not in selected

    def test_is_inverted(self, mime_filter):
        """Test is_inverted method."""
        assert mime_filter.is_inverted() is False
        mime_filter.invert_checkbox.setChecked(True)
        assert mime_filter.is_inverted() is True

    def test_matches_selected_type(self, mime_filter):
        """Test matches with selected type."""
        assert mime_filter.matches("image/jpeg") is True
        assert mime_filter.matches("image/png") is True

    def test_matches_unselected_type(self, mime_filter):
        """Test matches with unselected type."""
        mime_filter.checkboxes["image/gif"].setChecked(False)
        assert mime_filter.matches("image/gif") is False

    def test_matches_inverted(self, mime_filter):
        """Test matches with inverted filter."""
        mime_filter.invert_checkbox.setChecked(True)
        # Now selected types should NOT match
        assert mime_filter.matches("image/jpeg") is False
        # Unselect one type - it should now match (not in exclusion list)
        mime_filter.checkboxes["image/gif"].setChecked(False)
        assert mime_filter.matches("image/gif") is True

    def test_matches_none_returns_false(self, mime_filter):
        """Test matches with None."""
        assert mime_filter.matches(None) is False

    def test_matches_unknown_type(self, mime_filter):
        """Test matches with unknown MIME type."""
        assert mime_filter.matches("image/tiff") is False

    def test_select_all(self, mime_filter):
        """Test select_all method."""
        # First uncheck some
        mime_filter.checkboxes["image/jpeg"].setChecked(False)
        mime_filter.checkboxes["image/png"].setChecked(False)

        # Select all
        mime_filter.select_all()

        for checkbox in mime_filter.checkboxes.values():
            assert checkbox.isChecked() is True

    def test_select_none(self, mime_filter):
        """Test select_none method."""
        mime_filter.select_none()

        for checkbox in mime_filter.checkboxes.values():
            assert checkbox.isChecked() is False

    def test_filter_changed_signal_on_type_change(self, mime_filter, qtbot):
        """Test that filter_changed signal is emitted on type change."""
        with qtbot.waitSignal(mime_filter.filter_changed, timeout=1000):
            mime_filter.checkboxes["image/jpeg"].setChecked(False)

    def test_filter_changed_signal_on_invert_change(self, mime_filter, qtbot):
        """Test that filter_changed signal is emitted on invert change."""
        with qtbot.waitSignal(mime_filter.filter_changed, timeout=1000):
            mime_filter.invert_checkbox.setChecked(True)

    def test_no_types_selected_not_inverted(self, mime_filter):
        """Test matches when no types selected and not inverted."""
        mime_filter.select_none()
        # Should match nothing
        assert mime_filter.matches("image/jpeg") is False

    def test_no_types_selected_inverted(self, mime_filter):
        """Test matches when no types selected and inverted."""
        mime_filter.select_none()
        mime_filter.invert_checkbox.setChecked(True)
        # Should match everything
        assert mime_filter.matches("image/jpeg") is True
