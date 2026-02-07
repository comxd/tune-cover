"""
Provider metrics tracking for monitoring and debugging.

This module provides thread-safe metrics collection for API providers,
tracking request counts, success rates, response times, and rate limit events.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProviderMetrics:
    """
    Tracks performance metrics for a single provider.

    All metrics are collected in a thread-safe manner using a lock.
    Metrics can be reset to start fresh collection periods.
    """

    provider_name: str
    requests_total: int = 0
    requests_success: int = 0
    requests_failed: int = 0
    rate_limits_hit: int = 0
    total_response_time_ms: float = 0.0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def avg_response_time_ms(self) -> float:
        """Calculate average response time in milliseconds."""
        with self._lock:
            if self.requests_total == 0:
                return 0.0
            return self.total_response_time_ms / self.requests_total

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a ratio (0.0 to 1.0)."""
        with self._lock:
            if self.requests_total == 0:
                return 0.0
            return self.requests_success / self.requests_total

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as a ratio (0.0 to 1.0)."""
        with self._lock:
            if self.requests_total == 0:
                return 0.0
            return self.requests_failed / self.requests_total

    def record_request(self, success: bool, duration_ms: float, rate_limited: bool = False) -> None:
        """
        Record a completed request.

        Args:
            success: Whether the request succeeded
            duration_ms: Request duration in milliseconds
            rate_limited: Whether this request hit a rate limit
        """
        with self._lock:
            self.requests_total += 1
            self.total_response_time_ms += duration_ms
            if success:
                self.requests_success += 1
            else:
                self.requests_failed += 1
            if rate_limited:
                self.rate_limits_hit += 1

    def reset(self) -> None:
        """Reset all metrics to zero."""
        with self._lock:
            self.requests_total = 0
            self.requests_success = 0
            self.requests_failed = 0
            self.rate_limits_hit = 0
            self.total_response_time_ms = 0.0

    def to_dict(self) -> dict[str, Any]:
        """
        Export metrics as a dictionary.

        Returns:
            Dictionary with all metric values
        """
        with self._lock:
            return {
                "provider_name": self.provider_name,
                "requests_total": self.requests_total,
                "requests_success": self.requests_success,
                "requests_failed": self.requests_failed,
                "rate_limits_hit": self.rate_limits_hit,
                "total_response_time_ms": self.total_response_time_ms,
                "avg_response_time_ms": self.avg_response_time_ms,
                "success_rate": self.success_rate,
            }


class MetricsRegistry:
    """
    Global registry for provider metrics.

    Implemented as a singleton to provide consistent metrics access
    across the application. Each provider gets its own ProviderMetrics
    instance, created on first access.

    Usage:
        metrics = MetricsRegistry().get_metrics("MusicBrainz")
        print(f"Success rate: {metrics.success_rate:.1%}")
    """

    _instance: "MetricsRegistry | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "MetricsRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._metrics: dict[str, ProviderMetrics] = {}
                cls._instance._metrics_lock = threading.Lock()
            return cls._instance

    def get_metrics(self, provider_name: str) -> ProviderMetrics:
        """
        Get or create metrics for a provider.

        Args:
            provider_name: Name of the provider (e.g., "MusicBrainz")

        Returns:
            ProviderMetrics instance for the provider
        """
        with self._metrics_lock:
            if provider_name not in self._metrics:
                self._metrics[provider_name] = ProviderMetrics(provider_name)
            return self._metrics[provider_name]

    def get_all_metrics(self) -> dict[str, ProviderMetrics]:
        """
        Get metrics for all registered providers.

        Returns:
            Dictionary mapping provider names to their metrics
        """
        with self._metrics_lock:
            return dict(self._metrics)

    def reset_all(self) -> None:
        """Reset metrics for all providers."""
        with self._metrics_lock:
            for metrics in self._metrics.values():
                metrics.reset()

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """
        Export all metrics as a dictionary.

        Returns:
            Dictionary mapping provider names to their metric dictionaries
        """
        with self._metrics_lock:
            return {name: m.to_dict() for name, m in self._metrics.items()}
