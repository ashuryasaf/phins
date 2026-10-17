"""Conditional NDA for open links to the PHINS Unified Business Plan.

An admin can mint a single-use or multi-use open link to ``/business-plan.html``
(or the Hebrew edition) that is conditional on a non-disclosure undertaking.
Before the recipient is let in they see this text, addressed to the label the
admin typed on the link, and they sign it with their full name (and, when the
device allows, a drawn signature). The acceptance — signer, version, SHA-256
of the text, timestamp, address — is recorded on the share record by
``services/confidential_share_service.py`` and the view that follows is the
protected view (no download, print, copy or capture; access ends after the
window or when the view is left idle).

The text is versioned and content-addressed so a recorded acceptance always
names exactly the wording the signer saw. Changing a word changes
``nda_sha256``; bump ``NDA_VERSION`` whenever the substance changes.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

__all__ = [
    "NDA_VERSION",
    "DOCUMENT_NAME",
    "nda_document",
    "nda_sha256",
    "nda_text",
]

NDA_VERSION = "2026-10-v1"
DOCUMENT_NAME = "PHINS Unified Business Plan"

_EN: Dict[str, Any] = {
    "title": "Non-Disclosure Undertaking",
    "subtitle": "Conditional access to the PHINS Unified Business Plan",
    "addressed_to": "Addressed to",
    "intro": (
        "This undertaking is given by the person named below (the \"Recipient\") to "
        "PHINS (the \"Discloser\") as a condition of opening the protected view of the "
        "PHINS Unified Business Plan, investor deck and appendices (the \"Document\")."
    ),
    "clauses": [
        (
            "Confidential Information",
            "The Document, every figure, chart, assumption, factor, scenario, source "
            "note and narrative in it, and the fact that it was shared with the "
            "Recipient, are confidential information of the Discloser.",
        ),
        (
            "Permitted use",
            "The Recipient may read the Document solely to evaluate a potential "
            "investment, partnership, carrier, reinsurance or supervisory relationship "
            "with PHINS. No other use is permitted.",
        ),
        (
            "No copies or capture",
            "The Recipient shall not download, print, copy, photograph, screenshot, "
            "screen-record, transcribe, scrape or otherwise reproduce the Document or "
            "any part of it, and shall not circumvent the protected view. Each opening "
            "is attributed to the signer named below.",
        ),
        (
            "No onward disclosure",
            "The Recipient shall not disclose the Document or its contents to any third "
            "party. Advisers who need to see it must receive their own link from PHINS "
            "and sign their own undertaking.",
        ),
        (
            "Term",
            "This undertaking applies from signature and for three (3) years after the "
            "link closes. Access to the view itself ends at the time shown on the link "
            "and earlier when the view is left idle.",
        ),
        (
            "No licence, no offer",
            "Nothing in the Document grants any right in PHINS intellectual property. "
            "The Document is a planning identity, not an offer of securities or "
            "insurance; figures are adjustable assumptions, not representations.",
        ),
        (
            "Remedies and law",
            "The Recipient acknowledges that a breach may cause harm that damages cannot "
            "repair and that the Discloser may seek injunctive relief. This undertaking "
            "is governed by the laws of the State of Israel.",
        ),
        (
            "Electronic signature",
            "Typing a full name (and, where offered, drawing a signature) and selecting "
            "\"Sign and open\" constitutes the Recipient's electronic signature and "
            "binding acceptance of this undertaking.",
        ),
    ],
    "acknowledgement": (
        "I have read this undertaking, I am the person named above, and I accept it."
    ),
    "labels": {
        "full_name": "Full name",
        "typed_signature": "Type your full name as your signature",
        "draw_signature": "Draw your signature (optional)",
        "clear": "Clear",
        "password": "Link password",
        "accept": "I accept the undertaking above",
        "submit": "Sign and open",
        "version": "Version",
        "checksum": "Text checksum (SHA-256)",
        "window_note": (
            "Access runs for up to {hours} hours from the moment it opens and closes "
            "after {idle} minutes without activity."
        ),
    },
}

_HE: Dict[str, Any] = {
    "title": "התחייבות לשמירת סודיות",
    "subtitle": "גישה מותנית לתוכנית העסקית המאוחדת של PHINS",
    "addressed_to": "ממוען אל",
    "intro": (
        "התחייבות זו ניתנת על ידי האדם ששמו מופיע מטה (\"המקבל\") לטובת PHINS "
        "(\"המוסרת\") כתנאי לפתיחת התצוגה המוגנת של התוכנית העסקית המאוחדת, מצגת "
        "המשקיעים והנספחים של PHINS (\"המסמך\")."
    ),
    "clauses": [
        (
            "מידע סודי",
            "המסמך, כל נתון, תרשים, הנחה, גורם, תרחיש, הערת מקור ונרטיב שבו, וכן "
            "עצם מסירתו למקבל, הם מידע סודי של המוסרת.",
        ),
        (
            "שימוש מותר",
            "המקבל רשאי לקרוא את המסמך אך ורק לצורך בחינת השקעה, שותפות, קשר עם "
            "מבטח, מבטח משנה או רגולטור עם PHINS. כל שימוש אחר אסור.",
        ),
        (
            "ללא העתקה או לכידה",
            "המקבל לא יוריד, ידפיס, יעתיק, יצלם, יצלם מסך, יקליט מסך, יתמלל, יגרד או "
            "ישכפל בכל דרך אחרת את המסמך או חלק ממנו, ולא יעקוף את התצוגה המוגנת. כל "
            "פתיחה מיוחסת לחותם ששמו מופיע מטה.",
        ),
        (
            "ללא העברה הלאה",
            "המקבל לא יגלה את המסמך או את תוכנו לצד שלישי. יועצים הזקוקים לעיין בו "
            "יקבלו קישור משלהם מ‑PHINS ויחתמו על התחייבות משלהם.",
        ),
        (
            "תקופה",
            "התחייבות זו חלה מרגע החתימה ולמשך שלוש (3) שנים לאחר סגירת הקישור. הגישה "
            "לתצוגה עצמה מסתיימת במועד המוצג בקישור, ומוקדם יותר אם התצוגה נותרת ללא "
            "פעילות.",
        ),
        (
            "ללא רישיון, ללא הצעה",
            "אין במסמך כדי להקנות זכות כלשהי בקניין הרוחני של PHINS. המסמך הוא זהות "
            "תכנונית ולא הצעה של ניירות ערך או ביטוח; הנתונים הם הנחות מתכווננות ולא "
            "מצגים.",
        ),
        (
            "סעדים ודין",
            "המקבל מאשר כי הפרה עלולה לגרום נזק שפיצוי כספי לא יוכל לתקן, וכי המוסרת "
            "רשאית לבקש צו מניעה. על התחייבות זו יחולו דיני מדינת ישראל.",
        ),
        (
            "חתימה אלקטרונית",
            "הקלדת שם מלא (ולפי העניין, ציור חתימה) ובחירה ב\"חתימה ופתיחה\" מהוות את "
            "חתימתו האלקטרונית של המקבל ואת קבלתו המחייבת של התחייבות זו.",
        ),
    ],
    "acknowledgement": "קראתי את ההתחייבות, אני האדם ששמו מופיע לעיל, ואני מקבל/ת אותה.",
    "labels": {
        "full_name": "שם מלא",
        "typed_signature": "הקלידו את שמכם המלא כחתימה",
        "draw_signature": "ציירו את חתימתכם (לא חובה)",
        "clear": "נקה",
        "password": "סיסמת הקישור",
        "accept": "אני מקבל/ת את ההתחייבות שלעיל",
        "submit": "חתימה ופתיחה",
        "version": "גרסה",
        "checksum": "סיכום בדיקה של הטקסט (SHA-256)",
        "window_note": (
            "הגישה נמשכת עד {hours} שעות מרגע הפתיחה ונסגרת לאחר {idle} דקות ללא פעילות."
        ),
    },
}

_TEXTS = {"en": _EN, "he": _HE}


def _lang(lang: str) -> str:
    code = str(lang or "en").strip().lower()[:2]
    return code if code in _TEXTS else "en"


def nda_text(lang: str = "en") -> str:
    """The plain-text body that is hashed and that the signer accepts."""
    t = _TEXTS[_lang(lang)]
    lines: List[str] = [f"{t['title']} — {t['subtitle']} ({NDA_VERSION})", "", t["intro"], ""]
    for n, (head, body) in enumerate(t["clauses"], 1):
        lines.append(f"{n}. {head}. {body}")
    lines.extend(["", t["acknowledgement"]])
    return "\n".join(lines)


def nda_sha256(lang: str = "en") -> str:
    return hashlib.sha256(nda_text(lang).encode("utf-8")).hexdigest()


def nda_document(lang: str = "en", *, label: str = "") -> Dict[str, Any]:
    """Structured NDA for the unlock page / API, addressed to ``label``."""
    code = _lang(lang)
    t = _TEXTS[code]
    return {
        "document": DOCUMENT_NAME,
        "version": NDA_VERSION,
        "lang": code,
        "rtl": code == "he",
        "sha256": nda_sha256(code),
        "title": t["title"],
        "subtitle": t["subtitle"],
        "addressed_to_label": t["addressed_to"],
        "addressed_to": str(label or "").strip(),
        "intro": t["intro"],
        "clauses": [{"heading": h, "body": b} for h, b in t["clauses"]],
        "acknowledgement": t["acknowledgement"],
        "labels": dict(t["labels"]),
        "text": nda_text(code),
    }
