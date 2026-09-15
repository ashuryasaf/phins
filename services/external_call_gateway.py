"""
External-call gateway
=====================
One choke point for every outbound HTTP call an agent makes to a paid or
rate-limited provider (LLM completions, speech-to-text, video generation).
Design: ``docs/agent_operations_optimization_design.md`` §A2.

The gateway wraps a caller-supplied ``request_fn`` and adds, in this order:

1. **Response cache** - opt-in per call via ``cache_key``; successful results
   are kept for ``PHINS_GATEWAY_CACHE_TTL`` seconds (default 3600, ``0``
   disables). Cached values are deep-copied on the way in and out so a
   caller can never mutate what another caller receives. A caller that can
   only judge a result after the fact (schema validation) passes
   ``cache_when`` so an unusable result is returned but never stored.
2. **Budget enforcement** - per ``(budget_scope, agent_id, UTC day)`` call and
   token caps (``PHINS_AI_DAILY_CALL_BUDGET``, ``PHINS_AI_DAILY_TOKEN_BUDGET``;
   ``0`` = unlimited). Over budget raises :class:`BudgetExceeded` *before*
   the provider is contacted and records a ``blocked=True`` usage row so the
   refusal is visible in cost reporting. Callers fall back to their
   deterministic path exactly as they do for any provider failure. Calls the
   provider does not bill (polling an already-paid job) pass ``budget=False``
   so they neither consume nor are refused by the cap.
3. **Circuit breaker** per ``(provider_kind, endpoint)`` - the shared
   :class:`services.circuit_breaker.CircuitBreaker`; an open breaker raises
   :class:`CircuitOpen` without contacting the provider.
4. **Bounded retry with full jitter** for transient failures only
   (connection errors, timeouts, HTTP 408/425/429/5xx). ``Retry-After`` is
   honoured when the exception exposes it. Non-transient failures (4xx other
   than the above, value errors) are raised immediately and do not count
   toward the breaker.
5. **Usage metering** - when ``meter=True`` every successful call produces
   exactly one ``ai_usage_service`` record carrying ``agent_id``. Callers
   that already meter with richer context (the LLM ``usage_hook``, the
   transcription ``_meter``) pass ``meter=False`` and only the budget
   accounting uses the extracted usage. Either way there is exactly one
   usage record per successful call.

The gateway never changes what ``request_fn`` returns: on success the value
is handed back unchanged (or an equal deep copy on a cache hit).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Environment knobs -----------------------------------------------------------

MAX_RETRIES_ENV = 'PHINS_GATEWAY_MAX_RETRIES'          # default 2
CACHE_TTL_ENV = 'PHINS_GATEWAY_CACHE_TTL'              # seconds, default 3600
DAILY_TOKEN_BUDGET_ENV = 'PHINS_AI_DAILY_TOKEN_BUDGET'  # 0 = unlimited
DAILY_CALL_BUDGET_ENV = 'PHINS_AI_DAILY_CALL_BUDGET'    # 0 = unlimited
BREAKER_THRESHOLD_ENV = 'PHINS_GATEWAY_CB_FAILURE_THRESHOLD'   # default 5
BREAKER_RECOVERY_ENV = 'PHINS_GATEWAY_CB_RECOVERY_TIMEOUT_SECS'  # default 60
RETRY_BASE_ENV = 'PHINS_GATEWAY_RETRY_BASE_SECS'       # default 0.5
RETRY_CAP_ENV = 'PHINS_GATEWAY_RETRY_CAP_SECS'         # default 8

_TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
_MAX_CACHE_ENTRIES = 2048


def _env_int(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name, '') or default).strip())
    except (TypeError, ValueError):
        return default
    return max(0, value)


def _env_float(name: str, default: float) -> float:
    try:
        value = float(str(os.environ.get(name, '') or default).strip())
    except (TypeError, ValueError):
        return default
    return max(0.0, value)


# Typed failures --------------------------------------------------------------

class GatewayError(RuntimeError):
    """Base class for failures raised by the gateway itself (not the provider)."""


class BudgetExceeded(GatewayError):
    """The daily call or token budget for this scope/agent is exhausted."""

    def __init__(self, *, scope: str, agent_id: str, kind: str, used: float, limit: float):
        self.scope, self.agent_id, self.kind, self.used, self.limit = scope, agent_id, kind, used, limit
        super().__init__(f"AI {kind} budget exceeded for {agent_id}/{scope}: {used:g} of {limit:g}")


class CircuitOpen(GatewayError):
    """The breaker for this provider endpoint is open; the provider was not contacted."""

    def __init__(self, provider_kind: str, endpoint: str, status: Dict[str, Any]):
        self.provider_kind, self.endpoint, self.status = provider_kind, endpoint, status
        super().__init__(f"{provider_kind} circuit open for {endpoint or 'default'}: "
                         f"{status.get('last_failure') or 'recent failures'}")


# Failure classification --------------------------------------------------------

def http_status_of(exc: BaseException) -> Optional[int]:
    """Best-effort HTTP status from ``requests`` / ``urllib`` exceptions."""
    code = getattr(exc, 'code', None)  # urllib.error.HTTPError
    if isinstance(code, int):
        return code
    response = getattr(exc, 'response', None)  # requests.HTTPError
    status = getattr(response, 'status_code', None)
    return status if isinstance(status, int) else None


def retry_after_of(exc: BaseException) -> Optional[float]:
    """Seconds from a ``Retry-After`` header if the exception carries one."""
    headers = getattr(exc, 'headers', None)  # urllib HTTPError
    if headers is None:
        response = getattr(exc, 'response', None)
        headers = getattr(response, 'headers', None)
    if not headers:
        return None
    try:
        raw = headers.get('Retry-After') if hasattr(headers, 'get') else None
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def is_transient(exc: BaseException) -> bool:
    """Transient = worth retrying and counts toward the breaker."""
    status = http_status_of(exc)
    if status is not None:
        return status in _TRANSIENT_HTTP
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    name = type(exc).__name__
    module = type(exc).__module__ or ''
    if module.startswith('requests') and name in (
            'ConnectionError', 'Timeout', 'ConnectTimeout', 'ReadTimeout', 'ChunkedEncodingError'):
        return True
    if module.startswith('urllib') and name == 'URLError':
        return True
    if name in ('socket.timeout', 'timeout'):
        return True
    return False


# Gateway ---------------------------------------------------------------------

class ExternalCallGateway:
    """Process-wide policy layer for outbound provider calls. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._breakers: Dict[Tuple[str, str], CircuitBreaker] = {}
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._budget: Dict[Tuple[str, str, str], Dict[str, float]] = {}
        self._stats: Dict[str, int] = {
            'calls': 0, 'cache_hits': 0, 'retries': 0, 'budget_blocks': 0,
            'circuit_blocks': 0, 'failures': 0,
        }
        # Injectable for tests; production uses time.sleep.
        self._sleep: Callable[[float], None] = time.sleep

    # ---- policy lookups ---------------------------------------------------

    def breaker(self, provider_kind: str, endpoint: str = '') -> CircuitBreaker:
        key = (str(provider_kind), str(endpoint or ''))
        with self._lock:
            cb = self._breakers.get(key)
            if cb is None:
                cb = CircuitBreaker(
                    failure_threshold=_env_int(BREAKER_THRESHOLD_ENV, 5),
                    recovery_timeout=_env_int(BREAKER_RECOVERY_ENV, 60),
                    name=f"{provider_kind} gateway",
                )
                self._breakers[key] = cb
            return cb

    @staticmethod
    def make_cache_key(provider_kind: str, *parts: Any) -> str:
        """sha256 over the provider kind and a canonical JSON of the request."""
        canonical = json.dumps([provider_kind, *parts], sort_keys=True, default=str,
                               ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def budget_usage(self, scope: str, agent_id: str) -> Dict[str, float]:
        with self._lock:
            return dict(self._budget.get((str(scope), str(agent_id), self._today()),
                                         {'calls': 0, 'tokens': 0}))

    def _check_budget(self, scope: str, agent_id: str) -> None:
        call_cap = _env_int(DAILY_CALL_BUDGET_ENV, 0)
        token_cap = _env_int(DAILY_TOKEN_BUDGET_ENV, 0)
        if not call_cap and not token_cap:
            return
        used = self.budget_usage(scope, agent_id)
        if call_cap and used['calls'] >= call_cap:
            raise BudgetExceeded(scope=scope, agent_id=agent_id, kind='call',
                                 used=used['calls'], limit=call_cap)
        if token_cap and used['tokens'] >= token_cap:
            raise BudgetExceeded(scope=scope, agent_id=agent_id, kind='token',
                                 used=used['tokens'], limit=token_cap)

    def _charge_budget(self, scope: str, agent_id: str, tokens: float) -> None:
        key = (str(scope), str(agent_id), self._today())
        with self._lock:
            bucket = self._budget.setdefault(key, {'calls': 0, 'tokens': 0})
            bucket['calls'] += 1
            bucket['tokens'] += max(0.0, float(tokens or 0))
            # Keep only today's buckets so the map cannot grow unbounded.
            today = self._today()
            for stale in [k for k in self._budget if k[2] != today]:
                self._budget.pop(stale, None)

    # ---- cache ---------------------------------------------------------------

    def _cache_get(self, key: Optional[str]) -> Tuple[bool, Any]:
        if not key:
            return False, None
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False, None
            expires_at, value = entry
            if expires_at <= now:
                self._cache.pop(key, None)
                return False, None
            return True, copy.deepcopy(value)

    def _cache_put(self, key: Optional[str], value: Any, ttl: float) -> None:
        if not key or ttl <= 0:
            return
        try:
            stored = copy.deepcopy(value)
        except Exception:  # un-copyable values are simply not cached
            return
        with self._lock:
            if len(self._cache) >= _MAX_CACHE_ENTRIES:
                # Drop the soonest-expiring entries first.
                for stale_key, _ in sorted(self._cache.items(), key=lambda kv: kv[1][0])[:_MAX_CACHE_ENTRIES // 8]:
                    self._cache.pop(stale_key, None)
            self._cache[key] = (time.monotonic() + ttl, stored)

    @staticmethod
    def _is_cacheable(result: Any, cache_when: Optional[Callable[[Any], bool]]) -> bool:
        """A caller-supplied predicate keeps unusable results out of the cache."""
        if cache_when is None:
            return True
        try:
            return bool(cache_when(result))
        except Exception as exc:  # noqa: BLE001 - a failing predicate only skips the cache
            logger.debug("gateway cache predicate failed: %s", exc)
            return False

    # ---- metering ------------------------------------------------------------

    @staticmethod
    def _record_usage(*, provider_kind: str, operation: str, agent_id: str,
                      usage: Dict[str, Any], context: Dict[str, Any],
                      duration_ms: int, blocked: bool = False) -> None:
        try:
            from services.ai_usage_service import get_ai_usage_service
            get_ai_usage_service().record_usage(
                provider=provider_kind,
                operation=operation,
                model=usage.get('model'),
                input_tokens=usage.get('input_tokens'),
                output_tokens=usage.get('output_tokens'),
                media_seconds=usage.get('media_seconds'),
                pages=usage.get('pages'),
                duration_ms=duration_ms,
                agent_id=agent_id,
                blocked=blocked,
                **{k: v for k, v in context.items()
                   if k in ('customer_id', 'assessment_id', 'document_id', 'job_id', 'prompt_version')},
            )
        except Exception as exc:  # noqa: BLE001 - metering never breaks the call
            logger.debug("gateway usage metering skipped: %s", exc)

    # ---- the call -------------------------------------------------------------

    def call(
        self,
        provider_kind: str,
        request_fn: Callable[[], Any],
        *,
        endpoint: str = '',
        operation: str = 'external_call',
        agent_id: str = 'unknown',
        budget_scope: Optional[str] = None,
        budget: bool = True,
        cache_key: Optional[str] = None,
        cache_ttl: Optional[float] = None,
        cache_when: Optional[Callable[[Any], bool]] = None,
        max_retries: Optional[int] = None,
        usage_from: Optional[Callable[[Any], Dict[str, Any]]] = None,
        meter: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Run ``request_fn`` under the gateway policy and return its value.

        Raises :class:`BudgetExceeded` / :class:`CircuitOpen` without calling
        the provider, or re-raises the provider's own exception after the
        retry budget is spent (non-transient failures are raised at once).
        """
        context = dict(context or {})
        scope = str(budget_scope or context.get('customer_id') or 'global')
        ttl = _env_float(CACHE_TTL_ENV, 3600.0) if cache_ttl is None else max(0.0, float(cache_ttl))

        hit, cached = self._cache_get(cache_key if ttl > 0 else None)
        if hit:
            with self._lock:
                self._stats['cache_hits'] += 1
            return cached

        if budget:
            try:
                self._check_budget(scope, agent_id)
            except BudgetExceeded as exc:
                with self._lock:
                    self._stats['budget_blocks'] += 1
                logger.warning("gateway blocked %s/%s: %s", agent_id, operation, exc)
                self._record_usage(provider_kind=provider_kind, operation=operation, agent_id=agent_id,
                                   usage={}, context=context, duration_ms=0, blocked=True)
                raise

        cb = self.breaker(provider_kind, endpoint)
        if not cb.allow_request():
            with self._lock:
                self._stats['circuit_blocks'] += 1
            raise CircuitOpen(provider_kind, endpoint, cb.get_status())

        retries = _env_int(MAX_RETRIES_ENV, 2) if max_retries is None else max(0, int(max_retries))
        base = _env_float(RETRY_BASE_ENV, 0.5)
        cap = _env_float(RETRY_CAP_ENV, 8.0)
        started = time.time()

        attempt = 0
        while True:
            with self._lock:
                self._stats['calls'] += 1
            try:
                result = request_fn()
            except Exception as exc:  # noqa: BLE001 - classified below
                with self._lock:
                    self._stats['failures'] += 1
                if not is_transient(exc):
                    cb.record_non_transient_failure()
                    raise
                cb.record_failure(f"{type(exc).__name__}: {exc}"[:300])
                if attempt >= retries or not cb.allow_request():
                    raise
                attempt += 1
                with self._lock:
                    self._stats['retries'] += 1
                delay = retry_after_of(exc)
                if delay is None:
                    delay = random.uniform(0, min(cap, base * (2 ** (attempt - 1))))
                self._sleep(min(cap, delay))
                continue
            except BaseException:
                # Thread unwound mid-request (KeyboardInterrupt, SystemExit):
                # no outcome to record, but never strand a half-open probe.
                cb.release_probe()
                raise

            cb.record_success()
            duration_ms = int((time.time() - started) * 1000)
            usage: Dict[str, Any] = {}
            if usage_from is not None:
                try:
                    usage = dict(usage_from(result) or {})
                except Exception as exc:  # noqa: BLE001 - never let accounting break the result
                    logger.debug("gateway usage extraction failed: %s", exc)
            tokens = float(usage.get('input_tokens') or 0) + float(usage.get('output_tokens') or 0)
            if budget:
                self._charge_budget(scope, agent_id, tokens)
            if meter:
                self._record_usage(provider_kind=provider_kind, operation=operation,
                                   agent_id=agent_id, usage=usage, context=context,
                                   duration_ms=duration_ms)
            if self._is_cacheable(result, cache_when):
                self._cache_put(cache_key, result, ttl)
            return result

    # ---- introspection ---------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'stats': dict(self._stats),
                'cache_entries': len(self._cache),
                'breakers': {
                    f"{kind}|{endpoint or 'default'}": cb.get_status()
                    for (kind, endpoint), cb in self._breakers.items()
                },
                'budgets_today': {
                    f"{scope}|{agent}": dict(bucket)
                    for (scope, agent, day), bucket in self._budget.items() if day == self._today()
                },
            }

    def reset(self) -> None:
        """Forget cache, budgets, breakers and counters (tests / operator reset)."""
        with self._lock:
            self._breakers.clear()
            self._cache.clear()
            self._budget.clear()
            for key in self._stats:
                self._stats[key] = 0


# Module-level singleton --------------------------------------------------------

_gateway: Optional[ExternalCallGateway] = None
_gateway_lock = threading.Lock()


def get_gateway() -> ExternalCallGateway:
    global _gateway
    with _gateway_lock:
        if _gateway is None:
            _gateway = ExternalCallGateway()
        return _gateway


def reset_gateway() -> None:
    with _gateway_lock:
        if _gateway is not None:
            _gateway.reset()


__all__ = [
    'ExternalCallGateway', 'GatewayError', 'BudgetExceeded', 'CircuitOpen',
    'get_gateway', 'reset_gateway', 'is_transient', 'http_status_of', 'retry_after_of',
]
