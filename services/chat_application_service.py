"""
Chat-style New Policy Application service ("Phin" the PHINS broker bot).

This service powers the conversational replacement for the classic multi-step
``apply.html`` form. It keeps a stateful chat session per applicant and walks
them through the same underwriting questionnaire the legacy form collected,
but as a guided conversation with a licensed-broker persona:

- contact capture (name / email / phone) followed by an OTP gate
- adaptive underwriting questions (follow-ups appear based on answers)
- optional voice notes, video messages, and document uploads
- a live agentic risk assessment (reuses ``services.underwriting_risk_scoring``)
- an actuarial quote from the pricing kernel
  (``services.pricing_shadow_service.price_application_with_kernel``)
- payment + consent capture
- a final submission payload shaped exactly like the classic
  ``POST /api/policies/create`` body so the existing policy/underwriting/
  billing backbone stays the single source of truth.

Every mutation returns ``ledger_events`` describing what happened so the HTTP
layer (``web_portal/api_chat_application.py``) can append them to the
hash-chained platform event ledger - the chat transcript and the applicant's
A-Z journey (invited -> started -> stopped -> continued -> quoted ->
submitted -> ...) are therefore preserved for lifetime BI analysis.

Sessions can always be paused and resumed with the unique resume code plus the
contact email; sessions that already passed the OTP gate require a fresh OTP
when resumed.

The store is in-memory (consistent with the platform's demo/in-memory mode);
the ledger events are the durable, tamper-evident record.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("phins.chat_application")

try:
    from services.chat_application_i18n import (
        ack as _i18n_ack,
        is_hebrew,
        localize_choice_labels,
        localize_placeholder,
        msg as _i18n_msg,
        normalize_language,
        step_prompt_he,
        tr_validation,
    )
except ImportError:  # pragma: no cover - package layout fallback
    from chat_application_i18n import (  # type: ignore
        ack as _i18n_ack,
        is_hebrew,
        localize_choice_labels,
        localize_placeholder,
        msg as _i18n_msg,
        normalize_language,
        step_prompt_he,
        tr_validation,
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOT_NAME = "Phin"
BOT_TITLE = "PHINS Licensed Underwriting Broker"

MAX_MEDIA_ITEMS = 8
MAX_MEDIA_BYTES = 4 * 1024 * 1024          # 4 MB decoded per item
MAX_TOTAL_MEDIA_BYTES = 6 * 1024 * 1024    # 6 MB decoded per session
# Only inline files up to this size into the /api/policies/create payload so
# the final submission stays under the server's request-size ceiling.
MAX_INLINE_SUBMISSION_BYTES = 2 * 1024 * 1024

ALLOWED_MEDIA_KINDS = ("voice", "video", "document", "image")

CONSENT_VERSION = "phins-chat-consent-v1"
QUESTIONNAIRE_VERSION = "phins-chat-uw-v2"

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,30}$")
_NAME_RE = re.compile(r"^[A-Za-z\u0590-\u05FF\s\-'.]{2,100}$")

# Keyword -> (risk_impact, loading_percentage, severity) used by the broker
# bot to convert a free-text conditions list into scoring inputs.
_CONDITION_KEYWORDS = [
    ("cancer", 0.25, 40, "severe"),
    ("heart", 0.20, 30, "moderate"),
    ("stroke", 0.20, 30, "moderate"),
    ("diabet", 0.15, 20, "moderate"),
    ("kidney", 0.15, 20, "moderate"),
    ("liver", 0.15, 20, "moderate"),
    ("hypertension", 0.12, 15, "mild"),
    ("blood pressure", 0.12, 15, "mild"),
    ("cholesterol", 0.08, 10, "mild"),
    ("asthma", 0.08, 10, "mild"),
    ("depression", 0.08, 10, "mild"),
    ("anxiety", 0.06, 5, "mild"),
    ("thyroid", 0.06, 5, "mild"),
]
_DEFAULT_CONDITION = (0.10, 10, "mild")

_NONE_ANSWERS = {"none", "no", "n/a", "na", "nothing", "-", ""}

JOURNEY_STAGES = [
    "invited",
    "started",
    "contact_captured",
    "otp_verified",
    "questions_completed",
    "assessed",
    "quoted",
    "media_attached",
    "payment_captured",
    "stopped",
    "continued",
    "referred_senior_uw",
    "submitted",
    "uw_approved",
    "uw_rejected",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checksum_payload(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return _sha256_hex(canonical.encode("utf-8"))


def _calculate_age(dob_iso: str) -> Optional[int]:
    try:
        dob = datetime.strptime(dob_iso, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    today = datetime.now()
    age = today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day)
    )
    return age


def _luhn_ok(card_number: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", card_number)]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    parity = len(digits) % 2
    for idx, digit in enumerate(digits):
        if idx % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _mask_email(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
        shown = local[:2] if len(local) > 2 else local[:1]
        return f"{shown}{'*' * max(1, len(local) - len(shown))}@{domain}"
    except Exception:
        return "***"


def parse_conditions_text(text: str) -> List[Dict[str, Any]]:
    """Broker-bot heuristic: map a free-text conditions list to scoring inputs."""
    conditions: List[Dict[str, Any]] = []
    raw = str(text or "").strip().lower()
    if raw in _NONE_ANSWERS:
        return conditions
    parts = [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]
    for part in parts:
        matched = False
        for keyword, impact, loading, severity in _CONDITION_KEYWORDS:
            if keyword in part:
                conditions.append({
                    "condition": part,
                    "risk_impact": impact,
                    "loading_percentage": loading,
                    "severity": severity,
                    "exclusion_recommended": severity in ("moderate", "severe"),
                })
                matched = True
                break
        if not matched:
            conditions.append({
                "condition": part,
                "risk_impact": _DEFAULT_CONDITION[0],
                "loading_percentage": _DEFAULT_CONDITION[1],
                "severity": _DEFAULT_CONDITION[2],
                "exclusion_recommended": False,
            })
    return conditions


# ---------------------------------------------------------------------------
# Conversation script
# ---------------------------------------------------------------------------
#
# Each step: id, prompt (str or callable(session)->str), input spec for the
# UI, a validator returning (ok, cleaned_value_or_error), and an optional
# ``applies(session)`` gate for adaptive follow-ups.

def _validate_name(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
    text = str(value or "").strip()
    if not _NAME_RE.match(text):
        return False, "I need your full name as it appears on your ID (letters only, 2-100 characters)."
    if " " not in text:
        return False, "Could you give me your first and last name together? e.g. \"Dana Levi\"."
    return True, text


def _validate_email(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
    text = str(value or "").strip().lower()
    if not _EMAIL_RE.match(text):
        return False, "That email doesn't look right - could you re-type it? e.g. name@example.com"
    return True, text


def _validate_phone(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if not _PHONE_RE.match(text) or len(digits) < 7:
        return False, "That phone number doesn't look right - please include your area code, e.g. +1-555-0123."
    return True, text


def _validate_dob(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
    text = str(value or "").strip()
    age = _calculate_age(text)
    if age is None:
        return False, "Please give me your date of birth as YYYY-MM-DD."
    if age < 18:
        return False, "I'm sorry - applicants must be at least 18 years old."
    if age > 100:
        return False, "That date of birth doesn't look right - could you double-check it?"
    return True, text


def _choice_validator(options: List[str]) -> Callable[[Any, Dict[str, Any]], Tuple[bool, Any]]:
    lowered = {str(o).lower(): o for o in options}

    def _validate(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
        key = str(value or "").strip().lower()
        if key in lowered:
            return True, lowered[key]
        return False, f"Please pick one of: {', '.join(options)}."

    return _validate


def _validate_number_range(lo: float, hi: float, label: str) -> Callable[[Any, Dict[str, Any]], Tuple[bool, Any]]:
    def _validate(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return False, f"Please give me a number for {label}."
        if num < lo or num > hi:
            return False, f"{label} should be between {lo:g} and {hi:g}."
        return True, num

    return _validate


def _validate_multi_choice(options: List[str]) -> Callable[[Any, Dict[str, Any]], Tuple[bool, Any]]:
    allowed = {str(o).lower() for o in options}

    def _validate(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
        if isinstance(value, str):
            items = [v.strip().lower() for v in value.split(",") if v.strip()]
        elif isinstance(value, list):
            items = [str(v).strip().lower() for v in value if str(v).strip()]
        else:
            items = []
        if not items:
            items = ["none"]
        bad = [i for i in items if i not in allowed]
        if bad:
            return False, f"Please pick from: {', '.join(options)}."
        if "none" in items and len(items) > 1:
            items = [i for i in items if i != "none"]
        return True, items

    return _validate


def _validate_free_text(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
    return True, str(value or "").strip()


def _validate_disclosure_text(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
    text = str(value or "").strip()
    if len(text) < 1 or len(text) > 4000:
        return False, "Please provide a disclosure (or type \"none\")."
    return True, text


def _israeli_id_checksum_ok(value: str) -> bool:
    """Teudat Zehut Luhn-variant (same algorithm as assessment_center)."""
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) != 9 or len(set(digits)) == 1:
        return False
    total = 0
    for i, digit in enumerate(digits):
        weighted = digit * (1 if i % 2 == 0 else 2)
        if weighted > 9:
            weighted -= 9
        total += weighted
    return total % 10 == 0


def _validate_id_number(raw: Any) -> Tuple[bool, str]:
    cleaned = re.sub(r"[\s\-]", "", str(raw or "").strip())
    if not cleaned:
        return False, "Please enter your national ID / Teudat Zehut number."
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) == 9 and digits == cleaned:
        if not _israeli_id_checksum_ok(digits):
            return False, "That ID number does not look valid - please double-check the digits."
        return True, digits
    # Non-IL national IDs: keep alphanumeric, 5–20 chars.
    if not re.fullmatch(r"[A-Za-z0-9]{5,20}", cleaned):
        return False, "That ID number does not look valid - please double-check the digits."
    return True, cleaned.upper()


def _signature_image_ok(data_url: Any) -> Tuple[bool, str, str]:
    """Validate a drawn PNG data-URL and return (ok, error_or_empty, sha256)."""
    raw = str(data_url or "").strip()
    if not raw.startswith("data:image/png;base64,"):
        return False, "Please draw your signature in the signature panel.", ""
    b64 = raw.split(",", 1)[1].strip()
    if len(b64) < 80:
        return False, "Please draw your signature in the signature panel.", ""
    try:
        blob = base64.b64decode(b64, validate=False)
    except Exception:
        return False, "Please draw your signature in the signature panel.", ""
    if len(blob) < 60:
        return False, "Please draw your signature in the signature panel.", ""
    digest = hashlib.sha256(blob).hexdigest()
    return True, "", digest


def _validate_signature(value: Any, session: Dict[str, Any]) -> Tuple[bool, Any]:
    """Mandatory e-sign: legal name + ID number + drawn signature canvas.

    Accepts a structured object from the signature panel. A bare string is
    rejected so name/ID/canvas stay bound together for data integrity.
    """
    if isinstance(value, str):
        # Legacy typed-only payloads are no longer enough — keep a clear error.
        return False, (
            "Please complete the signature panel "
            "(legal name, ID number, and drawn signature)."
        )
    if not isinstance(value, dict):
        return False, (
            "Please complete the signature panel "
            "(legal name, ID number, and drawn signature)."
        )

    typed = str(value.get("name") or "").strip()
    if len(typed) < 2 or len(typed) > 120:
        return False, "Please type your full legal name to sign."
    expected = str((session.get("contact") or {}).get("name") or "").strip()
    if expected:
        def _fold(s: str) -> str:
            return " ".join(s.lower().split())
        if _fold(typed) != _fold(expected):
            return False, (
                f"Signature must match the name on this application ({expected})."
            )

    id_ok, id_val = _validate_id_number(value.get("id_number"))
    if not id_ok:
        return False, id_val

    img_ok, img_err, img_sha = _signature_image_ok(value.get("signature_data"))
    if not img_ok:
        return False, img_err

    method = str(value.get("method") or "drawn_canvas").strip() or "drawn_canvas"
    if method not in ("drawn_canvas", "drawn"):
        method = "drawn_canvas"

    # Keep the PNG on the answer only until finalize copies it into the UW
    # payload; mark_submitted redacts the raw bytes afterward.
    return True, {
        "name": typed,
        "id_number": id_val,
        "signature_data": str(value.get("signature_data")).strip(),
        "image_sha256": img_sha,
        "method": "drawn_canvas",
    }


def _validate_card(value: Any, _s: Dict[str, Any]) -> Tuple[bool, Any]:
    if not isinstance(value, dict):
        return False, "I need your card details as a structured object."
    card_number = re.sub(r"\D", "", str(value.get("card_number") or ""))
    name = str(value.get("cardholder_name") or "").strip()
    month = str(value.get("expiry_month") or "").strip()
    year = str(value.get("expiry_year") or "").strip()
    cvv = str(value.get("cvv") or "").strip()
    if not _luhn_ok(card_number):
        return False, "That card number doesn't pass validation - please double-check the digits."
    if not name:
        return False, "Please give me the cardholder name exactly as printed on the card."
    try:
        m, y = int(month), int(year)
        if m < 1 or m > 12:
            raise ValueError
        now = datetime.now()
        if (y, m) < (now.year, now.month):
            return False, "That card has already expired - do you have another one?"
    except (TypeError, ValueError):
        return False, "Please give me the card expiry as month (1-12) and 4-digit year."
    if not re.fullmatch(r"\d{3,4}", cvv):
        return False, "The CVV should be the 3 or 4 digit code on the back of the card."
    return True, {
        "card_number": card_number,
        "cardholder_name": name,
        "expiry_month": f"{int(month):02d}",
        "expiry_year": year,
        "cvv": cvv,
        "card_last4": card_number[-4:],
    }


def _applies_conditions_detail(session: Dict[str, Any]) -> bool:
    return session["answers"].get("medical_conditions") == "yes"


def _applies_surgery_detail(session: Dict[str, Any]) -> bool:
    return session["answers"].get("surgery") == "yes"


STEPS: List[Dict[str, Any]] = [
    {
        "id": "name",
        "prompt": "Let's start easy - what's your full name?",
        "input": {"type": "text", "placeholder": "e.g. Dana Levi"},
        "validate": _validate_name,
    },
    {
        "id": "email",
        "prompt": lambda s: (
            f"Nice to meet you, {s['answers'].get('name', '').split(' ')[0]}! "
            "What's the best email for you? I'll send your policy documents there - "
            "and a quick verification code in a moment."
        ),
        "input": {"type": "email", "placeholder": "name@example.com"},
        "validate": _validate_email,
    },
    {
        "id": "phone",
        "prompt": "And your mobile number? We only use it for important policy notifications.",
        "input": {"type": "phone", "placeholder": "+1-555-0123"},
        "validate": _validate_phone,
    },
    # OTP gate happens here (handled by dedicated endpoints, not a step).
    {
        "id": "dob",
        "prompt": "Verified - thank you! Now the underwriting part. I'll be your broker through this: honest answers get you the fairest price. First, what's your date of birth?",
        "input": {"type": "date"},
        "validate": _validate_dob,
    },
    {
        "id": "gender",
        "prompt": "Which option matches your gender? Our actuarial tables use this for accurate pricing.",
        "input": {"type": "choice", "options": ["male", "female", "other"]},
        "validate": _choice_validator(["male", "female", "other"]),
    },
    {
        "id": "occupation",
        "prompt": "What do you do for a living? Some occupations carry different risk profiles.",
        "input": {"type": "text", "placeholder": "e.g. Software Engineer"},
        "validate": _validate_free_text,
    },
    {
        "id": "height",
        "prompt": "Let's talk health. How tall are you, in centimeters?",
        "input": {"type": "number", "min": 100, "max": 250, "suffix": "cm"},
        "validate": _validate_number_range(100, 250, "height (cm)"),
    },
    {
        "id": "weight",
        "prompt": "And your weight in kilograms?",
        "input": {"type": "number", "min": 30, "max": 300, "suffix": "kg"},
        "validate": _validate_number_range(30, 300, "weight (kg)"),
    },
    {
        "id": "tobacco",
        "prompt": "Do you use tobacco products - cigarettes, cigars, or vaping?",
        "input": {"type": "choice", "options": ["no", "yes", "former"],
                  "labels": {"no": "No, never", "yes": "Yes, currently", "former": "Quit over a year ago"}},
        "validate": _choice_validator(["no", "yes", "former"]),
    },
    {
        "id": "medical_conditions",
        "prompt": "Do you have any pre-existing medical conditions? Everything you tell me is confidential and protected.",
        "input": {"type": "choice", "options": ["no", "yes"]},
        "validate": _choice_validator(["no", "yes"]),
    },
    {
        "id": "conditions_list",
        "prompt": "I appreciate your honesty - that's exactly what gets you a fair, valid policy. Please list the conditions (e.g. \"type 2 diabetes, high blood pressure\").",
        "input": {"type": "text", "placeholder": "e.g. diabetes, high blood pressure"},
        "validate": _validate_free_text,
        "applies": _applies_conditions_detail,
    },
    {
        "id": "surgery",
        "prompt": "Any major surgeries in the past 5 years?",
        "input": {"type": "choice", "options": ["no", "yes"]},
        "validate": _choice_validator(["no", "yes"]),
    },
    {
        "id": "surgery_list",
        "prompt": "Thanks for flagging it. Briefly, what was the surgery and when?",
        "input": {"type": "text"},
        "validate": _validate_free_text,
        "applies": _applies_surgery_detail,
    },
    {
        "id": "hazardous",
        "prompt": "Do you do any hazardous activities or extreme sports? Skydiving, motor racing, deep diving - that sort of thing.",
        "input": {"type": "choice", "options": ["no", "occasional", "regular"],
                  "labels": {"no": "No", "occasional": "1-2 times a year", "regular": "Monthly or more"}},
        "validate": _choice_validator(["no", "occasional", "regular"]),
    },
    {
        "id": "family_history",
        "prompt": "Has any immediate family member had heart disease, cancer, diabetes, or a stroke? Pick all that apply.",
        "input": {"type": "multi_choice", "options": ["heart", "cancer", "diabetes", "stroke", "none"]},
        "validate": _validate_multi_choice(["heart", "cancer", "diabetes", "stroke", "none"]),
    },
    {
        "id": "medications",
        "prompt": "Nearly done with health: any medications you take regularly? Type \"none\" if not.",
        "input": {"type": "text", "placeholder": "e.g. metformin - or \"none\""},
        "validate": _validate_free_text,
    },
    {
        "id": "prior_disclosure",
        "prompt": (
            "Before we continue, I check your answers against any earlier PHINS applications "
            "or claims. If anything conflicts I'll ask you to explain; otherwise I'll ask you "
            "to disclose any other medical facts now that you are releasing medical "
            "confidentiality to PHINS underwriting."
        ),
        "input": {"type": "text", "placeholder": "Your disclosure"},
        "validate": _validate_disclosure_text,
    },
    {
        "id": "daily_function",
        "prompt": (
            "Last health question, and it matters for your disability cover. "
            "Our actuaries price the disability benefit on your activities of daily living "
            "(dressing, bathing, eating, transferring, toileting, continence). "
            "How would you describe your day-to-day functional independence?"
        ),
        "input": {
            "type": "choice",
            "options": ["full", "minor", "moderate", "significant"],
            "labels": {
                "full": "Fully independent in all activities",
                "minor": "Minor difficulty with 1 activity",
                "moderate": "Need help with 1-2 activities",
                "significant": "Need help with 3 or more activities",
            },
        },
        "validate": _choice_validator(["full", "minor", "moderate", "significant"]),
    },
    # assessment is delivered by the bot right after `daily_function`.
    {
        "id": "coverage_amount",
        "prompt": "Now the fun part - how much coverage would you like? Most members pick $500,000. You can fine-tune it with the slider.",
        "input": {"type": "slider", "min": 100000, "max": 5000000, "step": 50000,
                  "default": 500000, "format": "currency"},
        "validate": _validate_number_range(100000, 5000000, "coverage amount"),
    },
    {
        "id": "coverage_years",
        "prompt": "And for how many years should we build your savings and protection? 20 years is our most popular plan.",
        "input": {"type": "choice", "options": ["10", "15", "20", "30"], "suffix": "years"},
        "validate": _choice_validator(["10", "15", "20", "30"]),
    },
    {
        "id": "savings_addon",
        "prompt": (
            "Would you like to add PHINS savings on top of your protection? "
            "It's priced as a markup on your risk premium and accumulates in your plan - "
            "pure protection is always an option."
        ),
        "input": {
            "type": "choice",
            "options": ["none", "light", "balanced", "growth"],
            "labels": {
                "none": "Pure protection (no savings)",
                "light": "Light (+25% of risk premium)",
                "balanced": "Balanced (+50%)",
                "growth": "Growth (+100%)",
            },
        },
        "validate": _choice_validator(["none", "light", "balanced", "growth"]),
    },
    # quote is delivered by the bot right after `savings_addon`.
    {
        "id": "media_offer",
        "prompt": (
            "Optional but recommended: you can send me a voice note, record a short video, "
            "or upload supporting documents (ID, medical results). It can speed up underwriting. "
            "Use the mic / camera / clip buttons - and tap \"Done\" when you're ready to move on."
        ),
        "input": {"type": "media", "options": ["done", "skip"]},
        "validate": _choice_validator(["done", "skip"]),
    },
    {
        "id": "billing_frequency",
        "prompt": "How would you like to pay your premium?",
        "input": {"type": "choice", "options": ["monthly", "quarterly", "annual"],
                  "labels": {"monthly": "Monthly", "quarterly": "Quarterly (save 3%)", "annual": "Annual (save 10%)"}},
        "validate": _choice_validator(["monthly", "quarterly", "annual"]),
    },
    {
        "id": "payment_card",
        "prompt": "Almost there. I need a payment card for premium billing - it's encrypted and tokenized, we never store the full number.",
        "input": {"type": "card"},
        "validate": _validate_card,
    },
    {
        "id": "auto_pay",
        "prompt": "Should I set up automatic payments so you never miss a premium?",
        "input": {"type": "choice", "options": ["yes", "no"]},
        "validate": _choice_validator(["yes", "no"]),
    },
    {
        "id": "consent",
        "prompt": (
            "Almost done - the legal part. Please confirm that: (1) you agree to the Terms of Use "
            "and Privacy Policy, (2) everything you told me is accurate and complete, and "
            "(3) you authorize PHINS to charge your payment method for premiums."
        ),
        "input": {"type": "consent", "options": ["agree"]},
        "validate": _choice_validator(["agree"]),
    },
    {
        "id": "signature",
        "prompt": (
            "Final step — your electronic signature is mandatory. Type your full legal name "
            "exactly as on this application, enter your national ID / Teudat Zehut, "
            "and draw your signature in the panel to seal your declarations."
        ),
        "input": {
            "type": "signature",
            "placeholder": "Full legal name",
            "id_placeholder": "National ID / Teudat Zehut",
        },
        "validate": _validate_signature,
    },
]

_STEP_INDEX = {step["id"]: idx for idx, step in enumerate(STEPS)}

# The step whose completion opens the OTP gate.
_OTP_GATE_AFTER = "phone"
# Steps reachable before the OTP gate is passed.
_PRE_OTP_STEPS = {"name", "email", "phone"}


class ChatPolicyApplicationService:
    """Stateful chat application store + broker-bot conversation engine."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._resume_index: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _generate_ids(self) -> Tuple[str, str]:
        app_id = f"CHAPP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"
        while True:
            resume_code = f"PHINS-CHAT-{secrets.token_hex(4).upper()}"
            if resume_code not in self._resume_index:
                break
        return app_id, resume_code

    def _get(self, application_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(str(application_id or "").strip())

    def _transcript_add(self, session: Dict[str, Any], role: str, text: str,
                        kind: str = "text", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry = {
            "seq": len(session["transcript"]) + 1,
            "role": role,
            "kind": kind,
            "text": text,
            "meta": meta or {},
            "ts": _utc_now_iso(),
        }
        session["transcript"].append(entry)
        session["updated_at"] = entry["ts"]
        return entry

    def _ledger_for_message(self, session: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
        safe_meta = {k: v for k, v in (entry.get("meta") or {}).items()
                     if k not in ("data_b64", "card_number", "cvv")}
        return {
            "event_type": "chat.message",
            "entity_type": "policy_application",
            "entity_id": session["id"],
            "customer_id": session.get("customer_id") or session["contact"].get("email") or None,
            "actor": "applicant" if entry["role"] == "user" else "underwriting_bot",
            "entry_id": f"CHAT-{session['id']}-{entry['seq']:04d}",
            "payload": {
                "application_id": session["id"],
                "seq": entry["seq"],
                "role": entry["role"],
                "kind": entry["kind"],
                "text": str(entry.get("text") or "")[:500],
                "meta": safe_meta,
                "ts": entry["ts"],
            },
        }

    def _journey_add(self, session: Dict[str, Any], stage: str, actor: str = "applicant",
                     meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record = {"stage": stage, "actor": actor, "meta": meta or {}, "ts": _utc_now_iso()}
        session["journey"].append(record)
        return {
            "event_type": f"journey.{stage}",
            "entity_type": "policy_application",
            "entity_id": session["id"],
            "customer_id": session.get("customer_id") or session["contact"].get("email") or None,
            "actor": actor,
            "entry_id": f"JRNY-{session['id']}-{len(session['journey']):03d}-{stage}",
            "payload": {"application_id": session["id"], **record},
        }

    def _steps_for(self, session: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [s for s in STEPS
                if "applies" not in s or s["applies"](session)]

    def _next_step(self, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        answered = session["answers"]
        for step in self._steps_for(session):
            if step["id"] not in answered:
                if step["id"] not in _PRE_OTP_STEPS and not session["email_verified"]:
                    return None  # OTP gate blocks progress
                return step
        return None

    def _progress(self, session: Dict[str, Any]) -> Dict[str, Any]:
        steps = self._steps_for(session)
        done = sum(1 for s in steps if s["id"] in session["answers"])
        pct = int(round(100 * done / max(1, len(steps))))
        return {"answered": done, "total": len(steps), "percent": pct}

    def _step_public(self, session: Dict[str, Any], step: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if step is None:
            return None
        prompt = step["prompt"]
        if callable(prompt):
            prompt = prompt(session)
        if is_hebrew(session):
            first = str(session.get("answers", {}).get("name") or "").split(" ")[0]
            he = step_prompt_he(step["id"], first=first or "")
            if he:
                prompt = he
        public_input = dict(step["input"])
        labels = public_input.get("labels") or {}
        # Ensure choice steps without English labels still get Hebrew labels.
        if step["id"] == "gender" and not labels:
            labels = {"male": "male", "female": "female", "other": "other"}
        if step["id"] == "coverage_years" and not labels:
            labels = {o: o for o in (public_input.get("options") or [])}
        if step["id"] in ("medical_conditions", "surgery", "auto_pay") and not labels:
            labels = {o: o for o in (public_input.get("options") or [])}
        if step["id"] == "family_history" and not labels:
            labels = {o: o for o in (public_input.get("options") or [])}
        if step["id"] == "media_offer" and not labels:
            labels = {"done": "Done - continue", "skip": "Skip for now"}
        localized = localize_choice_labels(session, step["id"], labels or None)
        if localized:
            public_input["labels"] = localized
        if public_input.get("placeholder"):
            public_input["placeholder"] = localize_placeholder(
                session, step["id"], public_input.get("placeholder")
            ) or public_input["placeholder"]
        if public_input.get("id_placeholder"):
            public_input["id_placeholder"] = localize_placeholder(
                session, "id_number", public_input.get("id_placeholder")
            ) or public_input["id_placeholder"]
        if public_input.get("suffix") and is_hebrew(session):
            suffix_map = {"years": "שנים", "cm": "ס\"מ", "kg": "ק\"ג"}
            public_input["suffix"] = suffix_map.get(
                str(public_input["suffix"]), public_input["suffix"]
            )
        public = {"id": step["id"], "prompt": prompt, "input": public_input}
        if step["id"] == "prior_disclosure":
            disclosure = self._build_disclosure_for(session)
            if is_hebrew(session) and disclosure.get("mode") == "open_disclosure":
                he = step_prompt_he("prior_disclosure")
                public["prompt"] = he or disclosure["prompt"]
            else:
                public["prompt"] = disclosure["prompt"]
            public["input"]["placeholder"] = disclosure.get("placeholder") or public["input"].get("placeholder")
            if is_hebrew(session):
                public["input"]["placeholder"] = localize_placeholder(
                    session, "prior_disclosure", public["input"].get("placeholder")
                )
            public["disclosure_mode"] = disclosure.get("mode")
            public["contradictions"] = disclosure.get("contradictions") or []
            session["disclosure_context"] = disclosure
        return public

    def _build_disclosure_for(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """Personalize the medical disclosure / contradiction step."""
        from services.underwriting_integrity_service import (
            build_disclosure_prompt,
            detect_claim_statement_contradictions,
            detect_statement_contradictions,
            find_prior_customer_records,
        )
        email = (session.get("contact") or {}).get("email")
        customer_id = session.get("customer_id")
        underwriting_apps: Dict[str, Any] = {}
        policies: Dict[str, Any] = {}
        claims: Dict[str, Any] = {}
        try:
            try:
                from web_portal import server as portal
            except ImportError:
                import server as portal  # type: ignore
            underwriting_apps = dict(getattr(portal, "UNDERWRITING_APPLICATIONS", {}) or {})
            policies = dict(getattr(portal, "POLICIES", {}) or {})
            claims = dict(getattr(portal, "CLAIMS", {}) or {})
        except Exception as exc:
            logger.warning("Disclosure prior-record lookup failed: %s", exc)
        prior = find_prior_customer_records(
            email=email,
            customer_id=customer_id,
            underwriting_apps=underwriting_apps,
            policies=policies,
            claims=claims,
            exclude_app_id=None,
        )
        contradictions = detect_statement_contradictions(
            session.get("answers") or {}, prior["applications"]
        )
        contradictions.extend(
            detect_claim_statement_contradictions(session.get("answers") or {}, prior["claims"])
        )
        return build_disclosure_prompt(contradictions)

    def _apply_side_effects(self, session: Dict[str, Any], step_id: str,
                            cleaned: Any, events: List[Dict[str, Any]]) -> None:
        contact = session["contact"]
        if step_id == "name":
            contact["name"] = cleaned
        elif step_id == "email":
            contact["email"] = cleaned
        elif step_id == "phone":
            contact["phone"] = cleaned
        elif step_id == "payment_card":
            # Redact the stored transcript meta; the card details live only in
            # answers (used once at submission, like the classic form).
            events.append(self._journey_add(session, "payment_captured",
                                            meta={"card_last4": cleaned["card_last4"]}))
        elif step_id == "prior_disclosure":
            ctx = session.get("disclosure_context") or self._build_disclosure_for(session)
            session["answers"]["disclosure_mode"] = ctx.get("mode")
            session["answers"]["prior_disclosure"] = cleaned
            session["answers"]["prior_disclosure_at"] = _utc_now_iso()
            session["answers"]["contradiction_codes"] = [
                c.get("field") for c in (ctx.get("contradictions") or []) if c.get("field")
            ]
            session["disclosure_context"] = ctx
            events.append(self._journey_add(
                session, "disclosure_captured",
                meta={"mode": ctx.get("mode"),
                      "contradiction_count": len(ctx.get("contradictions") or [])}))
        elif step_id == "consent":
            session["answers"]["consent_accepted_at"] = _utc_now_iso()
            session["answers"]["consent_version"] = CONSENT_VERSION
        elif step_id == "signature":
            # cleaned is the structured signature dict from _validate_signature
            sig = cleaned if isinstance(cleaned, dict) else {"name": cleaned}
            session["signature_name"] = sig.get("name")
            session["signature_at"] = _utc_now_iso()
            session["answers"]["signature_name"] = sig.get("name")
            session["answers"]["signature_at"] = session["signature_at"]
            session["answers"]["signature_method"] = sig.get("method") or "drawn_canvas"
            session["answers"]["id_number"] = sig.get("id_number")
            session["answers"]["signature_image_sha256"] = sig.get("image_sha256")
            # Keep raw PNG until finalize copies it into the UW payload.
            if sig.get("signature_data"):
                session["answers"]["signature_data"] = sig.get("signature_data")
            events.append(self._journey_add(
                session, "signed",
                meta={
                    "signature_name": sig.get("name"),
                    "signature_at": session["signature_at"],
                    "signature_method": session["answers"]["signature_method"],
                    "id_number_last4": str(sig.get("id_number") or "")[-4:],
                    "image_sha256": sig.get("image_sha256"),
                }))

    def start_session(self, *, channel: str = "web_chat",
                      invite: Optional[Dict[str, Any]] = None,
                      started_by: str = "applicant",
                      language: str = "en") -> Dict[str, Any]:
        with self._lock:
            app_id, resume_code = self._generate_ids()
            lang = normalize_language(language)
            session: Dict[str, Any] = {
                "id": app_id,
                "resume_code": resume_code,
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "status": "in_progress",
                "channel": channel,
                "started_by": started_by,
                "invited_by": invite,
                "language": lang,
                "contact": {"name": None, "email": None, "phone": None},
                "email_verified": False,
                "otp": {},
                "answers": {},
                "media": [],
                "transcript": [],
                "journey": [],
                "assessment": None,
                "quote": None,
                "customer_id": None,
                "submission": None,
                "finalizing": False,
            }
            self._sessions[app_id] = session
            self._resume_index[resume_code] = app_id

            events: List[Dict[str, Any]] = []
            if invite:
                events.append(self._journey_add(
                    session, "invited",
                    actor=str(invite.get("referrer_id") or invite.get("type") or "referrer"),
                    meta={"code": invite.get("code"), "referrer_type": invite.get("type"),
                          "referrer_id": invite.get("referrer_id")},
                ))
            events.append(self._journey_add(session, "started", actor=started_by,
                                            meta={"channel": channel, "language": lang}))

            greeting = _i18n_msg(
                session, "greeting",
                f"Hi! I'm {BOT_NAME}, your {BOT_TITLE} - I'll personally walk you "
                "through your PHINS application, just like a broker sitting across the desk. "
                "It usually takes about 3 minutes.",
                bot_name=BOT_NAME, bot_title=BOT_TITLE,
            )
            # Resume code stays ASCII in both languages for tracking integrity.
            resume_note = _i18n_msg(
                session, "resume_note",
                f"Your private resume code is {resume_code}. If we get interrupted, come back "
                "any time - the code plus your email picks up exactly where we left off.",
                resume_code=resume_code,
            )
            bot_msgs = []
            if invite:
                who = invite.get("type") or "someone"
                bot_msgs.append(self._transcript_add(
                    session, "bot",
                    _i18n_msg(
                        session, "invite_welcome",
                        f"Welcome! I see you were invited by a PHINS {who} - great referrals make great members.",
                        who=who,
                    ),
                    meta={"invite_code": invite.get("code")}))
            bot_msgs.append(self._transcript_add(session, "bot", greeting))
            bot_msgs.append(self._transcript_add(session, "bot", resume_note, kind="resume_code",
                                                 meta={"resume_code": resume_code}))
            step = self._next_step(session)
            step_pub = self._step_public(session, step)
            bot_msgs.append(self._transcript_add(session, "bot", step_pub["prompt"],
                                                 kind="question", meta={"step": step_pub["id"]}))
            events.extend(self._ledger_for_message(session, m) for m in bot_msgs)

            return {
                "ok": True,
                "application_id": app_id,
                "resume_code": resume_code,
                "language": lang,
                "messages": bot_msgs,
                "step": step_pub,
                "progress": self._progress(session),
                "ledger_events": events,
            }

    # ------------------------------------------------------------------
    # conversation
    # ------------------------------------------------------------------

    def submit_answer(self, application_id: str, value: Any,
                      step_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409,
                        "error": "This application was already submitted."}
            if session["status"] == "pending_reverify":
                return {"ok": False, "status_code": 403, "error": "OTP_REQUIRED",
                        "message": "Please verify the fresh security code first."}
            if session["status"] == "paused":
                if session["email_verified"]:
                    # A verified, paused session must go back through the
                    # resume + fresh-OTP gate; it must never silently unlock
                    # by writing an answer.
                    return {"ok": False, "status_code": 403, "error": "OTP_REQUIRED",
                            "message": "Please resume with a fresh security code before continuing."}
                session["status"] = "in_progress"

            step = self._next_step(session)
            if step is None:
                if not session["email_verified"]:
                    return {"ok": False, "status_code": 403, "error": "OTP_REQUIRED",
                            "message": "Please verify your email with the code I sent before we continue."}
                return {"ok": False, "status_code": 409,
                        "error": "All questions are answered - you can finalize now.",
                        "ready_to_finalize": True}
            if step_id and step_id != step["id"]:
                return {"ok": False, "status_code": 409,
                        "error": f"Expected an answer for step '{step['id']}'",
                        "step": self._step_public(session, step)}

            ok, cleaned = step["validate"](value, session)
            events: List[Dict[str, Any]] = []
            user_entry = self._transcript_add(
                session, "user",
                self._display_value(step["id"], value),
                kind="answer", meta={"step": step["id"]})
            events.append(self._ledger_for_message(session, user_entry))

            if not ok:
                err_text = tr_validation(session, str(cleaned))
                bot_entry = self._transcript_add(session, "bot", err_text,
                                                 kind="validation_error",
                                                 meta={"step": step["id"]})
                events.append(self._ledger_for_message(session, bot_entry))
                return {
                    "ok": False, "status_code": 400, "error": err_text,
                    "messages": [bot_entry],
                    "step": self._step_public(session, step),
                    "progress": self._progress(session),
                    "ledger_events": events,
                }

            session["answers"][step["id"]] = cleaned
            self._apply_side_effects(session, step["id"], cleaned, events)

            bot_msgs: List[Dict[str, Any]] = []
            ack = self._acknowledge(session, step["id"], cleaned)
            if ack:
                bot_msgs.append(self._transcript_add(session, "bot", ack,
                                                     kind="ack", meta={"step": step["id"]}))

            extras = self._milestone_messages(session, step["id"], events)
            bot_msgs.extend(extras)

            response: Dict[str, Any] = {"ok": True}
            next_step = self._next_step(session)

            if next_step is None and not session["email_verified"] and \
                    step["id"] == _OTP_GATE_AFTER:
                events.append(self._journey_add(session, "contact_captured"))
                otp_msg = self._transcript_add(
                    session, "bot",
                    _i18n_msg(
                        session, "otp_challenge",
                        f"Perfect. To protect your data I've sent a 6-digit verification code to "
                        f"{_mask_email(session['contact']['email'])}. Type it here when it arrives.",
                        masked_email=_mask_email(session["contact"]["email"]),
                    ),
                    kind="otp_challenge")
                bot_msgs.append(otp_msg)
                response["otp_required"] = True
            elif next_step is None:
                done_msg = self._transcript_add(
                    session, "bot",
                    _i18n_msg(
                        session, "ready_to_finalize",
                        "That's everything I need! Give me one second to run the final checks, "
                        "then I'll issue your application to underwriting.",
                    ),
                    kind="ready_to_finalize")
                bot_msgs.append(done_msg)
                response["ready_to_finalize"] = True
            else:
                step_pub = self._step_public(session, next_step)
                bot_msgs.append(self._transcript_add(session, "bot", step_pub["prompt"],
                                                     kind="question",
                                                     meta={"step": step_pub["id"]}))
                response["step"] = step_pub

            events.extend(self._ledger_for_message(session, m) for m in bot_msgs)
            response.update({
                "messages": bot_msgs,
                "progress": self._progress(session),
                "assessment": session.get("assessment"),
                "quote": session.get("quote"),
                "ledger_events": events,
            })
            return response

    def _display_value(self, step_id: str, value: Any) -> str:
        if step_id == "payment_card" and isinstance(value, dict):
            digits = re.sub(r"\D", "", str(value.get("card_number") or ""))
            return f"Card ending in {digits[-4:]}" if digits else "Card details provided"
        if step_id == "signature" and isinstance(value, dict):
            name = str(value.get("name") or "").strip()
            idn = str(value.get("id_number") or "").strip()
            id_mask = ("••••" + idn[-4:]) if len(idn) >= 4 else "••••"
            return f"Signed: {name} · ID {id_mask}"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

    # -- broker persona -------------------------------------------------

    def _acknowledge(self, session: Dict[str, Any], step_id: str, value: Any) -> Optional[str]:
        answers = session["answers"]
        if step_id == "dob":
            age = _calculate_age(value)
            if age is not None and age < 30:
                return _i18n_ack(
                    session, "dob_young",
                    f"{age} - starting early is the single smartest insurance decision. "
                    "Locking in your health now keeps premiums low for decades.",
                    age=age,
                )
            if age is not None and age >= 55:
                return _i18n_ack(
                    session, "dob_senior",
                    f"Noted, {age}. I'll make sure the plan reflects the protection that matters most at this stage.",
                    age=age,
                )
            return _i18n_ack(session, "dob_default", "Got it, thanks.")
        if step_id == "tobacco":
            if value == "yes":
                return _i18n_ack(
                    session, "tobacco_yes",
                    "Thanks for being straight with me - as your broker I have to be straight back: "
                    "tobacco does raise the premium. The good news? Quit for 12 months and we can re-rate you.",
                )
            if value == "former":
                return _i18n_ack(
                    session, "tobacco_former",
                    "Respect - quitting is hard. Since it's been over a year, the impact on your rate is modest.",
                )
            return _i18n_ack(session, "tobacco_no", "Great - that keeps your rate nice and lean.")
        if step_id == "weight":
            h = answers.get("height")
            w = answers.get("weight")
            if h and w:
                bmi = w / ((h / 100) ** 2)
                if 18.5 <= bmi < 25:
                    return _i18n_ack(
                        session, "bmi_healthy",
                        f"Your BMI comes out at {bmi:.1f} - right in the healthy range. Underwriting loves that.",
                        bmi=bmi,
                    )
                if bmi >= 30:
                    return _i18n_ack(
                        session, "bmi_high",
                        f"Your BMI comes out at {bmi:.1f}. It may add a small loading, but nothing we can't work with.",
                        bmi=bmi,
                    )
                return _i18n_ack(
                    session, "bmi_other",
                    f"Your BMI comes out at {bmi:.1f} - noted for the assessment.",
                    bmi=bmi,
                )
        if step_id == "medical_conditions" and value == "no":
            return _i18n_ack(session, "medical_clean", "Clean bill of health - excellent.")
        if step_id == "hazardous" and value != "no":
            return _i18n_ack(
                session, "hazardous",
                "Adventurous! I'll factor that in - full transparency keeps your claims bulletproof.",
            )
        if step_id == "family_history":
            if value and value != ["none"]:
                return _i18n_ack(
                    session, "family_yes",
                    "Thanks - family history helps our actuaries price fairly, it doesn't disqualify you.",
                )
            return _i18n_ack(session, "family_no", "Good genes - noted.")
        if step_id == "prior_disclosure":
            mode = (session.get("disclosure_context") or {}).get("mode")
            if mode == "contradiction":
                return _i18n_ack(
                    session, "disclosure_contradiction",
                    "Thank you - I've sealed that explanation into your file for the senior "
                    "underwriter. Honesty here protects your future claims.",
                )
            if str(value).strip().lower() in ("none", "n/a", "na", "no"):
                return _i18n_ack(
                    session, "disclosure_none",
                    "Understood - nothing further to disclose. Continuing.",
                )
            return _i18n_ack(
                session, "disclosure_other",
                "Recorded. That extra disclosure goes straight to underwriting with your file.",
            )
        if step_id == "coverage_amount":
            return _i18n_ack(
                session, "coverage_amount",
                f"${value:,.0f} of coverage - solid choice.",
                value=value,
            )
        if step_id == "daily_function":
            if value == "full":
                return _i18n_ack(
                    session, "daily_full",
                    "Full independence - that's the standard rating for the disability benefit.",
                )
            return _i18n_ack(
                session, "daily_other",
                "Thank you for being precise - our actuaries rate the disability benefit "
                "directly off that, so this keeps your cover honest and claimable.",
            )
        if step_id == "savings_addon":
            if value == "none":
                return _i18n_ack(
                    session, "savings_none",
                    "Pure protection it is. Let me price it from our actuarial pricing center...",
                )
            return _i18n_ack(
                session, "savings_other",
                "Savings added on top of your protection. Pricing it now through our "
                "actuarial pricing center...",
            )
        if step_id == "coverage_years":
            return _i18n_ack(
                session, "coverage_years",
                f"{value} years - noted.",
                value=value,
            )
        if step_id == "billing_frequency":
            if value == "annual":
                return _i18n_ack(
                    session, "billing_annual",
                    "Annual it is - that locks in the 10% saving.",
                )
            if value == "quarterly":
                return _i18n_ack(
                    session, "billing_quarterly",
                    "Quarterly - you get the 3% saving.",
                )
            return _i18n_ack(
                session, "billing_monthly",
                "Monthly - the most popular option.",
            )
        if step_id == "auto_pay":
            return (
                _i18n_ack(session, "auto_pay_yes", "Auto-pay armed - one less thing to think about.")
                if value == "yes"
                else _i18n_ack(
                    session, "auto_pay_no",
                    "No problem - I'll send you a reminder before each due date.",
                )
            )
        if step_id == "consent":
            return _i18n_ack(
                session, "consent_ack",
                "Legal confirmations recorded - one last step for your signature.",
            )
        if step_id == "signature":
            sig = value if isinstance(value, dict) else {"name": value}
            name = sig.get("name") or session.get("signature_name") or ""
            idn = str(sig.get("id_number") or session["answers"].get("id_number") or "")
            id_masked = ("••••" + idn[-4:]) if len(idn) >= 4 else "••••"
            return _i18n_ack(
                session, "signature_ack",
                f"Signed by {name} at {session.get('signature_at')}. "
                "Your declarations are now sealed for underwriting.",
                name=name,
                id_masked=id_masked,
                signed_at=session.get("signature_at"),
            )
        if step_id == "media_offer":
            n = len(session["media"])
            if n:
                return _i18n_ack(
                    session, "media_with",
                    f"Received {n} attachment{'s' if n > 1 else ''} - our underwriting bot will review them with your file.",
                    n=n,
                )
            return _i18n_ack(
                session, "media_none",
                "No problem - we can always request documents later if underwriting needs them.",
            )
        return None

    def _milestone_messages(self, session: Dict[str, Any], step_id: str,
                            events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []
        if step_id == "daily_function":
            assessment = self._run_assessment(session)
            events.append(self._journey_add(session, "questions_completed"))
            events.append(self._journey_add(
                session, "assessed", actor="underwriting_bot",
                meta={"risk_category": assessment.get("risk_category"),
                      "recommendation": assessment.get("recommendation_type"),
                      "confidence": assessment.get("confidence"),
                      "adl_level": assessment.get("adl_level"),
                      "engine_version": assessment.get("engine_version")}))
            msgs.append(self._transcript_add(
                session, "bot", self._assessment_narrative(assessment),
                kind="assessment", meta={"assessment": {
                    "risk_category": assessment.get("risk_category"),
                    "recommendation_type": assessment.get("recommendation_type"),
                    "confidence": assessment.get("confidence"),
                    "engine_version": assessment.get("engine_version"),
                    "adl_level": assessment.get("adl_level"),
                }}))
        elif step_id == "savings_addon":
            quote = self._run_quote(session)
            # Version provenance travels with the journey event so BI can prove
            # which actuarial tables and pricing config produced this price.
            events.append(self._journey_add(
                session, "quoted", actor="pricing_kernel",
                meta={"monthly": quote.get("monthly"),
                      "annual": quote.get("annual"),
                      "pricing_source": quote.get("pricing_source"),
                      "integrity_hash": quote.get("integrity_hash"),
                      "product_id": quote.get("product_id"),
                      "tables_version": quote.get("tables_version"),
                      "config_version": quote.get("config_version"),
                      "savings_formula": quote.get("savings_formula"),
                      "savings_rate_used": quote.get("savings_rate_used"),
                      "adl_level": quote.get("adl_level"),
                      "underwriting_loading": quote.get("underwriting_loading")}))
            msgs.append(self._transcript_add(
                session, "bot", self._quote_narrative(quote),
                kind="quote", meta={"quote": quote}))
        return msgs

    # Functional independence answer -> actuarial ADL severity level.
    # 5 is the standard/neutral level in the actuary's ADL multiplier tables;
    # higher levels carry the published loadings and exclusion rules.
    _ADL_BY_DAILY_FUNCTION = {
        "full": 5,
        "minor": 6,
        "moderate": 7,
        "significant": 8,
    }

    # Savings add-on choice -> markup on the risk premium, matching the
    # actuary dashboard's ``risk_premium_markup`` savings formula.
    _SAVINGS_RATE_BY_CHOICE = {
        "none": 0.0,
        "light": 0.25,
        "balanced": 0.50,
        "growth": 1.00,
    }

    def _adl_level_for(self, session: Dict[str, Any]) -> int:
        answer = str(session["answers"].get("daily_function") or "full").lower()
        return int(self._ADL_BY_DAILY_FUNCTION.get(answer, 5))

    def _savings_rate_for(self, session: Dict[str, Any]) -> float:
        answer = str(session["answers"].get("savings_addon") or "none").lower()
        return float(self._SAVINGS_RATE_BY_CHOICE.get(answer, 0.0))

    def _run_assessment(self, session: Dict[str, Any]) -> Dict[str, Any]:
        answers = session["answers"]
        conditions = parse_conditions_text(answers.get("conditions_list", ""))
        # Family history and hazardous activities add light, explainable
        # loadings on top of the shared deterministic scoring engine.
        fam = answers.get("family_history") or []
        for item in fam:
            if item != "none":
                conditions.append({
                    "condition": f"family history: {item}",
                    "risk_impact": 0.03,
                    "loading_percentage": 0,
                    "severity": "family_history",
                    "exclusion_recommended": False,
                })
        hazardous = answers.get("hazardous")
        if hazardous == "regular":
            conditions.append({"condition": "regular hazardous activities",
                               "risk_impact": 0.08, "loading_percentage": 10,
                               "severity": "lifestyle", "exclusion_recommended": False})
        elif hazardous == "occasional":
            conditions.append({"condition": "occasional hazardous activities",
                               "risk_impact": 0.04, "loading_percentage": 5,
                               "severity": "lifestyle", "exclusion_recommended": False})
        if answers.get("surgery") == "yes":
            conditions.append({"condition": f"recent surgery: {answers.get('surgery_list', '')}"[:120],
                               "risk_impact": 0.05, "loading_percentage": 5,
                               "severity": "history", "exclusion_recommended": False})

        h, w = answers.get("height"), answers.get("weight")
        bmi = round(w / ((h / 100) ** 2), 1) if h and w else None
        age = _calculate_age(answers.get("dob", ""))

        try:
            from services.underwriting_risk_scoring import score_risk_inputs
            scores = score_risk_inputs(
                age=age,
                medical_conditions=conditions,
                smoking_status=answers.get("tobacco"),
                claims_count=0,
                bmi=bmi,
            )
        except Exception as exc:  # pragma: no cover - engine is deterministic
            logger.warning("Chat application risk scoring failed: %s", exc)
            scores = {"risk_category": "moderate", "recommendation_type": "approve_standard",
                      "confidence": 0.5, "overall_risk": None, "engine_version": "unavailable"}

        scores["bmi"] = bmi
        scores["age"] = age
        scores["conditions_considered"] = [c["condition"] for c in conditions]
        scores["adl_level"] = self._adl_level_for(session)
        session["assessment"] = scores
        return scores

    def _assessment_narrative(self, assessment: Dict[str, Any]) -> str:
        category = str(assessment.get("risk_category") or "moderate").replace("_", " ")
        rec = assessment.get("recommendation_type")
        confidence = assessment.get("confidence") or 0.8
        base = (f"Here's my professional read: your risk profile comes out **{category}** "
                f"(confidence {int(confidence * 100)}%). ")
        if rec == "auto_approve":
            return base + "Frankly, this is as clean as applications get - I expect instant approval."
        if rec == "approve_standard":
            return base + "I expect a smooth, standard approval - no loadings, no exclusions."
        if rec == "approve_with_loading":
            return base + ("Underwriting will likely apply a modest premium loading, "
                           "but approval looks very achievable.")
        if rec == "approve_with_exclusions":
            return base + ("I expect approval with some specific exclusions - I'll flag them "
                           "clearly before anything is final.")
        if rec == "refer_senior_uw":
            return base + ("Your file will get a senior underwriter's personal review - "
                           "that's normal for profiles like yours, and I'll shepherd it through.")
        return base + "A human underwriter will take a careful look before we decide together."

    def _run_quote(self, session: Dict[str, Any]) -> Dict[str, Any]:
        answers = session["answers"]
        assessment = session.get("assessment") or {}
        payload = self.build_submission_payload(session, include_files=False)
        quote: Optional[Dict[str, Any]] = None
        try:
            from services.pricing_shadow_service import price_application_with_kernel
            quote = price_application_with_kernel(payload)
        except Exception as exc:
            logger.warning("Actuarial kernel quote failed, using flat fallback: %s", exc)

        if not quote:
            age = _calculate_age(answers.get("dob", "")) or 30
            coverage = float(answers.get("coverage_amount") or 500000)
            risk_mult = {
                "very_low": 0.9, "low": 1.0, "medium": 1.15, "moderate": 1.25,
                "elevated": 1.35, "high": 1.45, "very_high": 1.6,
            }.get(self._payload_risk_score(assessment), 1.0)
            savings_rate = self._savings_rate_for(session)
            monthly = round(
                (coverage / 1000) * 0.25
                * (1.0 + max(0, age - 25) * 0.015)
                * risk_mult
                * (1.0 + savings_rate),
                2,
            )
            quote = {
                "monthly": monthly,
                "quarterly": round(monthly * 3 * 0.97, 2),
                "annual": round(monthly * 12 * 0.90, 2),
                "pricing_source": "flat_fallback",
                "savings_rate_used": savings_rate,
                "adl_level": self._adl_level_for(session),
            }
        quote["quoted_at"] = _utc_now_iso()
        quote["coverage_amount"] = answers.get("coverage_amount")
        quote["coverage_years"] = int(answers.get("coverage_years") or 20)
        session["quote"] = quote
        return quote

    def _quote_narrative(self, quote: Dict[str, Any]) -> str:
        kernel = quote.get("pricing_source") == "pricing_kernel"
        # The pricing kernel declines lives whose ADL meets the actuary's
        # published decline threshold. Surface that outcome instead of
        # presenting a purchasable price the underwriting rules forbid.
        if kernel and (quote.get("adl_declined") or quote.get("eligible") is False):
            return (
                "Based on your current functional-needs answers, I can't offer an "
                "automated quote right now - our underwriting rules refer applications "
                "at this level to a senior underwriter, who will reach out to review "
                "your options with you personally."
            )
        src = ("our actuarial pricing kernel (versioned mortality and disability tables)"
               if kernel else "our standard rate card")
        monthly = quote.get("monthly") or 0
        annual = quote.get("annual") or 0
        parts = [
            f"Here's your personalized quote, priced by {src}: "
            f"${monthly:,.2f}/month, or ${annual:,.2f}/year if you pay annually (10% off)."
        ]
        if kernel:
            risk = float(quote.get("risk_premium_annual") or 0)
            savings = float(quote.get("savings_premium_annual") or 0)
            if savings > 0:
                parts.append(
                    f"That splits into ${risk:,.2f}/year of protection and "
                    f"${savings:,.2f}/year of savings accumulation."
                )
            if quote.get("disability_excluded"):
                parts.append(
                    "Because of your current functional needs, this quote covers life "
                    "protection only - the disability benefit is excluded, and an "
                    "underwriter will walk you through the options."
                )
            parts.append(
                f"Priced on tables {quote.get('tables_version')} / config "
                f"{quote.get('config_version')}."
            )
        parts.append(
            "Every figure is hash-sealed on our ledger, so the price you see is the price you get."
        )
        return " ".join(parts)

    def _payload_risk_score(self, assessment: Dict[str, Any]) -> str:
        """Pass the underwriting band straight through to the pricing kernel.

        The kernel keeps a loading for every band the scoring engine can emit,
        so collapsing bands here would silently under- or over-price
        (e.g. ``moderate`` is a +15% band, not a neutral one).
        """
        category = str(assessment.get("risk_category") or "moderate").strip().lower()
        known = {"very_low", "low", "medium", "moderate", "elevated", "high", "very_high"}
        return category if category in known else "medium"

    # ------------------------------------------------------------------
    # OTP integration hooks (state only - delivery lives in the API layer)
    # ------------------------------------------------------------------

    def note_otp_requested(self, application_id: str, verification_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            if not session["contact"].get("email"):
                return {"ok": False, "status_code": 409,
                        "error": "I need your email before I can send a verification code."}
            session["otp"] = {"verification_id": verification_id,
                              "requested_at": _utc_now_iso()}
            return {"ok": True, "email": session["contact"]["email"],
                    "phone": session["contact"].get("phone")}

    def contact_email(self, application_id: str) -> Optional[str]:
        with self._lock:
            session = self._get(application_id)
            return session["contact"].get("email") if session else None

    def pending_verification_id(self, application_id: str) -> Optional[str]:
        with self._lock:
            session = self._get(application_id)
            return (session or {}).get("otp", {}).get("verification_id")

    def mark_email_verified(self, application_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            was_reverify = session["status"] == "pending_reverify"
            # Snapshot the conversation captured so far *before* appending the
            # welcome-back messages, so a secure (OTP-gated) resume can restore
            # the full history only after identity is re-proven.
            prior_transcript = list(session["transcript"]) if was_reverify else None
            session["email_verified"] = True
            session["otp"] = {}
            events: List[Dict[str, Any]] = []
            bot_msgs: List[Dict[str, Any]] = []
            if was_reverify:
                session["status"] = "in_progress"
                events.append(self._journey_add(session, "continued",
                                                meta={"via": "resume_code+otp"}))
                bot_msgs.append(self._transcript_add(
                    session, "bot",
                    f"Welcome back{', ' + session['contact']['name'].split(' ')[0] if session['contact'].get('name') else ''}! "
                    "Identity confirmed - let's pick up right where we left off.",
                    kind="resumed"))
            else:
                events.append(self._journey_add(session, "otp_verified"))
            step = self._next_step(session)
            step_pub = self._step_public(session, step)
            if step_pub:
                bot_msgs.append(self._transcript_add(session, "bot", step_pub["prompt"],
                                                     kind="question",
                                                     meta={"step": step_pub["id"]}))
            events.extend(self._ledger_for_message(session, m) for m in bot_msgs)
            result = {"ok": True, "messages": bot_msgs, "step": step_pub,
                      "progress": self._progress(session), "ledger_events": events}
            if prior_transcript is not None:
                result["transcript"] = prior_transcript
            return result

    # ------------------------------------------------------------------
    # media
    # ------------------------------------------------------------------

    def attach_media(self, application_id: str, *, kind: str, name: str,
                     mime_type: str, data_b64: str,
                     duration_seconds: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409,
                        "error": "This application was already submitted."}
            if not session["email_verified"]:
                return {"ok": False, "status_code": 403,
                        "error": "Please verify your email before uploading attachments."}
            kind = str(kind or "").strip().lower()
            if kind not in ALLOWED_MEDIA_KINDS:
                return {"ok": False, "status_code": 400,
                        "error": f"kind must be one of {', '.join(ALLOWED_MEDIA_KINDS)}"}
            if len(session["media"]) >= MAX_MEDIA_ITEMS:
                return {"ok": False, "status_code": 400,
                        "error": f"Maximum {MAX_MEDIA_ITEMS} attachments per application."}

            raw_b64 = str(data_b64 or "")
            if "," in raw_b64 and raw_b64.strip().lower().startswith("data:"):
                raw_b64 = raw_b64.split(",", 1)[1]
            try:
                blob = base64.b64decode(raw_b64, validate=True)
            except Exception:
                return {"ok": False, "status_code": 400, "error": "Invalid base64 payload"}
            if not blob:
                return {"ok": False, "status_code": 400, "error": "Empty attachment"}
            if len(blob) > MAX_MEDIA_BYTES:
                return {"ok": False, "status_code": 400,
                        "error": f"Attachment exceeds {MAX_MEDIA_BYTES // (1024 * 1024)}MB limit."}
            total = sum(m["size"] for m in session["media"]) + len(blob)
            if total > MAX_TOTAL_MEDIA_BYTES:
                return {"ok": False, "status_code": 400,
                        "error": "Total attachments exceed the per-application size budget."}

            media_id = f"CHMEDIA-{secrets.token_hex(4).upper()}"
            item = {
                "id": media_id,
                "kind": kind,
                "name": str(name or f"{kind}-{media_id}").strip()[:200],
                "mime_type": str(mime_type or "application/octet-stream")[:100],
                "size": len(blob),
                "sha256": _sha256_hex(blob),
                "data_b64": raw_b64,
                "duration_seconds": duration_seconds,
                "uploaded_at": _utc_now_iso(),
            }
            # Persist the bytes immediately. The chat session is in-memory, so
            # without this a voice note or video only survives until finalize
            # (and not at all past a restart).
            item.update(self._persist_media_blob(session, item, raw_b64))
            session["media"].append(item)

            kind_label = {"voice": "voice note", "video": "video message",
                          "document": "document", "image": "image"}[kind]
            user_entry = self._transcript_add(
                session, "user", f"Sent a {kind_label}: {item['name']}",
                kind=f"media_{kind}",
                meta={"media_id": media_id, "size": item["size"],
                      "sha256": item["sha256"], "mime_type": item["mime_type"]})
            bot_entry = self._transcript_add(
                session, "bot",
                f"Got your {kind_label} - it's sealed into your file "
                f"(fingerprint {item['sha256'][:12]}...).",
                kind="media_ack", meta={"media_id": media_id})
            events = [
                self._ledger_for_message(session, user_entry),
                self._journey_add(session, "media_attached", meta={
                    "media_id": media_id, "kind": kind,
                    "sha256": item["sha256"], "size": item["size"]}),
                self._ledger_for_message(session, bot_entry),
            ]
            public = {k: v for k, v in item.items() if k != "data_b64"}
            return {"ok": True, "media": public, "messages": [bot_entry],
                    "ledger_events": events}

    _MEDIA_EXTENSIONS = {
        "voice": ".webm",
        "video": ".webm",
        "image": ".png",
        "document": ".pdf",
    }

    def _persist_media_blob(self, session: Dict[str, Any], item: Dict[str, Any],
                            raw_b64: str) -> Dict[str, Any]:
        """Write chat media to the durable document store.

        Returns the persistence fields to merge onto the media item. Failures
        are non-fatal: the upload still succeeds and the in-memory copy is
        used, but ``persistence_status`` records that durability is degraded.
        """
        name = str(item.get("name") or "")
        if "." not in name.rsplit("/", 1)[-1]:
            name = f"{name or item['id']}{self._MEDIA_EXTENSIONS.get(item['kind'], '.bin')}"
        try:
            from services.document_processing_service import get_document_service

            result = get_document_service().upload_document(
                file_name=name,
                file_data_b64=raw_b64,
                mime_type=item.get("mime_type"),
                document_type=item.get("kind"),
                description=f"Chat application {item['kind']} attachment",
                entity_type="chat_application",
                entity_id=session["id"],
                uploaded_by=session["contact"].get("email") or session["id"],
                uploaded_by_role="applicant",
                skip_processing=True,
            )
        except Exception as exc:
            logger.warning(
                "Chat media persistence failed for %s (%s): %s",
                item.get("id"), item.get("kind"), exc,
            )
            return {"persistence_status": "memory_only", "persistent_doc_id": None}

        stored_sha = str(getattr(result, "sha256", "") or "")
        if stored_sha and stored_sha != item.get("sha256"):
            # Never let a mismatched write masquerade as durable storage.
            logger.error(
                "Chat media checksum mismatch for %s: session=%s store=%s",
                item.get("id"), item.get("sha256"), stored_sha,
            )
            return {"persistence_status": "integrity_mismatch", "persistent_doc_id": None}

        return {
            "persistence_status": (
                "stored" if getattr(result, "status", "") == "uploaded" else "degraded"
            ),
            "persistent_doc_id": getattr(result, "document_id", None),
            "storage_path": getattr(result, "storage_path", None),
        }

    def load_media_bytes_b64(self, item: Dict[str, Any]) -> Optional[str]:
        """Return base64 bytes for a media item, preferring durable storage."""
        doc_id = item.get("persistent_doc_id")
        if doc_id:
            try:
                from services.document_processing_service import get_document_service

                record = get_document_service().get_document(doc_id, include_data=True)
                if record and record.get("integrity_warning"):
                    logger.error(
                        "Chat media integrity warning on read-back for %s; "
                        "falling back to session copy", doc_id,
                    )
                else:
                    data_b64 = (record or {}).get("data") or (record or {}).get("data_b64")
                    if data_b64:
                        return str(data_b64)
            except Exception as exc:
                logger.warning("Chat media read-back failed for %s: %s", doc_id, exc)
        return item.get("data_b64")

    # ------------------------------------------------------------------
    # pause / resume
    # ------------------------------------------------------------------

    def pause_session(self, application_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409,
                        "error": "This application was already submitted."}
            session["status"] = "paused"
            events = [self._journey_add(session, "stopped")]
            bot_entry = self._transcript_add(
                session, "bot",
                f"No problem - everything is saved. Come back with resume code "
                f"{session['resume_code']} and your email, and we'll continue exactly here.",
                kind="paused", meta={"resume_code": session["resume_code"]})
            events.append(self._ledger_for_message(session, bot_entry))
            return {"ok": True, "resume_code": session["resume_code"],
                    "messages": [bot_entry], "ledger_events": events}

    def resume_session(self, resume_code: str, email: str) -> Dict[str, Any]:
        with self._lock:
            code = str(resume_code or "").strip().upper()
            app_id = self._resume_index.get(code)
            session = self._sessions.get(app_id) if app_id else None
            if not session:
                # One generic error avoids resume-code / email enumeration.
                return {"ok": False, "status_code": 404,
                        "error": "We couldn't match that resume code and email."}
            stored_email = (session["contact"].get("email") or "").strip().lower()
            claimed = str(email or "").strip().lower()
            # Once an email is on file, resuming requires it to match (this
            # blocks resume-code enumeration). Before the email step there is
            # nothing to match, so a valid resume code alone reopens the
            # (pre-contact) session the bot promised was saved.
            if stored_email and stored_email != claimed:
                return {"ok": False, "status_code": 404,
                        "error": "We couldn't match that resume code and email."}

            if session["status"] == "submitted":
                sub = session.get("submission") or {}
                return {"ok": True, "application_id": session["id"],
                        "status": "submitted",
                        "submission": {k: sub.get(k) for k in
                                       ("policy_id", "underwriting_id", "submitted_at")},
                        "ledger_events": []}

            events: List[Dict[str, Any]] = []
            if session["email_verified"]:
                # Re-challenge: a resume code alone must never unlock a
                # verified session full of PII.
                session["status"] = "pending_reverify"
                session["email_verified"] = False
                return {"ok": True, "application_id": session["id"],
                        "status": "pending_reverify", "otp_required": True,
                        "email": session["contact"]["email"],
                        "masked_email": _mask_email(session["contact"]["email"]),
                        "ledger_events": events}

            session["status"] = "in_progress"
            events.append(self._journey_add(session, "continued",
                                            meta={"via": "resume_code"}))
            bot_entry = self._transcript_add(
                session, "bot", "Welcome back! Let's continue where we stopped.",
                kind="resumed")
            events.append(self._ledger_for_message(session, bot_entry))
            step = self._next_step(session)
            return {"ok": True, "application_id": session["id"],
                    "status": "in_progress",
                    "messages": [bot_entry],
                    "transcript": session["transcript"],
                    "step": self._step_public(session, step),
                    "progress": self._progress(session),
                    "ledger_events": events}

    # ------------------------------------------------------------------
    # state / finalize
    # ------------------------------------------------------------------

    def authorize_access(self, application_id: str, resume_code: Optional[str],
                         staff: bool) -> bool:
        session = self._get(application_id)
        if not session:
            return False
        if staff:
            return True
        return bool(resume_code) and \
            str(resume_code).strip().upper() == session["resume_code"]

    def get_state(self, application_id: str, *, staff: bool = False) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            step = self._next_step(session)
            answers_public = {k: ("***" if k == "payment_card" else v)
                              for k, v in session["answers"].items()}
            state = {
                "ok": True,
                "application_id": session["id"],
                "status": session["status"],
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "email_verified": session["email_verified"],
                "contact": {"name": session["contact"].get("name"),
                            "email": _mask_email(session["contact"].get("email") or "")
                            if session["contact"].get("email") else None,
                            "phone": session["contact"].get("phone")},
                "transcript": session["transcript"],
                "step": self._step_public(session, step),
                "progress": self._progress(session),
                "assessment": session.get("assessment"),
                "quote": session.get("quote"),
                "media": [{k: v for k, v in m.items() if k != "data_b64"}
                          for m in session["media"]],
                "journey": session["journey"],
                "invited_by": session.get("invited_by"),
                "submission": session.get("submission"),
                "language": session.get("language") or "en",
                "uw_decision": session.get("uw_decision"),
            }
            if staff:
                state["answers"] = answers_public
                state["resume_code"] = session["resume_code"]
                state["contact"] = session["contact"]
            return state

    def build_submission_payload(self, session: Dict[str, Any],
                                 include_files: bool = True) -> Dict[str, Any]:
        """Shape the collected answers exactly like the classic apply form."""
        answers = session["answers"]
        contact = session["contact"]
        assessment = session.get("assessment") or {}
        age = _calculate_age(answers.get("dob", "")) or 30
        tobacco = answers.get("tobacco", "no")
        smoking_status = {"yes": "smoker", "former": "former"}.get(tobacco, "nonsmoker")
        family = answers.get("family_history") or []
        card = answers.get("payment_card") or {}
        adl_level = self._adl_level_for(session)
        savings_rate = self._savings_rate_for(session)
        quote = session.get("quote") or {}

        payload: Dict[str, Any] = {
            "customer_name": contact.get("name") or "",
            "customer_email": contact.get("email") or "",
            "customer_phone": contact.get("phone") or "",
            "customer_dob": answers.get("dob") or "",
            "type": "phins_unified",
            "coverage_amount": answers.get("coverage_amount") or 500000,
            "coverage_years": int(answers.get("coverage_years") or 20),
            "term_years": int(answers.get("coverage_years") or 20),
            "age": age,
            "gender": answers.get("gender") or "",
            "smoking_status": smoking_status,
            "risk_score": self._payload_risk_score(assessment),
            # Actuarial pricing inputs: ADL severity drives the disability
            # multipliers / benefit table, savings_rate is the risk-premium
            # markup the actuary's savings formula expects.
            "adl_level": adl_level,
            "savings_rate": savings_rate,
            "savings_formula": "risk_premium_markup",
            "medical_exam_required": (
                answers.get("medical_conditions") == "yes"
                or answers.get("surgery") == "yes"
            ),
            "questionnaire": {
                "smoke": tobacco,
                "tobacco": tobacco,
                "gender": answers.get("gender") or "",
                "medical_conditions": answers.get("medical_conditions") or "no",
                "conditions_list": answers.get("conditions_list") or "",
                "surgery": answers.get("surgery") or "no",
                "surgery_list": answers.get("surgery_list") or "",
                "hazardous_activities": answers.get("hazardous") or "no",
                "family_history": ",".join(f for f in family if f != "none"),
                "medications": answers.get("medications") or "",
                "height": str(answers.get("height") or ""),
                "weight": str(answers.get("weight") or ""),
                "occupation": answers.get("occupation") or "",
                "daily_function": answers.get("daily_function") or "full",
                "adl_level": adl_level,
                "prior_disclosure": answers.get("prior_disclosure") or "",
                "disclosure_mode": answers.get("disclosure_mode") or "open_disclosure",
                "signature_name": answers.get("signature_name") or "",
                "signature_at": answers.get("signature_at") or "",
                "id_number": answers.get("id_number") or "",
                "signature_image_sha256": answers.get("signature_image_sha256") or "",
            },
            "phins_allocation": {
                "protection_pct": int(round(100 / (1 + savings_rate))) if savings_rate else 100,
                "savings_pct": 100 - (int(round(100 / (1 + savings_rate))) if savings_rate else 100),
                "distribution": {"wallet_pct": 15, "investment_pct": 60,
                                 "algo_trading_pct": 25},
            },
            "payment": {
                "card_number": card.get("card_number") or "",
                "cvv": card.get("cvv") or "",
                "expiry_month": card.get("expiry_month") or "",
                "expiry_year": card.get("expiry_year") or "",
                "cardholder_name": card.get("cardholder_name") or "",
                "billing_frequency": answers.get("billing_frequency") or "monthly",
                "auto_pay": answers.get("auto_pay") == "yes",
            },
            "consent": {
                "accepted": bool(answers.get("consent")),
                "accepted_at": answers.get("consent_accepted_at"),
                "version": answers.get("consent_version") or CONSENT_VERSION,
            },
            "prior_disclosure": {
                "mode": answers.get("disclosure_mode") or "open_disclosure",
                "text": answers.get("prior_disclosure") or "",
                "acknowledged_at": answers.get("prior_disclosure_at"),
                "contradiction_codes": list(answers.get("contradiction_codes") or []),
                "confidentiality_waiver": True,
            },
            "signature": {
                "name": answers.get("signature_name") or "",
                "signed_at": answers.get("signature_at"),
                "method": answers.get("signature_method") or "drawn_canvas",
                "id_number": answers.get("id_number") or "",
                "image_sha256": answers.get("signature_image_sha256") or "",
                "image_data": answers.get("signature_data") or None,
                "mandatory": True,
            },
            "id_number": answers.get("id_number") or "",
            "questionnaire_version": QUESTIONNAIRE_VERSION,
            "acknowledgements": [
                "I confirm the answers I provided are accurate to the best of my knowledge.",
                "I understand incomplete or inaccurate information may delay or void coverage.",
                "I authorize PHINS to use this information for underwriting and claim processing.",
                "I understand I am waiving medical confidentiality for underwriting analysis of the facts I disclosed.",
                "I electronically signed this application with my legal name and drawn signature and intend it as my binding signature.",
            ],
            "health_wallet": {"enabled": True, "monthly_deposit": 0},
            "pipeline_enabled": True,
            "savings_pipeline_enabled": bool(savings_rate),
            "application_channel": "chat",
            "chat_application_id": session["id"],
        }
        # Version consistency: the price the customer accepted is stamped with
        # the exact actuarial table + config revision that produced it.
        if quote:
            payload["quote_provenance"] = {
                "pricing_source": quote.get("pricing_source"),
                "product_id": quote.get("product_id"),
                "tables_version": quote.get("tables_version"),
                "config_version": quote.get("config_version"),
                "integrity_hash": quote.get("integrity_hash"),
                "savings_formula": quote.get("savings_formula"),
                "savings_rate_used": quote.get("savings_rate_used"),
                "underwriting_loading": quote.get("underwriting_loading"),
                "adl_level": quote.get("adl_level"),
                "quoted_monthly": quote.get("monthly"),
                "quoted_annual": quote.get("annual"),
                "quoted_at": quote.get("quoted_at"),
                "engine_version": (assessment or {}).get("engine_version"),
            }
        if include_files and session["media"]:
            files = []
            for item in session["media"]:
                entry = {
                    "name": item["name"],
                    "type": item["mime_type"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                    "kind": item["kind"],
                    "duration_seconds": item.get("duration_seconds"),
                    "persistent_doc_id": item.get("persistent_doc_id"),
                    "storage_path": item.get("storage_path"),
                }
                if item["size"] <= MAX_INLINE_SUBMISSION_BYTES:
                    data_b64 = self.load_media_bytes_b64(item) or item.get("data_b64")
                    entry["data"] = f"data:{item['mime_type']};base64,{data_b64}"
                elif item.get("persistent_doc_id"):
                    # Oversized for an inline copy, but the bytes are durable:
                    # the underwriting record links to the document store.
                    entry["data"] = None
                    entry["note"] = (
                        f"Stored in the document vault as {item['persistent_doc_id']}"
                    )
                else:
                    entry["data"] = None
                    entry["note"] = "Attachment bytes unavailable (durable storage failed)"
                files.append(entry)
            payload["files"] = files
            payload["files_count"] = len(files)
        return payload

    def prepare_finalize(self, application_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409,
                        "error": "This application was already submitted.",
                        "submission": session.get("submission")}
            if session.get("finalizing"):
                # A submission is already in flight for this session; refuse a
                # concurrent finalize so two loopbacks can't each create a
                # policy (the lock is released during the loopback request).
                return {"ok": False, "status_code": 409,
                        "error": "This application is already being submitted."}
            if not session["email_verified"]:
                return {"ok": False, "status_code": 403,
                        "error": "Please verify your email before submitting."}
            missing = [s["id"] for s in self._steps_for(session)
                       if s["id"] not in session["answers"]]
            if missing:
                return {"ok": False, "status_code": 409,
                        "error": f"Still missing answers for: {', '.join(missing)}"}
            # Do not submit lives the actuary's underwriting rules decline: the
            # kernel quote flags these, and the portfolio path skips them.
            # Callers MUST queue a senior-UW referral record so staff can
            # contact the applicant (chat sessions alone are in-memory).
            quote = session.get("quote") or {}
            if quote.get("adl_declined") or quote.get("eligible") is False:
                return {
                    "ok": False,
                    "status_code": 409,
                    "needs_senior_referral": True,
                    "error": (
                        "Based on your functional-needs answers, this "
                        "application needs a senior underwriter's review "
                        "before it can be submitted."
                    ),
                }
            payload = self.build_submission_payload(session)
            checksum = _checksum_payload(payload)
            session["pending_submission_checksum"] = checksum
            session["finalizing"] = True
            return {"ok": True, "payload": payload, "checksum": checksum,
                    "session": session}

    def abort_reverify(self, application_id: str) -> None:
        """Roll back a resume re-challenge whose OTP could not be delivered.

        ``resume_session`` flips a verified session to ``pending_reverify``
        with ``email_verified = False`` before the code is sent. If delivery
        fails we must restore the previous state: leaving ``email_verified``
        False would let the *next* resume attempt skip the OTP re-challenge
        entirely (it would take the unverified branch), and leaving the
        status ``pending_reverify`` would brick the session. Restoring
        ``paused`` + verified keeps the re-challenge guarantee intact for
        the next resume.
        """
        with self._lock:
            session = self._get(application_id)
            if session and session["status"] == "pending_reverify":
                session["status"] = "paused"
                session["email_verified"] = True
                session["otp"] = {}

    def clear_finalizing(self, application_id: str) -> None:
        """Release the in-flight finalize guard (e.g. when the loopback fails)."""
        with self._lock:
            session = self._get(application_id)
            if session and session["status"] != "submitted":
                session["finalizing"] = False

    def mark_submitted(self, application_id: str, *, policy_id: str,
                       underwriting_id: str, customer_id: Optional[str],
                       checksum: str,
                       provisioned_login: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            if session["status"] == "submitted":
                # Idempotent guard: never overwrite an existing submission (and
                # its policy ids) if a second finalize somehow reaches here.
                return {"ok": False, "status_code": 409,
                        "error": "This application was already submitted.",
                        "submission": session.get("submission")}
            session["status"] = "submitted"
            session["finalizing"] = False
            session["customer_id"] = customer_id
            # PCI DSS: the card was needed only for the one-shot policy-create
            # loopback (already tokenized downstream, which keeps last4). Never
            # retain the PAN or the CVV on the session after authorization.
            card = session["answers"].get("payment_card")
            if isinstance(card, dict):
                session["answers"]["payment_card"] = {
                    "card_last4": card.get("card_last4"),
                    "cardholder_name": card.get("cardholder_name"),
                    "expiry_month": card.get("expiry_month"),
                    "expiry_year": card.get("expiry_year"),
                }
            # Redact raw signature PNG after submission (hash remains for integrity).
            if session["answers"].get("signature_data"):
                session["answers"]["signature_data"] = None
            session["submission"] = {
                "policy_id": policy_id,
                "underwriting_id": underwriting_id,
                "customer_id": customer_id,
                "payload_checksum": checksum,
                "submitted_at": _utc_now_iso(),
            }
            events = [self._journey_add(
                session, "submitted", actor="applicant",
                meta={"policy_id": policy_id, "underwriting_id": underwriting_id,
                      "customer_id": customer_id, "payload_checksum": checksum})]
            first_name = (session["contact"].get("name") or "").split(" ")[0]
            name_part = f", {first_name}" if first_name else ""
            bot_entry = self._transcript_add(
                session, "bot",
                _i18n_msg(
                    session, "submitted",
                    (f"Congratulations{name_part}! Your application "
                     f"is officially in. Policy {policy_id} is with our underwriting team, "
                     f"reference {underwriting_id}. I've recorded every step of our conversation "
                     "on the PHINS ledger, so your file is complete and tamper-proof. "
                     "You'll hear from us shortly - usually within minutes, not days."),
                    name_part=name_part,
                    policy_id=policy_id,
                    underwriting_id=underwriting_id,
                ),
                kind="submitted",
                meta={"policy_id": policy_id, "underwriting_id": underwriting_id})
            events.append(self._ledger_for_message(session, bot_entry))
            return {"ok": True, "messages": [bot_entry],
                    "submission": session["submission"], "ledger_events": events}

    def post_underwriting_decision(
        self,
        chat_application_id: str,
        *,
        decision: str,
        policy_id: Optional[str] = None,
        underwriting_id: Optional[str] = None,
        monthly_premium: Optional[float] = None,
        premium_adjustment_pct: Optional[float] = None,
        reason: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append an auto bot answer when UW accepts, loads premium, or rejects.

        Called from the shared ``/api/underwriting/approve`` and
        ``/api/underwriting/reject`` handlers so chat applicants see the same
        outcome the classic form surfaces via email/portal, without breaking
        resume-code tracking.
        """
        with self._lock:
            session = self._get(chat_application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            decision_norm = str(decision or "").strip().lower()
            if decision_norm not in ("approved", "rejected"):
                return {"ok": False, "status_code": 400, "error": "Invalid decision"}

            # Idempotent: do not duplicate the same decision message.
            for entry in reversed(session.get("transcript") or []):
                if entry.get("kind") != "uw_decision":
                    continue
                meta = entry.get("meta") or {}
                if meta.get("decision") == decision_norm and (
                    not underwriting_id or meta.get("underwriting_id") == underwriting_id
                ):
                    return {
                        "ok": True,
                        "duplicate": True,
                        "messages": [entry],
                        "ledger_events": [],
                    }

            first_name = (session["contact"].get("name") or "").split(" ")[0]
            name_part = f", {first_name}" if first_name else ""
            events: List[Dict[str, Any]] = []
            loading = float(premium_adjustment_pct or 0)
            monthly = float(monthly_premium or 0)
            pol = policy_id or (session.get("submission") or {}).get("policy_id") or ""
            uw = underwriting_id or (session.get("submission") or {}).get("underwriting_id") or ""

            if decision_norm == "approved":
                loading_part = ""
                if abs(loading) >= 0.5:
                    loading_part = _i18n_msg(
                        session, "uw_approved_loading",
                        f" (including an underwriting adjustment of {loading:.0f}%)",
                        loading_pct=loading,
                    )
                text = _i18n_msg(
                    session, "uw_approved",
                    (f"Great news{name_part}! Underwriting **approved** your application. "
                     f"Policy {pol} is now active. Monthly premium: ${monthly:,.2f}"
                     f"{loading_part}. Your policy contract has been emailed to you."),
                    name_part=name_part,
                    policy_id=pol,
                    monthly=monthly,
                    loading_part=loading_part,
                )
                stage = "uw_approved"
            else:
                reason_part = ""
                if reason:
                    reason_part = _i18n_msg(
                        session, "uw_rejected_reason",
                        f" — reason: {reason}",
                        reason=reason,
                    )
                text = _i18n_msg(
                    session, "uw_rejected",
                    (f"An update on your application{name_part}: after review, underwriting "
                     f"**did not approve** coverage at this time{reason_part}. "
                     "A notification was sent to your email. You can contact us with questions."),
                    name_part=name_part,
                    reason_part=reason_part,
                )
                stage = "uw_rejected"

            bot_entry = self._transcript_add(
                session, "bot", text, kind="uw_decision",
                meta={
                    "decision": decision_norm,
                    "policy_id": pol,
                    "underwriting_id": uw,
                    "monthly_premium": monthly,
                    "premium_adjustment_pct": loading,
                    "reason": reason,
                    "notes": notes,
                },
            )
            events.append(self._journey_add(
                session, stage, actor="underwriter",
                meta={
                    "decision": decision_norm,
                    "policy_id": pol,
                    "underwriting_id": uw,
                    "monthly_premium": monthly,
                    "premium_adjustment_pct": loading,
                    "reason": reason,
                },
            ))
            events.append(self._ledger_for_message(session, bot_entry))
            session["uw_decision"] = {
                "decision": decision_norm,
                "policy_id": pol,
                "underwriting_id": uw,
                "monthly_premium": monthly,
                "premium_adjustment_pct": loading,
                "reason": reason,
                "decided_at": _utc_now_iso(),
            }
            return {
                "ok": True,
                "messages": [bot_entry],
                "uw_decision": session["uw_decision"],
                "ledger_events": events,
                "contact_email": (session.get("contact") or {}).get("email"),
                "contact_name": (session.get("contact") or {}).get("name"),
                "language": session.get("language") or "en",
            }

    # ------------------------------------------------------------------
    # BI / funnel
    # ------------------------------------------------------------------

    def needs_senior_referral(self, session_or_quote: Dict[str, Any]) -> bool:
        """True when the actuarial quote forbids automated submission."""
        quote = session_or_quote.get("quote") if "quote" in session_or_quote else session_or_quote
        quote = quote or {}
        return bool(quote.get("adl_declined") or quote.get("eligible") is False)

    def senior_referral_snapshot(self, application_id: str) -> Optional[Dict[str, Any]]:
        """Staff-facing payload used to open a durable underwriting queue row.

        Chat sessions live in process memory; the underwriter dashboard reads
        ``UNDERWRITING_APPLICATIONS``. This snapshot is the bridge.
        """
        with self._lock:
            session = self._get(application_id)
            if not session:
                return None
            quote = session.get("quote") or {}
            if not self.needs_senior_referral(quote):
                return None
            contact = dict(session.get("contact") or {})
            assessment = dict(session.get("assessment") or {})
            answers = dict(session.get("answers") or {})
            # Never hand payment PAN/CVV to the referral queue.
            card = answers.get("payment_card")
            if isinstance(card, dict):
                answers["payment_card"] = {
                    "card_last4": card.get("card_last4") or str(card.get("card_number") or "")[-4:],
                    "cardholder_name": card.get("cardholder_name"),
                    "expiry_month": card.get("expiry_month"),
                    "expiry_year": card.get("expiry_year"),
                }
            media = [
                {k: v for k, v in m.items() if k != "data_b64"}
                for m in (session.get("media") or [])
            ]
            return {
                "chat_application_id": session["id"],
                "resume_code": session.get("resume_code"),
                "status": session.get("status"),
                "email_verified": bool(session.get("email_verified")),
                "contact": contact,
                "answers": answers,
                "assessment": assessment,
                "quote": {
                    "pricing_source": quote.get("pricing_source"),
                    "eligible": quote.get("eligible"),
                    "adl_declined": quote.get("adl_declined"),
                    "decline_reason": quote.get("decline_reason"),
                    "adl_level": quote.get("adl_level"),
                    "adl_loading": quote.get("adl_loading"),
                    "disability_excluded": quote.get("disability_excluded"),
                    "adl_coverage_cap": quote.get("adl_coverage_cap"),
                    "coverage_amount": quote.get("coverage_amount") or answers.get("coverage_amount"),
                    "coverage_years": quote.get("coverage_years") or answers.get("coverage_years"),
                    "monthly": quote.get("monthly"),
                    "annual": quote.get("annual"),
                    "tables_version": quote.get("tables_version"),
                    "config_version": quote.get("config_version"),
                    "product_id": quote.get("product_id"),
                    "integrity_hash": quote.get("integrity_hash"),
                    "quoted_at": quote.get("quoted_at"),
                },
                "media": media,
                "journey": list(session.get("journey") or []),
                "existing_underwriting_id": (session.get("senior_referral") or {}).get(
                    "underwriting_id"
                ),
            }

    def mark_senior_referred(self, application_id: str, *, underwriting_id: str) -> Dict[str, Any]:
        """Record that staff now have a durable queue row for this chat file."""
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Application not found"}
            prior = session.get("senior_referral") or {}
            if prior.get("underwriting_id") == underwriting_id:
                return {"ok": True, "underwriting_id": underwriting_id, "ledger_events": []}
            session["senior_referral"] = {
                "underwriting_id": underwriting_id,
                "queued_at": _utc_now_iso(),
            }
            if session["status"] not in ("submitted", "paused", "pending_reverify"):
                session["status"] = "referred_senior_uw"
            events = [self._journey_add(
                session, "referred_senior_uw", actor="system",
                meta={"underwriting_id": underwriting_id,
                      "decline_reason": (session.get("quote") or {}).get("decline_reason"),
                      "adl_level": (session.get("quote") or {}).get("adl_level")})]
            return {"ok": True, "underwriting_id": underwriting_id, "ledger_events": events}

    def funnel_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            sessions = list(self._sessions.values())
        stages = {
            "started": 0, "contact_captured": 0, "otp_verified": 0,
            "questions_completed": 0, "quoted": 0, "payment_captured": 0,
            "referred_senior_uw": 0, "submitted": 0, "paused": 0,
            "invited": 0, "media_attached": 0,
        }
        items = []
        senior_queue = []
        for s in sessions:
            seen = {j["stage"] for j in s["journey"]}
            for stage in stages:
                if stage in seen:
                    stages[stage] += 1
            if s["status"] == "paused":
                # Pause records the journey stage as 'stopped', so the
                # journey-key loop above never sees 'paused'; count it here by
                # the live session status instead.
                stages["paused"] += 1
            quote = s.get("quote") or {}
            needs_senior = self.needs_senior_referral(quote)
            contact = s.get("contact") or {}
            item = {
                "application_id": s["id"],
                "status": s["status"],
                "created_at": s["created_at"],
                "updated_at": s["updated_at"],
                "email_verified": s["email_verified"],
                "progress": self._progress(s),
                "invited_by": s.get("invited_by"),
                "quote_monthly": quote.get("monthly"),
                "risk_category": (s.get("assessment") or {}).get("risk_category"),
                "policy_id": (s.get("submission") or {}).get("policy_id"),
                "customer_id": s.get("customer_id"),
                "journey_stages": sorted(seen),
                "needs_senior_review": needs_senior,
                "senior_underwriting_id": (s.get("senior_referral") or {}).get(
                    "underwriting_id"
                ),
                "contact_email": contact.get("email"),
                "contact_phone": contact.get("phone"),
                "contact_name": contact.get("name"),
                "adl_level": quote.get("adl_level") or (s.get("assessment") or {}).get(
                    "adl_level"
                ),
                "decline_reason": quote.get("decline_reason"),
            }
            items.append(item)
            if needs_senior and s["status"] != "submitted":
                senior_queue.append(item)
        total = len(sessions)
        submitted = stages["submitted"]
        return {
            "total_sessions": total,
            "stage_counts": stages,
            "conversion_rate": round(submitted / total, 3) if total else 0.0,
            "sessions": items,
            "senior_review_queue": senior_queue,
            "senior_review_pending": len(senior_queue),
        }

    def journey_for(self, application_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return None
            return {
                "application_id": session["id"],
                "customer_id": session.get("customer_id"),
                "invited_by": session.get("invited_by"),
                "journey": session["journey"],
                "submission": session.get("submission"),
            }


_service_singleton: Optional[ChatPolicyApplicationService] = None
_singleton_lock = threading.Lock()


def get_chat_application_service() -> ChatPolicyApplicationService:
    global _service_singleton
    if _service_singleton is None:
        with _singleton_lock:
            if _service_singleton is None:
                _service_singleton = ChatPolicyApplicationService()
    return _service_singleton


def reset_chat_application_service() -> None:
    """Test helper - drop all in-memory chat sessions."""
    global _service_singleton
    with _singleton_lock:
        _service_singleton = None
