"""
Conversational first notice of loss ("Phin" as the PHINS Claims Agent).

Same conversation contract as the policy chat (`services/chat_application_service.py`):
stateful steps, OTP gate, voice/video/document attachments, drawn signature,
pause/resume, and ledger events. Filing itself goes through `POST /api/claims/create`
so the claim, its files, the ledger, and assessment ingestion stay on the
existing claims pipeline.

Integrity rules:
- A logged-in customer's id is bound to the session. Edits change contact
  fields only.
- A public (no session) claimant may still confirm contact fields, but the
  verification code only goes to the contact already on the bound account, so
  an edited profile cannot redirect the OTP away from the policy holder.
- The national ID is reconciled through `customer_identity_service` and then
  dropped. Transcripts, the claim row, and the FNOL document keep nationality,
  last4, and the keyed hash.
- Media and the FNOL document are sha256-sealed. Finalize refuses success
  when the stored claim does not match the sealed facts.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import re
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("phins.claims_chat")

try:
    from services.phins_document import render_phins_document
except ImportError:  # pragma: no cover
    from phins_document import render_phins_document  # type: ignore

try:
    from services.chat_application_service import (
        _mask_email,
        _mask_phone,
        _validate_email,
        _validate_name,
        _validate_phone,
        _validate_signature,
    )
except ImportError:  # pragma: no cover
    from chat_application_service import (  # type: ignore
        _mask_email,
        _mask_phone,
        _validate_email,
        _validate_name,
        _validate_phone,
        _validate_signature,
    )

BOT_NAME = "Phin"
BOT_TITLE = "PHINS Claims Agent"

MAX_MEDIA_ITEMS = 8
MAX_MEDIA_BYTES = 4 * 1024 * 1024
MAX_TOTAL_MEDIA_BYTES = 6 * 1024 * 1024
ALLOWED_MEDIA_KINDS = ("voice", "video", "document", "image")
CONSENT_VERSION = "phins-claims-consent-v1"
QUESTIONNAIRE_VERSION = "phins-claims-chat-v1"

CLAIM_TYPES = (
    "medical", "hospitalization", "prescription", "dental", "vision",
    "therapy", "accident", "disability", "death_benefit", "other",
)
_ACTIVE_POLICY_STATUSES = {"active", "in_force", "issued"}

_CLAIMANT_STEP = {
    "id": "claimant",
    "prompt": (
        "Who is filing? Give me the customer's email or their policy number "
        "and I'll pull the account we already have."
    ),
    "input": {"type": "text", "placeholder": "name@example.com or POL-..."},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checksum_payload(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return _sha256_hex(canonical.encode("utf-8"))


def _codes_match(left: Any, right: Any) -> bool:
    a, b = str(left or ""), str(right or "")
    if not a or len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


def _customer_name(record: Dict[str, Any]) -> str:
    name = str(record.get("name") or "").strip()
    if name:
        return name
    parts = [record.get("first_name"), record.get("last_name")]
    return " ".join(str(p).strip() for p in parts if p and str(p).strip())


def _portal():
    try:
        from web_portal import server as portal
    except ImportError:  # pragma: no cover
        import server as portal  # type: ignore
    return portal


def active_policies_for(customer_id: str, policies: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Active policies owned by this customer, coverage included."""
    found: List[Dict[str, Any]] = []
    for key, policy in (policies or {}).items():
        if not isinstance(policy, dict):
            continue
        if str(policy.get("customer_id") or "") != str(customer_id):
            continue
        status = str(policy.get("status") or "").strip().lower()
        if status not in _ACTIVE_POLICY_STATUSES:
            continue
        coverage = policy.get("coverage_amount", policy.get("coverage", 0))
        try:
            coverage_f = float(coverage or 0)
        except (TypeError, ValueError):
            coverage_f = 0.0
        found.append({
            "id": str(policy.get("id") or key),
            "type": str(policy.get("type") or "policy"),
            "coverage_amount": coverage_f,
            "status": status,
            "start_date": str(policy.get("start_date") or policy.get("effective_date") or "")[:10],
        })
    found.sort(key=lambda item: item["id"])
    return found


def profile_from_customer(record: Dict[str, Any]) -> Dict[str, str]:
    return {
        "name": _customer_name(record),
        "email": str(record.get("email") or "").strip().lower(),
        "phone": str(record.get("phone") or "").strip(),
    }


def resolve_claimant(query: str) -> Dict[str, Any]:
    """Staff lookup: exact email or exact policy id. No partial matches."""
    text = str(query or "").strip()
    if len(text) < 3:
        return {"ok": False, "error": "Enter an email address or a policy number."}
    portal = _portal()
    customers = getattr(portal, "CUSTOMERS", {}) or {}
    policies = getattr(portal, "POLICIES", {}) or {}
    customer_id = None
    if "@" in text:
        wanted = text.lower()
        matches = [
            cid for cid, rec in customers.items()
            if isinstance(rec, dict) and str(rec.get("email") or "").strip().lower() == wanted
        ]
        if len(matches) > 1:
            return {"ok": False, "error": "More than one account uses that email. Use the policy number."}
        customer_id = matches[0] if matches else None
    else:
        wanted = text.upper()
        for key, policy in policies.items():
            if not isinstance(policy, dict):
                continue
            pid = str(policy.get("id") or key).upper()
            if pid == wanted:
                customer_id = policy.get("customer_id")
                break
    if not customer_id or customer_id not in customers or not isinstance(customers.get(customer_id), dict):
        return {"ok": False, "error": "I couldn't find that customer. Check the email or policy number."}
    record = customers[customer_id]
    return {
        "ok": True,
        "customer_id": str(customer_id),
        "profile": profile_from_customer(record),
        "policies": active_policies_for(str(customer_id), policies),
    }


def _choice_validator(options: List[str]):
    lowered = {str(o).lower(): o for o in options}

    def _validate(value: Any, _session: Dict[str, Any]) -> Tuple[bool, Any]:
        key = str(value or "").strip().lower()
        if key in lowered:
            return True, lowered[key]
        return False, f"Please pick one of: {', '.join(options)}."

    return _validate


def _validate_claimant(value: Any, session: Dict[str, Any]) -> Tuple[bool, Any]:
    resolved = resolve_claimant(str(value or ""))
    if not resolved.get("ok"):
        return False, resolved.get("error")
    session["_claimant_resolution"] = resolved
    return True, {
        "query": str(value).strip(),
        "customer_id": resolved["customer_id"],
    }


def _validate_profile(value: Any, session: Dict[str, Any]) -> Tuple[bool, Any]:
    if not isinstance(value, dict):
        return False, "Confirm your name, email, and mobile, or edit anything that changed."
    name_ok, name = _validate_name(value.get("name"), session)
    if not name_ok:
        return False, name
    email_ok, email = _validate_email(value.get("email"), session)
    if not email_ok:
        return False, email
    phone_ok, phone = _validate_phone(value.get("phone"), session)
    if not phone_ok:
        return False, phone
    prefill = session.get("prefill") or {}
    edited = any(
        str(prefill.get(field) or "").strip().lower() != str(cleaned).strip().lower()
        for field, cleaned in (("name", name), ("email", email), ("phone", phone))
        if prefill.get(field)
    )
    return True, {"name": name, "email": email, "phone": phone, "edited": edited}


def _validate_policy(value: Any, session: Dict[str, Any]) -> Tuple[bool, Any]:
    policies = session.get("policies") or []
    if not policies:
        return False, "This account has no active policy, so I can't open a claim yet."
    allowed = {p["id"]: p for p in policies}
    picked = str(value or "").strip()
    if picked not in allowed:
        return False, "Choose one of the active policies on this account."
    session["selected_policy"] = allowed[picked]
    return True, picked


def _validate_incident_date(value: Any, session: Dict[str, Any]) -> Tuple[bool, Any]:
    text = str(value or "").strip()
    try:
        incident = datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False, "Please give me the incident date as YYYY-MM-DD."
    today = datetime.now(timezone.utc).date()
    if incident > today:
        return False, "The incident date can't be in the future."
    if (today - incident).days > 3650:
        return False, "That incident date is more than 10 years ago. Please double-check it."
    start = str((session.get("selected_policy") or {}).get("start_date") or "")[:10]
    if start:
        try:
            start_d = datetime.strptime(start, "%Y-%m-%d").date()
        except ValueError:
            start_d = None
        if start_d and incident < start_d:
            return False, f"That date is before this policy started ({start})."
    return True, text


def _validate_location(value: Any, _session: Dict[str, Any]) -> Tuple[bool, Any]:
    text = " ".join(str(value or "").split())
    if len(text) < 2 or len(text) > 200:
        return False, "Where did it happen? A city, address, or place (2-200 characters)."
    return True, text


def _validate_narrative(value: Any, _session: Dict[str, Any]) -> Tuple[bool, Any]:
    text = str(value or "").strip()
    if len(text) < 20:
        return False, "Tell me what happened in a sentence or two (at least 20 characters)."
    if len(text) > 4000:
        return False, "That's a bit long for this step — keep it under 4000 characters. You can add documents next."
    return True, text


def _validate_amount(value: Any, session: Dict[str, Any]) -> Tuple[bool, Any]:
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError):
        return False, "Please give me the claimed amount as a number."
    if amount < 1:
        return False, "The claimed amount has to be at least 1."
    coverage = float((session.get("selected_policy") or {}).get("coverage_amount") or 0)
    if coverage <= 0:
        return False, "This policy has no coverage amount on file, so I can't accept an amount."
    if amount > coverage:
        return False, (
            f"That amount (${amount:,.2f}) is above the policy coverage (${coverage:,.2f})."
        )
    return True, amount


def _validate_provider(value: Any, _session: Dict[str, Any]) -> Tuple[bool, Any]:
    text = " ".join(str(value or "").split())
    if text.lower() in {"", "none", "n/a", "na", "-"}:
        return True, ""
    if len(text) > 200:
        return False, "Keep the provider name under 200 characters."
    return True, text


def _validate_media_step(value: Any, session: Dict[str, Any]) -> Tuple[bool, Any]:
    choice = str(value or "").strip().lower()
    if choice != "done":
        return False, "Attach a voice note, a video, or a document, then tap Done."
    if not session.get("media"):
        return False, (
            "I still need at least one attachment — a voice note, a video, or a document — "
            "before I can file this claim."
        )
    return True, "done"


def _post_otp_steps() -> List[Dict[str, Any]]:
    return [
        {
            "id": "policy_id",
            "prompt": "Which active policy should this claim be filed against?",
            "input": {"type": "choice", "options": []},
            "validate": _validate_policy,
        },
        {
            "id": "claim_type",
            "prompt": "What kind of claim is this?",
            "input": {
                "type": "choice",
                "options": list(CLAIM_TYPES),
                "labels": {
                    "medical": "Medical expense",
                    "hospitalization": "Hospitalization",
                    "prescription": "Prescription / medication",
                    "dental": "Dental",
                    "vision": "Vision",
                    "therapy": "Therapy / mental health",
                    "accident": "Accident / emergency",
                    "disability": "Disability",
                    "death_benefit": "Death benefit",
                    "other": "Other",
                },
            },
            "validate": _choice_validator(list(CLAIM_TYPES)),
        },
        {
            "id": "incident_date",
            "prompt": "What date did this happen?",
            "input": {"type": "date"},
            "validate": _validate_incident_date,
        },
        {
            "id": "incident_location",
            "prompt": "Where did it happen? A city, clinic, or address is enough.",
            "input": {"type": "text", "placeholder": "e.g. Tel Aviv, Ichilov ER"},
            "validate": _validate_location,
        },
        {
            "id": "accident_narrative",
            "prompt": (
                "In your own words, what happened? Include what you were doing, "
                "what went wrong, and what care or loss followed."
            ),
            "input": {"type": "text", "placeholder": "Describe the accident or loss"},
            "validate": _validate_narrative,
        },
        {
            "id": "claimed_amount",
            "prompt": "What amount are you claiming? I'll hold it inside the policy coverage.",
            "input": {"type": "number", "min": 1, "suffix": "USD"},
            "validate": _validate_amount,
        },
        {
            "id": "provider",
            "prompt": "Who treated you or who is the other party? Type \"none\" if there isn't one.",
            "input": {"type": "text", "placeholder": "Hospital, clinic, or other party"},
            "validate": _validate_provider,
        },
        {
            "id": "media_offer",
            "prompt": (
                "Now the evidence. Record a voice note, a short video, or upload documents "
                "(photos, bills, a police report). At least one file is required. "
                "Each file is hash-sealed into the claim."
            ),
            "input": {"type": "media", "options": ["done"]},
            "validate": _validate_media_step,
        },
        {
            "id": "consent",
            "prompt": (
                "Before you sign: (1) you agree to the Terms of Use and Privacy Policy, "
                "(2) this account of the loss is accurate and complete, and "
                "(3) you authorize PHINS to review the evidence and contact you about this claim."
            ),
            "input": {"type": "consent", "options": ["agree"]},
            "validate": _choice_validator(["agree"]),
        },
        {
            "id": "signature",
            "prompt": (
                "Last step — your electronic signature. Type the name exactly as you confirmed it, "
                "enter your national ID, and draw your signature to seal this notice of loss."
            ),
            "input": {
                "type": "signature",
                "placeholder": "Full legal name",
                "id_placeholder": "National ID / Teudat Zehut",
            },
            "validate": _validate_signature,
        },
    ]


def compose_description(narrative: str, location: str) -> str:
    return f"{narrative.strip()}\n\nIncident location: {location.strip()}"


def build_facts(session: Dict[str, Any], identity_ref: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    answers = session.get("answers") or {}
    sig = answers.get("signature") if isinstance(answers.get("signature"), dict) else {}
    ref = identity_ref or {}
    narrative = str(answers.get("accident_narrative") or "")
    location = str(answers.get("incident_location") or "")
    facts = {
        "v": 1,
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "customer_id": session.get("customer_id"),
        "policy_id": answers.get("policy_id"),
        "type": answers.get("claim_type"),
        "claimed_amount": f"{float(answers.get('claimed_amount') or 0):.2f}",
        "incident_date": answers.get("incident_date"),
        "incident_location": location,
        "description": compose_description(narrative, location),
        "provider": answers.get("provider") or "",
        "payment_destination": "health_wallet",
        "contact_name": (session.get("contact") or {}).get("name"),
        "contact_email": (session.get("contact") or {}).get("email"),
        "contact_phone": (session.get("contact") or {}).get("phone"),
        "contact_edited": bool(answers.get("profile", {}).get("edited") if isinstance(answers.get("profile"), dict) else False),
        "nationality": ref.get("nationality") or sig.get("nationality"),
        "national_id_last4": ref.get("national_id_last4") or str(sig.get("id_number") or "")[-4:],
        "national_id_hash": ref.get("national_id_hash"),
        "signature_name": sig.get("name"),
        "signature_sha256": sig.get("image_sha256"),
        "signature_method": sig.get("method") or "drawn_canvas",
        "consent_version": CONSENT_VERSION,
        "media": [
            {
                "name": item.get("name"),
                "kind": item.get("kind"),
                "sha256": item.get("sha256"),
                "size": item.get("size"),
                "mime_type": item.get("mime_type"),
            }
            for item in (session.get("media") or [])
        ],
    }
    return facts


def render_fnol_html(facts: Dict[str, Any], checksum: str) -> str:
    """Immutable first-notice document. No plaintext national ID."""
    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else ""), quote=True)

    media_rows = "".join(
        "<tr><td>{kind}</td><td>{name}</td><td>{size}</td><td><code>{sha}</code></td></tr>".format(
            kind=esc(item.get("kind")),
            name=esc(item.get("name")),
            size=esc(item.get("size")),
            sha=esc(item.get("sha256")),
        )
        for item in (facts.get("media") or [])
    ) or "<tr><td colspan='4'>No evidence files</td></tr>"
    last4 = esc(facts.get("national_id_last4") or "")
    body = f"""
  <h1>First <span class="gold">Notice of Loss</span></h1>
  <p class="sub">Claims agent intake · {esc(QUESTIONNAIRE_VERSION)} · status pending review</p>
  <table>
    <tr><th>Customer</th><td>{esc(facts.get('customer_id'))} · {esc(facts.get('contact_name'))}</td></tr>
    <tr><th>Contact</th><td>{esc(facts.get('contact_email'))}<br>{esc(facts.get('contact_phone'))}</td></tr>
    <tr><th>Policy</th><td>{esc(facts.get('policy_id'))}</td></tr>
    <tr><th>Claim type</th><td>{esc(facts.get('type'))}</td></tr>
    <tr><th>Incident date</th><td>{esc(facts.get('incident_date'))}</td></tr>
    <tr><th>Location</th><td>{esc(facts.get('incident_location'))}</td></tr>
    <tr><th>Claimed amount</th><td>USD {esc(facts.get('claimed_amount'))}</td></tr>
    <tr><th>Provider</th><td>{esc(facts.get('provider') or '—')}</td></tr>
    <tr><th>What happened</th><td>{esc(facts.get('description'))}</td></tr>
    <tr><th>Identity</th><td>Nationality {esc(facts.get('nationality'))} · ID ending {last4}<br>
        Hash <code>{esc(facts.get('national_id_hash'))}</code></td></tr>
    <tr><th>Signature</th><td>{esc(facts.get('signature_name'))} · {esc(facts.get('signature_method'))}<br>
        Image <code>{esc(facts.get('signature_sha256'))}</code></td></tr>
    <tr><th>Consent</th><td>{esc(facts.get('consent_version'))}</td></tr>
  </table>
  <h2 style="font-family:'Segoe UI',sans-serif;font-size:16px;color:#0d2a5c;">Evidence sealed with this notice</h2>
  <table>
    <tr><th>Kind</th><th>Name</th><th>Bytes</th><th>SHA-256</th></tr>
    {media_rows}
  </table>
  <p class="seal">Payload SHA-256 <code>{esc(checksum)}</code>. This notice is the intake record.
  The claims bot assessment and the notification id are recorded after filing and do not rewrite this document.</p>
"""
    return render_phins_document(
        title=f"PHINS Notice of Loss {facts.get('policy_id') or ''}",
        eyebrow="First Notice of Loss",
        subtitle=str(facts.get("policy_id") or ""),
        body_html=body,
        footer="PHINS claim file · confidential · identity stored as nationality, last four, and hash",
    )


def render_processing_html(facts: Dict[str, Any], checksum: str, processing: Dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else ""), quote=True)

    pipeline = processing.get("pipeline") or {}
    body = f"""
  <h1>Claim processing record</h1>
  <p class="sub">Advisory claims-bot assessment. The filed amount is unchanged.</p>
  <table>
    <tr><th>Claim</th><td>{esc(processing.get('claim_id'))}</td></tr>
    <tr><th>Customer</th><td>{esc(facts.get('customer_id'))}</td></tr>
    <tr><th>Policy</th><td>{esc(facts.get('policy_id'))}</td></tr>
    <tr><th>Type / amount</th><td>{esc(facts.get('type'))} · USD {esc(facts.get('claimed_amount'))}</td></tr>
    <tr><th>Incident</th><td>{esc(facts.get('incident_date'))} · {esc(facts.get('incident_location'))}</td></tr>
    <tr><th>Notification</th><td>{esc(processing.get('notification_id') or 'not sent')} · {esc(processing.get('notification_status'))}</td></tr>
    <tr><th>Claims bot</th><td>Recommendation {esc(pipeline.get('recommendation'))}<br>
        Fraud probability {esc(pipeline.get('fraud_probability'))} ·
        Authenticity {esc(pipeline.get('authenticity_probability'))} ·
        Risk {esc(pipeline.get('risk_level'))}</td></tr>
    <tr><th>FNOL checksum</th><td><code>{esc(checksum)}</code></td></tr>
    <tr><th>Identity</th><td>{esc(facts.get('nationality'))} ····{esc(facts.get('national_id_last4'))}</td></tr>
  </table>
  <p class="seal">Advisory only. The claims bot does not approve, deny, or alter the filed amount.</p>
"""
    return render_phins_document(
        title=f"PHINS claim processing {processing.get('claim_id') or ''}",
        eyebrow="Processing record",
        subtitle=str(processing.get("claim_id") or ""),
        body_html=body,
        footer="PHINS claims pipeline · notification and claims-bot recommendation",
    )


class ClaimsChatService:
    """In-memory claims conversation store. The claim row is the durable record."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._resume_index: Dict[str, str] = {}

    def _generate_ids(self) -> Tuple[str, str]:
        return (
            f"CLCHAT-{secrets.token_hex(4).upper()}",
            f"PHINS-CLAIM-{secrets.token_hex(4).upper()}",
        )

    def _get(self, application_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(application_id)

    def authorize(self, application_id: str, resume_code: Any, *,
                  staff: bool = False, customer_id: Optional[str] = None) -> bool:
        session = self._get(application_id)
        if not session:
            return False
        if staff:
            return True
        if customer_id and session.get("customer_id") and str(customer_id) == str(session["customer_id"]):
            return True
        return _codes_match(resume_code, session.get("resume_code"))

    def _steps_for(self, session: Dict[str, Any]) -> List[Dict[str, Any]]:
        steps: List[Dict[str, Any]] = []
        if session.get("needs_claimant_lookup"):
            steps.append(dict(_CLAIMANT_STEP, validate=_validate_claimant))
        steps.append({
            "id": "profile",
            "prompt": self._profile_prompt(session),
            "input": {"type": "profile"},
            "validate": _validate_profile,
        })
        steps.extend(_post_otp_steps())
        return steps

    def _profile_prompt(self, session: Dict[str, Any]) -> str:
        prefill = session.get("prefill") or {}
        if prefill.get("name") or prefill.get("email"):
            return (
                "I already have these details on the PHINS account. "
                "Edit anything that changed, then confirm. I'll send a verification code next."
            )
        return "Let's confirm who you are — full name, email, and mobile."

    def _pre_otp_ids(self, session: Dict[str, Any]) -> set:
        ids = {"profile"}
        if session.get("needs_claimant_lookup"):
            ids.add("claimant")
        return ids

    def _identity_verified(self, session: Dict[str, Any]) -> bool:
        return bool(session.get("email_verified") or session.get("phone_verified"))

    def _next_step(self, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        answered = session["answers"]
        for step in self._steps_for(session):
            if step["id"] not in answered:
                if step["id"] not in self._pre_otp_ids(session) and not self._identity_verified(session):
                    return None
                return step
        return None

    def _progress(self, session: Dict[str, Any]) -> Dict[str, Any]:
        steps = self._steps_for(session)
        done = sum(1 for step in steps if step["id"] in session["answers"])
        return {"answered": done, "total": len(steps), "percent": int(round(100 * done / max(1, len(steps))))}

    def _step_public(self, session: Dict[str, Any], step: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if step is None:
            return None
        public_input = dict(step.get("input") or {})
        if step["id"] == "profile":
            public_input["prefill"] = dict(session.get("prefill") or {})
            public_input["from_account"] = bool(session.get("customer_id"))
        elif step["id"] == "policy_id":
            policies = session.get("policies") or []
            labels = {}
            for policy in policies:
                coverage = policy.get("coverage_amount") or 0
                labels[policy["id"]] = f"{policy['id']} · {policy.get('type')} · ${coverage:,.0f}"
            public_input["options"] = [p["id"] for p in policies]
            public_input["labels"] = labels
        elif step["id"] == "claimed_amount":
            coverage = float((session.get("selected_policy") or {}).get("coverage_amount") or 0)
            if coverage:
                public_input["max"] = coverage
        elif step["id"] == "signature":
            public_input["name_default"] = (session.get("contact") or {}).get("name") or ""
        prompt = step.get("prompt")
        if callable(prompt):
            prompt = prompt(session)
        return {"id": step["id"], "prompt": prompt, "input": public_input}

    def _transcript_add(self, session: Dict[str, Any], role: str, text: str,
                        kind: str = "text", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry = {
            "seq": len(session["transcript"]) + 1,
            "role": role,
            "text": text,
            "kind": kind,
            "at": _utc_now_iso(),
            "meta": meta or {},
        }
        session["transcript"].append(entry)
        session["updated_at"] = entry["at"]
        return entry

    def _journey(self, session: Dict[str, Any], stage: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        event = {
            "event_type": "claims_chat.journey",
            "entity_type": "claims_chat",
            "entity_id": session["id"],
            "customer_id": session.get("customer_id"),
            "actor": session.get("started_by") or "claimant",
            "payload": {"stage": stage, "application_id": session["id"], **(meta or {})},
        }
        session["journey"].append({"stage": stage, "at": _utc_now_iso(), "meta": meta or {}})
        return event

    def _ledger_message(self, session: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "event_type": "claims_chat.message",
            "entity_type": "claims_chat",
            "entity_id": session["id"],
            "customer_id": session.get("customer_id"),
            "actor": entry.get("role") or "system",
            "payload": {
                "application_id": session["id"],
                "seq": entry.get("seq"),
                "kind": entry.get("kind"),
                "role": entry.get("role"),
            },
        }

    def _bind_customer(self, session: Dict[str, Any], customer_id: str,
                       profile: Dict[str, str], policies: List[Dict[str, Any]]) -> None:
        session["customer_id"] = customer_id
        session["prefill"] = {
            "name": profile.get("name") or "",
            "email": profile.get("email") or "",
            "phone": profile.get("phone") or "",
        }
        session["account_email"] = profile.get("email") or ""
        session["account_phone"] = profile.get("phone") or ""
        session["policies"] = policies

    def start_session(self, *, role: str, username: str, customer_id: Optional[str],
                      profile: Optional[Dict[str, str]] = None,
                      policies: Optional[List[Dict[str, Any]]] = None,
                      channel: str = "web_chat") -> Dict[str, Any]:
        with self._lock:
            app_id, resume_code = self._generate_ids()
            staff = role != "customer"
            guest = role == "external"
            session: Dict[str, Any] = {
                "id": app_id,
                "resume_code": resume_code,
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "status": "in_progress",
                "channel": channel,
                "started_by": f"{role}:{username}",
                "needs_claimant_lookup": staff,
                "guest": guest,
                "customer_id": None,
                "prefill": {},
                "account_email": None,
                "account_phone": None,
                "policies": [],
                "selected_policy": None,
                "contact": {"name": None, "email": None, "phone": None},
                "email_verified": False,
                "phone_verified": False,
                "verified_via": None,
                "otp": {},
                "answers": {},
                "media": [],
                "transcript": [],
                "journey": [],
                "facts": None,
                "payload_checksum": None,
                "document_html": None,
                "document_sha256": None,
                "processing": None,
                "submission": None,
                "finalizing": False,
            }
            if not staff and customer_id:
                self._bind_customer(session, customer_id, profile or {}, policies or [])
            self._sessions[app_id] = session
            self._resume_index[resume_code] = app_id
            events = [self._journey(session, "started", {"channel": channel, "role": role})]
            greeting = (
                f"Hi! I'm {BOT_NAME}, your {BOT_TITLE}. I'll take this notice of loss "
                "the same way I take an application — confirm who you are, verify a code, "
                "hear what happened, seal your evidence, and file it on the claims pipeline."
            )
            resume_note = (
                f"Your private resume code is {resume_code}. If we pause, that code plus "
                "your email brings us back to the same file."
            )
            messages = [
                self._transcript_add(session, "bot", greeting),
                self._transcript_add(session, "bot", resume_note, kind="resume_code",
                                     meta={"resume_code": resume_code}),
            ]
            step = self._next_step(session)
            step_pub = self._step_public(session, step)
            if step_pub:
                messages.append(self._transcript_add(
                    session, "bot", step_pub["prompt"], kind="question", meta={"step": step_pub["id"]}))
            events.extend(self._ledger_message(session, msg) for msg in messages)
            return {
                "ok": True,
                "application_id": app_id,
                "resume_code": resume_code,
                "messages": messages,
                "step": step_pub,
                "progress": self._progress(session),
                "from_account": bool(session.get("customer_id")),
                "ledger_events": events,
            }

    def _display(self, step_id: str, value: Any) -> str:
        if step_id == "profile" and isinstance(value, dict):
            return f"Confirmed: {value.get('name')} · {value.get('email')}"
        if step_id == "signature" and isinstance(value, dict):
            return f"Signed: {value.get('name')}"
        if step_id == "claimed_amount":
            try:
                return f"${float(value):,.2f}"
            except (TypeError, ValueError):
                return str(value)
        if isinstance(value, dict):
            return "Details confirmed"
        return str(value)

    def _apply(self, session: Dict[str, Any], step_id: str, cleaned: Any,
               events: List[Dict[str, Any]]) -> None:
        if step_id == "claimant":
            resolved = session.pop("_claimant_resolution", None) or {}
            if resolved.get("ok"):
                self._bind_customer(
                    session, resolved["customer_id"], resolved.get("profile") or {},
                    resolved.get("policies") or [])
                events.append(self._journey(session, "claimant_bound", {
                    "customer_id": resolved["customer_id"]}))
        elif step_id == "profile" and isinstance(cleaned, dict):
            session["contact"]["name"] = cleaned["name"]
            session["contact"]["email"] = cleaned["email"]
            session["contact"]["phone"] = cleaned["phone"]
            events.append(self._journey(session, "contact_captured", {
                "edited": bool(cleaned.get("edited")),
                "masked_email": _mask_email(cleaned["email"]),
            }))
        elif step_id == "consent":
            session["answers"]["consent_accepted_at"] = _utc_now_iso()
            session["answers"]["consent_version"] = CONSENT_VERSION
        elif step_id == "signature" and isinstance(cleaned, dict):
            session["signature_name"] = cleaned.get("name")
            session["signature_at"] = _utc_now_iso()
            session["answers"]["signature"] = cleaned
            events.append(self._journey(session, "signed", {
                "signature_name": cleaned.get("name"),
                "nationality": cleaned.get("nationality"),
                "id_number_last4": str(cleaned.get("id_number") or "")[-4:],
                "image_sha256": cleaned.get("image_sha256"),
            }))

    def submit_answer(self, application_id: str, value: Any,
                      step_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409, "error": "This claim was already filed."}
            if session["status"] in ("paused", "pending_reverify") and self._identity_verified(session):
                return {"ok": False, "status_code": 403, "error": "OTP_REQUIRED",
                        "message": "Verify a fresh code before continuing."}
            if session["status"] == "paused":
                session["status"] = "in_progress"

            step = self._next_step(session)
            if step is None:
                if not self._identity_verified(session):
                    return {"ok": False, "status_code": 403, "error": "OTP_REQUIRED",
                            "message": "Verify the code I sent before we continue."}
                return {"ok": False, "status_code": 409,
                        "error": "All questions are answered — you can finalize now.",
                        "ready_to_finalize": True}
            if step_id and step_id != step["id"]:
                return {"ok": False, "status_code": 409,
                        "error": f"Expected an answer for step '{step['id']}'",
                        "step": self._step_public(session, step)}

            ok, cleaned = step["validate"](value, session)
            events: List[Dict[str, Any]] = []
            user_entry = self._transcript_add(
                session, "user", self._display(step["id"], value if not ok else cleaned),
                kind="answer", meta={"step": step["id"]})
            events.append(self._ledger_message(session, user_entry))
            if not ok:
                bot_entry = self._transcript_add(
                    session, "bot", str(cleaned), kind="validation_error", meta={"step": step["id"]})
                events.append(self._ledger_message(session, bot_entry))
                return {
                    "ok": False, "status_code": 400, "error": str(cleaned),
                    "messages": [bot_entry], "step": self._step_public(session, step),
                    "progress": self._progress(session), "ledger_events": events,
                }

            if step["id"] != "signature":
                session["answers"][step["id"]] = cleaned
            self._apply(session, step["id"], cleaned, events)

            messages: List[Dict[str, Any]] = []
            response: Dict[str, Any] = {"ok": True}
            nxt = self._next_step(session)
            if nxt is None and not self._identity_verified(session) and step["id"] == "profile":
                target = self._verification_contact(session)
                masked_email = _mask_email(target.get("email") or "")
                masked_phone = _mask_phone(target.get("phone"))
                messages.append(self._transcript_add(
                    session, "bot",
                    "Confirmed. To protect this claim I'll send a 6-digit code to "
                    f"{masked_email}, SMS {masked_phone}, or WhatsApp {masked_phone}. "
                    "Choose where to send it, then enter the code.",
                    kind="otp_challenge"))
                response["otp_required"] = True
                response["otp_channels"] = ["email", "sms", "whatsapp"]
                response["masked_email"] = masked_email
                response["masked_phone"] = masked_phone
            elif nxt is None:
                messages.append(self._transcript_add(
                    session, "bot",
                    "That's the whole notice. I'll seal the file, file the claim, "
                    "notify you, and hand it to the claims pipeline.",
                    kind="ready_to_finalize"))
                response["ready_to_finalize"] = True
            else:
                step_pub = self._step_public(session, nxt)
                messages.append(self._transcript_add(
                    session, "bot", step_pub["prompt"], kind="question",
                    meta={"step": step_pub["id"]}))
                response["step"] = step_pub
            events.extend(self._ledger_message(session, msg) for msg in messages)
            response.update({
                "messages": messages,
                "progress": self._progress(session),
                "ledger_events": events,
            })
            return response

    def _verification_contact(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """Where a verification code may be sent.

        A public claimant proved nothing by looking up an account, so the code
        goes to the contact on that account, not to an edited profile. An
        account without that contact simply cannot be verified this way.
        """
        if session.get("guest"):
            return {
                "email": session.get("account_email") or "",
                "phone": session.get("account_phone") or "",
            }
        return session.get("contact") or {}

    def verification_email(self, application_id: str) -> Optional[str]:
        session = self._get(application_id)
        if not session:
            return None
        return self._verification_contact(session).get("email")

    def verification_phone(self, application_id: str) -> Optional[str]:
        session = self._get(application_id)
        if not session:
            return None
        return self._verification_contact(session).get("phone")

    def note_otp_requested(self, application_id: str, verification_id: str,
                           channel: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409, "error": "This claim was already filed."}
            session["otp"] = {"verification_id": verification_id, "channel": channel,
                              "requested_at": _utc_now_iso()}
            return {"ok": True}

    def pending_verification_id(self, application_id: str) -> Optional[str]:
        session = self._get(application_id)
        if not session:
            return None
        return (session.get("otp") or {}).get("verification_id")

    def mark_identity_verified(self, application_id: str, channel: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            if channel in ("sms", "whatsapp"):
                session["phone_verified"] = True
            else:
                session["email_verified"] = True
            session["verified_via"] = channel
            session["status"] = "in_progress"
            events = [self._journey(session, "otp_verified", {"channel": channel})]
            messages = [self._transcript_add(
                session, "bot", "Verified — thank you. Let's file the loss against the right policy.",
                kind="ack")]
            step = self._next_step(session)
            step_pub = self._step_public(session, step)
            if step_pub:
                messages.append(self._transcript_add(
                    session, "bot", step_pub["prompt"], kind="question",
                    meta={"step": step_pub["id"]}))
            events.extend(self._ledger_message(session, msg) for msg in messages)
            return {
                "ok": True, "messages": messages, "step": step_pub,
                "progress": self._progress(session), "ledger_events": events,
                "transcript": list(session["transcript"]),
            }

    def attach_media(self, application_id: str, *, kind: str, name: str,
                     mime_type: str, data_b64: str,
                     duration_seconds: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409, "error": "This claim was already filed."}
            if not self._identity_verified(session):
                return {"ok": False, "status_code": 403,
                        "error": "Verify your identity before uploading evidence."}
            kind = str(kind or "").strip().lower()
            if kind not in ALLOWED_MEDIA_KINDS:
                return {"ok": False, "status_code": 400,
                        "error": f"kind must be one of {', '.join(ALLOWED_MEDIA_KINDS)}"}
            if len(session["media"]) >= MAX_MEDIA_ITEMS:
                return {"ok": False, "status_code": 400,
                        "error": f"Maximum {MAX_MEDIA_ITEMS} attachments."}
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
                return {"ok": False, "status_code": 400, "error": "Attachment exceeds 4MB."}
            total = sum(item["size"] for item in session["media"]) + len(blob)
            if total > MAX_TOTAL_MEDIA_BYTES:
                return {"ok": False, "status_code": 400, "error": "Total attachments exceed 6MB."}
            media_id = f"CLMEDIA-{secrets.token_hex(4).upper()}"
            item = {
                "id": media_id,
                "kind": kind,
                "name": str(name or f"{kind}-{media_id}")[:200],
                "mime_type": str(mime_type or "application/octet-stream")[:120],
                "size": len(blob),
                "sha256": _sha256_hex(blob),
                "data_b64": raw_b64,
                "duration_seconds": duration_seconds,
                "uploaded_at": _utc_now_iso(),
            }
            session["media"].append(item)
            label = {"voice": "voice note", "video": "video", "document": "document", "image": "image"}[kind]
            user_entry = self._transcript_add(
                session, "user", f"Sent a {label}: {item['name']}", kind=f"media_{kind}",
                meta={"media_id": media_id, "sha256": item["sha256"], "size": item["size"]})
            bot_entry = self._transcript_add(
                session, "bot",
                f"Got your {label}. It's sealed into this claim (fingerprint {item['sha256'][:12]}).",
                kind="media_ack", meta={"media_id": media_id, "sha256": item["sha256"]})
            events = [
                self._ledger_message(session, user_entry),
                self._journey(session, "media_attached", {
                    "media_id": media_id, "kind": kind, "sha256": item["sha256"], "size": item["size"]}),
                self._ledger_message(session, bot_entry),
            ]
            public = {k: v for k, v in item.items() if k != "data_b64"}
            return {"ok": True, "media": public, "messages": [bot_entry], "ledger_events": events}

    def pause_session(self, application_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            if session["status"] == "submitted":
                return {"ok": False, "status_code": 409, "error": "This claim was already filed."}
            session["status"] = "paused"
            events = [self._journey(session, "stopped")]
            message = self._transcript_add(
                session, "bot",
                f"Paused. Resume with {session['resume_code']} and {session['contact'].get('email') or 'your email'}.",
                kind="paused")
            events.append(self._ledger_message(session, message))
            return {"ok": True, "messages": [message], "ledger_events": events,
                    "resume_code": session["resume_code"]}

    def resume_session(self, resume_code: str, email: str) -> Dict[str, Any]:
        with self._lock:
            app_id = self._resume_index.get(str(resume_code or "").strip().upper())
            session = self._get(app_id) if app_id else None
            if not session:
                return {"ok": False, "status_code": 404, "error": "That resume code doesn't match a claim file."}
            contact_email = (session.get("contact") or {}).get("email") or ""
            if contact_email and contact_email != str(email or "").strip().lower():
                return {"ok": False, "status_code": 404, "error": "That code and email don't match."}
            if session["status"] == "submitted":
                return {
                    "ok": True, "application_id": session["id"], "status": "submitted",
                    "submission": session.get("submission"), "processing": session.get("processing"),
                    "document_html": session.get("document_html"),
                    "document_sha256": session.get("document_sha256"),
                }
            otp_required = self._identity_verified(session)
            if otp_required:
                session["status"] = "pending_reverify"
                session["email_verified"] = False
                session["phone_verified"] = False
            else:
                session["status"] = "in_progress"
            step = None if otp_required else self._step_public(session, self._next_step(session))
            return {
                "ok": True,
                "application_id": session["id"],
                "status": session["status"],
                "otp_required": otp_required,
                "masked_email": _mask_email(contact_email) if contact_email else None,
                "masked_phone": _mask_phone((session.get("contact") or {}).get("phone")),
                "transcript": [] if otp_required else list(session["transcript"]),
                "step": step,
                "progress": self._progress(session),
                "ledger_events": [self._journey(session, "continued")],
            }

    def abort_reverify(self, application_id: str) -> None:
        with self._lock:
            session = self._get(application_id)
            if session and session["status"] == "pending_reverify":
                session["status"] = "paused"
                session["email_verified"] = True

    def prepare_finalize(self, application_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            if session["status"] == "submitted" and session.get("submission"):
                return {"ok": True, "already_submitted": True, "submission": session["submission"],
                        "document_html": session.get("document_html"),
                        "document_sha256": session.get("document_sha256"),
                        "processing": session.get("processing"),
                        "messages": []}
            if session.get("finalizing"):
                return {"ok": False, "status_code": 409, "error": "This claim is already being filed."}
            if not self._identity_verified(session):
                return {"ok": False, "status_code": 403, "error": "Verify your identity before filing."}
            missing = [step["id"] for step in self._steps_for(session) if step["id"] not in session["answers"]]
            if missing:
                return {"ok": False, "status_code": 409,
                        "error": f"Still missing answers for: {', '.join(missing)}"}
            sig = session["answers"].get("signature") if isinstance(session["answers"].get("signature"), dict) else {}
            if not sig.get("id_number") or not sig.get("nationality"):
                return {"ok": False, "status_code": 409, "error": "A signed identity is required to file."}
            session["finalizing"] = True
            return {
                "ok": True,
                "customer_id": session.get("customer_id"),
                "national_id": sig.get("id_number"),
                "nationality": sig.get("nationality"),
                "media": [dict(item) for item in session["media"]],
            }

    def seal(self, application_id: str, identity_ref: Dict[str, Any]) -> Dict[str, Any]:
        """Bind the identity reference into the checksummed facts and FNOL HTML."""
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            facts = build_facts(session, identity_ref)
            checksum = _checksum_payload(facts)
            document = render_fnol_html(facts, checksum)
            document_sha = _sha256_hex(document.encode("utf-8"))
            session["facts"] = facts
            session["payload_checksum"] = checksum
            session["document_html"] = document
            session["document_sha256"] = document_sha
            # Plaintext ID leaves the session once the master has it.
            sig = session["answers"].get("signature")
            if isinstance(sig, dict):
                sig.pop("id_number", None)
                sig.pop("signature_data", None)
                sig["id_last4"] = identity_ref.get("national_id_last4")
            return {
                "ok": True, "facts": facts, "checksum": checksum,
                "document_html": document, "document_sha256": document_sha,
            }

    def submission_files(self, application_id: str) -> List[Dict[str, Any]]:
        session = self._get(application_id)
        if not session:
            return []
        files = []
        for item in session.get("media") or []:
            files.append({
                "name": item["name"],
                "type": item["mime_type"],
                "size": item["size"],
                "data": item["data_b64"],
                "note": f"sha256:{item['sha256']}",
            })
        document = session.get("document_html") or ""
        raw = document.encode("utf-8")
        files.append({
            "name": "first-notice-of-loss.html",
            "type": "text/html",
            "size": len(raw),
            "data": base64.b64encode(raw).decode("ascii"),
            "note": f"sha256:{session.get('document_sha256')}",
        })
        return files

    def clear_finalizing(self, application_id: str) -> None:
        with self._lock:
            session = self._get(application_id)
            if session and session.get("status") != "submitted":
                session["finalizing"] = False

    def verify_stored_claim(self, application_id: str, claim: Dict[str, Any],
                            claim_files: Dict[str, Any]) -> List[str]:
        """Compare the created claim and stored bytes to the sealed facts."""
        session = self._get(application_id)
        if not session or not session.get("facts"):
            return ["missing sealed facts"]
        facts = session["facts"]
        problems = []
        if str(claim.get("customer_id") or "") != str(facts.get("customer_id") or ""):
            problems.append("customer_id mismatch")
        if str(claim.get("policy_id") or "") != str(facts.get("policy_id") or ""):
            problems.append("policy_id mismatch")
        if str(claim.get("type") or "") != str(facts.get("type") or ""):
            problems.append("type mismatch")
        if str(claim.get("incident_date") or "") != str(facts.get("incident_date") or ""):
            problems.append("incident_date mismatch")
        if str(claim.get("description") or "") != str(facts.get("description") or ""):
            problems.append("description mismatch")
        if str(claim.get("provider") or "") != str(facts.get("provider") or ""):
            problems.append("provider mismatch")
        try:
            if abs(float(claim.get("claimed_amount") or 0) - float(facts["claimed_amount"])) > 0.001:
                problems.append("claimed_amount mismatch")
        except (TypeError, ValueError):
            problems.append("claimed_amount mismatch")
        blob = json.dumps(claim, default=str)
        for forbidden in ("id_number", "national_id", "signature_data"):
            if f'"{forbidden}"' in blob:
                problems.append(f"plaintext field {forbidden} on claim")
        expected = {item["sha256"]: item for item in (facts.get("media") or [])}
        expected[session["document_sha256"]] = {
            "name": "first-notice-of-loss.html",
            "sha256": session["document_sha256"],
        }
        seen = set()
        claim_id = claim.get("id")
        for record in (claim_files or {}).values():
            if not isinstance(record, dict) or record.get("claim_id") != claim_id:
                continue
            raw_b64 = record.get("data") or ""
            try:
                blob_bytes = base64.b64decode(raw_b64, validate=False)
            except Exception:
                problems.append(f"unreadable file {record.get('name')}")
                continue
            digest = _sha256_hex(blob_bytes)
            note = str(record.get("note") or "")
            if note.startswith("sha256:") and note.split(":", 1)[1] != digest:
                problems.append(f"note checksum mismatch for {record.get('name')}")
            if digest not in expected:
                # Processing addendum is attached later; ignore unknown hashes here.
                continue
            seen.add(digest)
            if len(blob_bytes) != int(record.get("size") or 0):
                problems.append(f"size mismatch for {record.get('name')}")
        missing = [item["name"] for item in expected.values() if item["sha256"] not in seen]
        if missing:
            problems.append("missing sealed files: " + ", ".join(missing))
        ref = claim.get("customer_identity") or {}
        if facts.get("national_id_hash") and ref.get("national_id_hash") != facts.get("national_id_hash"):
            problems.append("identity hash not stamped on claim")
        return problems

    def remember_claim(self, application_id: str, claim_id: str) -> None:
        session = self._get(application_id)
        if session:
            session["claim_id"] = claim_id

    def attach_processing(self, application_id: str, processing: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            html_doc = render_processing_html(session.get("facts") or {}, session.get("payload_checksum") or "", processing)
            digest = _sha256_hex(html_doc.encode("utf-8"))
            processing = dict(processing)
            processing["record_sha256"] = digest
            processing["record_html"] = html_doc
            session["processing"] = processing
            return {"ok": True, "processing": processing, "record_html": html_doc, "record_sha256": digest}

    def mark_submitted(self, application_id: str, claim_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._get(application_id)
            if not session:
                return {"ok": False, "status_code": 404, "error": "Claim chat not found"}
            if session["status"] == "submitted" and (session.get("submission") or {}).get("claim_id"):
                return {"ok": True, "duplicate": True, "submission": session["submission"],
                        "messages": [], "ledger_events": []}
            session["status"] = "submitted"
            session["finalizing"] = False
            for item in session.get("media") or []:
                item.pop("data_b64", None)
            sig = session["answers"].get("signature")
            if isinstance(sig, dict):
                sig.pop("id_number", None)
                sig.pop("signature_data", None)
            session["submission"] = {
                "claim_id": claim_id,
                "customer_id": session.get("customer_id"),
                "policy_id": (session.get("facts") or {}).get("policy_id"),
                "payload_checksum": session.get("payload_checksum"),
                "document_sha256": session.get("document_sha256"),
                "submitted_at": _utc_now_iso(),
            }
            first = str((session.get("contact") or {}).get("name") or "").split(" ")[0]
            name_part = f", {first}" if first else ""
            message = self._transcript_add(
                session, "bot",
                f"Filed{name_part}. Claim {claim_id} is pending review. "
                "The notice of loss below is the sealed record, and the claims pipeline has it.",
                kind="submitted", meta={"claim_id": claim_id,
                                        "payload_checksum": session.get("payload_checksum")})
            events = [
                self._journey(session, "submitted", {
                    "claim_id": claim_id,
                    "payload_checksum": session.get("payload_checksum"),
                    "document_sha256": session.get("document_sha256"),
                }),
                self._ledger_message(session, message),
            ]
            return {"ok": True, "messages": [message], "submission": session["submission"],
                    "ledger_events": events}

    def public_state(self, application_id: str) -> Optional[Dict[str, Any]]:
        session = self._get(application_id)
        if not session:
            return None
        return {
            "application_id": session["id"],
            "status": session["status"],
            "progress": self._progress(session),
            "step": self._step_public(session, self._next_step(session)) if session["status"] == "in_progress" else None,
            "transcript": list(session["transcript"]),
            "submission": session.get("submission"),
            "processing": _public_processing(session.get("processing")),
            "document_html": session.get("document_html") if session["status"] == "submitted" else None,
            "document_sha256": session.get("document_sha256"),
            "customer_id": session.get("customer_id"),
        }


def _public_processing(processing: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not processing:
        return None
    public = {k: v for k, v in processing.items() if k != "record_html"}
    return public


_SERVICE: Optional[ClaimsChatService] = None
_SERVICE_LOCK = threading.Lock()


def get_claims_chat_service() -> ClaimsChatService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = ClaimsChatService()
    return _SERVICE


def reset_claims_chat_service() -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = None
