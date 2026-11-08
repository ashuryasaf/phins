"""Swiss Re Israel meeting deck — 8 December 2026.

A reinsurer-facing presentation built the way the investor deck is built
(``services/investor_deck_video.py``): one slide list whose bullets are
templates, figures filled from the unified plan at render time, one
15-second scene per paragraph with a short spoken script, presenters from
the shared roster, and a seal that refuses a paragraph the plan cannot fill.

What this deck adds for a reinsurer:

* a reinsurer view derived by identity from the plan's carrier rows —
  ceded premium, ceded claims, ceding commission and the technical result
  (ceded premium − ceded claims − ceding commission) per year and over the
  five years, with the technical margin and break-even claims ratio that
  follow from the expected claims ratio and the ceding commission;
* quota-share scenarios for the Israel pilot computed by the same model
  (``compute_plan`` with the current inputs and a different ``cession_rate``),
  each carrying its own content hash and labelled ``scenario``;
* the group envelope (group risk GWP × cession), labelled arithmetic, not a
  model row.

Every ``{re_*}`` placeholder resolves here; every other placeholder resolves
through the document's own figure registry, so a figure on this deck is the
same figure as on the plan page. The plan, its factors and the media library
are never written by this module. No limit, ticket or price is set.

Hebrew edition
--------------
The deck is authored once in English. ``lang="he"`` renders the same slides
through a :class:`~services.business_plan_i18n.Translator` whose table is the
unified plan's Hebrew dictionary plus the rows in :data:`HE` below, so a
figure placeholder stays inside the Hebrew sentence and is filled from the
same plan dict. Hebrew scenes are keyed ``re-he-sNNpNN`` and stored under
:data:`STORE_NAME_HE`; an English seal is never replaced by a Hebrew one. A
missing Hebrew sentence refuses the Hebrew catalog rather than filming
English under a Hebrew key.

Adjustable reinsurance factors
------------------------------
The presentation accepts the four reinsurance factors of the plan's own
register (:data:`ADJUSTABLE_FACTORS`) as a viewer scenario. The result is
``compute_plan`` with those factors moved over the viewer's baseline (saved
factors, or the set frozen on a share link); it carries its own content hash,
is labelled ``scenario`` and is never written back. A value outside the
register's range is refused, not clamped. The media lab seals scenes against
the baseline plan only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from services.business_plan_charts import (
    GOLD,
    GOLD_DEEP,
    GREY,
    NAVY,
    chart_by_id,
    render_svg,
)
from services.business_plan_document import _PLACEHOLDER, _fill, fmt
from services.business_plan_i18n import Translator, current as _current_translator, language_context
from services.business_plan_model import FACTOR_INDEX, _coerce, compute_plan

SCENE_KEY_PREFIX = "re-"
HEBREW_SCENE_KEY_PREFIX = "re-he-"
FIGURE_PREFIX = "re_"
DECK_ID = "reinsurer"
SCENE_SECONDS = 15
STORE_NAME = "reinsurer_deck_scenes"
STORE_NAME_HE = "reinsurer_deck_scenes_he"
PAGE_PATH = "/reinsurer-deck.html"
PAGE_PATH_HE = "/reinsurer-deck.he.html"
PRESENTATION_API = "/api/admin/media/reinsurer-deck/presentation"
LAB_API = "/api/admin/media/reinsurer-deck"

# Quota-share alternatives the pilot conversation can turn on. The plan's own
# cession stays the reference; these are scenarios of the same model.
SCENARIO_CESSIONS: Tuple[float, ...] = (0.30, 0.50)

# The reinsurance factors a viewer of this deck may move. They are rows of the
# plan's own factor register; nothing here declares a new assumption.
ADJUSTABLE_FACTORS: Tuple[str, ...] = (
    "cession_rate",
    "ceding_commission",
    "expected_loss_ratio",
    "insurer_own_expense_ratio",
)

MEETING: Dict[str, str] = {
    "date": "2026-12-08",
    "date_text": "Tuesday 8 December 2026",
    "counterpart": "Mr. Hillel Damelin",
    "counterpart_role": "Regional CEO, Israel — Swiss Re",
    "organization": "Swiss Re",
    "subject": "Israel pilot and the five-year plan — quota share, options, next steps",
    "phins_side": "Asaf Ashury, Adv. — Founder & CEO, PHINS Technologies",
    "pack": PAGE_PATH,
    "status": "Scheduled",
}

Section = Dict[str, Any]


# ---------------------------------------------------------------------------
# Language — English is the identity; Hebrew is the same deck through a table
# ---------------------------------------------------------------------------
def normalize_lang(value: Any) -> str:
    """``en`` or ``he``. Anything else is English, so a bad flag cannot retarget a seal."""
    text = str(value or "").strip().lower()
    return "he" if text in ("he", "heb", "hebrew", "iw") else "en"


_TRANSLATORS: Dict[str, Translator] = {}


def translator_for(lang: str = "en") -> Translator:
    """A translator whose table is the plan's Hebrew dictionary plus this deck's rows.

    One instance per language is kept so ``misses`` accumulate across a
    render; :func:`hebrew_misses` reports them for the contract test.
    """
    language = normalize_lang(lang)
    if language == "en":
        return Translator("en", table={})
    cached = _TRANSLATORS.get(language)
    if cached is None:
        from services.business_plan_i18n_he import HE as PLAN_HE

        table = dict(PLAN_HE)
        table.update(HE)
        cached = Translator(language, table=table)
        _TRANSLATORS[language] = cached
    return cached


def hebrew_misses() -> List[str]:
    """English strings the Hebrew render needed and the tables did not have."""
    return sorted(translator_for("he").misses)


def _T(text: str) -> str:
    """Translate with the translator of the render in progress."""
    return _current_translator()(text)


def meeting_facts(lang: str = "en") -> Dict[str, str]:
    """The meeting strip in the requested language. Dates and ids are not translated."""
    speak = translator_for(lang)
    facts = dict(MEETING)
    for field in ("date_text", "counterpart", "counterpart_role", "organization", "subject", "phins_side", "status"):
        facts[field] = speak(MEETING[field])
    facts["pack"] = PAGE_PATH_HE if normalize_lang(lang) == "he" else PAGE_PATH
    facts["lang"] = normalize_lang(lang)
    return facts

# Slide title → chart id. ``ceded_line`` is this module's own chart; the rest
# are the plan's charts, drawn by ``business_plan_charts``.
SLIDE_CHARTS: Dict[str, str] = {
    "The pilot in Israel — 2027": "in_force",
    "The ceded line — five years": "ceded_line",
    "Quota-share options for the pilot": "carrier_view",
    "Five-year plan — Israel anchor book": "gwp_split",
    "Five-year plan — the group": "revenue_ebitda",
    "Capital and timeline": "roadmap",
}


def deck_slides() -> List[Section]:
    """The meeting deck. Templates are unfilled; figures are never typed."""
    return [
        {"title": "PHINS × Swiss Re Israel",
         "kicker": "Tuesday 8 December 2026 · Mr. Hillel Damelin, Regional CEO Israel · Israel pilot and the five-year plan",
         "bullets": [
            "One regulated contract family — life with a lifelong ADL-3 disability mechanism, long-term care and a savings flow — carried by a licensed Israeli insurer and reinsured by quota share; PHINS is the technology and the administrator.",
            "A pilot in Israel from 1 January 2027 and a five-year plan to 2031. Every figure in this deck is a default of {plan_version} · hash {hash}…; nothing is typed by hand.",
         ]},
        {"title": "Why a reinsurer, why now", "bullets": [
            "The pre-ruling track with the Capital Market, Insurance and Savings Authority opened on 12 October 2026; carrier and reinsurance term sheets are the Q4 2026 gate before any sale.",
            "Severe disability and long-term care are the protection gap public systems leave open. A quota share on a new, digitally underwritten book is the reinsurer's way into that gap without carrying distribution on its own balance sheet.",
         ]},
        {"title": "The pilot in Israel — 2027", "bullets": [
            "Gate 5 — sales begin on 1 January 2027 on the licensed carrier's paper; Gate 6 — the first 1,000 policies in force with an Appointed Actuary review against the kernel; Gate 7 — {il_eoy_0} policies in force at year end.",
            "Pilot-year risk GWP {il_gwp_0}; ceded premium at the plan's {cession} quota share {cv_ceded_0}; reinsurer technical result {re_result_0} ({re_result_usd_0} at planning FX {fx}).",
         ]},
        {"title": "The contract the reinsurer underwrites", "bullets": [
            "Life {il_face} with a lifelong disability mechanism — 1:4 below 65, 1:1 from 65 — on an objective ADL-3 trigger; published tables 0.25 / 0.20 per ₪1,000 monthly; {premium} a year at the age-42 specimen.",
            "One pricing kernel is the single writer for premium decomposition. Repricing runs through it at every gate, and the carrier view is restated on every plan refresh, so the reinsurer reads the same rows as the carrier and the Appointed Actuary.",
         ]},
        {"title": "The ceded line — five years", "bullets": [
            "Ceded premium {cv_ceded_0} → {cv_ceded_2} → {cv_ceded_4} (2027 / 2029 / 2031); five-year ceded premium {re_ceded_5y} ({re_ceded_5y_usd}).",
            "Reinsurer technical result {re_result_0} → {re_result_2} → {re_result_4}; five years {re_result_5y} ({re_result_5y_usd}) — {re_margin} of ceded premium at the plan's {loss_ratio} expected claims and {ceding_commission} ceding commission; break-even claims ratio {re_breakeven}.",
         ]},
        {"title": "Quota-share options for the pilot", "bullets": [
            "The plan: {cession} cession, {ceding_commission} ceding commission, carrier margin {cv_margin_0}; the reinsurer's five-year technical result {re_result_5y}.",
            "Scenarios from the same model — at {re_qs30_label} cession the five-year ceded premium is {re_qs30_ceded_5y}, the technical result {re_qs30_result_5y} and the carrier margin {re_qs30_carrier_margin}; at {re_qs50_label} cession {re_qs50_ceded_5y}, {re_qs50_result_5y} and {re_qs50_carrier_margin}. PHINS revenue and EBITDA are unchanged in every scenario; the split between carrier and reinsurer is what moves.",
         ]},
        {"title": "Five-year plan — Israel anchor book", "bullets": [
            "Policies in force {il_eoy_0} → {il_eoy_1} → {il_eoy_2} → {il_eoy_3} → {il_eoy_4}; risk GWP {il_gwp_0} → {il_gwp_4}; five-year risk GWP {re_gwp_5y}.",
            "The savings flow — {il_savings_2} in 2029, {il_savings_4} in 2031 — is a separate licensed flow and is never split with the carrier or the reinsurer. The benefit is a lump sum with a fixed sum at risk, not a lifetime care annuity.",
         ]},
        {"title": "Five-year plan — the group", "bullets": [
            "OECD partner markets under local licensed carriers: {pm_live_1} in 2028, {pm_live_2} in 2029, {pm_live_4} by 2031 — {markets_2031} markets on one platform, {g_eoy_4} group lives and {g_gwp_4} group risk GWP.",
            "A reinsurer that leads Israel can follow the same wording into each market. Group risk GWP × {cession} is {re_group_envelope_4} in 2031 ({re_group_envelope_4_usd}) — arithmetic on the group GWP row, not a model row.",
         ]},
        {"title": "What PHINS asks of Swiss Re Israel", "bullets": [
            "Lead quota-share reinsurer for the Israel pilot: a non-binding indication on the plan's {cession} / {ceding_commission} structure by the Q4 2026 gate, and a technical review of the pricing kernel and the published tables under NDA.",
            "Beyond capacity, every option stays on the table — lead reinsurer and technical partner for the first partner market in 2028, a data-access arrangement on the evidence pipeline, or an equity conversation kept separate from the treaty. Never a linked price.",
         ]},
        {"title": "What Swiss Re sees — governance and data", "bullets": [
            "Agents recommend, humans decide. Every underwriting and claims recommendation is logged with evidence provenance; thresholds move only through an audited promotion step; a contradiction between documents is recorded, never resolved by a bot.",
            "One hash-chained ledger, one identity writer, checksummed agent state. The reinsurer's bordereaux read from the same rows the carrier and the Appointed Actuary read.",
         ]},
        {"title": "Capital and timeline", "bullets": [
            "Seed {seed} on {pre} pre-money ({post} post); Series A {series_a} indicative in 2028; group EBITDA positive in {first_positive}. The reinsurer's capacity carries the book; it does not fund PHINS.",
            "12 October 2026 pre-ruling · Q4 2026 seed close and term sheets · 1 January 2027 sales begin · Q4 2027 Gate 7 · 2028 first partner market · 2031 {markets_2031} markets.",
         ]},
        {"title": "Next steps after 8 December", "bullets": [
            "Proposed: within two weeks, NDA, data room and a kernel walkthrough with the Appointed Actuary; within six weeks, a non-binding indication on the quota share; before Gate 5, a signed term sheet with the carrier of record named.",
            "Nothing is bound today. No limit, ticket or price is set in this deck; every figure regenerates from {plan_version}, and the plan is not written by this meeting.",
         ]},
    ]


# ---------------------------------------------------------------------------
# Hebrew edition — keys are the exact English strings authored above and in
# the chart, meeting strip and markdown pack. Placeholders and code spans are
# kept verbatim so the Hebrew deck fills the same figures.
# ---------------------------------------------------------------------------
HE: Dict[str, str] = {
    # Slide titles, kicker and bullets
    "PHINS × Swiss Re Israel": "PHINS × Swiss Re ישראל",
    "Tuesday 8 December 2026 · Mr. Hillel Damelin, Regional CEO Israel · Israel pilot and the five-year plan":
        "יום שלישי, 8 בדצמבר 2026 · מר הלל דמלין, מנכ\"ל אזורי ישראל · הפיילוט בישראל ותוכנית החומש",
    "One regulated contract family — life with a lifelong ADL-3 disability mechanism, long-term care and a savings flow — carried by a licensed Israeli insurer and reinsured by quota share; PHINS is the technology and the administrator.":
        "משפחת חוזים מפוקחת אחת — ביטוח חיים עם מנגנון נכות ADL-3 לכל החיים, סיעוד וזרם חיסכון — הנישאת על ידי מבטח ישראלי מורשה ומבוטחת בביטוח משנה יחסי (quota share); PHINS היא הטכנולוגיה והמנהלת.",
    "A pilot in Israel from 1 January 2027 and a five-year plan to 2031. Every figure in this deck is a default of {plan_version} · hash {hash}…; nothing is typed by hand.":
        "פיילוט בישראל מ-1 בינואר 2027 ותוכנית חומש עד 2031. כל נתון במצגת זו הוא ברירת מחדל של {plan_version} · גיבוב {hash}…; דבר אינו מוקלד ביד.",
    "Why a reinsurer, why now": "למה מבטח משנה, ולמה עכשיו",
    "The pre-ruling track with the Capital Market, Insurance and Savings Authority opened on 12 October 2026; carrier and reinsurance term sheets are the Q4 2026 gate before any sale.":
        "מסלול הפרה-רולינג מול רשות שוק ההון, ביטוח וחיסכון נפתח ב-12 באוקטובר 2026; גיליונות תנאים עם המבטח ועם מבטח המשנה הם שער הרבעון הרביעי של 2026, לפני כל מכירה.",
    "Severe disability and long-term care are the protection gap public systems leave open. A quota share on a new, digitally underwritten book is the reinsurer's way into that gap without carrying distribution on its own balance sheet.":
        "נכות קשה וסיעוד הם פער ההגנה שהמערכות הציבוריות משאירות פתוח. ביטוח משנה יחסי על ספר חדש, המחותם דיגיטלית, הוא הדרך של מבטח המשנה אל הפער הזה בלי לשאת הפצה על המאזן שלו.",
    "The pilot in Israel — 2027": "הפיילוט בישראל — 2027",
    "Gate 5 — sales begin on 1 January 2027 on the licensed carrier's paper; Gate 6 — the first 1,000 policies in force with an Appointed Actuary review against the kernel; Gate 7 — {il_eoy_0} policies in force at year end.":
        "שער 5 — המכירות מתחילות ב-1 בינואר 2027 על הנייר של המבטח המורשה; שער 6 — 1,000 הפוליסות הראשונות בתוקף עם סקירת אקטואר ממונה מול הליבה; שער 7 — {il_eoy_0} פוליסות בתוקף בסוף השנה.",
    "Pilot-year risk GWP {il_gwp_0}; ceded premium at the plan's {cession} quota share {cv_ceded_0}; reinsurer technical result {re_result_0} ({re_result_usd_0} at planning FX {fx}).":
        "פרמיית סיכון ברוטו בשנת הפיילוט {il_gwp_0}; פרמיה מועברת בשיעור ההעברה של התוכנית {cession} — {cv_ceded_0}; תוצאה טכנית למבטח המשנה {re_result_0} ({re_result_usd_0} בשער תכנון {fx}).",
    "The contract the reinsurer underwrites": "החוזה שמבטח המשנה מחתם",
    "Life {il_face} with a lifelong disability mechanism — 1:4 below 65, 1:1 from 65 — on an objective ADL-3 trigger; published tables 0.25 / 0.20 per ₪1,000 monthly; {premium} a year at the age-42 specimen.":
        "ביטוח חיים {il_face} עם מנגנון נכות לכל החיים — 1:4 מתחת לגיל 65, 1:1 מגיל 65 — על טריגר ADL-3 אובייקטיבי; טבלאות מפורסמות 0.25 / 0.20 לכל ₪1,000 לחודש; {premium} לשנה בדוגמת גיל 42.",
    "One pricing kernel is the single writer for premium decomposition. Repricing runs through it at every gate, and the carrier view is restated on every plan refresh, so the reinsurer reads the same rows as the carrier and the Appointed Actuary.":
        "ליבת תמחור אחת היא הכותב היחיד של פירוק הפרמיה. תמחור מחדש עובר דרכה בכל שער, ומבט המבטח מוצג מחדש בכל רענון של התוכנית, כך שמבטח המשנה קורא את אותן שורות שקוראים המבטח והאקטואר הממונה.",
    "The ceded line — five years": "הקו המועבר — חמש שנים",
    "Ceded premium {cv_ceded_0} → {cv_ceded_2} → {cv_ceded_4} (2027 / 2029 / 2031); five-year ceded premium {re_ceded_5y} ({re_ceded_5y_usd}).":
        "פרמיה מועברת {cv_ceded_0} → {cv_ceded_2} → {cv_ceded_4} (2027 / 2029 / 2031); פרמיה מועברת לחמש שנים {re_ceded_5y} ({re_ceded_5y_usd}).",
    "Reinsurer technical result {re_result_0} → {re_result_2} → {re_result_4}; five years {re_result_5y} ({re_result_5y_usd}) — {re_margin} of ceded premium at the plan's {loss_ratio} expected claims and {ceding_commission} ceding commission; break-even claims ratio {re_breakeven}.":
        "תוצאה טכנית למבטח המשנה {re_result_0} → {re_result_2} → {re_result_4}; חמש שנים {re_result_5y} ({re_result_5y_usd}) — {re_margin} מהפרמיה המועברת ביחס תביעות צפוי של {loss_ratio} ועמלת העברה של {ceding_commission} לפי התוכנית; יחס תביעות לנקודת איזון {re_breakeven}.",
    "Quota-share options for the pilot": "חלופות ביטוח משנה יחסי לפיילוט",
    "The plan: {cession} cession, {ceding_commission} ceding commission, carrier margin {cv_margin_0}; the reinsurer's five-year technical result {re_result_5y}.":
        "התוכנית: העברה {cession}, עמלת העברה {ceding_commission}, מרווח מבטח {cv_margin_0}; התוצאה הטכנית לחמש שנים למבטח המשנה {re_result_5y}.",
    "Scenarios from the same model — at {re_qs30_label} cession the five-year ceded premium is {re_qs30_ceded_5y}, the technical result {re_qs30_result_5y} and the carrier margin {re_qs30_carrier_margin}; at {re_qs50_label} cession {re_qs50_ceded_5y}, {re_qs50_result_5y} and {re_qs50_carrier_margin}. PHINS revenue and EBITDA are unchanged in every scenario; the split between carrier and reinsurer is what moves.":
        "תרחישים מאותו מודל — בהעברה של {re_qs30_label} הפרמיה המועברת לחמש שנים היא {re_qs30_ceded_5y}, התוצאה הטכנית {re_qs30_result_5y} ומרווח המבטח {re_qs30_carrier_margin}; בהעברה של {re_qs50_label} — {re_qs50_ceded_5y}, {re_qs50_result_5y} ו-{re_qs50_carrier_margin}. הכנסות PHINS וה-EBITDA אינם משתנים באף תרחיש; מה שזז הוא החלוקה בין המבטח למבטח המשנה.",
    "Five-year plan — Israel anchor book": "תוכנית חומש — ספר העוגן בישראל",
    "Policies in force {il_eoy_0} → {il_eoy_1} → {il_eoy_2} → {il_eoy_3} → {il_eoy_4}; risk GWP {il_gwp_0} → {il_gwp_4}; five-year risk GWP {re_gwp_5y}.":
        "פוליסות בתוקף {il_eoy_0} → {il_eoy_1} → {il_eoy_2} → {il_eoy_3} → {il_eoy_4}; פרמיית סיכון ברוטו {il_gwp_0} → {il_gwp_4}; פרמיית סיכון ברוטו לחמש שנים {re_gwp_5y}.",
    "The savings flow — {il_savings_2} in 2029, {il_savings_4} in 2031 — is a separate licensed flow and is never split with the carrier or the reinsurer. The benefit is a lump sum with a fixed sum at risk, not a lifetime care annuity.":
        "זרם החיסכון — {il_savings_2} ב-2029, {il_savings_4} ב-2031 — הוא זרם מורשה נפרד ולעולם אינו מתחלק עם המבטח או עם מבטח המשנה. התגמול הוא סכום חד-פעמי עם סכום בסיכון קבוע, לא קצבת סיעוד לכל החיים.",
    "Five-year plan — the group": "תוכנית חומש — הקבוצה",
    "OECD partner markets under local licensed carriers: {pm_live_1} in 2028, {pm_live_2} in 2029, {pm_live_4} by 2031 — {markets_2031} markets on one platform, {g_eoy_4} group lives and {g_gwp_4} group risk GWP.":
        "שווקי שותפים ב-OECD תחת מבטחים מקומיים מורשים: {pm_live_1} ב-2028, {pm_live_2} ב-2029, {pm_live_4} עד 2031 — {markets_2031} שווקים על פלטפורמה אחת, {g_eoy_4} מבוטחים בקבוצה ו-{g_gwp_4} פרמיית סיכון ברוטו קבוצתית.",
    "A reinsurer that leads Israel can follow the same wording into each market. Group risk GWP × {cession} is {re_group_envelope_4} in 2031 ({re_group_envelope_4_usd}) — arithmetic on the group GWP row, not a model row.":
        "מבטח משנה שמוביל את ישראל יכול ללוות את אותו נוסח אל כל שוק. פרמיית הסיכון ברוטו של הקבוצה × {cession} היא {re_group_envelope_4} ב-2031 ({re_group_envelope_4_usd}) — חשבון על שורת פרמיית הקבוצה, לא שורת מודל.",
    "What PHINS asks of Swiss Re Israel": "מה PHINS מבקשת מ-Swiss Re ישראל",
    "Lead quota-share reinsurer for the Israel pilot: a non-binding indication on the plan's {cession} / {ceding_commission} structure by the Q4 2026 gate, and a technical review of the pricing kernel and the published tables under NDA.":
        "מבטח משנה מוביל בביטוח משנה יחסי לפיילוט בישראל: אינדיקציה לא מחייבת על מבנה {cession} / {ceding_commission} של התוכנית עד שער הרבעון הרביעי של 2026, וסקירה טכנית של ליבת התמחור והטבלאות המפורסמות תחת NDA.",
    "Beyond capacity, every option stays on the table — lead reinsurer and technical partner for the first partner market in 2028, a data-access arrangement on the evidence pipeline, or an equity conversation kept separate from the treaty. Never a linked price.":
        "מעבר לקיבולת, כל האפשרויות נשארות על השולחן — מבטח משנה מוביל ושותף טכני לשוק השותף הראשון ב-2028, הסדר גישה לנתונים על צינור הראיות, או שיחת אקוויטי המוחזקת בנפרד מהאמנה. לעולם לא מחיר מקושר.",
    "What Swiss Re sees — governance and data": "מה Swiss Re רואה — ממשל ונתונים",
    "Agents recommend, humans decide. Every underwriting and claims recommendation is logged with evidence provenance; thresholds move only through an audited promotion step; a contradiction between documents is recorded, never resolved by a bot.":
        "סוכנים ממליצים, בני אדם מחליטים. כל המלצת חיתום ותביעות נרשמת עם מקור הראיה; ספים זזים רק דרך שלב קידום מבוקר; סתירה בין מסמכים נרשמת ולעולם אינה מיושבת על ידי בוט.",
    "One hash-chained ledger, one identity writer, checksummed agent state. The reinsurer's bordereaux read from the same rows the carrier and the Appointed Actuary read.":
        "לדג'ר אחד בשרשרת גיבוב, כותב זהות אחד, מצב סוכנים מאומת בסיכום ביקורת. דוחות הבורדרו של מבטח המשנה נקראים מאותן שורות שקוראים המבטח והאקטואר הממונה.",
    "Capital and timeline": "הון ולוח זמנים",
    "Seed {seed} on {pre} pre-money ({post} post); Series A {series_a} indicative in 2028; group EBITDA positive in {first_positive}. The reinsurer's capacity carries the book; it does not fund PHINS.":
        "סיד {seed} על שווי {pre} לפני הכסף ({post} אחרי); סבב A {series_a} אינדיקטיבי ב-2028; EBITDA קבוצתי חיובי ב-{first_positive}. הקיבולת של מבטח המשנה נושאת את הספר; היא אינה מממנת את PHINS.",
    "12 October 2026 pre-ruling · Q4 2026 seed close and term sheets · 1 January 2027 sales begin · Q4 2027 Gate 7 · 2028 first partner market · 2031 {markets_2031} markets.":
        "12 באוקטובר 2026 פרה-רולינג · רבעון רביעי 2026 סגירת סיד וגיליונות תנאים · 1 בינואר 2027 תחילת מכירות · רבעון רביעי 2027 שער 7 · 2028 שוק שותף ראשון · 2031 {markets_2031} שווקים.",
    "Next steps after 8 December": "הצעדים הבאים אחרי 8 בדצמבר",
    "Proposed: within two weeks, NDA, data room and a kernel walkthrough with the Appointed Actuary; within six weeks, a non-binding indication on the quota share; before Gate 5, a signed term sheet with the carrier of record named.":
        "מוצע: בתוך שבועיים — NDA, חדר נתונים וסקירת ליבה עם האקטואר הממונה; בתוך שישה שבועות — אינדיקציה לא מחייבת על ביטוח המשנה היחסי; לפני שער 5 — גיליון תנאים חתום עם שם המבטח הרושם.",
    "Nothing is bound today. No limit, ticket or price is set in this deck; every figure regenerates from {plan_version}, and the plan is not written by this meeting.":
        "דבר אינו מחייב היום. במצגת זו לא נקבעים גבול, כרטיס או מחיר; כל נתון מופק מחדש מתוך {plan_version}, והתוכנית אינה נכתבת על ידי פגישה זו.",
    # The ceded-line chart
    "The ceded line — Israel anchor book (ILS)": "הקו המועבר — ספר העוגן בישראל (₪)",
    "Quota share {cession} · expected claims {loss_ratio} · ceding commission {ceding_commission}; technical result = ceded premium − ceded claims − ceding commission.":
        "ביטוח משנה יחסי {cession} · תביעות צפויות {loss_ratio} · עמלת העברה {ceding_commission}; תוצאה טכנית = פרמיה מועברת − תביעות מועברות − עמלת העברה.",
    "Ceded premium": "פרמיה מועברת",
    "Ceded claims": "תביעות מועברות",
    "Ceding commission": "עמלת העברה",
    "Technical result": "תוצאה טכנית",
    # Meeting strip and presentation chrome
    "Tuesday 8 December 2026": "יום שלישי, 8 בדצמבר 2026",
    "Mr. Hillel Damelin": "מר הלל דמלין",
    "Regional CEO, Israel — Swiss Re": "מנכ\"ל אזורי, ישראל — Swiss Re",
    "Swiss Re": "Swiss Re",
    "Israel pilot and the five-year plan — quota share, options, next steps":
        "הפיילוט בישראל ותוכנית החומש — ביטוח משנה יחסי, חלופות, צעדים הבאים",
    "Asaf Ashury, Adv. — Founder & CEO, PHINS Technologies": "עו\"ד אסף אשורי — מייסד ומנכ\"ל, PHINS Technologies",
    "Scheduled": "מתוכננת",
    "Swiss Re Israel · 8 December 2026": "Swiss Re ישראל · 8 בדצמבר 2026",
    # Factor panel
    "Reinsurance factors — a viewer scenario of the same model": "גורמי ביטוח המשנה — תרחיש צופה של אותו מודל",
    "Move a factor and every figure on the slides, the ceded line and the scenarios re-renders from the plan model under its own hash. The plan's saved factors are not written; the film is sealed to the plan, not to a scenario.":
        "הזיזו גורם — וכל נתון בשקפים, בקו המועבר ובתרחישים מופק מחדש ממודל התוכנית תחת גיבוב משלו. הגורמים השמורים של התוכנית אינם נכתבים; הסרט חתום לתוכנית, לא לתרחיש.",
    # Markdown pack
    "PHINS × Swiss Re Israel — Meeting Deck and Film Script (8 December 2026)":
        "PHINS × Swiss Re ישראל — מצגת הפגישה ותסריט הסרט (8 בדצמבר 2026)",
    "Internal · Confidential.": "פנימי · סודי.",
    "The presentation for the meeting with {counterpart}, {role}, on {date}: the Israel pilot from 1 January 2027 and the five-year plan to 2031, read from the reinsurer's seat. Every figure is a default of plan identity `{plan_version}` ({canonical}; content hash `{hash}…`) and regenerates from the same model as the unified business plan. Nothing is bound by this deck; no limit, ticket or price is set. The plan is not written by this meeting.":
        "המצגת לפגישה עם {counterpart}, {role}, {date}: הפיילוט בישראל מ-1 בינואר 2027 ותוכנית החומש עד 2031, נקראים ממושב מבטח המשנה. כל נתון הוא ברירת מחדל של זהות התוכנית `{plan_version}` ({canonical}; גיבוב תוכן `{hash}…`) ומופק מחדש מאותו מודל כמו התוכנית העסקית המאוחדת. דבר אינו מחייב במצגת זו; לא נקבעים גבול, כרטיס או מחיר. התוכנית אינה נכתבת על ידי פגישה זו.",
    "Meeting facts": "פרטי הפגישה",
    "Item": "פריט",
    "Detail": "פירוט",
    "Date": "תאריך",
    "Counterpart": "הצד שכנגד",
    "PHINS": "PHINS",
    "Subject": "נושא",
    "Format": "מתכונת",
    "{n} slides · one 15-second scene per paragraph · short film plays the filmed scenes in order":
        "{n} שקפים · סצנה אחת של 15 שניות לכל פסקה · הסרט הקצר מנגן את הסצנות המצולמות לפי הסדר",
    "Pack": "חבילה",
    "`{page}` (presentation + script sheet) · pitch dashboard — Swiss Re Israel 8.12 section · Group CEO assessment (7 Nov) · unified business plan Appendix B":
        "`{page}` (מצגת + דף תסריט) · לוח הפיץ' — מקטע Swiss Re ישראל 8.12 · הערכת מנכ\"ל הקבוצה (7 בנובמבר) · נספח ב׳ לתוכנית העסקית המאוחדת",
    "Status": "סטטוס",
    "The ceded line the reinsurer sees — Israel anchor book, default factors":
        "הקו המועבר שמבטח המשנה רואה — ספר העוגן בישראל, גורמי ברירת מחדל",
    "Quota share {cession} · expected claims {loss_ratio} · ceding commission {ceding_commission}. Technical result = ceded premium − ceded claims − ceding commission = {margin} of ceded premium; break-even claims ratio {breakeven}.":
        "ביטוח משנה יחסי {cession} · תביעות צפויות {loss_ratio} · עמלת העברה {ceding_commission}. תוצאה טכנית = פרמיה מועברת − תביעות מועברות − עמלת העברה = {margin} מהפרמיה המועברת; יחס תביעות לנקודת איזון {breakeven}.",
    "Year": "שנה",
    "Risk GWP": "פרמיית סיכון ברוטו",
    "Result (USD, planning FX)": "תוצאה (דולר, שער תכנון)",
    "Five years": "חמש שנים",
    "Quota-share options for the pilot — scenarios of the same model": "חלופות ביטוח משנה יחסי לפיילוט — תרחישים של אותו מודל",
    "The plan's cession is the reference. Each alternative is `compute_plan` with the current inputs and a different `cession_rate`; it carries its own content hash and is labelled a scenario. PHINS revenue and EBITDA do not move with the cession; the carrier's result does.":
        "שיעור ההעברה של התוכנית הוא הייחוס. כל חלופה היא `compute_plan` עם הקלטים הנוכחיים ו-`cession_rate` שונה; היא נושאת גיבוב תוכן משלה ומסומנת כתרחיש. הכנסות PHINS וה-EBITDA אינם זזים עם שיעור ההעברה; תוצאת המבטח כן.",
    "{cession} (plan)": "{cession} (התוכנית)",
    "Cession": "שיעור העברה",
    "Ceded premium 2027": "פרמיה מועברת 2027",
    "Technical result 2027": "תוצאה טכנית 2027",
    "Ceded premium 5y": "פרמיה מועברת 5 שנים",
    "Technical result 5y": "תוצאה טכנית 5 שנים",
    "Carrier margin": "מרווח מבטח",
    "PHINS revenue 5y": "הכנסות PHINS 5 שנים",
    "Plan identity": "זהות התוכנית",
    "Adjustable reinsurance factors": "גורמי ביטוח משנה מתכווננים",
    "On `{page}` a viewer may move these factors of the plan's own register. The result is the same model under its own hash, labelled a scenario; a value outside the register's range is refused; the saved factors are not written and the film stays sealed to the plan.":
        "ב-`{page}` צופה יכול להזיז את הגורמים הללו ממרשם התוכנית עצמו. התוצאה היא אותו מודל תחת גיבוב משלו, מסומן כתרחיש; ערך מחוץ לטווח המרשם נדחה; הגורמים השמורים אינם נכתבים והסרט נשאר חתום לתוכנית.",
    "Factor": "גורם",
    "Plan value": "ערך התוכנית",
    "Range": "טווח",
    "Slides and film script": "שקפים ותסריט הסרט",
    "One 15-second scene per paragraph. A paragraph with no figure is spoken in full; a paragraph that fills a figure is spoken as a short line and its figures stay on the slide. Presenters come from the shared roster and are assigned when a scene is filmed; charts are the plan's own and are shown beside the clip, never drawn by the generator.":
        "סצנה אחת של 15 שניות לכל פסקה. פסקה ללא נתון נאמרת במלואה; פסקה שממלאת נתון נאמרת כשורה קצרה והנתונים שלה נשארים על השקף. המגישים מגיעים מהסגל המשותף ומשובצים כשסצנה מצולמת; התרשימים הם של התוכנית עצמה ומוצגים לצד הקליפ, לעולם לא מצוירים על ידי המחולל.",
    "Slide {n} — {title}": "שקף {n} — {title}",
    "Chart beside the clip: `{chart}`.": "תרשים לצד הקליפ: `{chart}`.",
    "Paragraph {n} · scene `{key}` · {seconds} s": "פסקה {n} · סצנה `{key}` · {seconds} שניות",
    "On the slide: {text}": "על השקף: {text}",
    "Spoken: {text}": "נאמר: {text}",
    "Presenter: {text}": "מגיש/ה: {text}",
    "Data integrity": "שלמות הנתונים",
    "Every PHINS figure in this pack is read from plan identity `{plan_version}` (content hash `{hash}`). The reinsurer line is an identity on the plan's carrier rows: 2027 ceded premium {gwp} × {cession} = {ceded}; ceded claims {claims}; ceding commission {commission}; technical result {result}. Technical margin 1 − {loss_ratio} − {ceding_commission} = {margin}; break-even 1 − {ceding_commission} = {breakeven}. The group envelope is group risk GWP × cession, arithmetic on a model row and not a model row. The quota-share scenarios are the same model with a different cession and are labelled as scenarios with their own hashes. This pack is generated from the model by `scripts/build_reinsurer_deck_brief.py` and is never hand-edited. It does not write the platform ledger.":
        "כל נתון של PHINS בחבילה זו נקרא מזהות התוכנית `{plan_version}` (גיבוב תוכן `{hash}`). קו מבטח המשנה הוא זהות על שורות המבטח בתוכנית: פרמיה מועברת 2027 {gwp} × {cession} = {ceded}; תביעות מועברות {claims}; עמלת העברה {commission}; תוצאה טכנית {result}. מרווח טכני 1 − {loss_ratio} − {ceding_commission} = {margin}; נקודת איזון 1 − {ceding_commission} = {breakeven}. מעטפת הקבוצה היא פרמיית הסיכון ברוטו של הקבוצה × שיעור ההעברה — חשבון על שורת מודל ולא שורת מודל. תרחישי ביטוח המשנה היחסי הם אותו מודל עם שיעור העברה שונה ומסומנים כתרחישים עם גיבובים משלהם. חבילה זו מופקת מהמודל על ידי `scripts/build_reinsurer_deck_brief.py` ולעולם אינה נערכת ביד. היא אינה כותבת את לדג'ר הפלטפורמה.",
}


# ---------------------------------------------------------------------------
# Reinsurer view — derived by identity from the plan's carrier rows
# ---------------------------------------------------------------------------
def _scenario_key(cession: float) -> str:
    return f"qs{int(round(cession * 100)):02d}"


def reinsurer_view(plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Ceded line, totals, margins, group envelope and quota-share scenarios.

    Nothing here is a new assumption: every number is an identity on rows the
    plan already carries, or the same model run with a different cession.
    """
    inputs = plan["inputs"]
    fx = float(plan["presentation"]["fx_usd_ils"])
    cession = float(inputs["cession_rate"])
    loss_ratio = float(inputs["expected_loss_ratio"])
    commission_rate = float(inputs["ceding_commission"])
    carrier_rows = list(plan["carrier_view"]["rows"])
    group_rows = list(plan["group"]["rows"])
    anchor_rows = list(plan["anchor_book"]["rows"])

    rows: List[Dict[str, Any]] = []
    for carrier, group, anchor in zip(carrier_rows, group_rows, anchor_rows):
        ceded_premium = float(carrier["ceded_premium"])
        ceded_claims = float(carrier["ceded_claims"])
        commission = float(carrier["ceding_commission"])
        rows.append({
            "year": int(carrier["year"]),
            "risk_gwp": float(carrier["risk_gwp"]),
            "ceded_premium": ceded_premium,
            "ceded_claims": ceded_claims,
            "ceding_commission": commission,
            "technical_result": ceded_premium - ceded_claims - commission,
            "carrier_result": float(carrier["carrier_result"]),
            "carrier_margin": float(carrier["carrier_margin"]),
            "savings_flow": float(anchor["savings_flow"]),
            "group_risk_gwp": float(group["risk_gwp"]),
            "group_envelope": float(group["risk_gwp"]) * cession,
        })

    def _total(field: str) -> float:
        return float(sum(row[field] for row in rows))

    totals = {
        "risk_gwp": _total("risk_gwp"),
        "ceded_premium": _total("ceded_premium"),
        "ceded_claims": _total("ceded_claims"),
        "ceding_commission": _total("ceding_commission"),
        "technical_result": _total("technical_result"),
        "savings_flow": _total("savings_flow"),
    }

    scenarios: List[Dict[str, Any]] = []
    for alt in SCENARIO_CESSIONS:
        overrides = dict(inputs)
        overrides["cession_rate"] = alt
        alt_plan = compute_plan(overrides)
        alt_rows = alt_plan["carrier_view"]["rows"]
        ceded_5y = float(sum(r["ceded_premium"] for r in alt_rows))
        result_5y = float(sum(
            r["ceded_premium"] - r["ceded_claims"] - r["ceding_commission"] for r in alt_rows
        ))
        scenarios.append({
            "key": _scenario_key(alt),
            "cession_rate": alt,
            "ceded_premium_2027": float(alt_rows[0]["ceded_premium"]),
            "technical_result_2027": float(
                alt_rows[0]["ceded_premium"] - alt_rows[0]["ceded_claims"] - alt_rows[0]["ceding_commission"]
            ),
            "ceded_premium_5y": ceded_5y,
            "technical_result_5y": result_5y,
            "carrier_margin": float(alt_rows[0]["carrier_margin"]),
            "phins_revenue_5y": float(sum(r["phins_revenue"] for r in alt_plan["group"]["rows"])),
            "group_ebitda_5y": float(sum(r["ebitda"] for r in alt_plan["group"]["rows"])),
            "content_hash": str(alt_plan.get("content_hash") or ""),
            "canonical": bool(alt_plan.get("canonical")),
            "integrity_all_hold": (alt_plan.get("integrity") or {}).get("all_hold") is True,
        })

    return {
        "fx_usd_ils": fx,
        "cession_rate": cession,
        "expected_loss_ratio": loss_ratio,
        "ceding_commission": commission_rate,
        # Technical margin on ceded premium and the claims ratio at which the
        # reinsurer's result is zero, both identities on the two ratios.
        "technical_margin": 1.0 - loss_ratio - commission_rate,
        "breakeven_claims_ratio": 1.0 - commission_rate,
        "rows": rows,
        "totals": totals,
        "scenarios": scenarios,
        "phins_revenue_5y": float(sum(r["phins_revenue"] for r in group_rows)),
        "group_ebitda_5y": float(sum(r["ebitda"] for r in group_rows)),
    }


def reinsurer_figures(plan: Mapping[str, Any]) -> Dict[str, Tuple[Any, str]]:
    """``{re_*}`` placeholder → (value, format kind)."""
    view = reinsurer_view(plan)
    figures: Dict[str, Tuple[Any, str]] = {
        "re_margin": (view["technical_margin"], "pct"),
        "re_breakeven": (view["breakeven_claims_ratio"], "pct"),
        "re_gwp_5y": (view["totals"]["risk_gwp"], "ilsm"),
        "re_ceded_5y": (view["totals"]["ceded_premium"], "ilsm"),
        "re_ceded_5y_usd": (view["totals"]["ceded_premium"], "usdm"),
        "re_ceded_claims_5y": (view["totals"]["ceded_claims"], "ilsm"),
        "re_commission_5y": (view["totals"]["ceding_commission"], "ilsm"),
        "re_result_5y": (view["totals"]["technical_result"], "ilsm"),
        "re_result_5y_usd": (view["totals"]["technical_result"], "usdm"),
        "re_savings_5y": (view["totals"]["savings_flow"], "ilsm"),
    }
    for index, row in enumerate(view["rows"]):
        figures[f"re_result_{index}"] = (row["technical_result"], "ilsm")
        figures[f"re_result_usd_{index}"] = (row["technical_result"], "usdm")
        figures[f"re_group_envelope_{index}"] = (row["group_envelope"], "ilsm")
        figures[f"re_group_envelope_{index}_usd"] = (row["group_envelope"], "usdm")
    for scenario in view["scenarios"]:
        key = scenario["key"]
        figures[f"re_{key}_label"] = (scenario["cession_rate"], "pct")
        figures[f"re_{key}_ceded_0"] = (scenario["ceded_premium_2027"], "ilsm")
        figures[f"re_{key}_result_0"] = (scenario["technical_result_2027"], "ilsm")
        figures[f"re_{key}_ceded_5y"] = (scenario["ceded_premium_5y"], "ilsm")
        figures[f"re_{key}_result_5y"] = (scenario["technical_result_5y"], "ilsm")
        figures[f"re_{key}_carrier_margin"] = (scenario["carrier_margin"], "pct1")
        figures[f"re_{key}_hash"] = (scenario["content_hash"], "hash")
    return figures


_RE_PLACEHOLDER = re.compile(r"\{(re_[a-z_0-9]+)\}")


def fill_reinsurer_figures(text: str, plan: Mapping[str, Any]) -> str:
    """Substitute the ``{re_*}`` keys. Unknown ``re_`` keys stay as written."""
    if FIGURE_PREFIX not in text:
        return text
    figures = reinsurer_figures(plan)
    fx = float(plan["presentation"]["fx_usd_ils"])

    def repl(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in figures:
            return match.group(0)
        value, kind = figures[key]
        return fmt(value, kind, fx)

    return _RE_PLACEHOLDER.sub(repl, text)


def fill(text: str, plan: Mapping[str, Any]) -> str:
    """Translate once, then reinsurer keys, then the document's own registry.

    The document filler translates the text it is given; a sentence that is
    already half filled with figures is not a dictionary row, so that second
    pass runs on a throwaway translator of the same language and records no
    miss, while ``fmt`` inside it still speaks the render's language.
    """
    speak = _current_translator()
    translated = speak(str(text or ""))
    with language_context(Translator(speak.lang, table=speak.table)):
        return _fill(fill_reinsurer_figures(translated, plan), plan, False).strip()


# ---------------------------------------------------------------------------
# Adjustable reinsurance factors — a viewer scenario, never a write
# ---------------------------------------------------------------------------
def allowed_factors(whitelist: Any = None) -> List[str]:
    """The reinsurance factors this viewer may move.

    ``whitelist`` is the ``viewer_adjustable`` frozen on a share link (a list
    of factor ids) or ``None`` / ``"all"`` for staff; the result is always a
    subset of :data:`ADJUSTABLE_FACTORS`, in register order.
    """
    if isinstance(whitelist, (list, tuple, set, frozenset)):
        wanted = {str(item) for item in whitelist}
        return [fid for fid in ADJUSTABLE_FACTORS if fid in wanted]
    return list(ADJUSTABLE_FACTORS)


def scenario_overrides(
    query: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any],
    allowed: Sequence[str],
) -> Dict[str, Any]:
    """Resolve the viewer's factor moves over the baseline factor set.

    Returns ``effective`` (the full factor set to compute), ``adjusted``
    (only the factors the viewer actually moved), ``restricted`` (factors the
    query tried to move but this viewer may not) and ``errors`` (values the
    register refuses — out of range or not numeric). A refused value is never
    clamped into range; the caller declines the scenario.
    """
    effective: Dict[str, float] = {}
    for fid, spec in FACTOR_INDEX.items():
        raw = baseline.get(fid, spec["default"]) if isinstance(baseline, Mapping) else spec["default"]
        try:
            effective[fid] = float(raw)
        except (TypeError, ValueError):
            effective[fid] = float(spec["default"])
    adjusted: Dict[str, float] = {}
    restricted: List[str] = []
    errors: List[str] = []
    permitted = set(allowed)
    for fid in FACTOR_INDEX:
        raw = (query or {}).get(fid)
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        if raw is None or str(raw).strip() == "":
            continue
        if fid not in permitted:
            restricted.append(fid)
            continue
        value, err = _coerce(fid, raw)
        if err:
            errors.append(err)
            continue
        if value is None or abs(float(value) - effective[fid]) < 1e-12:
            continue
        effective[fid] = float(value)
        adjusted[fid] = float(value)
    return {"effective": effective, "adjusted": adjusted, "restricted": restricted, "errors": errors}


def factor_panel(
    plan: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any],
    allowed: Sequence[str],
    lang: str = "en",
) -> List[Dict[str, Any]]:
    """The register rows behind the deck's factor panel, with current values."""
    speak = translator_for(lang)
    inputs = plan.get("inputs") or {}
    permitted = set(allowed)
    rows: List[Dict[str, Any]] = []
    for fid in ADJUSTABLE_FACTORS:
        spec = FACTOR_INDEX[fid]
        value = float(inputs.get(fid, spec["default"]))
        base = float(baseline.get(fid, spec["default"])) if isinstance(baseline, Mapping) else float(spec["default"])
        rows.append({
            "id": fid,
            "label": speak(str(spec["label"])),
            "note": speak(str(spec["note"])) if spec.get("note") else "",
            "kind": str(spec["kind"]),
            "min": float(spec["min"]),
            "max": float(spec["max"]),
            "step": float(spec["step"]),
            "default": float(spec["default"]),
            "baseline": base,
            "value": value,
            "value_text": fmt(value, "pct" if spec["kind"] == "ratio" else "num2"),
            "adjustable": fid in permitted,
            "adjusted": abs(value - base) > 1e-12,
        })
    return rows


def placeholder_keys() -> List[str]:
    keys: set = set()
    for slide in deck_slides():
        keys.update(_PLACEHOLDER.findall(str(slide.get("kicker") or "")))
        for bullet in slide["bullets"]:
            keys.update(_PLACEHOLDER.findall(bullet))
    keys.discard("il_face")
    return sorted(keys)


# ---------------------------------------------------------------------------
# Scene catalog — one row per paragraph, keys ``re-sNNpNN``
# ---------------------------------------------------------------------------
def scene_storage_key(slide_no: int, paragraph_no: int, lang: str = "en") -> str:
    """English keys are ``re-sNNpNN``; Hebrew keys are ``re-he-sNNpNN``."""
    prefix = HEBREW_SCENE_KEY_PREFIX if normalize_lang(lang) == "he" else SCENE_KEY_PREFIX
    return f"{prefix}s{int(slide_no):02d}p{int(paragraph_no):02d}"


def is_reinsurer_scene_key(key: Any) -> bool:
    return str(key or "").startswith(SCENE_KEY_PREFIX)


def lang_of_scene_key(key: Any) -> str:
    return "he" if str(key or "").startswith(HEBREW_SCENE_KEY_PREFIX) else "en"


def store_name_for_lang(lang: str = "en") -> str:
    return STORE_NAME_HE if normalize_lang(lang) == "he" else STORE_NAME


def store_name_for_key(key: Any) -> str:
    """The design-settings store a reinsurer scene lives in, by its key."""
    return store_name_for_lang(lang_of_scene_key(key))


def page_path_for_lang(lang: str = "en") -> str:
    return PAGE_PATH_HE if normalize_lang(lang) == "he" else PAGE_PATH


def catalog(lang: str = "en") -> List[Dict[str, Any]]:
    """One row per deck bullet; the shape the investor-deck machinery reads.

    ``lang="he"`` is the Hebrew edition of the same bullets under Hebrew
    keys. A missing Hebrew sentence refuses the whole catalog, so English is
    never filmed under a Hebrew key.
    """
    from services.investor_deck_video import InvestorDeckError, campaign_id_for

    language = normalize_lang(lang)
    speak = translator_for(language)
    before = set(speak.misses)
    rows: List[Dict[str, Any]] = []
    for slide_no, slide in enumerate(deck_slides(), 1):
        title_en = str(slide.get("title") or "")
        bullets = list(slide.get("bullets") or [])
        chart_id = str(SLIDE_CHARTS.get(title_en) or "")
        raw_kicker = str(slide.get("kicker") or "")
        for paragraph_no, template in enumerate(bullets, 1):
            key = scene_storage_key(slide_no, paragraph_no, language)
            rows.append({
                "scene_key": key,
                "deck": DECK_ID,
                "lang": language,
                "slide_no": slide_no,
                "paragraph_no": paragraph_no,
                "paragraph_count": len(bullets),
                "slide_title": speak(title_en),
                "kicker": speak(raw_kicker) if raw_kicker else "",
                "template": speak(str(template)),
                "chart_id": chart_id,
                "photo": "",
                "campaign_id": campaign_id_for(key),
                "duration_seconds": SCENE_SECONDS,
            })
    missing = set(speak.misses) - before
    if language == "he" and missing:
        raise InvestorDeckError(
            "Hebrew deck text is incomplete. Nothing was prepared. "
            f"Missing {len(missing)} sentence(s)."
        )
    return rows


def spec_for(key: str) -> Optional[Dict[str, Any]]:
    wanted = str(key or "").strip()
    if not is_reinsurer_scene_key(wanted):
        return None
    for row in catalog(lang_of_scene_key(wanted)):
        if row["scene_key"] == wanted:
            return dict(row)
    return None


def chart_ids() -> List[str]:
    seen: List[str] = []
    for spec in catalog():
        chart_id = spec.get("chart_id") or ""
        if chart_id and chart_id not in seen:
            seen.append(chart_id)
    return seen


def slide_specs(lang: str = "en") -> List[Dict[str, Any]]:
    language = normalize_lang(lang)
    rows: List[Dict[str, Any]] = []
    seen: Dict[int, Dict[str, Any]] = {}
    for scene in catalog(language):
        number = int(scene["slide_no"])
        row = seen.get(number)
        if row is None:
            row = {
                "slide_no": number,
                "title": str(scene.get("slide_title") or ""),
                "kicker": str(scene.get("kicker") or ""),
                "bullets": [],
                "chart_id": str(scene.get("chart_id") or ""),
                "photo": "",
                "lang": language,
            }
            seen[number] = row
            rows.append(row)
        row["bullets"].append(str(scene.get("template") or ""))
    return rows


# ---------------------------------------------------------------------------
# Charts — the plan's own, plus the ceded line
# ---------------------------------------------------------------------------
def ceded_line_chart(plan: Mapping[str, Any]) -> Dict[str, Any]:
    view = reinsurer_view(plan)
    years = [str(row["year"]) for row in view["rows"]]
    return {
        "id": "ceded_line", "kind": "grouped_bars", "unit": "ilsm",
        "title": _T("The ceded line — Israel anchor book (ILS)"),
        "subtitle": _T(
            "Quota share {cession} · expected claims {loss_ratio} · ceding commission {ceding_commission}; "
            "technical result = ceded premium − ceded claims − ceding commission."
        ).format(
            cession=fmt(view["cession_rate"], "pct"),
            loss_ratio=fmt(view["expected_loss_ratio"], "pct"),
            ceding_commission=fmt(view["ceding_commission"], "pct"),
        ),
        "categories": years,
        "series": [
            {"label": _T("Ceded premium"), "color": NAVY, "values": [r["ceded_premium"] for r in view["rows"]]},
            {"label": _T("Ceded claims"), "color": GREY, "values": [r["ceded_claims"] for r in view["rows"]]},
            {"label": _T("Ceding commission"), "color": GOLD_DEEP, "values": [r["ceding_commission"] for r in view["rows"]]},
            {"label": _T("Technical result"), "color": GOLD, "values": [r["technical_result"] for r in view["rows"]]},
        ],
        "source": "carrier_view.rows[].ceded_premium, ceded_claims, ceding_commission (identity)",
    }


def chart_spec(plan: Mapping[str, Any], chart_id: str, lang: str = "en") -> Dict[str, Any]:
    with language_context(translator_for(lang)):
        if chart_id == "ceded_line":
            return ceded_line_chart(plan)
        return chart_by_id(plan, chart_id)


def charts(plan: Mapping[str, Any], lang: str = "en") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    with language_context(translator_for(lang)):
        for chart_id in chart_ids():
            spec = chart_spec(plan, chart_id, lang)
            out[chart_id] = {"id": chart_id, "title": str(spec.get("title") or ""), "svg": render_svg(spec)}
    return out


# ---------------------------------------------------------------------------
# Presentation — slides filled here and nowhere written back
# ---------------------------------------------------------------------------
def _scripts_for_slide(slide_no: int, scenes: Optional[Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in scenes or []:
        if not isinstance(item, Mapping):
            continue
        try:
            number = int(item.get("slide_no") or 0)
        except (TypeError, ValueError):
            continue
        if number != slide_no:
            continue
        rows.append({
            "scene_key": str(item.get("scene_key") or ""),
            "paragraph_no": int(item.get("paragraph_no") or 0),
            "spoken": str(item.get("script") or ""),
            "on_slide": str(item.get("narration") or ""),
            "presenter_label": str(item.get("presenter_label") or ""),
            "duration_seconds": SCENE_SECONDS,
            "in_stream": bool(item.get("in_stream")),
            "playback_url": str(item.get("playback_url") or "") if item.get("in_stream") else "",
            "figures_current": bool(item.get("figures_current")),
            "stored": bool(item.get("stored")),
            # A broken seal is refused by the same send path the lab uses.
            "integrity_ok": item.get("integrity_ok") is not False,
        })
    rows.sort(key=lambda row: row["paragraph_no"])
    return rows


def presentation_of(
    plan: Mapping[str, Any],
    scenes: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    chart_svgs: Optional[Mapping[str, Any]] = None,
    lang: str = "en",
    factors: Optional[Sequence[Mapping[str, Any]]] = None,
    scenario: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The deck as slides, with the film script for each slide.

    ``factors`` is the panel from :func:`factor_panel`; ``scenario`` describes
    a viewer adjustment (``adjusted``, ``baseline_content_hash``). Neither is
    written anywhere; the plan passed in is the one the figures come from.
    """
    from services.investor_deck_video import _chart_svg, _filmed_for_slide

    language = normalize_lang(lang)
    speak = translator_for(language)
    slides: List[Dict[str, Any]] = []
    for spec in slide_specs(language):
        number = int(spec["slide_no"])
        chart_id = str(spec.get("chart_id") or "")
        slides.append({
            "slide_no": number,
            "title": str(spec.get("title") or ""),
            "kicker": fill(str(spec.get("kicker") or ""), plan),
            "bullets": [fill(bullet, plan) for bullet in spec.get("bullets") or []],
            "chart_id": chart_id,
            "chart_svg": _chart_svg(chart_svgs, chart_id),
            "photo": "",
            "photo_url": "",
            "media": {"asset_id": "", "playback_url": "", "name": "", "intact": False, "withheld": False},
            "filmed": _filmed_for_slide(number, scenes),
            "script": _scripts_for_slide(number, scenes),
        })
    view = reinsurer_view(plan)
    # The film is at most one 15-second scene per catalogued paragraph; the
    # stream plays only the scenes that are filmed and still current.
    scene_total = len(catalog(language))
    adjusted = dict((scenario or {}).get("adjusted") or {})
    return {
        "deck": DECK_ID,
        "part": speak("Swiss Re Israel · 8 December 2026"),
        "lang": language,
        "page_path": page_path_for_lang(language),
        "meeting": meeting_facts(language),
        "slide_count": len(slides),
        "scene_count": scene_total,
        "film_seconds_max": SCENE_SECONDS * scene_total,
        "filmed_count": sum(1 for slide in slides for row in slide["script"] if row["in_stream"]),
        "slides": slides,
        "reinsurer_view": view,
        "factors": [dict(row) for row in (factors or [])],
        "adjustable": [row["id"] for row in (factors or []) if row.get("adjustable")],
        "scenario": {
            "active": bool(adjusted),
            "adjusted": adjusted,
            "restricted": list((scenario or {}).get("restricted") or []),
            "baseline_content_hash": str((scenario or {}).get("baseline_content_hash") or ""),
            "baseline_source": str((scenario or {}).get("baseline_source") or ""),
            "content_hash": str(plan.get("content_hash") or ""),
            "canonical": bool(plan.get("canonical")),
            "plan_version": str(plan.get("plan_version") or ""),
        },
        "watermark": {"images": [], "intact": False, "withheld": False},
    }


# ---------------------------------------------------------------------------
# Markdown edition — the meeting pack, generated, never hand-edited
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_markdown(
    plan: Mapping[str, Any],
    scenes: Optional[Sequence[Mapping[str, Any]]] = None,
    lang: str = "en",
) -> str:
    """Slides, spoken scripts, the ceded line and the scenarios as one brief.

    ``lang="he"`` is the Hebrew edition: the same tables, the same figures,
    the Hebrew sentences, Hebrew scene keys.
    """
    language = normalize_lang(lang)
    with language_context(translator_for(language)):
        return _render_markdown(plan, scenes, language)


def _render_markdown(plan: Mapping[str, Any], scenes: Optional[Sequence[Mapping[str, Any]]], language: str) -> str:
    from services.investor_deck_video import short_script

    view = reinsurer_view(plan)
    fx = view["fx_usd_ils"]
    money = lambda value: fmt(value, "ilsm", fx)  # noqa: E731
    usd = lambda value: fmt(value, "usdm", fx)  # noqa: E731
    pct = lambda value: fmt(value, "pct", fx)  # noqa: E731
    plan_version = str(plan.get("plan_version") or "")
    content_hash = str(plan.get("content_hash") or "")
    canonical = fmt(plan.get("canonical"), "canonical")
    meeting = meeting_facts(language)
    page = page_path_for_lang(language)

    out: List[str] = []
    out.append("# " + _T("PHINS × Swiss Re Israel — Meeting Deck and Film Script (8 December 2026)"))
    out.append("")
    out.append(
        "> **" + _T("Internal · Confidential.") + "** " + _T(
            "The presentation for the meeting with {counterpart}, {role}, on {date}: the Israel pilot from "
            "1 January 2027 and the five-year plan to 2031, read from the reinsurer's seat. Every figure is a "
            "default of plan identity `{plan_version}` ({canonical}; content hash `{hash}…`) and regenerates from "
            "the same model as the unified business plan. Nothing is bound by this deck; no limit, ticket or price "
            "is set. The plan is not written by this meeting."
        ).format(
            counterpart=meeting["counterpart"], role=meeting["counterpart_role"], date=meeting["date_text"],
            plan_version=plan_version, canonical=canonical, hash=content_hash[:16],
        )
    )
    out.append("")
    out.append("## " + _T("Meeting facts"))
    out.append("")
    out.append(_md_table(
        [_T("Item"), _T("Detail")],
        [
            [_T("Date"), meeting["date_text"]],
            [_T("Counterpart"), f"{meeting['counterpart']} — {meeting['counterpart_role']}"],
            [_T("PHINS"), meeting["phins_side"]],
            [_T("Subject"), meeting["subject"]],
            [_T("Format"), _T("{n} slides · one 15-second scene per paragraph · short film plays the filmed scenes in order").format(n=len(slide_specs(language)))],
            [_T("Pack"), _T("`{page}` (presentation + script sheet) · pitch dashboard — Swiss Re Israel 8.12 section · Group CEO assessment (7 Nov) · unified business plan Appendix B").format(page=page)],
            [_T("Status"), meeting["status"]],
        ],
    ))
    out.append("")
    out.append("## " + _T("The ceded line the reinsurer sees — Israel anchor book, default factors"))
    out.append("")
    out.append(_T(
        "Quota share {cession} · expected claims {loss_ratio} · ceding commission {ceding_commission}. Technical "
        "result = ceded premium − ceded claims − ceding commission = {margin} of ceded premium; break-even claims "
        "ratio {breakeven}."
    ).format(
        cession=pct(view["cession_rate"]), loss_ratio=pct(view["expected_loss_ratio"]),
        ceding_commission=pct(view["ceding_commission"]), margin=pct(view["technical_margin"]),
        breakeven=pct(view["breakeven_claims_ratio"]),
    ))
    out.append("")
    rows = [
        [str(r["year"]), money(r["risk_gwp"]), money(r["ceded_premium"]), money(r["ceded_claims"]),
         money(r["ceding_commission"]), money(r["technical_result"]), usd(r["technical_result"])]
        for r in view["rows"]
    ]
    totals = view["totals"]
    rows.append([
        _T("Five years"), money(totals["risk_gwp"]), money(totals["ceded_premium"]), money(totals["ceded_claims"]),
        money(totals["ceding_commission"]), money(totals["technical_result"]), usd(totals["technical_result"]),
    ])
    out.append(_md_table(
        [_T("Year"), _T("Risk GWP"), _T("Ceded premium"), _T("Ceded claims"), _T("Ceding commission"),
         _T("Technical result"), _T("Result (USD, planning FX)")],
        rows,
    ))
    out.append("")
    out.append("## " + _T("Quota-share options for the pilot — scenarios of the same model"))
    out.append("")
    out.append(_T(
        "The plan's cession is the reference. Each alternative is `compute_plan` with the current inputs and a "
        "different `cession_rate`; it carries its own content hash and is labelled a scenario. PHINS revenue and "
        "EBITDA do not move with the cession; the carrier's result does."
    ))
    out.append("")
    scenario_rows = [[
        _T("{cession} (plan)").format(cession=pct(view["cession_rate"])), money(view["rows"][0]["ceded_premium"]),
        money(view["rows"][0]["technical_result"]), money(totals["ceded_premium"]), money(totals["technical_result"]),
        fmt(view["rows"][0]["carrier_margin"], "pct1"), money(view["phins_revenue_5y"]), f"`{content_hash[:12]}` · {canonical}",
    ]]
    for scenario in view["scenarios"]:
        scenario_rows.append([
            pct(scenario["cession_rate"]), money(scenario["ceded_premium_2027"]), money(scenario["technical_result_2027"]),
            money(scenario["ceded_premium_5y"]), money(scenario["technical_result_5y"]),
            fmt(scenario["carrier_margin"], "pct1"), money(scenario["phins_revenue_5y"]),
            f"`{scenario['content_hash'][:12]}` · {fmt(scenario['canonical'], 'canonical')}",
        ])
    out.append(_md_table(
        [_T("Cession"), _T("Ceded premium 2027"), _T("Technical result 2027"), _T("Ceded premium 5y"),
         _T("Technical result 5y"), _T("Carrier margin"), _T("PHINS revenue 5y"), _T("Plan identity")],
        scenario_rows,
    ))
    out.append("")
    out.append("## " + _T("Adjustable reinsurance factors"))
    out.append("")
    out.append(_T(
        "On `{page}` a viewer may move these factors of the plan's own register. The result is the same model under "
        "its own hash, labelled a scenario; a value outside the register's range is refused; the saved factors are "
        "not written and the film stays sealed to the plan."
    ).format(page=page))
    out.append("")
    panel = factor_panel(plan, baseline=plan.get("inputs") or {}, allowed=ADJUSTABLE_FACTORS, lang=language)
    out.append(_md_table(
        [_T("Factor"), _T("Plan value"), _T("Range")],
        [[f"{row['label']} (`{row['id']}`)", row["value_text"],
          f"{fmt(row['min'], 'pct')} – {fmt(row['max'], 'pct')}"] for row in panel],
    ))
    out.append("")
    out.append("## " + _T("Slides and film script"))
    out.append("")
    out.append(_T(
        "One 15-second scene per paragraph. A paragraph with no figure is spoken in full; a paragraph that fills a "
        "figure is spoken as a short line and its figures stay on the slide. Presenters come from the shared roster "
        "and are assigned when a scene is filmed; charts are the plan's own and are shown beside the clip, never drawn "
        "by the generator."
    ))
    out.append("")
    scene_lookup = {str(s.get("scene_key") or ""): s for s in (scenes or []) if isinstance(s, Mapping)}
    for spec in catalog(language):
        if spec["paragraph_no"] == 1:
            out.append("### " + _T("Slide {n} — {title}").format(n=f"{spec['slide_no']:02d}", title=spec["slide_title"]))
            out.append("")
            if spec.get("kicker"):
                out.append(f"*{fill(spec['kicker'], plan)}*")
                out.append("")
            if spec.get("chart_id"):
                out.append(_T("Chart beside the clip: `{chart}`.").format(chart=spec["chart_id"]))
                out.append("")
        on_slide = fill(spec["template"], plan)
        spoken = short_script(spec, plan)
        filmed = scene_lookup.get(spec["scene_key"], {})
        presenter = str(filmed.get("presenter_label") or "") if filmed else ""
        out.append("**" + _T("Paragraph {n} · scene `{key}` · {seconds} s").format(
            n=spec["paragraph_no"], key=spec["scene_key"], seconds=SCENE_SECONDS) + "**")
        out.append("")
        out.append("- " + _T("On the slide: {text}").format(text=on_slide))
        out.append("- " + _T("Spoken: {text}").format(text=spoken))
        if presenter:
            out.append("- " + _T("Presenter: {text}").format(text=presenter))
        out.append("")
    out.append("## " + _T("Data integrity"))
    out.append("")
    first = view["rows"][0]
    out.append(_T(
        "Every PHINS figure in this pack is read from plan identity `{plan_version}` (content hash `{hash}`). The "
        "reinsurer line is an identity on the plan's carrier rows: 2027 ceded premium {gwp} × {cession} = {ceded}; "
        "ceded claims {claims}; ceding commission {commission}; technical result {result}. Technical margin 1 − "
        "{loss_ratio} − {ceding_commission} = {margin}; break-even 1 − {ceding_commission} = {breakeven}. The group "
        "envelope is group risk GWP × cession, arithmetic on a model row and not a model row. The quota-share "
        "scenarios are the same model with a different cession and are labelled as scenarios with their own hashes. "
        "This pack is generated from the model by `scripts/build_reinsurer_deck_brief.py` and is never hand-edited. "
        "It does not write the platform ledger."
    ).format(
        plan_version=plan_version, hash=content_hash, gwp=money(first["risk_gwp"]), cession=pct(view["cession_rate"]),
        ceded=money(first["ceded_premium"]), claims=money(first["ceded_claims"]), commission=money(first["ceding_commission"]),
        result=money(first["technical_result"]), loss_ratio=pct(view["expected_loss_ratio"]),
        ceding_commission=pct(view["ceding_commission"]), margin=pct(view["technical_margin"]),
        breakeven=pct(view["breakeven_claims_ratio"]),
    ))
    out.append("")
    return "\n".join(out)
