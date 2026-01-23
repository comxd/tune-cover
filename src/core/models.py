"""
Data models for TuneCover.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


class CoverStatus(Enum):
    """Status of album cover art."""

    NONE = auto()
    EMBEDDED_ONLY = auto()
    FOLDER_ONLY = auto()
    BOTH = auto()


class ProcessingStatus(Enum):
    """Status of cover processing operation."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    NO_MATCH = "no_match"
    NO_COVER = "no_cover"
    ERROR = "error"
    QUIT = "quit"


@dataclass(slots=True)
class TrackInfo:
    """Information about a single audio track.

    Uses slots=True for ~20-25% memory reduction and faster attribute access.
    """

    path: Path
    filename: str
    format: str
    has_embedded_cover: bool = False
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_number: int | None = None
    year: str | None = None
    # MusicBrainz IDs for direct lookups
    musicbrainz_albumid: str | None = None
    musicbrainz_releasegroupid: str | None = None
    musicbrainz_artistid: str | None = None
    # Additional identifiers
    isrc: str | None = None  # ISRC is per-track, not per-album

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "path": str(self.path),
            "filename": self.filename,
            "format": self.format,
            "has_embedded_cover": self.has_embedded_cover,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "track_number": self.track_number,
            "year": self.year,
            "musicbrainz_albumid": self.musicbrainz_albumid,
            "musicbrainz_releasegroupid": self.musicbrainz_releasegroupid,
            "musicbrainz_artistid": self.musicbrainz_artistid,
            "isrc": self.isrc,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrackInfo":
        """Create TrackInfo from dictionary."""
        return cls(
            path=Path(data["path"]),
            filename=data["filename"],
            format=data["format"],
            has_embedded_cover=data.get("has_embedded_cover", False),
            artist=data.get("artist"),
            album=data.get("album"),
            title=data.get("title"),
            track_number=data.get("track_number"),
            year=data.get("year"),
            musicbrainz_albumid=data.get("musicbrainz_albumid"),
            musicbrainz_releasegroupid=data.get("musicbrainz_releasegroupid"),
            musicbrainz_artistid=data.get("musicbrainz_artistid"),
            isrc=data.get("isrc"),
        )


@dataclass(slots=True)
class CoverInfo:
    """Information about album cover art.

    Uses slots=True for ~20-25% memory reduction and faster attribute access.
    """

    has_embedded: bool = False
    has_folder: bool = False
    folder_file: str | None = None
    embedded_mime_type: str | None = None
    folder_path: Path | None = None
    # Cover comparison info (when both exist)
    covers_differ: bool = False  # True if embedded and folder covers have different bytes
    embedded_dimensions: tuple | None = None  # (width, height) or None
    folder_dimensions: tuple | None = None  # (width, height) or None
    embedded_size_bytes: int | None = None
    folder_size_bytes: int | None = None
    folder_mime_type: str | None = None
    # Cover hashes for finding identical covers (computed on-demand)
    embedded_hash: str | None = None  # SHA256 hash of embedded cover
    folder_hash: str | None = None  # SHA256 hash of folder cover

    @property
    def status(self) -> CoverStatus:
        """Get the cover status."""
        if self.has_embedded and self.has_folder:
            return CoverStatus.BOTH
        elif self.has_embedded:
            return CoverStatus.EMBEDDED_ONLY
        elif self.has_folder:
            return CoverStatus.FOLDER_ONLY
        return CoverStatus.NONE

    @property
    def has_any(self) -> bool:
        """Check if any cover exists."""
        return self.has_embedded or self.has_folder

    @property
    def dimensions_differ(self) -> bool:
        """Check if embedded and folder cover dimensions differ."""
        if self.embedded_dimensions and self.folder_dimensions:
            return self.embedded_dimensions != self.folder_dimensions
        return False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "has_embedded": self.has_embedded,
            "has_folder": self.has_folder,
            "folder_file": self.folder_file,
            "embedded_mime_type": self.embedded_mime_type,
            "folder_path": str(self.folder_path) if self.folder_path else None,
            "covers_differ": self.covers_differ,
            "embedded_dimensions": self.embedded_dimensions,
            "folder_dimensions": self.folder_dimensions,
            "embedded_size_bytes": self.embedded_size_bytes,
            "folder_size_bytes": self.folder_size_bytes,
            "folder_mime_type": self.folder_mime_type,
            "embedded_hash": self.embedded_hash,
            "folder_hash": self.folder_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoverInfo":
        """Create CoverInfo from dictionary."""
        folder_path = data.get("folder_path")
        embedded_dimensions = data.get("embedded_dimensions")
        folder_dimensions = data.get("folder_dimensions")
        return cls(
            has_embedded=data.get("has_embedded", False),
            has_folder=data.get("has_folder", False),
            folder_file=data.get("folder_file"),
            embedded_mime_type=data.get("embedded_mime_type"),
            folder_path=Path(folder_path) if folder_path else None,
            covers_differ=data.get("covers_differ", False),
            embedded_dimensions=tuple(embedded_dimensions) if embedded_dimensions else None,
            folder_dimensions=tuple(folder_dimensions) if folder_dimensions else None,
            embedded_size_bytes=data.get("embedded_size_bytes"),
            folder_size_bytes=data.get("folder_size_bytes"),
            folder_mime_type=data.get("folder_mime_type"),
            embedded_hash=data.get("embedded_hash"),
            folder_hash=data.get("folder_hash"),
        )


@dataclass(slots=True)
class AlbumInfo:
    """Information about an album detected in the library.

    Uses slots=True for ~20-25% memory reduction and faster attribute access.
    """

    path: Path
    artist: str | None = None
    album: str | None = None
    year: str | None = None
    track_count: int = 0
    tracks: list[TrackInfo] = field(default_factory=list)
    cover: CoverInfo = field(default_factory=CoverInfo)
    formats: list[str] = field(default_factory=list)
    sample_file: Path | None = None
    # MusicBrainz IDs for direct lookups (extracted from audio tags)
    musicbrainz_albumid: str | None = None
    musicbrainz_releasegroupid: str | None = None
    musicbrainz_artistid: str | None = None
    # Additional identifiers for multi-source lookups
    isrc: str | None = None  # International Standard Recording Code
    barcode: str | None = None  # UPC/EAN barcode
    discogs_release_id: str | None = None  # Discogs release ID
    acoustid: str | None = None  # AcoustID audio fingerprint identifier
    # Shared folder flag: True if this file is in a folder with other unrelated files
    # When True, external cover files should NOT be saved (would affect other files)
    is_shared_folder: bool = False
    # Forced group flag: True if this album was manually grouped from individual files
    # by the user (files had different/missing album tags but user wanted them as one album)
    is_forced_group: bool = False
    # Original file paths when is_forced_group=True (for ungrouping)
    forced_group_files: list[Path] = field(default_factory=list)
    # Compilation detection cache (lazy-loaded on first search panel open)
    is_compilation: bool | None = None
    compilation_detection_reason: str | None = None
    # Metadata source tracking (for debugging/display)
    metadata_source: str | None = None  # 'tags', 'path', or 'fingerprint'

    @property
    def has_any_cover(self) -> bool:
        """Check if any cover exists."""
        return self.cover.has_any

    @property
    def cover_status(self) -> CoverStatus:
        """Get the cover status."""
        return self.cover.status

    @property
    def display_name(self) -> str:
        """Get display name for the album."""
        from ..i18n import tr

        artist = self.artist or tr("Unknown artist")
        album = self.album or tr("Unknown album")
        return f"{artist} - {album}"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "path": str(self.path),
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "track_count": self.track_count,
            "tracks": [track.to_dict() for track in self.tracks],
            "cover": self.cover.to_dict(),
            "sample_file": str(self.sample_file) if self.sample_file else None,
            "formats": self.formats,
            "musicbrainz_albumid": self.musicbrainz_albumid,
            "musicbrainz_releasegroupid": self.musicbrainz_releasegroupid,
            "musicbrainz_artistid": self.musicbrainz_artistid,
            "isrc": self.isrc,
            "barcode": self.barcode,
            "discogs_release_id": self.discogs_release_id,
            "acoustid": self.acoustid,
            "is_shared_folder": self.is_shared_folder,
            "is_forced_group": self.is_forced_group,
            "forced_group_files": [str(f) for f in self.forced_group_files],
            "is_compilation": self.is_compilation,
            "compilation_detection_reason": self.compilation_detection_reason,
            "metadata_source": self.metadata_source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AlbumInfo":
        """Create AlbumInfo from dictionary."""
        # Handle cover info - support both old format and new format
        cover_data = data.get("cover")
        if cover_data and isinstance(cover_data, dict):
            cover = CoverInfo.from_dict(cover_data)
        else:
            # Legacy format compatibility
            cover = CoverInfo(
                has_embedded=data.get("has_embedded_cover", False),
                has_folder=data.get("has_folder_cover", False),
                folder_file=data.get("folder_cover_file"),
            )

        sample_file = data.get("sample_file")

        # Restore tracks if present in data
        tracks_data = data.get("tracks", [])
        tracks = [TrackInfo.from_dict(t) for t in tracks_data]

        return cls(
            path=Path(data["path"]),
            artist=data.get("artist"),
            album=data.get("album"),
            year=data.get("year"),
            track_count=data.get("track_count", 0),
            tracks=tracks,
            cover=cover,
            sample_file=Path(sample_file) if sample_file else None,
            formats=data.get("formats", []),
            musicbrainz_albumid=data.get("musicbrainz_albumid"),
            musicbrainz_releasegroupid=data.get("musicbrainz_releasegroupid"),
            musicbrainz_artistid=data.get("musicbrainz_artistid"),
            isrc=data.get("isrc"),
            barcode=data.get("barcode"),
            discogs_release_id=data.get("discogs_release_id"),
            acoustid=data.get("acoustid"),
            is_shared_folder=data.get("is_shared_folder", False),
            is_forced_group=data.get("is_forced_group", False),
            forced_group_files=[Path(f) for f in data.get("forced_group_files", [])],
            is_compilation=data.get("is_compilation"),
            compilation_detection_reason=data.get("compilation_detection_reason"),
            metadata_source=data.get("metadata_source"),
        )


@dataclass(slots=True)
class SearchResult:
    """Result from a cover art search.

    Uses slots=True for ~20-25% memory reduction and faster attribute access.
    """

    provider: str
    mbid: str | None = None
    artist: str = ""
    album: str = ""
    year: str | None = None
    score: int = 0
    has_cover_art: bool = False
    cover_url: str | None = None
    thumbnail_url: str | None = None
    # Image metadata (populated after download)
    image_width: int | None = None
    image_height: int | None = None
    image_size_bytes: int | None = None

    @property
    def display_name(self) -> str:
        """Get display name for the search result."""
        year_str = f" ({self.year})" if self.year else ""
        return f"{self.artist} - {self.album}{year_str}"

    @property
    def image_dimensions_str(self) -> str:
        """Get formatted dimensions (e.g., '1000x1000')."""
        if self.image_width and self.image_height:
            return f"{self.image_width}x{self.image_height}"
        return "?"

    @property
    def image_size_kb(self) -> float | None:
        """Get image size in KB."""
        if self.image_size_bytes:
            return self.image_size_bytes / 1024
        return None

    @property
    def image_info_str(self) -> str:
        """Get formatted image info (e.g., '1000x1000 - 245 KB')."""
        parts = []
        if self.image_width and self.image_height:
            parts.append(f"{self.image_width}x{self.image_height}")
        if self.image_size_bytes:
            size_kb = self.image_size_bytes / 1024
            parts.append(f"{size_kb:.0f} KB")
        return " - ".join(parts) if parts else ""


@dataclass(slots=True)
class ProcessingResult:
    """Result of processing an album for cover art.

    Uses slots=True for ~20-25% memory reduction and faster attribute access.
    """

    album_path: str
    status: ProcessingStatus
    message: str
    mbid: str | None = None
    cover_saved_to: str | None = None
    provider: str | None = None
