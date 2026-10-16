"""Founder portrait for the unified business plan.

The portrait is a media-library asset assigned to the ``founder_portrait_id``
design placement (admin media dashboard → "Business plan founder portrait").
:func:`process_portrait` turns the stored original (typically a phone JPEG
with an EXIF orientation tag) into the print-ready edition the plan shows:
EXIF-corrected, square-cropped with a head-room bias, resized, gently
contrast- and sharpness-balanced, and re-encoded as a progressive JPEG. The
original asset is never rewritten; the processed bytes are a derived view
keyed by the asset checksum and :data:`PORTRAIT_VERSION`.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Tuple

PORTRAIT_VERSION = 1
PORTRAIT_SIZE = 720
# Fraction of the spare height kept above the crop when the source is taller
# than wide: faces sit in the upper part of a portrait.
HEADROOM_BIAS = 0.22
JPEG_QUALITY = 88
MAX_SOURCE_BYTES = 40 * 1024 * 1024


class PortraitError(ValueError):
    """Raised when the stored asset cannot be processed as a portrait."""


def portrait_cache_key(asset_id: str, checksum: str) -> str:
    raw = f"{asset_id}|{checksum}|v{PORTRAIT_VERSION}|{PORTRAIT_SIZE}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def process_portrait(data: bytes, size: int = PORTRAIT_SIZE) -> Tuple[bytes, str]:
    """Return ``(jpeg_bytes, 'image/jpeg')`` for the processed portrait."""
    if not data:
        raise PortraitError("empty image payload")
    if len(data) > MAX_SOURCE_BYTES:
        raise PortraitError("image payload too large")
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError as exc:  # pragma: no cover - Pillow is a declared dependency
        raise PortraitError("Pillow is not installed") from exc

    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:
        raise PortraitError("payload is not a readable image") from exc

    img = ImageOps.exif_transpose(img) or img
    if img.mode not in ("RGB", "L"):
        # Flatten transparency onto white so a PNG logo-style file still prints.
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    w, h = img.size
    side = min(w, h)
    if side < 32:
        raise PortraitError("image too small for a portrait")
    left = (w - side) // 2
    top = int(round((h - side) * HEADROOM_BIAS)) if h > w else 0
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=0.5)
    img = ImageEnhance.Color(img).enhance(1.04)
    img = ImageEnhance.Sharpness(img).enhance(1.15)

    out = BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue(), "image/jpeg"


__all__ = ["HEADROOM_BIAS", "PORTRAIT_SIZE", "PORTRAIT_VERSION", "PortraitError",
           "portrait_cache_key", "process_portrait"]
