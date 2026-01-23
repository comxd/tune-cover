"""
Utility functions and helpers.
"""

from .acoustid_tags import extract_acoustid, save_acoustid_to_file, save_acoustid_to_folder
from .cache import EmbeddedCoverCache, ImageCache, embedded_cover_cache
from .config import Config
from .file_manager import open_in_file_manager, open_terminal_at, truncate_path
from .logging import LogCapture, get_logger, setup_logging
from .metadata import extract_musicbrainz_ids
from .user_agent import build_user_agent, get_user_agent, get_version

__all__ = [
    "Config",
    "EmbeddedCoverCache",
    "ImageCache",
    "LogCapture",
    "build_user_agent",
    "embedded_cover_cache",
    "extract_acoustid",
    "extract_musicbrainz_ids",
    "get_logger",
    "get_user_agent",
    "get_version",
    "open_in_file_manager",
    "open_terminal_at",
    "save_acoustid_to_file",
    "save_acoustid_to_folder",
    "setup_logging",
    "truncate_path",
]
