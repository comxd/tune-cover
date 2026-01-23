"""
Tests for the circuit breaker module.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

import pytest

from src.api.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_is_closed(self):
        """Test circuit breaker starts in closed state."""
        breaker = CircuitBreaker()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    def test_allow_request_when_closed(self):
        """Test requests are allowed when circuit is closed."""
        breaker = CircuitBreaker()
        assert breaker.allow_request() is True

    def test_record_success_resets_failure_count(self):
        """Test recording success resets failure count."""
        breaker = CircuitBreaker(failure_threshold=5)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.failure_count == 2

        breaker.record_success()

        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        """Test circuit opens after reaching failure threshold."""
        breaker = CircuitBreaker(failure_threshold=3)

        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    def test_rejects_requests_when_open(self):
        """Test requests are rejected when circuit is open."""
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.allow_request() is False

    def test_transitions_to_half_open_after_timeout(self):
        """Test circuit transitions to half-open after reset timeout."""
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.1)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.15)

        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_allows_limited_requests(self):
        """Test half-open state allows limited test requests."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            reset_timeout_seconds=0.01,
            half_open_max_requests=2,
        )
        breaker.record_failure()
        time.sleep(0.02)

        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.allow_request() is True
        assert breaker.allow_request() is True
        assert breaker.allow_request() is False  # Limit reached

    def test_half_open_closes_on_success(self):
        """Test circuit closes when success recorded in half-open state."""
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.01)
        breaker.record_failure()
        time.sleep(0.02)

        assert breaker.state == CircuitState.HALF_OPEN
        breaker.record_success()

        assert breaker.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        """Test circuit reopens when failure recorded in half-open state."""
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.01)
        breaker.record_failure()
        time.sleep(0.02)

        assert breaker.state == CircuitState.HALF_OPEN
        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN

    def test_reset_forces_closed_state(self):
        """Test reset forces circuit to closed state."""
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_thread_safety(self):
        """Test circuit breaker is thread-safe under concurrent access."""
        breaker = CircuitBreaker(failure_threshold=100)
        errors = []

        def record_failures():
            try:
                for _ in range(50):
                    breaker.record_failure()
                return True
            except Exception as e:
                return e

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_failures) for _ in range(10)]
            for future in as_completed(futures):
                result = future.result()
                if isinstance(result, Exception):
                    errors.append(result)

        assert len(errors) == 0
        # 10 threads * 50 failures = 500 total failures
        assert breaker.failure_count >= 100  # At least threshold reached
        assert breaker.state == CircuitState.OPEN

    def test_default_configuration(self):
        """Test default configuration values."""
        breaker = CircuitBreaker()
        assert breaker.failure_threshold == 5
        assert breaker.reset_timeout_seconds == 60.0
        assert breaker.half_open_max_requests == 1

    def test_custom_configuration(self):
        """Test custom configuration values."""
        breaker = CircuitBreaker(
            failure_threshold=10,
            reset_timeout_seconds=120.0,
            half_open_max_requests=3,
        )
        assert breaker.failure_threshold == 10
        assert breaker.reset_timeout_seconds == 120.0
        assert breaker.half_open_max_requests == 3


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry singleton."""

    def test_singleton(self):
        """Test registry is a singleton."""
        registry1 = CircuitBreakerRegistry()
        registry2 = CircuitBreakerRegistry()
        assert registry1 is registry2

    def test_get_breaker_creates_new(self):
        """Test get_breaker creates new breaker for unknown provider."""
        registry = CircuitBreakerRegistry()
        # Clean up any existing breaker for this test
        registry._breakers.pop("NewTestCBProvider", None)

        breaker = registry.get_breaker("NewTestCBProvider")

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_threshold == 5  # Default

    def test_get_breaker_returns_existing(self):
        """Test get_breaker returns existing breaker."""
        registry = CircuitBreakerRegistry()
        breaker1 = registry.get_breaker("ExistingCBProvider")
        breaker1.record_failure()

        breaker2 = registry.get_breaker("ExistingCBProvider")

        assert breaker1 is breaker2
        assert breaker2.failure_count == 1

    def test_get_breaker_custom_config(self):
        """Test get_breaker with custom configuration."""
        registry = CircuitBreakerRegistry()
        # Clean up for this test
        registry._breakers.pop("CustomCBProvider", None)

        breaker = registry.get_breaker(
            "CustomCBProvider",
            failure_threshold=10,
            reset_timeout_seconds=120.0,
        )

        assert breaker.failure_threshold == 10
        assert breaker.reset_timeout_seconds == 120.0

    def test_get_all_breakers(self):
        """Test getting all registered breakers."""
        registry = CircuitBreakerRegistry()
        registry.get_breaker("CBProvider1")
        registry.get_breaker("CBProvider2")

        all_breakers = registry.get_all_breakers()

        assert "CBProvider1" in all_breakers
        assert "CBProvider2" in all_breakers

    def test_reset_all(self):
        """Test resetting all breakers."""
        registry = CircuitBreakerRegistry()
        breaker1 = registry.get_breaker("ResetCBProvider1", failure_threshold=1)
        breaker2 = registry.get_breaker("ResetCBProvider2", failure_threshold=1)
        breaker1.record_failure()
        breaker2.record_failure()
        assert breaker1.state == CircuitState.OPEN
        assert breaker2.state == CircuitState.OPEN

        registry.reset_all()

        assert breaker1.state == CircuitState.CLOSED
        assert breaker2.state == CircuitState.CLOSED

    def test_get_status(self):
        """Test getting status of all breakers."""
        registry = CircuitBreakerRegistry()
        # Clean up for clean test
        registry._breakers.pop("StatusCBProvider", None)

        breaker = registry.get_breaker("StatusCBProvider", failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()

        status = registry.get_status()

        assert "StatusCBProvider" in status
        assert status["StatusCBProvider"]["state"] == "closed"
        assert status["StatusCBProvider"]["failure_count"] == 2
        assert status["StatusCBProvider"]["failure_threshold"] == 3

    def test_thread_safety(self):
        """Test registry is thread-safe under concurrent access."""
        registry = CircuitBreakerRegistry()
        errors = []

        def access_breakers(i):
            try:
                breaker = registry.get_breaker(f"ConcurrentCBProvider{i % 5}")
                breaker.record_failure()
                _ = breaker.state
                return True
            except Exception as e:
                return e

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(access_breakers, i) for i in range(100)]
            for future in as_completed(futures):
                result = future.result()
                if isinstance(result, Exception):
                    errors.append(result)

        assert len(errors) == 0


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with network errors."""

    def test_integration_with_handle_network_errors(self):
        """Test circuit breaker integration with handle_network_errors.

        This tests that the circuit breaker is properly updated when
        network errors occur through the handle_network_errors context manager.
        """
        import requests

        from src.api.base import handle_network_errors
        from src.core.exceptions import NetworkError

        # Get a fresh breaker for testing
        registry = CircuitBreakerRegistry()
        registry._breakers.pop("IntegrationTestProvider", None)
        breaker = registry.get_breaker("IntegrationTestProvider", failure_threshold=2)

        assert breaker.state == CircuitState.CLOSED

        # Simulate failures
        for _ in range(2):
            try:
                with handle_network_errors("IntegrationTestProvider"):
                    raise requests.exceptions.ConnectionError("Test error")
            except NetworkError:
                pass

        # Circuit should now be open
        assert breaker.state == CircuitState.OPEN

        # Next request should be blocked
        with pytest.raises(NetworkError, match="circuit open"):
            with handle_network_errors("IntegrationTestProvider"):
                pass  # Should not reach here

    def test_circuit_breaker_can_be_disabled(self):
        """Test that circuit breaker can be disabled for specific calls."""
        import requests

        from src.api.base import handle_network_errors
        from src.core.exceptions import NetworkError

        # Get a fresh breaker
        registry = CircuitBreakerRegistry()
        registry._breakers.pop("DisabledCBProvider", None)
        breaker = registry.get_breaker("DisabledCBProvider", failure_threshold=1)

        # Open the circuit
        try:
            with handle_network_errors("DisabledCBProvider"):
                raise requests.exceptions.ConnectionError("Test error")
        except NetworkError:
            pass

        assert breaker.state == CircuitState.OPEN

        # With circuit breaker disabled, request should proceed (and fail normally)
        with pytest.raises(NetworkError, match="connection failed"):
            with handle_network_errors("DisabledCBProvider", use_circuit_breaker=False):
                raise requests.exceptions.ConnectionError("Another error")
