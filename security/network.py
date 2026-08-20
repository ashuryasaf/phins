"""Network safety helpers for outbound requests."""

from __future__ import annotations

from typing import Iterable, Optional, Tuple, Union
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import ipaddress
import ssl


RequestLike = Union[str, Request]

# Cloud metadata / link-local endpoints that must never be used as
# operator-configured outbound LLM or transcription targets.
_BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.google.com",
    "169.254.169.254",
}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_LINK_LOCAL_V4 = ipaddress.ip_network("169.254.0.0/16")


def _extract_url(request_or_url: RequestLike) -> str:
    if isinstance(request_or_url, Request):
        return str(request_or_url.full_url)
    return str(request_or_url)


def _hostname_blocked(hostname: str) -> bool:
    host = (hostname or "").lower().strip("[]")
    if not host:
        return True
    if host in _BLOCKED_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host) in _LINK_LOCAL_V4
    except ValueError:
        return False


def outbound_http_allowed_schemes(url: str) -> Tuple[str, ...]:
    """HTTPS everywhere; HTTP only for explicit loopback operator endpoints."""
    hostname = (urlparse(str(url or "")).hostname or "").lower()
    if hostname in _LOOPBACK_HOSTS:
        return ("https", "http")
    return ("https",)


def validate_remote_url(
    request_or_url: RequestLike,
    *,
    allowed_schemes: Iterable[str] = ("https",),
    allowed_hosts: Optional[Iterable[str]] = None,
) -> str:
    """Validate an outbound URL before any network call is made."""
    url = _extract_url(request_or_url)
    parsed = urlparse(url)
    normalized_schemes = {scheme.lower() for scheme in allowed_schemes}

    if parsed.scheme.lower() not in normalized_schemes:
        raise ValueError(f"Disallowed URL scheme for outbound request: {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError("Outbound request URL must include a hostname")

    hostname = (parsed.hostname or "").lower()
    if _hostname_blocked(hostname):
        raise ValueError(f"Disallowed outbound host: {hostname}")

    if allowed_hosts is not None:
        normalized_hosts = {host.lower() for host in allowed_hosts}
        if hostname not in normalized_hosts:
            raise ValueError(f"Disallowed outbound host: {hostname}")

    return url


def assert_safe_provider_url(url: str) -> str:
    """Validate an operator-configured LLM/transcription endpoint."""
    return validate_remote_url(
        url,
        allowed_schemes=outbound_http_allowed_schemes(url),
    )


def validated_urlopen(
    request_or_url: RequestLike,
    *,
    timeout: float = 30.0,
    allowed_schemes: Iterable[str] = ("https",),
    allowed_hosts: Optional[Iterable[str]] = None,
    context: Optional[ssl.SSLContext] = None,
):
    """
    Open a validated URL.

    Bandit flags raw `urlopen` broadly, so we validate the scheme/host first and
    keep the actual open call isolated here.
    """
    validate_remote_url(
        request_or_url,
        allowed_schemes=allowed_schemes,
        allowed_hosts=allowed_hosts,
    )
    return urlopen(request_or_url, timeout=timeout, context=context)  # nosec B310
