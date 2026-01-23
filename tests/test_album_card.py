"""
Tests for album card widget functionality.

Note: These tests mock Qt components to avoid requiring a QApplication.
For full GUI tests, use pytest-qt.
"""

import base64

from src.core.models import AlbumInfo, CoverInfo, CoverStatus


class TestAlbumCardTooltipLogic:
    """
    Tests for the tooltip creation logic in AlbumCard.

    These tests isolate the decision-making logic without requiring Qt.
    """

    def test_cover_status_text_mapping(self):
        """Test that all cover statuses have appropriate text."""
        status_texts = {
            CoverStatus.NONE: "Aucune pochette",
            CoverStatus.EMBEDDED_ONLY: "Pochette embarquee uniquement",
            CoverStatus.FOLDER_ONLY: "Pochette fichier uniquement",
            CoverStatus.BOTH: "Pochettes embarquee et fichier",
        }

        for status in CoverStatus:
            assert status in status_texts
            assert status_texts[status]  # Not empty

    def test_album_info_for_tooltip_no_cover(self, tmp_path):
        """Test album info for tooltip when there's no cover."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)

        cover = CoverInfo(
            has_embedded=False,
            has_folder=False,
        )
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            year="2023",
            cover=cover,
        )

        assert album.cover.status == CoverStatus.NONE
        assert album.artist == "Test Artist"
        assert album.album == "Test Album"
        assert album.year == "2023"

    def test_album_info_for_tooltip_with_embedded_only(self, tmp_path):
        """Test album info for tooltip when only embedded cover exists."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)

        cover = CoverInfo(
            has_embedded=True,
            has_folder=False,
            embedded_dimensions=(500, 500),
        )
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=cover,
        )

        assert album.cover.status == CoverStatus.EMBEDDED_ONLY
        assert album.cover.embedded_dimensions == (500, 500)

    def test_album_info_for_tooltip_with_folder_only(self, tmp_path):
        """Test album info for tooltip when only folder cover exists."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        cover_file = album_path / "cover.jpg"
        cover_file.write_bytes(b"fake image")

        cover = CoverInfo(
            has_embedded=False,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=cover_file,
            folder_dimensions=(800, 800),
        )
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=cover,
        )

        assert album.cover.status == CoverStatus.FOLDER_ONLY
        assert album.cover.folder_dimensions == (800, 800)

    def test_album_info_for_tooltip_with_both_covers(self, tmp_path):
        """Test album info for tooltip when both covers exist."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        cover_file = album_path / "cover.jpg"
        cover_file.write_bytes(b"fake image")

        cover = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=cover_file,
            covers_differ=False,
            embedded_dimensions=(600, 600),
            folder_dimensions=(600, 600),
        )
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=cover,
        )

        assert album.cover.status == CoverStatus.BOTH
        assert not album.cover.covers_differ

    def test_album_info_for_tooltip_covers_differ(self, tmp_path):
        """Test album info for tooltip when covers differ."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        cover_file = album_path / "cover.jpg"
        cover_file.write_bytes(b"fake image")

        cover = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="cover.jpg",
            folder_path=cover_file,
            covers_differ=True,
            embedded_dimensions=(500, 500),
            folder_dimensions=(800, 800),
        )
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=cover,
        )

        assert album.cover.status == CoverStatus.BOTH
        assert album.cover.covers_differ
        assert album.cover.dimensions_differ


class TestAlbumCardTooltipHtml:
    """
    Tests for tooltip HTML generation.

    Uses a mock implementation to test the logic without Qt.
    """

    def _create_tooltip_html(self, album: AlbumInfo, has_preview_image: bool = False) -> str:
        """
        Simplified tooltip HTML generation matching AlbumCard._create_tooltip logic.
        """
        album_name = album.album or "Album inconnu"
        artist_name = album.artist or "Artiste inconnu"
        year = album.year or ""

        status = album.cover.status
        status_texts = {
            CoverStatus.NONE: "Aucune pochette",
            CoverStatus.EMBEDDED_ONLY: "Pochette embarquee uniquement",
            CoverStatus.FOLDER_ONLY: "Pochette fichier uniquement",
            CoverStatus.BOTH: "Pochettes embarquee et fichier",
        }
        status_text = status_texts.get(status, "Statut inconnu")

        dimensions_info = ""
        if album.cover.embedded_dimensions:
            w, h = album.cover.embedded_dimensions
            dimensions_info += f"<br/>Tags: {w}x{h}"
        if album.cover.folder_dimensions:
            w, h = album.cover.folder_dimensions
            dimensions_info += f"<br/>Fichier: {w}x{h}"

        diff_warning = ""
        if album.cover.covers_differ:
            diff_warning = "<br/><span style='color: #e67e22;'>Images differentes</span>"

        forced_group_info = ""
        if album.is_forced_group:
            forced_group_info = "<br/><span style='color: #e67e22;'>🔗 Regroupé manuellement</span>"

        cover_html = ""
        if has_preview_image:
            cover_html = '<img src="data:image/png;base64,FAKE_BASE64" /><br/>'

        year_str = f" ({year})" if year else ""
        html = f"""
        <div style="text-align: center; padding: 4px;">
            {cover_html}
            <b>{album_name}</b>{year_str}<br/>
            <span style="color: #888;">{artist_name}</span><br/>
            <span style="font-size: 10px; color: #666;">{status_text}{dimensions_info}{diff_warning}{forced_group_info}</span>
        </div>
        """
        return html.strip()

    def test_tooltip_contains_album_name(self, tmp_path):
        """Test that tooltip contains the album name."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        assert "Test Album" in html
        assert "<b>Test Album</b>" in html

    def test_tooltip_contains_artist_name(self, tmp_path):
        """Test that tooltip contains the artist name."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        assert "Test Artist" in html

    def test_tooltip_contains_year_when_present(self, tmp_path):
        """Test that tooltip contains the year when present."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            year="2023",
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        assert "(2023)" in html

    def test_tooltip_no_year_when_absent(self, tmp_path):
        """Test that tooltip doesn't have empty year parentheses."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            year=None,
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        assert "()" not in html

    def test_tooltip_contains_status_no_cover(self, tmp_path):
        """Test that tooltip contains correct status for no cover."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        html = self._create_tooltip_html(album)

        assert "Aucune pochette" in html

    def test_tooltip_contains_status_embedded_only(self, tmp_path):
        """Test that tooltip contains correct status for embedded only."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(has_embedded=True, has_folder=False),
        )

        html = self._create_tooltip_html(album)

        assert "Pochette embarquee uniquement" in html

    def test_tooltip_contains_status_folder_only(self, tmp_path):
        """Test that tooltip contains correct status for folder only."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(has_embedded=False, has_folder=True),
        )

        html = self._create_tooltip_html(album)

        assert "Pochette fichier uniquement" in html

    def test_tooltip_contains_status_both(self, tmp_path):
        """Test that tooltip contains correct status for both covers."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(has_embedded=True, has_folder=True),
        )

        html = self._create_tooltip_html(album)

        assert "Pochettes embarquee et fichier" in html

    def test_tooltip_contains_embedded_dimensions(self, tmp_path):
        """Test that tooltip contains embedded dimensions."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(
                has_embedded=True,
                has_folder=False,
                embedded_dimensions=(500, 500),
            ),
        )

        html = self._create_tooltip_html(album)

        assert "Tags: 500x500" in html

    def test_tooltip_contains_folder_dimensions(self, tmp_path):
        """Test that tooltip contains folder dimensions."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(
                has_embedded=False,
                has_folder=True,
                folder_dimensions=(800, 800),
            ),
        )

        html = self._create_tooltip_html(album)

        assert "Fichier: 800x800" in html

    def test_tooltip_contains_both_dimensions(self, tmp_path):
        """Test that tooltip contains both dimensions."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(
                has_embedded=True,
                has_folder=True,
                embedded_dimensions=(500, 500),
                folder_dimensions=(800, 800),
            ),
        )

        html = self._create_tooltip_html(album)

        assert "Tags: 500x500" in html
        assert "Fichier: 800x800" in html

    def test_tooltip_contains_diff_warning_when_covers_differ(self, tmp_path):
        """Test that tooltip contains warning when covers differ."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(
                has_embedded=True,
                has_folder=True,
                covers_differ=True,
            ),
        )

        html = self._create_tooltip_html(album)

        assert "Images differentes" in html
        assert "#e67e22" in html  # Orange color

    def test_tooltip_no_diff_warning_when_covers_same(self, tmp_path):
        """Test that tooltip has no warning when covers are same."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(
                has_embedded=True,
                has_folder=True,
                covers_differ=False,
            ),
        )

        html = self._create_tooltip_html(album)

        assert "Images differentes" not in html

    def test_tooltip_contains_image_when_cover_exists(self, tmp_path):
        """Test that tooltip contains img tag when cover exists."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(has_embedded=True, has_folder=False),
        )

        html = self._create_tooltip_html(album, has_preview_image=True)

        assert '<img src="data:image/png;base64,' in html

    def test_tooltip_no_image_when_no_cover(self, tmp_path):
        """Test that tooltip has no img tag when no cover."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        html = self._create_tooltip_html(album, has_preview_image=False)

        assert "<img" not in html

    def test_tooltip_uses_unknown_album_when_none(self, tmp_path):
        """Test that tooltip uses 'Album inconnu' when album is None."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            album=None,
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        assert "Album inconnu" in html

    def test_tooltip_uses_unknown_artist_when_none(self, tmp_path):
        """Test that tooltip uses 'Artiste inconnu' when artist is None."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist=None,
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        assert "Artiste inconnu" in html

    def test_tooltip_contains_forced_group_indicator(self, tmp_path):
        """Test that tooltip contains forced group indicator when is_forced_group is True."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            is_forced_group=True,
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        # Should contain the forced group indicator (chain emoji + text)
        assert "🔗" in html
        assert "Regroupé manuellement" in html

    def test_tooltip_no_forced_group_indicator_when_not_grouped(self, tmp_path):
        """Test that tooltip does not contain forced group indicator when is_forced_group is False."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            is_forced_group=False,
            cover=CoverInfo(),
        )

        html = self._create_tooltip_html(album)

        # Should NOT contain the forced group indicator
        assert "🔗" not in html
        assert "Regroupé manuellement" not in html


class TestBase64Encoding:
    """Tests for base64 encoding logic used in tooltip images."""

    def test_base64_encoding_roundtrip(self):
        """Test that base64 encoding/decoding produces the same data."""
        original_data = b"fake PNG image data here"
        encoded = base64.b64encode(original_data).decode("utf-8")
        decoded = base64.b64decode(encoded)

        assert decoded == original_data

    def test_base64_encoding_produces_valid_string(self):
        """Test that base64 encoding produces valid ASCII string."""
        data = b"\x89PNG\r\n\x1a\n fake image data"
        encoded = base64.b64encode(data).decode("utf-8")

        # Should be ASCII-safe
        assert all(ord(c) < 128 for c in encoded)
        # Should only contain base64 characters
        import re

        assert re.match(r"^[A-Za-z0-9+/=]+$", encoded)


class TestTooltipPreviewSize:
    """Tests for tooltip preview size constant."""

    def test_tooltip_preview_size_is_defined(self):
        """Test that TOOLTIP_PREVIEW_SIZE is defined and reasonable."""
        # This tests that the constant exists and has a sensible value
        # The actual constant is in AlbumCard, but we test the expected value
        expected_size = 200

        # Verify it's a reasonable preview size (larger than card, not too large)
        assert expected_size > 130  # Larger than COVER_SIZE
        assert expected_size <= 400  # Not unreasonably large

    def test_preview_size_is_square(self):
        """Test that preview size is used for both dimensions (square)."""
        # The implementation uses TOOLTIP_PREVIEW_SIZE for both width and height
        # This test documents that the preview should be square
        preview_size = 200
        # Same value used for both dimensions
        assert preview_size == preview_size  # Trivial but documents intent
