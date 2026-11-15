"""Append-only answer history for policy and claim chats.

Every committed answer is a revision. The chain is checksummed: each record
names the previous checksum, and a broken link blocks another edit and blocks
filing. Card numbers, CVVs, and full national IDs are not stored. Staff review
recomputes prior-application matches at read time so the ledger seal can stay
free of other people's files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger("phins.chat_process_review")

POLICY_CATEGORIES = {
    "name": "identity",
    "email": "identity",
    "phone": "identity",
    "country": "identity",
    "city": "identity",
    "dob": "identity",
    "gender": "identity",
    "occupation": "identity",
    "signature": "identity",
    "height": "health",
    "weight": "health",
    "tobacco": "health",
    "medical_conditions": "health",
    "conditions_list": "health",
    "surgery": "health",
    "surgery_list": "health",
    "hazardous": "health",
    "family_history": "health",
    "medications": "health",
    "prior_disclosure": "health",
    "daily_function": "health",
    "coverage_amount": "coverage",
    "coverage_years": "coverage",
    "savings_addon": "coverage",
    "media_offer": "other",
    "billing_frequency": "billing",
    "payment_card": "billing",
    "auto_pay": "billing",
    "consent": "consent",
}

CLAIM_CATEGORIES = {
    "claimant": "identity",
    "profile": "identity",
    "signature": "identity",
    "policy_id": "billing",
    "claim_type": "health",
    "incident_date": "health",
    "incident_location": "health",
    "accident_narrative": "health",
    "provider": "health",
    "claimed_amount": "billing",
    "media_offer": "other",
    "consent": "consent",
}

STEP_LABELS = {
    "name": "Full name",
    "email": "Email",
    "phone": "Mobile",
    "country": "Country",
    "city": "City",
    "dob": "Date of birth",
    "gender": "Gender",
    "occupation": "Occupation",
    "signature": "Signature and identity",
    "height": "Height",
    "weight": "Weight",
    "tobacco": "Tobacco",
    "medical_conditions": "Medical conditions",
    "conditions_list": "Health problems",
    "surgery": "Recent surgery",
    "surgery_list": "Surgery detail",
    "hazardous": "Hazardous activities",
    "family_history": "Family history",
    "medications": "Medications",
    "prior_disclosure": "Health disclosure",
    "daily_function": "Daily function",
    "coverage_amount": "Coverage amount",
    "coverage_years": "Coverage years",
    "savings_addon": "Savings add-on",
    "media_offer": "Attachments",
    "billing_frequency": "Billing frequency",
    "payment_card": "Payment card",
    "auto_pay": "Auto-pay",
    "consent": "Consent",
    "claimant": "Policy holder",
    "profile": "Contact details",
    "policy_id": "Policy",
    "claim_type": "Claim type",
    "incident_date": "Incident date",
    "incident_location": "Incident location",
    "accident_narrative": "What happened",
    "provider": "Provider",
    "claimed_amount": "Claimed amount",
}

# Health and identity answers that the disclosure step was written against.
DISCLOSURE_INVALIDATING = frozenset({
    "name", "email", "dob", "signature",
    "tobacco", "medical_conditions", "conditions_list", "surgery", "surgery_list",
    "hazardous", "family_history", "medications", "daily_function",
})

ASSESSMENT_STEPS = frozenset({
    "dob", "gender", "occupation", "height", "weight", "tobacco",
    "medical_conditions", "conditions_list", "surgery", "surgery_list",
    "hazardous", "family_history", "medications", "daily_function",
})

QUOTE_STEPS = ASSESSMENT_STEPS | frozenset({
    "coverage_amount", "coverage_years", "savings_addon", "billing_frequency",
})

_CATEGORIES = ("identity", "health", "billing", "coverage", "consent", "other")

# Secret process review. Customers, accountants, and actuaries are not in this set.
PROCESS_REVIEW_ROLES = frozenset({
    "admin", "underwriter",
    "claims", "claims_adjuster", "claims_agent", "claims_manager", "adjuster",
})
_INTEGRITY_ERROR = "Answer history failed its integrity check."
_MAX_DISPLAY = 240
_MAX_REJECTED = 50


def category_for(step_id: str) -> str:
    return POLICY_CATEGORIES.get(step_id) or CLAIM_CATEGORIES.get(step_id) or "other"


def label_for(step_id: str) -> str:
    return STEP_LABELS.get(step_id) or str(step_id or "").replace("_", " ").title()


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def digest(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def _clip(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) <= _MAX_DISPLAY:
        return text
    return text[: _MAX_DISPLAY - 1] + "…"


def _last4(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) >= 4:
        return digits[-4:]
    text = str(value or "").strip()
    return text[-4:] if len(text) >= 4 else ""


def identity_pointer(nationality: Any, id_number: Any = None, id_last4: Any = None) -> Dict[str, Optional[str]]:
    """Nationality, last four, and the keyed identity hash. Never the number."""
    raw = str(id_number or "").strip()
    last4 = _last4(raw) or _last4(id_last4)
    hashed = None
    nat = str(nationality or "").strip() or None
    if raw and nat:
        try:
            from services.customer_identity_service import hash_national_id, normalize_national_id

            code, normalized = normalize_national_id(raw, nat)
            hashed = hash_national_id(code, normalized)
            last4 = normalized[-4:]
            nat = code
        except Exception:
            hashed = None
    return {
        "nationality": nat,
        "national_id_last4": last4 or None,
        "national_id_hash": hashed,
    }


def redact_answer(step_id: str, value: Any) -> Any:
    """Value safe to digest and, where noted, to show. No PAN, CVV, or full ID."""
    if step_id == "payment_card" and isinstance(value, dict):
        return {
            "card_last4": value.get("card_last4") or _last4(value.get("card_number")),
            "cardholder_name": value.get("cardholder_name") or "",
            "expiry_month": value.get("expiry_month") or "",
            "expiry_year": value.get("expiry_year") or "",
        }
    if step_id == "signature" and isinstance(value, dict):
        pointer = identity_pointer(
            value.get("nationality"),
            value.get("id_number"),
            value.get("national_id_last4") or value.get("id_last4"),
        )
        # After filing, the number is gone and the stored pointer is the record.
        if not pointer.get("national_id_hash") and value.get("national_id_hash"):
            pointer = {
                "nationality": pointer.get("nationality") or value.get("nationality"),
                "national_id_last4": (
                    pointer.get("national_id_last4")
                    or value.get("national_id_last4")
                    or value.get("id_last4")
                ),
                "national_id_hash": value.get("national_id_hash"),
            }
        return {
            "name": value.get("name") or "",
            "nationality": pointer.get("nationality"),
            "national_id_last4": pointer.get("national_id_last4"),
            "national_id_hash": pointer.get("national_id_hash"),
            "image_sha256": value.get("image_sha256") or value.get("signature_image_sha256") or "",
            "method": value.get("method") or "",
        }
    if step_id == "profile" and isinstance(value, dict):
        return {
            "name": value.get("name") or "",
            "email": value.get("email") or "",
            "phone": value.get("phone") or "",
            "edited": bool(value.get("edited")),
        }
    if isinstance(value, dict):
        blocked = {"card_number", "cvv", "id_number", "signature_data", "data_b64"}
        return {k: v for k, v in value.items() if k not in blocked}
    return value


def safe_display(step_id: str, value: Any) -> str:
    if step_id == "payment_card" and isinstance(value, dict):
        last4 = value.get("card_last4") or _last4(value.get("card_number"))
        return f"Card ending {last4}" if last4 else "Card on file"
    if step_id == "signature" and isinstance(value, dict):
        pointer = identity_pointer(
            value.get("nationality"),
            value.get("id_number"),
            value.get("national_id_last4") or value.get("id_last4"),
        )
        last4 = pointer.get("national_id_last4") or ""
        name = value.get("name") or ""
        return f"Signed: {name}" + (f" · ID ••••{last4}" if last4 else "")
    if step_id == "profile" and isinstance(value, dict):
        return f"{value.get('name') or ''} · {value.get('email') or ''}".strip(" ·")
    if step_id == "claimed_amount":
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        redacted = redact_answer(step_id, value)
        return ", ".join(f"{k}: {redacted[k]}" for k in sorted(redacted))
    return str(value if value is not None else "")


def same_answer(step_id: str, previous: Any, current: Any) -> bool:
    return canonical(redact_answer(step_id, previous)) == canonical(redact_answer(step_id, current))


def append_revision(
    revisions: List[Dict[str, Any]],
    *,
    step_id: str,
    action: str,
    at: str,
    previous: Any = None,
    current: Any = None,
    previous_display: Optional[str] = None,
    current_display: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one revision and return it. ``revisions`` is mutated."""
    prev_checksum = revisions[-1]["checksum"] if revisions else ""
    body: Dict[str, Any] = {
        "seq": len(revisions) + 1,
        "step_id": step_id,
        "category": category_for(step_id),
        "action": action,
        "at": at,
        "previous_display": _clip(previous_display) if action != "set" else None,
        "current_display": None if action == "withdrawn" else _clip(current_display),
        "previous_digest": digest(redact_answer(step_id, previous)) if action != "set" else None,
        "current_digest": None if action == "withdrawn" else digest(redact_answer(step_id, current)),
        "changed": action != "set",
        "prev_checksum": prev_checksum,
    }
    body["checksum"] = digest({k: v for k, v in body.items() if k != "checksum"})
    revisions.append(body)
    return body


def verify_revisions(revisions: Sequence[Mapping[str, Any]]) -> Tuple[bool, str]:
    prev = ""
    for index, rev in enumerate(revisions or []):
        if not isinstance(rev, Mapping):
            return False, _INTEGRITY_ERROR
        body = {k: v for k, v in rev.items() if k != "checksum"}
        if str(rev.get("prev_checksum") or "") != prev:
            return False, _INTEGRITY_ERROR
        if str(rev.get("checksum") or "") != digest(body):
            return False, _INTEGRITY_ERROR
        if int(rev.get("seq") or 0) != index + 1:
            return False, _INTEGRITY_ERROR
        prev = str(rev["checksum"])
    return True, ""


def history_gap(revisions: Sequence[Mapping[str, Any]], answers: Mapping[str, Any],
                step_ids: Iterable[str]) -> Optional[str]:
    ok, reason = verify_revisions(revisions)
    if not ok:
        return reason
    recorded = {
        str(rev.get("step_id"))
        for rev in revisions
        if rev.get("action") in ("set", "edit")
    }
    missing = [step_id for step_id in step_ids if step_id in answers and step_id not in recorded]
    if missing:
        return "Answer history is missing a recorded revision for: " + ", ".join(missing)
    return None


def summarize_edits(revisions: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Latest display and edit count per step."""
    summary: Dict[str, Dict[str, Any]] = {}
    for rev in revisions or []:
        step_id = str(rev.get("step_id") or "")
        if not step_id:
            continue
        row = summary.setdefault(step_id, {
            "display": None, "edit_count": 0, "last_edited_at": None, "category": rev.get("category"),
        })
        if rev.get("action") == "withdrawn":
            row["display"] = None
            row["edit_count"] = int(row["edit_count"]) + 1
            row["last_edited_at"] = rev.get("at")
            continue
        if rev.get("current_display"):
            row["display"] = rev.get("current_display")
        if rev.get("action") == "edit":
            row["edit_count"] = int(row["edit_count"]) + 1
            row["last_edited_at"] = rev.get("at")
        row["category"] = rev.get("category") or row.get("category")
    return summary


def edit_counts(revisions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    counts = {name: 0 for name in _CATEGORIES}
    last_at = None
    total = 0
    for rev in revisions or []:
        if rev.get("action") not in ("edit", "withdrawn"):
            continue
        bucket = str(rev.get("category") or "other")
        if bucket not in counts:
            bucket = "other"
        counts[bucket] += 1
        total += 1
        last_at = rev.get("at") or last_at
    counts["total"] = total
    counts["last_edited_at"] = last_at
    return counts


def intention_shifts(revisions: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """First committed answer versus the latest one, per step that was edited."""
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for rev in revisions or []:
        grouped.setdefault(str(rev.get("step_id") or ""), []).append(rev)
    shifts = []
    for step_id, rows in grouped.items():
        if not step_id:
            continue
        edits = [row for row in rows if row.get("action") == "edit"]
        withdrawals = [row for row in rows if row.get("action") == "withdrawn"]
        if not edits and not withdrawals:
            continue
        first = next((row for row in rows if row.get("action") == "set"), rows[0])
        last = rows[-1]
        if last.get("action") == "withdrawn":
            shifts.append({
                "step_id": step_id,
                "label": label_for(step_id),
                "category": last.get("category"),
                "from": first.get("current_display"),
                "to": None,
                "withdrawn": True,
                "edited_at": last.get("at"),
                "edit_count": len(edits) + len(withdrawals),
            })
            continue
        if first.get("current_display") == last.get("current_display"):
            continue
        shifts.append({
            "step_id": step_id,
            "label": label_for(step_id),
            "category": last.get("category"),
            "from": first.get("current_display"),
            "to": last.get("current_display"),
            "withdrawn": False,
            "edited_at": last.get("at"),
            "edit_count": len(edits),
        })
    return shifts


def remember_rejection(session: Dict[str, Any], *, step_id: str, display: str,
                       reason: str, at: str) -> Dict[str, Any]:
    row = {
        "step_id": step_id,
        "label": label_for(step_id),
        "category": category_for(step_id),
        "display": _clip(display),
        "reason": _clip(reason),
        "at": at,
    }
    bucket = session.setdefault("rejected_edits", [])
    bucket.append(row)
    if len(bucket) > _MAX_REJECTED:
        del bucket[:-_MAX_REJECTED]
    return row


def _norm_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_name(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _name_usable(value: str) -> bool:
    parts = value.split()
    return len(parts) >= 2 and len(value) >= 5


def _record_name(record: Mapping[str, Any]) -> str:
    for key in ("customer_name", "name", "full_name", "contact_name", "signature_name"):
        text = _norm_name(record.get(key))
        if text:
            return text
    return ""


def _record_email(record: Mapping[str, Any]) -> str:
    for key in ("customer_email", "email", "contact_email"):
        text = _norm_email(record.get(key))
        if text:
            return text
    return ""


def match_prior(
    *,
    email: Optional[str],
    name: Optional[str],
    national_id_hash: Optional[str],
    customer_id: Optional[str],
    applications: Mapping[str, Mapping[str, Any]],
    policies: Mapping[str, Mapping[str, Any]],
    claims: Mapping[str, Mapping[str, Any]],
    customers: Mapping[str, Mapping[str, Any]],
    peers: Sequence[Mapping[str, Any]] = (),
    exclude_ids: Iterable[str] = (),
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Prior files triggered by email, exact name, or identity hash."""
    email_n = _norm_email(email)
    name_n = _norm_name(name)
    name_ok = _name_usable(name_n)
    id_hash = str(national_id_hash or "").strip()
    own_customer = str(customer_id or "").strip()
    excluded = {str(item) for item in exclude_ids if item}

    customers_by_id = {
        str(cid): rec for cid, rec in (customers or {}).items() if isinstance(rec, Mapping)
    }

    def triggers_for(record: Mapping[str, Any], *, linked_customer: str = "") -> List[str]:
        found = []
        if email_n and _record_email(record) == email_n:
            found.append("email")
        if name_ok and _record_name(record) == name_n:
            found.append("name")
        cust_id = linked_customer or str(record.get("customer_id") or "")
        cust = customers_by_id.get(cust_id) or {}
        record_hash = str(
            record.get("national_id_hash")
            or (record.get("customer_identity") or {}).get("national_id_hash")
            or cust.get("national_id_hash")
            or ""
        )
        if id_hash and record_hash and record_hash == id_hash:
            found.append("id")
        return found

    matches: List[Dict[str, Any]] = []

    def add(kind: str, record_id: str, record: Mapping[str, Any], trigs: List[str]) -> None:
        if not trigs or record_id in excluded:
            return
        when = (
            record.get("submitted_date") or record.get("created_date")
            or record.get("created_at") or record.get("filed_date") or record.get("updated_at")
        )
        matches.append({
            "kind": kind,
            "id": record_id,
            "status": record.get("status"),
            "triggered_by": trigs,
            "label": record.get("customer_name") or record.get("name") or record.get("contact_name") or _record_email(record) or record_id,
            "when": when,
        })

    for app_id, app in (applications or {}).items():
        if not isinstance(app, Mapping):
            continue
        add("application", str(app.get("id") or app_id), app, triggers_for(app))
    for pol_id, pol in (policies or {}).items():
        if not isinstance(pol, Mapping):
            continue
        add("policy", str(pol.get("id") or pol_id), pol, triggers_for(pol))
    for claim_id, claim in (claims or {}).items():
        if not isinstance(claim, Mapping):
            continue
        add("claim", str(claim.get("id") or claim_id), claim, triggers_for(claim))

    for peer in peers or []:
        if not isinstance(peer, Mapping):
            continue
        peer_id = str(peer.get("id") or "")
        if not peer_id or peer_id in excluded:
            continue
        trigs = []
        if email_n and _norm_email(peer.get("email")) == email_n:
            trigs.append("email")
        peer_name = _norm_name(peer.get("name"))
        if name_ok and _name_usable(peer_name) and peer_name == name_n:
            trigs.append("name")
        if id_hash and str(peer.get("national_id_hash") or "") == id_hash:
            trigs.append("id")
        if trigs:
            add("chat", peer_id, {
                "id": peer_id,
                "status": peer.get("status"),
                "customer_name": peer.get("name"),
                "customer_email": peer.get("email"),
                "updated_at": peer.get("updated_at"),
            }, trigs)

    # Same identity on a customer row pulls that customer's other files even
    # when the email on the file differs. Those files are already added when
    # the hash sits on the file; this covers a customer match whose files were
    # stored only with customer_id.
    if id_hash:
        matched_customers = [
            cid for cid, rec in customers_by_id.items()
            if str(rec.get("national_id_hash") or "") == id_hash and cid != own_customer
        ]
        already = {item["id"] for item in matches}
        for cid in matched_customers:
            for app_id, app in (applications or {}).items():
                if not isinstance(app, Mapping):
                    continue
                if str(app.get("customer_id") or "") != cid:
                    continue
                record_id = str(app.get("id") or app_id)
                if record_id in already or record_id in excluded:
                    continue
                add("application", record_id, app, ["id"])
                already.add(record_id)

    matches.sort(key=lambda item: str(item.get("when") or ""), reverse=True)
    # Stable trigger order for tests and the staff page.
    for item in matches:
        item["triggered_by"] = sorted(set(item["triggered_by"]))
    return matches[:limit]


def _health_block(answers: Mapping[str, Any]) -> Dict[str, Any]:
    conditions = answers.get("conditions_list") or ""
    if not conditions and answers.get("medical_conditions") == "no":
        conditions = "none declared"
    narrative = answers.get("accident_narrative") or ""
    return {
        "tobacco": answers.get("tobacco"),
        "medical_conditions": answers.get("medical_conditions"),
        "main_problems": _clip(str(conditions)) if conditions else None,
        "surgery": answers.get("surgery"),
        "surgery_detail": _clip(str(answers.get("surgery_list") or "")) or None,
        "medications": _clip(str(answers.get("medications") or "")) or None,
        "family_history": answers.get("family_history"),
        "hazardous": answers.get("hazardous"),
        "daily_function": answers.get("daily_function"),
        "disclosure": _clip(str(answers.get("prior_disclosure") or "")) or None,
        "claim_type": answers.get("claim_type"),
        "what_happened": _clip(str(narrative)) if narrative else None,
        "provider": answers.get("provider"),
        "incident_date": answers.get("incident_date"),
        "incident_location": answers.get("incident_location"),
    }


def _billing_block(answers: Mapping[str, Any]) -> Dict[str, Any]:
    card = answers.get("payment_card") if isinstance(answers.get("payment_card"), dict) else {}
    amount = answers.get("claimed_amount")
    return {
        "billing_frequency": answers.get("billing_frequency"),
        "auto_pay": answers.get("auto_pay"),
        "card_last4": card.get("card_last4") or _last4(card.get("card_number")) or None,
        "cardholder_name": card.get("cardholder_name") or None,
        "expiry_month": card.get("expiry_month") or None,
        "expiry_year": card.get("expiry_year") or None,
        "policy_id": answers.get("policy_id"),
        "claimed_amount": amount,
    }


def subject_from_policy(session: Mapping[str, Any]) -> Dict[str, Any]:
    contact = session.get("contact") or {}
    answers = session.get("answers") or {}
    sig = answers.get("signature") if isinstance(answers.get("signature"), dict) else {}
    pointer = identity_pointer(
        answers.get("nationality") or sig.get("nationality"),
        answers.get("id_number") or sig.get("id_number"),
        answers.get("national_id_last4") or sig.get("national_id_last4") or sig.get("id_last4"),
    )
    if not pointer.get("national_id_hash"):
        stored = answers.get("national_id_hash") or sig.get("national_id_hash")
        if stored:
            pointer = {
                "nationality": (
                    pointer.get("nationality")
                    or answers.get("nationality")
                    or sig.get("nationality")
                ),
                "national_id_last4": (
                    pointer.get("national_id_last4")
                    or answers.get("national_id_last4")
                    or sig.get("national_id_last4")
                ),
                "national_id_hash": stored,
            }
    return {
        "customer_id": session.get("customer_id"),
        "name": contact.get("name") or answers.get("name"),
        "email": contact.get("email") or answers.get("email"),
        "phone": contact.get("phone") or answers.get("phone"),
        "dob": answers.get("dob"),
        "gender": answers.get("gender"),
        "occupation": answers.get("occupation"),
        "city": answers.get("city") or contact.get("city"),
        "country": answers.get("country") or contact.get("country"),
        "nationality": pointer.get("nationality") or answers.get("nationality"),
        "national_id_last4": pointer.get("national_id_last4"),
        "national_id_hash": pointer.get("national_id_hash"),
        "health": _health_block(answers),
        "billing": _billing_block(answers),
        "coverage": {
            "coverage_amount": answers.get("coverage_amount"),
            "coverage_years": answers.get("coverage_years"),
            "savings_addon": answers.get("savings_addon"),
        },
    }


def subject_from_claim(session: Mapping[str, Any]) -> Dict[str, Any]:
    contact = session.get("contact") or {}
    answers = session.get("answers") or {}
    sig = answers.get("signature") if isinstance(answers.get("signature"), dict) else {}
    facts = session.get("facts") or {}
    pointer = identity_pointer(sig.get("nationality"), sig.get("id_number"), sig.get("id_last4"))
    if not pointer.get("national_id_hash") and facts.get("national_id_hash"):
        pointer = {
            "nationality": facts.get("nationality") or pointer.get("nationality"),
            "national_id_last4": facts.get("national_id_last4") or pointer.get("national_id_last4"),
            "national_id_hash": facts.get("national_id_hash"),
        }
    profile = answers.get("profile") if isinstance(answers.get("profile"), dict) else {}
    return {
        "customer_id": session.get("customer_id"),
        "name": contact.get("name") or profile.get("name"),
        "email": contact.get("email") or profile.get("email"),
        "phone": contact.get("phone") or profile.get("phone"),
        "nationality": pointer.get("nationality"),
        "national_id_last4": pointer.get("national_id_last4"),
        "national_id_hash": pointer.get("national_id_hash"),
        "health": _health_block(answers),
        "billing": _billing_block(answers),
        "coverage": {},
    }


def build_seal(session: Mapping[str, Any], *, kind: str) -> Dict[str, Any]:
    """Redacted snapshot safe to ledger. Prior matches are not frozen here."""
    revisions = list(session.get("revisions") or [])
    ok, reason = verify_revisions(revisions)
    subject = subject_from_claim(session) if kind == "claim" else subject_from_policy(session)
    counts = edit_counts(revisions)
    return {
        "kind": kind,
        "application_id": session.get("id"),
        "status": session.get("status"),
        "revision_head": revisions[-1]["checksum"] if revisions else None,
        "revision_count": len(revisions),
        "edit_count": counts["total"],
        "counts": {k: counts[k] for k in list(_CATEGORIES) + ["total", "last_edited_at"]},
        "integrity_ok": ok,
        "integrity_reason": reason,
        "subject": subject,
        "revisions": revisions,
        "rejected_edits": list(session.get("rejected_edits") or []),
    }


def _contradictions(subject: Mapping[str, Any], applications: Mapping[str, Any],
                    claims: Mapping[str, Any]) -> List[Dict[str, Any]]:
    health = dict(subject.get("health") or {})
    answers = {
        "tobacco": health.get("tobacco"),
        "medical_conditions": health.get("medical_conditions"),
        "conditions_list": health.get("main_problems"),
        "surgery": health.get("surgery"),
        "medications": health.get("medications"),
        "family_history": health.get("family_history"),
        "hazardous": health.get("hazardous"),
    }
    try:
        from services.underwriting_integrity_service import (
            detect_claim_statement_contradictions,
            detect_statement_contradictions,
        )
    except Exception:
        return []
    found = detect_statement_contradictions(answers, list((applications or {}).values()))
    found.extend(detect_claim_statement_contradictions(answers, list((claims or {}).values())))
    return found


def build_review(
    *,
    kind: str,
    application_id: str,
    status: str,
    subject: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
    rejected_edits: Sequence[Mapping[str, Any]] = (),
    books: Optional[Mapping[str, Any]] = None,
    peers: Sequence[Mapping[str, Any]] = (),
    exclude_ids: Iterable[str] = (),
) -> Dict[str, Any]:
    ok, reason = verify_revisions(revisions)
    counts = edit_counts(revisions)
    books = books or {}
    matches = match_prior(
        email=subject.get("email"),
        name=subject.get("name"),
        national_id_hash=subject.get("national_id_hash"),
        customer_id=subject.get("customer_id"),
        applications=books.get("applications") or {},
        policies=books.get("policies") or {},
        claims=books.get("claims") or {},
        customers=books.get("customers") or {},
        peers=peers,
        exclude_ids=exclude_ids,
    )
    trigger_set = sorted({flag for item in matches for flag in item.get("triggered_by") or []})
    contradictions = _contradictions(
        subject, books.get("applications") or {}, books.get("claims") or {},
    )
    personal = {
        "name": subject.get("name"),
        "email": subject.get("email"),
        "phone": subject.get("phone"),
        "dob": subject.get("dob"),
        "gender": subject.get("gender"),
        "occupation": subject.get("occupation"),
        "city": subject.get("city"),
        "country": subject.get("country"),
        "nationality": subject.get("nationality"),
        "national_id_last4": subject.get("national_id_last4"),
        "customer_id": subject.get("customer_id"),
    }
    quick = {
        "personal": personal,
        "health": subject.get("health") or {},
        "billing": subject.get("billing") or {},
        "coverage": subject.get("coverage") or {},
        "edits": {
            "identity": counts["identity"],
            "health": counts["health"],
            "billing": counts["billing"],
            "coverage": counts["coverage"],
            "other": counts["consent"] + counts["other"],
            "total": counts["total"],
            "last_edited_at": counts["last_edited_at"],
        },
        "prior": {
            "count": len(matches),
            "triggered_by": trigger_set,
            "items": matches,
        },
    }
    full = {
        "revisions": [dict(rev) for rev in revisions],
        "intention": intention_shifts(revisions),
        "rejected_edits": [dict(row) for row in rejected_edits],
        "contradictions": contradictions,
        "prior": matches,
        "integrity": {
            "ok": ok,
            "reason": reason,
            "head": revisions[-1]["checksum"] if revisions else None,
            "revision_count": len(revisions),
        },
    }
    return {
        "ok": True,
        "kind": kind,
        "application_id": application_id,
        "status": status,
        "secret": True,
        "quick": quick,
        "full": full,
        "integrity": full["integrity"],
    }


def review_from_seal(seal: Mapping[str, Any], books: Optional[Mapping[str, Any]] = None,
                      peers: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    subject = seal.get("subject") or {}
    review = build_review(
        kind=str(seal.get("kind") or "policy_application"),
        application_id=str(seal.get("application_id") or ""),
        status=str(seal.get("status") or "submitted"),
        subject=subject,
        revisions=list(seal.get("revisions") or []),
        rejected_edits=list(seal.get("rejected_edits") or []),
        books=books,
        peers=peers,
        exclude_ids=[str(seal.get("application_id") or "")],
    )
    review["source"] = "ledger"
    return review


def _sequence_no(entry: Mapping[str, Any]) -> Optional[int]:
    try:
        return int(entry.get("sequence_no"))
    except (TypeError, ValueError):
        return None


def latest_seal(entries: Iterable[Mapping[str, Any]], application_id: str,
                event_type: str) -> Optional[Dict[str, Any]]:
    """Return the newest process seal for one chat.

    ``append_event`` stores the event payload as the ledger row itself, so the
    seal usually sits on the entry. A nested ``payload.seal`` is accepted too.
    A higher ``sequence_no`` wins. Rows without one keep the previous last-match
    order. The entries are not modified.
    """
    found = None
    found_seq: Optional[int] = None
    found_pos = -1
    wanted = str(application_id or "")
    for pos, entry in enumerate(entries or []):
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("event_type") or entry.get("type") or "") != event_type:
            continue
        payload = entry.get("payload") if isinstance(entry.get("payload"), Mapping) else {}
        linked = {
            str(entry.get("entity_id") or ""),
            str(entry.get("application_id") or ""),
            str(payload.get("application_id") or ""),
        }
        if wanted not in linked:
            continue
        seal = payload.get("seal") if isinstance(payload.get("seal"), dict) else entry.get("seal")
        if not isinstance(seal, dict):
            continue
        seq = _sequence_no(entry)
        if seq is None and payload:
            seq = _sequence_no(payload)
        if found is None:
            newer = True
        elif seq is None and found_seq is None:
            newer = pos >= found_pos
        elif seq is None:
            newer = False
        elif found_seq is None or seq > found_seq:
            newer = True
        elif seq == found_seq:
            newer = pos >= found_pos
        else:
            newer = False
        if newer:
            found = seal
            found_seq = seq
            found_pos = pos
    return found


def load_books() -> Dict[str, Dict[str, Any]]:
    try:
        try:
            from web_portal import server as portal
        except ImportError:
            import server as portal  # type: ignore
    except Exception:
        return {"applications": {}, "policies": {}, "claims": {}, "customers": {}}

    def _copy(name: str) -> Dict[str, Any]:
        raw = getattr(portal, name, {}) or {}
        try:
            return {str(k): v for k, v in dict(raw).items() if isinstance(v, dict)}
        except Exception:
            return {}

    return {
        "applications": _copy("UNDERWRITING_APPLICATIONS"),
        "policies": _copy("POLICIES"),
        "claims": _copy("CLAIMS"),
        "customers": _copy("CUSTOMERS"),
    }


# ---------------------------------------------------------------------------
# Staff review presentation. Controls and the AI note are response-only.
# ---------------------------------------------------------------------------

REVIEW_VIEWS = ("quick", "full", "both")
QUICK_REVIEW_SECTIONS = ("identity", "health", "billing", "coverage", "edits", "prior")
FULL_REVIEW_SECTIONS = ("intention", "revisions", "contradictions", "rejected", "prior")
ALL_REVIEW_SECTIONS = (
    "identity", "health", "billing", "coverage", "edits", "prior",
    "intention", "revisions", "contradictions", "rejected", "ai",
)
_QUICK_FIELDS = {
    "identity": "personal",
    "health": "health",
    "billing": "billing",
    "coverage": "coverage",
    "edits": "edits",
    "prior": "prior",
}
_FULL_FIELDS = {
    "intention": "intention",
    "revisions": "revisions",
    "contradictions": "contradictions",
    "rejected": "rejected_edits",
    "prior": "prior",
}
_HIDDEN_REVIEW_KEYS = frozenset({
    "card_number", "cvv", "id_number", "national_id", "signature_data", "data_b64",
})
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LONG_DIGITS = re.compile(r"\d{13,}")
_AI_DISCLAIMER = (
    "Advisory explanation of the sealed chat record. It does not underwrite, "
    "decide a claim, change billing, or pay a reward."
)


def _query_value(query: Optional[Mapping[str, Any]], name: str) -> Optional[str]:
    if not query:
        return None
    value = query.get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    return str(value)


def _sections_for_view(view: str) -> List[str]:
    if view == "quick":
        return list(QUICK_REVIEW_SECTIONS) + ["ai"]
    if view == "full":
        return list(FULL_REVIEW_SECTIONS) + ["ai"]
    return list(ALL_REVIEW_SECTIONS)


def parse_review_controls(query: Optional[Mapping[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str]]]:
    """Read view, sections, ask, and narrate. Nothing here is stored."""
    view = (_query_value(query, "view") or "both").strip().lower()
    if view not in REVIEW_VIEWS:
        return None, {"error": "view must be quick, full, or both"}
    raw = _query_value(query, "sections")
    if raw is None or not raw.strip():
        sections = _sections_for_view(view)
    else:
        sections = []
        for piece in raw.split(","):
            name = piece.strip().lower()
            if name and name not in sections:
                sections.append(name)
        if not sections:
            sections = _sections_for_view(view)
        else:
            unknown = [name for name in sections if name not in ALL_REVIEW_SECTIONS]
            if unknown:
                return None, {"error": "Unknown review section"}
    ask = (_query_value(query, "ask") or "").strip()
    if len(ask) > 500:
        return None, {"error": "ask is too long"}
    narrate = (_query_value(query, "narrate") or "").strip().lower() in {"1", "true", "yes", "on"}
    return {"view": view, "sections": sections, "ask": ask, "narrate": narrate}, None


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in value.items()
            if str(key) not in _HIDDEN_REVIEW_KEYS
        }
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _project_review(review: Mapping[str, Any], sections: Sequence[str],
                    integrity: Mapping[str, Any]) -> Dict[str, Any]:
    selected = set(sections)
    quick_src = review.get("quick") if isinstance(review.get("quick"), Mapping) else {}
    full_src = review.get("full") if isinstance(review.get("full"), Mapping) else {}
    quick: Dict[str, Any] = {}
    for section, key in _QUICK_FIELDS.items():
        if section in selected and key in quick_src:
            quick[key] = _plain(quick_src.get(key))
    full: Dict[str, Any] = {}
    for section, key in _FULL_FIELDS.items():
        if section in selected and key in full_src:
            full[key] = _plain(full_src.get(key))
    if full:
        full["integrity"] = {
            "ok": bool(integrity.get("ok")),
            "reason": integrity.get("reason") or "",
            "head": integrity.get("head"),
            "revision_count": integrity.get("revision_count"),
        }
    shown: Dict[str, Any] = {}
    if quick:
        shown["quick"] = quick
    if full:
        shown["full"] = full
    return shown


def _norm_num(token: str) -> str:
    text = str(token).replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _numbers_in(value: Any) -> set:
    if isinstance(value, str):
        blob = value
    else:
        blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return {_norm_num(token) for token in _NUMBER.findall(blob)}


def _narrative_template():
    import os

    from prompts import get_prompt

    pinned = os.environ.get("PHINS_ASSESSMENT_NARRATIVE_PROMPT_VERSION", "").strip()
    version = int(pinned) if pinned.isdigit() else None
    return get_prompt("narrative", version=version)


def _add_evidence(lines: List[Dict[str, str]], label: str, value: Any) -> None:
    if value is None or value == "" or value == [] or value == {}:
        return
    if isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = str(value).strip()
    if not text:
        return
    if len(re.sub(r"\D", "", text)) >= 13:
        return
    lines.append({"label": label, "value": text[:500]})


def sealed_evidence(review: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Facts the note may repeat. Last4 and nationality only; no full ID or PAN."""
    quick = review.get("quick") if isinstance(review.get("quick"), Mapping) else {}
    full = review.get("full") if isinstance(review.get("full"), Mapping) else {}
    lines: List[Dict[str, str]] = []
    _add_evidence(lines, "kind", review.get("kind"))
    _add_evidence(lines, "application", review.get("application_id"))
    _add_evidence(lines, "status", review.get("status"))
    integrity = review.get("integrity") if isinstance(review.get("integrity"), Mapping) else {}
    _add_evidence(lines, "answer chain", "intact" if integrity.get("ok") else "failed")
    personal = quick.get("personal") if isinstance(quick.get("personal"), Mapping) else {}
    for key in (
        "name", "email", "phone", "dob", "gender", "occupation", "city", "country",
        "nationality", "national_id_last4",
    ):
        _add_evidence(lines, key.replace("_", " "), personal.get(key))
    health = quick.get("health") if isinstance(quick.get("health"), Mapping) else {}
    for key, value in health.items():
        _add_evidence(lines, str(key).replace("_", " "), value)
    billing = quick.get("billing") if isinstance(quick.get("billing"), Mapping) else {}
    for key in (
        "billing_frequency", "auto_pay", "card_last4", "cardholder_name",
        "expiry_month", "expiry_year", "policy_id", "claimed_amount",
    ):
        _add_evidence(lines, str(key).replace("_", " "), billing.get(key))
    coverage = quick.get("coverage") if isinstance(quick.get("coverage"), Mapping) else {}
    for key, value in coverage.items():
        _add_evidence(lines, str(key).replace("_", " "), value)
    edits = quick.get("edits") if isinstance(quick.get("edits"), Mapping) else {}
    for key in ("identity", "health", "billing", "coverage", "other", "total"):
        if key in edits:
            label = "edit total" if key == "total" else f"{key} edits"
            _add_evidence(lines, label, edits.get(key))
    _add_evidence(lines, "last edit", edits.get("last_edited_at"))
    for row in full.get("intention") or []:
        if not isinstance(row, Mapping):
            continue
        label = row.get("label") or row.get("step_id") or "answer"
        if row.get("withdrawn"):
            _add_evidence(lines, f"intention {label}", f"from {row.get('from') or 'empty'} withdrawn")
        else:
            _add_evidence(
                lines, f"intention {label}",
                f"from {row.get('from') or 'empty'} to {row.get('to') or 'empty'}",
            )
    return lines[:40]


def _deterministic_explanation(evidence: Sequence[Mapping[str, str]], ask_received: bool) -> str:
    if evidence:
        body = " ".join(f"{item['label']}: {item['value']}." for item in evidence)
    else:
        body = "No sealed facts were available for this review."
    focus = ""
    if ask_received:
        focus = (
            " A staff question was applied as focus only; figures in that "
            "question are not treated as facts."
        )
    return (
        body + focus + " This note explains the sealed record. It does not "
        "underwrite, decide a claim, change billing, or pay a reward."
    ).strip()


def _ai_base(template) -> Dict[str, Any]:
    schema = template.response_schema or {}
    return {
        "source": "assessment_ai",
        "mode": "deterministic",
        "advisory": True,
        "needs_review": True,
        "decides": False,
        "summary_text": "",
        "key_points": [],
        "review_flags": [],
        "evidence": [],
        **template.provenance(),
        "schema_id": schema.get("$id"),
        "disclaimer": _AI_DISCLAIMER,
    }


def explain_sealed_review(review: Mapping[str, Any], *, ask: str = "",
                          narrate: bool = False, provider: Any = None) -> Dict[str, Any]:
    """Explain the sealed facts. Does not persist a narrative or a decision.

    The live model is used only when ``narrate`` is set. A schema failure, an
    unavailable model, or a figure that is not on the seal keeps the
    deterministic note.
    """
    template = _narrative_template()
    report = _ai_base(template)
    integrity = review.get("integrity") if isinstance(review.get("integrity"), Mapping) else {}
    if review.get("withheld") or not integrity.get("ok"):
        report["source"] = "withheld"
        report["fallback_reason"] = "checksum_failed"
        return report
    evidence = sealed_evidence(review)
    report["evidence"] = evidence
    report["summary_text"] = _deterministic_explanation(evidence, bool(str(ask or "").strip()))
    if not narrate:
        return report
    schema = template.response_schema
    try:
        from services.llm_providers import (
            LLMUnavailableError,
            LLMValidationError,
            get_llm_provider,
            validate_json_schema,
        )
    except Exception:
        report["fallback_reason"] = "llm_unavailable"
        return report
    if provider is None:
        provider = get_llm_provider()
    user = json.dumps({
        "instruction": (
            "Explain only the evidence. Do not invent a number, an identifier, "
            "or a condition. Do not decide underwriting, a claim, billing, or a "
            "reward. needs_review must be true. A staff question is focus, not a fact."
        ),
        "staff_question": str(ask or "").strip() or None,
        "evidence": evidence,
    }, ensure_ascii=False)
    try:
        if schema is None:
            text = provider.completion(template.system_prompt, user)
            result = {
                "summary_text": str(text or "").strip(),
                "key_points": [],
                "review_flags": [],
                "needs_review": True,
            }
            if not result["summary_text"]:
                raise ValueError("empty")
        else:
            result = provider.structured_completion(template.system_prompt, user, schema)
    except LLMUnavailableError:
        report["fallback_reason"] = "llm_unavailable"
        return report
    except LLMValidationError:
        report["fallback_reason"] = "schema_invalid"
        return report
    except Exception:
        report["fallback_reason"] = "llm_failed"
        return report
    if not isinstance(result, dict):
        report["fallback_reason"] = "schema_invalid"
        return report
    if schema is not None:
        errors = validate_json_schema(result, schema)
        if errors or result.get("needs_review") is not True:
            report["fallback_reason"] = "schema_invalid"
            return report
    points = list(result.get("key_points") or [])
    for point in points:
        if not isinstance(point, Mapping):
            report["fallback_reason"] = "schema_invalid"
            return report
        index = point.get("evidence_index")
        if index is None:
            continue
        if isinstance(index, bool) or not isinstance(index, int) or not (0 <= index < len(evidence)):
            report["fallback_reason"] = "schema_invalid"
            return report
    model_text = " ".join([
        str(result.get("summary_text") or ""),
        " ".join(str((point or {}).get("point") or "") for point in points),
        " ".join(str(flag) for flag in (result.get("review_flags") or [])),
    ])
    extra = _numbers_in(model_text) - _numbers_in(evidence)
    if extra or _LONG_DIGITS.search(model_text):
        report["fallback_reason"] = "narrative_introduced_numbers"
        short = sorted(token for token in extra if len(token) <= 6)
        if short and len(short) == len(extra):
            report["rejected_numbers"] = short
        return report
    report["mode"] = "llm"
    report["summary_text"] = str(result.get("summary_text") or "").strip()
    report["key_points"] = [dict(point) for point in points]
    report["review_flags"] = [str(flag) for flag in (result.get("review_flags") or [])]
    return report


def present_process_review(review: Mapping[str, Any], *, view: str = "both",
                           sections: Optional[Sequence[str]] = None, ask: str = "",
                           narrate: bool = False, provider: Any = None) -> Dict[str, Any]:
    """Copy the review down to the requested sections. The source is not written."""
    view_name = str(view or "both").strip().lower()
    if view_name not in REVIEW_VIEWS:
        view_name = "both"
    selected = list(sections) if sections is not None else _sections_for_view(view_name)
    integrity = review.get("integrity") if isinstance(review.get("integrity"), Mapping) else {}
    withheld = not bool(integrity.get("ok"))
    shown: Dict[str, Any] = {
        "kind": review.get("kind"),
        "application_id": review.get("application_id"),
        "status": review.get("status"),
        "secret": True,
        "source": review.get("source"),
        "integrity": {
            "ok": bool(integrity.get("ok")),
            "reason": integrity.get("reason") or "",
            "withheld": withheld,
            "head": None if withheld else integrity.get("head"),
            "revision_count": integrity.get("revision_count"),
        },
        "controls": {
            "view": view_name,
            "sections": list(selected),
            "ask": str(ask or "").strip() or None,
            "narrate": bool(narrate),
        },
    }
    if withheld:
        shown["withheld"] = True
        if "ai" in selected:
            shown["ai_report"] = explain_sealed_review(
                {"withheld": True, "integrity": {"ok": False}},
                ask=ask, narrate=False,
            )
        return shown
    shown.update(_project_review(review, selected, integrity))
    if "ai" in selected:
        shown["ai_report"] = explain_sealed_review(
            review, ask=ask, narrate=narrate, provider=provider,
        )
    return shown


def memory_ledger_entries() -> List[Dict[str, Any]]:
    try:
        try:
            from web_portal import server as portal
        except ImportError:
            import server as portal  # type: ignore
        raw = getattr(portal, "TRANSACTION_LEDGER", {}) or {}
        return [entry for entry in raw.values() if isinstance(entry, dict)]
    except Exception as exc:
        logger.warning("Process review ledger scan failed: %s", type(exc).__name__)
        return []


def database_seal_entries(application_id: str, event_type: str) -> List[Dict[str, Any]]:
    """Read one chat's seal rows. Does not copy them into the memory ledger."""
    try:
        try:
            from web_portal import server as portal
        except ImportError:
            import server as portal  # type: ignore
    except Exception:
        return []
    if not (getattr(portal, "USE_DATABASE", False) and getattr(portal, "database_enabled", False)):
        return []
    try:
        from database.manager import DatabaseManager

        with DatabaseManager() as db:
            rows = db.platform_ledger.get_by_entity_event(application_id, event_type, limit=5)
            copied = [row.to_dict() for row in rows or [] if row is not None]
            db.rollback()
            return copied
    except Exception as exc:
        logger.warning(
            "Process review database seal read failed for %s: %s",
            application_id, type(exc).__name__,
        )
        return []


def serve_process_review(session_review: Mapping[str, Any], application_id: str,
                         event_type: str, query: Optional[Mapping[str, Any]] = None, *,
                         provider: Any = None,
                         memory_entries: Optional[Sequence[Mapping[str, Any]]] = None,
                         db_entries: Optional[Sequence[Mapping[str, Any]]] = None,
                         ) -> Tuple[int, Dict[str, Any]]:
    """One staff read of a policy chat or a claim chat.

    The in-memory session wins while it exists. After it is gone the seal is
    read from the memory ledger, then from the database row. A bad checksum is
    withheld. This function does not write either store.
    """
    controls, error = parse_review_controls(query)
    if error:
        return 400, error
    assert controls is not None
    if session_review.get("ok"):
        review: Mapping[str, Any] = session_review
    else:
        memory = list(memory_entries) if memory_entries is not None else memory_ledger_entries()
        seal = latest_seal(memory, application_id, event_type)
        if seal is None:
            rows = list(db_entries) if db_entries is not None else database_seal_entries(
                application_id, event_type,
            )
            seal = latest_seal(rows, application_id, event_type)
        if seal is None:
            return int(session_review.get("status_code") or 404), {
                "error": session_review.get("error") or "Application not found",
            }
        review = review_from_seal(seal, load_books())
    shown = present_process_review(
        review,
        view=controls["view"],
        sections=controls["sections"],
        ask=controls["ask"],
        narrate=controls["narrate"],
        provider=provider,
    )
    return 200, shown
