"""
Shared metadata extraction utilities.

This module provides functions for extracting various identifiers from audio files:
- MusicBrainz IDs (Album, Release Group, Artist)
- ISRC (International Standard Recording Code)
- Barcode/UPC
- Discogs Release ID
"""

import logging
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError

logger = logging.getLogger(__name__)


def _get_tag_value(tags: dict, key: str) -> str | None:
    """
    Extract a string value from tags dict, handling various formats.

    Args:
        tags: Tag dictionary (EasyID3 style or raw)
        key: Tag key to extract

    Returns:
        String value or None
    """
    if key not in tags:
        return None

    value = tags[key]

    # Handle TXXX frames with .text attribute
    if hasattr(value, "text") and value.text:
        text = value.text
        return text[0] if isinstance(text, list) else str(text)

    # Handle list values
    if isinstance(value, list) and value:
        val = value[0]
        # MP4 freeform tags are bytes
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="ignore")
        return str(val)

    # Handle direct string values
    if isinstance(value, str):
        return value

    return None


def _extract_raw_tag(filepath: Path, tag_mappings: dict[str, str]) -> dict[str, str | None]:
    """
    Extract tags from raw audio file using multiple tag name mappings.

    Args:
        filepath: Path to audio file
        tag_mappings: Dict mapping tag keys to result keys

    Returns:
        Dict with extracted values
    """
    result = dict.fromkeys(set(tag_mappings.values()))

    audio_raw = None
    try:
        audio_raw = MutagenFile(filepath)
        if audio_raw and hasattr(audio_raw, "tags") and audio_raw.tags:
            raw_tags = audio_raw.tags
            for tag_key, result_key in tag_mappings.items():
                if result[result_key] is None:
                    value = _get_tag_value(raw_tags, tag_key)
                    if value:
                        result[result_key] = value
    except OSError as e:
        logger.debug(f"I/O error reading tags from {filepath}: {e}")
    except MutagenError as e:
        logger.debug(f"Error reading tags from {filepath}: {e}")
    finally:
        if audio_raw is not None:
            del audio_raw

    return result


def extract_musicbrainz_ids(filepath: Path, easy_tags: dict | None = None) -> dict[str, str | None]:
    """
    Extract MusicBrainz IDs from an audio file.

    This function handles various tag formats:
    - EasyID3-style tags (musicbrainz_albumid, etc.)
    - MP3 TXXX frames (both standard and uppercase variants)
    - MP4/M4A iTunes-style freeform tags

    Args:
        filepath: Path to the audio file
        easy_tags: Optional pre-loaded EasyID3-style tags dict

    Returns:
        Dictionary with keys: musicbrainz_albumid, musicbrainz_releasegroupid, musicbrainz_artistid
    """
    result = {
        "musicbrainz_albumid": None,
        "musicbrainz_releasegroupid": None,
        "musicbrainz_artistid": None,
    }

    # First try EasyID3-style tags if provided
    if easy_tags:
        for key in result:
            if easy_tags.get(key):
                value = easy_tags[key]
                result[key] = value[0] if isinstance(value, list) else str(value)

    # If we found all IDs, return early
    if all(result.values()):
        return result

    # Try raw tags for format-specific tag names
    audio_raw = None
    try:
        audio_raw = MutagenFile(filepath)
        if audio_raw and hasattr(audio_raw, "tags") and audio_raw.tags:
            raw_tags = audio_raw.tags

            # MP3 TXXX frames - standard naming
            txxx_mappings = {
                "TXXX:MusicBrainz Album Id": "musicbrainz_albumid",
                "TXXX:MusicBrainz Release Group Id": "musicbrainz_releasegroupid",
                "TXXX:MusicBrainz Artist Id": "musicbrainz_artistid",
            }

            for tag_key, metadata_key in txxx_mappings.items():
                if tag_key in raw_tags and not result[metadata_key]:
                    value = raw_tags[tag_key]
                    if hasattr(value, "text") and value.text:
                        result[metadata_key] = (
                            value.text[0] if isinstance(value.text, list) else str(value.text)
                        )
                    elif isinstance(value, list) and value:
                        result[metadata_key] = str(value[0])

            # MP3 TXXX frames - uppercase variant (some taggers use this)
            txxx_upper_mappings = {
                "TXXX:MUSICBRAINZ_ALBUMID": "musicbrainz_albumid",
                "TXXX:MUSICBRAINZ_RELEASEGROUPID": "musicbrainz_releasegroupid",
                "TXXX:MUSICBRAINZ_ARTISTID": "musicbrainz_artistid",
            }

            for tag_key, metadata_key in txxx_upper_mappings.items():
                if tag_key in raw_tags and not result[metadata_key]:
                    value = raw_tags[tag_key]
                    if hasattr(value, "text") and value.text:
                        result[metadata_key] = (
                            value.text[0] if isinstance(value.text, list) else str(value.text)
                        )
                    elif isinstance(value, list) and value:
                        result[metadata_key] = str(value[0])

            # MP4/M4A tags (iTunes-style freeform tags)
            mp4_mappings = {
                "----:com.apple.iTunes:MusicBrainz Album Id": "musicbrainz_albumid",
                "----:com.apple.iTunes:MusicBrainz Release Group Id": "musicbrainz_releasegroupid",
                "----:com.apple.iTunes:MusicBrainz Artist Id": "musicbrainz_artistid",
            }

            for tag_key, metadata_key in mp4_mappings.items():
                if tag_key in raw_tags and not result[metadata_key]:
                    value = raw_tags[tag_key]
                    if isinstance(value, list) and value:
                        # MP4 freeform tags are bytes
                        val = value[0]
                        if isinstance(val, bytes):
                            result[metadata_key] = val.decode("utf-8", errors="ignore")
                        else:
                            result[metadata_key] = str(val)

    except OSError as e:
        logger.debug(f"I/O error extracting MusicBrainz IDs from {filepath}: {e}")
    except MutagenError as e:
        logger.debug(f"Error extracting MusicBrainz IDs from {filepath}: {e}")
    finally:
        if audio_raw is not None:
            del audio_raw

    return result


def extract_isrc(filepath: Path, easy_tags: dict | None = None) -> str | None:
    """
    Extract ISRC (International Standard Recording Code) from an audio file.

    ISRC is a 12-character code that identifies a specific recording.
    Format: CC-XXX-YY-NNNNN (country-registrant-year-designation)

    Args:
        filepath: Path to the audio file
        easy_tags: Optional pre-loaded EasyID3-style tags dict

    Returns:
        ISRC string if found, None otherwise
    """
    # Try EasyID3 tags first
    if easy_tags:
        for key in ["isrc", "ISRC"]:
            value = easy_tags.get(key)
            if value:
                return value[0] if isinstance(value, list) else str(value)

    # Tag mappings for raw extraction
    tag_mappings = {
        # MP3 ID3v2
        "TSRC": "isrc",  # ID3v2.4 standard ISRC frame
        "TXXX:ISRC": "isrc",
        "TXXX:isrc": "isrc",
        # Vorbis/FLAC
        "isrc": "isrc",
        "ISRC": "isrc",
        # MP4/M4A
        "----:com.apple.iTunes:ISRC": "isrc",
    }

    result = _extract_raw_tag(filepath, tag_mappings)
    isrc = result.get("isrc")

    if isrc:
        # Normalize: remove hyphens and validate length
        isrc_clean = isrc.replace("-", "").replace(" ", "").upper()
        if len(isrc_clean) == 12:
            logger.debug(f"Found ISRC for {filepath.name}: {isrc_clean}")
            return isrc_clean

    return None


def extract_barcode(filepath: Path, easy_tags: dict | None = None) -> str | None:
    """
    Extract barcode/UPC/EAN from an audio file.

    Barcodes are typically 12 (UPC-A) or 13 (EAN-13) digit codes.

    Args:
        filepath: Path to the audio file
        easy_tags: Optional pre-loaded EasyID3-style tags dict

    Returns:
        Barcode string if found, None otherwise
    """
    # Try EasyID3 tags first
    if easy_tags:
        for key in ["barcode", "BARCODE", "upc", "UPC", "ean", "EAN"]:
            value = easy_tags.get(key)
            if value:
                return value[0] if isinstance(value, list) else str(value)

    # Tag mappings for raw extraction
    tag_mappings = {
        # MP3 TXXX frames
        "TXXX:BARCODE": "barcode",
        "TXXX:barcode": "barcode",
        "TXXX:UPC": "barcode",
        "TXXX:upc": "barcode",
        "TXXX:EAN": "barcode",
        # Vorbis/FLAC
        "barcode": "barcode",
        "BARCODE": "barcode",
        "upc": "barcode",
        "UPC": "barcode",
        "ean": "barcode",
        "EAN": "barcode",
        # MP4/M4A
        "----:com.apple.iTunes:BARCODE": "barcode",
        "----:com.apple.iTunes:UPC": "barcode",
    }

    result = _extract_raw_tag(filepath, tag_mappings)
    barcode = result.get("barcode")

    if barcode:
        # Clean and validate
        barcode_clean = barcode.replace("-", "").replace(" ", "")
        # UPC-A is 12 digits, EAN-13 is 13 digits
        if barcode_clean.isdigit() and len(barcode_clean) in (12, 13):
            logger.debug(f"Found barcode for {filepath.name}: {barcode_clean}")
            return barcode_clean

    return None


def extract_discogs_id(filepath: Path, easy_tags: dict | None = None) -> str | None:
    """
    Extract Discogs release ID from an audio file.

    Args:
        filepath: Path to the audio file
        easy_tags: Optional pre-loaded EasyID3-style tags dict

    Returns:
        Discogs release ID string if found, None otherwise
    """
    # Try EasyID3 tags first
    if easy_tags:
        for key in ["discogs_release_id", "DISCOGS_RELEASE_ID", "discogsid", "DISCOGSID"]:
            value = easy_tags.get(key)
            if value:
                return value[0] if isinstance(value, list) else str(value)

    # Tag mappings for raw extraction
    tag_mappings = {
        # MP3 TXXX frames
        "TXXX:DISCOGS_RELEASE_ID": "discogs_id",
        "TXXX:discogs_release_id": "discogs_id",
        "TXXX:DISCOGSID": "discogs_id",
        # Vorbis/FLAC
        "discogs_release_id": "discogs_id",
        "DISCOGS_RELEASE_ID": "discogs_id",
        "discogsid": "discogs_id",
        "DISCOGSID": "discogs_id",
        # MP4/M4A
        "----:com.apple.iTunes:DISCOGS_RELEASE_ID": "discogs_id",
        "----:com.apple.iTunes:DISCOGSID": "discogs_id",
    }

    result = _extract_raw_tag(filepath, tag_mappings)
    discogs_id = result.get("discogs_id")

    if discogs_id:
        # Clean and validate (should be numeric)
        discogs_clean = discogs_id.strip()
        if discogs_clean.isdigit():
            logger.debug(f"Found Discogs ID for {filepath.name}: {discogs_clean}")
            return discogs_clean

    return None


def extract_all_identifiers(filepath: Path, easy_tags: dict | None = None) -> dict[str, str | None]:
    """
    Extract all available identifiers from an audio file.

    Convenience function that calls all extraction functions.

    Args:
        filepath: Path to the audio file
        easy_tags: Optional pre-loaded EasyID3-style tags dict

    Returns:
        Dict with all identifiers (keys: musicbrainz_albumid, musicbrainz_releasegroupid,
        musicbrainz_artistid, isrc, barcode, discogs_release_id)
    """
    result = extract_musicbrainz_ids(filepath, easy_tags)
    result["isrc"] = extract_isrc(filepath, easy_tags)
    result["barcode"] = extract_barcode(filepath, easy_tags)
    result["discogs_release_id"] = extract_discogs_id(filepath, easy_tags)
    return result
