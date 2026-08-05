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
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

def _running_on_railway() -> bool:
    """Detect Railway runtime via env signals.

    Used to gate the ``/data`` fallback so a developer machine that
    coincidentally has a writable ``/data`` directory doesn't get its
    persistence path silently redirected there. Any of these signals is
    enough - they are all set by Railway in production deploys.
    """
    for key in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
        "RAILWAY_DEPLOYMENT_ID",
        "RAILWAY_STATIC_URL",
    ):
        if os.environ.get(key):
            return True
    return False


def _data_volume_eligible(probe_dir: str = "/data") -> bool:
    """``/data`` is only used when we can prove Railway / Docker context.

    Conditions (all required):
      - the directory exists and is writable, AND
      - we are running on Railway (env signals) or the operator has
        explicitly opted in via ``PHINS_USE_DATA_VOLUME=1``.
    """
    if not (os.path.isdir(probe_dir) and os.access(probe_dir, os.W_OK)):
        return False
    if os.environ.get("PHINS_USE_DATA_VOLUME", "").strip() == "1":
        return True
    return _running_on_railway()


def _resolve_fact_store_dir() -> str:
    """Return the persistent fact-store directory.

    Priority:
      1. ``PHINS_ASSESSMENT_FACT_STORE`` (explicit override)
      2. ``RAILWAY_VOLUME_MOUNT_PATH/assessment_center`` (Railway volume)
      3. ``/data/assessment_center`` (Docker volume mount, gated by
         :func:`_data_volume_eligible` so dev machines that happen to
         have a writable ``/data`` directory aren't hijacked)
      4. ``<repo>/data/assessment_center`` (developer fallback)

    The first three options survive Railway container restarts; the last is
    ephemeral and emits a warning so operators know to attach a volume.
    """
    explicit = os.environ.get("PHINS_ASSESSMENT_FACT_STORE")
    if explicit:
        return explicit

    railway_mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_mount and os.path.isdir(railway_mount):
        return os.path.join(railway_mount, "assessment_center")

    if _data_volume_eligible():
        return "/data/assessment_center"

    fallback = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "assessment_center",
    )
    # Only emit the warning if we are not in a test environment to keep the
    # CI output quiet.
    if not os.environ.get("PHINS_TEST_MODE"):
        print(
            f"⚠️  [assessment-center] Using ephemeral fact store {fallback} - "
            "set PHINS_ASSESSMENT_FACT_STORE or mount a volume at /data for "
            "durable Customer 360 persistence on Railway.",
            flush=True,
        )
    return fallback


ASSESSMENT_FACT_STORE = _resolve_fact_store_dir()

# Bounded list / batch sizes used to prevent runaway memory or HTTP timeouts
# when admins kick off large backfill or BI runs on Railway's edge timeout
# (~120s) and small (512MB-2GB) container memory budgets.
MAX_FACTS_PER_CUSTOMER = int(os.environ.get("PHINS_MAX_FACTS_PER_CUSTOMER", 5000))
MAX_FACTS_LOAD_FILES = int(os.environ.get("PHINS_MAX_FACTS_LOAD_FILES", 10000))

# On-disk fact store format marker. v2 files wrap the payload in a vault
# envelope (Fernet-encrypted when PHINS_ENCRYPTION_KEY is set) and carry a
# facts_sha256 integrity checksum. Legacy plaintext files (no marker) remain
# readable and are upgraded to v2 on the next save.
FACT_STORE_FORMAT_V2 = "phins-assessment-facts-v2"
MAX_EXPORT_ROWS = int(os.environ.get("PHINS_MAX_EXPORT_ROWS", 50000))


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
    # Always-on metadata so a successful upload always produces ≥1 fact.
    "document_meta",       # file name, mime type, size, ocr_required hint
    "extraction_hint",     # explanatory hint when no text could be mined
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
# The two Israeli patterns below capture both the bare 9-digit form and the
# common Hebrew-prefixed forms ("ת.ז.", "תעודת זהות", "מספר זהות") that
# show up in scanned ID PDFs and Mislaka downloads.
_ID_PATTERNS: Tuple[Tuple[str, str, "re.Pattern[str]", Optional[Any]], ...] = (
    ("israeli_id_hebrew", "IL",
        re.compile(
            r"(?:ת\.?\s*ז\.?|תעודת\s+זהות|מספר\s+זהות)\s*[:\-]?\s*(\d{9})",
            re.IGNORECASE,
        ),
        _israeli_id_valid),
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

_NAME_RE = re.compile(
    r"(?:full\s+name|name|שם\s+מלא|שם\s+פרטי|שם\s+משפחה|nombre|nom)\s*[:\-]?\s*"
    r"([A-Za-z\u0590-\u05FF\u0621-\u064A][A-Za-z\u0590-\u05FF\u0621-\u064A '\-]{2,80})",
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


# ── Adjustable reporting filters ────────────────────────────────────────────

def _parse_filter_date(value: Any) -> Optional[datetime]:
    """Parse a filter date string into a ``datetime`` (date precision)."""
    if not value:
        return None
    raw = str(value).strip()
    candidate = raw.replace("Z", "").split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(candidate, fmt)
        except (ValueError, TypeError):
            continue
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 8:
        for fmt in ("%Y%m%d", "%d%m%Y"):
            try:
                return datetime.strptime(digits, fmt)
            except (ValueError, TypeError):
                continue
    return None


def _fact_matches_filters(fact: "Fact", filters: Dict[str, Any]) -> bool:
    """Adjustable-reporting predicate over a single fact.

    Supported keys (all optional; an unset key imposes no constraint):

    * ``date_from`` / ``date_to`` - inclusive window on the policy business
      date (``start_date`` / ``last_update`` from external rows, selectable via
      ``date_field``), falling back to the fact ``captured_at`` when absent.
    * ``fact_type`` - exact fact-type match.
    * ``source`` - exact source match (e.g. ``mislaka``, ``document``).
    * ``min_confidence`` - minimum confidence threshold.
    * ``policy_number`` - matches the fact value or its metadata policy number.
    * ``provider`` / ``product`` / ``status`` - substring match against the
      fact value or affiliation metadata.

    Filtering only ever *removes* facts; it never alters or fabricates them.
    """
    if not filters:
        return True

    meta = fact.metadata if isinstance(fact.metadata, dict) else {}
    # External clearinghouse facts (e.g. Mislaka) carry the full source row
    # under metadata["row"]; flatten it so filters can match its fields too.
    row = meta.get("row") if isinstance(meta.get("row"), dict) else {}
    lookup = {**row, **{k: v for k, v in meta.items() if k != "row"}}
    value_str = "" if fact.value is None else str(fact.value).lower()

    ft = filters.get("fact_type")
    if ft and str(ft).strip().lower() != str(fact.fact_type).strip().lower():
        return False

    src = filters.get("source")
    if src and str(src).strip().lower() != str(fact.source).strip().lower():
        return False

    min_conf = filters.get("min_confidence")
    if min_conf not in (None, ""):
        try:
            if float(fact.confidence) < float(min_conf):
                return False
        except (TypeError, ValueError):
            pass

    pol = filters.get("policy_number")
    if pol:
        want = str(pol).strip().lower()
        candidates = {value_str}
        for key in ("policy_number", "policy_id"):
            if lookup.get(key):
                candidates.add(str(lookup.get(key)).lower())
        if want not in candidates:
            return False

    for fkey, mkeys in (
        ("provider", ("affiliation_provider", "company_name", "provider")),
        ("product", ("affiliation_product", "product_type", "product_type_name")),
        ("status", ("affiliation_status", "status", "status_name")),
    ):
        want = filters.get(fkey)
        if not want:
            continue
        want = str(want).strip().lower()
        haystacks = [value_str]
        for mk in mkeys:
            if lookup.get(mk):
                haystacks.append(str(lookup.get(mk)).lower())
        if not any(want in h for h in haystacks):
            return False

    date_from = _parse_filter_date(filters.get("date_from"))
    date_to = _parse_filter_date(filters.get("date_to"))
    if date_from or date_to:
        # Prefer the policy business date carried by external (e.g. Mislaka)
        # rows so date-window reporting matches the source's report filters;
        # fall back to the fact ingestion time only when no business date is
        # present. ``date_field`` mirrors Mislaka's ReportFilters.
        date_field = str(filters.get("date_field") or "start_date").strip()
        fact_date = None
        for key in (date_field, "start_date", "last_update"):
            fact_date = _parse_filter_date(lookup.get(key))
            if fact_date is not None:
                break
        if fact_date is None:
            fact_date = _parse_filter_date(fact.captured_at)
        if fact_date is None:
            return False
        if date_from and fact_date < date_from:
            return False
        if date_to and fact_date > date_to:
            return False

    return True


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

        # Always emit a baseline metadata fact so the customer sees the
        # document in their Customer 360 even when no text could be
        # extracted (scanned PDFs without OCR, image-only IDs, novel
        # binary formats). This guarantees "facts: 0" never happens for
        # a successful upload.
        try:
            from services.hebrew_assessment_lexicon import (
                detect_document_language,
                hebrew_ratio,
            )
            doc_lang = detect_document_language(text or "")
            he_ratio = round(hebrew_ratio(text or ""), 3)
        except Exception:
            doc_lang, he_ratio = "unknown", 0.0
        meta_value = {
            "file_name": record.get("original_file_name") or record.get("file_name") or "",
            "mime_type": mime,
            "size_bytes": record.get("file_size") or len(raw_bytes),
            "extracted_text_chars": len(text or ""),
            "language": doc_lang,
            "hebrew_ratio": he_ratio,
            "ocr_required": bool(
                (mime.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"))
                or (text and text.startswith("[PDF content"))
            ),
        }
        facts.append(_make_fact(
            cust, "document_meta", "uploaded", meta_value,
            document_id, sha, source_context or "document_upload",
            confidence=0.99,
            metadata={"lang": doc_lang},
        ))

        # If no real intelligence came out of the file, surface an
        # explicit hint so the workbench can show a clear "extraction
        # incomplete - re-scan or upload a typed copy" badge instead of
        # a confusing "no facts".
        non_meta_facts = [f for f in facts if f.fact_type != "document_meta"]
        if not non_meta_facts:
            facts.append(_make_fact(
                cust, "extraction_hint", "no_text_extracted",
                "No text could be mined from this file. If it is a "
                "scanned PDF or photograph, re-upload a typed/searchable "
                "copy or run OCR before re-scanning.",
                document_id, sha, source_context or "document_upload",
                confidence=0.95,
            ))

        self._store_facts(cust, facts)
        summary = self._summarise(facts)

        # When Hebrew intelligence was mined, snapshot the resulting customer
        # risk into the durable assessment-record store so the score → decision
        # loop accumulates training data from non-English documents too.
        try:
            hebrew_facts = [
                f for f in facts
                if (f.metadata or {}).get("lang") == "he"
                or (f.metadata or {}).get("extractor") == "hebrew_assessment_lexicon"
            ]
            if hebrew_facts:
                self._snapshot_hebrew_assessment(
                    customer_id=cust,
                    document_id=document_id,
                    hebrew_fact_count=len(hebrew_facts),
                    language=meta_value.get("language"),
                )
                summary["hebrew_facts"] = len(hebrew_facts)
                summary["document_language"] = meta_value.get("language")
        except Exception as snap_exc:
            logger.debug("Hebrew assessment snapshot skipped: %s", snap_exc)

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

    LIST_CUSTOMERS_TIME_BUDGET_S = float(os.environ.get("PHINS_LIST_CUSTOMERS_TIME_BUDGET_S", 10))

    def list_customers_with_facts(self) -> List[Dict[str, Any]]:
        """Return one summary row per customer that has any facts on file.

        Each row contains the fact count, the most recent capture timestamp,
        the document set that contributed to the profile, and the cached risk
        level. Used by the Assessment Center dashboard to populate the admin
        customer picker.
        """
        with self._lock:
            snapshot = {cid: list(facts) for cid, facts in self._facts.items()}

        deadline = time.monotonic() + self.LIST_CUSTOMERS_TIME_BUDGET_S
        rows: List[Dict[str, Any]] = []
        truncated = False
        for cid, facts in snapshot.items():
            if not facts:
                continue
            if time.monotonic() > deadline:
                truncated = True
                break
            try:
                doc_ids = sorted({f.source_document_id for f in facts if f.source_document_id})
                latest = max((f.captured_at for f in facts), default="")
                try:
                    risk = self.compute_risk_indicators(cid)
                    risk_score = risk.get("risk_score", 0.0)
                    risk_level = risk.get("risk_level", "minimal")
                except Exception as exc:
                    logger.warning("risk computation failed for %s: %s", cid, exc)
                    risk_score = 0.0
                    risk_level = "unknown"
                by_type: Dict[str, int] = {}
                for f in facts:
                    by_type[f.fact_type] = by_type.get(f.fact_type, 0) + 1
                rows.append({
                    "customer_id": cid,
                    "fact_count": len(facts),
                    "document_count": len(doc_ids),
                    "documents": doc_ids,
                    "by_type": by_type,
                    "latest_capture": latest,
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                })
            except Exception as exc:
                # Never let a single malformed customer entry kill the whole
                # admin tile; just skip it and keep going.
                logger.warning("Skipping customer %s in list: %s", cid, exc)
                continue
        rows.sort(key=lambda r: r.get("latest_capture", ""), reverse=True)
        if truncated:
            rows.append({"customer_id": "__truncated__",
                         "fact_count": 0,
                         "note": "List truncated to keep the response inside Railway's HTTP budget."})
        return rows

    BACKFILL_DEFAULT_LIMIT = int(os.environ.get("PHINS_BACKFILL_DEFAULT_LIMIT", 200))
    BACKFILL_MAX_LIMIT = int(os.environ.get("PHINS_BACKFILL_MAX_LIMIT", 1000))
    BACKFILL_TIME_BUDGET_S = float(os.environ.get("PHINS_BACKFILL_TIME_BUDGET_S", 90))

    def backfill_documents(
        self,
        *,
        document_ids: Optional[Iterable[str]] = None,
        customer_id: Optional[str] = None,
        force: bool = False,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run the assessment pipeline on documents that pre-date this service.

        The backend can land before any UI for the Assessment Center is in
        place, which means there is normally a population of older documents
        sitting in :class:`DocumentProcessingService` (and the legacy
        ``POLICY_DOCUMENTS`` mirror) that have never been mined for facts.
        This method walks those documents and runs ``assess_document`` on
        each one.

        The operation is intentionally **idempotent**: a document that already
        has at least one fact recorded against it is skipped unless the caller
        passes ``force=True``. Errors per document are captured and reported
        but never abort the run, so a single bad file cannot poison a large
        batch.

        Args:
            document_ids: optional explicit list of persistent document IDs.
                When ``None``, every document in the document service is
                considered.
            customer_id: optional filter; only documents owned by this
                customer are processed.
            force: re-extract even when facts already exist.
            limit: hard cap on the number of documents processed in this run.

        Returns:
            A dict with ``scanned``, ``assessed``, ``skipped``, ``errors``
            and ``customers_updated`` counters plus the per-customer fact
            delta in ``deltas``.
        """
        ids: List[str] = []
        if document_ids is not None:
            ids = [str(d) for d in document_ids if d]
        else:
            try:
                page = 1
                page_size = 200
                while True:
                    response = self.document_service.list_documents(
                        customer_id=customer_id,
                        page=page,
                        page_size=page_size,
                    )
                    items = response.get("items") if isinstance(response, dict) else response
                    if not items:
                        break
                    for item in items:
                        if isinstance(item, dict):
                            doc_id = item.get("id") or item.get("document_id")
                        else:
                            doc_id = getattr(item, "id", None)
                        if doc_id:
                            ids.append(str(doc_id))
                    if len(items) < page_size:
                        break
                    page += 1
            except Exception as exc:
                logger.warning("backfill_documents listing failed: %s", exc)

        # Resolve the effective per-call cap.
        #
        # Semantics chosen to remove the asymmetry the bug review flagged:
        #   - ``limit=None`` (caller did not specify) means "process as many
        #     as we can" and is bounded by ``BACKFILL_MAX_LIMIT`` plus the
        #     wall-clock ``BACKFILL_TIME_BUDGET_S``. Previously this silently
        #     fell back to ``BACKFILL_DEFAULT_LIMIT`` (200) which meant a
        #     "no limit" request processed *fewer* docs than an explicit
        #     ``limit=500``.
        #   - ``limit=N`` is clamped to ``[1, BACKFILL_MAX_LIMIT]``.
        #   - ``limit`` parsing failures fall back to ``BACKFILL_DEFAULT_LIMIT``
        #     to preserve the conservative behaviour for malformed input.
        if limit is None:
            effective_limit = self.BACKFILL_MAX_LIMIT
        else:
            try:
                effective_limit = max(1, min(int(limit), self.BACKFILL_MAX_LIMIT))
            except (TypeError, ValueError):
                effective_limit = self.BACKFILL_DEFAULT_LIMIT
        truncated = len(ids) > effective_limit
        ids = ids[:effective_limit]

        existing = self.get_document_assessments(ids) if ids else {}
        scanned = 0
        assessed = 0
        skipped = 0
        errors: List[Dict[str, Any]] = []
        customers_updated: set = set()
        deltas: Dict[str, int] = {}

        deadline = time.monotonic() + self.BACKFILL_TIME_BUDGET_S
        time_budget_hit = False

        for doc_id in ids:
            if time.monotonic() > deadline:
                # Stop early so the HTTP request returns within Railway's edge
                # timeout. The caller can issue another request to keep going.
                time_budget_hit = True
                break
            scanned += 1
            current = existing.get(doc_id, {})
            if not force and current.get("facts_extracted"):
                skipped += 1
                continue
            try:
                result = self.assess_document(
                    doc_id,
                    customer_id=customer_id,
                    source_context="backfill",
                )
                facts_added = result.summary.get("facts_extracted", 0) if result.summary else 0
                if facts_added:
                    assessed += 1
                    customers_updated.add(result.customer_id)
                    deltas[result.customer_id] = deltas.get(result.customer_id, 0) + facts_added
                else:
                    # No new facts could be mined from this file (unsupported
                    # binary format, empty text, etc.). Treat it as scanned
                    # but not assessed so the dashboard does not double-count.
                    skipped += 1
            except Exception as exc:
                logger.warning("backfill_documents assess failed for %s: %s", doc_id, exc)
                errors.append({"document_id": doc_id, "error": str(exc)})

        return {
            "scanned": scanned,
            "assessed": assessed,
            "skipped": skipped,
            "error_count": len(errors),
            "errors": errors[:50],
            "customers_updated": sorted(customers_updated),
            "deltas": deltas,
            "force": bool(force),
            "limit_applied": effective_limit,
            "truncated": truncated,
            "time_budget_hit": time_budget_hit,
        }

    def backfill_status(self, customer_id: Optional[str] = None) -> Dict[str, Any]:
        """Summarise how many documents are still missing assessment facts.

        Used by the admin tile to surface a "backfill needed" prompt without
        having to actually run the heavy pipeline.
        """
        ids: List[str] = []
        try:
            page = 1
            page_size = 200
            while True:
                response = self.document_service.list_documents(
                    customer_id=customer_id,
                    page=page,
                    page_size=page_size,
                )
                items = response.get("items") if isinstance(response, dict) else response
                if not items:
                    break
                for item in items:
                    doc_id = (item.get("id") or item.get("document_id")
                              if isinstance(item, dict)
                              else getattr(item, "id", None))
                    if doc_id:
                        ids.append(str(doc_id))
                if len(items) < page_size:
                    break
                page += 1
        except Exception as exc:
            # SECURITY: This endpoint is reachable by every authenticated
            # user (admins see everything, customers see their own
            # backfill status). The exception object can carry filesystem
            # paths, SQLAlchemy connection strings, or library internals,
            # so we never echo str(exc) back to the caller. Operators
            # already get the full diagnostics from logger.warning above.
            logger.warning("backfill_status listing failed: %s", exc)
            return {
                "total_documents": 0,
                "with_facts": 0,
                "without_facts": 0,
                "error": "Document listing unavailable",
            }

        summaries = self.get_document_assessments(ids) if ids else {}
        with_facts = sum(1 for d in ids if summaries.get(d, {}).get("facts_extracted"))
        return {
            "total_documents": len(ids),
            "with_facts": with_facts,
            "without_facts": max(0, len(ids) - with_facts),
            "customer_id": customer_id or "",
        }

    # ── BI / "describe data with data" ──────────────────────────────────────

    # Each fact_type is mapped to a human-friendly relevance category. The
    # workbench surfaces the categories in this order so identity always
    # appears above contact, medical above financial, etc.
    _CATEGORY_FOR_FACT = {
        "identity": "Identity",
        "contact": "Contact",
        "photo": "Photo / Portrait",
        "medical_condition": "Medical",
        "medication": "Medical",
        "allergy": "Medical",
        "vital_sign": "Medical",
        "insurance": "Insurance",
        "savings": "Financial",
        "policy_reference": "Policy / Claim references",
        "risk_indicator": "Risk markers",
        "external_policy": "External clearinghouse",
        "external_account": "External clearinghouse",
        "external_contribution": "External clearinghouse",
        "document_meta": "Document metadata",
        "extraction_hint": "Document metadata",
    }

    _CATEGORY_ORDER = (
        "Identity",
        "Contact",
        "Photo / Portrait",
        "Medical",
        "Insurance",
        "Financial",
        "Policy / Claim references",
        "Risk markers",
        "External clearinghouse",
        "Document metadata",
    )

    def describe_data_with_data(
        self,
        customer_id: str,
        document_ids: Optional[Iterable[str]] = None,
        *,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a hierarchical 'describe data with data' view.

        Every fact stored for the customer is grouped by relevance category
        (Identity, Contact, Medical, Insurance, Financial, ...) and within
        each category by ``label``. Each entry keeps the source document ID,
        document type (id / medical / receipt / financial / general), and
        SHA-256 hash so the workbench can prove provenance.

        When ``document_ids`` is provided the description is restricted to
        the union of facts that come from those documents - this is the
        cross-document mode used by the workbench when an admin picks a
        subset of files.
        """
        with self._lock:
            facts = list(self._facts.get(customer_id, ()))
        ids_set = {str(d) for d in document_ids} if document_ids else None
        if ids_set is not None:
            facts = [f for f in facts if (f.source_document_id or "") in ids_set]
        if filters:
            facts = [f for f in facts if _fact_matches_filters(f, filters)]

        # Build a lookup of document metadata so we can label each entry with
        # the originating document_type (id / medical / receipt / financial).
        doc_lookup: Dict[str, Dict[str, Any]] = {}
        for f in facts:
            if not f.source_document_id or f.source_document_id in doc_lookup:
                continue
            try:
                rec = self.document_service.get_document(f.source_document_id) or {}
            except Exception:
                rec = {}
            if isinstance(rec, dict):
                doc_lookup[f.source_document_id] = {
                    "name": rec.get("file_name") or rec.get("original_file_name") or f.source_document_id,
                    "document_type": rec.get("document_type") or "general",
                    "category": rec.get("category") or "general",
                    "mime_type": rec.get("mime_type") or "",
                    "uploaded_at": rec.get("uploaded_date")
                                   or rec.get("uploaded_at")
                                   or rec.get("created_at"),
                }
            else:
                doc_lookup[f.source_document_id] = {"name": f.source_document_id}

        sections: Dict[str, Dict[str, Any]] = {}
        for f in facts:
            cat = self._CATEGORY_FOR_FACT.get(f.fact_type, "Other")
            sec = sections.setdefault(cat, {
                "category": cat,
                "fact_count": 0,
                "by_label": {},
                "documents": set(),
                "top_confidence": 0.0,
            })
            label_bucket = sec["by_label"].setdefault(f.label or f.fact_type, [])
            doc_meta = doc_lookup.get(f.source_document_id or "", {})
            label_bucket.append({
                "value": f.value,
                "fact_type": f.fact_type,
                "confidence": round(f.confidence, 3),
                "source": f.source,
                "document_id": f.source_document_id,
                "document_name": doc_meta.get("name", ""),
                "document_type": doc_meta.get("document_type", ""),
                "document_category": doc_meta.get("category", ""),
                "sha256": f.source_document_sha256,
                "captured_at": f.captured_at,
                "metadata": f.metadata,
            })
            sec["fact_count"] += 1
            if f.source_document_id:
                sec["documents"].add(f.source_document_id)
            if f.confidence > sec["top_confidence"]:
                sec["top_confidence"] = round(f.confidence, 3)

        ordered_sections: List[Dict[str, Any]] = []
        for cat in self._CATEGORY_ORDER:
            if cat in sections:
                sec = sections.pop(cat)
                sec["documents"] = sorted(sec["documents"])
                ordered_sections.append(sec)
        for cat, sec in sorted(sections.items()):
            sec["documents"] = sorted(sec["documents"])
            ordered_sections.append(sec)

        return {
            "customer_id": customer_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "fact_count": len(facts),
            "document_count": len(doc_lookup),
            "documents": [
                {"id": did, **meta} for did, meta in sorted(doc_lookup.items())
            ],
            "sections": ordered_sections,
            "filtered_to_documents": sorted(ids_set) if ids_set else None,
            "filters_applied": {k: v for k, v in (filters or {}).items() if v not in (None, "")} or None,
        }

    def run_analysis(
        self,
        customer_id: str,
        analysis_type: str,
        *,
        document_ids: Optional[Iterable[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Single dispatcher returning a normalised analysis payload.

        The supported analyses are:

        - ``customer_360``: full Customer 360 profile (alias for ``profile``).
        - ``risk_assessment``: risk score + weighted contributors.
        - ``bi_summary``: BI roll-up across categories with chart series.
        - ``describe_data``: ``describe_data_with_data`` output.
        - ``cross_document``: describe_data restricted to the provided docs
           plus a "consolidated facts" table designed for cross-document
           review.

        Each return value includes ``analysis_type``, ``customer_id``,
        ``sections`` (when applicable) and a ``download`` block enumerating
        the table rows that the export endpoint will render to CSV/XLSX/PDF.
        """
        analysis = (analysis_type or "customer_360").lower()
        options = dict(options or {})
        ids = list(document_ids) if document_ids else None
        report_filters = self._extract_report_filters(options)
        platform_context = options.get("platform_context")
        if platform_context is not None and not isinstance(platform_context, dict):
            platform_context = None

        if analysis in ("customer_360", "profile"):
            profile = self.build_customer_360(customer_id)
            return {
                "analysis_type": "customer_360",
                "customer_id": customer_id,
                "title": "Customer 360 profile",
                "profile": profile,
                "download": self._profile_to_rows(profile),
            }
        if analysis in ("risk_assessment", "risk"):
            risk = self.compute_risk_indicators(
                customer_id, platform_context=platform_context,
            )
            return {
                "analysis_type": "risk_assessment",
                "customer_id": customer_id,
                "title": "Risk assessment",
                "risk": risk,
                "download": {
                    "headers": ["factor", "value", "weight"],
                    "rows": [
                        [c.get("factor"), str(c.get("value")), c.get("weight")]
                        for c in risk.get("contributors", [])
                    ],
                    "summary": {"risk_score": risk.get("risk_score"),
                                "risk_level": risk.get("risk_level")},
                },
            }
        if analysis in ("bi_summary", "bi"):
            charts = self.build_chart_data(
                customer_id, platform_context=platform_context,
            )
            risk = self.compute_risk_indicators(
                customer_id, platform_context=platform_context,
            )
            return {
                "analysis_type": "bi_summary",
                "customer_id": customer_id,
                "title": "BI summary",
                "charts": charts,
                "risk": risk,
                "download": self._bi_to_rows(charts, risk),
            }
        if analysis in ("describe_data", "describe"):
            description = self.describe_data_with_data(
                customer_id, ids, filters=report_filters,
            )
            payload = {
                "analysis_type": "describe_data",
                "customer_id": customer_id,
                "title": "Describe data with data",
                "description": description,
                "download": self._description_to_rows(description),
            }
            self._attach_ai_narrative(payload, customer_id, options)
            return payload
        if analysis in ("cross_document", "cross_doc", "compare"):
            description = self.describe_data_with_data(
                customer_id, ids, filters=report_filters,
            )
            risk = self.compute_risk_indicators(
                customer_id, platform_context=platform_context,
            )
            payload = {
                "analysis_type": "cross_document",
                "customer_id": customer_id,
                "title": "Cross-document review",
                "description": description,
                "risk": risk,
                "download": self._description_to_rows(description),
            }
            self._attach_ai_narrative(payload, customer_id, options)
            return payload
        if analysis in ("unified", "unified_assessment"):
            return {
                "analysis_type": "unified",
                "customer_id": customer_id,
                "title": "Unified assessment",
                **self.build_unified_assessment(
                    customer_id, platform_context=platform_context,
                ),
            }
        raise ValueError(f"Unknown analysis_type: {analysis_type!r}")

    # ── Adjustable reporting + AI narrative helpers ────────────────────────

    @staticmethod
    def _extract_report_filters(options: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Pull adjustable-reporting filters out of an analysis options dict.

        Accepts either a nested ``options["filters"]`` dict or recognised
        top-level keys, so callers can pass filters whichever way is natural.
        """
        recognised = (
            "date_from", "date_to", "date_field", "fact_type", "source",
            "min_confidence", "policy_number", "provider", "product", "status",
            "product_type", "productType",
        )
        filters: Dict[str, Any] = {}
        nested = options.get("filters")
        if isinstance(nested, dict):
            for key in recognised:
                if nested.get(key) not in (None, ""):
                    filters[key] = nested[key]
        for key in recognised:
            if options.get(key) not in (None, ""):
                filters[key] = options[key]
        # ``product`` and Mislaka's ``product_type``/``productType`` are aliases
        # so a single shared filters object narrows product on both paths.
        if filters.get("product") in (None, ""):
            for alias in ("product_type", "productType"):
                if filters.get(alias) not in (None, ""):
                    filters["product"] = filters[alias]
                    break
        return filters or None

    @staticmethod
    def _ai_narrative_requested(options: Dict[str, Any]) -> bool:
        """Whether to attach the advisory AI narrative for this analysis.

        Opt-in: enabled when the caller passes ``ai_narrative``/``ai`` in
        options, or when the platform feature flag
        ``PHINS_ASSESSMENT_AI_ENABLED`` is set. Off by default so existing
        callers and response shapes are unaffected.
        """
        for key in ("ai_narrative", "ai", "include_ai_narrative"):
            val = options.get(key)
            if isinstance(val, bool) and val:
                return True
            if isinstance(val, str) and val.strip().lower() in ("1", "true", "yes", "on"):
                return True
        return str(os.environ.get("PHINS_ASSESSMENT_AI_ENABLED", "")).strip().lower() in (
            "1", "true", "yes", "on",
        )

    def _attach_ai_narrative(
        self,
        payload: Dict[str, Any],
        customer_id: str,
        options: Dict[str, Any],
    ) -> None:
        """Additively attach an advisory ``ai_narrative`` block when requested.

        Failures are swallowed so the advisory layer can never break the
        authoritative analysis response.
        """
        if not self._ai_narrative_requested(options):
            return
        try:
            from services.assessment_ai_service import get_assessment_ai_service
            payload["ai_narrative"] = get_assessment_ai_service().generate_narrative(
                payload, customer_id=customer_id, options=options,
            )
        except Exception as exc:  # noqa: BLE001 - advisory must never break analysis
            logger.warning("AI narrative attach failed for %s: %s", customer_id, exc)

    # ── Download row builders ──────────────────────────────────────────────

    @staticmethod
    def _profile_to_rows(profile: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[List[Any]] = []
        for section in ("identity",):
            for label, items in (profile.get(section) or {}).items():
                for item in items or []:
                    if isinstance(item, dict):
                        rows.append(["identity", label, json.dumps(item, ensure_ascii=False, default=str)])
                    else:
                        rows.append(["identity", label, str(item)])
        for label, items in (profile.get("contact") or {}).items():
            for item in items or []:
                rows.append(["contact", label, str(item)])
        for label, items in (profile.get("medical") or {}).items():
            for item in items or []:
                if isinstance(item, dict):
                    rows.append(["medical", label, json.dumps(item, ensure_ascii=False, default=str)])
                else:
                    rows.append(["medical", label, str(item)])
        for entry in profile.get("insurance_indicators") or []:
            rows.append(["insurance", entry.get("label", ""), str(entry.get("value", ""))])
        for entry in profile.get("savings_indicators") or []:
            rows.append(["financial", entry.get("label", ""), str(entry.get("value", ""))])
        for entry in profile.get("risk_indicators") or []:
            rows.append(["risk", "marker", str(entry)])
        for src, items in (profile.get("external_sources") or {}).items():
            for entry in items or []:
                rows.append([f"external:{src}", entry.get("label", ""), str(entry.get("value", ""))])
        return {"headers": ["category", "label", "value"], "rows": rows}

    @staticmethod
    def _description_to_rows(description: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[List[Any]] = []
        for section in description.get("sections", []):
            cat = section.get("category", "Other")
            for label, entries in (section.get("by_label") or {}).items():
                for entry in entries:
                    value = entry.get("value")
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, ensure_ascii=False, default=str)
                    rows.append([
                        cat,
                        label,
                        str(value),
                        entry.get("document_id") or "",
                        entry.get("document_type") or "",
                        entry.get("sha256") or "",
                        entry.get("confidence"),
                    ])
        return {
            "headers": ["category", "label", "value", "document_id",
                        "document_type", "sha256", "confidence"],
            "rows": rows,
        }

    @staticmethod
    def _bi_to_rows(charts: Dict[str, Any], risk: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[List[Any]] = []
        for series_name, entries in (charts.get("charts") or {}).items():
            for entry in entries or []:
                rows.append([series_name, entry.get("label"), entry.get("value")])
        for c in risk.get("contributors", []):
            rows.append(["risk_contributors", f"{c.get('factor')}:{c.get('value')}", c.get("weight")])
        return {"headers": ["series", "label", "value"], "rows": rows}

    # ── Export to CSV / XLSX / PDF ─────────────────────────────────────────

    def export_analysis(
        self,
        customer_id: str,
        analysis_type: str,
        export_format: str,
        *,
        document_ids: Optional[Iterable[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bytes, str, str]:
        """Build a downloadable representation of an analysis.

        Returns ``(bytes, mime_type, filename)``. Supported formats: ``csv``,
        ``xlsx``, ``pdf``. The CSV path uses only the standard library, the
        XLSX path uses ``openpyxl``, and the PDF path uses ``reportlab`` -
        all already required by the platform.
        """
        result = self.run_analysis(
            customer_id, analysis_type,
            document_ids=document_ids, options=options,
        )
        download = result.get("download") or {"headers": [], "rows": []}
        headers = download.get("headers") or []
        rows = download.get("rows") or []
        title = result.get("title") or analysis_type
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{customer_id}_{analysis_type}").strip("_")
        fmt = (export_format or "csv").lower()

        if fmt == "csv":
            import csv as _csv
            import io as _io
            buf = _io.StringIO()
            writer = _csv.writer(buf)
            if headers:
                writer.writerow(headers)
            truncated_rows = rows
            if len(rows) > MAX_EXPORT_ROWS:
                truncated_rows = rows[:MAX_EXPORT_ROWS]
            for row in truncated_rows:
                writer.writerow(row)
            if len(rows) > MAX_EXPORT_ROWS:
                writer.writerow([
                    f"# truncated to {MAX_EXPORT_ROWS} of {len(rows)} rows"
                ])
            payload = buf.getvalue().encode("utf-8")
            return payload, "text/csv", f"{slug}.csv"

        if fmt == "xlsx":
            try:
                from openpyxl import Workbook  # type: ignore
            except ImportError as exc:
                raise RuntimeError("openpyxl is required for XLSX export") from exc
            wb = Workbook()
            ws = wb.active
            ws.title = (analysis_type or "analysis")[:30] or "analysis"
            ws.append([title])
            ws.append([f"Customer: {customer_id}",
                       f"Generated: {datetime.utcnow().isoformat() + 'Z'}"])
            ws.append([])
            if headers:
                ws.append(headers)
            truncated_rows = rows
            row_truncated = False
            if len(rows) > MAX_EXPORT_ROWS:
                truncated_rows = rows[:MAX_EXPORT_ROWS]
                row_truncated = True
            for row in truncated_rows:
                ws.append([self._xlsx_cell(v) for v in row])
            if row_truncated:
                ws.append([])
                ws.append([
                    f"Note: only the first {MAX_EXPORT_ROWS} of {len(rows)} "
                    "rows are included in this export. Re-run with a tighter "
                    "filter (selected documents) for full coverage."
                ])
            import io as _io
            buf = _io.BytesIO()
            wb.save(buf)
            return (buf.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    f"{slug}.xlsx")

        if fmt == "pdf":
            try:
                from reportlab.lib.pagesizes import A4  # type: ignore
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore
                from reportlab.platypus import (
                    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                )  # type: ignore
                from reportlab.lib import colors  # type: ignore
                from reportlab.lib.units import mm  # type: ignore
            except ImportError as exc:
                raise RuntimeError("reportlab is required for PDF export") from exc
            import io as _io
            buf = _io.BytesIO()
            doc = SimpleDocTemplate(
                buf, pagesize=A4,
                leftMargin=14 * mm, rightMargin=14 * mm,
                topMargin=14 * mm, bottomMargin=14 * mm,
            )
            styles = getSampleStyleSheet()
            heading = ParagraphStyle("Heading", parent=styles["Title"], fontSize=15, leading=18)
            meta = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
            story: List[Any] = [
                Paragraph(self._pdf_safe(title), heading),
                Paragraph(self._pdf_safe(
                    f"Customer: {customer_id}  |  Generated: {datetime.utcnow().isoformat()}Z  |  Rows: {len(rows)}"
                ), meta),
                Spacer(1, 6),
            ]
            if headers and rows:
                truncated = [headers] + [
                    [self._pdf_safe(v, 80) for v in row] for row in rows[:300]
                ]
                table = Table(truncated, repeatRows=1)
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565c0")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cfd8dc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#f5f7fa")]),
                ]))
                story.append(table)
                if len(rows) > 300:
                    story.append(Spacer(1, 4))
                    story.append(Paragraph(
                        f"Showing first 300 of {len(rows)} rows. Export to CSV/XLSX for full data.",
                        meta,
                    ))
            else:
                story.append(Paragraph("No tabular data available for this analysis.", meta))
            doc.build(story)
            return buf.getvalue(), "application/pdf", f"{slug}.pdf"

        raise ValueError(f"Unsupported export_format: {export_format!r}")

    @staticmethod
    def _xlsx_cell(value: Any) -> Any:
        if isinstance(value, (str, int, float)) or value is None:
            return value
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    @staticmethod
    def _pdf_safe(value: Any, max_length: Optional[int] = None) -> str:
        if value is None:
            text = ""
        elif isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                text = str(value)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if max_length and len(text) > max_length:
            text = text[: max_length - 1] + "…"
        return text

    def get_document_assessments(self, document_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Return per-document summary derived from the unified fact store.

        For each requested ``document_id`` we report how many facts were
        extracted, the breakdown by ``fact_type`` and the highest fact
        confidence. The result is keyed by ``document_id`` so callers can
        attach it directly to existing document listing payloads.
        """
        wanted = {d for d in document_ids if d}
        if not wanted:
            return {}
        with self._lock:
            all_facts = [f for facts in self._facts.values() for f in facts]
        out: Dict[str, Dict[str, Any]] = {d: {
            "facts_extracted": 0,
            "by_type": {},
            "top_confidence": 0.0,
            "customer_id": "",
        } for d in wanted}
        for f in all_facts:
            if f.source_document_id not in wanted:
                continue
            entry = out[f.source_document_id]
            entry["facts_extracted"] += 1
            entry["by_type"][f.fact_type] = entry["by_type"].get(f.fact_type, 0) + 1
            if f.confidence > entry["top_confidence"]:
                entry["top_confidence"] = round(f.confidence, 3)
            if not entry["customer_id"]:
                entry["customer_id"] = f.customer_id
        return out

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
                "documents": _build_integrity_doc_list(facts),
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

    @staticmethod
    def _row_status_lower(row: Any) -> str:
        if not isinstance(row, dict):
            return ""
        return str(row.get("status") or "").strip().lower().replace(" ", "_")

    @staticmethod
    def _truthy_smoking(value: Any) -> bool:
        """Return True only when the UW smoking field clearly indicates smoking.

        Accepts English labels and Hebrew smoking phrases (``מעשן`` / ``עישון``)
        via the shared Hebrew lexicon so platform-context signals from IL
        underwriting forms are not silently ignored.
        """
        if value is True:
            return True
        if value is False or value is None:
            return False
        text = str(value).strip()
        if not text:
            return False
        try:
            from services.hebrew_assessment_lexicon import is_truthy_smoking_hebrew
            if is_truthy_smoking_hebrew(text):
                return True
            # Explicit Hebrew/English negatives short-circuit before the
            # English allow-list so "לא מעשן" never becomes a smoker signal.
            from services.hebrew_assessment_lexicon import smoking_status_from_hebrew
            he_status = smoking_status_from_hebrew(text)
            if he_status in ("never", "former"):
                return False
        except ImportError:
            pass
        lowered = text.lower()
        if lowered in ("false", "0", "no", "none", "never", "non-smoker",
                       "nonsmoker", "non_smoker", "former", "former_smoker",
                       "former smoker", "ex-smoker", "ex_smoker"):
            return False
        return lowered in ("true", "1", "yes", "y", "smoker", "current",
                           "current_smoker", "smoking", "active")

    def compute_risk_indicators(
        self,
        customer_id: str,
        *,
        profile: Optional[Dict[str, Any]] = None,
        platform_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Derive a deterministic risk score from the unified fact store.

        When ``platform_context`` is provided, evidence-based adjustments from
        real policies/claims/underwriting/billing rows are layered on top.
        Scores are never invented — every contributor cites concrete evidence.
        """
        if profile is None:
            profile = self.build_customer_360(customer_id)
        score = 0.0
        contributors: List[Dict[str, Any]] = []
        sources: List[str] = []

        if profile.get("fact_count", 0) > 0:
            sources.append("fact_store")

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
            # Hebrew (and English) disability % from structured form fields.
            if label == "disability_percentage" and value is not None and value > 50:
                score += 0.15
                contributors.append({
                    "factor": "disability_percentage",
                    "value": value,
                    "weight": 0.15,
                })

        # External policy load - many policies but no recent updates raise risk
        external_total = sum(len(rows) for rows in profile["external_sources"].values())
        if external_total >= 6:
            score += 0.05
            contributors.append({"factor": "external_policy_count", "value": external_total, "weight": 0.05})

        platform_signals_applied = False
        ctx = platform_context if isinstance(platform_context, dict) else None
        if ctx:
            policies = [p for p in (ctx.get("policies") or []) if isinstance(p, dict)]
            claims = [c for c in (ctx.get("claims") or []) if isinstance(c, dict)]
            underwriting = [u for u in (ctx.get("underwriting") or []) if isinstance(u, dict)]
            billing = [b for b in (ctx.get("billing") or []) if isinstance(b, dict)]

            if policies:
                sources.append("policies")
            if claims:
                sources.append("claims")
            if underwriting:
                sources.append("underwriting")
            if billing:
                sources.append("billing")

            pending_boost = 0.0
            for claim in claims:
                st = self._row_status_lower(claim)
                if st in ("pending", "under_review"):
                    add = 0.08
                    if pending_boost + add > 0.24:
                        add = max(0.0, 0.24 - pending_boost)
                    if add <= 0:
                        continue
                    pending_boost += add
                    score += add
                    platform_signals_applied = True
                    contributors.append({
                        "factor": "pending_claim",
                        "value": claim.get("id") or claim.get("claim_id") or st,
                        "weight": round(add, 3),
                        "source": "claims",
                    })

            denied_boost = 0.0
            for claim in claims:
                st = self._row_status_lower(claim)
                if st in ("denied", "rejected"):
                    add = 0.05
                    if denied_boost + add > 0.15:
                        add = max(0.0, 0.15 - denied_boost)
                    if add <= 0:
                        continue
                    denied_boost += add
                    score += add
                    platform_signals_applied = True
                    contributors.append({
                        "factor": "denied_claim",
                        "value": claim.get("id") or claim.get("claim_id") or st,
                        "weight": round(add, 3),
                        "source": "claims",
                    })

            active_policies = [
                p for p in policies
                if self._row_status_lower(p) in ("active", "approved")
            ]
            if claims and not active_policies:
                score += 0.10
                platform_signals_applied = True
                contributors.append({
                    "factor": "no_active_policy_with_claims",
                    "value": {"claims": len(claims), "active_policies": 0},
                    "weight": 0.10,
                    "source": "policies",
                })

            rejected_uw = False
            for app in underwriting:
                st = self._row_status_lower(app)
                if st in ("rejected", "declined"):
                    rejected_uw = True
                    break
            if rejected_uw:
                score += 0.12
                platform_signals_applied = True
                contributors.append({
                    "factor": "uw_rejected",
                    "value": "rejected_or_declined",
                    "weight": 0.12,
                    "source": "underwriting",
                })

            # High-risk UW fields — apply once per signal type using only
            # fields that are actually present on an application.
            uw_bmi_applied = False
            uw_smoking_applied = False
            uw_disability_applied = False
            for app in underwriting:
                if not uw_disability_applied and "disability_percentage" in app:
                    try:
                        disability_pct = float(app.get("disability_percentage"))
                    except (TypeError, ValueError):
                        disability_pct = None
                    if disability_pct is not None and disability_pct > 50:
                        # Align with hypertension-class medical weight (0.15).
                        score += 0.15
                        platform_signals_applied = True
                        uw_disability_applied = True
                        contributors.append({
                            "factor": "uw_disability_percentage",
                            "value": disability_pct,
                            "weight": 0.15,
                            "source": "underwriting",
                        })
                if not uw_smoking_applied and ("smoking" in app or "smoking_status" in app):
                    smoking_val = app["smoking"] if "smoking" in app else app.get("smoking_status")
                    if self._truthy_smoking(smoking_val):
                        # Align with blood-pressure lifestyle weight (0.10).
                        score += 0.10
                        platform_signals_applied = True
                        uw_smoking_applied = True
                        contributors.append({
                            "factor": "uw_smoking",
                            "value": smoking_val,
                            "weight": 0.10,
                            "source": "underwriting",
                        })
                if not uw_bmi_applied and "bmi" in app:
                    try:
                        bmi_val = float(app.get("bmi"))
                    except (TypeError, ValueError):
                        bmi_val = None
                    if bmi_val is not None and bmi_val >= 35:
                        score += 0.18
                        platform_signals_applied = True
                        uw_bmi_applied = True
                        contributors.append({
                            "factor": "uw_bmi",
                            "value": bmi_val,
                            "weight": 0.18,
                            "source": "underwriting",
                        })
                    elif bmi_val is not None and bmi_val >= 30:
                        score += 0.10
                        platform_signals_applied = True
                        uw_bmi_applied = True
                        contributors.append({
                            "factor": "uw_bmi",
                            "value": bmi_val,
                            "weight": 0.10,
                            "source": "underwriting",
                        })

            overdue_boost = 0.0
            for bill in billing:
                st = self._row_status_lower(bill)
                if st in ("overdue", "past_due"):
                    add = 0.04
                    if overdue_boost + add > 0.12:
                        add = max(0.0, 0.12 - overdue_boost)
                    if add <= 0:
                        continue
                    overdue_boost += add
                    score += add
                    platform_signals_applied = True
                    contributors.append({
                        "factor": "overdue_bill",
                        "value": bill.get("id") or bill.get("bill_id") or st,
                        "weight": round(add, 3),
                        "source": "billing",
                    })

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
            "scale": "0-1",
            "platform_signals_applied": platform_signals_applied,
            "sources": sources,
        }

    def build_unified_assessment(
        self,
        customer_id: str,
        *,
        platform_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a joined Customer 360 + risk + charts assessment payload."""
        profile = self.build_customer_360(customer_id)
        risk = self.compute_risk_indicators(
            customer_id, profile=profile, platform_context=platform_context,
        )
        charts = self.build_chart_data(
            customer_id, platform_context=platform_context,
        )
        return {
            "customer_id": customer_id,
            "profile": profile,
            "risk": risk,
            "charts": charts,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "integrity": {
                "fact_count": profile.get("fact_count", 0),
                "documents_with_facts": len(
                    (profile.get("data_integrity") or {}).get("documents") or []
                ),
                "platform_signals_applied": bool(
                    risk.get("platform_signals_applied")
                ),
            },
        }

    def build_chart_data(
        self,
        customer_id: str,
        *,
        platform_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Produce chart-ready data series for the customer dashboards.

        The returned payload is intentionally framework-agnostic: every chart is
        described as a list of ``{label, value}`` pairs so the frontend can
        render with whichever charting library is in use.
        """
        profile = self.build_customer_360(customer_id)
        risk = self.compute_risk_indicators(
            customer_id, profile=profile, platform_context=platform_context,
        )

        condition_counts: Dict[str, int] = {}
        for cond in profile["medical"]["conditions"]:
            condition_counts[cond] = condition_counts.get(cond, 0) + 1

        external_counts = {
            src: len(rows) for src, rows in profile["external_sources"].items()
        }

        savings_total = 0.0
        savings_series: List[Dict[str, Any]] = []
        for ind in profile["savings_indicators"]:
            if isinstance(ind["value"], bool):
                continue
            try:
                amount = float(ind["value"]) if not isinstance(ind["value"], dict) else float(ind["value"].get("amount", 0))
            except (TypeError, ValueError):
                continue
            savings_total += amount
            savings_series.append({"label": ind.get("label", "savings"), "value": amount})

        coverage_series: List[Dict[str, Any]] = []
        for ind in profile["insurance_indicators"]:
            if isinstance(ind["value"], bool):
                continue
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

    def import_customer_pack(self, pack: Dict[str, Any], customer_id_override: Optional[str] = None) -> Dict[str, Any]:
        """Re-import a previously exported customer pack with integrity check."""
        if not isinstance(pack, dict) or "facts" not in pack:
            raise ValueError("Invalid customer pack payload")
        verifier = dict(pack)
        digest = verifier.pop("sha256", None)
        recomputed = hashlib.sha256(
            json.dumps(verifier, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        integrity = digest == recomputed
        cust = (customer_id_override or str(pack.get("customer_id") or "")).strip()
        if not cust:
            raise ValueError("customer_id required in pack")
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
            doc_svc = self.document_service
            if mime.startswith("text/") or ext in (".csv", ".txt", ".json", ".xml", ".html", ".htm"):
                return raw_bytes.decode("utf-8", errors="replace")[:MAX_TEXT_SCAN]
            lang_hint = (
                record.get("original_file_name")
                or record.get("file_name")
                or ""
            )
            if mime == "application/pdf" or ext == ".pdf":
                pdf_helper = getattr(doc_svc, "_extract_pdf_text", None)
                if callable(pdf_helper):
                    try:
                        return pdf_helper(raw_bytes, lang_hint=lang_hint)[:MAX_TEXT_SCAN]
                    except TypeError:
                        return pdf_helper(raw_bytes)[:MAX_TEXT_SCAN]
                return raw_bytes.decode("latin-1", errors="replace")[:MAX_TEXT_SCAN]
            if mime.startswith("image/") or ext in (".png", ".jpg", ".jpeg",
                                                    ".tiff", ".bmp", ".gif", ".webp"):
                # OCR the image (Hebrew + English + Arabic) so scanned ID
                # cards / handwritten labels / photographed receipts
                # always feed real text into the assessment center.
                ocr_helper = getattr(doc_svc, "_ocr_image_bytes", None)
                if callable(ocr_helper):
                    try:
                        return (ocr_helper(raw_bytes, lang_hint=lang_hint) or "")[:MAX_TEXT_SCAN]
                    except TypeError:
                        return (ocr_helper(raw_bytes) or "")[:MAX_TEXT_SCAN]
                return ""
            if ext in (".xlsx", ".xls"):
                xlsx_helper = getattr(doc_svc, "_extract_spreadsheet_summary", None)
                if callable(xlsx_helper):
                    return (xlsx_helper(raw_bytes, ext) or "")[:MAX_TEXT_SCAN]
                return ""
            if ext == ".zip" or mime == "application/zip":
                # Walk the zip and concatenate text from every supported
                # entry so customers can upload a folder of mixed
                # documents (ID + medical + financial) in one go.
                zip_helper = getattr(doc_svc, "_extract_zip_contents", None)
                if callable(zip_helper):
                    return (zip_helper(raw_bytes) or "")[:MAX_TEXT_SCAN]
                return ""
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

        for match in _NAME_RE.finditer(text):
            value = match.group(1).strip().rstrip(",.;:")
            if value:
                facts.append(_make_fact(customer_id, "identity", "full_name", value,
                                        document_id, sha256, source, 0.65))

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
        try:
            from services.hebrew_assessment_lexicon import is_clinically_negated as _clin_neg
        except ImportError:
            def _clin_neg(_t: str, _s: int) -> bool:  # type: ignore
                return False
        for cond in _MEDICAL_CONDITIONS:
            idx = lower.find(cond)
            if idx < 0:
                continue
            # Skip when Hebrew/English negation precedes the term so mixed
            # IL forms ("שלילי ל-HIV", "negative for diabetes") stay clean.
            if _clin_neg(text, idx) or _clin_neg(lower, idx):
                continue
            facts.append(_make_fact(customer_id, "medical_condition", cond, cond,
                                    document_id, sha256, source, 0.75))
        for med in _MEDICATIONS:
            idx = lower.find(med)
            if idx < 0:
                continue
            if _clin_neg(text, idx) or _clin_neg(lower, idx):
                continue
            facts.append(_make_fact(customer_id, "medication", med, med,
                                    document_id, sha256, source, 0.80))
        for allergy in _ALLERGIES:
            idx = lower.find(allergy)
            if idx < 0:
                continue
            if _clin_neg(text, idx) or _clin_neg(lower, idx):
                continue
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

        matched_insurance: List[str] = []
        for keyword in sorted(_INSURANCE_KEYWORDS, key=len, reverse=True):
            if keyword in lower:
                if any(keyword in longer for longer in matched_insurance):
                    continue
                matched_insurance.append(keyword)
                amount = _amount_near(text, keyword)
                if amount is not None:
                    facts.append(_make_fact(customer_id, "insurance", keyword, amount,
                                            document_id, sha256, source, 0.70))
                else:
                    facts.append(_make_fact(customer_id, "insurance", keyword, True,
                                            document_id, sha256, source, 0.55))

        matched_savings: List[str] = []
        for keyword in sorted(_SAVINGS_KEYWORDS, key=len, reverse=True):
            if keyword in lower:
                if any(keyword in longer for longer in matched_savings):
                    continue
                matched_savings.append(keyword)
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

        # Hebrew / mixed-language documents: map Hebrew clinical, insurance,
        # savings and risk phrases onto the same English canonical keys the
        # rest of the scoring pipeline already understands. Original Hebrew
        # surface forms are preserved in metadata.raw_match for audit.
        facts.extend(self._extract_hebrew_facts(
            text=text,
            customer_id=customer_id,
            document_id=document_id,
            sha256=sha256,
            source=source,
        ))

        return facts

    def _extract_hebrew_facts(
        self,
        *,
        text: str,
        customer_id: str,
        document_id: Optional[str],
        sha256: Optional[str],
        source: str,
    ) -> List[Fact]:
        """Mine Assessment Center facts from Hebrew (and mixed) document text.

        Returns an empty list when the text has no Hebrew characters so the
        English-only path pays no overhead. Never raises into the caller.
        """
        try:
            from services.hebrew_assessment_lexicon import (
                contains_hebrew,
                extract_hebrew_matches,
            )
        except ImportError:
            return []
        try:
            if not contains_hebrew(text):
                return []
            matches = extract_hebrew_matches(text)
        except Exception as exc:
            logger.warning("Hebrew fact extraction failed (non-fatal): %s", exc)
            return []

        # Collapse within this pass; cross-pass dedup (English + Hebrew both
        # emitting ``medical_condition/diabetes``) is handled by _store_facts.
        seen_local: set = set()
        out: List[Fact] = []
        for match in matches:
            key = (match.fact_type, match.canonical)
            if key in seen_local:
                continue
            seen_local.add(key)

            value: Any
            if match.amount is not None and match.fact_type in (
                "insurance", "savings", "vital_sign",
            ):
                value = match.amount
            elif match.fact_type == "insurance" and match.canonical == "policy_number":
                value = match.metadata.get("policy_number") or match.raw_match
            elif match.fact_type == "insurance" and match.canonical == "provider":
                value = match.metadata.get("provider") or match.raw_match
            elif match.fact_type in ("insurance", "savings") and match.amount is None:
                # Best-effort: look for a ₪ amount near the Hebrew phrase.
                amount = _amount_near(text, match.raw_match)
                value = amount if amount is not None else True
            else:
                value = match.canonical

            meta = dict(match.metadata or {})
            meta.setdefault("lang", "he")
            meta.setdefault("raw_match", match.raw_match)
            meta["extractor"] = "hebrew_assessment_lexicon"

            out.append(_make_fact(
                customer_id, match.fact_type, match.canonical, value,
                document_id, sha256, source, match.confidence,
                metadata=meta,
            ))
        return out

    def _snapshot_hebrew_assessment(
        self,
        *,
        customer_id: str,
        document_id: Optional[str],
        hebrew_fact_count: int,
        language: Optional[str],
    ) -> None:
        """Persist a customer_risk assessment driven by Hebrew document facts.

        Best-effort and never fatal: a durable-write failure must not break
        document ingestion. The snapshot uses the same risk engine as the
        English path so Hebrew and English evidence share one scoring model.
        """
        try:
            from services.assessment_record_service import get_assessment_record_service
        except ImportError:
            return
        try:
            risk = self.compute_risk_indicators(customer_id)
            get_assessment_record_service().record_assessment(
                subject_type="customer",
                subject_id=customer_id,
                assessment_type="customer_risk",
                customer_id=customer_id,
                score=risk.get("risk_score"),
                level=risk.get("risk_level"),
                recommendation=None,
                details={
                    "source_document_id": document_id,
                    "document_language": language or "he",
                    "hebrew_facts": hebrew_fact_count,
                    "contributors": risk.get("contributors") or [],
                    "trigger": "hebrew_document_assessment",
                },
                engine="assessment_center+hebrew_lexicon",
                engine_version="he-rules-1.0.0",
            )
        except Exception as exc:
            logger.warning(
                "Hebrew assessment record snapshot failed (non-fatal): %s", exc,
            )

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
            # Bound the per-customer fact list so a runaway document or a
            # malicious upload can't blow the process memory budget. We keep
            # the most recent facts and discard the oldest beyond the cap.
            if len(existing) > MAX_FACTS_PER_CUSTOMER:
                drop = len(existing) - MAX_FACTS_PER_CUSTOMER
                logger.warning(
                    "Trimming %d oldest facts for %s (capped at %d)",
                    drop, customer_id, MAX_FACTS_PER_CUSTOMER,
                )
                self._facts[customer_id] = existing[-MAX_FACTS_PER_CUSTOMER:]
                existing = self._facts[customer_id]
            self._persist_customer(customer_id, existing)

    @staticmethod
    def _facts_checksum(fact_dicts: List[Dict[str, Any]]) -> str:
        """Deterministic SHA-256 over the serialized fact list (tamper evidence)."""
        canonical = json.dumps(
            fact_dicts, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _persist_customer(self, customer_id: str, facts: List[Fact]) -> None:
        """Persist a customer's facts atomically, encrypted at rest.

        The payload (which contains PII: identity numbers, medical conditions,
        IBANs) is wrapped in a vault envelope: Fernet-encrypted when
        ``PHINS_ENCRYPTION_KEY`` is configured, plain-scheme otherwise so
        development and test environments keep working without a key. A
        ``facts_sha256`` checksum inside the payload provides tamper evidence
        that is verified on load. Legacy plaintext files remain readable and
        are transparently upgraded on the next save.
        """
        try:
            safe_cid = re.sub(r"[^A-Za-z0-9_-]", "_", customer_id)[:80] or "anonymous"
            target = os.path.join(self._fact_store_dir, f"{safe_cid}.json")
            fact_dicts = [f.to_dict() for f in facts]
            payload = {
                "customer_id": customer_id,
                "saved_at": datetime.utcnow().isoformat() + "Z",
                "facts": fact_dicts,
                "facts_sha256": self._facts_checksum(fact_dicts),
            }
            try:
                from security.vault import encrypt_json
                blob = encrypt_json(payload)
                envelope = {
                    "format": FACT_STORE_FORMAT_V2,
                    "scheme": blob.scheme,
                    "ciphertext": blob.ciphertext,
                }
            except ImportError:  # pragma: no cover - vault ships with the repo
                envelope = payload
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, ensure_ascii=False, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except Exception as exc:
            logger.warning("Assessment fact persistence failed for %s: %s", customer_id, exc)

    @staticmethod
    def _decode_fact_file(payload: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
        """Decode a fact-store file: v2 vault envelope or legacy plaintext.

        Returns the inner payload dict, or ``None`` when the file cannot be
        decoded (e.g. encrypted with a missing/rotated key). The file itself is
        never deleted on decode failure so data can be recovered once the
        correct ``PHINS_ENCRYPTION_KEY`` is restored.
        """
        if payload.get("format") == FACT_STORE_FORMAT_V2 and "ciphertext" in payload:
            from security.vault import decrypt_json
            inner = decrypt_json(json.dumps({
                "scheme": payload.get("scheme", "plain"),
                "ciphertext": payload.get("ciphertext", ""),
            }))
            if not isinstance(inner, dict):
                logger.error(
                    "Cannot decrypt assessment fact file %s (missing or rotated "
                    "PHINS_ENCRYPTION_KEY?). File left intact for recovery.",
                    path,
                )
                return None
            expected = inner.get("facts_sha256")
            if expected:
                actual = AssessmentCenterService._facts_checksum(
                    inner.get("facts", [])
                )
                if actual != expected:
                    logger.error(
                        "Integrity checksum mismatch for assessment fact file "
                        "%s (expected %s, got %s). Loading anyway; investigate "
                        "possible corruption or tampering.",
                        path, expected[:16], actual[:16],
                    )
            return inner
        # Legacy plaintext payload ({"customer_id": ..., "facts": [...]}).
        return payload

    def _load_from_disk(self) -> None:
        try:
            if not os.path.isdir(self._fact_store_dir):
                return
            entries = sorted(os.listdir(self._fact_store_dir))
            if len(entries) > MAX_FACTS_LOAD_FILES:
                logger.warning(
                    "Assessment fact store has %d entries; only loading the "
                    "first %d on cold start to keep boot time predictable. "
                    "Older customers will hydrate on first read.",
                    len(entries), MAX_FACTS_LOAD_FILES,
                )
                entries = entries[:MAX_FACTS_LOAD_FILES]
            for name in entries:
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self._fact_store_dir, name)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        raw_payload = json.load(fh)
                    payload = self._decode_fact_file(raw_payload, path)
                    if payload is None:
                        continue
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


def _make_fact(
    customer_id, fact_type, label, value, doc_id, sha, source, confidence,
    metadata: Optional[Dict[str, Any]] = None,
) -> Fact:
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
        metadata=dict(metadata) if metadata else {},
    )


def _hashable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def _build_integrity_doc_list(facts) -> list:
    """Return a sorted list of document-object dicts for data_integrity.documents."""
    doc_map: Dict[str, Dict[str, str]] = {}
    for f in facts:
        if not f.source_document_id:
            continue
        if f.source_document_id not in doc_map:
            doc_map[f.source_document_id] = {
                "id": f.source_document_id,
                "sha256": f.source_document_sha256 or "",
            }
        elif f.source_document_sha256 and not doc_map[f.source_document_id].get("sha256"):
            doc_map[f.source_document_id]["sha256"] = f.source_document_sha256
    return sorted(doc_map.values(), key=lambda d: d["id"])


def _id_number_view(fact: Fact) -> Dict[str, Any]:
    return {
        "value": fact.value,
        "country": fact.metadata.get("country", ""),
        "id_type": fact.metadata.get("id_type", ""),
        "confidence": fact.confidence,
        "source_document_id": fact.source_document_id,
    }


def _amount_near(text: str, keyword: str) -> Optional[float]:
    """Look for a monetary amount within 80 characters of ``keyword``.

    Searches near *all* occurrences of the keyword and returns the largest
    amount found.
    """
    lower = text.lower()
    best: Optional[float] = None
    start = 0
    while True:
        idx = lower.find(keyword, start)
        if idx < 0:
            break
        window = text[max(0, idx - 40): idx + len(keyword) + 80]
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
        start = idx + len(keyword)
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


# Alias used by the customer AI report and other call sites.
get_assessment_center_service = get_assessment_center


def reset_assessment_center() -> None:
    """Reset the singleton (used by the test harness)."""
    global _default_service
    with _default_lock:
        if _default_service is not None:
            _default_service.reset()
        _default_service = None
