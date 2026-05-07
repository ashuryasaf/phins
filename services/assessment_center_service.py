"""
PHINS Assessment Center Service
================================

The Assessment Center is the single, unified location where the platform turns
**uploaded documents and ingested external facts** into actionable underwriting,
risk and savings intelligence.

Why this exists
---------------
Across the platform many upload endpoints (policy applications, claims,
underwriting reports, contribution receipts, risk dashboards, Mislaka downloads,
ID/medical scans, etc.) used to perform their own ad-hoc analysis. Some only
held files in temporary storage and never built a shared profile of the
customer, and the Mislaka dashboard ran statistical reviews on top of data that
is already a *factual* clearing-house response.

The Assessment Center fixes this by providing one pipeline that:

1. Ingests any uploaded document (always persistently, via
   :class:`services.document_processing_service.DocumentProcessingService`)
2. Mines documents for **classic insurance, risk and savings indicators**:
   - Government identity numbers (any country supported by the regex pack)
   - Customer photo region (best-effort crop hint from image metadata)
   - Mailing address, phone, e-mail, date of birth
   - Medical conditions, medications, allergies, lab values, BMI/blood pressure
   - Premiums, sums insured, deductibles, policy/claim references
   - Savings balances, contributions, deposits, IBANs / account references
3. Stores every extracted fact with full provenance (document_id, sha256,
   confidence, source) so data integrity is verifiable end-to-end and the
   facts remain *uploadable / re-exportable* later
4. Aggregates per-customer facts into a deterministic **Customer 360 profile**
5. Computes **risk and underwriting indicators** plus chart-ready data series
   on top of the unified fact store - never on the raw external response
6. Accepts **external facts as facts** (e.g. Mislaka policy rows) so the
   Assessment Center, not the Mislaka dashboard, performs every statistical
   review

The service is intentionally dependency-free at runtime (no numpy / pandas /
opencv requirements) so it can run in the same environments as the rest of the
PHINS server. Heavier optional dependencies are imported lazily.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

ASSESSMENT_FACT_STORE = os.environ.get(
    "PHINS_ASSESSMENT_FACT_STORE",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "assessment_center",
    ),
)


# Universe of supported fact categories. Frozen so callers cannot inject
# arbitrary buckets that break Customer 360 aggregation.
FACT_TYPES = (
    "identity",            # ID numbers, full name, DOB
    "contact",             # address, phone, email
    "photo",               # face / portrait region hints
    "medical_condition",   # diagnoses, chronic flags
    "medication",          # active prescriptions
    "allergy",             # known allergies
    "vital_sign",          # BMI, blood pressure, lab values
    "insurance",           # premiums, sums insured, coverage, deductibles
    "savings",             # balances, contributions, deposits
    "policy_reference",    # POL-, claim-, account references
    "risk_indicator",      # explicit risk markers found in text
    "external_policy",     # Mislaka and similar clearinghouse rows
    "external_account",    # external savings/pension accounts
    "external_contribution",  # contribution rows from external providers
)

# Maximum text length we are willing to scan in a single document
MAX_TEXT_SCAN = 200_000


# ── Identity number patterns ──────────────────────────────────────────────────
#
# Each entry is (label, country, compiled regex, validator). The validator may
# be ``None`` when no checksum is defined; otherwise it must accept the matched
# digit string and return ``True``/``False``.

def _israeli_id_valid(value: str) -> bool:
    """Validate an Israeli ID (Teudat Zehut) using the standard Luhn variant."""
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) != 9:
        return False
    total = 0
    for i, digit in enumerate(digits):
        weighted = digit * (1 if i % 2 == 0 else 2)
        if weighted > 9:
            weighted -= 9
        total += weighted
    return total % 10 == 0


def _us_ssn_valid(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        return False
    if digits[:3] in {"000", "666"} or digits[0] == "9":
        return False
    if digits[3:5] == "00" or digits[5:] == "0000":
        return False
    return True


def _cpf_valid(value: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", value)]
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for n in (9, 10):
        total = sum(d * (n + 1 - i) for i, d in enumerate(digits[:n]))
        check = (total * 10) % 11
        if check == 10:
            check = 0
        if check != digits[n]:
            return False
    return True


def _aadhaar_valid(value: str) -> bool:
    # Verhoeff checksum; full table embedded for self-containment.
    d = (
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
        (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
        (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
        (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
        (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
        (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
        (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
        (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
        (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
    )
    p = (
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
        (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
        (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
        (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
        (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
        (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
        (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
    )
    digits = [int(c) for c in re.sub(r"\D", "", value)]
    if len(digits) != 12 or digits[0] in (0, 1):
        return False
    c = 0
    for i, n in enumerate(reversed(digits)):
        c = d[c][p[i % 8][n]]
    return c == 0


def _spain_dni_valid(value: str) -> bool:
    """Validate Spanish DNI/NIE (8 digits + control letter)."""
    cleaned = value.upper().replace("-", "").replace(" ", "")
    table = "TRWAGMYFPDXBNJZSQVHLCKE"
    if re.fullmatch(r"[XYZ]?\d{7,8}[A-Z]", cleaned):
        translation = {"X": "0", "Y": "1", "Z": "2"}
        if cleaned[0] in translation:
            num_part = translation[cleaned[0]] + cleaned[1:-1]
        else:
            num_part = cleaned[:-1]
        try:
            return table[int(num_part) % 23] == cleaned[-1]
        except ValueError:
            return False
    return False


# Order matters: more specific / more validated patterns first so a 9-digit
# number that is a valid Israeli ID is not first claimed by the SSN regex.
_ID_PATTERNS: Tuple[Tuple[str, str, "re.Pattern[str]", Optional[Any]], ...] = (
    ("israeli_id", "IL", re.compile(r"(?<!\d)(\d{9})(?!\d)"), _israeli_id_valid),
    ("us_ssn", "US", re.compile(r"(?<!\d)(\d{3}-\d{2}-\d{4})(?!\d)"), _us_ssn_valid),
    ("uk_nin", "UK", re.compile(r"\b([A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D])\b", re.IGNORECASE), None),
    ("spain_dni", "ES", re.compile(r"\b([XYZ]?\d{7,8}[A-Z])\b"), _spain_dni_valid),
    ("italy_codice_fiscale", "IT",
        re.compile(r"\b([A-Z]{6}\d{2}[A-EHLMPRT][0-9]{2}[A-Z]\d{3}[A-Z])\b"), None),
    ("brazil_cpf", "BR", re.compile(r"(?<!\d)(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)"), _cpf_valid),
    ("germany_steuer_id", "DE", re.compile(r"(?<!\d)(\d{11})(?!\d)"), None),
    ("india_aadhaar", "IN", re.compile(r"(?<!\d)(\d{4}\s?\d{4}\s?\d{4})(?!\d)"), _aadhaar_valid),
    ("france_insee", "FR", re.compile(r"(?<!\d)([12]\d{2}(0[1-9]|1[0-2])\d{2}\d{3}\d{3}\d{2})(?!\d)"), None),
    ("passport_generic", "ANY", re.compile(r"\b([A-Z]{1,2}\d{6,9})\b"), None),
)


# ── Other extraction patterns ─────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)?\d{3,4}[\s\-.]?\d{3,4}",
)
_DOB_RE = re.compile(
    r"(?:DOB|D\.O\.B\.|date of birth|תאריך לידה|birth date|nacimiento)\s*[:\-]?\s*"
    r"(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}|\d{4}[\/\-.]\d{1,2}[\/\-.]\d{1,2})",
    re.IGNORECASE,
)
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b")
_AMOUNT_RE = re.compile(
    r"(?P<currency>USD|EUR|GBP|ILS|NIS|₪|\$|€|£|ש\"ח)?\s*"
    r"(?P<amount>(?:\d{1,3}(?:[,\.]\d{3})+|\d+)(?:[\.,]\d{2})?)\s*"
    r"(?P<currency2>USD|EUR|GBP|ILS|NIS|₪|\$|€|£|ש\"ח)?",
    re.IGNORECASE,
)
_BMI_RE = re.compile(r"\bBMI\s*[:=]?\s*(\d{2}(?:\.\d)?)\b", re.IGNORECASE)
_BP_RE = re.compile(r"\b(?:BP|blood pressure)\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b", re.IGNORECASE)

_ADDRESS_RE = re.compile(
    r"(?:address|כתובת|מען|residence)\s*[:\-]?\s*([^\n\r]{6,160})",
    re.IGNORECASE,
)


_MEDICAL_CONDITIONS = (
    "diabetes", "hypertension", "asthma", "cancer", "tumor", "tumour",
    "stroke", "heart disease", "coronary", "myocardial", "arrhythmia",
    "copd", "epilepsy", "depression", "anxiety", "schizophrenia",
    "hiv", "aids", "hepatitis", "tuberculosis", "renal failure",
    "chronic kidney", "liver disease", "lupus", "arthritis",
    "alzheimer", "parkinson", "obesity", "anemia",
)

_MEDICATIONS = (
    "metformin", "insulin", "atorvastatin", "lisinopril", "amlodipine",
    "warfarin", "aspirin", "clopidogrel", "omeprazole", "levothyroxine",
    "albuterol", "ventolin", "fluoxetine", "sertraline", "citalopram",
    "morphine", "tramadol", "ibuprofen", "paracetamol", "acetaminophen",
    "tamoxifen", "chemotherapy", "radiotherapy",
)

_ALLERGIES = (
    "penicillin", "peanut", "latex", "shellfish", "iodine", "sulfa",
    "aspirin allergy", "egg allergy", "lactose intolerance",
)

_INSURANCE_KEYWORDS = (
    "premium", "policy number", "sum insured", "cover amount",
    "coverage", "deductible", "excess", "beneficiary", "insured",
    "claim", "reinstatement", "endorsement", "renewal",
)

_SAVINGS_KEYWORDS = (
    "balance", "deposit", "contribution", "withdrawal", "vesting",
    "accumulated", "interest", "dividend", "yield", "fund value",
    "pension", "provident", "education fund",
)

_RISK_KEYWORDS = (
    "high risk", "very high risk", "elevated risk", "low risk",
    "stage 4", "stage iv", "terminal", "critical", "fatal",
    "denied", "fraud", "suspicious", "non-disclosure",
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Fact:
    """A single piece of evidence extracted from an uploaded artefact."""

    fact_id: str
    customer_id: str
    fact_type: str
    value: Any
    label: str
    confidence: float = 0.5
    source_document_id: Optional[str] = None
    source_document_sha256: Optional[str] = None
    source: str = "document"
    metadata: Dict[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AssessmentResult:
    """The full assessment of a single document or fact ingestion call."""

    customer_id: str
    document_id: Optional[str]
    captured_at: str
    facts: List[Fact]
    summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "document_id": self.document_id,
            "captured_at": self.captured_at,
            "facts": [f.to_dict() for f in self.facts],
            "summary": self.summary,
        }


# ── Service ───────────────────────────────────────────────────────────────────

class AssessmentCenterService:
    """Unified Assessment Center.

    Wraps :class:`DocumentProcessingService` for persistent storage and adds an
    extraction + Customer 360 + risk pipeline shared by every upload route.
    """

    def __init__(self, document_service=None, fact_store_dir: Optional[str] = None):
        self._lock = threading.RLock()
        self._document_service = document_service
        self._fact_store_dir = fact_store_dir or ASSESSMENT_FACT_STORE
        os.makedirs(self._fact_store_dir, exist_ok=True)
        # In-memory mirror of facts keyed by customer_id.
        self._facts: Dict[str, List[Fact]] = {}
        # External fact bundles keyed by (customer_id, source).
        self._external: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._load_from_disk()

    # ── Document service binding ─────────────────────────────────────────

    @property
    def document_service(self):
        if self._document_service is None:
            from services.document_processing_service import get_document_service
            self._document_service = get_document_service()
        return self._document_service

    def reset(self) -> None:
        """Drop all in-memory state and persisted facts. Mainly used by tests."""
        with self._lock:
            self._facts.clear()
            self._external.clear()
            self._clear_persisted_facts()

    def _clear_persisted_facts(self) -> None:
        """Remove all JSON fact files from the fact store directory."""
        try:
            if not os.path.isdir(self._fact_store_dir):
                return
            for name in os.listdir(self._fact_store_dir):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self._fact_store_dir, name)
                try:
                    os.remove(path)
                except OSError:
                    pass
        except Exception as exc:
            logger.warning("Failed clearing persisted facts: %s", exc)

    # ── Public API ───────────────────────────────────────────────────────

    def assess_document(
        self,
        document_id: str,
        *,
        customer_id: Optional[str] = None,
        source_context: Optional[str] = None,
    ) -> AssessmentResult:
        """Run the full intelligence pipeline on an already-uploaded document."""
        record = self.document_service.get_document(document_id, include_data=True)
        if not record:
            raise ValueError(f"Document {document_id} not found")

        cust = customer_id or record.get("customer_id") or record.get("uploaded_by_customer") or ""
        cust = cust or "anonymous"
        sha = record.get("sha256_checksum") or record.get("sha256")
        mime = record.get("mime_type", "")
        ext = record.get("file_extension", "")
        raw_b64 = record.get("data") or ""
        raw_bytes = base64.b64decode(raw_b64) if raw_b64 else b""

        text = self._extract_searchable_text(record, raw_bytes, mime, ext)
        facts = self._extract_facts_from_text(
            text=text,
            customer_id=cust,
            document_id=document_id,
            sha256=sha,
            source=source_context or "document_upload",
        )
        if mime.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
            facts.extend(self._extract_photo_facts(
                raw_bytes=raw_bytes,
                customer_id=cust,
                document_id=document_id,
                sha256=sha,
            ))

        self._store_facts(cust, facts)
        summary = self._summarise(facts)
        return AssessmentResult(
            customer_id=cust,
            document_id=document_id,
            captured_at=datetime.utcnow().isoformat() + "Z",
            facts=facts,
            summary=summary,
        )

    def upload_and_assess(
        self,
        *,
        file_name: str,
        file_data_b64: str,
        mime_type: Optional[str] = None,
        category: Optional[str] = None,
        customer_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        uploaded_by_role: Optional[str] = None,
        description: Optional[str] = None,
        source_context: Optional[str] = None,
    ) -> AssessmentResult:
        """Persist a fresh upload and immediately run the assessment pipeline."""
        upload = self.document_service.upload_document(
            file_name=file_name,
            file_data_b64=file_data_b64,
            mime_type=mime_type,
            category=category,
            customer_id=customer_id,
            entity_type=entity_type,
            entity_id=entity_id,
            uploaded_by=uploaded_by,
            uploaded_by_role=uploaded_by_role,
            description=description,
            skip_processing=False,
        )
        return self.assess_document(
            upload.document_id,
            customer_id=customer_id,
            source_context=source_context,
        )

    def ingest_external_facts(
        self,
        *,
        customer_id: str,
        source: str,
        records: Iterable[Dict[str, Any]],
        fact_type: str = "external_policy",
    ) -> AssessmentResult:
        """Accept external clearing-house rows (e.g. Mislaka) as raw facts.

        The assessment center never *re-aggregates* the raw response - it simply
        records each row with provenance so that downstream risk and dashboard
        endpoints can query the same fact store.
        """
        if fact_type not in FACT_TYPES:
            raise ValueError(f"Unknown fact_type {fact_type!r}")
        rec_list = list(records)
        bundle_key = (customer_id, source)
        with self._lock:
            self._external[bundle_key] = rec_list

        facts: List[Fact] = []
        for row in rec_list:
            value = row.get("policy_id") or row.get("id") or row.get("policy_number") or row.get("account_number")
            if not value:
                value = json.dumps(row, sort_keys=True, default=str)[:120]
            label = row.get("product_type") or row.get("type") or fact_type
            facts.append(Fact(
                fact_id=_new_fact_id(),
                customer_id=customer_id,
                fact_type=fact_type,
                value=str(value),
                label=str(label),
                confidence=1.0,
                source_document_id=None,
                source_document_sha256=None,
                source=source,
                metadata={"row": row},
            ))
        self._store_facts(customer_id, facts)
        return AssessmentResult(
            customer_id=customer_id,
            document_id=None,
            captured_at=datetime.utcnow().isoformat() + "Z",
            facts=facts,
            summary=self._summarise(facts),
        )

    # ── Customer 360 / risk ──────────────────────────────────────────────

    def get_facts(self, customer_id: str, fact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            facts = list(self._facts.get(customer_id, ()))
        if fact_type:
            facts = [f for f in facts if f.fact_type == fact_type]
        return [f.to_dict() for f in facts]

    def build_customer_360(self, customer_id: str) -> Dict[str, Any]:
        """Aggregate every collected fact into a deterministic profile snapshot."""
        with self._lock:
            facts = list(self._facts.get(customer_id, ()))
        profile: Dict[str, Any] = {
            "customer_id": customer_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "fact_count": len(facts),
            "identity": {
                "id_numbers": [],
                "full_names": [],
                "dates_of_birth": [],
            },
            "contact": {
                "addresses": [],
                "phones": [],
                "emails": [],
            },
            "photo_hints": [],
            "medical": {
                "conditions": [],
                "medications": [],
                "allergies": [],
                "vital_signs": [],
            },
            "insurance_indicators": [],
            "savings_indicators": [],
            "policy_references": [],
            "risk_indicators": [],
            "external_sources": {},
            "data_integrity": {
                "documents": sorted({f.source_document_id for f in facts if f.source_document_id}),
                "sha256_set": sorted({f.source_document_sha256 for f in facts if f.source_document_sha256}),
            },
        }
        for f in facts:
            if f.fact_type == "identity":
                if f.label == "id_number":
                    profile["identity"]["id_numbers"].append(_id_number_view(f))
                elif f.label == "full_name":
                    profile["identity"]["full_names"].append(f.value)
                elif f.label == "date_of_birth":
                    profile["identity"]["dates_of_birth"].append(f.value)
            elif f.fact_type == "contact":
                plural = f.label + "es" if f.label.endswith("s") else f.label + "s"
                target = profile["contact"].get(plural)
                if isinstance(target, list):
                    target.append(f.value)
            elif f.fact_type == "photo":
                profile["photo_hints"].append({
                    "document_id": f.source_document_id,
                    "value": f.value,
                    "metadata": f.metadata,
                })
            elif f.fact_type == "medical_condition":
                profile["medical"]["conditions"].append(f.value)
            elif f.fact_type == "medication":
                profile["medical"]["medications"].append(f.value)
            elif f.fact_type == "allergy":
                profile["medical"]["allergies"].append(f.value)
            elif f.fact_type == "vital_sign":
                profile["medical"]["vital_signs"].append({"label": f.label, "value": f.value})
            elif f.fact_type == "insurance":
                profile["insurance_indicators"].append({"label": f.label, "value": f.value})
            elif f.fact_type == "savings":
                profile["savings_indicators"].append({"label": f.label, "value": f.value})
            elif f.fact_type == "policy_reference":
                profile["policy_references"].append(f.value)
            elif f.fact_type == "risk_indicator":
                profile["risk_indicators"].append(f.value)
            elif f.fact_type in ("external_policy", "external_account", "external_contribution"):
                src = profile["external_sources"].setdefault(f.source, [])
                src.append({
                    "fact_type": f.fact_type,
                    "value": f.value,
                    "label": f.label,
                    "row": f.metadata.get("row"),
                })

        # De-duplicate while preserving order to keep the profile deterministic.
        for section, key in (
            ("identity", "full_names"),
            ("identity", "dates_of_birth"),
            ("contact", "addresses"),
            ("contact", "phones"),
            ("contact", "emails"),
            ("medical", "conditions"),
            ("medical", "medications"),
            ("medical", "allergies"),
        ):
            seen = set()
            keep = []
            for value in profile[section][key]:
                k = json.dumps(value, sort_keys=True, default=str) if not isinstance(value, str) else value.lower()
                if k in seen:
                    continue
                seen.add(k)
                keep.append(value)
            profile[section][key] = keep

        return profile

    def compute_risk_indicators(self, customer_id: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Derive a deterministic risk score from the unified fact store."""
        if profile is None:
            profile = self.build_customer_360(customer_id)
        score = 0.0
        contributors: List[Dict[str, Any]] = []

        condition_weights = {
            "cancer": 0.30, "tumor": 0.30, "tumour": 0.30,
            "stroke": 0.25, "heart disease": 0.25, "coronary": 0.25,
            "diabetes": 0.18, "hypertension": 0.15, "copd": 0.20,
            "hiv": 0.30, "aids": 0.30, "obesity": 0.12,
        }
        for cond in profile["medical"]["conditions"]:
            w = condition_weights.get(cond.lower(), 0.05)
            score += w
            contributors.append({"factor": "condition", "value": cond, "weight": w})

        for risk in profile["risk_indicators"]:
            w = 0.20 if "high" in risk.lower() else 0.10
            if "very high" in risk.lower() or "terminal" in risk.lower() or "fatal" in risk.lower():
                w = 0.35
            score += w
            contributors.append({"factor": "risk_marker", "value": risk, "weight": w})

        # Vital signs: BMI > 30 adds risk; systolic BP > 140 adds risk.
        for vs in profile["medical"]["vital_signs"]:
            label = (vs.get("label") or "").lower()
            try:
                value = float(vs.get("value")) if not isinstance(vs.get("value"), dict) else None
            except (TypeError, ValueError):
                value = None
            if label == "bmi" and value is not None:
                if value >= 35:
                    score += 0.18
                    contributors.append({"factor": "bmi", "value": value, "weight": 0.18})
                elif value >= 30:
                    score += 0.10
                    contributors.append({"factor": "bmi", "value": value, "weight": 0.10})
            if label == "blood_pressure_systolic" and value is not None and value >= 140:
                score += 0.10
                contributors.append({"factor": "blood_pressure", "value": value, "weight": 0.10})

        # External policy load - many policies but no recent updates raise risk
        external_total = sum(len(rows) for rows in profile["external_sources"].values())
        if external_total >= 6:
            score += 0.05
            contributors.append({"factor": "external_policy_count", "value": external_total, "weight": 0.05})

        score = min(1.0, round(score, 3))
        if score >= 0.80:
            level = "very_high"
        elif score >= 0.60:
            level = "high"
        elif score >= 0.35:
            level = "medium"
        elif score > 0:
            level = "low"
        else:
            level = "minimal"

        return {
            "customer_id": customer_id,
            "risk_score": score,
            "risk_level": level,
            "contributors": contributors,
            "computed_at": datetime.utcnow().isoformat() + "Z",
            "fact_count": profile["fact_count"],
        }

    def build_chart_data(self, customer_id: str) -> Dict[str, Any]:
        """Produce chart-ready data series for the customer dashboards.

        The returned payload is intentionally framework-agnostic: every chart is
        described as a list of ``{label, value}`` pairs so the frontend can
        render with whichever charting library is in use.
        """
        profile = self.build_customer_360(customer_id)
        risk = self.compute_risk_indicators(customer_id, profile=profile)

        condition_counts: Dict[str, int] = {}
        for cond in profile["medical"]["conditions"]:
            condition_counts[cond] = condition_counts.get(cond, 0) + 1

        external_counts = {
            src: len(rows) for src, rows in profile["external_sources"].items()
        }

        savings_total = 0.0
        savings_series: List[Dict[str, Any]] = []
        for ind in profile["savings_indicators"]:
            try:
                amount = float(ind["value"]) if not isinstance(ind["value"], dict) else float(ind["value"].get("amount", 0))
            except (TypeError, ValueError):
                continue
            savings_total += amount
            savings_series.append({"label": ind.get("label", "savings"), "value": amount})

        coverage_series: List[Dict[str, Any]] = []
        for ind in profile["insurance_indicators"]:
            try:
                amount = float(ind["value"]) if not isinstance(ind["value"], dict) else float(ind["value"].get("amount", 0))
            except (TypeError, ValueError):
                continue
            coverage_series.append({"label": ind.get("label", "insurance"), "value": amount})

        return {
            "customer_id": customer_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "charts": {
                "risk_breakdown": [
                    {"label": c["factor"] + ":" + str(c["value"]), "value": c["weight"]}
                    for c in risk["contributors"]
                ],
                "condition_distribution": [
                    {"label": k, "value": v} for k, v in sorted(condition_counts.items())
                ],
                "external_sources": [
                    {"label": k, "value": v} for k, v in sorted(external_counts.items())
                ],
                "savings_distribution": savings_series,
                "coverage_distribution": coverage_series,
            },
            "totals": {
                "savings_total": round(savings_total, 2),
                "coverage_items": len(coverage_series),
                "external_records": sum(external_counts.values()),
                "risk_score": risk["risk_score"],
                "risk_level": risk["risk_level"],
            },
        }

    def export_customer_pack(self, customer_id: str) -> Dict[str, Any]:
        """Build a re-uploadable JSON pack of every fact for a customer."""
        with self._lock:
            facts = [f.to_dict() for f in self._facts.get(customer_id, ())]
        payload = {
            "customer_id": customer_id,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "facts": facts,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        payload["sha256"] = digest
        return payload

    def import_customer_pack(self, pack: Dict[str, Any]) -> Dict[str, Any]:
        """Re-import a previously exported customer pack with integrity check."""
        if not isinstance(pack, dict) or "facts" not in pack:
            raise ValueError("Invalid customer pack payload")
        cust = str(pack.get("customer_id") or "").strip()
        if not cust:
            raise ValueError("customer_id required in pack")
        verifier = dict(pack)
        digest = verifier.pop("sha256", None)
        recomputed = hashlib.sha256(
            json.dumps(verifier, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        integrity = digest == recomputed
        facts = []
        for raw in pack.get("facts", []):
            try:
                facts.append(Fact(
                    fact_id=raw.get("fact_id") or _new_fact_id(),
                    customer_id=cust,
                    fact_type=raw.get("fact_type", "risk_indicator"),
                    value=raw.get("value"),
                    label=raw.get("label", ""),
                    confidence=float(raw.get("confidence", 0.5)),
                    source_document_id=raw.get("source_document_id"),
                    source_document_sha256=raw.get("source_document_sha256"),
                    source=raw.get("source", "imported"),
                    metadata=raw.get("metadata") or {},
                    captured_at=raw.get("captured_at") or datetime.utcnow().isoformat() + "Z",
                ))
            except Exception as exc:
                logger.warning("Skipping invalid fact in pack import: %s", exc)
        if integrity:
            self._store_facts(cust, facts)
        else:
            logger.warning("Rejecting tampered customer pack for %s: SHA-256 mismatch", cust)
            facts = []
        return {
            "customer_id": cust,
            "imported_facts": len(facts),
            "integrity_ok": integrity,
            "expected_sha256": digest,
            "actual_sha256": recomputed,
        }

    # ── Extraction helpers ───────────────────────────────────────────────

    def _extract_searchable_text(
        self,
        record: Dict[str, Any],
        raw_bytes: bytes,
        mime: str,
        ext: str,
    ) -> str:
        """Return the best-effort searchable text for a document."""
        text = record.get("extracted_text") or ""
        if text:
            return text[:MAX_TEXT_SCAN]
        if not raw_bytes:
            return ""
        try:
            if mime.startswith("text/") or ext in (".csv", ".txt", ".json", ".xml", ".html", ".htm"):
                return raw_bytes.decode("utf-8", errors="replace")[:MAX_TEXT_SCAN]
            if mime == "application/pdf" or ext == ".pdf":
                # Reuse the document service PDF heuristic if available.
                doc_svc = self.document_service
                pdf_helper = getattr(doc_svc, "_extract_pdf_text", None)
                if callable(pdf_helper):
                    return pdf_helper(raw_bytes)[:MAX_TEXT_SCAN]
                return raw_bytes.decode("latin-1", errors="replace")[:MAX_TEXT_SCAN]
            return raw_bytes.decode("utf-8", errors="replace")[:MAX_TEXT_SCAN]
        except Exception:
            return ""

    def _extract_facts_from_text(
        self,
        *,
        text: str,
        customer_id: str,
        document_id: Optional[str],
        sha256: Optional[str],
        source: str,
    ) -> List[Fact]:
        if not text:
            return []
        facts: List[Fact] = []

        for label, country, pattern, validator in _ID_PATTERNS:
            for match in pattern.finditer(text):
                raw_value = match.group(1)
                cleaned = re.sub(r"\s", "", raw_value)
                ok = True
                if validator is not None:
                    try:
                        ok = bool(validator(raw_value))
                    except Exception:
                        ok = False
                confidence = 0.95 if validator and ok else (0.70 if validator is None else 0.0)
                if confidence == 0.0:
                    continue
                facts.append(Fact(
                    fact_id=_new_fact_id(),
                    customer_id=customer_id,
                    fact_type="identity",
                    value=cleaned,
                    label="id_number",
                    confidence=confidence,
                    source_document_id=document_id,
                    source_document_sha256=sha256,
                    source=source,
                    metadata={"id_type": label, "country": country, "raw": raw_value},
                ))

        for match in _EMAIL_RE.finditer(text):
            facts.append(_make_fact(customer_id, "contact", "email", match.group(0).lower(),
                                    document_id, sha256, source, 0.92))

        for match in _PHONE_RE.finditer(text):
            value = re.sub(r"[\s\-.]", "", match.group(0))
            if 7 <= len(re.sub(r"\D", "", value)) <= 16:
                facts.append(_make_fact(customer_id, "contact", "phone", value,
                                        document_id, sha256, source, 0.55))

        for match in _DOB_RE.finditer(text):
            facts.append(_make_fact(customer_id, "identity", "date_of_birth", match.group(1),
                                    document_id, sha256, source, 0.85))

        for match in _ADDRESS_RE.finditer(text):
            value = re.split(r"\s{2,}", match.group(1).strip())[0].strip()
            if value:
                facts.append(_make_fact(customer_id, "contact", "address", value,
                                        document_id, sha256, source, 0.65))

        for match in _IBAN_RE.finditer(text):
            facts.append(_make_fact(customer_id, "savings", "iban", match.group(1),
                                    document_id, sha256, source, 0.90))

        lower = text.lower()
        for cond in _MEDICAL_CONDITIONS:
            if cond in lower:
                facts.append(_make_fact(customer_id, "medical_condition", cond, cond,
                                        document_id, sha256, source, 0.75))
        for med in _MEDICATIONS:
            if med in lower:
                facts.append(_make_fact(customer_id, "medication", med, med,
                                        document_id, sha256, source, 0.80))
        for allergy in _ALLERGIES:
            if allergy in lower:
                facts.append(_make_fact(customer_id, "allergy", allergy, allergy,
                                        document_id, sha256, source, 0.80))

        bmi_match = _BMI_RE.search(text)
        if bmi_match:
            facts.append(_make_fact(customer_id, "vital_sign", "bmi", float(bmi_match.group(1)),
                                    document_id, sha256, source, 0.90))
        bp_match = _BP_RE.search(text)
        if bp_match:
            facts.append(_make_fact(customer_id, "vital_sign", "blood_pressure_systolic",
                                    float(bp_match.group(1)), document_id, sha256, source, 0.90))
            facts.append(_make_fact(customer_id, "vital_sign", "blood_pressure_diastolic",
                                    float(bp_match.group(2)), document_id, sha256, source, 0.90))

        for keyword in _INSURANCE_KEYWORDS:
            if keyword in lower:
                amount = _amount_near(text, keyword)
                if amount is not None:
                    facts.append(_make_fact(customer_id, "insurance", keyword, amount,
                                            document_id, sha256, source, 0.70))
                else:
                    facts.append(_make_fact(customer_id, "insurance", keyword, True,
                                            document_id, sha256, source, 0.55))

        for keyword in _SAVINGS_KEYWORDS:
            if keyword in lower:
                amount = _amount_near(text, keyword)
                if amount is not None:
                    facts.append(_make_fact(customer_id, "savings", keyword, amount,
                                            document_id, sha256, source, 0.70))
                else:
                    facts.append(_make_fact(customer_id, "savings", keyword, True,
                                            document_id, sha256, source, 0.55))

        matched_risk: List[str] = []
        for marker in sorted(_RISK_KEYWORDS, key=len, reverse=True):
            if marker in lower:
                if any(marker in longer for longer in matched_risk):
                    continue
                matched_risk.append(marker)
                facts.append(_make_fact(customer_id, "risk_indicator", marker, marker,
                                        document_id, sha256, source, 0.80))

        return facts

    def _extract_photo_facts(
        self,
        *,
        raw_bytes: bytes,
        customer_id: str,
        document_id: Optional[str],
        sha256: Optional[str],
    ) -> List[Fact]:
        """Best-effort portrait detection.

        Without OpenCV we can still tell the front-end that a portrait-shaped
        image was uploaded and where to crop in normalised coordinates. The
        face crop hint is just the centred upper portion of the image, which is
        the conventional layout for ID photographs.
        """
        try:
            doc_svc = self.document_service
            meta = doc_svc._image_metadata(raw_bytes)  # type: ignore[attr-defined]
        except Exception:
            meta = {}
        width = meta.get("width") or 0
        height = meta.get("height") or 0
        aspect = round(width / height, 3) if width and height else None
        portrait = bool(aspect and 0.6 < aspect < 0.95)
        crop_hint = None
        if width and height:
            crop_hint = {
                "x": round(width * 0.18),
                "y": round(height * 0.10),
                "width": round(width * 0.64),
                "height": round(height * 0.55),
                "normalised": {"x": 0.18, "y": 0.10, "width": 0.64, "height": 0.55},
            }
        if not crop_hint and not aspect:
            return []
        return [_make_fact(
            customer_id,
            "photo",
            "portrait_hint",
            {
                "width": width,
                "height": height,
                "aspect_ratio": aspect,
                "likely_portrait": portrait,
                "crop_hint": crop_hint,
            },
            document_id,
            sha256,
            "image_analysis",
            0.55 if portrait else 0.30,
        )]

    def _summarise(self, facts: List[Fact]) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        for f in facts:
            by_type[f.fact_type] = by_type.get(f.fact_type, 0) + 1
        return {
            "facts_extracted": len(facts),
            "by_type": by_type,
            "top_confidence": round(max((f.confidence for f in facts), default=0.0), 3),
        }

    # ── Persistence ──────────────────────────────────────────────────────

    def _store_facts(self, customer_id: str, facts: List[Fact]) -> None:
        if not customer_id or not facts:
            return
        with self._lock:
            existing = self._facts.setdefault(customer_id, [])
            seen = {(f.fact_type, f.label, _hashable(f.value)) for f in existing}
            for f in facts:
                key = (f.fact_type, f.label, _hashable(f.value))
                if key in seen:
                    continue
                existing.append(f)
                seen.add(key)
            self._persist_customer(customer_id, existing)

    def _persist_customer(self, customer_id: str, facts: List[Fact]) -> None:
        try:
            safe_cid = re.sub(r"[^A-Za-z0-9_-]", "_", customer_id)[:80] or "anonymous"
            target = os.path.join(self._fact_store_dir, f"{safe_cid}.json")
            payload = {
                "customer_id": customer_id,
                "saved_at": datetime.utcnow().isoformat() + "Z",
                "facts": [f.to_dict() for f in facts],
            }
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except Exception as exc:
            logger.warning("Assessment fact persistence failed for %s: %s", customer_id, exc)

    def _load_from_disk(self) -> None:
        try:
            if not os.path.isdir(self._fact_store_dir):
                return
            for name in os.listdir(self._fact_store_dir):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self._fact_store_dir, name)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                    cust = str(payload.get("customer_id") or "").strip()
                    if not cust:
                        continue
                    facts = []
                    for raw in payload.get("facts", []):
                        try:
                            facts.append(Fact(
                                fact_id=raw.get("fact_id") or _new_fact_id(),
                                customer_id=cust,
                                fact_type=raw.get("fact_type", "risk_indicator"),
                                value=raw.get("value"),
                                label=raw.get("label", ""),
                                confidence=float(raw.get("confidence", 0.5)),
                                source_document_id=raw.get("source_document_id"),
                                source_document_sha256=raw.get("source_document_sha256"),
                                source=raw.get("source", "imported"),
                                metadata=raw.get("metadata") or {},
                                captured_at=raw.get("captured_at") or datetime.utcnow().isoformat() + "Z",
                            ))
                        except Exception:
                            continue
                    if facts:
                        with self._lock:
                            self._facts[cust] = facts
                except Exception as exc:
                    logger.warning("Failed loading fact file %s: %s", path, exc)
        except Exception as exc:
            logger.warning("Assessment fact store load failed: %s", exc)


# ── Module helpers ────────────────────────────────────────────────────────────

def _new_fact_id() -> str:
    return f"FACT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"


def _make_fact(customer_id, fact_type, label, value, doc_id, sha, source, confidence) -> Fact:
    return Fact(
        fact_id=_new_fact_id(),
        customer_id=customer_id,
        fact_type=fact_type,
        value=value,
        label=label,
        confidence=confidence,
        source_document_id=doc_id,
        source_document_sha256=sha,
        source=source,
    )


def _hashable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def _id_number_view(fact: Fact) -> Dict[str, Any]:
    return {
        "value": fact.value,
        "country": fact.metadata.get("country", ""),
        "id_type": fact.metadata.get("id_type", ""),
        "confidence": fact.confidence,
        "source_document_id": fact.source_document_id,
    }


def _amount_near(text: str, keyword: str) -> Optional[float]:
    """Look for a monetary amount within 80 characters of ``keyword``."""
    lower = text.lower()
    idx = lower.find(keyword)
    if idx < 0:
        return None
    window = text[max(0, idx - 40): idx + len(keyword) + 80]
    best: Optional[float] = None
    for match in _AMOUNT_RE.finditer(window):
        raw = match.group("amount") or ""
        if not raw:
            continue
        cleaned = raw.replace(",", "")
        if cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "", cleaned.count(".") - 1)
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        if best is None or value > best:
            best = value
    return best


# ── Singleton plumbing ────────────────────────────────────────────────────────

_default_service: Optional[AssessmentCenterService] = None
_default_lock = threading.Lock()


def get_assessment_center(document_service=None) -> AssessmentCenterService:
    """Return the module-level singleton, creating it lazily."""
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = AssessmentCenterService(document_service=document_service)
        elif document_service is not None and _default_service._document_service is None:
            _default_service._document_service = document_service
        return _default_service


def reset_assessment_center() -> None:
    """Reset the singleton (used by the test harness)."""
    global _default_service
    with _default_lock:
        if _default_service is not None:
            _default_service.reset()
        _default_service = None
