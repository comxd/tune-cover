"""
Core functionality for music library scanning and cover fetching.
"""

from .embedder import CoverEmbedder
from .exceptions import (
    CacheError,
    ConfigError,
    FileProcessingError,
    FingerprintError,
    MusicTaggerError,
    NetworkError,
    ProviderError,
    RateLimitError,
    ScanError,
    TagReadError,
    TagWriteError,
    UnsupportedFormatError,
)
from .models import AlbumInfo, CoverInfo, ProcessingResult, SearchResult, TrackInfo
from .scan_cache import ScanCache
from .scanner import MusicScanner

__all__ = [
    "AlbumInfo",
    "CacheError",
    "ConfigError",
    "CoverEmbedder",
    "CoverInfo",
    "FileProcessingError",
    "FingerprintError",
    "MusicScanner",
    "MusicTaggerError",
    "NetworkError",
    "ProcessingResult",
    "ProviderError",
    "RateLimitError",
    "ScanCache",
    "ScanError",
    "SearchResult",
    "TagReadError",
    "TagWriteError",
    "TrackInfo",
    "UnsupportedFormatError",
]
