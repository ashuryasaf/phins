"""
Shared AI reasoning and assessment utilities for insurance data workflows.

This service keeps analysis deterministic and dependency-light while still
providing a richer, context-aware assessment layer across:
- policy applications
- uploaded documents and AI reports
- claims submissions
- BI / portfolio analytics
"""

from __future__ import annotations

import base64
import json
import re
import threading
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


class AdvancedAIAssessmentService:
    """Context-aware analysis for uploaded and affiliated insurance data."""

    MEDICAL_HIGH_RISK_TERMS = (
        "terminal", "fatal", "deceased", "death", "died", "stage 4", "stage iv",
        "cancer", "tumor", "organ failure", "cardiac arrest", "heart failure",
        "stroke", "hospice", "palliative", "mortality",
    )
    MEDICAL_MODERATE_RISK_TERMS = (
        "diabetes", "hypertension", "chronic", "smoker", "obesity", "bmi",
        "disability", "disabled", "paralysis", "amputation",
    )
    CLAIM_URGENCY_TERMS = (
        "hospital", "emergency", "icu", "surgery", "injury", "accident",
        "critical", "fracture", "death", "disability",
    )
    FRAUD_SIGNAL_TERMS = (
        "urgent cash", "expedite payment", "backdated", "altered", "amended",
        "manual override", "duplicate", "mismatch",
    )

    def _normalize_text(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def _decode_base64_text(self, raw_data: Any) -> str:
        if not raw_data:
            return ""
        try:
            return base64.b64decode(raw_data).decode("utf-8", errors="ignore").lower()
        except Exception:
            return ""

    def _infer_document_type(self, document: Dict[str, Any]) -> str:
        explicit = self._normalize_text(document.get("document_type"))
        if explicit and explicit != "general":
            return explicit

        joined = " ".join([
            self._normalize_text(document.get("name")),
            self._normalize_text(document.get("description")),
            self._normalize_text(document.get("note")),
            self._normalize_text(document.get("type")),
        ])

        if any(term in joined for term in ("medical", "hospital", "lab", "diagnosis")):
            return "medical"
        if any(term in joined for term in ("invoice", "receipt", "billing", "statement")):
            return "receipt"
        if any(term in joined for term in ("certificate", "authority", "registrar", "death cert")):
            return "authority"
        if any(term in joined for term in ("passport", "identity", "driver", "id card")):
            return "id"
        return "general"

    def _collect_document_text(self, document: Dict[str, Any]) -> str:
        text_parts = [
            self._normalize_text(document.get("name")),
            self._normalize_text(document.get("description")),
            self._normalize_text(document.get("note")),
            self._normalize_text(document.get("entity_type")),
            self._normalize_text(document.get("entity_id")),
            self._decode_base64_text(document.get("data")),
        ]
        return " ".join(part for part in text_parts if part)

    def _derive_risk_level(self, score: float) -> str:
        if score >= 0.85:
            return "very_high"
        if score >= 0.65:
            return "high"
        if score >= 0.40:
            return "medium"
        return "low"

    def _build_reasoning_summary(self, findings: List[str]) -> str:
        if not findings:
            return "Assessment completed with limited supporting evidence."
        return " ".join(findings[:3])

    def _build_optimization_opportunities(
        self,
        *,
        process: str,
        flags: List[str],
        affiliated_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        affiliated_context = affiliated_context or {}
        opportunities: List[Dict[str, Any]] = []

        if "LIMITED_SUPPORTING_EVIDENCE" in flags:
            opportunities.append({
                "area": process,
                "priority": "high",
                "recommendation": "Request additional supporting documents before final decisioning.",
                "expected_benefit": "Improves evidence quality and reduces manual rework.",
            })
        if "HIGH_CLAIM_TO_COVERAGE_RATIO" in flags:
            opportunities.append({
                "area": "claims",
                "priority": "high",
                "recommendation": "Route high-severity claims to senior review and fraud checks automatically.",
                "expected_benefit": "Reduces leakage on high-value claims.",
            })
        if "CUSTOMER_DATA_INCOMPLETE" in flags:
            opportunities.append({
                "area": "intake",
                "priority": "medium",
                "recommendation": "Enforce missing customer profile fields at submission time.",
                "expected_benefit": "Improves downstream BI and claims traceability.",
            })
        if "AUTHENTICITY_REQUIRES_INQUIRY" in flags or "AUTHENTICITY_UNVERIFIABLE" in flags:
            opportunities.append({
                "area": process,
                "priority": "high",
                "recommendation": "Trigger issuer validation or registry verification workflow for authority documents.",
                "expected_benefit": "Shortens manual authenticity investigations.",
            })
        if affiliated_context.get("related_documents") and len(affiliated_context.get("related_documents", [])) > 3:
            opportunities.append({
                "area": "document_intelligence",
                "priority": "medium",
                "recommendation": "Cluster related uploads into a single case bundle for underwriter and adjuster review.",
                "expected_benefit": "Improves case navigation and speeds review cycles.",
            })

        return opportunities

    def _build_process_impacts(
        self,
        *,
        process: str,
        recommendation: str,
        risk_level: str,
        flags: List[str],
    ) -> Dict[str, Any]:
        impact_priority = {
            "very_high": "critical",
            "high": "high",
            "medium": "medium",
            "low": "normal",
        }.get(risk_level, "normal")

        impacts: Dict[str, Any] = {
            "primary_process": process,
            "priority": impact_priority,
            "next_step": recommendation,
        }

        if process == "claims":
            impacts["claims"] = {
                "priority": impact_priority,
                "recommended_queue": "senior_adjuster" if risk_level in ("high", "very_high") else "standard_adjuster",
                "fraud_review": any(flag in flags for flag in ("HIGH_CLAIM_TO_COVERAGE_RATIO", "FRAUD_SIGNAL_DETECTED")),
            }
        elif process == "underwriting":
            impacts["underwriting"] = {
                "priority": impact_priority,
                "medical_review_required": any(flag in flags for flag in (
                    "TERMINAL_CONDITION_DETECTED",
                    "SERIOUS_ILLNESS_DETECTED",
                    "DISABILITY_CONDITION_DETECTED",
                )),
                "pricing_review_required": any(flag in flags for flag in (
                    "CHRONIC_CONDITION_DETECTED",
                    "HIGH_COVERAGE_APPLICATION",
                )),
            }
        elif process == "dataset":
            impacts["analytics"] = {
                "priority": impact_priority,
                "dashboard_refresh": True,
                "data_quality_review": any(flag in flags for flag in (
                    "DATASET_HIGH_MISSING_RATE",
                    "DATASET_SPARSE",
                )),
            }
        else:
            impacts["documents"] = {
                "priority": impact_priority,
                "manual_verification": recommendation == "hold_pending_verification",
            }

        return impacts

    def _build_document_bi_insights(
        self,
        *,
        document_type: str,
        entity_type: str,
        risk_level: str,
        risk_score: float,
        flags: List[str],
        affiliated_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        affiliated_context = affiliated_context or {}
        insights: Dict[str, Any] = {
            "portfolio_signal": {
                "risk_level": risk_level,
                "risk_score": round(risk_score, 3),
                "entity_type": entity_type or "general",
                "document_type": document_type or "general",
            }
        }

        claim = affiliated_context.get("claim") or {}
        policy = affiliated_context.get("policy") or {}
        application = affiliated_context.get("application") or {}

        if document_type == "authority" or entity_type == "claim":
            claim_type = "General Claim"
            if "DEATH_CERTIFICATE" in flags:
                claim_type = "Life / Death Benefit"
            elif "DISABILITY_CERTIFICATE" in flags:
                claim_type = "Disability Benefit"
            insights["claims_impact"] = {
                "claim_type": claim_type,
                "priority": "HIGH" if risk_level in ("high", "very_high") else "MEDIUM",
                "status": "verification_required" if "AUTHENTICITY_REQUIRES_INQUIRY" in flags or "AUTHENTICITY_UNVERIFIABLE" in flags else "ready_for_review",
                "claimed_amount": round(_safe_float(claim.get("claimed_amount")), 2),
                "policy_coverage": round(_safe_float(policy.get("coverage_amount")), 2),
            }

        if document_type == "receipt" or entity_type in ("billing", "policy"):
            insights["billing_impact"] = {
                "status": "Anomaly detected" if "BILLING_ANOMALY_OVERDUE" in flags else "Normal",
                "collection_risk": "elevated" if "BILLING_ANOMALY_OVERDUE" in flags else "stable",
                "large_transaction_flag": "LARGE_TRANSACTION_DETECTED" in flags,
            }

        if document_type == "medical" or entity_type == "underwriting":
            insights["underwriting_impact"] = {
                "policy_type": application.get("policy_type") or policy.get("type") or "unknown",
                "coverage_amount": round(_safe_float(application.get("coverage_amount") or policy.get("coverage_amount")), 2),
                "medical_exam_required": any(flag in flags for flag in (
                    "SERIOUS_ILLNESS_DETECTED",
                    "TERMINAL_CONDITION_DETECTED",
                    "DISABILITY_CONDITION_DETECTED",
                )),
            }

        return insights

    def _finalize_assessment(
        self,
        *,
        process: str,
        entity_type: str,
        risk_score: float,
        flags: List[str],
        findings: List[str],
        recommendation: str,
        bi_insights: Dict[str, Any],
        affiliated_context: Optional[Dict[str, Any]] = None,
        confidence: float = 0.85,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        risk_score = round(_clamp(risk_score), 3)
        risk_level = self._derive_risk_level(risk_score)
        affiliated_context = affiliated_context or {}

        return {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "flags": list(dict.fromkeys(flags)),
            "findings": findings or ["Assessment completed with no elevated indicators."],
            "recommendation": recommendation,
            "bi_insights": bi_insights,
            "confidence": round(_clamp(confidence), 3),
            "analyzed_at": datetime.now().isoformat(),
            "analysis_version": "2.0",
            "analysis_mode": "contextual_reasoning_engine",
            "reasoning_summary": self._build_reasoning_summary(findings),
            "optimization_opportunities": self._build_optimization_opportunities(
                process=process,
                flags=flags,
                affiliated_context=affiliated_context,
            ),
            "process_impacts": self._build_process_impacts(
                process=process,
                recommendation=recommendation,
                risk_level=risk_level,
                flags=flags,
            ),
            "assessment_scope": {
                "process": process,
                "entity_type": entity_type or "general",
                "affiliated_entities": sorted([
                    key for key, value in affiliated_context.items()
                    if key != "related_documents" and value
                ]),
                "related_document_count": len(affiliated_context.get("related_documents") or []),
            },
            **(extra or {}),
        }

    def assess_document(
        self,
        document: Dict[str, Any],
        affiliated_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Assess one uploaded document with affiliated workflow context."""
        affiliated_context = affiliated_context or {}
        document_type = self._infer_document_type(document)
        entity_type = self._normalize_text(document.get("entity_type")) or "general"
        full_text = self._collect_document_text(document)

        flags: List[str] = []
        findings: List[str] = []
        risk_score = 0.10

        if document_type == "medical" or entity_type == "underwriting":
            if any(term in full_text for term in self.MEDICAL_HIGH_RISK_TERMS):
                flags.append("TERMINAL_CONDITION_DETECTED")
                findings.append("Severe medical indicators were detected in the uploaded evidence.")
                risk_score = max(risk_score, 0.92)
            if any(term in full_text for term in ("cancer", "heart failure", "cardiac arrest", "stroke", "hiv", "aids")):
                flags.append("SERIOUS_ILLNESS_DETECTED")
                findings.append("Serious illness markers suggest elevated underwriting risk and pricing review.")
                risk_score = max(risk_score, 0.80)
            if any(term in full_text for term in ("disability", "disabled", "paralysis", "amputation", "loss of limb", "loss of sight")):
                flags.append("DISABILITY_CONDITION_DETECTED")
                findings.append("Disability-related indicators require coverage and eligibility review.")
                risk_score = max(risk_score, 0.75)
            if any(term in full_text for term in self.MEDICAL_MODERATE_RISK_TERMS):
                flags.append("CHRONIC_CONDITION_DETECTED")
                findings.append("Chronic-condition indicators suggest a conditional approval or premium loading review.")
                risk_score = max(risk_score, 0.55)
            if "high risk" in full_text or "very high risk" in full_text:
                flags.append("EXPLICIT_HIGH_RISK_FLAG")
                findings.append("The uploaded evidence explicitly references a high-risk classification.")
                risk_score = max(risk_score, 0.85)

        if document_type == "authority":
            if any(term in full_text for term in ("certificate of death", "death certificate", "cause of death", "died on")):
                flags.append("DEATH_CERTIFICATE")
                findings.append("Death-certificate evidence was identified and mapped to a life-claim workflow.")
                risk_score = max(risk_score, 0.90)
                auth_markers = ("ministry", "registrar", "authorized", "certificate no", "official", "issued by")
                auth_count = sum(1 for marker in auth_markers if marker in full_text)
                if auth_count >= 3:
                    flags.append("AUTHENTICITY_VERIFIED")
                    findings.append("Authority-document authenticity markers are strong enough for normal claim handling.")
                elif auth_count >= 1:
                    flags.append("AUTHENTICITY_REQUIRES_INQUIRY")
                    findings.append("Partial authenticity markers were found, so verification should precede payment.")
                else:
                    flags.append("AUTHENTICITY_UNVERIFIABLE")
                    findings.append("No strong authenticity markers were found in the authority document.")
            elif any(term in full_text for term in ("disability certificate", "certificate of disability", "disability grade", "national insurance")):
                flags.append("DISABILITY_CERTIFICATE")
                findings.append("Disability-certificate evidence was identified and mapped to a disability-claim workflow.")
                risk_score = max(risk_score, 0.80)
                auth_markers = ("national insurance", "authorized", "certificate no", "medical examiner", "valid until", "issued by")
                auth_count = sum(1 for marker in auth_markers if marker in full_text)
                if auth_count >= 3:
                    flags.append("AUTHENTICITY_VERIFIED")
                    findings.append("The disability certificate includes several authenticity markers.")
                else:
                    flags.append("AUTHENTICITY_REQUIRES_INQUIRY")
                    findings.append("The disability certificate needs manual authenticity follow-up.")
            else:
                flags.append("MANUAL_REVIEW_REQUIRED")
                findings.append("The authority document could not be definitively classified.")
                risk_score = max(risk_score, 0.50)

        if document_type == "receipt" or entity_type in ("billing", "policy"):
            if any(term in full_text for term in ("overdue", "outstanding", "late fee", "delinquent", "past due")):
                flags.append("BILLING_ANOMALY_OVERDUE")
                findings.append("Billing anomalies indicate collection or payment follow-up risk.")
                risk_score = max(risk_score, 0.40)

            amounts = re.findall(r"\$[\d,]+(?:\.\d{2})?", full_text)
            if amounts:
                max_amount = max(_safe_float(amount.replace("$", "").replace(",", "")) for amount in amounts)
                if max_amount > 50000:
                    flags.append("LARGE_TRANSACTION_DETECTED")
                    findings.append("A large transaction amount was detected and should be reviewed for materiality.")
                    risk_score = max(risk_score, 0.60)

        if document_type == "id":
            flags.append("IDENTITY_DOCUMENT")
            findings.append("Identity evidence is present and can be used for KYC and ownership validation.")
            risk_score = max(risk_score, 0.15)

        claim = affiliated_context.get("claim") or {}
        policy = affiliated_context.get("policy") or {}
        application = affiliated_context.get("application") or {}
        customer = affiliated_context.get("customer") or {}
        related_documents = affiliated_context.get("related_documents") or []

        if claim:
            claimed_amount = _safe_float(claim.get("claimed_amount"))
            coverage_amount = _safe_float(policy.get("coverage_amount"))
            if coverage_amount > 0:
                utilization = claimed_amount / coverage_amount
                if utilization >= 0.80:
                    flags.append("HIGH_CLAIM_TO_COVERAGE_RATIO")
                    findings.append("The claim amount consumes a high proportion of the related policy coverage.")
                    risk_score = max(risk_score, 0.72)
            if any(term in self._normalize_text(claim.get("description")) for term in self.CLAIM_URGENCY_TERMS):
                flags.append("CLAIM_SEVERITY_SIGNAL")
                findings.append("Claim description indicates elevated severity and faster triage needs.")
                risk_score = max(risk_score, 0.58)

        if application:
            questionnaire_blob = self._normalize_text(json.dumps(application.get("questionnaire_responses", {}), default=str))
            coverage_amount = _safe_float(application.get("coverage_amount") or policy.get("coverage_amount"))
            if coverage_amount >= 500000:
                flags.append("HIGH_COVERAGE_APPLICATION")
                findings.append("The related application requests high coverage and may justify senior underwriting review.")
                risk_score = max(risk_score, 0.48)
            if any(term in questionnaire_blob for term in ("smoker", "cancer", "diabetes", "hypertension", "heart", "chronic")):
                flags.append("QUESTIONNAIRE_MEDICAL_DISCLOSURE")
                findings.append("The questionnaire includes medical disclosures that materially affect underwriting.")
                risk_score = max(risk_score, 0.62)

        if customer and (not customer.get("email") or not customer.get("phone")):
            flags.append("CUSTOMER_DATA_INCOMPLETE")
            findings.append("Affiliated customer profile data is incomplete and could reduce automation confidence.")
            risk_score = max(risk_score, 0.35)

        if entity_type in ("claim", "underwriting") and not related_documents:
            flags.append("LIMITED_SUPPORTING_EVIDENCE")
            findings.append("No additional supporting uploads were found for the related case.")
            risk_score = max(risk_score, 0.42)

        if any(term in full_text for term in self.FRAUD_SIGNAL_TERMS):
            flags.append("FRAUD_SIGNAL_DETECTED")
            findings.append("Textual signals suggest the document should be cross-checked for manipulation or urgency bias.")
            risk_score = max(risk_score, 0.70)

        if not findings:
            findings.append("No elevated risk indicators were detected in the uploaded document.")

        if "AUTHENTICITY_REQUIRES_INQUIRY" in flags or "AUTHENTICITY_UNVERIFIABLE" in flags:
            recommendation = "hold_pending_verification"
        elif "DEATH_CERTIFICATE" in flags:
            recommendation = "process_death_claim"
        elif "DISABILITY_CERTIFICATE" in flags:
            recommendation = "process_disability_claim"
        else:
            recommendation = {
                "very_high": "decline_or_senior_review",
                "high": "refer_manual_review",
                "medium": "approve_conditional",
                "low": "approve",
            }[self._derive_risk_level(risk_score)]

        bi_insights = self._build_document_bi_insights(
            document_type=document_type,
            entity_type=entity_type,
            risk_level=self._derive_risk_level(risk_score),
            risk_score=risk_score,
            flags=flags,
            affiliated_context=affiliated_context,
        )

        return self._finalize_assessment(
            process="claims" if entity_type == "claim" else "underwriting" if entity_type == "underwriting" else "document",
            entity_type=entity_type,
            risk_score=risk_score + min(0.09, max(0, len(set(flags)) - 2) * 0.02),
            flags=flags,
            findings=findings,
            recommendation=recommendation,
            bi_insights=bi_insights,
            affiliated_context=affiliated_context,
            confidence=0.88 if full_text else 0.72,
            extra={
                "document_type": document_type,
            },
        )

    def assess_policy_application(
        self,
        application: Dict[str, Any],
        *,
        policy: Optional[Dict[str, Any]] = None,
        customer: Optional[Dict[str, Any]] = None,
        documents: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Assess policy intake using application data and uploaded evidence."""
        policy = policy or {}
        customer = customer or {}
        documents = documents or []
        flags: List[str] = []
        findings: List[str] = []
        risk_score = 0.18

        age = _safe_int(application.get("age"))
        coverage_amount = _safe_float(application.get("coverage_amount") or policy.get("coverage_amount"))
        questionnaire_blob = self._normalize_text(json.dumps(application.get("questionnaire_responses", {}), default=str))
        policy_type = self._normalize_text(application.get("policy_type") or policy.get("type") or "unknown")

        if age >= 60:
            flags.append("AGE_ELEVATED_RISK")
            findings.append("Applicant age exceeds the standard automated-review comfort band.")
            risk_score = max(risk_score, 0.45)
        if coverage_amount >= 500000:
            flags.append("HIGH_COVERAGE_APPLICATION")
            findings.append("Requested coverage is large enough to require stronger evidence and pricing controls.")
            risk_score = max(risk_score, 0.52)
        if any(term in questionnaire_blob for term in ("smoker", "diabetes", "hypertension", "cancer", "heart", "chronic")):
            flags.append("QUESTIONNAIRE_MEDICAL_DISCLOSURE")
            findings.append("Disclosed medical conditions indicate that underwriting review should not rely only on the base premium model.")
            risk_score = max(risk_score, 0.65)
        if application.get("medical_exam_required"):
            flags.append("MEDICAL_EXAM_REQUIRED")
            findings.append("The application already indicates that additional medical evidence is required.")
            risk_score = max(risk_score, 0.55)
        if customer and (not customer.get("email") or not customer.get("phone")):
            flags.append("CUSTOMER_DATA_INCOMPLETE")
            findings.append("Customer profile data is incomplete, reducing straight-through processing quality.")
            risk_score = max(risk_score, 0.35)
        if not documents:
            flags.append("LIMITED_SUPPORTING_EVIDENCE")
            findings.append("No supporting uploads were attached to the application.")
            risk_score = max(risk_score, 0.40)

        document_assessments = []
        for doc in documents[:10]:
            document_assessments.append(self.assess_document(doc, {
                "application": application,
                "policy": policy,
                "customer": customer,
                "related_documents": [],
            }))

        if document_assessments:
            highest_document_risk = max(item.get("risk_score", 0.0) for item in document_assessments)
            risk_score = max(risk_score, highest_document_risk)
            for item in document_assessments:
                flags.extend(item.get("flags", []))
            high_risk_docs = sum(1 for item in document_assessments if item.get("risk_level") in ("high", "very_high"))
            if high_risk_docs:
                findings.append(f"{high_risk_docs} supporting document(s) produced elevated underwriting risk indicators.")

        if not findings:
            findings.append("The application data supports standard underwriting review with no major anomalies.")

        recommendation = {
            "very_high": "decline_or_senior_review",
            "high": "refer_manual_review",
            "medium": "approve_conditional",
            "low": "approve",
        }[self._derive_risk_level(risk_score)]

        bi_insights = {
            "underwriting_impact": {
                "policy_type": policy_type,
                "coverage_amount": round(coverage_amount, 2),
                "document_count": len(documents),
                "high_risk_document_count": sum(
                    1 for item in document_assessments if item.get("risk_level") in ("high", "very_high")
                ),
            },
            "pricing_signal": {
                "recommended_review_band": self._derive_risk_level(risk_score),
                "medical_disclosures_present": "QUESTIONNAIRE_MEDICAL_DISCLOSURE" in flags,
            },
        }

        return self._finalize_assessment(
            process="underwriting",
            entity_type="underwriting",
            risk_score=risk_score + min(0.08, max(0, len(set(flags)) - 2) * 0.015),
            flags=flags,
            findings=findings,
            recommendation=recommendation,
            bi_insights=bi_insights,
            affiliated_context={
                "application": application,
                "policy": policy,
                "customer": customer,
                "related_documents": documents,
            },
            confidence=0.86,
            extra={
                "document_assessments": document_assessments[:5],
            },
        )

    def assess_claim(
        self,
        claim: Dict[str, Any],
        *,
        policy: Optional[Dict[str, Any]] = None,
        customer: Optional[Dict[str, Any]] = None,
        documents: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Assess a claim submission using claim details and uploaded evidence."""
        policy = policy or {}
        customer = customer or {}
        documents = documents or []
        flags: List[str] = []
        findings: List[str] = []
        risk_score = 0.24

        claimed_amount = _safe_float(claim.get("claimed_amount"))
        coverage_amount = _safe_float(policy.get("coverage_amount"))
        description = self._normalize_text(claim.get("description"))
        claim_type = self._normalize_text(claim.get("type") or "general")

        if coverage_amount > 0:
            utilization = claimed_amount / coverage_amount
            if utilization >= 0.80:
                flags.append("HIGH_CLAIM_TO_COVERAGE_RATIO")
                findings.append("Claim utilization is close to total policy coverage and needs heightened review.")
                risk_score = max(risk_score, 0.76)
            elif utilization >= 0.40:
                flags.append("MODERATE_CLAIM_TO_COVERAGE_RATIO")
                findings.append("Claim utilization is material relative to policy coverage.")
                risk_score = max(risk_score, 0.48)
        if any(term in description for term in self.CLAIM_URGENCY_TERMS):
            flags.append("CLAIM_SEVERITY_SIGNAL")
            findings.append("Claim description indicates urgent medical or life-event handling.")
            risk_score = max(risk_score, 0.56)
        if any(term in description for term in self.FRAUD_SIGNAL_TERMS):
            flags.append("FRAUD_SIGNAL_DETECTED")
            findings.append("Claim narrative contains urgency or alteration signals that warrant scrutiny.")
            risk_score = max(risk_score, 0.72)
        if not documents:
            flags.append("LIMITED_SUPPORTING_EVIDENCE")
            findings.append("No supporting evidence files were attached to the claim.")
            risk_score = max(risk_score, 0.45)
        if customer and (not customer.get("email") or not customer.get("phone")):
            flags.append("CUSTOMER_DATA_INCOMPLETE")
            findings.append("Customer contact data is incomplete for follow-up during claim handling.")
            risk_score = max(risk_score, 0.35)

        document_assessments = []
        for doc in documents[:10]:
            document_assessments.append(self.assess_document(doc, {
                "claim": claim,
                "policy": policy,
                "customer": customer,
                "related_documents": [],
            }))

        if document_assessments:
            risk_score = max(risk_score, max(item.get("risk_score", 0.0) for item in document_assessments))
            for item in document_assessments:
                flags.extend(item.get("flags", []))
            findings.append(
                f"{sum(1 for item in document_assessments if item.get('risk_level') in ('high', 'very_high'))} attached file(s) triggered elevated review logic."
            )

        if claim_type in ("death_benefit", "death", "life"):
            findings.append("Claim type suggests a life-event workflow with authority-document dependencies.")
            risk_score = max(risk_score, 0.58)

        if not findings:
            findings.append("Claim intake data supports standard adjudication with normal review depth.")

        recommendation = "standard_review"
        risk_level = self._derive_risk_level(risk_score)
        if "AUTHENTICITY_REQUIRES_INQUIRY" in flags or "AUTHENTICITY_UNVERIFIABLE" in flags:
            recommendation = "hold_pending_verification"
        elif risk_level in ("high", "very_high"):
            recommendation = "manual_investigation"
        elif risk_level == "medium":
            recommendation = "enhanced_review"

        bi_insights = {
            "claims_impact": {
                "claim_type": claim_type or "general",
                "claimed_amount": round(claimed_amount, 2),
                "coverage_amount": round(coverage_amount, 2),
                "document_count": len(documents),
                "review_band": risk_level,
            },
            "fraud_signal": {
                "requires_fraud_review": any(flag in flags for flag in (
                    "HIGH_CLAIM_TO_COVERAGE_RATIO",
                    "FRAUD_SIGNAL_DETECTED",
                )),
            },
        }

        return self._finalize_assessment(
            process="claims",
            entity_type="claim",
            risk_score=risk_score + min(0.08, max(0, len(set(flags)) - 2) * 0.015),
            flags=flags,
            findings=findings,
            recommendation=recommendation,
            bi_insights=bi_insights,
            affiliated_context={
                "claim": claim,
                "policy": policy,
                "customer": customer,
                "related_documents": documents,
            },
            confidence=0.84,
            extra={
                "document_assessments": document_assessments[:5],
            },
        )

    def assess_uploaded_dataset(
        self,
        *,
        document_name: str,
        parsed_data: Dict[str, Any],
        affiliated_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Assess uploaded tabular/report data and produce BI-oriented guidance."""
        affiliated_context = affiliated_context or {}
        columns = parsed_data.get("columns") or []
        rows = parsed_data.get("rows") or []
        flags: List[str] = []
        findings: List[str] = []
        risk_score = 0.16

        row_count = len(rows)
        column_count = len(columns)
        if row_count >= 1000:
            flags.append("DATASET_LARGE_UPLOAD")
            findings.append("The uploaded dataset is large enough to benefit from batch-oriented monitoring and caching.")
        if row_count <= 3 or column_count <= 2:
            flags.append("DATASET_SPARSE")
            findings.append("The uploaded dataset is sparse and may not support stable trend analysis.")
            risk_score = max(risk_score, 0.38)

        numeric_columns: Dict[str, List[float]] = {}
        missing_cells = 0
        total_cells = max(row_count * max(column_count, 1), 1)
        for row in rows[:500]:
            if not isinstance(row, dict):
                continue
            for column in columns:
                value = row.get(column)
                if value in (None, "", "null", "None"):
                    missing_cells += 1
                    continue
                try:
                    numeric_columns.setdefault(str(column), []).append(float(value))
                except (TypeError, ValueError):
                    continue

        missing_rate = missing_cells / total_cells
        if missing_rate >= 0.20:
            flags.append("DATASET_HIGH_MISSING_RATE")
            findings.append("The dataset has a high missing-value rate that can distort BI outputs.")
            risk_score = max(risk_score, 0.52)

        lower_columns = [self._normalize_text(col) for col in columns]
        risk_column = next((col for col in columns if "risk" in self._normalize_text(col) and col in numeric_columns), None)
        claim_column = next((col for col in columns if "claim" in self._normalize_text(col) and col in numeric_columns), None)
        coverage_column = next((col for col in columns if "coverage" in self._normalize_text(col) and col in numeric_columns), None)
        premium_column = next((col for col in columns if "premium" in self._normalize_text(col) and col in numeric_columns), None)

        if risk_column:
            avg_risk = sum(numeric_columns[risk_column]) / max(len(numeric_columns[risk_column]), 1)
            if avg_risk >= 70:
                flags.append("DATASET_HIGH_AVERAGE_RISK")
                findings.append("Uploaded risk metrics trend high and justify tighter operational monitoring.")
                risk_score = max(risk_score, 0.58)
        if claim_column and coverage_column:
            avg_claim = sum(numeric_columns[claim_column]) / max(len(numeric_columns[claim_column]), 1)
            avg_coverage = sum(numeric_columns[coverage_column]) / max(len(numeric_columns[coverage_column]), 1)
            if avg_coverage > 0 and (avg_claim / avg_coverage) >= 0.30:
                flags.append("DATASET_CLAIM_PRESSURE")
                findings.append("Claim amounts are large relative to coverage, which may pressure reserves and pricing.")
                risk_score = max(risk_score, 0.62)
        if premium_column and coverage_column:
            avg_premium = sum(numeric_columns[premium_column]) / max(len(numeric_columns[premium_column]), 1)
            avg_coverage = sum(numeric_columns[coverage_column]) / max(len(numeric_columns[coverage_column]), 1)
            if avg_coverage > 0 and avg_premium > 0 and (avg_premium / avg_coverage) < 0.002:
                flags.append("DATASET_PREMIUM_TO_COVERAGE_GAP")
                findings.append("Premium-to-coverage ratios look thin and may indicate pricing optimization opportunities.")
                risk_score = max(risk_score, 0.50)

        if affiliated_context.get("affiliation_snapshot"):
            flags.append("AFFILIATED_CONTEXT_AVAILABLE")
            findings.append("Affiliated portfolio context is available and can enrich downstream recommendations.")

        if not findings:
            findings.append("The uploaded dataset appears structurally usable for BI and operational reporting.")

        recommendation = "optimize_dashboard_rules"
        risk_level = self._derive_risk_level(risk_score)
        if risk_level in ("high", "very_high"):
            recommendation = "prioritize_data_quality_and_case_review"
        elif risk_level == "medium":
            recommendation = "monitor_with_targeted_alerting"

        bi_insights = {
            "dataset_quality": {
                "document_name": document_name,
                "row_count": row_count,
                "column_count": column_count,
                "missing_rate": round(missing_rate, 3),
                "numeric_columns_detected": sorted(numeric_columns.keys())[:20],
            },
            "portfolio_indicators": {
                "contains_risk_metrics": bool(risk_column),
                "contains_claim_metrics": bool(claim_column),
                "contains_coverage_metrics": bool(coverage_column),
                "contains_premium_metrics": bool(premium_column),
                "column_keywords": Counter(lower_columns).most_common(10),
            },
        }

        return self._finalize_assessment(
            process="dataset",
            entity_type="report_upload",
            risk_score=risk_score,
            flags=flags,
            findings=findings,
            recommendation=recommendation,
            bi_insights=bi_insights,
            affiliated_context=affiliated_context,
            confidence=0.82,
            extra={
                "document_name": document_name,
            },
        )

    def assess_bi_portfolio(
        self,
        *,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        billing: Dict[str, Any],
        underwriting_apps: Dict[str, Any],
        documents: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Produce a portfolio-level operational assessment for BI endpoints."""
        documents = documents or {}
        active_policies = [p for p in policies.values() if str(p.get("status", "")).lower() == "active"]
        pending_claims = [c for c in claims.values() if str(c.get("status", "")).lower() in ("pending", "under_review", "underreview")]
        approved_claims = [c for c in claims.values() if str(c.get("status", "")).lower() in ("approved", "paid")]
        pending_apps = [a for a in underwriting_apps.values() if str(a.get("status", "")).lower() == "pending"]
        outstanding_bills = [b for b in billing.values() if str(b.get("status", "")).lower() in ("outstanding", "overdue", "pending")]

        total_premium = sum(_safe_float(p.get("annual_premium")) for p in active_policies)
        claims_exposure = sum(_safe_float(c.get("approved_amount") or c.get("claimed_amount")) for c in approved_claims)
        pending_exposure = sum(_safe_float(c.get("claimed_amount")) for c in pending_claims)
        outstanding_amount = sum(max(0.0, _safe_float(b.get("amount")) - _safe_float(b.get("amount_paid"))) for b in outstanding_bills)
        loss_ratio = (claims_exposure / total_premium) if total_premium > 0 else 0.0

        risk_score = 0.18
        insights: List[Dict[str, Any]] = []
        recommendations: List[Dict[str, Any]] = []
        optimization_opportunities: List[Dict[str, Any]] = []

        if loss_ratio >= 0.60:
            risk_score = max(risk_score, 0.72)
            insights.append({
                "type": "warning",
                "category": "risk",
                "message": f"Loss ratio is elevated at {loss_ratio * 100:.1f}% and should feed pricing and underwriting reviews.",
            })
            recommendations.append({
                "priority": "high",
                "action": "Tighten underwriting and pricing controls for loss-heavy segments",
                "impact": "Protects margin and reserve adequacy",
            })
        if pending_exposure > max(total_premium * 0.30, 1):
            risk_score = max(risk_score, 0.67)
            insights.append({
                "type": "alert",
                "category": "claims",
                "message": f"Pending claims exposure (${pending_exposure:,.0f}) is materially high versus premium volume.",
            })
        if len(pending_apps) >= 5:
            risk_score = max(risk_score, 0.46)
            insights.append({
                "type": "info",
                "category": "pipeline",
                "message": f"{len(pending_apps)} underwriting applications are waiting for review and could slow issuance.",
            })
            recommendations.append({
                "priority": "medium",
                "action": "Auto-prioritize underwriting cases using AI assessment scores",
                "impact": "Reduces application cycle time",
            })
        if outstanding_amount > max(total_premium * 0.10, 1000):
            risk_score = max(risk_score, 0.50)
            insights.append({
                "type": "warning",
                "category": "billing",
                "message": f"Outstanding receivables total ${outstanding_amount:,.0f}; collections optimization is recommended.",
            })
            recommendations.append({
                "priority": "medium",
                "action": "Increase automated billing reminders and aging-based escalation",
                "impact": "Improves cash collection and BI forecast accuracy",
            })

        high_risk_documents = 0
        analyzed_documents = 0
        for doc in documents.values():
            analysis = doc.get("ai_analysis") or {}
            if analysis:
                analyzed_documents += 1
                if analysis.get("risk_level") in ("high", "very_high"):
                    high_risk_documents += 1

        if analyzed_documents:
            high_doc_ratio = high_risk_documents / max(analyzed_documents, 1)
            if high_doc_ratio >= 0.30:
                risk_score = max(risk_score, 0.54)
                insights.append({
                    "type": "warning",
                    "category": "document_intelligence",
                    "message": f"{high_risk_documents} of {analyzed_documents} analyzed documents are marked high risk.",
                })
            optimization_opportunities.append({
                "area": "document_intelligence",
                "priority": "medium",
                "recommendation": "Expand automatic document analysis coverage to all uploads feeding claims and underwriting.",
                "expected_benefit": "Improves portfolio-level BI visibility across uploaded evidence.",
            })

        process_breakdown = {
            "customers": len(customers),
            "active_policies": len(active_policies),
            "pending_underwriting": len(pending_apps),
            "pending_claims": len(pending_claims),
            "outstanding_bills": len(outstanding_bills),
            "analyzed_documents": analyzed_documents,
        }

        return {
            "portfolio_risk_level": self._derive_risk_level(risk_score),
            "portfolio_risk_score": round(_clamp(risk_score), 3),
            "generated_at": datetime.now().isoformat(),
            "insights": insights,
            "recommendations": recommendations,
            "optimization_opportunities": optimization_opportunities,
            "document_intelligence": {
                "analyzed_documents": analyzed_documents,
                "high_risk_documents": high_risk_documents,
                "coverage_ratio": round((analyzed_documents / max(len(documents), 1)), 3) if documents else 0.0,
            },
            "process_breakdown": process_breakdown,
            "financial_pressure": {
                "loss_ratio": round(loss_ratio, 3),
                "claims_exposure": round(claims_exposure, 2),
                "pending_exposure": round(pending_exposure, 2),
                "outstanding_receivables": round(outstanding_amount, 2),
            },
        }


_assessment_service: Optional[AdvancedAIAssessmentService] = None
_assessment_lock = threading.Lock()


def get_ai_assessment_service() -> AdvancedAIAssessmentService:
    global _assessment_service
    if _assessment_service is None:
        with _assessment_lock:
            if _assessment_service is None:
                _assessment_service = AdvancedAIAssessmentService()
    return _assessment_service
