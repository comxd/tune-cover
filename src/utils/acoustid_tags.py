"""
AcoustID tag reading and writing for audio files.

Standard tag names (following MusicBrainz Picard convention):
- MP3 (ID3v2): TXXX:Acoustid Id
- FLAC/OGG/Opus: ACOUSTID_ID
- MP4/M4A: ----:com.apple.iTunes:Acoustid Id
"""

import logging
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX, ID3NoHeaderError
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)

# Supported audio extensions for AcoustID tag operations
SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".mp4"}


def extract_acoustid(filepath: Path) -> str | None:
    """
    Extract the AcoustID from audio file tags.

    Args:
        filepath: Path to the audio file

    Returns:
        AcoustID string if found, None otherwise
    """
    if not filepath.exists():
        return None

    ext = filepath.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return None

    try:
        audio = MutagenFile(filepath)
        if audio is None:
            return None

        # MP3 (ID3v2) - TXXX:Acoustid Id
        if ext == ".mp3":
            if audio.tags:
                for key in audio.tags:
                    if key.startswith("TXXX:") and "acoustid" in key.lower():
                        frame = audio.tags[key]
                        if hasattr(frame, "text") and frame.text:
                            return str(frame.text[0])
            return None

        # FLAC - ACOUSTID_ID
        if ext == ".flac":
            if isinstance(audio, FLAC):
                acoustid = audio.get("ACOUSTID_ID") or audio.get("acoustid_id")
                if acoustid:
                    return str(acoustid[0])
            return None

        # OGG Vorbis/Opus - ACOUSTID_ID
        if ext in (".ogg", ".opus"):
            acoustid = audio.get("ACOUSTID_ID") or audio.get("acoustid_id")
            if acoustid:
                return str(acoustid[0])
            return None

        # MP4/M4A - ----:com.apple.iTunes:Acoustid Id
        if ext in (".m4a", ".mp4"):
            if isinstance(audio, MP4) and audio.tags:
                # Try standard Picard naming
                acoustid = audio.tags.get("----:com.apple.iTunes:Acoustid Id")
                if acoustid:
                    # MP4 freeform tags store data as bytes
                    return (
                        acoustid[0].decode("utf-8")
                        if isinstance(acoustid[0], bytes)
                        else str(acoustid[0])
                    )
                # Try lowercase variant
                acoustid = audio.tags.get("----:com.apple.iTunes:acoustid id")
                if acoustid:
                    return (
                        acoustid[0].decode("utf-8")
                        if isinstance(acoustid[0], bytes)
                        else str(acoustid[0])
                    )
            return None

    except (OSError, MutagenError) as e:
        logger.debug(f"Error extracting AcoustID from {filepath}: {e}")
        return None

    return None


def save_acoustid_to_file(filepath: Path, acoustid: str) -> bool:
    """
    Save an AcoustID to a single audio file's tags.

    Args:
        filepath: Path to the audio file
        acoustid: AcoustID string to save

    Returns:
        True if successful, False otherwise
    """
    if not filepath.exists():
        logger.warning(f"File does not exist: {filepath}")
        return False

    ext = filepath.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        logger.warning(f"Unsupported format for AcoustID: {ext}")
        return False

    try:
        # MP3 (ID3v2) - TXXX:Acoustid Id
        if ext == ".mp3":
            try:
                audio = ID3(filepath)
            except ID3NoHeaderError:
                # Create ID3 tags if they don't exist
                audio = ID3()
                audio.save(filepath)
                audio = ID3(filepath)

            # Remove existing AcoustID tags
            to_remove = [k for k in audio if k.startswith("TXXX:") and "acoustid" in k.lower()]
            for k in to_remove:
                del audio[k]

            # Add new AcoustID tag
            audio.add(TXXX(encoding=3, desc="Acoustid Id", text=[acoustid]))
            audio.save(filepath)
            logger.debug(f"Saved AcoustID to MP3: {filepath}")
            return True

        # FLAC - ACOUSTID_ID
        if ext == ".flac":
            audio = FLAC(filepath)
            audio["ACOUSTID_ID"] = acoustid
            audio.save()
            logger.debug(f"Saved AcoustID to FLAC: {filepath}")
            return True

        # OGG Vorbis - ACOUSTID_ID
        if ext == ".ogg":
            audio = OggVorbis(filepath)
            audio["ACOUSTID_ID"] = acoustid
            audio.save()
            logger.debug(f"Saved AcoustID to OGG: {filepath}")
            return True

        # Opus - ACOUSTID_ID
        if ext == ".opus":
            audio = OggOpus(filepath)
            audio["ACOUSTID_ID"] = acoustid
            audio.save()
            logger.debug(f"Saved AcoustID to Opus: {filepath}")
            return True

        # MP4/M4A - ----:com.apple.iTunes:Acoustid Id
        if ext in (".m4a", ".mp4"):
            audio = MP4(filepath)
            if audio.tags is None:
                audio.add_tags()
            # MP4 freeform tags require bytes
            from mutagen.mp4 import MP4FreeForm

            audio.tags["----:com.apple.iTunes:Acoustid Id"] = [
                MP4FreeForm(acoustid.encode("utf-8"))
            ]
            audio.save()
            logger.debug(f"Saved AcoustID to M4A/MP4: {filepath}")
            return True

    except PermissionError as e:
        logger.warning(f"Permission denied saving AcoustID to {filepath}: {e}")
        return False
    except (OSError, MutagenError) as e:
        logger.error(f"Error saving AcoustID to {filepath}: {e}")
        return False

    return False


def save_acoustid_to_folder(folder: Path, acoustid: str) -> int:
    """
    Save an AcoustID to all audio files in a folder.

    Args:
        folder: Path to the folder containing audio files
        acoustid: AcoustID string to save

    Returns:
        Number of files successfully updated
    """
    if not folder.is_dir():
        logger.warning(f"Not a directory: {folder}")
        return 0

    success_count = 0
    for item in folder.iterdir():
        if (
            item.is_file()
            and item.suffix.lower() in SUPPORTED_EXTENSIONS
            and save_acoustid_to_file(item, acoustid)
        ):
            success_count += 1

    logger.info(f"Saved AcoustID to {success_count} files in {folder}")
    return success_count


def update_metadata_in_file(
    filepath: Path,
    artist: str | None = None,
    album: str | None = None,
) -> bool:
    """
    Update artist and/or album metadata in an audio file.

    Args:
        filepath: Path to the audio file
        artist: New artist name (None to skip)
        album: New album name (None to skip)

    Returns:
        True if successful, False otherwise
    """
    if not filepath.exists():
        logger.warning(f"File does not exist: {filepath}")
        return False

    if artist is None and album is None:
        return True  # Nothing to update

    ext = filepath.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        logger.warning(f"Unsupported format for metadata update: {ext}")
        return False

    try:
        audio = MutagenFile(filepath)
        if audio is None:
            return False

        # MP3 (ID3v2)
        if ext == ".mp3":
            from mutagen.id3 import TALB, TPE1

            if audio.tags is None:
                from mutagen.id3 import ID3

                audio = ID3(filepath)
                audio.save(filepath)
                audio = ID3(filepath)

            if artist:
                audio.delall("TPE1")
                audio.add(TPE1(encoding=3, text=[artist]))
            if album:
                audio.delall("TALB")
                audio.add(TALB(encoding=3, text=[album]))
            audio.save(filepath)
            logger.debug(f"Updated metadata in MP3: {filepath}")
            return True

        # FLAC
        if ext == ".flac":
            if artist:
                audio["ARTIST"] = artist
            if album:
                audio["ALBUM"] = album
            audio.save()
            logger.debug(f"Updated metadata in FLAC: {filepath}")
            return True

        # OGG Vorbis/Opus
        if ext in (".ogg", ".opus"):
            if artist:
                audio["ARTIST"] = artist
            if album:
                audio["ALBUM"] = album
            audio.save()
            logger.debug(f"Updated metadata in OGG/Opus: {filepath}")
            return True

        # MP4/M4A
        if ext in (".m4a", ".mp4"):
            if audio.tags is None:
                audio.add_tags()
            if artist:
                audio.tags["\xa9ART"] = [artist]
            if album:
                audio.tags["\xa9alb"] = [album]
            audio.save()
            logger.debug(f"Updated metadata in M4A/MP4: {filepath}")
            return True

    except PermissionError as e:
        logger.warning(f"Permission denied updating metadata in {filepath}: {e}")
        return False
    except (OSError, MutagenError) as e:
        logger.error(f"Error updating metadata in {filepath}: {e}")
        return False

    return False


def update_metadata_in_folder(
    folder: Path,
    artist: str | None = None,
    album: str | None = None,
) -> int:
    """
    Update artist and/or album metadata in all audio files in a folder.

    Args:
        folder: Path to the folder containing audio files
        artist: New artist name (None to skip)
        album: New album name (None to skip)

    Returns:
        Number of files successfully updated
    """
    if not folder.is_dir():
        logger.warning(f"Not a directory: {folder}")
        return 0

    if artist is None and album is None:
        return 0  # Nothing to update

    success_count = 0
    for item in folder.iterdir():
        if (
            item.is_file()
            and item.suffix.lower() in SUPPORTED_EXTENSIONS
            and update_metadata_in_file(item, artist, album)
        ):
            success_count += 1

    logger.info(f"Updated metadata in {success_count} files in {folder}")
    return success_count
