"""Slideshow chrome for the investor deck.

This is separate from the scene generator. A slide's look is a checksummed
pointer: theme words, a gradient, a transparency wash, and at most one
embedded library image. Figures are filled by the plan and are not stored
here. A checksum mismatch withholds the look. The library file is not rewritten.

The same pointer shape is what landing, solutions, and login use for a
placement: an asset id of the right type, sealed to the checksum the library
holds now.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Mapping, Optional

from services.investor_deck_video import (
    InvestorDeckError,
    _clean_asset_id,
    parse_slide_no,
)

GRADIENTS = ("letterhead", "soft", "deep", "none")
WASH_MIN = 0.35
WASH_MAX = 0.85
WASH_DEFAULT = 0.58
MAX_THEME_CHARS = 80


def parse_gradient(value: Any, default: str = "letterhead") -> str:
    if value is None or value == "":
        text = default
    else:
        text = str(value).strip().lower()
    if text not in GRADIENTS:
        raise InvestorDeckError("Unknown slide gradient")
    return text


def parse_wash(value: Any, default: float = WASH_DEFAULT) -> str:
    """Return the wash as a two-decimal string so the seal does not drift."""
    if value is None or value == "":
        number = float(default)
    else:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise InvestorDeckError("Transparency must be a number") from exc
    if number < WASH_MIN or number > WASH_MAX:
        raise InvestorDeckError("Transparency must stay between 0.35 and 0.85")
    return f"{number:.2f}"


def clean_slide_theme(value: Any) -> str:
    """Theme words for one slide. A digit would look like a plan figure."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvestorDeckError("Theme must be text")
    text = " ".join(value.replace("\x00", " ").split())
    if len(text) > MAX_THEME_CHARS:
        raise InvestorDeckError(f"A slide theme is limited to {MAX_THEME_CHARS} characters")
    if any(ch.isdigit() for ch in text) or "{" in text or "}" in text:
        raise InvestorDeckError("A slide theme cannot carry a figure")
    return text


def chrome_checksum(record: Mapping[str, Any]) -> str:
    """Checksum of the look. Library bytes and timestamps are not included."""
    try:
        slide_no = int(record.get("slide_no") or 0)
    except (TypeError, ValueError):
        slide_no = 0
    material = {
        "slide_no": slide_no,
        "theme": str(record.get("theme") or ""),
        "gradient": str(record.get("gradient") or ""),
        "wash": str(record.get("wash") or ""),
        "image_asset_id": str(record.get("image_asset_id") or ""),
        "image_checksum": str(record.get("image_checksum") or ""),
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verify_chrome(record: Mapping[str, Any], slide_no: int) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        recorded = int(record.get("slide_no"))
    except (TypeError, ValueError):
        return False
    if recorded != int(slide_no):
        return False
    if str(record.get("gradient") or "") not in GRADIENTS:
        return False
    digest = chrome_checksum(record)
    stored = str(record.get("checksum") or "")
    if not stored or len(stored) != len(digest):
        return False
    return hmac.compare_digest(stored, digest)


def assign_chrome(
    slide_no: Any,
    *,
    theme: Any = "",
    gradient: Any = "letterhead",
    wash: Any = None,
    image_asset_id: Any = "",
    image_checksum: Any = "",
) -> Dict[str, Any]:
    """Seal one slide's look. The image file is not copied."""
    number = parse_slide_no(slide_no)
    image_id = _clean_asset_id(image_asset_id) if image_asset_id else ""
    checksum = str(image_checksum or "").strip()
    if image_id:
        if not checksum or any(ch.isspace() for ch in checksum) or len(checksum) > 128:
            raise InvestorDeckError("Media image has no checksum")
    else:
        checksum = ""
    record = {
        "slide_no": number,
        "theme": clean_slide_theme(theme),
        "gradient": parse_gradient(gradient),
        "wash": parse_wash(wash),
        "image_asset_id": image_id,
        "image_checksum": checksum,
    }
    record["checksum"] = chrome_checksum(record)
    return record


def _image_view(
    asset_id: str,
    sealed_checksum: str,
    assets: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    empty = {
        "asset_id": "",
        "playback_url": "",
        "name": "",
        "intact": False,
        "withheld": False,
    }
    if not asset_id:
        return empty
    info = assets.get(asset_id) if isinstance(assets, Mapping) else None
    info = info if isinstance(info, dict) else {}
    actual = str(info.get("checksum") or "").strip()
    kind = str(info.get("type") or "")
    playback = str(info.get("playback_url") or info.get("url") or "")
    if sealed_checksum and sealed_checksum == actual and kind == "image" and playback:
        return {
            "asset_id": asset_id,
            "playback_url": playback,
            "name": str(info.get("name") or ""),
            "intact": True,
            "withheld": False,
        }
    return {
        "asset_id": asset_id,
        "playback_url": "",
        "name": str(info.get("name") or ""),
        "intact": False,
        "withheld": True,
    }


def chrome_view(
    slide_no: int,
    record: Optional[Mapping[str, Any]],
    assets: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The look to paint. A broken seal is not applied."""
    plain = {
        "theme": "",
        "gradient": "letterhead",
        "wash": WASH_DEFAULT,
        "image": _image_view("", "", assets),
        "intact": False,
        "withheld": False,
    }
    if not isinstance(record, dict) or not record.get("checksum"):
        return plain
    if not verify_chrome(record, slide_no):
        return dict(plain, withheld=True)
    image = _image_view(
        str(record.get("image_asset_id") or ""),
        str(record.get("image_checksum") or ""),
        assets,
    )
    try:
        wash = float(record.get("wash"))
    except (TypeError, ValueError):
        wash = WASH_DEFAULT
    return {
        "theme": str(record.get("theme") or ""),
        "gradient": str(record.get("gradient") or "letterhead"),
        "wash": wash,
        "image": image,
        "intact": True,
        "withheld": bool(image.get("withheld")),
    }


def decorate_presentation(
    view: Mapping[str, Any],
    chrome_store: Optional[Mapping[str, Any]],
    assets: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach each slide's look. Slide figures are copied through unchanged."""
    slides = []
    store = chrome_store if isinstance(chrome_store, Mapping) else {}
    for slide in view.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        row = dict(slide)
        bullets = list(slide.get("bullets") or [])
        row["bullets"] = bullets
        try:
            number = int(slide.get("slide_no") or 0)
        except (TypeError, ValueError):
            number = 0
        record = None
        for key in (str(number), number):
            found = store.get(key)
            if isinstance(found, dict):
                record = found
                break
        row["chrome"] = chrome_view(number, record, assets)
        slides.append(row)
    out = dict(view)
    out["slides"] = slides
    return out
