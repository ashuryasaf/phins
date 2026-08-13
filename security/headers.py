"""HTTP security headers for the PHINS portal.

Centralises the headers emitted on every response so we can update the policy
in one place and exercise it from tests. The helpers return header pairs
instead of writing to ``self`` directly because the portal's request handler
already owns the lifecycle of ``send_header`` calls.
"""

from __future__ import annotations

from typing import Iterable, Tuple


JSON_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: https://api.qrserver.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

# Static HTML still depends on inline handlers in legacy pages. Tightening this
# beyond 'unsafe-inline' requires the migration work tracked in
# ``SECURITY_ENHANCEMENTS.md``; in the meantime we still block plugins,
# frame-ancestors, and mixed content.
HTML_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
    "https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
    "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net "
    "https://cdnjs.cloudflare.com; "
    "img-src 'self' data: blob: https://api.qrserver.com; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "upgrade-insecure-requests"
)

# ``Permissions-Policy`` explicitly turns off browser features the portal does
# not use; this limits blast radius of any XSS by denying access to sensors,
# payment APIs, camera, etc. ``microphone=(self)`` stays enabled for the
# same-origin voice assistants (Admin AI Mic, customer AI assistant, floating
# voice quick actions) — ``microphone=()`` made every SpeechRecognition /
# getUserMedia call fail with "not-allowed" regardless of user consent.
PERMISSIONS_POLICY = (
    "accelerometer=(), "
    "autoplay=(), "
    "camera=(), "
    "cross-origin-isolated=(), "
    "display-capture=(), "
    "encrypted-media=(), "
    "fullscreen=(self), "
    "geolocation=(), "
    "gyroscope=(), "
    "keyboard-map=(), "
    "magnetometer=(), "
    "microphone=(self), "
    "midi=(), "
    "payment=(), "
    "picture-in-picture=(), "
    "publickey-credentials-get=(self), "
    "screen-wake-lock=(), "
    "sync-xhr=(), "
    "usb=(), "
    "xr-spatial-tracking=()"
)


def common_security_headers() -> Iterable[Tuple[str, str]]:
    """Headers applied on every response regardless of content type."""
    yield "X-Content-Type-Options", "nosniff"
    yield "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    yield "Referrer-Policy", "strict-origin-when-cross-origin"
    yield "Permissions-Policy", PERMISSIONS_POLICY
    yield "Cross-Origin-Opener-Policy", "same-origin"
    yield "Cross-Origin-Resource-Policy", "same-origin"
    yield "X-Permitted-Cross-Domain-Policies", "none"


def json_security_headers() -> Iterable[Tuple[str, str]]:
    """Headers for JSON API responses (stricter CSP, deny framing)."""
    for name, value in common_security_headers():
        yield name, value
    yield "X-Frame-Options", "DENY"
    yield "X-XSS-Protection", "1; mode=block"
    yield "Content-Security-Policy", JSON_CSP
    yield "Cache-Control", "no-store"


def html_security_headers() -> Iterable[Tuple[str, str]]:
    """Headers for HTML responses (allow same-origin framing for legacy UIs)."""
    for name, value in common_security_headers():
        yield name, value
    yield "X-Frame-Options", "SAMEORIGIN"
    yield "X-XSS-Protection", "1; mode=block"
    yield "Content-Security-Policy", HTML_CSP


def static_asset_security_headers() -> Iterable[Tuple[str, str]]:
    """Headers for static CSS/JS/images."""
    yield "X-Content-Type-Options", "nosniff"
    yield "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    yield "Referrer-Policy", "strict-origin-when-cross-origin"
    yield "Cross-Origin-Resource-Policy", "same-origin"
