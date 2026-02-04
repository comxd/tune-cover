"""
Cover art embedding functionality for various audio formats.
"""

import base64
import contextlib
import logging
import os
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

from src.utils.cache import embedded_cover_cache

from .exceptions import TagWriteError, UnsupportedFormatError

logger = logging.getLogger(__name__)

# Audio formats that support cover embedding
EMBEDDABLE_FORMATS: set[str] = {".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".opus"}


def detect_image_mime_type(image_data: bytes) -> str:
    """
    Detect the MIME type of an image from its magic bytes.

    Args:
        image_data: Raw image data

    Returns:
        Detected MIME type or 'image/jpeg' as default
    """
    if image_data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    elif image_data[:2] == b"\xff\xd8":
        return "image/jpeg"
    elif image_data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    elif image_data[:4] == b"RIFF" and image_data[8:12] == b"WEBP":
        return "image/webp"
    elif image_data[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"


def get_extension_for_mime(mime_type: str) -> str:
    """Get file extension for a MIME type."""
    extension_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    return extension_map.get(mime_type, ".jpg")


def extract_embedded_cover(filepath: Path, use_cache: bool = True) -> bytes | None:
    """
    Extract embedded cover art from an audio file.

    Args:
        filepath: Path to the audio file
        use_cache: Whether to use the memory cache (default: True)

    Returns:
        Raw image data if found, None otherwise
    """
    # Check cache first
    if use_cache:
        cached = embedded_cover_cache.get(filepath)
        if cached is not None:
            return cached

    audio = None
    suffix = filepath.suffix.lower()
    result = None

    try:
        audio = MutagenFile(filepath)
        if audio is None:
            return None

        # FLAC
        if isinstance(audio, FLAC) and audio.pictures:
            result = audio.pictures[0].data

        # MP3 with ID3
        if result is None and hasattr(audio, "tags") and audio.tags:
            tags = audio.tags
            # ID3 APIC frames
            # ASFTags (WMA) inherits from list: iterating directly yields tuples,
            # not string keys. Explicit .keys() is required here.
            for key in tags.keys():  # noqa: SIM118
                if key.startswith("APIC"):
                    result = tags[key].data
                    break

        # MP4/M4A
        if result is None and isinstance(audio, MP4) and audio.tags and "covr" in audio.tags:
            covers = audio.tags["covr"]
            if covers:
                result = bytes(covers[0])

        # OGG Vorbis / Opus
        if (
            result is None
            and (isinstance(audio, OggVorbis) or suffix == ".opus")
            and audio
            and "metadata_block_picture" in audio
        ):
            try:
                picture_data = base64.b64decode(audio["metadata_block_picture"][0])
                # Parse the FLAC picture block
                picture = Picture(picture_data)
                result = picture.data
            except (ValueError, MutagenError):
                pass

        # Cache the result if we found cover data
        if result is not None and use_cache:
            embedded_cover_cache.put(filepath, result)

        return result
    except OSError as e:
        logger.debug(f"I/O error extracting cover from {filepath}: {e}")
        return None
    except MutagenError as e:
        logger.debug(f"Error extracting cover from {filepath}: {e}")
        return None
    finally:
        if audio is not None:
            del audio


def _validate_filename(filename: str) -> None:
    """
    Validate filename to prevent path traversal attacks.

    Args:
        filename: The filename to validate

    Raises:
        ValueError: If filename contains path separators or traversal sequences
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError(f"Invalid filename (path traversal attempt): {filename}")
    if filename.startswith("."):
        raise ValueError(f"Invalid filename (hidden file): {filename}")


class CoverEmbedder:
    """
    Embeds cover art into audio files.
    """

    def __init__(self, preserve_timestamp: bool = True) -> None:
        """
        Initialize the embedder.

        Args:
            preserve_timestamp: If True, preserve original file modification time after embedding.
        """
        self.preserve_timestamp = preserve_timestamp

    def save_cover_to_folder(
        self, cover_data: bytes, folder: Path, filename: str | None = None
    ) -> Path:
        """
        Save cover art to a folder.

        Args:
            cover_data: Raw image data
            folder: Target folder
            filename: Optional filename (auto-detected extension if None)

        Returns:
            Path to the saved cover file

        Raises:
            ValueError: If filename is invalid
            OSError: If folder is not accessible
        """
        if filename is None:
            mime_type = detect_image_mime_type(cover_data)
            extension = get_extension_for_mime(mime_type)
            filename = f"cover{extension}"
        else:
            _validate_filename(filename)

        try:
            # Ensure folder exists
            folder.mkdir(parents=True, exist_ok=True)

            cover_path = folder / filename
            with cover_path.open("wb") as f:
                f.write(cover_data)

            logger.info(f"Saved cover to: {cover_path}")
            return cover_path
        except (PermissionError, OSError) as e:
            logger.error(f"Failed to save cover to {folder}: {e}")
            raise TagWriteError(f"Failed to save cover: {e}", file_path=str(folder)) from e

    def embed_cover_in_folder(
        self, cover_data: bytes, folder: Path, mime_type: str | None = None
    ) -> int:
        """
        Embed cover art in all audio files in a folder.

        Args:
            cover_data: Raw image data
            folder: Folder containing audio files
            mime_type: Optional MIME type (auto-detected if None)

        Returns:
            Number of files successfully processed
        """
        if mime_type is None:
            mime_type = detect_image_mime_type(cover_data)

        success_count = 0

        try:
            items = list(folder.iterdir())
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.error(f"Cannot access folder {folder}: {e}")
            return 0

        for item in items:
            if item.is_file() and item.suffix.lower() in EMBEDDABLE_FORMATS:
                try:
                    if self.embed_cover_in_file(item, cover_data, mime_type):
                        success_count += 1
                except UnsupportedFormatError as e:
                    logger.warning(f"Unsupported format for {item.name}: {e}")
                except OSError as e:
                    logger.error(f"I/O error embedding in {item.name}: {e}")
                except ValueError as e:
                    logger.error(f"Invalid data embedding in {item.name}: {e}")

        return success_count

    def embed_cover_in_file(
        self, filepath: Path, cover_data: bytes, mime_type: str = "image/jpeg"
    ) -> bool:
        """
        Embed cover art in a single audio file.

        Args:
            filepath: Path to the audio file
            cover_data: Raw image data
            mime_type: Image MIME type

        Returns:
            True if successful, False otherwise
        """
        suffix = filepath.suffix.lower()

        # Save original modification time if preserve_timestamp is enabled
        original_mtime = None
        if self.preserve_timestamp:
            with contextlib.suppress(OSError):
                original_mtime = filepath.stat().st_mtime

        try:
            # Python 3.10+ match/case for cleaner format dispatch
            match suffix:
                case ".mp3":
                    self._embed_mp3(filepath, cover_data, mime_type)
                case ".flac":
                    self._embed_flac(filepath, cover_data, mime_type)
                case ".m4a" | ".mp4":
                    self._embed_mp4(filepath, cover_data, mime_type)
                case ".ogg" | ".opus":
                    self._embed_ogg(filepath, cover_data, mime_type)
                case _:
                    raise UnsupportedFormatError(
                        f"Unsupported format for cover embedding: {suffix}",
                        file_path=str(filepath),
                    )

            # Restore original modification time if preserve_timestamp is enabled
            if self.preserve_timestamp and original_mtime is not None:
                try:
                    os.utime(filepath, (filepath.stat().st_atime, original_mtime))
                except OSError as e:
                    logger.warning(f"Could not restore timestamp for {filepath}: {e}")

            # Invalidate cache for this file (important when preserve_timestamp is True)
            embedded_cover_cache.invalidate(filepath)

            logger.debug(f"Embedded cover in: {filepath}")
            return True
        except OSError as e:
            logger.error(f"I/O error embedding cover in {filepath}: {e}")
            return False
        except MutagenError as e:
            logger.error(f"Error embedding cover in {filepath}: {e}")
            return False

    def _embed_mp3(self, filepath: Path, cover_data: bytes, mime_type: str) -> None:
        """Embed cover in MP3 file."""
        audio = None
        try:
            try:
                audio = ID3(filepath)
            except ID3NoHeaderError:
                # Create new ID3 tag
                audio = ID3()
                audio.save(filepath)
                audio = ID3(filepath)

            # Remove existing covers
            audio.delall("APIC")

            # Add new cover
            audio.add(
                APIC(
                    encoding=3,  # UTF-8
                    mime=mime_type,
                    type=3,  # Cover front
                    desc="Cover",
                    data=cover_data,
                )
            )
            audio.save()
        finally:
            if audio is not None:
                del audio

    def _embed_flac(self, filepath: Path, cover_data: bytes, mime_type: str) -> None:
        """Embed cover in FLAC file."""
        audio = None
        try:
            audio = FLAC(filepath)

            # Remove existing covers
            audio.clear_pictures()

            # Add new cover
            picture = Picture()
            picture.type = 3  # Cover front
            picture.mime = mime_type
            picture.desc = "Cover"
            picture.data = cover_data
            audio.add_picture(picture)
            audio.save()
        finally:
            if audio is not None:
                del audio

    def _embed_mp4(self, filepath: Path, cover_data: bytes, mime_type: str) -> None:
        """Embed cover in MP4/M4A file."""
        audio = None
        try:
            audio = MP4(filepath)

            # MP4Cover only supports JPEG and PNG formats
            # Determine format based on mime_type, with validation
            if "jpeg" in mime_type or "jpg" in mime_type:
                img_format = MP4Cover.FORMAT_JPEG
            elif "png" in mime_type:
                img_format = MP4Cover.FORMAT_PNG
            else:
                # For unsupported formats (GIF, WebP, BMP), detect from data
                # and use appropriate format, defaulting to JPEG for unknowns
                detected_mime = detect_image_mime_type(cover_data)
                if "png" in detected_mime:
                    img_format = MP4Cover.FORMAT_PNG
                else:
                    # Default to JPEG for all other formats
                    # Note: This may cause issues for non-JPEG/PNG images
                    logger.warning(
                        f"MP4 only supports JPEG/PNG covers. Using JPEG format for {mime_type}"
                    )
                    img_format = MP4Cover.FORMAT_JPEG

            audio["covr"] = [MP4Cover(cover_data, imageformat=img_format)]
            audio.save()
        finally:
            if audio is not None:
                del audio

    def _embed_ogg(self, filepath: Path, cover_data: bytes, mime_type: str) -> None:
        """Embed cover in OGG/Opus file."""
        suffix = filepath.suffix.lower()
        audio = None
        try:
            audio = OggVorbis(filepath) if suffix == ".ogg" else MutagenFile(filepath)

            if audio is None:
                raise ValueError(f"Could not open file: {filepath}")

            picture = Picture()
            picture.type = 3  # Cover front
            picture.mime = mime_type
            picture.desc = "Cover"
            picture.data = cover_data

            # Set required image dimensions
            try:
                import io

                from PIL import Image

                img = Image.open(io.BytesIO(cover_data))
                picture.width, picture.height = img.size
                picture.depth = 24 if img.mode == "RGB" else 32
                picture.colors = 0
            except ImportError:
                # Fallback dimensions if PIL not available
                picture.width = 500
                picture.height = 500
                picture.depth = 24
                picture.colors = 0

            # Encode and store
            picture_data = picture.write()
            encoded_data = base64.b64encode(picture_data).decode("ascii")
            audio["metadata_block_picture"] = [encoded_data]
            audio.save()
        finally:
            if audio is not None:
                del audio

    def remove_embedded_cover(self, filepath: Path) -> bool:
        """
        Remove embedded cover from an audio file.

        Args:
            filepath: Path to the audio file

        Returns:
            True if successful, False otherwise
        """
        suffix = filepath.suffix.lower()
        audio = None

        try:
            # Python 3.10+ match/case for cleaner format dispatch
            match suffix:
                case ".mp3":
                    try:
                        audio = ID3(filepath)
                    except ID3NoHeaderError:
                        # No ID3 header means no embedded cover to remove
                        logger.debug(f"No ID3 header in {filepath}, nothing to remove")
                        return True
                    audio.delall("APIC")
                    audio.save()
                case ".flac":
                    audio = FLAC(filepath)
                    audio.clear_pictures()
                    audio.save()
                case ".m4a" | ".mp4":
                    audio = MP4(filepath)
                    if "covr" in audio:
                        del audio["covr"]
                        audio.save()
                case ".ogg":
                    audio = OggVorbis(filepath)
                    if audio and "metadata_block_picture" in audio:
                        del audio["metadata_block_picture"]
                        audio.save()
                case ".opus":
                    audio = MutagenFile(filepath)
                    if audio and "metadata_block_picture" in audio:
                        del audio["metadata_block_picture"]
                        audio.save()
                case _:
                    return False

            logger.debug(f"Removed cover from: {filepath}")
            return True
        except OSError as e:
            logger.error(f"I/O error removing cover from {filepath}: {e}")
            return False
        except MutagenError as e:
            logger.error(f"Error removing cover from {filepath}: {e}")
            return False
        finally:
            if audio is not None:
                del audio
