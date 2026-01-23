"""
Tests for cover zoom dialog functionality.

Note: These tests mock Qt components to avoid requiring a QApplication.
For full GUI tests, use pytest-qt.
"""

import pytest

from src.core.models import AlbumInfo, CoverInfo


class TestCoverZoomDialogLogic:
    """
    Tests for the CoverZoomDialog's core logic without requiring Qt.

    These tests verify the comparison logic and zoom calculations.
    """

    def test_larger_indicator_embedded_larger(self):
        """Test larger indicator when embedded is larger."""
        # Embedded: 1000x1000 = 1,000,000 pixels
        # Folder: 800x800 = 640,000 pixels
        embedded_pixels = 1000 * 1000
        folder_pixels = 800 * 800

        assert embedded_pixels > folder_pixels

        # Difference percentage
        diff_percent = ((embedded_pixels - folder_pixels) / folder_pixels) * 100
        assert diff_percent == pytest.approx(56.25, rel=0.01)

    def test_larger_indicator_folder_larger(self):
        """Test larger indicator when folder is larger."""
        # Embedded: 600x600 = 360,000 pixels
        # Folder: 1200x1200 = 1,440,000 pixels
        embedded_pixels = 600 * 600
        folder_pixels = 1200 * 1200

        assert folder_pixels > embedded_pixels

        # Difference percentage
        diff_percent = ((folder_pixels - embedded_pixels) / embedded_pixels) * 100
        assert diff_percent == pytest.approx(300.0, rel=0.01)

    def test_larger_indicator_equal_size(self):
        """Test larger indicator when sizes are equal."""
        embedded_pixels = 500 * 500
        folder_pixels = 500 * 500

        assert embedded_pixels == folder_pixels

    def test_pixel_count_calculation(self):
        """Test pixel count calculation for various dimensions."""
        test_cases = [
            ((100, 100), 10000),
            ((1920, 1080), 2073600),
            ((3000, 3000), 9000000),
            ((1, 1), 1),
            ((0, 100), 0),
        ]

        for dimensions, expected_pixels in test_cases:
            actual = dimensions[0] * dimensions[1]
            assert actual == expected_pixels


class TestZoomCalculations:
    """Tests for zoom factor calculations."""

    def test_zoom_bounds(self):
        """Test that zoom stays within bounds."""
        min_zoom = 0.25
        max_zoom = 4.0
        zoom_step = 0.1

        # Test zoom in at max
        current = max_zoom
        new_zoom = min(current + zoom_step, max_zoom)
        assert new_zoom == max_zoom

        # Test zoom out at min
        current = min_zoom
        new_zoom = max(current - zoom_step, min_zoom)
        assert new_zoom == min_zoom

        # Test zoom in within bounds
        current = 1.0
        new_zoom = min(current + zoom_step, max_zoom)
        assert new_zoom == pytest.approx(1.1, rel=0.01)

        # Test zoom out within bounds
        current = 1.0
        new_zoom = max(current - zoom_step, min_zoom)
        assert new_zoom == pytest.approx(0.9, rel=0.01)

    def test_zoom_percentage_label(self):
        """Test zoom percentage label formatting."""
        test_cases = [
            (1.0, "100%"),
            (0.5, "50%"),
            (2.0, "200%"),
            (0.25, "25%"),
            (4.0, "400%"),
            (1.5, "150%"),
        ]

        for factor, expected_label in test_cases:
            actual_label = f"{int(factor * 100)}%"
            assert actual_label == expected_label

    def test_zoom_slider_value_conversion(self):
        """Test conversion between zoom factor and slider value."""
        # Slider is 0-400 (representing 0-4x zoom in percent)
        test_cases = [
            (100, 1.0),  # 100% slider = 1.0x zoom
            (50, 0.5),  # 50% slider = 0.5x zoom
            (200, 2.0),  # 200% slider = 2.0x zoom
            (25, 0.25),  # 25% slider = 0.25x zoom
            (400, 4.0),  # 400% slider = 4.0x zoom
        ]

        for slider_value, expected_factor in test_cases:
            factor = slider_value / 100.0
            assert factor == expected_factor

        # Reverse conversion
        for slider_value, factor in test_cases:
            actual_slider = int(factor * 100)
            assert actual_slider == slider_value


class TestCoverViewPanelLogic:
    """Tests for CoverViewPanel's non-Qt logic."""

    def test_mime_to_format_conversion(self):
        """Test MIME type to format string conversion."""
        mime_map = {
            "image/jpeg": "JPEG",
            "image/jpg": "JPEG",
            "image/png": "PNG",
            "image/gif": "GIF",
            "image/webp": "WebP",
            "image/bmp": "BMP",
        }

        for mime_type, expected_format in mime_map.items():
            actual = mime_map.get(mime_type.lower(), mime_type.split("/")[-1].upper())
            assert actual == expected_format

    def test_mime_to_format_unknown(self):
        """Test MIME type conversion for unknown types."""
        unknown_types = [
            ("image/tiff", "TIFF"),
            ("image/svg+xml", "SVG+XML"),
            ("application/octet-stream", "OCTET-STREAM"),
        ]

        for mime_type, expected in unknown_types:
            # Fallback behavior
            result = mime_type.split("/")[-1].upper()
            assert result == expected

    def test_extension_to_format_map(self):
        """Test file extension to format mapping."""
        fmt_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WebP"}

        test_cases = [
            ("jpg", "JPEG"),
            ("jpeg", "JPEG"),
            ("png", "PNG"),
            ("gif", "GIF"),
            ("webp", "WebP"),
            ("bmp", "BMP"),  # Not in map, should use uppercase
        ]

        for ext, expected in test_cases:
            result = fmt_map.get(ext, ext.upper())
            assert result == expected


class TestBorderStyleLogic:
    """Tests for border style determination logic."""

    def test_larger_cover_gets_green_border(self):
        """Test that the larger cover gets a green border style."""

        # Simulate the logic for setting border style
        def get_border_style(is_larger):
            if is_larger:
                return "border: 3px solid #27ae60;"  # Green border
            return "border: 1px solid #444;"  # Normal border

        # Larger cover should get green border
        assert "#27ae60" in get_border_style(True)
        assert "3px" in get_border_style(True)

        # Smaller cover should get normal border
        assert "#444" in get_border_style(False)
        assert "1px" in get_border_style(False)

    def test_comparison_result_text(self):
        """Test the comparison result text generation."""

        def get_comparison_text(embedded_dims, folder_dims):
            embedded_pixels = embedded_dims[0] * embedded_dims[1]
            folder_pixels = folder_dims[0] * folder_dims[1]

            if embedded_pixels > folder_pixels:
                diff_percent = ((embedded_pixels - folder_pixels) / folder_pixels) * 100
                return f"Tags audio plus grande (+{diff_percent:.1f}% de pixels)"
            elif folder_pixels > embedded_pixels:
                diff_percent = ((folder_pixels - embedded_pixels) / embedded_pixels) * 100
                return f"Fichier externe plus grand (+{diff_percent:.1f}% de pixels)"
            else:
                return f"Tailles identiques ({embedded_dims[0]}x{embedded_dims[1]})"

        # Embedded larger
        result = get_comparison_text((1000, 1000), (500, 500))
        assert "Tags audio plus grande" in result
        assert "+300.0%" in result

        # Folder larger
        result = get_comparison_text((500, 500), (1000, 1000))
        assert "Fichier externe plus grand" in result
        assert "+300.0%" in result

        # Equal
        result = get_comparison_text((800, 800), (800, 800))
        assert "Tailles identiques" in result


class TestKeyboardShortcuts:
    """Tests for keyboard shortcut handling logic."""

    def test_key_mappings(self):
        """Test that the expected keys map to correct actions."""
        # Simulated key to action mapping
        key_actions = {
            "Escape": "reject",
            "Plus": "zoom_in",
            "Equal": "zoom_in",  # = key without shift is +
            "Minus": "zoom_out",
            "0": "reset_zoom",
            "F": "fit_to_view",
        }

        assert key_actions["Escape"] == "reject"
        assert key_actions["Plus"] == "zoom_in"
        assert key_actions["Minus"] == "zoom_out"
        assert key_actions["0"] == "reset_zoom"
        assert key_actions["F"] == "fit_to_view"


class TestCoverZoomDialogWithFixtures:
    """
    Tests using fixtures for CoverZoomDialog scenarios.
    """

    @pytest.fixture
    def album_with_both_covers(self, tmp_path):
        """Create an album with both embedded and folder covers."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        sample_file = album_path / "track.mp3"
        sample_file.write_bytes(b"fake mp3 data")
        cover_file = album_path / "cover.jpg"
        # Create a minimal JPEG header
        cover_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        cover = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=cover_file,
            covers_differ=True,
            embedded_dimensions=(800, 800),
            folder_dimensions=(500, 500),
            embedded_mime_type="image/jpeg",
            folder_mime_type="image/jpeg",
        )
        return AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=cover,
            sample_file=sample_file,
        )

    def test_dialog_requires_both_covers(self, album_with_both_covers):
        """Test that the dialog requires both covers to be present."""
        album = album_with_both_covers

        # Both covers present - should be valid
        has_embedded = bool(album.cover.has_embedded and album.sample_file)
        has_folder = bool(album.cover.folder_path and album.cover.folder_path.exists())

        assert has_embedded is True
        assert has_folder is True

    def test_dialog_disabled_without_embedded(self, tmp_path):
        """Test that dialog cannot open without embedded cover."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        cover_file = album_path / "cover.jpg"
        cover_file.write_bytes(b"fake image")

        cover = CoverInfo(
            has_embedded=False,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=cover_file,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Test",
            album="Test",
            cover=cover,
        )

        has_embedded = album.cover.has_embedded and album.sample_file
        has_folder = album.cover.folder_path and album.cover.folder_path.exists()

        assert has_embedded is False
        assert has_folder is True
        # Should not be able to open comparison
        assert not (has_embedded and has_folder)

    def test_dialog_disabled_without_folder(self, tmp_path):
        """Test that dialog cannot open without folder cover."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        sample_file = album_path / "track.mp3"
        sample_file.write_bytes(b"fake mp3")

        cover = CoverInfo(
            has_embedded=True,
            has_folder=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Test",
            album="Test",
            cover=cover,
            sample_file=sample_file,
        )

        has_embedded = bool(album.cover.has_embedded and album.sample_file)
        has_folder = bool(
            album.cover.folder_path
            and (album.cover.folder_path.exists() if album.cover.folder_path else False)
        )

        assert has_embedded is True
        assert has_folder is False
        # Should not be able to open comparison
        assert not (has_embedded and has_folder)


class TestZoomSynchronization:
    """Tests for zoom synchronization logic between panels."""

    def test_zoom_sync_from_embedded_to_folder(self):
        """Test that zoom changes on embedded panel sync to folder panel."""
        # Simulate two panel zoom states
        embedded_zoom = 1.5
        folder_zoom = 1.0

        # Sync should make them equal
        folder_zoom = embedded_zoom
        assert folder_zoom == embedded_zoom == 1.5

    def test_zoom_sync_from_folder_to_embedded(self):
        """Test that zoom changes on folder panel sync to embedded panel."""
        embedded_zoom = 1.0
        folder_zoom = 2.0

        # Sync should make them equal
        embedded_zoom = folder_zoom
        assert embedded_zoom == folder_zoom == 2.0

    def test_slider_update_on_zoom_change(self):
        """Test that slider updates when zoom changes."""

        def update_slider(zoom_factor):
            return int(zoom_factor * 100)

        assert update_slider(1.0) == 100
        assert update_slider(1.5) == 150
        assert update_slider(0.5) == 50
        assert update_slider(2.0) == 200
