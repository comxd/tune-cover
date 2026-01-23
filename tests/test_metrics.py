"""
Tests for the provider metrics module.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from src.api.metrics import MetricsRegistry, ProviderMetrics


class TestProviderMetrics:
    """Tests for ProviderMetrics dataclass."""

    def test_init(self):
        """Test metrics initialization with default values."""
        metrics = ProviderMetrics("TestProvider")
        assert metrics.provider_name == "TestProvider"
        assert metrics.requests_total == 0
        assert metrics.requests_success == 0
        assert metrics.requests_failed == 0
        assert metrics.rate_limits_hit == 0
        assert metrics.total_response_time_ms == 0.0

    def test_record_successful_request(self):
        """Test recording a successful request."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=True, duration_ms=100.0)

        assert metrics.requests_total == 1
        assert metrics.requests_success == 1
        assert metrics.requests_failed == 0
        assert metrics.total_response_time_ms == 100.0

    def test_record_failed_request(self):
        """Test recording a failed request."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=False, duration_ms=50.0)

        assert metrics.requests_total == 1
        assert metrics.requests_success == 0
        assert metrics.requests_failed == 1
        assert metrics.total_response_time_ms == 50.0

    def test_record_rate_limited_request(self):
        """Test recording a rate-limited request."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=False, duration_ms=25.0, rate_limited=True)

        assert metrics.requests_total == 1
        assert metrics.requests_failed == 1
        assert metrics.rate_limits_hit == 1

    def test_avg_response_time_ms(self):
        """Test average response time calculation."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=True, duration_ms=100.0)
        metrics.record_request(success=True, duration_ms=200.0)
        metrics.record_request(success=False, duration_ms=300.0)

        assert metrics.avg_response_time_ms == 200.0  # (100 + 200 + 300) / 3

    def test_avg_response_time_ms_empty(self):
        """Test average response time with no requests."""
        metrics = ProviderMetrics("TestProvider")
        assert metrics.avg_response_time_ms == 0.0

    def test_success_rate(self):
        """Test success rate calculation."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=True, duration_ms=100.0)
        metrics.record_request(success=True, duration_ms=100.0)
        metrics.record_request(success=False, duration_ms=100.0)

        assert metrics.success_rate == pytest.approx(2 / 3)

    def test_success_rate_empty(self):
        """Test success rate with no requests."""
        metrics = ProviderMetrics("TestProvider")
        assert metrics.success_rate == 0.0

    def test_failure_rate(self):
        """Test failure rate calculation."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=True, duration_ms=100.0)
        metrics.record_request(success=False, duration_ms=100.0)
        metrics.record_request(success=False, duration_ms=100.0)

        assert metrics.failure_rate == pytest.approx(2 / 3)

    def test_failure_rate_empty(self):
        """Test failure rate with no requests."""
        metrics = ProviderMetrics("TestProvider")
        assert metrics.failure_rate == 0.0

    def test_reset(self):
        """Test resetting metrics."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=True, duration_ms=100.0)
        metrics.record_request(success=False, duration_ms=50.0, rate_limited=True)

        metrics.reset()

        assert metrics.requests_total == 0
        assert metrics.requests_success == 0
        assert metrics.requests_failed == 0
        assert metrics.rate_limits_hit == 0
        assert metrics.total_response_time_ms == 0.0

    def test_to_dict(self):
        """Test exporting metrics as dictionary."""
        metrics = ProviderMetrics("TestProvider")
        metrics.record_request(success=True, duration_ms=100.0)
        metrics.record_request(success=False, duration_ms=50.0)

        result = metrics.to_dict()

        assert result["provider_name"] == "TestProvider"
        assert result["requests_total"] == 2
        assert result["requests_success"] == 1
        assert result["requests_failed"] == 1
        assert result["avg_response_time_ms"] == 75.0
        assert result["success_rate"] == 0.5

    def test_thread_safety(self):
        """Test metrics are thread-safe under concurrent access."""
        metrics = ProviderMetrics("TestProvider")
        errors = []

        def record_requests():
            try:
                for _ in range(100):
                    metrics.record_request(success=True, duration_ms=1.0)
                    metrics.record_request(success=False, duration_ms=1.0)
                return True
            except Exception as e:
                return e

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_requests) for _ in range(10)]
            for future in as_completed(futures):
                result = future.result()
                if isinstance(result, Exception):
                    errors.append(result)

        assert len(errors) == 0
        # Each thread does 100 success + 100 failure = 200 total
        # With 10 threads, total should be 2000
        assert metrics.requests_total == 2000
        assert metrics.requests_success == 1000
        assert metrics.requests_failed == 1000


class TestMetricsRegistry:
    """Tests for MetricsRegistry singleton."""

    def test_singleton(self):
        """Test registry is a singleton."""
        registry1 = MetricsRegistry()
        registry2 = MetricsRegistry()
        assert registry1 is registry2

    def test_get_metrics_creates_new(self):
        """Test get_metrics creates new metrics for unknown provider."""
        registry = MetricsRegistry()
        # Clean up any existing metrics for this test
        registry._metrics.pop("NewTestProvider", None)

        metrics = registry.get_metrics("NewTestProvider")

        assert metrics.provider_name == "NewTestProvider"
        assert metrics.requests_total == 0

    def test_get_metrics_returns_existing(self):
        """Test get_metrics returns existing metrics."""
        registry = MetricsRegistry()
        metrics1 = registry.get_metrics("ExistingProvider")
        metrics1.record_request(success=True, duration_ms=100.0)

        metrics2 = registry.get_metrics("ExistingProvider")

        assert metrics1 is metrics2
        assert metrics2.requests_total == 1

    def test_get_all_metrics(self):
        """Test getting all registered metrics."""
        registry = MetricsRegistry()
        registry.get_metrics("Provider1")
        registry.get_metrics("Provider2")

        all_metrics = registry.get_all_metrics()

        assert "Provider1" in all_metrics
        assert "Provider2" in all_metrics

    def test_reset_all(self):
        """Test resetting all metrics."""
        registry = MetricsRegistry()
        metrics1 = registry.get_metrics("ResetTestProvider1")
        metrics2 = registry.get_metrics("ResetTestProvider2")
        metrics1.record_request(success=True, duration_ms=100.0)
        metrics2.record_request(success=False, duration_ms=50.0)

        registry.reset_all()

        assert metrics1.requests_total == 0
        assert metrics2.requests_total == 0

    def test_to_dict(self):
        """Test exporting all metrics as dictionary."""
        registry = MetricsRegistry()
        metrics = registry.get_metrics("DictTestProvider")
        metrics.record_request(success=True, duration_ms=100.0)

        result = registry.to_dict()

        assert "DictTestProvider" in result
        assert result["DictTestProvider"]["requests_total"] == 1

    def test_thread_safety(self):
        """Test registry is thread-safe under concurrent access."""
        registry = MetricsRegistry()
        errors = []

        def access_metrics(i):
            try:
                metrics = registry.get_metrics(f"ConcurrentProvider{i % 5}")
                metrics.record_request(success=True, duration_ms=1.0)
                return True
            except Exception as e:
                return e

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(access_metrics, i) for i in range(100)]
            for future in as_completed(futures):
                result = future.result()
                if isinstance(result, Exception):
                    errors.append(result)

        assert len(errors) == 0
