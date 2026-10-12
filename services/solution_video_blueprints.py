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


class SolutionBlueprintError(ValueError):
    """A blueprint edit or send was rejected before any provider call."""


def canonical_narration(solution_key: str) -> str:
    outline = SOLUTION_OUTLINES[solution_key]
    return " ".join(f"{bullet.rstrip('.')}." for bullet in outline["bullets"])


def campaign_id_for(solution_key: str) -> str:
    return f"{_CAMPAIGN_PREFIX}{solution_key}"


def parse_campaign_id(campaign_id: str) -> str:
    """Return the solution key for a ``SOL-`` campaign id, or ''."""
    text = str(campaign_id or "").strip()
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
    outline = SOLUTION_OUTLINES.get(str(solution_key or "").strip())
    if outline is None:
        raise SolutionBlueprintError(f"Unknown solution: {solution_key}")
    key = str(solution_key).strip()
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
    outline = SOLUTION_OUTLINES.get(key)
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
    if key not in SOLUTION_OUTLINES:
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
    base["source_bullets"] = list(SOLUTION_OUTLINES[key]["bullets"])
    base["title"] = SOLUTION_OUTLINES[key]["title"]
    base["group"] = SOLUTION_OUTLINES[key]["group"]
    base["campaign_id"] = campaign_id_for(key)
    base["stored"] = True
    base["checksum"] = blueprint_checksum(base)
    base["integrity_ok"] = True
    return base


def growth_blueprint(record: Dict[str, Any]) -> Dict[str, Any]:
    """Brief shape consumed by ``build_media_video_prompt``."""
    narration = str(record.get("narration") or "").strip()
    theme = str(record.get("theme") or "").strip()
    storyboard: List[str] = [narration]
    if theme:
        storyboard.append(f"Theme: {theme}")
    return {
        "title": f"{record.get('title') or 'Solution'} — Inside the Solution",
        "format": "16:9 business appearance, 8 seconds",
        "voiceover_style": "Clear business presenter, one spoken pass",
        "storyboard": storyboard,
        "solution_key": str(record.get("solution_key") or ""),
    }


def prompt_override(record: Dict[str, Any]) -> str:
    """Presenter direction. The spoken line is the editable narration only."""
    narration = str(record.get("narration") or "").strip()
    theme = str(record.get("theme") or "").strip()
    reference = str(record.get("reference_image_asset_id") or "").strip()
    parts = [
        "Business appearance, eight seconds, 16:9.",
        "A single professional presenter in business attire, medium close-up, calm office, looking at the camera.",
        "No charts and no readable customer data.",
    ]
    if reference:
        parts.append("Use the supplied screenshot as the visual reference for the setting.")
    if theme:
        parts.append(f"Descriptive theme: {theme}.")
    parts.append(
        f'The presenter speaks this line once, in a clear calm voice, and then stops: "{narration}"'
    )
    return " ".join(parts)
