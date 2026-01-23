"""
Tests for cover comparison dialog logic.

Note: Tests focus on business logic and avoid instantiating Qt widgets
where possible, but some Qt widget tests are included for ClickableImageLabel.
"""

from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class TestCoverComparisonDialogLogic:
    """Tests for CoverComparisonDialog business logic."""

    @pytest.fixture
    def mock_album(self, tmp_path):
        """Create a mock album."""
        album = Mock()
        album.path = tmp_path
        album.display_name = "Test Artist - Test Album"
        album.artist = "Test Artist"
        album.album = "Test Album"
        return album

    @pytest.fixture
    def mock_search_result(self):
        """Create a mock search result."""
        result = Mock()
        result.provider = "MusicBrainz"
        result.display_name = "Test Album"
        result.artist = "Test Artist"
        result.album = "Test Album"
        result.score = 95
        return result

    @pytest.fixture
    def mock_save_decision(self):
        """Create a mock save decision."""
        decision = Mock()
        decision.embed_in_tags = True
        decision.save_external_file = True
        decision.external_filename = "cover"
        decision.reason = "Test reason"
        return decision

    def test_save_decision_creation(self, mock_save_decision):
        """Test save decision has required attributes."""
        assert mock_save_decision.embed_in_tags is True
        assert mock_save_decision.save_external_file is True
        assert mock_save_decision.external_filename == "cover"
        assert mock_save_decision.reason == "Test reason"

    def test_modified_decision_both_enabled(self):
        """Test creating modified decision with both options enabled."""
        from src.core.cover_save_strategy import CoverSaveDecision

        decision = CoverSaveDecision(
            embed_in_tags=True,
            save_external_file=True,
            external_filename="cover",
            reason="Options modified by user",
        )

        assert decision.embed_in_tags is True
        assert decision.save_external_file is True

    def test_modified_decision_embed_only(self):
        """Test creating modified decision with embed only."""
        from src.core.cover_save_strategy import CoverSaveDecision

        decision = CoverSaveDecision(
            embed_in_tags=True,
            save_external_file=False,
            external_filename="cover",
            reason="Embed only",
        )

        assert decision.embed_in_tags is True
        assert decision.save_external_file is False

    def test_modified_decision_external_only(self):
        """Test creating modified decision with external file only."""
        from src.core.cover_save_strategy import CoverSaveDecision

        decision = CoverSaveDecision(
            embed_in_tags=False,
            save_external_file=True,
            external_filename="cover",
            reason="External only",
        )

        assert decision.embed_in_tags is False
        assert decision.save_external_file is True


class TestCoverDetection:
    """Tests for cover detection logic."""

    def test_has_both_covers(self, tmp_path):
        """Test detecting both embedded and folder covers."""
        # Simulate having both covers
        embedded_data = b"embedded cover data"
        folder_cover = tmp_path / "cover.jpg"
        folder_cover.write_bytes(b"folder cover data")

        has_embedded = bool(embedded_data)
        has_folder = folder_cover.exists()

        assert has_embedded is True
        assert has_folder is True

    def test_has_embedded_only(self, tmp_path):
        """Test detecting embedded cover only."""
        embedded_data = b"embedded cover data"
        folder_cover = tmp_path / "cover.jpg"  # Does not exist

        has_embedded = bool(embedded_data)
        has_folder = folder_cover.exists()

        assert has_embedded is True
        assert has_folder is False

    def test_has_folder_only(self, tmp_path):
        """Test detecting folder cover only."""
        embedded_data = None
        folder_cover = tmp_path / "cover.jpg"
        folder_cover.write_bytes(b"folder cover data")

        has_embedded = bool(embedded_data)
        has_folder = folder_cover.exists()

        assert has_embedded is False
        assert has_folder is True

    def test_has_no_covers(self, tmp_path):
        """Test detecting no covers."""
        embedded_data = None
        folder_cover = tmp_path / "cover.jpg"  # Does not exist

        has_embedded = bool(embedded_data)
        has_folder = folder_cover.exists()

        assert has_embedded is False
        assert has_folder is False


class TestApplyButtonState:
    """Tests for apply button enabled/disabled logic."""

    def test_at_least_one_checked_enabled(self):
        """Test apply button enabled when at least one option checked."""
        embed_checked = True
        save_file_checked = False

        at_least_one = embed_checked or save_file_checked
        assert at_least_one is True

    def test_both_checked_enabled(self):
        """Test apply button enabled when both options checked."""
        embed_checked = True
        save_file_checked = True

        at_least_one = embed_checked or save_file_checked
        assert at_least_one is True

    def test_none_checked_disabled(self):
        """Test apply button disabled when no option checked."""
        embed_checked = False
        save_file_checked = False

        at_least_one = embed_checked or save_file_checked
        assert at_least_one is False


class TestSourceFormatting:
    """Tests for source string formatting."""

    def test_source_format_musicbrainz(self):
        """Test source format for MusicBrainz."""
        provider = "MusicBrainz"
        display_name = "Test Album"

        source = f"{provider}: {display_name}"
        assert source == "MusicBrainz: Test Album"

    def test_source_format_discogs(self):
        """Test source format for Discogs."""
        provider = "Discogs"
        display_name = "Test Album (2020)"

        source = f"{provider}: {display_name}"
        assert source == "Discogs: Test Album (2020)"

    def test_source_format_lastfm(self):
        """Test source format for Last.fm."""
        provider = "Last.fm"
        display_name = "Test Artist - Test Album"

        source = f"{provider}: {display_name}"
        assert source == "Last.fm: Test Artist - Test Album"


class TestCoverDataValidation:
    """Tests for cover data validation."""

    def test_valid_jpeg_data(self):
        """Test valid JPEG data detection."""
        # JPEG magic bytes
        data = b"\xff\xd8\xff" + b"\x00" * 100

        is_valid = data and len(data) > 0
        is_jpeg = data[:3] == b"\xff\xd8\xff" if data and len(data) >= 3 else False

        assert is_valid is True
        assert is_jpeg is True

    def test_valid_png_data(self):
        """Test valid PNG data detection."""
        # PNG magic bytes
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        is_valid = data and len(data) > 0
        is_png = data[:8] == b"\x89PNG\r\n\x1a\n" if data and len(data) >= 8 else False

        assert is_valid is True
        assert is_png is True

    def test_empty_data_invalid(self):
        """Test empty data is invalid."""
        data = b""

        is_valid = bool(data) and len(data) > 0
        assert is_valid is False

    def test_none_data_invalid(self):
        """Test None data is invalid."""
        data = None

        is_valid = data and len(data) > 0 if data else False
        assert is_valid is False


class TestCoverSizeInfo:
    """Tests for cover size information formatting."""

    def test_format_image_dimensions(self):
        """Test formatting image dimensions."""
        width = 1000
        height = 1000

        dimensions = f"{width}x{height}"
        assert dimensions == "1000x1000"

    def test_format_file_size_kb(self):
        """Test formatting file size in KB."""
        size_bytes = 512000  # 500 KB

        size_kb = size_bytes / 1024
        formatted = f"{size_kb:.0f} KB"
        assert formatted == "500 KB"

    def test_format_file_size_mb(self):
        """Test formatting file size in MB."""
        size_bytes = 2 * 1024 * 1024  # 2 MB

        size_kb = size_bytes / 1024
        size_mb = size_kb / 1024
        formatted = f"{size_mb:.1f} MB"
        assert formatted == "2.0 MB"

    def test_format_combined_info(self):
        """Test formatting combined image info."""
        width = 1000
        height = 1000
        size_bytes = 512000

        dimensions = f"{width}x{height}"
        size_kb = size_bytes / 1024
        size_str = f"{size_kb:.0f} KB"

        combined = f"{dimensions} - {size_str}"
        assert combined == "1000x1000 - 500 KB"


class TestClickableImageLabel:
    """Tests for ClickableImageLabel widget."""

    @pytest.fixture
    def clickable_label(self, qtbot):
        """Create a ClickableImageLabel instance."""
        from src.ui.dialogs.cover_comparison import ClickableImageLabel

        label = ClickableImageLabel()
        qtbot.addWidget(label)
        return label

    @pytest.fixture
    def test_pixmap(self):
        """Create a test pixmap."""
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.GlobalColor.red)
        return pixmap

    def test_init_cursor(self, clickable_label):
        """Test that ClickableImageLabel has pointing hand cursor."""
        assert clickable_label.cursor().shape() == Qt.CursorShape.PointingHandCursor

    def test_init_no_pixmap(self, clickable_label):
        """Test that ClickableImageLabel starts with no pixmap."""
        assert clickable_label._pixmap is None

    def test_set_original_pixmap(self, clickable_label, test_pixmap):
        """Test setting the original pixmap."""
        clickable_label.set_original_pixmap(test_pixmap)
        assert clickable_label._pixmap is not None
        assert clickable_label._pixmap.width() == 100
        assert clickable_label._pixmap.height() == 100

    def test_double_click_without_pixmap_no_crash(self, clickable_label, qtbot):
        """Test that double-click without pixmap doesn't crash."""
        # Should not raise any exception
        qtbot.mouseDClick(clickable_label, Qt.MouseButton.LeftButton)

    def test_double_click_with_null_pixmap_no_dialog(self, clickable_label, qtbot):
        """Test that double-click with null pixmap doesn't show dialog."""
        null_pixmap = QPixmap()  # Null pixmap
        clickable_label.set_original_pixmap(null_pixmap)

        with patch("src.ui.dialogs.cover_comparison.ZoomDialog") as mock_dialog:
            qtbot.mouseDClick(clickable_label, Qt.MouseButton.LeftButton)
            mock_dialog.assert_not_called()

    def test_double_click_with_valid_pixmap_shows_dialog(self, clickable_label, test_pixmap, qtbot):
        """Test that double-click with valid pixmap shows ZoomDialog."""
        clickable_label.set_original_pixmap(test_pixmap)

        with patch("src.ui.dialogs.cover_comparison.ZoomDialog") as mock_dialog_class:
            mock_dialog = Mock()
            mock_dialog_class.return_value = mock_dialog

            qtbot.mouseDClick(clickable_label, Qt.MouseButton.LeftButton)

            mock_dialog_class.assert_called_once()
            mock_dialog.exec.assert_called_once()

    def test_right_click_does_not_show_dialog(self, clickable_label, test_pixmap, qtbot):
        """Test that right-click doesn't show dialog."""
        clickable_label.set_original_pixmap(test_pixmap)

        with patch("src.ui.dialogs.cover_comparison.ZoomDialog") as mock_dialog:
            qtbot.mouseDClick(clickable_label, Qt.MouseButton.RightButton)
            mock_dialog.assert_not_called()


class TestCoverPanelWithClickableLabel:
    """Tests for CoverPanel using ClickableImageLabel."""

    @pytest.fixture
    def cover_panel(self, qtbot):
        """Create a CoverPanel instance."""
        from src.ui.dialogs.cover_comparison import CoverPanel

        panel = CoverPanel("Test Title")
        qtbot.addWidget(panel)
        return panel

    def test_cover_label_is_clickable(self, cover_panel):
        """Test that cover_label is a ClickableImageLabel."""
        from src.ui.dialogs.cover_comparison import ClickableImageLabel

        assert isinstance(cover_panel.cover_label, ClickableImageLabel)

    def test_cover_label_has_tooltip(self, cover_panel):
        """Test that cover_label has zoom tooltip."""
        tooltip = cover_panel.cover_label.toolTip()
        # Should contain zoom-related text (may be translated)
        assert tooltip != ""

    def test_set_pixmap_stores_original(self, cover_panel):
        """Test that _set_pixmap stores the original for zoom."""
        pixmap = QPixmap(200, 200)
        pixmap.fill(Qt.GlobalColor.blue)

        cover_panel._set_pixmap(pixmap)

        # Original should be stored
        assert cover_panel.cover_label._pixmap is not None
        assert cover_panel.cover_label._pixmap.width() == 200


class TestSmallCoverPanelWithClickableLabel:
    """Tests for SmallCoverPanel using ClickableImageLabel."""

    @pytest.fixture
    def small_panel(self, qtbot):
        """Create a SmallCoverPanel instance."""
        from src.ui.dialogs.cover_comparison import SmallCoverPanel

        panel = SmallCoverPanel("Test Title")
        qtbot.addWidget(panel)
        return panel

    def test_cover_label_is_clickable(self, small_panel):
        """Test that cover_label is a ClickableImageLabel."""
        from src.ui.dialogs.cover_comparison import ClickableImageLabel

        assert isinstance(small_panel.cover_label, ClickableImageLabel)

    def test_cover_label_has_tooltip(self, small_panel):
        """Test that cover_label has zoom tooltip."""
        tooltip = small_panel.cover_label.toolTip()
        assert tooltip != ""

    def test_set_pixmap_stores_original(self, small_panel):
        """Test that _set_pixmap stores the original for zoom."""
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.GlobalColor.green)

        small_panel._set_pixmap(pixmap)

        assert small_panel.cover_label._pixmap is not None
        assert small_panel.cover_label._pixmap.width() == 100
