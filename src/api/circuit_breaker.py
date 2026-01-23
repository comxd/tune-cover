"""
Circuit breaker pattern for provider resilience.

This module implements the circuit breaker pattern to prevent cascading failures
when a provider becomes unavailable. After a threshold of consecutive failures,
the circuit "opens" and requests are rejected immediately without attempting
to contact the failing service.

States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests rejected immediately
    - HALF_OPEN: Testing recovery, limited requests allowed
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass(slots=True)
class CircuitBreaker:
    """
    Circuit breaker for provider resilience.

    The circuit breaker monitors failures and temporarily disables
    a provider after consecutive failures. This prevents wasted
    requests to an unavailable service and allows time for recovery.

    State transitions:
        CLOSED -> OPEN: After failure_threshold consecutive failures
        OPEN -> HALF_OPEN: After reset_timeout_seconds
        HALF_OPEN -> CLOSED: After a successful request
        HALF_OPEN -> OPEN: After a failed request

    Default configuration:
        - failure_threshold: 5 consecutive failures to open circuit
        - reset_timeout_seconds: 60 seconds before testing recovery
        - half_open_max_requests: 1 test request in half-open state

    Usage:
        breaker = CircuitBreaker()
        if not breaker.allow_request():
            raise NetworkError("Provider temporarily unavailable")
        try:
            result = make_request()
            breaker.record_success()
        except Exception:
            breaker.record_failure()
            raise
    """

    failure_threshold: int = 5
    reset_timeout_seconds: float = 60.0
    half_open_max_requests: int = 1

    # Internal state fields (not part of __init__)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False, repr=False)
    _failure_count: int = field(default=0, init=False, repr=False)
    _last_failure_time: float = field(default=0.0, init=False, repr=False)
    _half_open_requests: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _get_state_and_maybe_transition(self) -> CircuitState:
        """
        Get current state and perform timeout-based transition if needed.

        Must be called while holding self._lock.
        Automatically transitions from OPEN to HALF_OPEN after the reset timeout.
        """
        if (
            self._state == CircuitState.OPEN
            and time.time() - self._last_failure_time >= self.reset_timeout_seconds
        ):
            logger.info("Circuit breaker transitioning to HALF_OPEN")
            self._state = CircuitState.HALF_OPEN
            self._half_open_requests = 0
        return self._state

    @property
    def state(self) -> CircuitState:
        """
        Get current circuit state.

        Automatically transitions from OPEN to HALF_OPEN after the reset timeout.
        """
        with self._lock:
            return self._get_state_and_maybe_transition()

    @property
    def failure_count(self) -> int:
        """Get current consecutive failure count."""
        with self._lock:
            return self._failure_count

    @property
    def is_closed(self) -> bool:
        """Check if circuit is in closed (normal) state."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is in open (rejecting) state."""
        return self.state == CircuitState.OPEN

    def allow_request(self) -> bool:
        """
        Check if a request should be allowed.

        This method is atomic - it holds the lock for its entire duration
        to prevent race conditions between checking state and updating
        the half-open request counter.

        Returns:
            True if the request should proceed, False if it should be rejected
        """
        with self._lock:
            current_state = self._get_state_and_maybe_transition()

            if current_state == CircuitState.CLOSED:
                return True

            if current_state == CircuitState.OPEN:
                return False

            # HALF_OPEN: allow limited requests to test recovery
            if self._half_open_requests < self.half_open_max_requests:
                self._half_open_requests += 1
                return True
            return False

    def record_success(self) -> None:
        """
        Record a successful request.

        In HALF_OPEN state, this closes the circuit.
        Resets the failure count.
        """
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker recovered, transitioning to CLOSED")
                self._state = CircuitState.CLOSED
            self._failure_count = 0

    def record_failure(self) -> None:
        """
        Record a failed request.

        In HALF_OPEN state, this immediately reopens the circuit.
        In CLOSED state, increments failure count and may open the circuit.
        """
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning("Circuit breaker test request failed, reopening circuit")
                self._state = CircuitState.OPEN
            elif self._failure_count >= self.failure_threshold:
                logger.warning(
                    f"Circuit breaker opening after {self._failure_count} consecutive failures"
                )
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Force reset to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_requests = 0
            logger.info("Circuit breaker manually reset to CLOSED")


class CircuitBreakerRegistry:
    """
    Global registry for circuit breakers.

    Implemented as a singleton to provide consistent circuit breaker access
    across the application. Each provider gets its own CircuitBreaker
    instance, created on first access.

    Usage:
        breaker = CircuitBreakerRegistry().get_breaker("MusicBrainz")
        if breaker.state == CircuitState.OPEN:
            print("Provider temporarily unavailable")
    """

    _instance: "CircuitBreakerRegistry | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "CircuitBreakerRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._breakers: dict[str, CircuitBreaker] = {}
                cls._instance._breakers_lock = threading.Lock()
            return cls._instance

    def get_breaker(
        self,
        provider_name: str,
        failure_threshold: int = 5,
        reset_timeout_seconds: float = 60.0,
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker for a provider.

        Args:
            provider_name: Name of the provider (e.g., "MusicBrainz")
            failure_threshold: Number of failures before opening circuit
            reset_timeout_seconds: Time before attempting recovery

        Returns:
            CircuitBreaker instance for the provider
        """
        with self._breakers_lock:
            if provider_name not in self._breakers:
                self._breakers[provider_name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    reset_timeout_seconds=reset_timeout_seconds,
                )
            return self._breakers[provider_name]

    def get_all_breakers(self) -> dict[str, CircuitBreaker]:
        """
        Get circuit breakers for all registered providers.

        Returns:
            Dictionary mapping provider names to their circuit breakers
        """
        with self._breakers_lock:
            return dict(self._breakers)

    def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        with self._breakers_lock:
            for breaker in self._breakers.values():
                breaker.reset()

    def get_status(self) -> dict[str, dict]:
        """
        Get status of all circuit breakers.

        Returns:
            Dictionary mapping provider names to their status info
        """
        with self._breakers_lock:
            return {
                name: {
                    "state": breaker.state.value,
                    "failure_count": breaker.failure_count,
                    "failure_threshold": breaker.failure_threshold,
                    "reset_timeout_seconds": breaker.reset_timeout_seconds,
                }
                for name, breaker in self._breakers.items()
            }
