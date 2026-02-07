"""
Music library scanner for detecting albums and their cover art status.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path

# Import ScanCache with TYPE_CHECKING to avoid circular imports
from typing import TYPE_CHECKING

from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

from ..utils.acoustid_tags import extract_acoustid
from ..utils.metadata import (
    extract_barcode,
    extract_discogs_id,
    extract_isrc,
    extract_musicbrainz_ids,
)
from .embedder import extract_embedded_cover
from .metadata_cleaner import clean_album, clean_artist
from .models import AlbumInfo, CoverInfo, TrackInfo
from .path_parser import parse_path

if TYPE_CHECKING:
    from .scan_cache import ScanCache

logger = logging.getLogger(__name__)

# Supported audio extensions
AUDIO_EXTENSIONS: set[str] = {
    ".mp3",
    ".flac",
    ".ogg",
    ".oga",
    ".m4a",
    ".mp4",
    ".opus",
    ".wma",
    ".wav",
    ".aiff",
}

# Recognized cover filenames
COVER_FILENAMES: set[str] = {
    "cover",
    "folder",
    "front",
    "album",
    "albumart",
    "albumartsmall",
    "thumb",
    "disc",
    "artwork",
    "art",
    "scan",
    "jacket",
}

# Supported image extensions
COVER_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def _get_image_dimensions_from_bytes(data: bytes) -> tuple[int, int] | None:
    """
    Get image dimensions from raw bytes without loading the full image.

    Args:
        data: Raw image data

    Returns:
        Tuple of (width, height) or None if unable to determine
    """
    try:
        # Try PIL/Pillow first if available
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        return img.size
    except ImportError:
        pass
    except OSError:
        pass

    # Fallback: Parse image headers manually
    try:
        # PNG
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            if len(data) >= 24:
                import struct

                width = struct.unpack(">I", data[16:20])[0]
                height = struct.unpack(">I", data[20:24])[0]
                return (width, height)

        # JPEG
        elif data[:2] == b"\xff\xd8":
            import struct

            i = 2
            while i < len(data) - 8:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                # SOF0, SOF1, SOF2 markers contain dimensions
                if marker in (0xC0, 0xC1, 0xC2):
                    height = struct.unpack(">H", data[i + 5 : i + 7])[0]
                    width = struct.unpack(">H", data[i + 7 : i + 9])[0]
                    return (width, height)
                elif marker == 0xD9:  # EOI
                    break
                elif marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01):
                    i += 2
                else:
                    length = struct.unpack(">H", data[i + 2 : i + 4])[0]
                    i += 2 + length
    except (struct.error, IndexError):
        pass

    return None


def _get_image_dimensions_from_file(filepath: Path) -> tuple[int, int] | None:
    """
    Get image dimensions from a file.

    Args:
        filepath: Path to image file

    Returns:
        Tuple of (width, height) or None if unable to determine
    """
    try:
        from PIL import Image

        with Image.open(filepath) as img:
            return img.size
    except ImportError:
        pass
    except OSError:
        pass

    # Fallback: read bytes and parse
    try:
        data = filepath.read_bytes()[:1024]  # Read first 1KB for header parsing
        return _get_image_dimensions_from_bytes(data)
    except OSError:
        pass

    return None


class MusicScanner:
    """
    Scanner for music libraries that detects albums and their cover art status.
    """

    def __init__(
        self,
        exclude_patterns: list[str] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancelled_callback: Callable[[], bool] | None = None,
    ):
        """
        Initialize the scanner.

        Args:
            exclude_patterns: List of directory name patterns to exclude
            progress_callback: Callback function(current, total, message) for progress updates
            cancelled_callback: Callback function that returns True if scan should be cancelled
        """
        self.exclude_patterns = exclude_patterns or []
        self.progress_callback = progress_callback
        self.cancelled_callback = cancelled_callback

    def scan_library(
        self,
        music_dir: Path,
        scan_cache: "ScanCache | None" = None,
    ) -> list[AlbumInfo]:
        """
        Scan a music library and return information about all albums.

        Args:
            music_dir: Root directory of the music library
            scan_cache: Optional ScanCache for incremental scanning.
                        If provided, unchanged folders will use cached data.

        Returns:
            List of AlbumInfo objects for each detected album
        """
        albums = []
        album_folders = self._find_album_folders(music_dir)
        total = len(album_folders)

        cached_count = 0
        scanned_count = 0

        logger.info(f"Found {total} album folders to scan")

        for i, folder in enumerate(album_folders, 1):
            # Check for cancellation
            if self.cancelled_callback and self.cancelled_callback():
                logger.info("Scan cancelled")
                break

            if self.progress_callback:
                self.progress_callback(i, total, str(folder))

            # Try to use cached data if scan_cache is provided
            if scan_cache is not None and not scan_cache.is_folder_changed(folder):
                cached_album = scan_cache.get_cached_album(folder)
                if cached_album is not None:
                    albums.append(cached_album)
                    cached_count += 1
                    continue

            # Scan the folder (may return multiple AlbumInfo for individual files)
            folder_albums = self._scan_album_folder(folder)
            if folder_albums:
                albums.extend(folder_albums)
                scanned_count += len(folder_albums)

                # Update cache with new scan result
                # Only cache real albums (single AlbumInfo), not individual files
                # Individual files (multiple AlbumInfo per folder) are not cached
                # to avoid data loss on subsequent scans
                if scan_cache is not None and len(folder_albums) == 1:
                    scan_cache.update_folder(folder, folder_albums[0])

        if scan_cache is not None:
            logger.info(f"Scan complete: {scanned_count} scanned, {cached_count} from cache")
        else:
            logger.info(f"Scan complete: {len(albums)} albums")

        return albums

    def _should_exclude(self, dirname: str) -> bool:
        """Check if a directory should be excluded."""
        if dirname.startswith("."):
            return True
        return any(pattern.lower() in dirname.lower() for pattern in self.exclude_patterns)

    def _walk_error_handler(self, error: OSError) -> None:
        """Error handler for os.walk()."""
        logger.warning(f"Access error: {error.filename} - {error.strerror}")

    def _find_album_folders(self, music_dir: Path) -> list[Path]:
        """
        Find all album folders in a music library.

        An album folder is any folder containing audio files.
        """
        album_folders = []

        try:
            for root, dirs, files in os.walk(music_dir, onerror=self._walk_error_handler):
                root_path = Path(root)

                # Filter out excluded directories
                dirs[:] = [d for d in dirs if not self._should_exclude(d)]

                # Check if this folder contains audio files
                has_audio = any(Path(f).suffix.lower() in AUDIO_EXTENSIONS for f in files)

                if has_audio:
                    album_folders.append(root_path)
        except PermissionError as e:
            logger.error(f"Permission denied: {music_dir}: {e}")

        return album_folders

    def _scan_album_folder(self, folder: Path) -> list[AlbumInfo]:
        """
        Scan a single folder and return album information.

        If files share common album metadata, they are grouped as one album.
        If files have different or missing album metadata (individual files),
        each file is returned as its own AlbumInfo.

        Returns:
            List of AlbumInfo objects (one for album, or multiple for individual files)
        """
        audio_files = []
        formats = set()

        try:
            for item in folder.iterdir():
                if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS:
                    audio_files.append(item)
                    formats.add(item.suffix.lower())
        except PermissionError:
            logger.warning(f"Permission denied: {folder}")
            return []
        except OSError as e:
            logger.warning(f"Error accessing {folder}: {e}")
            return []

        if not audio_files:
            return []

        # Check if this is an album folder or a folder of individual files
        is_album, common_metadata = self._detect_album_vs_individual(audio_files)

        if not is_album:
            # Individual files: create one AlbumInfo per file
            return self._create_individual_file_albums(audio_files, folder)

        # Album folder: group all files as one album
        # Check for covers
        has_embedded = self._check_embedded_cover(audio_files)
        folder_cover = self._check_folder_cover(folder)

        # Use common metadata or extract from first file
        metadata = common_metadata or self._extract_metadata(audio_files[0])

        # Initialize cover comparison fields
        covers_differ = False
        embedded_dimensions = None
        folder_dimensions = None
        embedded_size_bytes = None
        folder_size_bytes = None
        embedded_mime_type = None
        folder_mime_type = None

        folder_path = folder / folder_cover[1] if folder_cover[1] else None

        # Extract embedded cover data once if it exists
        # (matches the logic in _check_embedded_cover which checks first 3 files)
        embedded_data = None
        if has_embedded:
            for audio_file in audio_files[:3]:
                embedded_data = extract_embedded_cover(audio_file)
                if embedded_data:
                    embedded_mime_type = self._detect_mime_type_from_bytes(embedded_data)
                    embedded_dimensions = _get_image_dimensions_from_bytes(embedded_data)
                    embedded_size_bytes = len(embedded_data)
                    break

        # Get folder cover info if it exists
        if folder_cover[0] and folder_path:
            try:
                folder_data = folder_path.read_bytes()
                folder_dimensions = _get_image_dimensions_from_bytes(folder_data)
                folder_size_bytes = len(folder_data)
                folder_mime_type = self._detect_mime_type_from_extension(folder_path)

                # Compare bytes to detect if covers differ (only if both exist)
                if embedded_data:
                    covers_differ = embedded_data != folder_data
            except OSError as e:
                logger.debug(f"Error reading folder cover {folder_path}: {e}")

        cover_info = CoverInfo(
            has_embedded=has_embedded,
            has_folder=folder_cover[0],
            folder_file=folder_cover[1],
            folder_path=folder_path,
            covers_differ=covers_differ,
            embedded_dimensions=embedded_dimensions,
            folder_dimensions=folder_dimensions,
            embedded_size_bytes=embedded_size_bytes,
            folder_size_bytes=folder_size_bytes,
            embedded_mime_type=embedded_mime_type,
            folder_mime_type=folder_mime_type,
        )

        # Create TrackInfo for each audio file (required for AcoustID fingerprinting)
        tracks = []
        for audio_file in audio_files:
            file_metadata = self._extract_metadata(audio_file)
            track_info = TrackInfo(
                path=audio_file,
                filename=audio_file.name,
                format=audio_file.suffix.lower(),
                has_embedded_cover=self._file_has_embedded_cover(audio_file),
                artist=file_metadata.get("artist"),
                album=file_metadata.get("album"),
                title=file_metadata.get("title"),
                year=file_metadata.get("year"),
                musicbrainz_albumid=file_metadata.get("musicbrainz_albumid"),
                musicbrainz_releasegroupid=file_metadata.get("musicbrainz_releasegroupid"),
                musicbrainz_artistid=file_metadata.get("musicbrainz_artistid"),
                isrc=file_metadata.get("isrc"),
            )
            tracks.append(track_info)

        return [
            AlbumInfo(
                path=folder,
                artist=metadata.get("artist"),
                album=metadata.get("album"),
                year=metadata.get("year"),
                track_count=len(audio_files),
                tracks=tracks,
                cover=cover_info,
                sample_file=audio_files[0],
                formats=list(formats),
                musicbrainz_albumid=metadata.get("musicbrainz_albumid"),
                musicbrainz_releasegroupid=metadata.get("musicbrainz_releasegroupid"),
                musicbrainz_artistid=metadata.get("musicbrainz_artistid"),
                isrc=metadata.get("isrc"),
                barcode=metadata.get("barcode"),
                discogs_release_id=metadata.get("discogs_release_id"),
                acoustid=metadata.get("acoustid"),
                metadata_source=metadata.get("metadata_source"),
            )
        ]

    def _detect_album_vs_individual(self, audio_files: list[Path]) -> tuple[bool, dict | None]:
        """
        Detect if files in a folder form an album or are individual files.

        An album is detected when:
        - All files share the same non-empty album tag
        - Or all files share the same artist tag (compilation-like)

        Returns:
            Tuple of (is_album, common_metadata)
            - is_album: True if files form an album
            - common_metadata: Shared metadata dict if is_album, else None
        """
        if len(audio_files) == 1:
            # Single file is always treated as individual
            return False, None

        # Extract metadata from all files (up to first 10 for performance)
        files_to_check = audio_files[:10]
        all_metadata = []

        for filepath in files_to_check:
            try:
                metadata = self._extract_metadata(filepath)
                all_metadata.append(metadata)
            except FileNotFoundError:
                logger.debug(f"File not found: {filepath}")
                all_metadata.append({})
            except PermissionError as e:
                logger.warning(f"Permission denied reading {filepath}: {e}")
                all_metadata.append({})
            except (OSError, MutagenError) as e:
                logger.debug(f"Error extracting metadata from {filepath}: {e}")
                all_metadata.append({})

        if not all_metadata:
            return False, None

        # Check if all files share a common album name
        albums = [m.get("album") for m in all_metadata if m.get("album")]
        artists = [m.get("artist") for m in all_metadata if m.get("artist")]

        # If no album tags at all, treat as individual files
        if not albums:
            logger.debug("No album tags found, treating as individual files")
            return False, None

        # If all files have the same album tag, it's an album
        unique_albums = set(albums)
        if len(unique_albums) == 1 and len(albums) == len(files_to_check):
            # All files have the same album tag
            common_album = albums[0]
            common_artist = artists[0] if artists else None

            # Use first file's full metadata as base
            common_metadata = all_metadata[0].copy()
            common_metadata["album"] = common_album
            if common_artist:
                common_metadata["artist"] = common_artist

            logger.debug(f"Detected album: {common_album}")
            return True, common_metadata

        # If majority (>= 70%) have the same album, still treat as album
        if albums:
            most_common_album = max(set(albums), key=albums.count)
            album_ratio = albums.count(most_common_album) / len(files_to_check)
            if album_ratio >= 0.7:
                logger.debug(
                    f"Detected album (majority): {most_common_album} ({album_ratio:.0%} match)"
                )
                # Find a file with this album for metadata
                for m in all_metadata:
                    if m.get("album") == most_common_album:
                        return True, m
                return True, all_metadata[0]

        # Files have different album tags - individual files
        logger.debug(
            f"Different album tags detected ({len(unique_albums)} unique), "
            f"treating as individual files"
        )
        return False, None

    def _create_individual_file_albums(
        self, audio_files: list[Path], folder: Path
    ) -> list[AlbumInfo]:
        """
        Create individual AlbumInfo objects for each file in a folder.

        Each file gets its own AlbumInfo with track_count=1.
        When multiple files are in the folder (shared folder), we:
        - Set is_shared_folder=True to prevent external cover saving
        - Set path=filepath (the file itself, not the folder)
        """
        albums = []
        folder_cover = self._check_folder_cover(folder)

        # Shared folder: multiple unrelated files in the same directory
        is_shared_folder = len(audio_files) > 1

        for filepath in audio_files:
            try:
                metadata = self._extract_metadata(filepath)

                # Check for embedded cover in this file
                has_embedded = self._file_has_embedded_cover(filepath)

                # Get embedded cover details if present
                embedded_dimensions = None
                embedded_size_bytes = None
                embedded_mime_type = None
                embedded_data = None

                if has_embedded:
                    embedded_data = extract_embedded_cover(filepath)
                    if embedded_data:
                        embedded_mime_type = self._detect_mime_type_from_bytes(embedded_data)
                        embedded_dimensions = _get_image_dimensions_from_bytes(embedded_data)
                        embedded_size_bytes = len(embedded_data)

                # Folder cover info (shared for all files in folder)
                folder_path = folder / folder_cover[1] if folder_cover[1] else None
                folder_dimensions = None
                folder_size_bytes = None
                folder_mime_type = None
                covers_differ = False

                if folder_cover[0] and folder_path:
                    try:
                        folder_data = folder_path.read_bytes()
                        folder_dimensions = _get_image_dimensions_from_bytes(folder_data)
                        folder_size_bytes = len(folder_data)
                        folder_mime_type = self._detect_mime_type_from_extension(folder_path)
                        if embedded_data:
                            covers_differ = embedded_data != folder_data
                    except OSError:
                        pass

                cover_info = CoverInfo(
                    has_embedded=has_embedded,
                    has_folder=folder_cover[0],
                    folder_file=folder_cover[1],
                    folder_path=folder_path,
                    covers_differ=covers_differ,
                    embedded_dimensions=embedded_dimensions,
                    folder_dimensions=folder_dimensions,
                    embedded_size_bytes=embedded_size_bytes,
                    folder_size_bytes=folder_size_bytes,
                    embedded_mime_type=embedded_mime_type,
                    folder_mime_type=folder_mime_type,
                )

                # Use the file path directly for individual files
                # This allows proper detection of single-file entries
                # Use title or filename as album name for display
                display_album = metadata.get("album")
                if not display_album:
                    # Use filename without extension as album name
                    display_album = filepath.stem

                # Create TrackInfo for this file (required for AcoustID fingerprinting)
                track_info = TrackInfo(
                    path=filepath,
                    filename=filepath.name,
                    format=filepath.suffix.lower(),
                    has_embedded_cover=has_embedded,
                    artist=metadata.get("artist"),
                    album=metadata.get("album"),
                    title=metadata.get("title"),
                    year=metadata.get("year"),
                    musicbrainz_albumid=metadata.get("musicbrainz_albumid"),
                    musicbrainz_releasegroupid=metadata.get("musicbrainz_releasegroupid"),
                    musicbrainz_artistid=metadata.get("musicbrainz_artistid"),
                    isrc=metadata.get("isrc"),
                )

                album_info = AlbumInfo(
                    path=filepath,  # Use file path, not folder
                    artist=metadata.get("artist"),
                    album=display_album,
                    year=metadata.get("year"),
                    track_count=1,
                    tracks=[track_info],
                    cover=cover_info,
                    sample_file=filepath,
                    formats=[filepath.suffix.lower()],
                    musicbrainz_albumid=metadata.get("musicbrainz_albumid"),
                    musicbrainz_releasegroupid=metadata.get("musicbrainz_releasegroupid"),
                    musicbrainz_artistid=metadata.get("musicbrainz_artistid"),
                    isrc=metadata.get("isrc"),
                    barcode=metadata.get("barcode"),
                    discogs_release_id=metadata.get("discogs_release_id"),
                    acoustid=metadata.get("acoustid"),
                    is_shared_folder=is_shared_folder,
                    metadata_source=metadata.get("metadata_source"),
                )

                albums.append(album_info)

            except FileNotFoundError:
                logger.debug(f"File disappeared during scan: {filepath}")
                continue
            except PermissionError as e:
                logger.warning(f"Permission denied for {filepath}: {e}")
                continue
            except (OSError, MutagenError) as e:
                logger.warning(f"Error creating album info for {filepath}: {e}")
                continue

        logger.debug(f"Created {len(albums)} individual file albums from {folder}")
        return albums

    def _check_embedded_cover(self, audio_files: list[Path]) -> bool:
        """Check if any audio file has an embedded cover."""
        # Check first few files to determine if album has embedded covers
        return any(self._file_has_embedded_cover(filepath) for filepath in audio_files[:3])

    def _file_has_embedded_cover(self, filepath: Path) -> bool:
        """Check if a single file has an embedded cover."""
        audio = None
        try:
            audio = MutagenFile(filepath)
            if audio is None:
                return False

            # FLAC
            if isinstance(audio, FLAC):
                return bool(audio.pictures)

            # MP3 with ID3
            if hasattr(audio, "tags") and audio.tags:
                tags = audio.tags
                # ID3 APIC frames
                # ASFTags (WMA) inherits from list: iterating directly yields tuples,
                # not string keys. Explicit .keys() is required here.
                if any(key.startswith("APIC") for key in tags.keys()):  # noqa: SIM118
                    return True

            # MP4/M4A
            if isinstance(audio, MP4):
                return "covr" in audio.tags if audio.tags else False

            # OGG Vorbis
            if isinstance(audio, OggVorbis):
                return "metadata_block_picture" in audio if audio else False

            # Generic check for other formats
            return bool(hasattr(audio, "pictures") and audio.pictures)
        except OSError as e:
            logger.debug(f"I/O error checking embedded cover in {filepath}: {e}")
            return False
        except MutagenError as e:
            logger.debug(f"Error checking embedded cover in {filepath}: {e}")
            return False
        finally:
            # Mutagen file objects don't have explicit close, but we ensure cleanup
            if audio is not None:
                del audio

    def _check_folder_cover(self, folder: Path) -> tuple[bool, str | None]:
        """Check if a folder contains a cover image file."""
        try:
            for item in folder.iterdir():
                if item.is_file():
                    stem = item.stem.lower()
                    suffix = item.suffix.lower()
                    if suffix in COVER_EXTENSIONS and (
                        stem in COVER_FILENAMES or any(name in stem for name in COVER_FILENAMES)
                    ):
                        return True, item.name
        except PermissionError:
            logger.warning(f"Permission denied: {folder}")
        except OSError as e:
            logger.warning(f"Error accessing {folder}: {e}")
        return False, None

    def _detect_mime_type_from_bytes(self, data: bytes) -> str | None:
        """Detect image MIME type from raw bytes."""
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        elif data[:2] == b"\xff\xd8":
            return "image/jpeg"
        elif data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        elif data[:2] == b"BM":
            return "image/bmp"
        return None

    def _detect_mime_type_from_extension(self, filepath: Path) -> str | None:
        """Detect image MIME type from file extension."""
        ext = filepath.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        return mime_map.get(ext)

    def _extract_metadata(self, filepath: Path) -> dict:
        """
        Extract metadata from an audio file.

        This method implements a multi-level extraction strategy:
        1. Extract from audio tags (primary source)
        2. Extract additional identifiers (ISRC, barcode, Discogs ID)
        3. Fall back to path parsing if tags are missing
        4. Clean metadata to remove noise (remaster tags, etc.)
        """
        metadata = {
            "artist": None,
            "album": None,
            "year": None,
            "musicbrainz_albumid": None,
            "musicbrainz_releasegroupid": None,
            "musicbrainz_artistid": None,
            "isrc": None,
            "barcode": None,
            "discogs_release_id": None,
            "acoustid": None,
            "metadata_source": None,
        }
        audio_easy = None

        try:
            # First pass: easy tags for basic metadata
            audio_easy = MutagenFile(filepath, easy=True)
            easy_tags = None
            if audio_easy is not None and hasattr(audio_easy, "tags") and audio_easy.tags:
                easy_tags = audio_easy.tags

                # Artist
                for key in ["albumartist", "artist", "performer"]:
                    if easy_tags.get(key):
                        metadata["artist"] = easy_tags[key][0]
                        break

                # Album
                if easy_tags.get("album"):
                    metadata["album"] = easy_tags["album"][0]

                # Year
                for key in ["date", "year", "originaldate"]:
                    if easy_tags.get(key):
                        year_str = easy_tags[key][0]
                        if year_str:
                            metadata["year"] = year_str[:4]
                        break

            # MusicBrainz IDs - use shared extraction function
            mbids = extract_musicbrainz_ids(filepath, easy_tags)
            metadata.update(mbids)

            # Additional identifiers
            metadata["isrc"] = extract_isrc(filepath, easy_tags)
            metadata["barcode"] = extract_barcode(filepath, easy_tags)
            metadata["discogs_release_id"] = extract_discogs_id(filepath, easy_tags)
            metadata["acoustid"] = extract_acoustid(filepath)

            # Track metadata source
            if metadata["artist"] or metadata["album"]:
                metadata["metadata_source"] = "tags"

        except OSError as e:
            logger.debug(f"I/O error extracting metadata from {filepath}: {e}")
        except MutagenError as e:
            logger.debug(f"Error extracting metadata from {filepath}: {e}")
        finally:
            if audio_easy is not None:
                del audio_easy

        # Fallback: parse from folder path if tags are missing
        if not metadata["artist"] and not metadata["album"]:
            try:
                parsed = parse_path(filepath.parent)
                if parsed.artist or parsed.album:
                    metadata["artist"] = parsed.artist
                    metadata["album"] = parsed.album
                    metadata["year"] = metadata["year"] or parsed.year
                    metadata["metadata_source"] = "path"
                    logger.debug(
                        f"Extracted from path: artist={parsed.artist!r}, "
                        f"album={parsed.album!r}, year={parsed.year!r}"
                    )
            except (ValueError, OSError) as e:
                logger.debug(f"Error parsing path for {filepath}: {e}")

        # Clean metadata to remove noise (remaster tags, etc.)
        if metadata["artist"]:
            metadata["artist"] = clean_artist(metadata["artist"])
        if metadata["album"]:
            metadata["album"] = clean_album(metadata["album"])

        # Log if we found MBIDs
        if metadata["musicbrainz_albumid"]:
            logger.debug(f"Found MBID for {filepath.name}: {metadata['musicbrainz_albumid']}")

        return metadata

    def rescan_album_covers(self, album: AlbumInfo) -> None:
        """
        Rescan cover information for a single album folder.

        Updates cover dimensions, sizes, mime types, and comparison status.
        Call this after any cover modification (add/remove/sync) to refresh metadata.

        Args:
            album: AlbumInfo object to update (modified in place)
        """
        try:
            # Get audio files from album folder
            audio_files = []
            for item in album.path.iterdir():
                if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS:
                    audio_files.append(item)

            if not audio_files:
                return

            # Re-check covers
            has_embedded = self._check_embedded_cover(audio_files)
            folder_cover = self._check_folder_cover(album.path)

            # Reset cover info fields
            covers_differ = False
            embedded_dimensions = None
            folder_dimensions = None
            embedded_size_bytes = None
            folder_size_bytes = None
            embedded_mime_type = None
            folder_mime_type = None

            folder_path = album.path / folder_cover[1] if folder_cover[1] else None

            # Extract embedded cover data if it exists
            embedded_data = None
            if has_embedded:
                for audio_file in audio_files[:3]:
                    embedded_data = extract_embedded_cover(audio_file, use_cache=False)
                    if embedded_data:
                        embedded_mime_type = self._detect_mime_type_from_bytes(embedded_data)
                        embedded_dimensions = _get_image_dimensions_from_bytes(embedded_data)
                        embedded_size_bytes = len(embedded_data)
                        break

            # Get folder cover info if it exists
            if folder_cover[0] and folder_path:
                try:
                    folder_data = folder_path.read_bytes()
                    folder_dimensions = _get_image_dimensions_from_bytes(folder_data)
                    folder_size_bytes = len(folder_data)
                    folder_mime_type = self._detect_mime_type_from_extension(folder_path)

                    # Compare bytes to detect if covers differ
                    if embedded_data:
                        covers_differ = embedded_data != folder_data
                except OSError as e:
                    logger.debug(f"Error reading folder cover {folder_path}: {e}")

            # Update album cover info in place
            album.cover.has_embedded = has_embedded
            album.cover.has_folder = folder_cover[0]
            album.cover.folder_file = folder_cover[1]
            album.cover.folder_path = folder_path
            album.cover.covers_differ = covers_differ
            album.cover.embedded_dimensions = embedded_dimensions
            album.cover.folder_dimensions = folder_dimensions
            album.cover.embedded_size_bytes = embedded_size_bytes
            album.cover.folder_size_bytes = folder_size_bytes
            album.cover.embedded_mime_type = embedded_mime_type
            album.cover.folder_mime_type = folder_mime_type
            # Clear cached hashes (will be recomputed on-demand)
            album.cover.embedded_hash = None
            album.cover.folder_hash = None

            logger.debug(f"Rescanned covers for {album.display_name}")

        except OSError as e:
            logger.error(f"Error rescanning album {album.path}: {e}")
