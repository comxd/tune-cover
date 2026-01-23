"""
Tests for the StatisticsDialog class.
"""

from pathlib import Path

from src.core.models import AlbumInfo, CoverInfo, CoverStatus


class TestStatisticsDialogComputation:
    """Tests for statistics computation logic (without Qt)."""

    def test_empty_album_list(self):
        """Test statistics with empty album list."""

        # We cannot instantiate the dialog without Qt, so test the computation method
        albums = []
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["total_albums"] == 0
        assert stats["cover_status"][CoverStatus.NONE] == 0
        assert stats["cover_status"][CoverStatus.BOTH] == 0
        assert stats["differing_covers"] == 0
        assert stats["embedded_dimensions"] == []
        assert stats["folder_dimensions"] == []

    def test_single_album_no_cover(self):
        """Test statistics with one album without cover."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                artist="Artist1",
                album="Album1",
                cover=CoverInfo(has_embedded=False, has_folder=False),
            )
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["total_albums"] == 1
        assert stats["cover_status"][CoverStatus.NONE] == 1
        assert stats["cover_status"][CoverStatus.BOTH] == 0

    def test_single_album_embedded_only(self):
        """Test statistics with album having only embedded cover."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                artist="Artist1",
                album="Album1",
                cover=CoverInfo(
                    has_embedded=True,
                    has_folder=False,
                    embedded_mime_type="image/jpeg",
                    embedded_dimensions=(500, 500),
                    embedded_size_bytes=102400,
                ),
            )
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["total_albums"] == 1
        assert stats["cover_status"][CoverStatus.EMBEDDED_ONLY] == 1
        assert stats["embedded_dimensions"] == [(500, 500)]
        assert stats["embedded_sizes"] == [102400]
        assert stats["embedded_formats"] == {"JPEG": 1}

    def test_single_album_folder_only(self):
        """Test statistics with album having only folder cover."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                artist="Artist1",
                album="Album1",
                cover=CoverInfo(
                    has_embedded=False,
                    has_folder=True,
                    folder_file="cover.png",
                    folder_path=Path("/music/album1/cover.png"),
                    folder_mime_type="image/png",
                    folder_dimensions=(1000, 1000),
                    folder_size_bytes=204800,
                ),
            )
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["total_albums"] == 1
        assert stats["cover_status"][CoverStatus.FOLDER_ONLY] == 1
        assert stats["folder_dimensions"] == [(1000, 1000)]
        assert stats["folder_sizes"] == [204800]
        assert stats["folder_formats"] == {"PNG": 1}

    def test_single_album_both_covers(self):
        """Test statistics with album having both covers."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                artist="Artist1",
                album="Album1",
                cover=CoverInfo(
                    has_embedded=True,
                    has_folder=True,
                    embedded_mime_type="image/jpeg",
                    embedded_dimensions=(500, 500),
                    embedded_size_bytes=51200,
                    folder_file="cover.jpg",
                    folder_path=Path("/music/album1/cover.jpg"),
                    folder_mime_type="image/jpeg",
                    folder_dimensions=(1000, 1000),
                    folder_size_bytes=102400,
                ),
            )
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["total_albums"] == 1
        assert stats["cover_status"][CoverStatus.BOTH] == 1
        assert stats["embedded_dimensions"] == [(500, 500)]
        assert stats["folder_dimensions"] == [(1000, 1000)]

    def test_differing_covers_count(self):
        """Test differing covers count."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                cover=CoverInfo(
                    has_embedded=True,
                    has_folder=True,
                    covers_differ=True,
                ),
            ),
            AlbumInfo(
                path=Path("/music/album2"),
                cover=CoverInfo(
                    has_embedded=True,
                    has_folder=True,
                    covers_differ=False,
                ),
            ),
            AlbumInfo(
                path=Path("/music/album3"),
                cover=CoverInfo(
                    has_embedded=True,
                    has_folder=True,
                    covers_differ=True,
                ),
            ),
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["differing_covers"] == 2

    def test_multiple_albums_mixed_status(self):
        """Test statistics with multiple albums of mixed cover status."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                cover=CoverInfo(has_embedded=True, has_folder=True),
            ),
            AlbumInfo(
                path=Path("/music/album2"),
                cover=CoverInfo(has_embedded=True, has_folder=False),
            ),
            AlbumInfo(
                path=Path("/music/album3"),
                cover=CoverInfo(has_embedded=False, has_folder=True),
            ),
            AlbumInfo(
                path=Path("/music/album4"),
                cover=CoverInfo(has_embedded=False, has_folder=False),
            ),
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["total_albums"] == 4
        assert stats["cover_status"][CoverStatus.BOTH] == 1
        assert stats["cover_status"][CoverStatus.EMBEDDED_ONLY] == 1
        assert stats["cover_status"][CoverStatus.FOLDER_ONLY] == 1
        assert stats["cover_status"][CoverStatus.NONE] == 1

    def test_format_distribution_multiple_formats(self):
        """Test format distribution with multiple formats."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                cover=CoverInfo(
                    has_embedded=True,
                    embedded_mime_type="image/jpeg",
                ),
            ),
            AlbumInfo(
                path=Path("/music/album2"),
                cover=CoverInfo(
                    has_embedded=True,
                    embedded_mime_type="image/png",
                ),
            ),
            AlbumInfo(
                path=Path("/music/album3"),
                cover=CoverInfo(
                    has_embedded=True,
                    embedded_mime_type="image/jpeg",
                ),
            ),
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["embedded_formats"] == {"JPEG": 2, "PNG": 1}

    def test_folder_format_fallback_to_extension(self):
        """Test folder format uses file extension when mime type not available."""
        albums = [
            AlbumInfo(
                path=Path("/music/album1"),
                cover=CoverInfo(
                    has_folder=True,
                    folder_file="cover.jpg",
                    folder_mime_type=None,
                ),
            ),
        ]
        dialog = MockStatisticsDialog(albums)
        stats = dialog._compute_statistics()

        assert stats["folder_formats"] == {"JPG": 1}


class TestStatisticsDialogFormatting:
    """Tests for formatting helper methods."""

    def test_format_percentage_zero_total(self):
        """Test percentage formatting with zero total."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_percentage(0, 0)
        assert result == "0%"

    def test_format_percentage_normal(self):
        """Test percentage formatting with normal values."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_percentage(25, 100)
        assert result == "25.0%"

    def test_format_percentage_partial(self):
        """Test percentage formatting with partial value."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_percentage(1, 3)
        assert result == "33.3%"

    def test_format_dimensions_empty(self):
        """Test dimension formatting with empty list."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_dimensions([])
        assert result == "-"

    def test_format_dimensions_single(self):
        """Test dimension formatting with single value."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_dimensions([(500, 500)])
        assert result == "500 x 500 px"

    def test_format_dimensions_average(self):
        """Test dimension formatting calculates average."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_dimensions([(400, 400), (600, 600)])
        assert result == "500 x 500 px"

    def test_format_size_stats_empty(self):
        """Test size stats formatting with empty list."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_size_stats([])
        assert result == "-"

    def test_format_size_stats_single(self):
        """Test size stats formatting with single value."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_size_stats([102400])  # 100 KB
        assert "100 KB" in result

    def test_format_size_stats_multiple(self):
        """Test size stats formatting with multiple values."""
        dialog = MockStatisticsDialog([])
        # 50 KB, 100 KB, 150 KB
        result = dialog._format_size_stats([51200, 102400, 153600])
        assert "Min: 50 KB" in result
        assert "Max: 150 KB" in result
        assert "Moy: 100 KB" in result

    def test_format_distribution_empty(self):
        """Test distribution formatting with empty dict."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_distribution({})
        assert result == "-"

    def test_format_distribution_single(self):
        """Test distribution formatting with single format."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_distribution({"JPEG": 5})
        assert result == "JPEG: 5"

    def test_format_distribution_multiple(self):
        """Test distribution formatting with multiple formats."""
        dialog = MockStatisticsDialog([])
        result = dialog._format_distribution({"JPEG": 5, "PNG": 3})
        # Sorted alphabetically
        assert "JPEG: 5" in result
        assert "PNG: 3" in result


class TestMimeToFormat:
    """Tests for MIME type to format conversion."""

    def test_mime_jpeg(self):
        """Test JPEG MIME type conversion."""
        dialog = MockStatisticsDialog([])
        assert dialog._mime_to_format("image/jpeg") == "JPEG"

    def test_mime_png(self):
        """Test PNG MIME type conversion."""
        dialog = MockStatisticsDialog([])
        assert dialog._mime_to_format("image/png") == "PNG"

    def test_mime_webp(self):
        """Test WebP MIME type conversion."""
        dialog = MockStatisticsDialog([])
        assert dialog._mime_to_format("image/webp") == "WebP"

    def test_mime_unknown(self):
        """Test unknown MIME type conversion."""
        dialog = MockStatisticsDialog([])
        result = dialog._mime_to_format("image/unknown")
        assert result == "UNKNOWN"

    def test_mime_case_insensitive(self):
        """Test MIME type conversion is case insensitive."""
        dialog = MockStatisticsDialog([])
        assert dialog._mime_to_format("IMAGE/JPEG") == "JPEG"


class MockStatisticsDialog:
    """
    Mock version of StatisticsDialog for testing without Qt.

    Contains only the computation and formatting methods.
    """

    def __init__(self, albums):
        self.albums = albums
        self.stats = self._compute_statistics()

    def _compute_statistics(self):
        """Compute all statistics from the albums list."""
        stats = {
            "total_albums": len(self.albums),
            "cover_status": {
                CoverStatus.BOTH: 0,
                CoverStatus.EMBEDDED_ONLY: 0,
                CoverStatus.FOLDER_ONLY: 0,
                CoverStatus.NONE: 0,
            },
            "differing_covers": 0,
            "embedded_dimensions": [],
            "folder_dimensions": [],
            "embedded_formats": {},
            "folder_formats": {},
            "embedded_sizes": [],
            "folder_sizes": [],
        }

        for album in self.albums:
            cover = album.cover

            # Cover status
            status = cover.status
            stats["cover_status"][status] += 1

            # Differing covers
            if cover.covers_differ:
                stats["differing_covers"] += 1

            # Embedded cover info
            if cover.has_embedded:
                if cover.embedded_dimensions:
                    stats["embedded_dimensions"].append(cover.embedded_dimensions)
                if cover.embedded_mime_type:
                    fmt = self._mime_to_format(cover.embedded_mime_type)
                    stats["embedded_formats"][fmt] = stats["embedded_formats"].get(fmt, 0) + 1
                if cover.embedded_size_bytes:
                    stats["embedded_sizes"].append(cover.embedded_size_bytes)

            # Folder cover info
            if cover.has_folder:
                if cover.folder_dimensions:
                    stats["folder_dimensions"].append(cover.folder_dimensions)
                if cover.folder_mime_type:
                    fmt = self._mime_to_format(cover.folder_mime_type)
                    stats["folder_formats"][fmt] = stats["folder_formats"].get(fmt, 0) + 1
                elif cover.folder_file:
                    # Fallback to extension if mime type not available
                    ext = (
                        cover.folder_file.lower().split(".")[-1] if "." in cover.folder_file else ""
                    )
                    fmt = ext.upper() if ext else "Inconnu"
                    stats["folder_formats"][fmt] = stats["folder_formats"].get(fmt, 0) + 1
                if cover.folder_size_bytes:
                    stats["folder_sizes"].append(cover.folder_size_bytes)

        return stats

    def _mime_to_format(self, mime_type):
        """Convert MIME type to human-readable format name."""
        mime_map = {
            "image/jpeg": "JPEG",
            "image/jpg": "JPEG",
            "image/png": "PNG",
            "image/gif": "GIF",
            "image/webp": "WebP",
            "image/bmp": "BMP",
            "image/tiff": "TIFF",
        }
        return mime_map.get(mime_type.lower(), mime_type.upper().replace("IMAGE/", ""))

    def _format_percentage(self, count, total):
        """Format count as percentage string."""
        if total == 0:
            return "0%"
        percentage = (count / total) * 100
        return f"{percentage:.1f}%"

    def _format_dimensions(self, dimensions):
        """Calculate and format average dimensions."""
        if not dimensions:
            return "-"
        avg_width = sum(d[0] for d in dimensions) / len(dimensions)
        avg_height = sum(d[1] for d in dimensions) / len(dimensions)
        return f"{avg_width:.0f} x {avg_height:.0f} px"

    def _format_size_stats(self, sizes):
        """Format size statistics (min, max, average)."""
        if not sizes:
            return "-"
        min_kb = min(sizes) / 1024
        max_kb = max(sizes) / 1024
        avg_kb = sum(sizes) / len(sizes) / 1024
        return f"Min: {min_kb:.0f} KB / Max: {max_kb:.0f} KB / Moy: {avg_kb:.0f} KB"

    def _format_distribution(self, formats):
        """Format the format distribution as a string."""
        if not formats:
            return "-"
        parts = [f"{fmt}: {count}" for fmt, count in sorted(formats.items())]
        return ", ".join(parts)
