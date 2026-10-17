"""The platform NDA, as the condition on open links to the Unified Business Plan.

The NDA that gates an open link is **the PHINS platform NDA** — the same
document the Corporate Legal dashboard offers at ``/legal/nda.html`` (NDA
Center, ``docType="nda"``) — instantiated for the link: investor / due
diligence context, one-way (the Company discloses), the Receiving Party is
the label the admin typed on the link, and the Purpose names the PHINS
Unified Business Plan. A short "protected view" rider states the open-link
rules (no download / print / copy / capture, attributed access, access
window). Nothing else is added or removed from the platform clauses.

When the recipient signs, the server anchors the signature through the same
legal-docs path as every other platform NDA (``/api/legal-docs/sign`` →
``legal_document_signed`` on the platform ledger) under the document
instance ``LGL-NDA-<share id>``, so the acceptance is visible in the NDA
registry (``/api/legal-docs/registry?doc_id=…``) and verifiable with
``/api/legal-docs/verify``. The document text is content-addressed
(``sha256`` of the rendered text); that digest is the ``documentHash`` the
ledger anchors and the share record keeps.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Dict, List, Optional

__all__ = [
    "DOC_TYPE",
    "DOC_CONTEXT",
    "DOCUMENT_NAME",
    "NDA_VERSION",
    "doc_instance_id",
    "field_values",
    "nda_document",
    "nda_sha256",
    "nda_text",
]

# Platform document identity (mirrors web_portal/static/legal/nda.html).
DOC_TYPE = "nda"
DOC_CONTEXT = "investor"
DOCUMENT_NAME = "PHINS Unified Business Plan"
NDA_VERSION = "platform-nda-2026-10"
COMPANY_NAME = "PHINS Insurance, Inc."
MUTUALITY = "One-way (Company discloses)"
TERM_YEARS = 2
CONFID_YEARS = 5
GOVERNING_LAW = "State of Delaware, USA"
PURPOSE = (
    "Evaluation of a potential business and/or investment relationship with PHINS, "
    "through the protected view of the PHINS Unified Business Plan, investor deck and appendices."
)


def doc_instance_id(share_id: str) -> str:
    """Legal-docs instance id for the NDA signed on a share link."""
    clean = "".join(ch for ch in str(share_id or "") if ch.isalnum() or ch in "-_")[:80]
    return f"LGL-NDA-{clean.upper()}"


def field_values(label: str, effective_date: Optional[str] = None) -> Dict[str, Any]:
    """The field set of ``/legal/nda.html`` as filled for this link."""
    return {
        "companyName": COMPANY_NAME,
        "counterpartyName": str(label or "").strip(),
        "mutual": MUTUALITY,
        "effectiveDate": effective_date or date.today().isoformat(),
        "purpose": PURPOSE,
        "termYears": TERM_YEARS,
        "confidYears": CONFID_YEARS,
        "governingLaw": GOVERNING_LAW,
    }


def _en(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": "Non-Disclosure Agreement",
        "subtitle": "PHINS NDA Center · investor / due diligence · one-way",
        "addressed_to": "Receiving Party",
        "intro": (
            f"This {v['mutual']} Non-Disclosure Agreement is entered into as of {v['effectiveDate']} "
            f"between {v['companyName']} (the \u201cCompany\u201d) and {v['counterpartyName'] or '________'} "
            "(the \u201cReceiving Party\u201d; together the \u201cParties\u201d)."
        ),
        "clauses": [
            ("Purpose",
             f"{v['purpose']} The Receiving Party is reviewing confidential materials in the PHINS "
             "investor data room (pitch, architecture, AI/BI optimization, financial model and cap "
             "table) solely to evaluate a potential investment."),
            ("Confidential Information",
             "\u201cConfidential Information\u201d means non-public information disclosed by a Party, "
             "including the PHINS platform architecture, the append-only hash-chained ledger design, "
             "actuarial and pricing models, AI/automation specifications, source code, financial "
             "projections, cap table, customer and claims data, and business plans, whether or not "
             "marked confidential."),
            ("Obligations",
             "Use Confidential Information solely for the Purpose. Protect it with at least reasonable "
             "care and restrict access to those with a need to know who are bound by like obligations. "
             "Not reverse-engineer, copy, or disclose it to third parties without prior written consent. "
             "Where this Agreement is one-way, only the Company's information is protected; where "
             "mutual, each Party protects the other's."),
            ("Exclusions",
             "Confidential Information does not include information that is or becomes public through "
             "no fault of the Receiving Party, was rightfully known before disclosure, is independently "
             "developed, or is required to be disclosed by law (with notice where permitted)."),
            ("Term",
             f"This Agreement remains in effect for {v['termYears']} years; confidentiality obligations "
             f"survive for {v['confidYears']} years after disclosure (and indefinitely for trade secrets "
             "while they remain such)."),
            ("No License; Return",
             "No license or ownership is granted. Upon request or termination, the Receiving Party will "
             "return or destroy Confidential Information and certify the same."),
            ("Governing Law",
             f"This Agreement is governed by the laws of {v['governingLaw']}. This is a template and not "
             "legal advice. Country-specific regulator NDAs are also available in the PHINS NDA Center."),
            ("Protected view (open-link rider)",
             "The Document is made available only through the protected view of this link. The Receiving "
             "Party shall not download, print, copy, photograph, screenshot, screen-record, transcribe or "
             "otherwise reproduce it and shall not circumvent the view; each opening is attributed to the "
             "signer, access ends at the time shown on the link and earlier when the view is left idle. "
             "Typing a full name (and, where offered, drawing a signature) and selecting \u201cSign and "
             "open\u201d is the Receiving Party's electronic signature of this Agreement, anchored to the "
             "PHINS platform ledger."),
        ],
        "acknowledgement": (
            "I have read this Agreement, I am (or am authorised to sign for) the Receiving Party named "
            "above, and I accept it."
        ),
        "labels": {
            "full_name": "Full name",
            "typed_signature": "Type your full name as your signature",
            "draw_signature": "Draw your signature (optional)",
            "clear": "Clear",
            "password": "Link password",
            "accept": "I accept the Agreement above",
            "submit": "Sign and open",
            "version": "Document",
            "checksum": "Content hash (SHA-256)",
            "window_note": (
                "Access runs for up to {hours} hours from the moment it opens and closes after "
                "{idle} minutes without activity."
            ),
        },
    }


def _he(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": "הסכם סודיות (NDA)",
        "subtitle": "מרכז ה‑NDA של PHINS · משקיע / בדיקת נאותות · חד‑צדדי",
        "addressed_to": "הצד המקבל",
        "intro": (
            f"הסכם סודיות זה ({v['mutual']}) נכרת ביום {v['effectiveDate']} בין {v['companyName']} "
            f"(\u201eהחברה\u201d) לבין {v['counterpartyName'] or '________'} (\u201eהצד המקבל\u201d; יחד \u201eהצדדים\u201d)."
        ),
        "clauses": [
            ("מטרה",
             f"{v['purpose']} הצד המקבל מעיין בחומרים סודיים בחדר הנתונים למשקיעים של PHINS (מצגת, "
             "ארכיטקטורה, אופטימיזציית AI/BI, מודל פיננסי וטבלת הון) אך ורק לצורך בחינת השקעה אפשרית."),
            ("מידע סודי",
             "\u201eמידע סודי\u201d הוא מידע שאינו ציבורי שנמסר על ידי צד, לרבות ארכיטקטורת הפלטפורמה של "
             "PHINS, עיצוב הלדג'ר בשרשור גיבוב (append-only), מודלים אקטואריים ותמחוריים, מפרטי "
             "AI/אוטומציה, קוד מקור, תחזיות פיננסיות, טבלת הון, נתוני לקוחות ותביעות ותוכניות עסקיות, "
             "בין אם סומנו כסודיים ובין אם לאו."),
            ("התחייבויות",
             "להשתמש במידע הסודי אך ורק למטרה. להגן עליו בזהירות סבירה לפחות ולהגביל את הגישה למי "
             "שזקוק לו וכפוף להתחייבויות דומות. לא לבצע הנדסה לאחור, לא להעתיק ולא לגלות לצד שלישי "
             "ללא הסכמה מראש ובכתב. כשההסכם חד‑צדדי מוגן רק מידע החברה; כשהוא הדדי כל צד מגן על "
             "מידע משנהו."),
            ("חריגים",
             "מידע סודי אינו כולל מידע שהפך ציבורי שלא באשמת הצד המקבל, שהיה ידוע לו כדין לפני "
             "המסירה, שפותח באופן עצמאי, או שנדרש לגילוי על פי דין (בהודעה מראש ככל שמותר)."),
            ("תקופה",
             f"הסכם זה בתוקף {v['termYears']} שנים; חובות הסודיות ממשיכות לחול {v['confidYears']} שנים "
             "לאחר המסירה (וללא הגבלת זמן לגבי סודות מסחריים כל עוד הם כאלה)."),
            ("ללא רישיון; השבה",
             "לא מוענק רישיון או בעלות. לפי דרישה או עם סיום ההסכם ישיב הצד המקבל את המידע הסודי או "
             "ישמידו ויאשר זאת."),
            ("דין חל",
             f"על הסכם זה יחולו דיני {v['governingLaw']}. זוהי תבנית ואינה ייעוץ משפטי. הסכמי NDA "
             "ייעודיים לרגולטורים לפי מדינה זמינים במרכז ה‑NDA של PHINS."),
            ("תצוגה מוגנת (נספח לקישור פתוח)",
             "המסמך זמין אך ורק דרך התצוגה המוגנת של קישור זה. הצד המקבל לא יוריד, ידפיס, יעתיק, "
             "יצלם, יצלם מסך, יקליט מסך, יתמלל או ישכפל אותו בכל דרך ולא יעקוף את התצוגה; כל פתיחה "
             "מיוחסת לחותם, הגישה מסתיימת במועד המוצג בקישור ומוקדם יותר כשהתצוגה נותרת ללא פעילות. "
             "הקלדת שם מלא (ולפי העניין ציור חתימה) ובחירה ב\u201eחתימה ופתיחה\u201d היא חתימתו "
             "האלקטרונית של הצד המקבל על הסכם זה, המעוגנת בלדג'ר של פלטפורמת PHINS."),
        ],
        "acknowledgement": "קראתי את ההסכם, אני הצד המקבל ששמו לעיל (או מוסמך/ת לחתום בשמו), ואני מקבל/ת אותו.",
        "labels": {
            "full_name": "שם מלא",
            "typed_signature": "הקלידו את שמכם המלא כחתימה",
            "draw_signature": "ציירו את חתימתכם (לא חובה)",
            "clear": "נקה",
            "password": "סיסמת הקישור",
            "accept": "אני מקבל/ת את ההסכם שלעיל",
            "submit": "חתימה ופתיחה",
            "version": "מסמך",
            "checksum": "גיבוב תוכן (SHA-256)",
            "window_note": "הגישה נמשכת עד {hours} שעות מרגע הפתיחה ונסגרת לאחר {idle} דקות ללא פעילות.",
        },
    }


_BUILDERS = {"en": _en, "he": _he}


def _lang(lang: str) -> str:
    code = str(lang or "en").strip().lower()[:2]
    return code if code in _BUILDERS else "en"


def nda_text(lang: str = "en", *, label: str = "", effective_date: Optional[str] = None) -> str:
    """The plain-text agreement that is hashed and that the signer accepts."""
    v = field_values(label, effective_date)
    t = _BUILDERS[_lang(lang)](v)
    lines: List[str] = [f"{t['title']} — {t['subtitle']} ({NDA_VERSION})", "", t["intro"], ""]
    for n, (head, body) in enumerate(t["clauses"], 1):
        lines.append(f"{n}. {head}. {body}")
    lines.extend(["", t["acknowledgement"]])
    return "\n".join(lines)


def nda_sha256(lang: str = "en", *, label: str = "", effective_date: Optional[str] = None) -> str:
    return hashlib.sha256(nda_text(lang, label=label, effective_date=effective_date).encode("utf-8")).hexdigest()


def nda_document(lang: str = "en", *, label: str = "", effective_date: Optional[str] = None,
                 share_id: str = "") -> Dict[str, Any]:
    """Structured platform NDA for the unlock page / API, filled for ``label``."""
    code = _lang(lang)
    v = field_values(label, effective_date)
    t = _BUILDERS[code](v)
    return {
        "document": DOCUMENT_NAME,
        "doc_type": DOC_TYPE,
        "context": DOC_CONTEXT,
        "doc_instance_id": doc_instance_id(share_id) if share_id else None,
        "platform_document": "/legal/nda.html",
        "version": NDA_VERSION,
        "lang": code,
        "rtl": code == "he",
        "sha256": nda_sha256(code, label=label, effective_date=v["effectiveDate"]),
        "field_values": v,
        "title": t["title"],
        "subtitle": t["subtitle"],
        "addressed_to_label": t["addressed_to"],
        "addressed_to": v["counterpartyName"],
        "intro": t["intro"],
        "clauses": [{"heading": h, "body": b} for h, b in t["clauses"]],
        "acknowledgement": t["acknowledgement"],
        "labels": dict(t["labels"]),
        "text": nda_text(code, label=label, effective_date=v["effectiveDate"]),
    }
