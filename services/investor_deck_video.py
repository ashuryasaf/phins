"""Investor-deck scenes for the media lab.

Part II of the unified plan (``deck_slides``) is the only script. Each bullet
is one scene. The spoken line is that bullet filled from the current plan;
a client cannot replace a figure. Charts and the founder portrait stay
outside the generator and are drawn from the plan when a clip is played.

A clip joins the film only when a library video exists, its checksum matches
the seal, and the sealed line is still the line the plan speaks now. A
missing scene is omitted. The plan, its factors, and public placements are
not written here.

The 13-slide presentation (``presentation_of``) is the same Part II, one
slide at a time. A library video combines with a slide only as a checksummed
pointer. A mismatch is omitted and the library file is not rewritten.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from typing import Any, Dict, List, Mapping, Optional, Sequence

from services.business_plan_document import (
    SLIDE_CHARTS,
    _PLACEHOLDER,
    _fill,
    deck_slides,
)

SCENE_SECONDS = 15
CAMPAIGN_PREFIX = "DECK-"
MAX_THEME_CHARS = 240
_ASSET_ID_RE_SOURCE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"

# Elegant on-camera roster. Sex, age, and appearance are varied so a full
# deck does not collapse to one presenter. The id is what gets stored.
PRESENTERS: tuple = (
    {"id": "p01", "sex": "woman", "age": "early 30s", "label": "Woman, early 30s",
     "appearance": "East Asian features, tailored navy suit, small gold earrings"},
    {"id": "p02", "sex": "man", "age": "mid 50s", "label": "Man, mid 50s",
     "appearance": "West African features, charcoal suit, silver tie"},
    {"id": "p03", "sex": "woman", "age": "early 40s", "label": "Woman, early 40s",
     "appearance": "Northern European features, ivory blouse and navy blazer"},
    {"id": "p04", "sex": "man", "age": "early 30s", "label": "Man, early 30s",
     "appearance": "South Asian features, navy suit, open collar"},
    {"id": "p05", "sex": "woman", "age": "late 20s", "label": "Woman, late 20s",
     "appearance": "Latina features, black blazer, soft studio light"},
    {"id": "p06", "sex": "man", "age": "early 60s", "label": "Man, early 60s",
     "appearance": "Middle Eastern features, grey suit, pocket square"},
    {"id": "p07", "sex": "woman", "age": "mid 40s", "label": "Woman, mid 40s",
     "appearance": "Black features, deep navy dress, small gold pin"},
    {"id": "p08", "sex": "man", "age": "late 30s", "label": "Man, late 30s",
     "appearance": "East Asian features, midnight-blue suit"},
    {"id": "p09", "sex": "woman", "age": "early 50s", "label": "Woman, early 50s",
     "appearance": "Mediterranean features, cream silk blouse and tailored jacket"},
    {"id": "p10", "sex": "man", "age": "early 40s", "label": "Man, early 40s",
     "appearance": "Latino features, navy suit, subtle gold tie bar"},
    {"id": "p11", "sex": "woman", "age": "late 30s", "label": "Woman, late 30s",
     "appearance": "mixed Black and East Asian features, charcoal suit"},
    {"id": "p12", "sex": "man", "age": "late 20s", "label": "Man, late 20s",
     "appearance": "Northern European features, light grey suit"},
)

# Engines whose own duration set includes a 15-second clip. Veo (8) and
# official Kling (10) are not in this list; the server still refuses any
# selection whose clip length is not exactly SCENE_SECONDS.
SCENE_ENGINES: tuple = (
    {
        "id": "replicate-seedance",
        "provider": "replicate",
        "model": "bytedance/seedance-2.0",
        "label": "Replicate · Seedance",
    },
    {
        "id": "kling-v3",
        "provider": "kling",
        "model": "kling-v3-text-to-video",
        "label": "Kling v3",
    },
)


class InvestorDeckError(ValueError):
    """A scene edit or send was rejected before any provider call."""


def scene_key(slide_no: int, paragraph_no: int) -> str:
    return f"s{int(slide_no):02d}p{int(paragraph_no):02d}"


def campaign_id_for(key: str) -> str:
    return f"{CAMPAIGN_PREFIX}{key}"


def parse_campaign_id(campaign_id: str) -> str:
    text = str(campaign_id or "").strip()
    if not text.startswith(CAMPAIGN_PREFIX):
        return ""
    key = text[len(CAMPAIGN_PREFIX):]
    return key if spec_for(key) is not None else ""


def presenter_by_id(presenter_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(presenter_id or "").strip()
    for item in PRESENTERS:
        if item["id"] == wanted:
            return dict(item)
    return None


def chart_ids() -> List[str]:
    """Chart ids the deck actually places, in slide order, once each."""
    seen = []
    for spec in catalog():
        chart_id = spec.get("chart_id") or ""
        if chart_id and chart_id not in seen:
            seen.append(chart_id)
    return seen


def catalog() -> List[Dict[str, Any]]:
    """One row per deck bullet. Templates are unfilled; figures are not baked in."""
    rows: List[Dict[str, Any]] = []
    for slide_no, slide in enumerate(deck_slides(), 1):
        bullets = list(slide.get("bullets") or [])
        chart_id = str(SLIDE_CHARTS.get(slide.get("title") or "") or "")
        photo = "founder" if slide.get("founder") else ""
        for paragraph_no, template in enumerate(bullets, 1):
            key = scene_key(slide_no, paragraph_no)
            rows.append({
                "scene_key": key,
                "slide_no": slide_no,
                "paragraph_no": paragraph_no,
                "paragraph_count": len(bullets),
                "slide_title": str(slide.get("title") or ""),
                "kicker": str(slide.get("kicker") or ""),
                "template": str(template),
                "chart_id": chart_id,
                "photo": photo,
                "campaign_id": campaign_id_for(key),
                "duration_seconds": SCENE_SECONDS,
            })
    return rows


def spec_for(key: str) -> Optional[Dict[str, Any]]:
    wanted = str(key or "").strip()
    for row in catalog():
        if row["scene_key"] == wanted:
            return dict(row)
    return None


def fill_narration(template: str, plan: Mapping[str, Any]) -> str:
    """The spoken line. Same filler as the document, so the words match the page."""
    return _fill(str(template or ""), plan, False).strip()


def _clean_theme(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvestorDeckError("Theme must be text")
    text = " ".join(value.replace("\x00", " ").split())
    if len(text) > MAX_THEME_CHARS:
        raise InvestorDeckError(f"Theme is limited to {MAX_THEME_CHARS} characters")
    return text


_ASSET_ID_RE = re.compile(_ASSET_ID_RE_SOURCE)


def _clean_asset_id(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvestorDeckError("Photo reference must be a media asset id")
    text = value.strip()
    if not text:
        return ""
    if not _ASSET_ID_RE.match(text):
        raise InvestorDeckError("Photo reference is not a media asset id")
    return text


def scene_checksum(record: Mapping[str, Any]) -> str:
    """Checksum of the sealed brief. Job ids and library asset ids are excluded."""
    material = {
        "scene_key": str(record.get("scene_key") or ""),
        "source_template": str(record.get("source_template") or ""),
        "presenter_id": str(record.get("presenter_id") or ""),
        "theme": str(record.get("theme") or ""),
        "reference_image_asset_id": str(record.get("reference_image_asset_id") or ""),
        "sealed_narration": str(record.get("sealed_narration") or ""),
        "sealed_plan_hash": str(record.get("sealed_plan_hash") or ""),
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verify_scene(record: Mapping[str, Any], spec: Optional[Mapping[str, Any]] = None) -> bool:
    if not isinstance(record, dict):
        return False
    key = str(record.get("scene_key") or "").strip()
    expected = spec if spec is not None else spec_for(key)
    if expected is None or expected.get("scene_key") != key:
        return False
    if str(record.get("source_template") or "") != str(expected.get("template") or ""):
        return False
    presenter_id = str(record.get("presenter_id") or "")
    if presenter_id and presenter_by_id(presenter_id) is None:
        return False
    campaign = str(record.get("campaign_id") or "")
    if campaign and campaign != campaign_id_for(key):
        return False
    digest = scene_checksum(record)
    stored = str(record.get("checksum") or "")
    if len(stored) != len(digest):
        return False
    return hmac.compare_digest(stored, digest)


def fresh_scene(spec: Mapping[str, Any]) -> Dict[str, Any]:
    key = str(spec["scene_key"])
    record = {
        "scene_key": key,
        "source_template": str(spec["template"]),
        "presenter_id": "",
        "theme": "",
        "reference_image_asset_id": "",
        "sealed_narration": "",
        "sealed_plan_hash": "",
        "sealed_plan_version": "",
        "campaign_id": campaign_id_for(key),
        "last_job_id": "",
        "last_asset_id": "",
        "asset_checksum": "",
        "stored": False,
    }
    record["checksum"] = scene_checksum(record)
    record["integrity_ok"] = True
    return record


def _copy_scene(spec: Mapping[str, Any], current: Mapping[str, Any]) -> Dict[str, Any]:
    base = fresh_scene(spec)
    for field in (
        "presenter_id", "theme", "reference_image_asset_id", "sealed_narration",
        "sealed_plan_hash", "sealed_plan_version", "last_job_id", "last_asset_id",
        "asset_checksum",
    ):
        base[field] = str(current.get(field) or "")
    return base


def apply_scene_edit(
    key: str,
    current: Optional[Mapping[str, Any]],
    *,
    theme: Any = None,
    reference_image_asset_id: Any = None,
    reset: bool = False,
) -> Dict[str, Any]:
    """Return a new checksummed scene. The bullet text is not client-writable."""
    spec = spec_for(key)
    if spec is None:
        raise InvestorDeckError(f"Unknown investor-deck scene: {key}")
    if reset:
        base = fresh_scene(spec)
        base["stored"] = True
        base["checksum"] = scene_checksum(base)
        base["integrity_ok"] = True
        return base
    if isinstance(current, dict) and current.get("stored") and not verify_scene(current, spec):
        raise InvestorDeckError("Scene checksum mismatch. Reset the scene before editing.")
    previous = str(current.get("checksum") or "") if isinstance(current, dict) and verify_scene(current, spec) else ""
    base = _copy_scene(spec, current) if isinstance(current, dict) else fresh_scene(spec)
    if theme is not None:
        base["theme"] = _clean_theme(theme)
    if reference_image_asset_id is not None:
        base["reference_image_asset_id"] = _clean_asset_id(reference_image_asset_id)
    base["stored"] = True
    base["checksum"] = scene_checksum(base)
    base["integrity_ok"] = True
    if previous and base["checksum"] != previous:
        # The filmed clip was sealed to the previous brief. Drop the link.
        # The library file stays; it is not rewritten.
        base["last_asset_id"] = ""
        base["asset_checksum"] = ""
        base["last_job_id"] = ""
    return base


def choose_presenter(
    used_ids: Sequence[str],
    rng: Any = None,
    *,
    exclude: str = "",
) -> Dict[str, Any]:
    """Pick an elegant presenter, spreading sex and preferring unused people."""
    chooser = rng if rng is not None else secrets.SystemRandom()
    counts = {item["id"]: 0 for item in PRESENTERS}
    sex_counts = {"woman": 0, "man": 0}
    for raw in used_ids:
        presenter = presenter_by_id(str(raw or ""))
        if presenter is None:
            continue
        counts[presenter["id"]] += 1
        sex_counts[presenter["sex"]] += 1
    least = min(counts.values()) if counts else 0
    pool = [dict(item) for item in PRESENTERS if counts[item["id"]] == least]
    if sex_counts["woman"] > sex_counts["man"]:
        preferred = [item for item in pool if item["sex"] == "man"]
    elif sex_counts["man"] > sex_counts["woman"]:
        preferred = [item for item in pool if item["sex"] == "woman"]
    else:
        preferred = []
    if preferred:
        pool = preferred
    skipped = str(exclude or "").strip()
    if skipped:
        narrowed = [item for item in pool if item["id"] != skipped]
        if narrowed:
            pool = narrowed
    if not pool:
        pool = [dict(item) for item in PRESENTERS]
    return dict(chooser.choice(pool))


def seal_for_send(
    key: str,
    current: Optional[Mapping[str, Any]],
    plan: Mapping[str, Any],
    *,
    used_presenter_ids: Sequence[str],
    rng: Any = None,
    reassign_presenter: bool = False,
    theme: Any = None,
    reference_image_asset_id: Any = None,
) -> Dict[str, Any]:
    """Seal the spoken line to this plan and assign a presenter once."""
    spec = spec_for(key)
    if spec is None:
        raise InvestorDeckError(f"Unknown investor-deck scene: {key}")
    if isinstance(current, dict) and current.get("stored") and not verify_scene(current, spec):
        raise InvestorDeckError("Scene checksum mismatch. Reset the scene before sending.")
    record = apply_scene_edit(
        key,
        current if isinstance(current, dict) else None,
        theme=theme,
        reference_image_asset_id=reference_image_asset_id,
    )
    narration = fill_narration(spec["template"], plan)
    if not narration or _PLACEHOLDER.findall(narration):
        raise InvestorDeckError("This paragraph could not be filled from the plan. Nothing was sent.")
    plan_hash = str(plan.get("content_hash") or "")
    if not plan_hash:
        raise InvestorDeckError("The plan has no content hash. Nothing was sent.")
    integrity = plan.get("integrity") if isinstance(plan.get("integrity"), dict) else {}
    if integrity.get("all_hold") is not True:
        raise InvestorDeckError("Plan identities do not hold. Nothing was sent.")
    current_presenter = str(record.get("presenter_id") or "")
    if reassign_presenter or not current_presenter:
        chosen = choose_presenter(
            list(used_presenter_ids),
            rng,
            exclude=current_presenter if reassign_presenter else "",
        )
        record["presenter_id"] = chosen["id"]
    elif presenter_by_id(current_presenter) is None:
        raise InvestorDeckError("Stored presenter is not in the roster. Reset the scene before sending.")
    previous_narration = str(record.get("sealed_narration") or "")
    previous_presenter = current_presenter
    record["sealed_narration"] = narration
    record["sealed_plan_hash"] = plan_hash
    record["sealed_plan_version"] = str(plan.get("plan_version") or "")
    record["checksum"] = scene_checksum(record)
    record["integrity_ok"] = True
    record["stored"] = True
    # The whole-plan content hash moves when any slide or census figure
    # changes. That alone does not retire a clip whose spoken line and
    # presenter are unchanged; clearing the link here would persist an empty
    # asset before an identical job is reused, and that job would not reattach.
    if (
        previous_narration != narration
        or previous_presenter != record["presenter_id"]
    ):
        record["last_asset_id"] = ""
        record["asset_checksum"] = ""
        record["last_job_id"] = ""
        record["checksum"] = scene_checksum(record)
    return record


def growth_brief(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Brief shape consumed by ``build_media_video_prompt``."""
    narration = str(record.get("sealed_narration") or "").strip()
    theme = str(record.get("theme") or "").strip()
    storyboard = [narration] if narration else []
    if theme:
        storyboard.append(f"Theme: {theme}")
    return {
        "title": f"Investor deck {record.get('scene_key') or ''}",
        "format": "16:9 investor presentation",
        "voiceover_style": "Elegant business presenter, one spoken pass, picture free of lettering and charts",
        "storyboard": storyboard,
        "scene_key": str(record.get("scene_key") or ""),
    }


def prompt_override(record: Mapping[str, Any]) -> str:
    """Presenter direction. The quoted line is the sealed paragraph in full."""
    narration = str(record.get("sealed_narration") or "").strip()
    theme = str(record.get("theme") or "").strip()
    reference = str(record.get("reference_image_asset_id") or "").strip()
    presenter = presenter_by_id(str(record.get("presenter_id") or "")) or {}
    appearance = str(presenter.get("appearance") or "a professional presenter in business attire")
    age = str(presenter.get("age") or "")
    sex = str(presenter.get("sex") or "")
    casting = appearance
    if sex or age:
        casting = f"{appearance}; {sex}, {age}".strip("; ")
    parts = [
        "Investor presentation, 16:9.",
        f"One elegant presenter ({casting}), medium close-up, calm private office, looking at the camera.",
        "The frame contains no readable text, charts, tables, or numerals.",
        "Figures are spoken only. Do not draw a chart and do not render a number on screen.",
        "Do not depict a named real person. A portrait, when this slide has one, is shown beside the film.",
    ]
    if reference:
        parts.append("Use the supplied photo only as the setting. Do not reproduce writing from it.")
    if theme:
        parts.append(f"Descriptive theme, unspoken: {theme}.")
    if narration:
        parts.append(
            "The presenter speaks this line once, in a clear calm voice, and finishes on its final period. "
            f'Do not stop mid-word or mid-sentence: "{narration}"'
        )
    return " ".join(parts)


def engine_by_id(engine_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(engine_id or "").strip()
    for item in SCENE_ENGINES:
        if item["id"] == wanted:
            return dict(item)
    return None


def clip_is_scene_length(provider: str, model: str, *, evolink: bool = False) -> int:
    """Return SCENE_SECONDS, or 0 when this engine cannot hold a 15-second clip."""
    from services.media_generation_service import MediaGenerationService

    seconds = MediaGenerationService.clip_duration(
        provider, model, SCENE_SECONDS, evolink=evolink,
    )
    return SCENE_SECONDS if int(seconds) == SCENE_SECONDS else 0


def scene_view(
    spec: Mapping[str, Any],
    stored: Optional[Mapping[str, Any]],
    plan: Mapping[str, Any],
    asset: Optional[Mapping[str, Any]] = None,
    *,
    photo_url: str = "",
    reference_url: str = "",
) -> Dict[str, Any]:
    """One paragraph as the lab and the pitch page show it."""
    key = str(spec["scene_key"])
    record = dict(stored) if isinstance(stored, dict) else None
    integrity_ok = True
    if record is None:
        record = fresh_scene(spec)
    elif not verify_scene(record, spec):
        integrity_ok = False
    narration = fill_narration(str(spec["template"]), plan)
    sealed = str(record.get("sealed_narration") or "")
    # The whole-plan content hash changes when any slide or census figure
    # changes. A clip stays current while its sealed line is still this
    # paragraph; narration equality is that check.
    figures_current = bool(sealed) and sealed == narration
    presenter = presenter_by_id(str(record.get("presenter_id") or ""))
    asset_info = asset if isinstance(asset, dict) else {}
    asset_type = str(asset_info.get("type") or "")
    asset_checksum = str(asset_info.get("checksum") or "")
    stored_checksum = str(record.get("asset_checksum") or "")
    playback = str(asset_info.get("playback_url") or "")
    checksum_ok = bool(stored_checksum) and stored_checksum == asset_checksum and asset_type == "video"
    in_stream = bool(
        integrity_ok
        and figures_current
        and checksum_ok
        and playback
        and str(record.get("last_asset_id") or "")
    )
    photo = str(spec.get("photo") or "")
    return {
        "scene_key": key,
        "slide_no": spec["slide_no"],
        "paragraph_no": spec["paragraph_no"],
        "paragraph_count": spec["paragraph_count"],
        "slide_title": spec["slide_title"],
        "kicker": spec.get("kicker") or "",
        "narration": narration,
        "sealed_narration": sealed,
        "chart_id": spec.get("chart_id") or "",
        "photo": photo,
        "photo_url": photo_url if photo == "founder" else "",
        "reference_image_asset_id": str(record.get("reference_image_asset_id") or ""),
        "reference_url": reference_url,
        "theme": str(record.get("theme") or ""),
        "presenter_id": str(record.get("presenter_id") or ""),
        "presenter_label": str((presenter or {}).get("label") or ""),
        "presenter_appearance": str((presenter or {}).get("appearance") or ""),
        "campaign_id": campaign_id_for(key),
        "duration_seconds": SCENE_SECONDS,
        "stored": bool(record.get("stored")),
        "integrity_ok": integrity_ok,
        "figures_current": figures_current,
        "sealed_plan_hash": str(record.get("sealed_plan_hash") or ""),
        "sealed_plan_version": str(record.get("sealed_plan_version") or ""),
        "last_job_id": str(record.get("last_job_id") or ""),
        "last_asset_id": str(record.get("last_asset_id") or ""),
        "playback_url": playback if in_stream else "",
        "in_stream": in_stream,
        "checksum": str(record.get("checksum") or ""),
    }


def stream_of(scenes: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Filmed scenes in deck order. A scene without a current clip is omitted."""
    ordered = sorted(
        (dict(scene) for scene in scenes if scene.get("in_stream")),
        key=lambda scene: (int(scene.get("slide_no") or 0), int(scene.get("paragraph_no") or 0)),
    )
    return ordered


def slide_specs() -> List[Dict[str, Any]]:
    """One row per Part II slide. Bullet templates stay unfilled."""
    rows: List[Dict[str, Any]] = []
    for slide_no, slide in enumerate(deck_slides(), 1):
        title = str(slide.get("title") or "")
        rows.append({
            "slide_no": slide_no,
            "title": title,
            "kicker": str(slide.get("kicker") or ""),
            "bullets": [str(item) for item in (slide.get("bullets") or [])],
            "chart_id": str(SLIDE_CHARTS.get(title) or ""),
            "photo": "founder" if slide.get("founder") else "",
        })
    return rows


def slide_spec(slide_no: int) -> Optional[Dict[str, Any]]:
    try:
        number = int(slide_no)
    except (TypeError, ValueError):
        return None
    for row in slide_specs():
        if row["slide_no"] == number:
            return dict(row)
    return None


def parse_slide_no(value: Any) -> int:
    """Slide numbers are 1-based positions in Part II."""
    if isinstance(value, bool) or value is None:
        raise InvestorDeckError("Unknown investor-deck slide")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        raise InvestorDeckError("Unknown investor-deck slide")
    if slide_spec(number) is None:
        raise InvestorDeckError(f"Unknown investor-deck slide: {number}")
    return number


def media_assignment_checksum(record: Mapping[str, Any]) -> str:
    """Checksum of the slide-to-video pointer. Library bytes are not included."""
    try:
        slide_no = int(record.get("slide_no") or 0)
    except (TypeError, ValueError):
        slide_no = 0
    material = {
        "slide_no": slide_no,
        "asset_id": str(record.get("asset_id") or ""),
        "asset_checksum": str(record.get("asset_checksum") or ""),
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verify_media_assignment(record: Mapping[str, Any], slide_no: int) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        recorded = int(record.get("slide_no"))
    except (TypeError, ValueError):
        return False
    if recorded != int(slide_no) or slide_spec(slide_no) is None:
        return False
    digest = media_assignment_checksum(record)
    stored = str(record.get("checksum") or "")
    if not stored or len(stored) != len(digest):
        return False
    return hmac.compare_digest(stored, digest)


def assign_slide_media(slide_no: Any, asset_id: Any, asset_checksum: Any) -> Dict[str, Any]:
    """Seal a library video to one slide. The file itself is not copied."""
    number = parse_slide_no(slide_no)
    cleaned = _clean_asset_id(asset_id)
    if not cleaned:
        raise InvestorDeckError("Choose a video from the media library")
    checksum = str(asset_checksum or "").strip()
    if not checksum or any(ch.isspace() for ch in checksum) or len(checksum) > 128:
        raise InvestorDeckError("Media video has no checksum")
    record = {
        "slide_no": number,
        "asset_id": cleaned,
        "asset_checksum": checksum,
    }
    record["checksum"] = media_assignment_checksum(record)
    return record


def _assignment_for(assignments: Optional[Mapping[str, Any]], slide_no: int) -> Optional[Dict[str, Any]]:
    if not isinstance(assignments, Mapping):
        return None
    for key in (str(slide_no), slide_no):
        record = assignments.get(key)
        if isinstance(record, dict):
            return record
    return None


def _chart_svg(charts: Optional[Mapping[str, Any]], chart_id: str) -> str:
    if not chart_id or not isinstance(charts, Mapping):
        return ""
    spec = charts.get(chart_id)
    svg = ""
    if isinstance(spec, str):
        svg = spec
    elif isinstance(spec, dict):
        svg = str(spec.get("svg") or "")
    if "<svg" not in svg[:400] and not svg.lstrip().startswith("<svg"):
        return ""
    return svg


def _filmed_for_slide(slide_no: int, filmed: Optional[Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in filmed or []:
        if not isinstance(item, dict) or not item.get("in_stream"):
            continue
        try:
            number = int(item.get("slide_no") or 0)
            paragraph_no = int(item.get("paragraph_no") or 0)
        except (TypeError, ValueError):
            continue
        playback = str(item.get("playback_url") or "")
        if number != slide_no or not playback:
            continue
        rows.append({
            "paragraph_no": paragraph_no,
            "narration": str(item.get("narration") or ""),
            "playback_url": playback,
            "presenter_label": str(item.get("presenter_label") or ""),
        })
    rows.sort(key=lambda row: row["paragraph_no"])
    return rows


def _combined_media(
    slide_no: int,
    assignment: Optional[Mapping[str, Any]],
    assets: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Play a library video only when the pointer and the file still match."""
    empty = {
        "asset_id": "",
        "playback_url": "",
        "name": "",
        "intact": False,
        "withheld": False,
    }
    if not isinstance(assignment, dict):
        return empty
    asset_id = str(assignment.get("asset_id") or "")
    if not asset_id:
        return empty
    if not verify_media_assignment(assignment, slide_no):
        return dict(empty, withheld=True)
    asset = assets.get(asset_id) if isinstance(assets, Mapping) else None
    info = asset if isinstance(asset, dict) else {}
    sealed = str(assignment.get("asset_checksum") or "")
    actual = str(info.get("checksum") or "").strip()
    kind = str(info.get("type") or "")
    playback = str(info.get("playback_url") or info.get("url") or "")
    if sealed and sealed == actual and kind == "video" and playback:
        return {
            "asset_id": asset_id,
            "playback_url": playback,
            "name": str(info.get("name") or ""),
            "intact": True,
            "withheld": False,
        }
    return dict(empty, withheld=True)


def presentation_of(
    plan: Mapping[str, Any],
    assignments: Optional[Mapping[str, Any]] = None,
    assets: Optional[Mapping[str, Any]] = None,
    filmed: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    photo_url: str = "",
    charts: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Part II as slides. Figures are filled here and nowhere written back."""
    slides: List[Dict[str, Any]] = []
    for spec in slide_specs():
        number = int(spec["slide_no"])
        photo = str(spec.get("photo") or "")
        chart_id = str(spec.get("chart_id") or "")
        slides.append({
            "slide_no": number,
            "title": str(spec.get("title") or ""),
            "kicker": fill_narration(str(spec.get("kicker") or ""), plan),
            "bullets": [fill_narration(bullet, plan) for bullet in spec.get("bullets") or []],
            "chart_id": chart_id,
            "chart_svg": _chart_svg(charts, chart_id),
            "photo": photo,
            "photo_url": photo_url if photo == "founder" else "",
            "media": _combined_media(number, _assignment_for(assignments, number), assets),
            "filmed": _filmed_for_slide(number, filmed),
        })
    return {
        "part": "II",
        "slide_count": len(slides),
        "slides": slides,
    }
