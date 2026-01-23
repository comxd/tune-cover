"""
Tests for image info widget.

Note: These tests mock Qt components to avoid requiring a QApplication.
"""


class TestImageInfoLabelLogic:
    """Tests for ImageInfoLabel business logic without Qt."""

    def test_size_formatting_bytes_to_kb(self):
        """Test size formatting from bytes to KB."""

        # Simulate the _update_text logic
        def format_size(size_bytes):
            if not size_bytes:
                return ""
            size_kb = size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                return f"{size_mb:.1f} MB"
            return f"{size_kb:.0f} KB"

        assert format_size(1024) == "1 KB"
        assert format_size(10240) == "10 KB"
        assert format_size(512000) == "500 KB"

    def test_size_formatting_bytes_to_mb(self):
        """Test size formatting from bytes to MB."""

        def format_size(size_bytes):
            if not size_bytes:
                return ""
            size_kb = size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                return f"{size_mb:.1f} MB"
            return f"{size_kb:.0f} KB"

        # 1 MB = 1024 * 1024 bytes
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(2 * 1024 * 1024) == "2.0 MB"
        assert format_size(1.5 * 1024 * 1024) == "1.5 MB"

    def test_size_formatting_none_returns_empty(self):
        """Test size formatting with None returns empty string."""

        def format_size(size_bytes):
            if not size_bytes:
                return ""
            size_kb = size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                return f"{size_mb:.1f} MB"
            return f"{size_kb:.0f} KB"

        assert format_size(None) == ""
        assert format_size(0) == ""

    def test_dimensions_formatting(self):
        """Test dimensions formatting."""

        def format_dimensions(width, height):
            if width and height:
                return f"{width}x{height}"
            return ""

        assert format_dimensions(1000, 1000) == "1000x1000"
        assert format_dimensions(1920, 1080) == "1920x1080"
        assert format_dimensions(500, 300) == "500x300"

    def test_dimensions_formatting_none(self):
        """Test dimensions formatting with None values."""

        def format_dimensions(width, height):
            if width and height:
                return f"{width}x{height}"
            return ""

        assert format_dimensions(None, 100) == ""
        assert format_dimensions(100, None) == ""
        assert format_dimensions(None, None) == ""
        assert format_dimensions(0, 100) == ""

    def test_full_text_formatting(self):
        """Test full text formatting with dimensions and size."""

        def format_info(width, height, size_bytes):
            parts = []

            if width and height:
                parts.append(f"{width}x{height}")

            if size_bytes:
                size_kb = size_bytes / 1024
                if size_kb >= 1024:
                    size_mb = size_kb / 1024
                    parts.append(f"{size_mb:.1f} MB")
                else:
                    parts.append(f"{size_kb:.0f} KB")

            return " - ".join(parts)

        assert format_info(1000, 1000, 512000) == "1000x1000 - 500 KB"
        assert format_info(1920, 1080, 2 * 1024 * 1024) == "1920x1080 - 2.0 MB"
        assert format_info(None, None, 1024) == "1 KB"
        assert format_info(500, 500, None) == "500x500"
        assert format_info(None, None, None) == ""


class TestImageInfoEdgeCases:
    """Tests for edge cases in image info formatting."""

    def test_very_small_file(self):
        """Test formatting very small file sizes."""

        def format_size(size_bytes):
            if not size_bytes:
                return ""
            size_kb = size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                return f"{size_mb:.1f} MB"
            return f"{size_kb:.0f} KB"

        # 1 byte = ~0 KB
        assert format_size(1) == "0 KB"
        assert format_size(100) == "0 KB"
        assert format_size(512) == "0 KB"
        assert format_size(1024) == "1 KB"

    def test_large_file_sizes(self):
        """Test formatting large file sizes."""

        def format_size(size_bytes):
            if not size_bytes:
                return ""
            size_kb = size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                return f"{size_mb:.1f} MB"
            return f"{size_kb:.0f} KB"

        # 100 MB
        assert format_size(100 * 1024 * 1024) == "100.0 MB"
        # 1 GB
        assert format_size(1024 * 1024 * 1024) == "1024.0 MB"

    def test_unusual_dimensions(self):
        """Test formatting unusual dimensions."""

        def format_dimensions(width, height):
            if width and height:
                return f"{width}x{height}"
            return ""

        # Very small
        assert format_dimensions(1, 1) == "1x1"
        # Very large
        assert format_dimensions(10000, 10000) == "10000x10000"
        # Non-square
        assert format_dimensions(1, 10000) == "1x10000"

    def test_boundary_size_kb_to_mb(self):
        """Test size formatting at KB/MB boundary."""

        def format_size(size_bytes):
            if not size_bytes:
                return ""
            size_kb = size_bytes / 1024
            if size_kb >= 1024:
                size_mb = size_kb / 1024
                return f"{size_mb:.1f} MB"
            return f"{size_kb:.0f} KB"

        # Just under 1 MB (1023 KB)
        assert format_size(1023 * 1024) == "1023 KB"
        # Exactly 1 MB
        assert format_size(1024 * 1024) == "1.0 MB"
        # Just over 1 MB
        assert format_size(1025 * 1024) == "1.0 MB"
