"""Adjustable video blueprints for the public solution walkthroughs.

Each blueprint is affiliated with one solution on ``/solutions.html``.
The narration starts from that solution's "Inside the Solution" lines and
can be edited, given a descriptive theme, and pointed at a library image
used as a screenshot reference. The signed marketing campaign is not
modified. Sending a blueprint builds the same growth-agent video brief the
media dashboard already submits, and the finished file is a media-library
asset. Public theater slots are never written here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Dict, List, Optional

MAX_NARRATION_CHARS = 800
MAX_THEME_CHARS = 240
_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_CAMPAIGN_PREFIX = "SOL-"
_JOIN_CAMPAIGN_PREFIX = "JOIN-"

# Canonical public outline. Keys match ``data-preview`` / theater slots.
# Editing a blueprint copies these lines; it does not rewrite the page.
SOLUTION_OUTLINES: Dict[str, Dict[str, Any]] = {
    "underwriting": {
        "title": "AI-Assisted Underwriting",
        "group": "lifecycle",
        "bullets": [
            "Guided digital application intake feeding a live underwriting pipeline",
            "AI-assisted risk evaluation aware of demographics and policy terms",
            "An underwriter decision workbench — approval authority stays human",
            "Premium pricing connected to actuarial parameters at the point of decision",
        ],
    },
    "assessments": {
        "title": "Assessment Center",
        "group": "lifecycle",
        "bullets": [
            "360° customer view assembled from imported facts and documents",
            "Risk-level classification feeding underwriting and servicing decisions",
            "Assessment records that keep every decision loop auditable",
        ],
    },
    "media": {
        "title": "Media Library",
        "group": "lifecycle",
        "bullets": [
            "One library for the videos and images the platform presents",
            "Hero films, disclosures and solution walkthroughs chosen from that library",
            "Swapping a film leaves policies, billing and inquiries unchanged",
        ],
    },
    "billing": {
        "title": "Billing & Payments",
        "group": "lifecycle",
        "bullets": [
            "Premium billing engine aligned with the accounting ledger",
            "Flexible payment methods with monthly auto-pay scheduling",
            "Reconciliation designed so every charge stays traceable",
        ],
    },
    "claims": {
        "title": "Claims Management",
        "group": "lifecycle",
        "bullets": [
            "Structured claims intake with integrated document handling",
            "Adjuster dashboards for review and adjudication",
            "Settlement approval flow with clear separation of duties",
        ],
    },
    "actuarial_investments": {
        "title": "Actuarial & Investments",
        "group": "lifecycle",
        "bullets": [
            "Actuarial tables, reserve forecasting and portfolio simulations",
            "Pricing parameters managed as first-class platform data",
            "Savings and investment allocation connected to coverage",
        ],
    },
    "platform": {
        "title": "Trust, Security & Auditability",
        "group": "lifecycle",
        "bullets": [
            "Role-scoped access across every operations desk",
            "Layered network and request defenses",
            "Tamper-evident event trails built for examination",
        ],
    },
    "smart_contracts": {
        "title": "Smart Contracts Development",
        "group": "crown",
        "bullets": [
            "Ledger-anchored agreements for insurance and marketplace flows",
            "Verifiable signatures and settlement events on tamper-evident rails",
            "Entitlements recorded as first-class platform outcomes",
        ],
    },
    "mga_solutions": {
        "title": "MGA Solutions",
        "group": "crown",
        "bullets": [
            "Distribution and program operations in one working layer",
            "Underwriting authority coordinated with partner ecosystems",
            "Supplier and agent networks orchestrated from a single platform",
        ],
    },
    "actuarial_force": {
        "title": "Actuarial Force",
        "group": "crown",
        "bullets": [
            "Pricing, reserve forecasts and simulations as platform citizens",
            "Capital views connected to coverage and portfolio performance",
            "Working depth reserved for qualified conversations",
        ],
    },
    "deep_research": {
        "title": "Deep Research Strategy",
        "group": "crown",
        "bullets": [
            "The LTC residential strategy bar is the public view of the desk",
            "Private institutions, public institutions and home care in one place",
            "The research method is reserved for qualified conversations",
        ],
    },
    "regulation": {
        "title": "Regulation Dashboard",
        "group": "crown",
        "bullets": [
            "A read-only outline built for regulatory oversight",
            "Sections spanning underwriting, claims, investments, health, billing and agents",
            "A direct question path for one outlined subject at a time",
        ],
    },
    "individuals": {
        "title": "For Individuals",
        "group": "audience",
        "bullets": [
            "A health wallet for consultations, devices and daily care",
            "A self-service client portal for policies, claims and documents",
            "Transparent billing with flexible payment and auto-pay options",
            "Savings and investment allocation connected to your coverage",
            "AI-assisted guidance across application and servicing journeys",
        ],
    },
    "enterprises": {
        "title": "For Enterprises & Partners",
        "group": "audience",
        "bullets": [
            "Role-based operations desks: underwriting, claims, billing, actuary, accounting",
            "MGA and program-partner tooling with supplier and agent ecosystems",
            "BI analytics and portfolio views for management and oversight",
            "Audit-ready event trails and security controls across every workflow",
        ],
    },
}

SOLUTION_KEYS = tuple(SOLUTION_OUTLINES.keys())

# Customer intro films on /join.html. Kept out of SOLUTION_KEYS so the
# public solutions page and its SOL- campaigns stay a separate catalog.
JOIN_INTRO_OUTLINES: Dict[str, Dict[str, Any]] = {
    "welcome": {
        "title": "Welcome to PHINS",
        "group": "join",
        "bullets": [
            "PHINS connects customers, agents, and suppliers in one ecosystem",
            "An invitation opens the insurance contract, the wallets, and the professional desks",
            "One acquisition settlement stays blocked until the hold ends and the invited customer is still paying",
        ],
    },
    "insurance": {
        "title": "Unified contract",
        "group": "join",
        "bullets": [
            "The unified insurance contract is opened in a guided chat",
            "The invitation code travels with that application",
            "Underwriting, billing, and the policy record stay on their existing path",
        ],
    },
    "health_wallet": {
        "title": "Health wallet",
        "group": "join",
        "bullets": [
            "The health wallet pays for consultations, devices, and daily care",
            "An invitation code is carried into account opening",
            "A released reward can be accepted into this wallet when that layer allows it",
        ],
    },
    "investments": {
        "title": "Investments",
        "group": "join",
        "bullets": [
            "Savings and investments sit beside the coverage",
            "An invitation code is carried into account opening",
            "A released reward can be directed into long-term savings when that layer allows it",
        ],
    },
    "credit": {
        "title": "Credit and wallets",
        "group": "join",
        "bullets": [
            "Premium credit and the wallet split are chosen when a reward is released",
            "The split follows the layer set by an admin",
            "The acquisition expense is booked once, at allocation",
        ],
    },
    "agent": {
        "title": "Agent desk",
        "group": "join",
        "bullets": [
            "A customer can request the agent desk from the referral page",
            "Approval opens the agent tools and a larger invitation cap",
            "Agent invitation codes stay on the commission rail",
        ],
    },
    "supplier": {
        "title": "Supplier desk",
        "group": "join",
        "bullets": [
            "A customer can request the supplier desk from the same referral page",
            "Approval opens the supplier profile beside the customer account",
            "Supplier invitations keep their own registration link",
        ],
    },
    "claims_chat": {
        "title": "Claims chat",
        "group": "join",
        "bullets": [
            "A claim opens in chat at the public claims desk",
            "The invitation code stays on that link",
            "The claim record follows the existing claims path",
        ],
    },
}

# Adjustable generator order for customer-intro films. The id is the only
# value an admin can store. Provider and model are looked up here.
JOIN_INTRO_ENGINES: tuple = (
    {
        "id": "replicate-veo",
        "provider": "replicate",
        "model": "google/veo-3.1-fast",
        "label": "Replicate · Veo",
    },
    {
        "id": "replicate-seedance",
        "provider": "replicate",
        "model": "bytedance/seedance-2.0",
        "label": "Replicate · Seedance",
    },
    {
        "id": "kling",
        "provider": "kling",
        "model": "kling-v2.6-pro",
        "label": "Kling",
    },
    {
        "id": "gemini-veo",
        "provider": "gemini",
        "model": "veo-3.1-generate-preview",
        "label": "Gemini · Veo",
    },
)
JOIN_INTRO_ENGINE_IDS = tuple(item["id"] for item in JOIN_INTRO_ENGINES)

JOIN_INTRO_KEYS = tuple(JOIN_INTRO_OUTLINES.keys())


class SolutionBlueprintError(ValueError):
    """A blueprint edit or send was rejected before any provider call."""


def outline_for(solution_key: str) -> Optional[Dict[str, Any]]:
    """Canonical outline for a solution walkthrough or a customer-intro film."""
    key = str(solution_key or "").strip()
    if key in SOLUTION_OUTLINES:
        return SOLUTION_OUTLINES[key]
    return JOIN_INTRO_OUTLINES.get(key)


def is_join_intro_key(solution_key: str) -> bool:
    return str(solution_key or "").strip() in JOIN_INTRO_OUTLINES


def engine_by_id(engine_id: str) -> Optional[Dict[str, Any]]:
    key = str(engine_id or "").strip()
    for item in JOIN_INTRO_ENGINES:
        if item["id"] == key:
            return dict(item)
    return None


def engine_priority_checksum(order: List[str]) -> str:
    """Checksum of the saved engine order. Catalog labels are not included."""
    encoded = json.dumps(list(order), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_engine_priority(value: Any) -> List[str]:
    """Require every catalog engine once. Unknown or repeated ids are refused."""
    if not isinstance(value, list) or not value:
        raise SolutionBlueprintError("Engine priority must list every video engine once")
    ordered: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SolutionBlueprintError("Engine priority must list engine ids")
        engine_id = item.strip()
        if engine_by_id(engine_id) is None:
            raise SolutionBlueprintError(f"Unknown video engine: {engine_id}")
        if engine_id in ordered:
            raise SolutionBlueprintError(f"Duplicate video engine: {engine_id}")
        ordered.append(engine_id)
    if set(ordered) != set(JOIN_INTRO_ENGINE_IDS):
        raise SolutionBlueprintError("Engine priority must include every video engine once")
    return ordered


def verify_engine_priority(order: Any, checksum: Any) -> bool:
    """True when the stored order matches the catalog and its checksum."""
    try:
        normalized = normalize_engine_priority(order)
    except SolutionBlueprintError:
        return False
    expected = engine_priority_checksum(normalized)
    stored = str(checksum or "")
    if len(stored) != len(expected):
        return False
    return hmac.compare_digest(stored, expected)


def canonical_narration(solution_key: str) -> str:
    """Default spoken line: every public bullet, as complete sentences.

    A saved blueprint keeps the narration it was sealed with. This text is
    only the fresh default and the result of an explicit reset.
    """
    outline = outline_for(solution_key)
    if outline is None:
        raise SolutionBlueprintError(f"Unknown solution: {solution_key}")
    return " ".join(f"{bullet.rstrip('.')}." for bullet in outline["bullets"])


def campaign_id_for(solution_key: str) -> str:
    key = str(solution_key or "").strip()
    if key in JOIN_INTRO_OUTLINES:
        return f"{_JOIN_CAMPAIGN_PREFIX}{key}"
    return f"{_CAMPAIGN_PREFIX}{key}"


def parse_campaign_id(campaign_id: str) -> str:
    """Return the key for a ``SOL-`` or ``JOIN-`` campaign id, or ''."""
    text = str(campaign_id or "").strip()
    if text.startswith(_JOIN_CAMPAIGN_PREFIX):
        key = text[len(_JOIN_CAMPAIGN_PREFIX):]
        return key if key in JOIN_INTRO_OUTLINES else ""
    if not text.startswith(_CAMPAIGN_PREFIX):
        return ""
    key = text[len(_CAMPAIGN_PREFIX):]
    return key if key in SOLUTION_OUTLINES else ""


def _clean_text(value: Any, *, limit: int, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SolutionBlueprintError(f"{field} must be text")
    text = " ".join(value.replace("\x00", " ").split())
    if len(text) > limit:
        raise SolutionBlueprintError(f"{field} is limited to {limit} characters")
    return text


def _clean_asset_id(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SolutionBlueprintError("Screenshot reference must be a media asset id")
    text = value.strip()
    if not text:
        return ""
    if not _ASSET_ID_RE.match(text):
        raise SolutionBlueprintError("Screenshot reference is not a media asset id")
    return text


def blueprint_checksum(record: Dict[str, Any]) -> str:
    """Checksum of the editable brief. Job ids and stored asset ids are excluded."""
    material = {
        "solution_key": str(record.get("solution_key") or ""),
        "source_bullets": list(record.get("source_bullets") or []),
        "narration": str(record.get("narration") or ""),
        "theme": str(record.get("theme") or ""),
        "reference_image_asset_id": str(record.get("reference_image_asset_id") or ""),
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fresh_blueprint(solution_key: str) -> Dict[str, Any]:
    key = str(solution_key or "").strip()
    outline = outline_for(key)
    if outline is None:
        raise SolutionBlueprintError(f"Unknown solution: {solution_key}")
    record = {
        "solution_key": key,
        "title": outline["title"],
        "group": outline["group"],
        "source_bullets": list(outline["bullets"]),
        "narration": canonical_narration(key),
        "theme": "",
        "reference_image_asset_id": "",
        "campaign_id": campaign_id_for(key),
        "last_job_id": "",
        "last_asset_id": "",
        "stored": False,
    }
    record["checksum"] = blueprint_checksum(record)
    record["integrity_ok"] = True
    return record


def verify_blueprint(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    key = str(record.get("solution_key") or "").strip()
    outline = outline_for(key)
    if outline is None:
        return False
    if list(record.get("source_bullets") or []) != list(outline["bullets"]):
        return False
    expected = blueprint_checksum(record)
    stored = str(record.get("checksum") or "")
    if len(stored) != len(expected):
        return False
    return hmac.compare_digest(stored, expected)


def apply_blueprint_edit(
    solution_key: str,
    current: Optional[Dict[str, Any]],
    *,
    narration: Any = None,
    theme: Any = None,
    reference_image_asset_id: Any = None,
    reset_text: bool = False,
) -> Dict[str, Any]:
    """Return a new checksummed blueprint. Canonical bullets are not client-writable."""
    key = str(solution_key or "").strip()
    outline = outline_for(key)
    if outline is None:
        raise SolutionBlueprintError(f"Unknown solution: {solution_key}")
    base = fresh_blueprint(key)
    if isinstance(current, dict) and str(current.get("solution_key") or "") == key:
        base["theme"] = str(current.get("theme") or "")
        base["narration"] = str(current.get("narration") or base["narration"])
        base["reference_image_asset_id"] = str(current.get("reference_image_asset_id") or "")
        base["last_job_id"] = str(current.get("last_job_id") or "")
        base["last_asset_id"] = str(current.get("last_asset_id") or "")
    if reset_text:
        base["narration"] = canonical_narration(key)
    elif narration is not None:
        base["narration"] = _clean_text(narration, limit=MAX_NARRATION_CHARS, field="Narration")
    if theme is not None:
        base["theme"] = _clean_text(theme, limit=MAX_THEME_CHARS, field="Theme")
    if reference_image_asset_id is not None:
        base["reference_image_asset_id"] = _clean_asset_id(reference_image_asset_id)
    if not str(base.get("narration") or "").strip():
        raise SolutionBlueprintError("Narration is required")
    base["source_bullets"] = list(outline["bullets"])
    base["title"] = outline["title"]
    base["group"] = outline["group"]
    base["campaign_id"] = campaign_id_for(key)
    base["stored"] = True
    base["checksum"] = blueprint_checksum(base)
    base["integrity_ok"] = True
    return base


def growth_blueprint(record: Dict[str, Any]) -> Dict[str, Any]:
    """Brief shape consumed by ``build_media_video_prompt``.

    The storyboard carries the stored narration in full. Clip length is the
    selected engine's own maximum. The stored narration is left as saved.
    """
    narration = str(record.get("narration") or "").strip()
    theme = str(record.get("theme") or "").strip()
    storyboard: List[str] = [narration] if narration else []
    if theme:
        storyboard.append(f"Theme: {theme}")
    return {
        "title": f"{record.get('title') or 'Solution'} — Inside the Solution",
        "format": "16:9 business appearance",
        "voiceover_style": "Clear business presenter, one spoken pass, picture free of lettering",
        "storyboard": storyboard,
        "solution_key": str(record.get("solution_key") or ""),
    }


def prompt_override(record: Dict[str, Any]) -> str:
    """Presenter direction. The quoted line is the sealed narration in full."""
    narration = str(record.get("narration") or "").strip()
    theme = str(record.get("theme") or "").strip()
    reference = str(record.get("reference_image_asset_id") or "").strip()
    parts = [
        "Business appearance, 16:9.",
        "A single professional presenter in business attire, medium close-up, calm office, looking at the camera.",
        "The frame contains no readable text: no titles, captions, subtitles, lower thirds, logos, watermarks, or disclaimers.",
        "No charts and no readable customer data.",
    ]
    if reference:
        parts.append("Use the supplied screenshot only as the setting. Do not reproduce writing from it.")
    if theme:
        parts.append(f"Descriptive theme: {theme}.")
    if narration:
        parts.append(
            "The presenter speaks this line once, in a clear calm voice, and finishes on its final period. "
            f'Do not stop mid-word or mid-sentence: "{narration}"'
        )
    return " ".join(parts)
