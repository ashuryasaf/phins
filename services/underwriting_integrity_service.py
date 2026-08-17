"""
Underwriting integrity pipeline
===============================

Bridges actuarial pricing (system key) with per-customer underwriting
fine-tuning, and keeps durable history / media / contracts aligned.

Capabilities
------------
- Contradiction scan vs prior applications, policies, and claims
- Application history archive on reject (leave pending queue, keep forever)
- Premium adjustment fine-tune on approve (actuarial base × UW loading)
- Branded policy contract generation + email after approval
- Durable media inventory for an underwriting file
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("phins.underwriting_integrity")

COMPARE_FIELDS = (
    "tobacco",
    "smoke",
    "smoking_status",
    "occupation",
    "family_history",
    "medications",
    "medical_conditions",
    "conditions_list",
    "surgery",
    "hazardous",
    "hazardous_activities",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = sorted(_norm(v) for v in value if _norm(v) and _norm(v) != "none")
        return ",".join(parts)
    text = str(value).strip().lower()
    aliases = {
        "yes": "yes", "true": "yes", "smoker": "yes", "current": "yes",
        "no": "no", "false": "no", "never": "no", "nonsmoker": "no",
        "non-smoker": "no", "none": "none", "n/a": "none", "na": "none",
    }
    return aliases.get(text, text)


def _questionnaire_of(record: Dict[str, Any]) -> Dict[str, Any]:
    q = record.get("questionnaire_responses") or record.get("questionnaire") or {}
    if isinstance(q, str):
        try:
            q = json.loads(q)
        except (TypeError, ValueError):
            q = {}
    return q if isinstance(q, dict) else {}


def _field_from_record(record: Dict[str, Any], field: str) -> Any:
    q = _questionnaire_of(record)
    if field in q and q.get(field) not in (None, ""):
        return q.get(field)
    if field in record and record.get(field) not in (None, ""):
        return record.get(field)
    # Smoking aliases across chat / classic / denormalized columns
    if field in ("tobacco", "smoke", "smoking_status"):
        for key in ("smoking_status", "tobacco", "smoke"):
            if q.get(key) not in (None, ""):
                return q.get(key)
            if record.get(key) not in (None, ""):
                return record.get(key)
    if field in ("hazardous", "hazardous_activities"):
        return q.get("hazardous") or q.get("hazardous_activities") or record.get("hazardous")
    return None


def find_prior_customer_records(
    *,
    email: Optional[str],
    customer_id: Optional[str],
    underwriting_apps: Dict[str, Dict[str, Any]],
    policies: Dict[str, Dict[str, Any]],
    claims: Dict[str, Dict[str, Any]],
    exclude_app_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Collect prior UW apps / policies / claims for the same person."""
    email_l = str(email or "").strip().lower()
    cust = str(customer_id or "").strip()
    prior_apps: List[Dict[str, Any]] = []
    for app_id, app in (underwriting_apps or {}).items():
        if exclude_app_id and app_id == exclude_app_id:
            continue
        app_email = str(app.get("customer_email") or "").strip().lower()
        app_cust = str(app.get("customer_id") or "").strip()
        if (email_l and app_email == email_l) or (cust and app_cust == cust):
            prior_apps.append(app)

    prior_policies: List[Dict[str, Any]] = []
    for pol in (policies or {}).values():
        pol_cust = str(pol.get("customer_id") or "").strip()
        pol_email = str(pol.get("customer_email") or "").strip().lower()
        if (cust and pol_cust == cust) or (email_l and pol_email == email_l):
            prior_policies.append(pol)

    prior_claims: List[Dict[str, Any]] = []
    for claim in (claims or {}).values():
        claim_cust = str(claim.get("customer_id") or "").strip()
        if cust and claim_cust == cust:
            prior_claims.append(claim)
        else:
            # Match claims linked to prior policies for this email
            pol_id = claim.get("policy_id")
            if pol_id and any(p.get("id") == pol_id for p in prior_policies):
                prior_claims.append(claim)

    return {
        "applications": prior_apps,
        "policies": prior_policies,
        "claims": prior_claims,
    }


def detect_statement_contradictions(
    current_answers: Dict[str, Any],
    prior_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compare current chat/classic answers against prior underwriting statements."""
    contradictions: List[Dict[str, Any]] = []
    if not prior_records:
        return contradictions

    for field in COMPARE_FIELDS:
        current_raw = current_answers.get(field)
        if field in ("tobacco", "smoke", "smoking_status"):
            current_raw = (
                current_answers.get("tobacco")
                or current_answers.get("smoke")
                or current_answers.get("smoking_status")
            )
        current_n = _norm(current_raw)
        if not current_n or current_n in ("none",):
            # Still compare smoking no/yes — "no" is meaningful
            if field not in ("tobacco", "smoke", "smoking_status") or current_raw in (None, ""):
                continue

        for prior in prior_records:
            prior_raw = _field_from_record(prior, field)
            prior_n = _norm(prior_raw)
            if not prior_n:
                continue
            # Normalize smoking family to one comparison key
            if field in ("tobacco", "smoke", "smoking_status"):
                if current_n == prior_n:
                    continue
                # Treat yes/current vs no/never as contradiction
                contradictions.append({
                    "field": "smoking_status",
                    "label": "Smoking / tobacco use",
                    "current": current_raw,
                    "previous": prior_raw,
                    "previous_application_id": prior.get("id"),
                    "previous_status": prior.get("status"),
                })
                break
            if current_n != prior_n:
                contradictions.append({
                    "field": field,
                    "label": field.replace("_", " ").title(),
                    "current": current_raw,
                    "previous": prior_raw,
                    "previous_application_id": prior.get("id"),
                    "previous_status": prior.get("status"),
                })
                break
    # De-dupe by field
    seen = set()
    unique: List[Dict[str, Any]] = []
    for item in contradictions:
        key = item["field"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def detect_claim_statement_contradictions(
    current_answers: Dict[str, Any],
    claims: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Flag claim narratives that conflict with current medical statements."""
    findings: List[Dict[str, Any]] = []
    if not claims:
        return findings
    smoker_now = _norm(
        current_answers.get("tobacco")
        or current_answers.get("smoke")
        or current_answers.get("smoking_status")
    )
    meds_now = _norm(current_answers.get("medications"))
    conditions_now = _norm(
        current_answers.get("conditions_list")
        or current_answers.get("medical_conditions")
    )
    for claim in claims:
        blob = " ".join(str(claim.get(k) or "") for k in (
            "description", "notes", "diagnosis", "cause", "details", "ai_assessment_notes"
        )).lower()
        if not blob:
            continue
        if smoker_now in ("no", "never") and any(
            token in blob for token in ("smoker", "smoking", "tobacco", "cigarette")
        ):
            findings.append({
                "field": "smoking_status",
                "label": "Smoking vs prior claim narrative",
                "current": current_answers.get("tobacco") or "no",
                "previous": f"Claim {claim.get('id')} mentions smoking/tobacco",
                "previous_application_id": claim.get("id"),
                "previous_status": claim.get("status"),
                "source": "claim",
            })
        if meds_now in ("", "none", "no") and any(
            token in blob for token in ("medication", "prescription", "drug therapy")
        ):
            findings.append({
                "field": "medications",
                "label": "Medications vs prior claim narrative",
                "current": current_answers.get("medications") or "none",
                "previous": f"Claim {claim.get('id')} mentions medications",
                "previous_application_id": claim.get("id"),
                "previous_status": claim.get("status"),
                "source": "claim",
            })
        if conditions_now in ("", "none", "no") and any(
            token in blob for token in ("diabetes", "hypertension", "cancer", "heart disease")
        ):
            findings.append({
                "field": "medical_conditions",
                "label": "Medical conditions vs prior claim narrative",
                "current": current_answers.get("conditions_list") or "none",
                "previous": f"Claim {claim.get('id')} mentions a serious condition",
                "previous_application_id": claim.get("id"),
                "previous_status": claim.get("status"),
                "source": "claim",
            })
    seen = set()
    unique = []
    for item in findings:
        if item["field"] in seen:
            continue
        seen.add(item["field"])
        unique.append(item)
    return unique


def build_disclosure_prompt(contradictions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Chat step content for contradiction explain OR open medical disclosure."""
    if contradictions:
        lines = [
            "Before we continue, I compared your answers with your earlier PHINS file "
            "and found differences that need a clear explanation (this protects both of us):"
        ]
        for item in contradictions[:6]:
            lines.append(
                f"- {item.get('label')}: you just said “{item.get('current')}”, "
                f"earlier file had “{item.get('previous')}” "
                f"({item.get('previous_application_id') or 'prior record'})."
            )
        lines.append(
            "Please explain each difference in your own words. Underwriting will review "
            "this alongside your declarations."
        )
        return {
            "mode": "contradiction",
            "prompt": " ".join(lines),
            "contradictions": contradictions,
            "placeholder": "Explain the differences (required)",
            "require_nonempty": True,
        }
    return {
        "mode": "open_disclosure",
        "prompt": (
            "One more health question. By applying you are releasing medical confidentiality "
            "to PHINS underwriting for this application. Please describe any other medical "
            "information we should know now — diagnoses, treatments, tests, or symptoms not "
            "already covered. If there is nothing else, type \"none\"."
        ),
        "contradictions": [],
        "placeholder": 'Any other medical details — or type "none"',
        "require_nonempty": True,
    }


def apply_premium_adjustment(
    *,
    policy: Dict[str, Any],
    app: Dict[str, Any],
    adjustment: Any,
    risk_factor_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Fine-tune actuarial/quoted premiums by underwriter loading percentage.

    ``adjustment`` may be a fraction (0.15) or a percent (15). Values with an
    absolute magnitude of at least 1 are treated as percents so an underwriter
    "1%" loading is billed as 1% (not 100%); only magnitudes strictly below 1
    are treated as already-fractional. Actuarial base premiums stay on the
    policy as ``actuarial_*``; billed premiums update.
    """
    try:
        adj = float(adjustment if adjustment is not None else 0)
    except (TypeError, ValueError):
        adj = 0.0
    if abs(adj) >= 1.0:
        adj = adj / 100.0
    adj = max(-0.5, min(2.0, adj))

    monthly = float(policy.get("monthly_premium") or 0)
    annual = float(policy.get("annual_premium") or 0)
    if monthly <= 0 and annual > 0:
        monthly = annual / 12.0
    if annual <= 0 and monthly > 0:
        annual = monthly * 12.0

    policy.setdefault("actuarial_monthly_premium", monthly)
    policy.setdefault("actuarial_annual_premium", annual)
    policy["underwriting_loading"] = adj
    policy["monthly_premium"] = round(monthly * (1.0 + adj), 2)
    policy["annual_premium"] = round(annual * (1.0 + adj), 2)
    policy["quarterly_premium"] = round(policy["monthly_premium"] * 3 * 0.97, 2)

    app["premium_adjustment"] = int(round(adj * 100))
    factors = list(app.get("underwriting_risk_factors") or [])
    if adj != 0:
        factors.append({
            "name": "Underwriter premium adjustment",
            "category": "underwriting",
            "impact": adj,
            "direction": "increase" if adj > 0 else "decrease",
            "explanation": risk_factor_note or (
                f"Manual premium loading of {adj * 100:.1f}% applied at approval"
            ),
            "recorded_at": _utc_now_iso(),
        })
    app["underwriting_risk_factors"] = factors
    return {
        "loading": adj,
        "monthly_premium": policy["monthly_premium"],
        "annual_premium": policy["annual_premium"],
        "actuarial_monthly_premium": policy["actuarial_monthly_premium"],
        "actuarial_annual_premium": policy["actuarial_annual_premium"],
    }


def archive_rejected_application(
    app: Dict[str, Any],
    *,
    reason: str,
    rejected_by: str,
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Remove from active UW queue (status=rejected) while preserving history."""
    now = _utc_now_iso()
    history_entry = {
        "id": app.get("id"),
        "status": "rejected",
        "decision": "rejected",
        "reason": reason,
        "rejected_by": rejected_by,
        "decided_at": now,
        "customer_id": app.get("customer_id"),
        "customer_email": app.get("customer_email"),
        "coverage_amount": app.get("coverage_amount"),
        "risk_assessment": app.get("risk_assessment") or app.get("risk_score"),
        "chat_application_id": app.get("chat_application_id"),
        "policy_id": app.get("policy_id"),
        "source": app.get("source") or app.get("application_channel"),
    }
    app["status"] = "rejected"
    app["decision_date"] = now
    app["rejection_reason"] = reason
    app["rejected_by"] = rejected_by
    app["archived_from_queue_at"] = now
    app["active_queue"] = False
    decision_history = list(app.get("decision_history") or [])
    decision_history.append(history_entry)
    app["decision_history"] = decision_history
    # Persist a compact copy under data_sources (DB-safe JSON column)
    sources = dict(app.get("data_sources") or {})
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except (TypeError, ValueError):
            sources = {}
    hist = list(sources.get("application_history") or [])
    hist.append(history_entry)
    sources["application_history"] = hist
    app["data_sources"] = sources

    if customer is not None:
        cust_hist = list(customer.get("application_history") or [])
        cust_hist.append(history_entry)
        customer["application_history"] = cust_hist
        customer["updated_date"] = now
    return history_entry


def collect_application_media(
    *,
    app: Dict[str, Any],
    underwriting_files: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Durable media inventory (vault pointers preferred over inline bytes)."""
    app_id = str(app.get("id") or "")
    chat_id = str(app.get("chat_application_id") or "")
    items: List[Dict[str, Any]] = []
    for file_id, meta in (underwriting_files or {}).items():
        if not isinstance(meta, dict):
            continue
        linked = (
            meta.get("application_id") == app_id
            or (chat_id and meta.get("application_id") == chat_id)
            or (chat_id and meta.get("chat_application_id") == chat_id)
            or meta.get("chat_application_id") == app_id
        )
        if not linked:
            continue
        items.append({
            "id": file_id,
            "name": meta.get("name"),
            "kind": meta.get("kind") or meta.get("type"),
            "mime_type": meta.get("type") or meta.get("mime_type"),
            "size": meta.get("size"),
            "sha256": meta.get("sha256"),
            "persistent_doc_id": meta.get("persistent_doc_id"),
            "storage_path": meta.get("storage_path"),
        })
    # Also include media array stored on the application (chat referral)
    for media in app.get("media") or []:
        if not isinstance(media, dict):
            continue
        items.append({
            "id": media.get("id") or media.get("sha256"),
            "name": media.get("name"),
            "kind": media.get("kind"),
            "mime_type": media.get("mime_type"),
            "size": media.get("size"),
            "sha256": media.get("sha256"),
            "persistent_doc_id": media.get("persistent_doc_id"),
            "storage_path": media.get("storage_path"),
        })
    # De-dupe by sha256 / id
    seen = set()
    unique = []
    for item in items:
        key = item.get("sha256") or item.get("persistent_doc_id") or item.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _integrity_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_policy_contract(
    *,
    policy: Dict[str, Any],
    customer: Dict[str, Any],
    app: Dict[str, Any],
    bill: Optional[Dict[str, Any]] = None,
    media: Optional[List[Dict[str, Any]]] = None,
    base_url: str = "https://www.phins.ai",
    invite_or_login_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a branded HTML policy contract with integrity seal."""
    q = _questionnaire_of(app)
    payment = app.get("payment_setup") or {}
    if isinstance(payment, str):
        try:
            payment = json.loads(payment)
        except (TypeError, ValueError):
            payment = {}
    quote = app.get("quote_summary") or (app.get("data_sources") or {}).get("quote_summary") or {}
    if isinstance(quote, str):
        try:
            quote = json.loads(quote)
        except (TypeError, ValueError):
            quote = {}

    portal_url = f"{base_url.rstrip('/')}/login.html"
    track_url = f"{base_url.rstrip('/')}/track-application.html"
    if invite_or_login_code:
        track_url = f"{track_url}?code={invite_or_login_code}"
    qr_url = (
        "https://api.qrserver.com/v1/create-qr-code/?size=160x160&data="
        + html.escape(track_url if invite_or_login_code else portal_url, quote=True)
    )

    declarations = {
        "dob": q.get("dob"),
        "gender": q.get("gender") or app.get("gender"),
        "occupation": q.get("occupation") or app.get("occupation"),
        "height_cm": q.get("height") or app.get("height_cm"),
        "weight_kg": q.get("weight") or app.get("weight_kg"),
        "tobacco": q.get("tobacco") or q.get("smoke") or app.get("smoking_status"),
        "medical_conditions": q.get("medical_conditions"),
        "conditions_list": q.get("conditions_list"),
        "surgery": q.get("surgery"),
        "surgery_list": q.get("surgery_list"),
        "hazardous": q.get("hazardous") or q.get("hazardous_activities"),
        "family_history": q.get("family_history"),
        "medications": q.get("medications"),
        "daily_function": q.get("daily_function"),
        "adl_level": app.get("adl_level") or q.get("adl_level"),
        "prior_disclosure": q.get("prior_disclosure") or app.get("prior_disclosure"),
        "disclosure_mode": q.get("disclosure_mode") or app.get("disclosure_mode"),
        "signature_name": app.get("signature_name") or q.get("signature_name"),
        "signature_at": app.get("signature_at") or q.get("signature_at"),
        "consent": q.get("consent") or "agree",
    }

    savings_annual = float(
        quote.get("savings_premium_annual")
        or policy.get("savings_premium_annual")
        or 0
    )
    risk_annual = float(
        quote.get("risk_premium_annual")
        or policy.get("risk_premium_annual")
        or policy.get("actuarial_annual_premium")
        or policy.get("annual_premium")
        or 0
    )

    body = {
        "policy_id": policy.get("id"),
        "underwriting_id": app.get("id") or policy.get("underwriting_id"),
        "customer_id": customer.get("id") or app.get("customer_id"),
        "issued_at": _utc_now_iso(),
        "product_id": policy.get("type") or app.get("policy_type") or "phins_unified",
        "coverage_amount": policy.get("coverage_amount") or app.get("coverage_amount"),
        "monthly_premium": policy.get("monthly_premium"),
        "annual_premium": policy.get("annual_premium"),
        "actuarial_monthly_premium": policy.get("actuarial_monthly_premium"),
        "actuarial_annual_premium": policy.get("actuarial_annual_premium"),
        "underwriting_loading": policy.get("underwriting_loading") or 0,
        "risk_premium_annual": risk_annual,
        "savings_premium_annual": savings_annual,
        "tables_version": quote.get("tables_version") or policy.get("tables_version"),
        "config_version": quote.get("config_version") or policy.get("config_version"),
        "declarations": declarations,
        "card_last4": (
            payment.get("card_last4")
            or (
                ((bill or {}).get("payment_method") or {}).get("card_last4")
                if isinstance((bill or {}).get("payment_method"), dict)
                else None
            )
        ),
        "billing_frequency": (bill or {}).get("billing_frequency") or payment.get("billing_frequency") or "monthly",
        "media_count": len(media or []),
        "media_sha256": [m.get("sha256") for m in (media or []) if m.get("sha256")],
    }
    seal = _integrity_hash(body)
    body["integrity_hash"] = seal

    name = html.escape(str(customer.get("name") or app.get("customer_name") or "Policyholder"))
    email = html.escape(str(customer.get("email") or app.get("customer_email") or ""))
    phone = html.escape(str(customer.get("phone") or app.get("customer_phone") or ""))
    policy_id = html.escape(str(policy.get("id") or ""))
    product = html.escape(str(body["product_id"]).replace("_", " ").title())

    decl_rows = "".join(
        f"<tr><td>{html.escape(str(k).replace('_', ' ').title())}</td>"
        f"<td>{html.escape(str(v) if v not in (None, '') else '—')}</td></tr>"
        for k, v in declarations.items()
    )
    media_rows = "".join(
        f"<tr><td>{html.escape(str(m.get('kind') or 'file'))}</td>"
        f"<td>{html.escape(str(m.get('name') or ''))}</td>"
        f"<td><code>{html.escape(str(m.get('sha256') or m.get('persistent_doc_id') or '')[:16])}</code></td></tr>"
        for m in (media or [])
    ) or "<tr><td colspan='3'>No supporting media attached</td></tr>"

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>PHINS Policy Contract {policy_id}</title>
<style>
  :root {{ --phins-navy:#0d47a1; --phins-deep:#12284c; --phins-gold:#c9a227; --phins-ice:#f4f7fb; }}
  body {{ font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; color: var(--phins-deep);
         margin:0; background: linear-gradient(180deg,#e8eef8 0%,#ffffff 40%); }}
  .sheet {{ max-width: 800px; margin: 24px auto; background:#fff; border:1px solid #d5deee;
            box-shadow: 0 12px 40px rgba(13,71,161,.08); }}
  .banner {{ background: linear-gradient(135deg, var(--phins-navy), #1565c0 55%, #0d47a1);
             color:#fff; padding:28px 32px; display:flex; justify-content:space-between; gap:16px; }}
  .brand {{ font-size:28px; font-weight:800; letter-spacing:.04em; }}
  .brand small {{ display:block; font-size:12px; opacity:.85; font-weight:500; letter-spacing:.12em; text-transform:uppercase; }}
  .seal {{ font-size:11px; background:rgba(255,255,255,.12); padding:8px 10px; border-radius:8px; }}
  h2 {{ color: var(--phins-navy); border-bottom:2px solid var(--phins-gold); padding-bottom:6px; margin-top:28px; }}
  .pad {{ padding: 8px 32px 32px; }}
  table {{ width:100%; border-collapse:collapse; margin:12px 0; }}
  td, th {{ border:1px solid #e1e8f5; padding:8px 10px; text-align:left; font-size:13px; }}
  th {{ background: var(--phins-ice); color: var(--phins-navy); }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .card {{ background: var(--phins-ice); border:1px solid #d7e2f5; border-radius:10px; padding:14px; }}
  .card .lbl {{ font-size:11px; color:#5a6780; text-transform:uppercase; letter-spacing:.06em; }}
  .card .val {{ font-size:18px; font-weight:700; color: var(--phins-deep); margin-top:4px; }}
  .qr {{ text-align:center; }}
  .foot {{ background:#0f1a2e; color:#9fb0d0; padding:14px 32px; font-size:11px; }}
  code {{ font-size:11px; }}
</style></head>
<body>
  <div class="sheet">
    <div class="banner">
      <div class="brand">PHINS<small>Insurance · Life &amp; Disability</small></div>
      <div class="seal">Policy Contract<br/>Integrity {html.escape(seal[:16])}…</div>
    </div>
    <div class="pad">
      <p>This contract is issued from the actuarial pricing center rates, fine-tuned by underwriting
         for this customer, and hash-sealed for data integrity.</p>
      <div class="grid">
        <div class="card"><div class="lbl">Policy</div><div class="val">{policy_id}</div></div>
        <div class="card"><div class="lbl">Product</div><div class="val">{product}</div></div>
        <div class="card"><div class="lbl">Coverage</div><div class="val">${float(body['coverage_amount'] or 0):,.0f}</div></div>
        <div class="card"><div class="lbl">Monthly premium</div><div class="val">${float(body['monthly_premium'] or 0):,.2f}</div></div>
      </div>

      <h2>1. Policyholder</h2>
      <table>
        <tr><th>Name</th><td>{name}</td></tr>
        <tr><th>Customer ID</th><td>{html.escape(str(body['customer_id'] or ''))}</td></tr>
        <tr><th>Email</th><td>{email}</td></tr>
        <tr><th>Phone</th><td>{phone}</td></tr>
        <tr><th>Electronic signature</th><td>{html.escape(str(declarations.get('signature_name') or '—'))}
            <div style="font-size:11px;color:#5a6780">{html.escape(str(declarations.get('signature_at') or ''))}</div></td></tr>
      </table>

      <h2>2. Medical &amp; underwriting declarations</h2>
      <table><tr><th>Declaration</th><th>Customer statement</th></tr>{decl_rows}</table>

      <h2>3. Premium &amp; savings (actuarial base + underwriting fine-tune)</h2>
      <table>
        <tr><th>Actuarial annual (tables {html.escape(str(body.get('tables_version') or 'n/a'))})</th>
            <td>${float(body.get('actuarial_annual_premium') or risk_annual or 0):,.2f}</td></tr>
        <tr><th>Risk premium (annual)</th><td>${risk_annual:,.2f}</td></tr>
        <tr><th>Savings premium (annual)</th><td>${savings_annual:,.2f}</td></tr>
        <tr><th>Underwriting loading</th><td>{float(body.get('underwriting_loading') or 0)*100:.1f}%</td></tr>
        <tr><th>Billed monthly / annual</th>
            <td>${float(body['monthly_premium'] or 0):,.2f} / ${float(body['annual_premium'] or 0):,.2f}</td></tr>
        <tr><th>Config version</th><td>{html.escape(str(body.get('config_version') or 'n/a'))}</td></tr>
      </table>

      <h2>4. Billing &amp; payment method</h2>
      <table>
        <tr><th>Billing frequency</th><td>{html.escape(str(body.get('billing_frequency') or 'monthly').title())}</td></tr>
        <tr><th>Payment card (last 4)</th><td>**** {html.escape(str(body.get('card_last4') or '————'))}</td></tr>
        <tr><th>Next bill</th><td>{html.escape(str((bill or {}).get('due_date') or 'Per schedule'))}</td></tr>
        <tr><th>Bill ID</th><td>{html.escape(str((bill or {}).get('id') or '—'))}</td></tr>
      </table>

      <h2>5. Supporting media (voice / video / files)</h2>
      <table><tr><th>Kind</th><th>Name</th><th>Integrity</th></tr>{media_rows}</table>

      <h2>6. Portal registration</h2>
      <div class="grid">
        <div>
          <p>Scan to open your PHINS portal / track your application:</p>
          <p><a href="{html.escape(track_url if invite_or_login_code else portal_url)}">
            {html.escape(track_url if invite_or_login_code else portal_url)}</a></p>
          {"<p>Invitation / claim code: <strong>"+html.escape(str(invite_or_login_code))+"</strong></p>" if invite_or_login_code else ""}
        </div>
        <div class="qr"><img src="{qr_url}" alt="PHINS portal QR" width="140" height="140"/></div>
      </div>
    </div>
    <div class="foot">PHINS · Actuarial pricing center + underwriting fine-tune · Seal {html.escape(seal)} · {html.escape(body['issued_at'])}</div>
  </div>
</body></html>"""

    return {
        "contract_id": f"CONTRACT-{policy.get('id')}",
        "integrity_hash": seal,
        "html": html_doc,
        "payload": body,
        "filename": f"PHINS_Policy_{policy.get('id')}.html",
        "portal_url": portal_url,
        "track_url": track_url,
        "qr_url": qr_url,
    }


def email_policy_contract(
    *,
    to_email: str,
    customer_name: str,
    contract: Dict[str, Any],
    policy: Dict[str, Any],
) -> Dict[str, Any]:
    """Send the branded policy contract HTML via the platform notification service."""
    if not to_email:
        return {"ok": False, "error": "No customer email"}
    try:
        from services.notification_service import (
            NotificationChannel,
            NotificationPriority,
            NotificationRequest,
            get_notification_service,
        )
        svc = get_notification_service()
        subject = f"Your PHINS Policy Contract — {policy.get('id')}"
        text = (
            f"Dear {customer_name or 'Customer'},\n\n"
            f"Your PHINS policy {policy.get('id')} has been approved.\n"
            f"Coverage: ${float(policy.get('coverage_amount') or 0):,.0f}\n"
            f"Monthly premium: ${float(policy.get('monthly_premium') or 0):,.2f}\n"
            f"Integrity seal: {contract.get('integrity_hash')}\n"
            f"Portal: {contract.get('portal_url')}\n\n"
            "Your full policy contract is included below.\n\n"
            "— The PHINS Underwriting Team\n"
        )
        result = svc.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient=to_email,
            subject=subject,
            content=text,
            html_content=contract.get("html"),
            customer_id=str(policy.get("customer_id") or ""),
            priority=NotificationPriority.HIGH,
            metadata={
                "type": "policy_contract",
                "policy_id": policy.get("id"),
                "integrity_hash": contract.get("integrity_hash"),
            },
        ))
        ok = bool(getattr(result, "success", False))
        return {
            "ok": ok,
            "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
            "integrity_hash": contract.get("integrity_hash"),
        }
    except Exception as exc:
        logger.warning("Policy contract email failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def mint_portal_invite_code(customer_id: str) -> str:
    """Short single-use style portal invite code for the contract QR."""
    return f"PHINS-PORTAL-{str(customer_id or 'CUST')[-6:].upper()}-{secrets.token_hex(3).upper()}"


__all__ = [
    "detect_statement_contradictions",
    "detect_claim_statement_contradictions",
    "find_prior_customer_records",
    "build_disclosure_prompt",
    "apply_premium_adjustment",
    "archive_rejected_application",
    "collect_application_media",
    "build_policy_contract",
    "email_policy_contract",
    "mint_portal_invite_code",
]
