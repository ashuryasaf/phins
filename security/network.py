"""Network safety helpers for outbound requests."""

from __future__ import annotations

from typing import Iterable, Optional, Union
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import ssl


RequestLike = Union[str, Request]


def _extract_url(request_or_url: RequestLike) -> str:
    if isinstance(request_or_url, Request):
        return str(request_or_url.full_url)
    return str(request_or_url)


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

    if allowed_hosts is not None:
        normalized_hosts = {host.lower() for host in allowed_hosts}
        hostname = (parsed.hostname or "").lower()
        if hostname not in normalized_hosts:
            raise ValueError(f"Disallowed outbound host: {hostname}")

    return url


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
