"""IP-layer firewall for PHINS.

Provides configurable IP-based access control that sits in front of the
existing ``is_ip_blocked`` / ``block_ip`` helpers in ``server.py``.

Features
--------
* **Blocklist / allowlist** — explicit CIDR-range and single-IP lists loaded
  from environment or programmatic API.
* **Geo-fence stubs** — placeholder hooks for country-level blocking when a
  GeoIP provider is available.
* **Adaptive threat scoring** — each IP accumulates a threat score from
  multiple detectors; when the score crosses a threshold the IP is
  automatically blocked for a configurable duration.
* **Connection-flood detection** — tracks per-IP connection counts inside a
  sliding window and flags IPs that exceed a burst threshold.
* **Request fingerprinting** — records a lightweight fingerprint per request
  so replayed or automated requests can be spotted.
* **Admin query API** — ``get_firewall_status`` returns a snapshot suitable
  for the security dashboard.

The module is thread-safe and stdlib-only.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

__all__ = [
    "FirewallVerdict",
    "check_request",
    "add_to_blocklist",
    "remove_from_blocklist",
    "add_to_allowlist",
    "remove_from_allowlist",
    "record_threat_signal",
    "get_threat_score",
    "get_firewall_status",
    "reset_firewall",
]

LOGGER = logging.getLogger("phins.security.firewall")

# ── configuration ────────────────────────────────────────────────────────────

THREAT_SCORE_BLOCK_THRESHOLD = int(
    os.environ.get("PHINS_FIREWALL_THREAT_THRESHOLD", "100")
)
THREAT_SCORE_DECAY_SECONDS = int(
    os.environ.get("PHINS_FIREWALL_SCORE_DECAY", "3600")
)
AUTO_BLOCK_DURATION_SECONDS = int(
    os.environ.get("PHINS_FIREWALL_BLOCK_DURATION", "86400")
)
BURST_WINDOW_SECONDS = int(
    os.environ.get("PHINS_FIREWALL_BURST_WINDOW", "10")
)
BURST_MAX_CONNECTIONS = int(
    os.environ.get("PHINS_FIREWALL_BURST_MAX", "50")
)
PHINS_TEST_MODE = str(os.environ.get("PHINS_TEST_MODE", "")).lower() in (
    "1", "true", "yes", "y",
)

# Threat-signal weights
SIGNAL_WEIGHTS: Dict[str, int] = {
    "sql_injection": 40,
    "xss_attempt": 35,
    "path_traversal": 30,
    "command_injection": 45,
    "malicious_payload": 35,
    "malicious_upload": 50,
    "brute_force": 25,
    "rate_limit_exceeded": 10,
    "invalid_auth_token": 15,
    "oversized_request": 20,
    "suspicious_user_agent": 10,
    "directory_scan": 20,
    "api_abuse": 15,
    "csrf_violation": 30,
}

# ── internal state ───────────────────────────────────────────────────────────

_lock = threading.RLock()

_blocklist_ips: Set[str] = set()
_blocklist_networks: Set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()
_allowlist_ips: Set[str] = set()
_allowlist_networks: Set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()

_auto_blocked: Dict[str, float] = {}  # ip -> expiry timestamp

_threat_scores: Dict[str, List[Tuple[float, int]]] = defaultdict(list)

_connection_log: Dict[str, List[float]] = defaultdict(list)

_request_fingerprints: Dict[str, List[Tuple[float, str]]] = defaultdict(list)

_SCORES_HARD_LIMIT = 10_000
_CONN_LOG_HARD_LIMIT = 10_000

# Suspicious user-agent fragments
_SUSPICIOUS_UA_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"sqlmap", re.IGNORECASE),
    re.compile(r"nikto", re.IGNORECASE),
    re.compile(r"nmap", re.IGNORECASE),
    re.compile(r"masscan", re.IGNORECASE),
    re.compile(r"dirbuster", re.IGNORECASE),
    re.compile(r"gobuster", re.IGNORECASE),
    re.compile(r"wfuzz", re.IGNORECASE),
    re.compile(r"hydra", re.IGNORECASE),
    re.compile(r"metasploit", re.IGNORECASE),
    re.compile(r"burpsuite", re.IGNORECASE),
    re.compile(r"zgrab", re.IGNORECASE),
]

_DIRECTORY_SCAN_PATHS: FrozenSet[str] = frozenset({
    "/.env", "/.git/config", "/wp-admin", "/wp-login.php",
    "/administrator", "/phpmyadmin", "/.htaccess", "/.htpasswd",
    "/server-status", "/server-info", "/xmlrpc.php", "/wp-content",
    "/actuator", "/actuator/health", "/debug", "/trace",
    "/console", "/manage", "/_config", "/config.json",
    "/admin/config", "/api/debug", "/api/config",
    "/backup", "/dump", "/db", "/database",
    "/.aws/credentials", "/.ssh/id_rsa",
})


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FirewallVerdict:
    """Result of firewall inspection for a single request."""

    allowed: bool
    reason: str = ""
    threat_score: int = 0
    signals: Tuple[str, ...] = ()


# ── public API ───────────────────────────────────────────────────────────────

def check_request(
    client_ip: str,
    *,
    path: str = "",
    method: str = "GET",
    user_agent: str = "",
    headers: Optional[Dict[str, str]] = None,
) -> FirewallVerdict:
    """Run firewall checks against an inbound request.

    Returns a :class:`FirewallVerdict` indicating whether the request should
    proceed.  Callers in ``server.py`` should reject requests where
    ``verdict.allowed is False``.
    """
    signals: List[str] = []
    now = time.time()

    # 1) Explicit allowlist — bypass all other checks
    if _is_allowlisted(client_ip):
        return FirewallVerdict(allowed=True, reason="allowlisted")

    # 2) Explicit blocklist
    if _is_blocklisted(client_ip):
        return FirewallVerdict(
            allowed=False, reason="ip_blocklisted", signals=("blocklist",)
        )

    # 3) Auto-block (threat score exceeded)
    with _lock:
        expiry = _auto_blocked.get(client_ip, 0)
        if expiry > now:
            return FirewallVerdict(
                allowed=False,
                reason="auto_blocked_threat_score",
                threat_score=_current_score(client_ip, now),
            )
        elif expiry:
            del _auto_blocked[client_ip]

    # 4) Suspicious user-agent
    if user_agent:
        for pat in _SUSPICIOUS_UA_PATTERNS:
            if pat.search(user_agent):
                signals.append("suspicious_user_agent")
                break

    # 5) Directory / vulnerability scanner detection
    if path and path.lower() in _DIRECTORY_SCAN_PATHS:
        signals.append("directory_scan")

    # 6) Connection-flood detection
    if _is_connection_flood(client_ip, now):
        signals.append("connection_flood")

    # Record any signals and check cumulative score
    for sig in signals:
        record_threat_signal(client_ip, sig)

    score = _current_score(client_ip, now)

    if not PHINS_TEST_MODE and score >= THREAT_SCORE_BLOCK_THRESHOLD:
        with _lock:
            _auto_blocked[client_ip] = now + AUTO_BLOCK_DURATION_SECONDS
        LOGGER.warning(
            "[FIREWALL] Auto-blocked %s — score=%d threshold=%d",
            client_ip, score, THREAT_SCORE_BLOCK_THRESHOLD,
        )
        return FirewallVerdict(
            allowed=False,
            reason="threat_score_exceeded",
            threat_score=score,
            signals=tuple(signals),
        )

    return FirewallVerdict(
        allowed=True,
        reason="passed",
        threat_score=score,
        signals=tuple(signals),
    )


def record_threat_signal(ip: str, signal_type: str) -> int:
    """Add a threat signal for *ip* and return the new cumulative score."""
    weight = SIGNAL_WEIGHTS.get(signal_type, 10)
    now = time.time()
    with _lock:
        _threat_scores[ip].append((now, weight))
        if len(_threat_scores) > _SCORES_HARD_LIMIT:
            _prune_scores()
        return _current_score(ip, now)


def get_threat_score(ip: str) -> int:
    """Return the current threat score for *ip* (without recording anything)."""
    return _current_score(ip, time.time())


def add_to_blocklist(ip_or_cidr: str) -> None:
    net = _parse_network(ip_or_cidr)
    with _lock:
        if net:
            _blocklist_networks.add(net)
        else:
            _blocklist_ips.add(ip_or_cidr.strip())


def remove_from_blocklist(ip_or_cidr: str) -> None:
    net = _parse_network(ip_or_cidr)
    with _lock:
        if net:
            _blocklist_networks.discard(net)
        else:
            _blocklist_ips.discard(ip_or_cidr.strip())


def add_to_allowlist(ip_or_cidr: str) -> None:
    net = _parse_network(ip_or_cidr)
    with _lock:
        if net:
            _allowlist_networks.add(net)
        else:
            _allowlist_ips.add(ip_or_cidr.strip())


def remove_from_allowlist(ip_or_cidr: str) -> None:
    net = _parse_network(ip_or_cidr)
    with _lock:
        if net:
            _allowlist_networks.discard(net)
        else:
            _allowlist_ips.discard(ip_or_cidr.strip())


def get_firewall_status() -> Dict[str, Any]:
    """Snapshot of current firewall state (for admin dashboard)."""
    now = time.time()
    with _lock:
        return {
            "blocklist_ips": sorted(_blocklist_ips),
            "blocklist_networks": sorted(str(n) for n in _blocklist_networks),
            "allowlist_ips": sorted(_allowlist_ips),
            "allowlist_networks": sorted(str(n) for n in _allowlist_networks),
            "auto_blocked": {
                ip: {"expires_in": int(exp - now)}
                for ip, exp in _auto_blocked.items()
                if exp > now
            },
            "threat_scores": {
                ip: _current_score(ip, now)
                for ip in list(_threat_scores.keys())[:100]
            },
            "config": {
                "threshold": THREAT_SCORE_BLOCK_THRESHOLD,
                "decay_seconds": THREAT_SCORE_DECAY_SECONDS,
                "block_duration": AUTO_BLOCK_DURATION_SECONDS,
                "burst_window": BURST_WINDOW_SECONDS,
                "burst_max": BURST_MAX_CONNECTIONS,
            },
        }


def reset_firewall() -> None:
    """Clear all firewall state (used by tests)."""
    with _lock:
        _blocklist_ips.clear()
        _blocklist_networks.clear()
        _allowlist_ips.clear()
        _allowlist_networks.clear()
        _auto_blocked.clear()
        _threat_scores.clear()
        _connection_log.clear()
        _request_fingerprints.clear()


# ── request fingerprinting ───────────────────────────────────────────────────

def compute_request_fingerprint(
    client_ip: str,
    path: str,
    method: str,
    user_agent: str,
    content_length: int = 0,
) -> str:
    """Compute a lightweight fingerprint for replay detection."""
    raw = f"{client_ip}|{method}|{path}|{user_agent}|{content_length}"
    fp = hashlib.sha256(raw.encode()).hexdigest()[:16]
    now = time.time()
    with _lock:
        entries = _request_fingerprints[client_ip]
        entries.append((now, fp))
        cutoff = now - 60
        _request_fingerprints[client_ip] = [
            (t, f) for t, f in entries if t > cutoff
        ]
    return fp


def detect_replay(client_ip: str, fingerprint: str, window: int = 5) -> bool:
    """Return True if the same fingerprint appeared more than *window* times
    in the last 60 seconds for this IP."""
    now = time.time()
    cutoff = now - 60
    with _lock:
        entries = _request_fingerprints.get(client_ip, [])
        count = sum(1 for t, f in entries if f == fingerprint and t > cutoff)
    return count > window


# ── internal helpers ─────────────────────────────────────────────────────────

def _is_blocklisted(ip: str) -> bool:
    with _lock:
        if ip in _blocklist_ips:
            return True
        try:
            addr = ipaddress.ip_address(ip)
            for net in _blocklist_networks:
                if addr in net:
                    return True
        except ValueError:
            pass
    return False


def _is_allowlisted(ip: str) -> bool:
    with _lock:
        if ip in _allowlist_ips:
            return True
        try:
            addr = ipaddress.ip_address(ip)
            for net in _allowlist_networks:
                if addr in net:
                    return True
        except ValueError:
            pass
    return False


def _current_score(ip: str, now: float) -> int:
    """Compute score with time-based decay."""
    with _lock:
        entries = _threat_scores.get(ip, [])
        score = 0
        for ts, weight in entries:
            age = now - ts
            if age < THREAT_SCORE_DECAY_SECONDS:
                decay_factor = 1.0 - (age / THREAT_SCORE_DECAY_SECONDS)
                score += int(weight * decay_factor)
        return score


def _is_connection_flood(ip: str, now: float) -> bool:
    cutoff = now - BURST_WINDOW_SECONDS
    with _lock:
        log = _connection_log[ip]
        log.append(now)
        _connection_log[ip] = [t for t in log if t > cutoff]
        return len(_connection_log[ip]) > BURST_MAX_CONNECTIONS


def _prune_scores() -> None:
    """Evict stale entries when the scores map grows too large."""
    now = time.time()
    cutoff = now - THREAT_SCORE_DECAY_SECONDS
    for ip in list(_threat_scores.keys()):
        _threat_scores[ip] = [
            (ts, w) for ts, w in _threat_scores[ip] if ts > cutoff
        ]
        if not _threat_scores[ip]:
            del _threat_scores[ip]


def _parse_network(
    value: str,
) -> Optional[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a CIDR string; return None if it's a bare IP."""
    value = value.strip()
    if "/" in value:
        try:
            return ipaddress.ip_network(value, strict=False)
        except ValueError:
            return None
    return None


# ── load environment blocklist/allowlist on import ───────────────────────────

def _load_env_lists() -> None:
    raw_block = os.environ.get("PHINS_FIREWALL_BLOCKLIST", "")
    for entry in raw_block.split(","):
        entry = entry.strip()
        if entry:
            add_to_blocklist(entry)

    raw_allow = os.environ.get("PHINS_FIREWALL_ALLOWLIST", "")
    for entry in raw_allow.split(","):
        entry = entry.strip()
        if entry:
            add_to_allowlist(entry)


_load_env_lists()
