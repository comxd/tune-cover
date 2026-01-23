"""
Tests for data models (CoverInfo, AlbumInfo serialization).
"""

import json
from pathlib import Path

from src.core.models import AlbumInfo, CoverInfo


class TestCoverInfo:
    """Tests for CoverInfo dataclass."""

    def test_to_dict_basic(self):
        """Test basic CoverInfo serialization."""
        cover = CoverInfo(
            has_embedded=True,
            has_folder=False,
            folder_file=None,
        )
        result = cover.to_dict()

        assert result["has_embedded"] is True
        assert result["has_folder"] is False
        assert result["folder_file"] is None

    def test_to_dict_full(self):
        """Test CoverInfo serialization with all fields."""
        cover = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="cover.jpg",
            embedded_mime_type="image/jpeg",
            folder_path=Path("/music/album"),
            covers_differ=True,
            embedded_dimensions=(500, 500),
            folder_dimensions=(1000, 1000),
            embedded_size_bytes=50000,
            folder_size_bytes=100000,
            folder_mime_type="image/jpeg",
        )
        result = cover.to_dict()

        assert result["has_embedded"] is True
        assert result["has_folder"] is True
        assert result["folder_file"] == "cover.jpg"
        assert result["embedded_mime_type"] == "image/jpeg"
        assert result["folder_path"] == "/music/album"
        assert result["covers_differ"] is True
        assert result["embedded_dimensions"] == (500, 500)
        assert result["folder_dimensions"] == (1000, 1000)
        assert result["embedded_size_bytes"] == 50000
        assert result["folder_size_bytes"] == 100000
        assert result["folder_mime_type"] == "image/jpeg"

    def test_from_dict_basic(self):
        """Test basic CoverInfo deserialization."""
        data = {
            "has_embedded": True,
            "has_folder": False,
        }
        cover = CoverInfo.from_dict(data)

        assert cover.has_embedded is True
        assert cover.has_folder is False
        assert cover.folder_file is None

    def test_from_dict_full(self):
        """Test CoverInfo deserialization with all fields."""
        data = {
            "has_embedded": True,
            "has_folder": True,
            "folder_file": "cover.jpg",
            "embedded_mime_type": "image/jpeg",
            "folder_path": "/music/album",
            "covers_differ": True,
            "embedded_dimensions": [500, 500],  # JSON uses lists
            "folder_dimensions": [1000, 1000],
            "embedded_size_bytes": 50000,
            "folder_size_bytes": 100000,
            "folder_mime_type": "image/jpeg",
        }
        cover = CoverInfo.from_dict(data)

        assert cover.has_embedded is True
        assert cover.has_folder is True
        assert cover.folder_file == "cover.jpg"
        assert cover.embedded_mime_type == "image/jpeg"
        assert cover.folder_path == Path("/music/album")
        assert cover.covers_differ is True
        assert cover.embedded_dimensions == (500, 500)
        assert cover.folder_dimensions == (1000, 1000)
        assert cover.embedded_size_bytes == 50000
        assert cover.folder_size_bytes == 100000
        assert cover.folder_mime_type == "image/jpeg"

    def test_roundtrip(self):
        """Test CoverInfo serialization roundtrip."""
        original = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="front.png",
            embedded_dimensions=(800, 800),
            folder_dimensions=(1200, 1200),
        )

        # Serialize and deserialize
        data = original.to_dict()
        json_str = json.dumps(data)
        restored_data = json.loads(json_str)
        restored = CoverInfo.from_dict(restored_data)

        assert restored.has_embedded == original.has_embedded
        assert restored.has_folder == original.has_folder
        assert restored.folder_file == original.folder_file
        assert restored.embedded_dimensions == original.embedded_dimensions
        assert restored.folder_dimensions == original.folder_dimensions


class TestAlbumInfo:
    """Tests for AlbumInfo dataclass."""

    def test_to_dict_basic(self):
        """Test basic AlbumInfo serialization."""
        album = AlbumInfo(
            path=Path("/music/Artist/Album"),
            artist="Test Artist",
            album="Test Album",
            year="2023",
            track_count=10,
        )
        result = album.to_dict()

        assert result["path"] == "/music/Artist/Album"
        assert result["artist"] == "Test Artist"
        assert result["album"] == "Test Album"
        assert result["year"] == "2023"
        assert result["track_count"] == 10
        assert "cover" in result

    def test_to_dict_with_cover(self):
        """Test AlbumInfo serialization with cover info."""
        cover = CoverInfo(has_embedded=True, has_folder=True, folder_file="cover.jpg")
        album = AlbumInfo(
            path=Path("/music/Artist/Album"),
            artist="Test Artist",
            album="Test Album",
            cover=cover,
        )
        result = album.to_dict()

        assert result["cover"]["has_embedded"] is True
        assert result["cover"]["has_folder"] is True
        assert result["cover"]["folder_file"] == "cover.jpg"

    def test_to_dict_with_musicbrainz_ids(self):
        """Test AlbumInfo serialization with MusicBrainz IDs."""
        album = AlbumInfo(
            path=Path("/music/Artist/Album"),
            artist="Test Artist",
            album="Test Album",
            musicbrainz_albumid="12345-abcde",
            musicbrainz_releasegroupid="67890-fghij",
            musicbrainz_artistid="11111-zzzzz",
        )
        result = album.to_dict()

        assert result["musicbrainz_albumid"] == "12345-abcde"
        assert result["musicbrainz_releasegroupid"] == "67890-fghij"
        assert result["musicbrainz_artistid"] == "11111-zzzzz"

    def test_from_dict_basic(self):
        """Test basic AlbumInfo deserialization."""
        data = {
            "path": "/music/Artist/Album",
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2023",
            "track_count": 10,
            "cover": {
                "has_embedded": False,
                "has_folder": False,
            },
            "formats": [".mp3", ".flac"],
        }
        album = AlbumInfo.from_dict(data)

        assert album.path == Path("/music/Artist/Album")
        assert album.artist == "Test Artist"
        assert album.album == "Test Album"
        assert album.year == "2023"
        assert album.track_count == 10
        assert album.formats == [".mp3", ".flac"]

    def test_from_dict_with_cover(self):
        """Test AlbumInfo deserialization with cover info."""
        data = {
            "path": "/music/Artist/Album",
            "cover": {
                "has_embedded": True,
                "has_folder": True,
                "folder_file": "cover.jpg",
            },
        }
        album = AlbumInfo.from_dict(data)

        assert album.cover.has_embedded is True
        assert album.cover.has_folder is True
        assert album.cover.folder_file == "cover.jpg"

    def test_from_dict_legacy_format(self):
        """Test AlbumInfo deserialization with legacy format (no nested cover)."""
        data = {
            "path": "/music/Artist/Album",
            "artist": "Test Artist",
            "album": "Test Album",
            "has_embedded_cover": True,
            "has_folder_cover": True,
            "folder_cover_file": "cover.jpg",
        }
        album = AlbumInfo.from_dict(data)

        assert album.cover.has_embedded is True
        assert album.cover.has_folder is True
        assert album.cover.folder_file == "cover.jpg"

    def test_from_dict_with_sample_file(self):
        """Test AlbumInfo deserialization with sample file."""
        data = {
            "path": "/music/Artist/Album",
            "sample_file": "/music/Artist/Album/01-track.mp3",
            "cover": {},
        }
        album = AlbumInfo.from_dict(data)

        assert album.sample_file == Path("/music/Artist/Album/01-track.mp3")

    def test_from_dict_with_musicbrainz_ids(self):
        """Test AlbumInfo deserialization with MusicBrainz IDs."""
        data = {
            "path": "/music/Artist/Album",
            "musicbrainz_albumid": "12345-abcde",
            "musicbrainz_releasegroupid": "67890-fghij",
            "musicbrainz_artistid": "11111-zzzzz",
            "cover": {},
        }
        album = AlbumInfo.from_dict(data)

        assert album.musicbrainz_albumid == "12345-abcde"
        assert album.musicbrainz_releasegroupid == "67890-fghij"
        assert album.musicbrainz_artistid == "11111-zzzzz"

    def test_roundtrip(self):
        """Test AlbumInfo serialization roundtrip."""
        cover = CoverInfo(
            has_embedded=True,
            has_folder=True,
            folder_file="cover.jpg",
            embedded_dimensions=(500, 500),
        )
        original = AlbumInfo(
            path=Path("/music/Artist/Album"),
            artist="Test Artist",
            album="Test Album",
            year="2023",
            track_count=12,
            cover=cover,
            sample_file=Path("/music/Artist/Album/01-track.mp3"),
            formats=[".mp3"],
            musicbrainz_albumid="12345-abcde",
        )

        # Serialize and deserialize
        data = original.to_dict()
        json_str = json.dumps(data)
        restored_data = json.loads(json_str)
        restored = AlbumInfo.from_dict(restored_data)

        assert restored.path == original.path
        assert restored.artist == original.artist
        assert restored.album == original.album
        assert restored.year == original.year
        assert restored.track_count == original.track_count
        assert restored.sample_file == original.sample_file
        assert restored.formats == original.formats
        assert restored.musicbrainz_albumid == original.musicbrainz_albumid
        assert restored.cover.has_embedded == original.cover.has_embedded
        assert restored.cover.has_folder == original.cover.has_folder
        assert restored.cover.folder_file == original.cover.folder_file
        assert restored.cover.embedded_dimensions == original.cover.embedded_dimensions

    def test_from_dict_missing_optional_fields(self):
        """Test AlbumInfo deserialization with missing optional fields."""
        data = {
            "path": "/music/Artist/Album",
        }
        album = AlbumInfo.from_dict(data)

        assert album.path == Path("/music/Artist/Album")
        assert album.artist is None
        assert album.album is None
        assert album.year is None
        assert album.track_count == 0
        assert album.formats == []
        assert album.sample_file is None
        assert album.musicbrainz_albumid is None

    def test_to_dict_with_forced_group(self):
        """Test AlbumInfo serialization with forced group fields."""
        album = AlbumInfo(
            path=Path("/music/Compilation"),
            artist="Various Artists",
            album="My Compilation",
            is_forced_group=True,
            forced_group_files=[
                Path("/music/Compilation/track1.mp3"),
                Path("/music/Compilation/track2.mp3"),
            ],
        )

        data = album.to_dict()

        assert data["is_forced_group"] is True
        assert data["forced_group_files"] == [
            "/music/Compilation/track1.mp3",
            "/music/Compilation/track2.mp3",
        ]

    def test_from_dict_with_forced_group(self):
        """Test AlbumInfo deserialization with forced group fields."""
        data = {
            "path": "/music/Compilation",
            "artist": "Various Artists",
            "album": "My Compilation",
            "is_forced_group": True,
            "forced_group_files": [
                "/music/Compilation/track1.mp3",
                "/music/Compilation/track2.mp3",
            ],
        }

        album = AlbumInfo.from_dict(data)

        assert album.is_forced_group is True
        assert len(album.forced_group_files) == 2
        assert album.forced_group_files[0] == Path("/music/Compilation/track1.mp3")
        assert album.forced_group_files[1] == Path("/music/Compilation/track2.mp3")

    def test_from_dict_missing_forced_group_fields(self):
        """Test backward compatibility: loading old format without forced_group fields."""
        data = {
            "path": "/music/Album",
            "artist": "Artist",
            "album": "Album",
            # No is_forced_group or forced_group_files
        }

        album = AlbumInfo.from_dict(data)

        # Should default to False and empty list
        assert album.is_forced_group is False
        assert album.forced_group_files == []

    def test_forced_group_roundtrip(self):
        """Test JSON roundtrip with forced group data."""
        original = AlbumInfo(
            path=Path("/music/Compilation"),
            artist="Various Artists",
            album="My Compilation",
            track_count=3,
            is_forced_group=True,
            forced_group_files=[
                Path("/music/Compilation/track1.mp3"),
                Path("/music/Compilation/track2.mp3"),
                Path("/music/Compilation/track3.mp3"),
            ],
        )

        data = original.to_dict()
        restored = AlbumInfo.from_dict(data)

        assert restored.is_forced_group == original.is_forced_group
        assert restored.forced_group_files == original.forced_group_files
        assert restored.artist == original.artist
        assert restored.album == original.album
        assert restored.track_count == original.track_count


class TestExportImportFormat:
    """Tests for the export/import JSON format."""

    def test_export_format_structure(self):
        """Test that export format has the expected structure."""
        albums = [
            AlbumInfo(
                path=Path("/music/Artist1/Album1"),
                artist="Artist 1",
                album="Album 1",
            ),
            AlbumInfo(
                path=Path("/music/Artist2/Album2"),
                artist="Artist 2",
                album="Album 2",
            ),
        ]

        export_data = {
            "version": "1.0",
            "export_date": "2024-01-24T12:00:00",
            "total_count": len(albums),
            "albums": [album.to_dict() for album in albums],
        }

        assert export_data["version"] == "1.0"
        assert "export_date" in export_data
        assert export_data["total_count"] == 2
        assert len(export_data["albums"]) == 2

    def test_import_format_parsing(self):
        """Test parsing of import format."""
        import_json = """
        {
            "version": "1.0",
            "export_date": "2024-01-24T12:00:00",
            "total_count": 2,
            "albums": [
                {
                    "path": "/music/Artist1/Album1",
                    "artist": "Artist 1",
                    "album": "Album 1",
                    "cover": {"has_embedded": false, "has_folder": true}
                },
                {
                    "path": "/music/Artist2/Album2",
                    "artist": "Artist 2",
                    "album": "Album 2",
                    "cover": {"has_embedded": true, "has_folder": false}
                }
            ]
        }
        """

        import_data = json.loads(import_json)
        albums = [AlbumInfo.from_dict(a) for a in import_data["albums"]]

        assert len(albums) == 2
        assert albums[0].artist == "Artist 1"
        assert albums[0].cover.has_folder is True
        assert albums[1].artist == "Artist 2"
        assert albums[1].cover.has_embedded is True

    def test_full_roundtrip_via_json(self):
        """Test full export/import cycle through JSON."""
        original_albums = [
            AlbumInfo(
                path=Path("/music/Artist1/Album1"),
                artist="Artist 1",
                album="Album 1",
                year="2020",
                track_count=10,
                cover=CoverInfo(has_embedded=True, has_folder=True),
                formats=[".flac"],
            ),
            AlbumInfo(
                path=Path("/music/Artist2/Album2"),
                artist="Artist 2",
                album="Album 2",
                year="2021",
                track_count=8,
                cover=CoverInfo(has_embedded=False, has_folder=False),
                formats=[".mp3"],
            ),
        ]

        # Export
        export_data = {
            "version": "1.0",
            "export_date": "2024-01-24T12:00:00",
            "total_count": len(original_albums),
            "albums": [album.to_dict() for album in original_albums],
        }
        json_str = json.dumps(export_data, indent=2)

        # Import
        import_data = json.loads(json_str)
        restored_albums = [AlbumInfo.from_dict(a) for a in import_data["albums"]]

        # Verify
        assert len(restored_albums) == len(original_albums)
        for orig, rest in zip(original_albums, restored_albums, strict=False):
            assert rest.path == orig.path
            assert rest.artist == orig.artist
            assert rest.album == orig.album
            assert rest.year == orig.year
            assert rest.track_count == orig.track_count
            assert rest.cover.has_embedded == orig.cover.has_embedded
            assert rest.cover.has_folder == orig.cover.has_folder
            assert rest.formats == orig.formats
