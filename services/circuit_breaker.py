"""
Circuit breaker
===============
Shared three-state circuit breaker, lifted verbatim from the SMTP breaker in
``services/notification_service.py`` so the external-call gateway
(``services/external_call_gateway.py``) and the mail path use one
implementation.

States:
    CLOSED    - normal operation, requests pass through.
    OPEN      - too many consecutive failures; requests are rejected
                immediately until ``recovery_timeout`` elapses.
    HALF_OPEN - recovery window; exactly one probe request is allowed.
                Success closes the breaker, failure re-opens it.

Semantics are unchanged from the original: only *transient* failures count
toward the threshold (``record_failure``); a non-transient failure
(``record_non_transient_failure``, e.g. an authentication error) resets the
counter and, from HALF_OPEN, closes the breaker because the dependency is
reachable.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Thread-safe consecutive-failure circuit breaker."""

    #: Consecutive transient failures before the breaker opens.
    FAILURE_THRESHOLD: int = 5
    #: Seconds the breaker stays open before allowing a half-open probe.
    RECOVERY_TIMEOUT: int = 120

    def __init__(self, failure_threshold: Optional[int] = None,
                 recovery_timeout: Optional[int] = None, *,
                 name: str = 'dependency') -> None:
        if failure_threshold is not None:
            self.FAILURE_THRESHOLD = max(1, int(failure_threshold))
        if recovery_timeout is not None:
            self.RECOVERY_TIMEOUT = max(0, int(recovery_timeout))
        self.name = name
        self._lock = threading.RLock()
        self._consecutive_failures: int = 0
        self._state: str = 'closed'
        self._opened_at: Optional[datetime] = None
        self._last_failure_error: Optional[str] = None
        self._half_open_probe_in_flight: bool = False

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == 'open' and self._opened_at:
                elapsed = (datetime.now(timezone.utc) - self._opened_at).total_seconds()
                if elapsed >= self.RECOVERY_TIMEOUT:
                    self._state = 'half_open'
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            current_state = self.state
            if current_state == 'open':
                return False
            if current_state == 'half_open':
                if self._half_open_probe_in_flight:
                    return False
                self._half_open_probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._state = 'closed'
            self._opened_at = None
            self._last_failure_error = None
            self._half_open_probe_in_flight = False

    def record_non_transient_failure(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._last_failure_error = None
            self._half_open_probe_in_flight = False
            if self._state == 'half_open':
                self._state = 'closed'
                self._opened_at = None

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_error = error
            self._half_open_probe_in_flight = False
            if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                if self._state != 'open':
                    logger.warning(
                        "%s circuit breaker OPEN after %d consecutive failures (last: %s). "
                        "Will retry after %ds.",
                        self.name, self._consecutive_failures, error, self.RECOVERY_TIMEOUT,
                    )
                    self._state = 'open'
                    self._opened_at = datetime.now(timezone.utc)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'state': self.state,
                'consecutive_failures': self._consecutive_failures,
                'last_failure': self._last_failure_error,
                'opened_at': self._opened_at.isoformat() if self._opened_at else None,
            }


__all__ = ['CircuitBreaker']
