"""
PHINS Hebrew Assessment Lexicon
================================

Canonical Hebrew → English term maps used by the Assessment Center to mine
facts from Hebrew (and mixed Hebrew/English) insurance, medical, and financial
documents — then feed the same score → decision loop as English text.

Design rules (data integrity):

1. **Canonical English values.** Facts store English keys
   (``diabetes``, ``premium``, ``smoker``) so ``compute_risk_indicators`` and
   underwriting scoring keep working without parallel Hebrew weight tables.
   The original Hebrew match is preserved in ``metadata.raw_match``.
2. **Longest-match-first.** Multi-word Hebrew phrases are preferred over
   shorter substrings (e.g. ``יתר לחץ דם`` before ``לחץ דם``).
3. **Negation-aware for clinical terms.** Matches preceded by ``אין`` /
   ``ללא`` / ``שלילי ל`` / ``לא מאובחן`` within a short window are skipped so
   "אין סוכרת" does not invent a diabetes fact.
4. **Advisory / additive only.** This module never mutates documents or posts
   money decisions; it only proposes fact candidates for the Assessment Center.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Hebrew Unicode block (basic + presentation forms used by some OCR engines).
_HEBREW_RE = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")

# Negation window before a clinical keyword (characters).
_NEGATION_WINDOW = 28
_NEGATION_PATTERNS = (
    re.compile(r"אין\s*$"),
    re.compile(r"ללא\s*$"),
    re.compile(r"לא\s+מאובחן\w*\s*$"),
    # Allow optional hyphen after ל (OCR: "שלילי ל-HIV").
    re.compile(r"שלילי(?:ת)?\s+(?:ל|עבור)?-?\s*$"),
    re.compile(r"ללא\s+עדות\s+(?:ל)?\s*$"),
    re.compile(r"אין\s+עדות\s+(?:ל)?\s*$"),
    re.compile(r"לא\s+סובל\w*\s+(?:מ)?\s*$"),
    re.compile(r"ללא\s+היסטוריה\s+(?:של)?\s*$"),
    re.compile(r"הכחשה\s+(?:של)?\s*$"),
    re.compile(r"שולל(?:ת)?\s*$"),
)

# English clinical negation (mixed-language IL forms often say "negative for HIV").
_EN_NEGATION_PATTERNS = (
    re.compile(
        r"(?:no\s+evidence\s+of|no\s+history\s+of|denies|denied|"
        r"negative\s+for|not\s+diagnosed\s+with|without|rule[sd]\s+out)\s*$",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class HebrewMatch:
    """One lexicon hit ready to become an Assessment Center Fact."""

    fact_type: str
    canonical: str          # English key stored as fact.value / fact.label
    raw_match: str          # Original Hebrew (or mixed) surface form
    confidence: float
    amount: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Lexicon tables: Hebrew phrase → canonical English ────────────────────────
# Longer phrases MUST appear before their shorter substrings in each category
# because matching is longest-first within a category.

MEDICAL_CONDITIONS_HE: Tuple[Tuple[str, str], ...] = (
    ("מחלת ריאות חסימתית כרונית", "copd"),
    ("מחלת לב כלילית", "coronary"),
    ("מחלת לב איסכמית", "coronary"),
    ("אוטם שריר הלב", "myocardial"),
    ("אי ספיקת כליות", "renal failure"),
    ("כשל כלייתי כרוני", "chronic kidney"),
    ("מחלת כליות כרונית", "chronic kidney"),
    ("מחלת כבד", "liver disease"),
    ("דלקת כבד", "hepatitis"),
    ("יתר לחץ דם", "hypertension"),
    ("לחץ דם גבוה", "hypertension"),
    ("מחלת לב", "heart disease"),
    ("אי ספיקת לב", "heart disease"),
    ("הפרעת קצב", "arrhythmia"),
    ("סוכרת סוג 2", "diabetes"),
    ("סוכרת סוג 1", "diabetes"),
    ("סוכרת נעורים", "diabetes"),
    ("סוכרת", "diabetes"),
    ("אסתמה", "asthma"),
    ("אסטמה", "asthma"),
    ("סרטן", "cancer"),
    ("ממאירות", "cancer"),
    ("גידול ממאיר", "tumor"),
    ("גידול", "tumor"),
    ("שבץ מוחי", "stroke"),
    ("אירוע מוחי", "stroke"),
    ("שבץ", "stroke"),
    ("אפילפסיה", "epilepsy"),
    ("דיכאון", "depression"),
    ("חרדה", "anxiety"),
    ("סכיזופרניה", "schizophrenia"),
    ("איידס", "aids"),
    ("HIV", "hiv"),
    ("hiv", "hiv"),
    ("שחפת", "tuberculosis"),
    ("השמנת יתר", "obesity"),
    ("השמנה", "obesity"),
    ("אנמיה", "anemia"),
    ("אלצהיימר", "alzheimer"),
    ("פרקינסון", "parkinson"),
    ("זאבת", "lupus"),
    ("דלקת מפרקים", "arthritis"),
    ("נכות", "disability"),
)

MEDICATIONS_HE: Tuple[Tuple[str, str], ...] = (
    ("מטפורמין", "metformin"),
    ("אינסולין", "insulin"),
    ("אטורבסטטין", "atorvastatin"),
    ("ליסינופריל", "lisinopril"),
    ("אמלודיפין", "amlodipine"),
    ("וורפרין", "warfarin"),
    ("אספירין", "aspirin"),
    ("קלופידוגרל", "clopidogrel"),
    ("אומפרזול", "omeprazole"),
    ("לבותירוקסין", "levothyroxine"),
    ("ונטולין", "ventolin"),
    ("סאלבוטמול", "albuterol"),
    ("סלבוטמול", "albuterol"),
    ("פלואוקסטין", "fluoxetine"),
    ("סרטרלין", "sertraline"),
    ("ציטאלופרם", "citalopram"),
    ("מורפין", "morphine"),
    ("טרמדול", "tramadol"),
    ("איבופרופן", "ibuprofen"),
    ("פרצטמול", "paracetamol"),
    ("אצטמינופן", "acetaminophen"),
    ("טמוקסיפן", "tamoxifen"),
    ("כימותרפיה", "chemotherapy"),
    ("הקרנות", "radiotherapy"),
)

ALLERGIES_HE: Tuple[Tuple[str, str], ...] = (
    ("אלרגיה לפניצילין", "penicillin"),
    ("רגישות לפניצילין", "penicillin"),
    ("פניצילין", "penicillin"),
    ("אלרגיה לבוטנים", "peanut"),
    ("בוטנים", "peanut"),
    ("אלרגיה ללטקס", "latex"),
    ("לטקס", "latex"),
    ("פירות ים", "shellfish"),
    ("יוד", "iodine"),
    ("סולפה", "sulfa"),
    ("רגישות לאספירין", "aspirin allergy"),
    ("אלרגיה לביצים", "egg allergy"),
    ("אי סבילות ללקטוז", "lactose intolerance"),
    ("לקטוז", "lactose intolerance"),
)

INSURANCE_HE: Tuple[Tuple[str, str], ...] = (
    ("סכום ביטוח", "sum insured"),
    ("סכום כיסוי", "cover amount"),
    ("סכום מבוטח", "sum insured"),
    ("השתתפות עצמית", "deductible"),
    ("מספר פוליסה", "policy number"),
    ("ביטוח חיים", "life insurance"),
    ("ביטוח בריאות", "health insurance"),
    ("ביטוח מנהלים", "managers insurance"),
    ("ביטוח משכנתא", "mortgage insurance"),
    ("אובדן כושר עבודה", "disability insurance"),
    ("ביטוח סיעודי", "long term care"),
    ("קרן השתלמות", "education fund"),
    ("קופת גמל", "provident"),
    ("קרן פנסיה", "pension"),
    ("פרמיה חודשית", "premium"),
    ("פרמיה", "premium"),
    ("כיסוי", "coverage"),
    ("מוטב", "beneficiary"),
    ("מבוטח", "insured"),
    ("תביעה", "claim"),
    ("חידוש", "renewal"),
    ("פוליסה", "policy number"),
    ("סיעוד", "long term care"),
    ("פנסיה", "pension"),
)

SAVINGS_HE: Tuple[Tuple[str, str], ...] = (
    ("קרן השתלמות", "education fund"),
    ("קופת גמל", "provident"),
    ("קרן פנסיה", "pension"),
    ("דמי ניהול", "management fees"),
    ("צבירה", "accumulated"),
    ("יתרה", "balance"),
    ("הפקדה", "deposit"),
    ("הפקדות", "contribution"),
    ("משיכה", "withdrawal"),
    ("תגמולים", "contribution"),
    ("פיצויים", "severance"),
    ("ריבית", "interest"),
    ("דיבידנד", "dividend"),
    ("תשואה", "yield"),
    ("פנסיה", "pension"),
)

RISK_HE: Tuple[Tuple[str, str], ...] = (
    ("סיכון גבוה מאוד", "very high risk"),
    ("סיכון מוגבר", "elevated risk"),
    ("סיכון גבוה", "high risk"),
    ("סיכון נמוך", "low risk"),
    ("שלב 4", "stage 4"),
    ("סופני", "terminal"),
    ("קריטי", "critical"),
    ("קטלני", "fatal"),
    ("נדחה", "denied"),
    ("הונאה", "fraud"),
    ("חשוד", "suspicious"),
    ("אי גילוי", "non-disclosure"),
    ("הסתרת מידע", "non-disclosure"),
)

# Canonical values are English risk-indicator labels so
# compute_risk_indicators' marker weights apply (``smoker`` → 0.10).
SMOKING_HE: Tuple[Tuple[str, str], ...] = (
    ("לשעבר מעשן", "former smoker"),
    ("לשעבר מעשנת", "former smoker"),
    ("מעשן לשעבר", "former smoker"),
    ("מעשנת לשעבר", "former smoker"),
    ("עישון כבד", "smoker"),
    ("מעשן", "smoker"),
    ("מעשנת", "smoker"),
    ("עישון", "smoker"),
)

# Status terms only — numeric % is captured by STRUCTURED_FIELD_PATTERNS
# as vital_sign/disability_percentage so scoring can read the amount.
DISABILITY_HE: Tuple[Tuple[str, str], ...] = (
    ("נכות צמיתה", "disability"),
    ("אובדן כושר עבודה", "disability"),
    ("מוגבלות", "disability"),
    ("סיעודי", "disability"),
    ("נכות", "disability"),
)

# Structured Hebrew field patterns (amounts / dates / IDs on labeled forms).
# Group 1 is the captured value.
STRUCTURED_FIELD_PATTERNS: Tuple[Tuple[str, str, str, float], ...] = (
    # (fact_type, canonical_label, regex, confidence)
    ("insurance", "policy_number",
     r"מספר\s*פוליס[הא][\s:]*([0-9\-/]+)", 0.92),
    ("insurance", "policy_number",
     r"פוליס[הא]\s*מס[פ']?[\s:]*([0-9\-/]+)", 0.90),
    ("insurance", "premium",
     r"פרמי[הא](?:\s*חודשית)?[\s:]*[₪$]?\s*([0-9,\.]+)", 0.90),
    ("insurance", "premium",
     r"תשלום\s*חודשי[\s:]*[₪$]?\s*([0-9,\.]+)", 0.88),
    ("insurance", "sum insured",
     r"סכום\s*ביטוח[\s:]*[₪$]?\s*([0-9,\.]+)", 0.92),
    ("insurance", "cover amount",
     r"סכום\s*כיסוי[\s:]*[₪$]?\s*([0-9,\.]+)", 0.90),
    ("insurance", "deductible",
     r"השתתפות\s*עצמית[\s:]*[₪$]?\s*([0-9,\.]+)", 0.90),
    ("savings", "balance",
     r"יתר[הת][\s:]*[₪$]?\s*([0-9,\.]+)", 0.85),
    ("savings", "accumulated",
     r"צביר[הת][\s:]*[₪$]?\s*([0-9,\.]+)", 0.85),
    ("vital_sign", "disability_percentage",
     r"(?:אחוזי|דרגת)\s*נכות[\s:]*(\d{1,3})\s*%?", 0.90),
)

# BMI / BP labeled in Hebrew (OCR often drops Latin "BMI").
BMI_HE_RE = re.compile(
    r"(?:מדד\s*מסת\s*גוף|מסת\s*גוף|BMI|בי\s*אם\s*איי)\s*[:=]?\s*(\d{2}(?:[.,]\d)?)",
    re.IGNORECASE,
)
BP_HE_RE = re.compile(
    r"(?:לחץ\s*דם|ל\.?\s*ד\.?|BP)\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})",
    re.IGNORECASE,
)

# Israeli insurer names → provider metadata (not scored, provenance only).
INSURER_NAMES_HE: Tuple[str, ...] = (
    "מגדל", "כלל", "הפניקס", "מנורה", "הראל", "איילון",
    "הכשרה", "שירביט", "ביטוח ישיר", "איידיאיי", "הכשרת הישוב",
)


def contains_hebrew(text: str) -> bool:
    """True when the text contains any Hebrew letter."""
    return bool(text and _HEBREW_RE.search(text))


def hebrew_ratio(text: str) -> float:
    """Share of alphabetic characters that are Hebrew (0..1)."""
    if not text:
        return 0.0
    hebrew = 0
    alpha = 0
    for ch in text:
        if ch.isalpha() or ("\u0590" <= ch <= "\u05FF"):
            alpha += 1
            if "\u0590" <= ch <= "\u05FF" or "\uFB1D" <= ch <= "\uFB4F":
                hebrew += 1
    return (hebrew / alpha) if alpha else 0.0


def detect_document_language(text: str) -> str:
    """Coarse language tag for document_meta: ``he``, ``en``, or ``mixed``."""
    if not text or not text.strip():
        return "unknown"
    ratio = hebrew_ratio(text)
    if ratio >= 0.45:
        return "he"
    if ratio >= 0.08 and contains_hebrew(text):
        return "mixed"
    return "en"


def _is_negated(text: str, start: int) -> bool:
    """True when a Hebrew or English clinical negation precedes ``start``."""
    window = text[max(0, start - _NEGATION_WINDOW): start]
    # Strip trailing punctuation/whitespace so anchors match cleanly.
    # Keep a trailing hyphen attached to the negation particle ("ל-").
    window = re.sub(r"[\s,.;:–—]+$", "", window)
    if any(p.search(window) for p in _NEGATION_PATTERNS):
        return True
    if any(p.search(window) for p in _EN_NEGATION_PATTERNS):
        return True
    return False


def is_clinically_negated(text: str, start: int) -> bool:
    """Public wrapper: True when clinical negation precedes ``start``."""
    if not text or start < 0:
        return False
    return _is_negated(text, start)


def _parse_amount(raw: str) -> Optional[float]:
    cleaned = (raw or "").replace(",", "").replace(" ", "")
    cleaned = cleaned.replace("\u200f", "").replace("\u200e", "")
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "", cleaned.count(".") - 1)
    cleaned = cleaned.replace(",", ".")
    try:
        value = float(cleaned)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return value


def _match_lexicon(
    text: str,
    pairs: Sequence[Tuple[str, str]],
    *,
    fact_type: str,
    confidence: float,
    check_negation: bool = False,
) -> List[HebrewMatch]:
    """Longest-first lexicon scan; one fact per canonical key."""
    if not text:
        return []
    # Sort by Hebrew phrase length descending so longer phrases win.
    ordered = sorted(pairs, key=lambda p: len(p[0]), reverse=True)
    seen_canonical: set = set()
    claimed_spans: List[Tuple[int, int]] = []
    matches: List[HebrewMatch] = []

    for hebrew, canonical in ordered:
        if canonical in seen_canonical:
            continue
        start = 0
        while True:
            idx = text.find(hebrew, start)
            if idx < 0:
                break
            end = idx + len(hebrew)
            # Skip if this span sits inside an already-claimed longer match.
            if any(s <= idx and end <= e for s, e in claimed_spans):
                start = end
                continue
            if check_negation and _is_negated(text, idx):
                start = end
                continue
            seen_canonical.add(canonical)
            claimed_spans.append((idx, end))
            matches.append(HebrewMatch(
                fact_type=fact_type,
                canonical=canonical,
                raw_match=hebrew,
                confidence=confidence,
                metadata={"lang": "he", "raw_match": hebrew, "match_offset": idx},
            ))
            break
        # continue to next lexicon entry
    return matches


def _match_structured_fields(text: str) -> List[HebrewMatch]:
    matches: List[HebrewMatch] = []
    seen: set = set()
    for fact_type, label, pattern, confidence in STRUCTURED_FIELD_PATTERNS:
        key = (fact_type, label)
        if key in seen:
            continue
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1).strip()
        amount = None
        value_meta: Dict[str, Any] = {
            "lang": "he", "raw_match": m.group(0), "match_offset": m.start(),
        }
        if label in ("premium", "sum insured", "cover amount", "deductible",
                     "balance", "accumulated"):
            amount = _parse_amount(raw)
            if amount is None:
                continue
            value_meta["raw_numeric"] = raw
        elif label == "disability_percentage":
            amount = _parse_amount(raw)
            if amount is None:
                continue
            value_meta["unit"] = "percent"
        elif label == "policy_number":
            value_meta["policy_number"] = raw
        seen.add(key)
        matches.append(HebrewMatch(
            fact_type=fact_type,
            canonical=label,
            raw_match=m.group(0),
            confidence=confidence,
            amount=amount,
            metadata={
                **value_meta,
                **({"policy_number": raw} if label == "policy_number" else {}),
            },
        ))
    return matches


def _match_vitals(text: str) -> List[HebrewMatch]:
    matches: List[HebrewMatch] = []
    bmi = BMI_HE_RE.search(text or "")
    if bmi:
        raw = bmi.group(1).replace(",", ".")
        try:
            value = float(raw)
            matches.append(HebrewMatch(
                fact_type="vital_sign",
                canonical="bmi",
                raw_match=bmi.group(0),
                confidence=0.90,
                amount=value,
                metadata={"lang": "he", "raw_match": bmi.group(0)},
            ))
        except ValueError:
            pass
    bp = BP_HE_RE.search(text or "")
    if bp:
        try:
            sys_v = float(bp.group(1))
            dia_v = float(bp.group(2))
            matches.append(HebrewMatch(
                fact_type="vital_sign",
                canonical="blood_pressure_systolic",
                raw_match=bp.group(0),
                confidence=0.90,
                amount=sys_v,
                metadata={"lang": "he", "raw_match": bp.group(0)},
            ))
            matches.append(HebrewMatch(
                fact_type="vital_sign",
                canonical="blood_pressure_diastolic",
                raw_match=bp.group(0),
                confidence=0.90,
                amount=dia_v,
                metadata={"lang": "he", "raw_match": bp.group(0)},
            ))
        except ValueError:
            pass
    return matches


def _match_insurers(text: str) -> List[HebrewMatch]:
    matches: List[HebrewMatch] = []
    for name in INSURER_NAMES_HE:
        idx = text.find(name)
        if idx >= 0:
            matches.append(HebrewMatch(
                fact_type="insurance",
                canonical="provider",
                raw_match=name,
                confidence=0.85,
                metadata={"lang": "he", "raw_match": name, "provider": name},
            ))
            # One provider fact is enough for provenance.
            break
    return matches


def extract_hebrew_matches(text: str) -> List[HebrewMatch]:
    """Run the full Hebrew lexicon + structured-field pass over ``text``.

    Safe to call on any text: returns ``[]`` when no Hebrew is present.
    Deduplicates by ``(fact_type, canonical)`` preferring higher confidence /
    structured-field matches.
    """
    if not text or not contains_hebrew(text):
        return []

    candidates: List[HebrewMatch] = []
    candidates.extend(_match_lexicon(
        text, MEDICAL_CONDITIONS_HE, fact_type="medical_condition",
        confidence=0.80, check_negation=True,
    ))
    candidates.extend(_match_lexicon(
        text, MEDICATIONS_HE, fact_type="medication",
        confidence=0.82, check_negation=True,
    ))
    candidates.extend(_match_lexicon(
        text, ALLERGIES_HE, fact_type="allergy",
        confidence=0.82, check_negation=True,
    ))
    candidates.extend(_match_lexicon(
        text, INSURANCE_HE, fact_type="insurance", confidence=0.70,
    ))
    candidates.extend(_match_lexicon(
        text, SAVINGS_HE, fact_type="savings", confidence=0.70,
    ))
    candidates.extend(_match_lexicon(
        text, RISK_HE, fact_type="risk_indicator", confidence=0.80,
    ))
    candidates.extend(_match_lexicon(
        text, SMOKING_HE, fact_type="risk_indicator", confidence=0.85,
    ))
    candidates.extend(_match_lexicon(
        text, DISABILITY_HE, fact_type="medical_condition",
        confidence=0.78, check_negation=True,
    ))
    candidates.extend(_match_structured_fields(text))
    candidates.extend(_match_vitals(text))
    candidates.extend(_match_insurers(text))

    # Prefer structured/higher-confidence matches for the same canonical key.
    best: Dict[Tuple[str, str], HebrewMatch] = {}
    for match in candidates:
        key = (match.fact_type, match.canonical)
        existing = best.get(key)
        if existing is None or match.confidence > existing.confidence:
            best[key] = match
        elif (existing is not None
              and match.confidence == existing.confidence
              and match.amount is not None
              and existing.amount is None):
            best[key] = match
    return list(best.values())


def smoking_status_from_hebrew(text: str) -> Optional[str]:
    """Return ``current`` / ``former`` / ``never`` when Hebrew smoking evidence exists."""
    if not text or not contains_hebrew(text):
        return None
    # Never-smoker phrases first.
    never_phrases = ("לא מעשן", "לא מעשנת", "מעולם לא עישן", "מעולם לא עישנה",
                     "אינו מעשן", "אינה מעשנת")
    for phrase in never_phrases:
        if phrase in text:
            return "never"
    for hebrew, canonical in sorted(SMOKING_HE, key=lambda p: len(p[0]), reverse=True):
        idx = text.find(hebrew)
        if idx < 0:
            continue
        if _is_negated(text, idx):
            return "never"
        if canonical == "smoker":
            return "current"
        if canonical == "former smoker":
            return "former"
    return None


def is_truthy_smoking_hebrew(value: Any) -> bool:
    """Hebrew-aware smoking truthiness for UW platform-context fields."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    status = smoking_status_from_hebrew(text)
    if status == "current":
        return True
    if status in ("former", "never"):
        return False
    # Also accept the English risk-indicator labels we emit as facts.
    lowered = text.lower()
    if lowered == "smoker":
        return True
    if lowered in ("former smoker", "never"):
        return False
    return False


__all__ = [
    "HebrewMatch",
    "contains_hebrew",
    "hebrew_ratio",
    "detect_document_language",
    "extract_hebrew_matches",
    "smoking_status_from_hebrew",
    "is_truthy_smoking_hebrew",
    "is_clinically_negated",
    "BMI_HE_RE",
    "BP_HE_RE",
    "MEDICAL_CONDITIONS_HE",
    "INSURANCE_HE",
]
