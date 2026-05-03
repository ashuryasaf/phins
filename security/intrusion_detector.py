"""Intrusion detection and security event logging for PHINS.

Provides:

1. **Security Event Bus** — unified ``record_event`` sink that all security
   modules feed into.  Events are stored in a bounded in-memory ring buffer
   and optionally forwarded to the Python logging system.
2. **Pattern correlation** — watches for attack patterns that span multiple
   requests (e.g. credential stuffing across different usernames from the
   same IP, slow-rate directory enumeration).
3. **Anomaly flags** — detects unusual behavioural shifts such as a
   previously-idle IP suddenly issuing hundreds of API calls, or a session
   used from a new IP/user-agent.
4. **Alert generation** — when a correlation rule fires it produces an
   ``Alert`` that admin endpoints can surface on the security dashboard.
5. **Session hijack detection** — tracks the (session, ip, user-agent)
   triple and flags when a token appears from a different origin.

Thread-safe, stdlib-only.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "Severity",
    "SecurityEvent",
    "Alert",
    "record_event",
    "get_recent_events",
    "get_active_alerts",
    "acknowledge_alert",
    "check_session_anomaly",
    "get_security_summary",
    "reset_ids",
]

LOGGER = logging.getLogger("phins.security.intrusion_detector")


# ── severity enum ────────────────────────────────────────────────────────────

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class SecurityEvent:
    timestamp: float
    event_type: str
    severity: Severity
    client_ip: str
    details: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    user_agent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "severity": self.severity.value,
            "client_ip": self.client_ip,
            "session_id": self.session_id[:8] + "..." if len(self.session_id) > 8 else self.session_id,
            "user_agent": self.user_agent[:80],
            "details": self.details,
        }


@dataclass
class Alert:
    alert_id: str
    created_at: float
    rule: str
    severity: Severity
    message: str
    source_ip: str
    acknowledged: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "created_at": self.created_at,
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
            "source_ip": self.source_ip,
            "acknowledged": self.acknowledged,
            "details": self.details,
        }


# ── configuration ────────────────────────────────────────────────────────────

EVENT_BUFFER_SIZE = int(os.environ.get("PHINS_IDS_BUFFER_SIZE", "2000"))
MAX_ALERTS = int(os.environ.get("PHINS_IDS_MAX_ALERTS", "200"))

CREDENTIAL_STUFFING_THRESHOLD = 10
CREDENTIAL_STUFFING_WINDOW = 300

DIRECTORY_ENUM_THRESHOLD = 8
DIRECTORY_ENUM_WINDOW = 120

ACTIVITY_SPIKE_THRESHOLD = 100
ACTIVITY_SPIKE_WINDOW = 60

# ── internal state ───────────────────────────────────────────────────────────

_lock = threading.RLock()
_events: List[SecurityEvent] = []
_alerts: List[Alert] = []
_alert_counter = 0

_ip_event_counts: Dict[str, List[float]] = defaultdict(list)

_credential_attempts: Dict[str, List[Tuple[float, str]]] = defaultdict(list)

_session_origins: Dict[str, Tuple[str, str]] = {}

_directory_probes: Dict[str, List[float]] = defaultdict(list)

_event_listeners: List[Callable[[SecurityEvent], None]] = []


# ── public API ───────────────────────────────────────────────────────────────

def record_event(
    event_type: str,
    *,
    severity: Severity = Severity.WARNING,
    client_ip: str = "",
    details: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    user_agent: str = "",
) -> SecurityEvent:
    """Record a security event and run correlation rules."""
    now = time.time()
    event = SecurityEvent(
        timestamp=now,
        event_type=event_type,
        severity=severity,
        client_ip=client_ip,
        details=details or {},
        session_id=session_id,
        user_agent=user_agent,
    )

    with _lock:
        _events.append(event)
        if len(_events) > EVENT_BUFFER_SIZE:
            _events[:] = _events[-EVENT_BUFFER_SIZE:]

        _ip_event_counts[client_ip].append(now)

    # Log to standard logger
    log_fn = LOGGER.info if severity == Severity.INFO else (
        LOGGER.warning if severity == Severity.WARNING else LOGGER.critical
    )
    log_fn(
        "[IDS] %s severity=%s ip=%s %s",
        event_type, severity.value, client_ip,
        _summarize_details(details),
    )

    # Run correlation rules
    _run_correlations(event)

    # Notify listeners
    for listener in _event_listeners:
        try:
            listener(event)
        except Exception:
            pass

    return event


def get_recent_events(
    limit: int = 50,
    *,
    severity: Optional[Severity] = None,
    event_type: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return recent events, optionally filtered."""
    with _lock:
        filtered = _events[:]
    if severity:
        filtered = [e for e in filtered if e.severity == severity]
    if event_type:
        filtered = [e for e in filtered if e.event_type == event_type]
    if client_ip:
        filtered = [e for e in filtered if e.client_ip == client_ip]
    return [e.to_dict() for e in filtered[-limit:]]


def get_active_alerts(include_acknowledged: bool = False) -> List[Dict[str, Any]]:
    """Return current alerts for the security dashboard."""
    with _lock:
        alerts = _alerts[:]
    if not include_acknowledged:
        alerts = [a for a in alerts if not a.acknowledged]
    return [a.to_dict() for a in alerts]


def acknowledge_alert(alert_id: str) -> bool:
    """Mark an alert as acknowledged. Returns True if found."""
    with _lock:
        for alert in _alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
    return False


def check_session_anomaly(
    session_id: str,
    client_ip: str,
    user_agent: str,
) -> Optional[str]:
    """Check if a session is being used from an unexpected origin.

    Returns a warning string if anomalous, None otherwise.
    """
    if not session_id:
        return None

    with _lock:
        origin = _session_origins.get(session_id)
        if origin is None:
            _session_origins[session_id] = (client_ip, user_agent)
            return None

        orig_ip, orig_ua = origin
        anomalies: List[str] = []

        if orig_ip != client_ip:
            anomalies.append(f"ip_changed ({orig_ip} -> {client_ip})")
        if orig_ua and user_agent and orig_ua != user_agent:
            anomalies.append("user_agent_changed")

        if anomalies:
            msg = "; ".join(anomalies)
            LOGGER.warning(
                "[IDS] Session anomaly: session=%s %s",
                session_id[:8], msg,
            )
            return msg
    return None


def register_event_listener(fn: Callable[[SecurityEvent], None]) -> None:
    """Register a callback invoked on every security event."""
    _event_listeners.append(fn)


def get_security_summary() -> Dict[str, Any]:
    """High-level security summary for admin dashboard."""
    now = time.time()
    window = 3600
    with _lock:
        recent = [e for e in _events if e.timestamp > now - window]
        by_type: Dict[str, int] = defaultdict(int)
        by_severity: Dict[str, int] = defaultdict(int)
        by_ip: Dict[str, int] = defaultdict(int)
        for e in recent:
            by_type[e.event_type] += 1
            by_severity[e.severity.value] += 1
            by_ip[e.client_ip] += 1

        top_ips = sorted(by_ip.items(), key=lambda kv: kv[1], reverse=True)[:10]
        active_alerts = sum(1 for a in _alerts if not a.acknowledged)

    return {
        "window_seconds": window,
        "total_events": len(recent),
        "by_type": dict(by_type),
        "by_severity": dict(by_severity),
        "top_source_ips": top_ips,
        "active_alerts": active_alerts,
        "total_alerts": len(_alerts),
    }


def reset_ids() -> None:
    """Clear all IDS state (used by tests)."""
    with _lock:
        _events.clear()
        _alerts.clear()
        _ip_event_counts.clear()
        _credential_attempts.clear()
        _session_origins.clear()
        _directory_probes.clear()
        _event_listeners.clear()
        global _alert_counter
        _alert_counter = 0


# ── correlation rules ────────────────────────────────────────────────────────

def _run_correlations(event: SecurityEvent) -> None:
    """Run post-event correlation rules."""
    _check_credential_stuffing(event)
    _check_directory_enumeration(event)
    _check_activity_spike(event)


def _check_credential_stuffing(event: SecurityEvent) -> None:
    if event.event_type not in ("failed_login", "brute_force", "invalid_auth_token"):
        return
    ip = event.client_ip
    username = event.details.get("username", "")
    now = event.timestamp
    cutoff = now - CREDENTIAL_STUFFING_WINDOW

    with _lock:
        _credential_attempts[ip].append((now, username))
        _credential_attempts[ip] = [
            (t, u) for t, u in _credential_attempts[ip] if t > cutoff
        ]
        unique_users = len({u for _, u in _credential_attempts[ip]})

    if unique_users >= CREDENTIAL_STUFFING_THRESHOLD:
        _create_alert(
            rule="credential_stuffing",
            severity=Severity.CRITICAL,
            message=(
                f"Credential stuffing detected from {ip}: "
                f"{unique_users} unique usernames in {CREDENTIAL_STUFFING_WINDOW}s"
            ),
            source_ip=ip,
            details={"unique_usernames": unique_users},
        )


def _check_directory_enumeration(event: SecurityEvent) -> None:
    if event.event_type != "directory_scan":
        return
    ip = event.client_ip
    now = event.timestamp
    cutoff = now - DIRECTORY_ENUM_WINDOW

    with _lock:
        _directory_probes[ip].append(now)
        _directory_probes[ip] = [t for t in _directory_probes[ip] if t > cutoff]
        count = len(_directory_probes[ip])

    if count >= DIRECTORY_ENUM_THRESHOLD:
        _create_alert(
            rule="directory_enumeration",
            severity=Severity.WARNING,
            message=(
                f"Directory enumeration from {ip}: "
                f"{count} probes in {DIRECTORY_ENUM_WINDOW}s"
            ),
            source_ip=ip,
            details={"probe_count": count},
        )


def _check_activity_spike(event: SecurityEvent) -> None:
    ip = event.client_ip
    now = event.timestamp
    cutoff = now - ACTIVITY_SPIKE_WINDOW

    with _lock:
        entries = _ip_event_counts.get(ip, [])
        recent = [t for t in entries if t > cutoff]
        _ip_event_counts[ip] = recent

    if len(recent) >= ACTIVITY_SPIKE_THRESHOLD:
        _create_alert(
            rule="activity_spike",
            severity=Severity.WARNING,
            message=(
                f"Abnormal activity spike from {ip}: "
                f"{len(recent)} security events in {ACTIVITY_SPIKE_WINDOW}s"
            ),
            source_ip=ip,
            details={"event_count": len(recent)},
        )


def _create_alert(
    *,
    rule: str,
    severity: Severity,
    message: str,
    source_ip: str,
    details: Optional[Dict[str, Any]] = None,
) -> Alert:
    global _alert_counter
    with _lock:
        _alert_counter += 1
        alert_id = f"ALERT-{_alert_counter:06d}"
        alert = Alert(
            alert_id=alert_id,
            created_at=time.time(),
            rule=rule,
            severity=severity,
            message=message,
            source_ip=source_ip,
            details=details or {},
        )
        _alerts.append(alert)
        if len(_alerts) > MAX_ALERTS:
            _alerts[:] = _alerts[-MAX_ALERTS:]

    LOGGER.critical(
        "[IDS ALERT] %s rule=%s ip=%s — %s",
        alert_id, rule, source_ip, message,
    )
    return alert


def _summarize_details(details: Optional[Dict[str, Any]]) -> str:
    if not details:
        return ""
    parts = []
    for k, v in list(details.items())[:5]:
        parts.append(f"{k}={v!r}")
    return " ".join(parts)


def record_failed_login(client_ip: str, username: str, reason: str = "") -> SecurityEvent:
    """Convenience wrapper for login failures."""
    return record_event(
        "failed_login",
        severity=Severity.WARNING,
        client_ip=client_ip,
        details={"username": username, "reason": reason},
    )


def record_upload_threat(
    client_ip: str,
    filename: str,
    threats: Tuple[str, ...] | List[str],
) -> SecurityEvent:
    """Convenience wrapper for malicious upload detection."""
    return record_event(
        "malicious_upload",
        severity=Severity.CRITICAL,
        client_ip=client_ip,
        details={"filename": filename, "threats": list(threats)},
    )
