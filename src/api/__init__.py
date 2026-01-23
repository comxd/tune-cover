"""
API clients for cover art providers.
"""

from .base import CoverProvider
from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from .discogs import DiscogsProvider
from .lastfm import LastFmProvider
from .metrics import MetricsRegistry, ProviderMetrics
from .musicbrainz import MusicBrainzProvider

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    "CoverProvider",
    "DiscogsProvider",
    "LastFmProvider",
    "MetricsRegistry",
    "MusicBrainzProvider",
    "ProviderMetrics",
]
