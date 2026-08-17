"""Hebrew (and future) localization for the Phin chat application process.

Resume codes (``PHINS-CHAT-XXXXXXXX``) are intentionally never translated —
they stay ASCII so tracking / pause-resume remain stable across languages.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Step prompts (static). Dynamic prompts use MSG_* templates below.
STEP_PROMPTS_HE: Dict[str, str] = {
    "name": "בואו נתחיל בקלות — מה שמך המלא?",
    "email": (
        "נעים להכיר, {first}! מה כתובת הדוא\"ל הטובה ביותר עבורך? "
        "אשלח לשם את מסמכי הפוליסה — וגם קוד אימות קצר בעוד רגע."
    ),
    "phone": "ומה מספר הנייד שלך? נשתמש בו רק להודעות חשובות על הפוליסה.",
    "dob": (
        "אומת — תודה! עכשיו חלק החיתום. אהיה הסוכן/ת שלך לאורך הדרך: "
        "תשובות כנות מביאות את המחיר ההוגן ביותר. קודם כל, מה תאריך הלידה שלך?"
    ),
    "gender": "איזו אפשרות מתאימה למגדר שלך? טבלאות האקטואריה שלנו משתמשות בזה לתמחור מדויק.",
    "occupation": "במה את/ה עוסק/ת? מקצועות מסוימים נושאים פרופילי סיכון שונים.",
    "height": "בואו נדבר על בריאות. מה גובהך בסנטימטרים?",
    "weight": "ומה משקלך בקילוגרמים?",
    "tobacco": "האם את/ה משתמש/ת במוצרי טבק — סיגריות, סיגרים או אידוי?",
    "medical_conditions": (
        "האם יש לך מצבים רפואיים קיימים? כל מה שתשתף/י נשמר בסודיות ומוגן."
    ),
    "conditions_list": (
        "מעריך/ה את הכנות שלך — בדיוק זה שמביא פוליסה הוגנת ותקפה. "
        "נא לרשום את המצבים (למשל \"סוכרת סוג 2, לחץ דם גבוה\")."
    ),
    "surgery": "האם עברת ניתוחים משמעותיים ב־5 השנים האחרונות?",
    "surgery_list": "תודה שסימנת. בקצרה, מה היה הניתוח ומתי?",
    "hazardous": (
        "האם את/ה עוסק/ת בפעילויות מסוכנות או ספורט קיצוני? "
        "צניחה, מרוצי מכוניות, צלילה עמוקה — דברים מסוג זה."
    ),
    "family_history": (
        "האם לבן משפחה מדרגה ראשונה היה מחלת לב, סרטן, סוכרת או שבץ? "
        "בחר/י את כל מה שרלוונטי."
    ),
    "medications": (
        "כמעט סיימנו עם הבריאות: האם את/ה נוטל/ת תרופות באופן קבוע? "
        "כתוב/י \"none\" אם לא."
    ),
    "prior_disclosure": (
        "לפני שנמשיך, אני בודק/ת את תשובותיך מול בקשות או תביעות קודמות ב־PHINS. "
        "אם יש סתירה אבקש הסבר; אחרת אבקש לגלות כעת כל עובדה רפואית נוספת "
        "שאת/ה משחרר/ת לסודיות רפואית לטובת חיתום PHINS."
    ),
    "daily_function": (
        "שאלת בריאות אחרונה — והיא חשובה לכיסוי הנכות. "
        "האקטוארים מתמחרים את קצבת הנכות לפי פעילויות יומיום "
        "(הלבשה, רחצה, אכילה, מעברים, שימוש בשירותים, שליטה). "
        "איך תתאר/י את העצמאות התפקודית היומיומית שלך?"
    ),
    "coverage_amount": (
        "עכשיו החלק הנעים — כמה כיסוי תרצה/י? רוב החברים בוחרים $500,000. "
        "אפשר לכוון עם המחוון."
    ),
    "coverage_years": (
        "ולכמה שנים לבנות את החיסכון וההגנה? 20 שנה היא התוכנית הפופולרית ביותר."
    ),
    "savings_addon": (
        "האם תרצה/י להוסיף חיסכון PHINS מעל ההגנה? "
        "הוא מתומחר כתוספת על פרמיית הסיכון ומצטבר בתוכנית — "
        "הגנה טהורה תמיד אפשרית."
    ),
    "media_offer": (
        "אופציונלי אך מומלץ: אפשר לשלוח הודעת קול, להקליט סרטון קצר, "
        "או להעלות מסמכים תומכים (תעודה, תוצאות רפואיות). זה יכול להאיץ חיתום. "
        "השתמש/י בכפתורי המיקרופון / מצלמה / קובץ — ולחץ/י \"סיום\" כשמוכן/ה להמשיך."
    ),
    "billing_frequency": "איך תרצה/י לשלם את הפרמיה?",
    "payment_card": (
        "כמעט שם. אני צריך/ה כרטיס תשלום לחיוב הפרמיה — "
        "הוא מוצפן ומטוקן, לעולם לא נשמר המספר המלא."
    ),
    "auto_pay": "האם להגדיר תשלומים אוטומטיים כדי שלא תפספס/י פרמיה?",
    "consent": (
        "כמעט סיימנו — החלק המשפטי. נא לאשר ש: (1) את/ה מסכים/ה לתנאי השימוש "
        "ולמדיניות הפרטיות, (2) כל מה שסיפרת לי מדויק ומלא, ו־"
        "(3) את/ה מאשר/ת ל־PHINS לחייב את אמצעי התשלום עבור פרמיות."
    ),
    "signature": (
        "שלב אחרון — חתימה אלקטרונית חובה. הזן/י את שמך החוקי המלא, "
        "מספר תעודת זהות, וחתום/י בלוח החתימה כדי לאטום את ההצהרות."
    ),
}

CHOICE_LABELS_HE: Dict[str, Dict[str, str]] = {
    "tobacco": {
        "no": "לא, אף פעם",
        "yes": "כן, כרגע",
        "former": "הפסקתי לפני יותר משנה",
    },
    "medical_conditions": {"no": "לא", "yes": "כן"},
    "surgery": {"no": "לא", "yes": "כן"},
    "hazardous": {
        "no": "לא",
        "occasional": "1–2 פעמים בשנה",
        "regular": "חודשי או יותר",
    },
    "family_history": {
        "heart": "לב",
        "cancer": "סרטן",
        "diabetes": "סוכרת",
        "stroke": "שבץ",
        "none": "אין",
    },
    "daily_function": {
        "full": "עצמאות מלאה בכל הפעילויות",
        "minor": "קושי קל בפעילות אחת",
        "moderate": "זקוק/ה לעזרה ב־1–2 פעילויות",
        "significant": "זקוק/ה לעזרה ב־3 פעילויות או יותר",
    },
    "coverage_years": {"10": "10", "15": "15", "20": "20", "30": "30"},
    "savings_addon": {
        "none": "הגנה טהורה (ללא חיסכון)",
        "light": "קל (+25% מפרמיית הסיכון)",
        "balanced": "מאוזן (+50%)",
        "growth": "צמיחה (+100%)",
    },
    "billing_frequency": {
        "monthly": "חודשי",
        "quarterly": "רבעוני (חיסכון 3%)",
        "annual": "שנתי (חיסכון 10%)",
    },
    "auto_pay": {"yes": "כן", "no": "לא"},
    "gender": {"male": "זכר", "female": "נקבה", "other": "אחר"},
    "media_offer": {"done": "סיום — המשך", "skip": "דלג לעת עתה"},
}

PLACEHOLDERS_HE: Dict[str, str] = {
    "name": "למשל דנה לוי",
    "email": "name@example.com",
    "phone": "+972-50-000-0000",
    "occupation": "למשל מהנדס/ת תוכנה",
    "conditions_list": "למשל סוכרת, לחץ דם גבוה",
    "medications": "למשל מטפורמין — או \"none\"",
    "prior_disclosure": "הגילוי שלך",
    "signature": "שם חוקי מלא",
    "id_number": "מספר תעודת זהות",
}

MSG_HE: Dict[str, str] = {
    "greeting": (
        "שלום! אני {bot_name}, {bot_title} שלך — אלך איתך אישית "
        "לאורך בקשת הכיסוי ב־PHINS, כמו סוכן/ת מולך. בדרך כלל זה לוקח כ־3 דקות."
    ),
    # Resume code stays ASCII inside the sentence (tracking invariant).
    "resume_note": (
        "קוד ההמשך הפרטי שלך הוא {resume_code}. אם ניפסק באמצע, חזור/י בכל עת — "
        "הקוד יחד עם הדוא\"ל ממשיכים בדיוק מאיפה שעצרנו."
    ),
    "invite_welcome": (
        "ברוך/ה הבא/ה! רואה שהוזמנת על ידי {who} של PHINS — "
        "הפניות טובות יוצרות חברים טובים."
    ),
    "otp_challenge": (
        "מושלם. כדי להגן על הנתונים שלך שלחתי קוד אימות בן 6 ספרות אל "
        "{masked_email}. הקלד/י אותו כאן כשיגיע."
    ),
    "ready_to_finalize": (
        "זה כל מה שצריך! רגע אחד לבדיקות סופיות, "
        "ואז אעביר את הבקשה לחיתום."
    ),
    "submitted": (
        "מזל טוב{name_part}! הבקשה שלך רשמית בפנים. פוליסה {policy_id} "
        "אצל צוות החיתום, מספר אסמכתא {underwriting_id}. רשמתי כל שלב בשיחה "
        "בפנקס PHINS, כך שהתיק שלם וחתום נגד שינוי. "
        "נחזור אליך בקרוב — בדרך כלל תוך דקות, לא ימים."
    ),
    "uw_approved": (
        "חדשות טובות{name_part}! החיתום **אישר** את הבקשה שלך. "
        "פוליסה {policy_id} פעילה. פרמיה חודשית: ${monthly:,.2f}"
        "{loading_part}. חוזה הפוליסה נשלח לדוא\"ל שלך."
    ),
    "uw_approved_loading": " (כולל התאמת חיתום של {loading_pct}%)",
    "uw_rejected": (
        "עדכון על הבקשה שלך{name_part}: לאחר בדיקה, החיתום **לא אישר** "
        "את הכיסוי בשלב זה"
        "{reason_part}. נשלחה הודעה לדוא\"ל שלך. אפשר לפנות אלינו לשאלות."
    ),
    "uw_rejected_reason": " — סיבה: {reason}",
    "signature_ack": (
        "נחתם על ידי {name} (ת.ז. {id_masked}) ב־{signed_at}. "
        "ההצהרות שלך נאטמו כעת לחיתום."
    ),
    "consent_ack": "אישורים משפטיים נרשמו — שלב אחרון לחתימה.",
    "paused": (
        "שמרתי את ההתקדמות שלך. חזור/י עם הקוד {resume_code} והדוא\"ל שלך, "
        "ונמשיך בדיוק מכאן."
    ),
    "resumed": "ברוך/ה השב/ה! ממשיכים משם שעצרנו.",
    "otp_verified": "האימות הצליח — ממשיכים.",
}

ACK_HE: Dict[str, str] = {
    "dob_young": (
        "{age} — להתחיל מוקדם הוא ההחלטה הביטוחית החכמה ביותר. "
        "נעילת הבריאות עכשיו שומרת על פרמיות נמוכות לעשורים."
    ),
    "dob_senior": "רשמתי, {age}. אוודא שהתוכנית משקפת את ההגנה החשובה ביותר בשלב זה.",
    "dob_default": "קיבלתי, תודה.",
    "tobacco_yes": (
        "תודה על הכנות — כסוכן/ת שלך אני חייב/ת להיות ישיר/ה גם: "
        "טבק מעלה את הפרמיה. החדשות הטובות? הפסקה ל־12 חודשים ואפשר לדרג מחדש."
    ),
    "tobacco_former": "כבוד — להפסיק זה קשה. כי עברה יותר משנה, ההשפעה על התעריף מתונה.",
    "tobacco_no": "מעולה — זה שומר על התעריף רזה.",
    "bmi_healthy": "ה־BMI שלך יוצא {bmi:.1f} — בדיוק בטווח הבריא. החיתום אוהב את זה.",
    "bmi_high": "ה־BMI שלך יוצא {bmi:.1f}. ייתכן תוספת קטנה, אבל אין משהו שאי אפשר לעבוד איתו.",
    "bmi_other": "ה־BMI שלך יוצא {bmi:.1f} — נרשם להערכה.",
    "medical_clean": "בריאות נקייה — מצוין.",
    "hazardous": "הרפתקני/ת! אקח את זה בחשבון — שקיפות מלאה שומרת על תביעות חזקות.",
    "family_yes": "תודה — היסטוריה משפחתית עוזרת לאקטוארים לתמחר בהוגנות, היא לא פוסלת.",
    "family_no": "גנים טובים — נרשם.",
    "disclosure_contradiction": (
        "תודה — חתמתי את ההסבר לתיק עבור החתם הבכיר. כנות כאן מגנה על תביעות עתידיות."
    ),
    "disclosure_none": "הבנתי — אין מה לגלות נוסף. ממשיכים.",
    "disclosure_other": "נרשם. הגילוי הנוסף עובר ישירות לחיתום עם התיק.",
    "coverage_amount": "${value:,.0f} של כיסוי — בחירה יציבה.",
    "daily_full": "עצמאות מלאה — זה הדירוג הסטנדרטי לקצבת הנכות.",
    "daily_other": (
        "תודה על הדיוק — האקטוארים מתמחרים את קצבת הנכות ישירות מכך, "
        "כך שהכיסוי נשאר כנה וניתן לתביעה."
    ),
    "savings_none": "הגנה טהורה. מתמחר ממרכז התמחור האקטוארי...",
    "savings_other": "חיסכון נוסף מעל ההגנה. מתמחר כעת דרך מרכז התמחור האקטוארי...",
    "coverage_years": "{value} שנים — נרשם.",
    "billing_annual": "שנתי — זה נועל את חיסכון ה־10%.",
    "billing_quarterly": "רבעוני — מקבלים חיסכון 3%.",
    "billing_monthly": "חודשי — האפשרות הפופולרית ביותר.",
    "auto_pay_yes": "תשלום אוטומטי מופעל — פחות דבר לדאוג לו.",
    "auto_pay_no": "אין בעיה — אשלח תזכורת לפני כל מועד.",
    "media_with": "התקבלו {n} קבצים מצורפים — בוט החיתום יבדוק אותם עם התיק.",
    "media_none": "אין בעיה — תמיד אפשר לבקש מסמכים מאוחר יותר אם החיתום יצטרך.",
}

VALIDATION_HE: Dict[str, str] = {
    "Please type your full legal name to sign.": "נא להקליד את שמך החוקי המלא לחתימה.",
    "Please complete the signature panel (legal name, ID number, and drawn signature).": (
        "נא להשלים את לוח החתימה (שם חוקי, מספר זהות וחתימה מצוירת)."
    ),
    "Please enter your national ID / Teudat Zehut number.": (
        "נא להזין את מספר תעודת הזהות / מספר זהות לאומי."
    ),
    "That ID number does not look valid - please double-check the digits.": (
        "מספר הזהות לא נראה תקין — נא לבדוק שוב את הספרות."
    ),
    "Please draw your signature in the signature panel.": (
        "נא לצייר את חתימתך בלוח החתימה."
    ),
    "Please provide a disclosure (or type \"none\").": (
        "נא לספק גילוי (או להקליד \"none\")."
    ),
}

UI_INPUT_HE: Dict[str, str] = {
    "years": "שנים",
    "cm": "ס\"מ",
    "kg": "ק\"ג",
}


def normalize_language(value: Any) -> str:
    lang = str(value or "en").strip().lower()[:8]
    if lang.startswith("he") or lang in ("iw", "heb", "hebrew"):
        return "he"
    return "en"


def is_hebrew(session_or_lang: Any) -> bool:
    if isinstance(session_or_lang, dict):
        return normalize_language(session_or_lang.get("language")) == "he"
    return normalize_language(session_or_lang) == "he"


def tr_validation(session: Dict[str, Any], message: str) -> str:
    if not is_hebrew(session):
        return message
    return VALIDATION_HE.get(message, message)


def localize_choice_labels(session: Dict[str, Any], step_id: str,
                           labels: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if not is_hebrew(session):
        return labels
    he = CHOICE_LABELS_HE.get(step_id)
    if not he:
        return labels
    if labels:
        return {k: he.get(k, v) for k, v in labels.items()}
    return dict(he)


def localize_placeholder(session: Dict[str, Any], step_id: str,
                         fallback: Optional[str]) -> Optional[str]:
    if not is_hebrew(session):
        return fallback
    return PLACEHOLDERS_HE.get(step_id, fallback)


def msg(session: Dict[str, Any], key: str, en: str, **kwargs: Any) -> str:
    if is_hebrew(session) and key in MSG_HE:
        template = MSG_HE[key]
    else:
        template = en
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def ack(session: Dict[str, Any], key: str, en: str, **kwargs: Any) -> str:
    if is_hebrew(session) and key in ACK_HE:
        template = ACK_HE[key]
    else:
        template = en
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def step_prompt_he(step_id: str, **kwargs: Any) -> Optional[str]:
    tmpl = STEP_PROMPTS_HE.get(step_id)
    if not tmpl:
        return None
    try:
        return tmpl.format(**kwargs)
    except (KeyError, ValueError):
        return tmpl
