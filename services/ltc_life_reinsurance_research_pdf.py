"""
Full-study PDF for the LTC 3+ADL / life reinsurance research pack.

English and Hebrew documents share the same slider set and integrity hashes.
The Hebrew file is a complete translation (title, narrative, labels, table
headers, methodology, sources) rendered RTL with DejaVu + python-bidi — the
same path used by customer risk-report PDFs.
"""

from __future__ import annotations

import html
import io
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from services.phins_pdf_brand import (
    BRAND_NAME,
    BRAND_TAGLINE,
    BRAND_TAGLINE_HE,
    PHINS_GOLD,
    PHINS_NAVY,
    PHINS_WASH,
    page_callbacks,
)
from services.ltc_life_reinsurance_research import (
    ADL_NAMES_HE,
    COVER_LABELS_HE,
    ERA_LABELS_HE,
    ERA_NOTES_HE,
    FORECAST_NOTES_HE,
    HEDGE_IMPLICATIONS_HE,
    HEDGE_LABELS_HE,
    PRICING_NOTE_HE,
    REGION_LABELS_HE,
    RESEARCH_SOURCES_HE,
    STUDY_ID,
    STUDY_TITLE,
    STUDY_TITLE_HE,
    extract_research_table,
)

_HEBREW_RE = re.compile(r'[\u0590-\u05FF]')

try:
    from bidi.algorithm import get_display as _bidi_get_display
except Exception:  # pragma: no cover - optional at import; required for RTL
    _bidi_get_display = None


def normalize_pdf_lang(lang: Any) -> str:
    value = str(lang or 'en').strip().lower()
    if value in ('he', 'hebrew', 'iw', 'he-il'):
        return 'he'
    return 'en'


def has_hebrew(text: str) -> bool:
    return bool(_HEBREW_RE.search(str(text or '')))


def bidi_text(text: str, rtl: bool = False) -> str:
    value = str(text or '')
    if not value or not rtl or not has_hebrew(value):
        return value
    if _bidi_get_display is None:
        return value
    return _bidi_get_display(value, base_dir='R')


def _register_fonts() -> Tuple[str, str]:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        return 'Helvetica', 'Helvetica-Bold'

    candidates = (
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        (os.path.join(os.path.dirname(__file__), '..', 'web_portal', 'static', 'fonts', 'DejaVuSans.ttf'),
         os.path.join(os.path.dirname(__file__), '..', 'web_portal', 'static', 'fonts', 'DejaVuSans-Bold.ttf')),
    )
    registered = set(pdfmetrics.getRegisteredFontNames())
    for regular_path, bold_path in candidates:
        if os.path.exists(regular_path):
            if 'DejaVuSans' not in registered:
                pdfmetrics.registerFont(TTFont('DejaVuSans', regular_path))
            if os.path.exists(bold_path) and 'DejaVuSans-Bold' not in registered:
                pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', bold_path))
            return 'DejaVuSans', 'DejaVuSans-Bold' if os.path.exists(bold_path) else 'DejaVuSans'
    return 'Helvetica', 'Helvetica-Bold'


# ---------------------------------------------------------------------------
# Copy (English + full Hebrew)
# ---------------------------------------------------------------------------

COPY = {
    'en': {
        'brand': BRAND_NAME,
        'subtitle': 'Research & Audit — long-term-care disability and life reinsurance appetite',
        'generated': 'Generated',
        'study_id': 'Study ID',
        'language': 'Language',
        'language_value': 'English',
        'methodology_title': 'Methodology and scope',
        'methodology': (
            'Fifty-year study of long-term-care disability at a 3+ ADL trigger, '
            'life risk premiums, and reinsurance appetite. Tables are rebuilt from '
            'the current sliders so they can be used for analysis, pricing overlays, '
            'and hedge design. Figures are research indices calibrated to SOA / LIMRA / '
            'NAIC / Swiss Re / Munich Re sources and the live PHINS rate bands — not a '
            'carrier experience study. Promoting a table replaces the live band and is '
            'an explicit actuary decision.'
        ),
        'narrative_title': 'Study narrative',
        'kpis_title': 'Key results on this slider set',
        'params_title': 'Adjustable study controls',
        'sources_title': 'Affiliated sources (1975–2025)',
        'integrity_title': 'Integrity',
        'page': 'Page',
        'yes': 'Yes',
        'no': 'No',
        'metric': 'Metric',
        'value': 'Value',
        'published': 'Published',
        'period': 'Period',
        'table_titles': {
            'historical_appetite': 'Reinsurance appetite and premium indices (50 years)',
            'age_cover_matrix': 'Ages vs covers — life face, 3+ADL annual indemnity, premiums',
            'cross_risk_adl_mortality': 'Cross-risk — 3+ADL trigger to death expectancy',
            'reinsurance_exposure': 'Expected reinsurance exposure',
            'coverage_forecast': 'Forecast — coverage-type mix and hedge stack',
            'pricing_overlay': 'Pricing overlay — technical rates for analysis',
            'adl_mortality_multipliers': 'ADL mortality multipliers',
        },
        'kpi_labels': {
            'life_premium_index_end': 'Life premium index (end)',
            'ltc3_premium_index_end': '3+ADL LTC premium index (end)',
            'life_appetite_now_pct': 'Life reinsurance appetite %',
            'ltc3_appetite_now_pct': 'Standalone 3+ADL appetite %',
            'hybrid_appetite_now_pct': 'Hybrid / combo appetite %',
            'net_ceded_exposure': 'Net ceded exposure',
            'tail_99_exposure': '99% tail exposure',
            'expected_life_claims': 'Expected life claims',
            'expected_ltc_claims': 'Expected 3+ADL claims',
        },
        'param_labels': {
            'year_from': 'History from',
            'year_to': 'History to',
            'forecast_end': 'Forecast end',
            'region': 'Region',
            'coverage_type': 'Coverage type',
            'age_min': 'Age min',
            'age_max': 'Age max',
            'life_cover': 'Life cover',
            'ltc_annual_cover': 'LTC annual cover',
            'adl_threshold': 'ADL threshold',
            'hedge_share_pct': 'Hedge share %',
            'lives': 'Lives in book',
            'mortality_improvement_pct': 'Mortality improvement % / yr',
            'ltc_incidence_load_pct': '3+ADL incidence load %',
            'duration_stress_pct': 'Duration stress %',
            'recommended_hedge': 'Recommended hedge',
            'adl_names': 'ADL list',
        },
        'integrity_labels': {
            'study_id': 'Study ID',
            'params_hash': 'Params hash',
            'tables_hash': 'Tables hash',
            'pack_hash': 'Pack hash',
            'table_version': 'Live table version',
            'historical_span_years': 'Historical span (years)',
            'exposure_totals_match': 'Exposure totals reconcile',
            'forecast_mix_normalised': 'Forecast mix normalised',
            'uses_live_rate_tables': 'Uses live PHINS rate bands',
        },
        'headers': {
            'year': 'Year',
            'era': 'Era',
            'life_premium_index': 'Life idx',
            'ltc3_premium_index': '3+ADL idx',
            'life_appetite_pct': 'Life app. %',
            'ltc3_appetite_pct': '3+ADL app. %',
            'hybrid_appetite_pct': 'Hybrid app. %',
            'joint_appetite_pct': 'Joint app. %',
            'capacity_index': 'Capacity',
            'life_to_ltc_premium_ratio': 'Life/LTC ratio',
            'preferred_structure': 'Structure',
            'era_note': 'Era note',
            'age_band': 'Age band',
            'age_min': 'Age min',
            'age_max': 'Age max',
            'attained_age': 'Attained age',
            'recommended_life_cover': 'Life cover',
            'recommended_ltc_annual_cover': 'LTC annual',
            'life_rate_per_1000': 'Life / 1,000',
            'ltc3_rate_per_1000': '3+ADL / 1,000',
            'life_annual_premium': 'Life premium',
            'ltc3_annual_premium': '3+ADL premium',
            'combined_annual_premium': 'Combined',
            'expected_ltc_claim_cost': 'E[LTC claim]',
            'coverage_type': 'Coverage',
            'adl_threshold': 'ADL trigger',
            'healthy_life_expectancy': 'Healthy LE',
            'remaining_le_after_3adl': 'LE after 3+ADL',
            'le_reduction_years': 'LE lost',
            'excess_mortality_multiple': 'Excess mort.',
            'life_qx': 'Life q(x)',
            'ltc3_incidence': '3+ADL i(x)',
            'p_death_within_5y_given_3adl': 'P(death ≤5y | 3+ADL)',
            'joint_year1_probability': 'Joint year-1',
            'frailty_correlation': 'Frailty ρ',
            'hedge_implication': 'Hedge implication',
            'band_lives': 'Lives',
            'life_face': 'Life face',
            'ltc_annual_cover': 'LTC annual',
            'expected_life_claims': 'E[life claims]',
            'expected_ltc_claims': 'E[3+ADL claims]',
            'ceded_life_exposure': 'Ceded life',
            'ceded_ltc_exposure': 'Ceded LTC',
            'joint_credit': 'Joint credit',
            'net_ceded_exposure': 'Net ceded',
            'tail_99_exposure': '99% tail',
            'mean_claim_duration_years': 'Duration',
            'hedge_share_pct': 'Hedge %',
            'mix_standalone_ltc': 'Standalone',
            'mix_indemnity': 'Indemnity',
            'mix_reimbursement': 'Reimburse',
            'mix_hybrid_life_ltc': 'Hybrid',
            'mix_adb_rider': 'ADB',
            'recommended_hedge': 'Recommended hedge',
            'forecast_note': 'Forecast note',
            'selected_coverage_type': 'Selected cover',
            'rate_per_1000': 'Rate / 1,000',
            'life_technical_rate_per_1000': 'Life technical',
            'ltc3_technical_rate_per_1000': '3+ADL technical',
            'reinsurance_load': 'Reins. load',
            'adl': 'ADL',
            'multiplier': 'Multiplier',
            'trigger': 'Trigger',
            'note': 'Note',
        },
    },
    'he': {
        'brand': BRAND_NAME,
        'subtitle': 'מחקר וביקורת — נכות סיעודית ותיאבון ביטוח משנה לחיים',
        'generated': 'הופק',
        'study_id': 'מזהה מחקר',
        'language': 'שפה',
        'language_value': 'עברית',
        'methodology_title': 'מתודולוגיה והיקף',
        'methodology': (
            'מחקר בן חמישים שנה על נכות סיעודית בהפעלה של 3+ פעולות יומיום, '
            'פרמיות סיכון חיים, ותיאבון ביטוח משנה. הטבלאות נבנות מחדש ממחווני '
            'המחקר כדי לשמש לניתוח, לשכבות תמחור ולעיצוב גידור. הנתונים הם מדדי '
            'מחקר מכוילים למקורות SOA / LIMRA / NAIC / Swiss Re / Munich Re ולרצועות '
            'השיעורים החיות של PHINS — ואינם מחקר ניסיון של מבטח. קידום טבלה מחליף '
            'את הרצועה החיה והוא החלטת אקטואר מפורשת.'
        ),
        'narrative_title': 'נרטיב המחקר',
        'kpis_title': 'תוצאות עיקריות על ערכת המחוונים',
        'params_title': 'מחווני מחקר מתכווננים',
        'sources_title': 'מקורות מסונפים (1975–2025)',
        'integrity_title': 'שלמות הנתונים',
        'page': 'עמוד',
        'yes': 'כן',
        'no': 'לא',
        'metric': 'מדד',
        'value': 'ערך',
        'published': 'פורסם',
        'period': 'תקופה',
        'table_titles': {
            'historical_appetite': 'תיאבון ביטוח משנה ומדדי פרמיה (50 שנה)',
            'age_cover_matrix': 'גילאים מול כיסויים — סכום חיים, שיפוי שנתי 3+ פעולות יומיום, פרמיות',
            'cross_risk_adl_mortality': 'סיכון צולב — הפעלת 3+ פעולות יומיום לתוחלת מוות',
            'reinsurance_exposure': 'חשיפת ביטוח משנה צפויה',
            'coverage_forecast': 'תחזית — תמהיל סוגי כיסוי ומחסנית גידור',
            'pricing_overlay': 'שכבת תמחור — שיעורים טכניים לניתוח',
            'adl_mortality_multipliers': 'מכפילי תמותה לפי פעולות יומיום',
        },
        'kpi_labels': {
            'life_premium_index_end': 'מדד פרמיית חיים (סוף)',
            'ltc3_premium_index_end': 'מדד פרמיית סיעוד 3+ פעולות יומיום (סוף)',
            'life_appetite_now_pct': 'תיאבון ביטוח משנה לחיים %',
            'ltc3_appetite_now_pct': 'תיאבון לסיעוד עצמאי 3+ %',
            'hybrid_appetite_now_pct': 'תיאבון למוצרים משולבים %',
            'net_ceded_exposure': 'חשיפה מועברת נטו',
            'tail_99_exposure': 'חשיפת זנב 99%',
            'expected_life_claims': 'תביעות חיים צפויות',
            'expected_ltc_claims': 'תביעות 3+ פעולות יומיום צפויות',
        },
        'param_labels': {
            'year_from': 'היסטוריה מ־',
            'year_to': 'היסטוריה עד',
            'forecast_end': 'סוף תחזית',
            'region': 'אזור',
            'coverage_type': 'סוג כיסוי',
            'age_min': 'גיל מינימום',
            'age_max': 'גיל מקסימום',
            'life_cover': 'סכום חיים',
            'ltc_annual_cover': 'כיסוי סיעוד שנתי',
            'adl_threshold': 'סף פעולות יומיום',
            'hedge_share_pct': 'שיעור גידור %',
            'lives': 'חיים בספר',
            'mortality_improvement_pct': 'שיפור תמותה % / שנה',
            'ltc_incidence_load_pct': 'עומס היארעות 3+ %',
            'duration_stress_pct': 'קיצון משך %',
            'recommended_hedge': 'גידור מומלץ',
            'adl_names': 'רשימת פעולות יומיום',
        },
        'integrity_labels': {
            'study_id': 'מזהה מחקר',
            'params_hash': 'גיבוב פרמטרים',
            'tables_hash': 'גיבוב טבלאות',
            'pack_hash': 'גיבוב המארז',
            'table_version': 'גרסת טבלה חיה',
            'historical_span_years': 'טווח היסטורי (שנים)',
            'exposure_totals_match': 'סכימות חשיפה מתיישבות',
            'forecast_mix_normalised': 'תמהיל התחזית מנורמל',
            'uses_live_rate_tables': 'משתמש ברצועות שיעורים חיות של PHINS',
        },
        'headers': {
            'year': 'שנה',
            'era': 'תקופה',
            'life_premium_index': 'מדד חיים',
            'ltc3_premium_index': 'מדד 3+',
            'life_appetite_pct': 'תיאבון חיים %',
            'ltc3_appetite_pct': 'תיאבון 3+ %',
            'hybrid_appetite_pct': 'תיאבון משולב %',
            'joint_appetite_pct': 'תיאבון משותף %',
            'capacity_index': 'קיבולת',
            'life_to_ltc_premium_ratio': 'יחס חיים/סיעוד',
            'preferred_structure': 'מבנה',
            'era_note': 'הערת תקופה',
            'age_band': 'רצועת גיל',
            'age_min': 'גיל מינ׳',
            'age_max': 'גיל מקס׳',
            'attained_age': 'גיל מושג',
            'recommended_life_cover': 'סכום חיים',
            'recommended_ltc_annual_cover': 'סיעוד שנתי',
            'life_rate_per_1000': 'חיים / 1,000',
            'ltc3_rate_per_1000': '3+ / 1,000',
            'life_annual_premium': 'פרמיית חיים',
            'ltc3_annual_premium': 'פרמיית 3+',
            'combined_annual_premium': 'משולב',
            'expected_ltc_claim_cost': 'עלות תביעת סיעוד',
            'coverage_type': 'כיסוי',
            'adl_threshold': 'סף הפעלה',
            'healthy_life_expectancy': 'תוחלת בריאה',
            'remaining_le_after_3adl': 'תוחלת אחרי 3+',
            'le_reduction_years': 'שנים שאבדו',
            'excess_mortality_multiple': 'תמותת יתר',
            'life_qx': 'q(x) חיים',
            'ltc3_incidence': 'i(x) 3+',
            'p_death_within_5y_given_3adl': 'P(מוות ≤5ש | 3+)',
            'joint_year1_probability': 'משותף שנה־1',
            'frailty_correlation': 'מתאם חולשה',
            'hedge_implication': 'משמעות גידור',
            'band_lives': 'חיים',
            'life_face': 'סכום חיים',
            'ltc_annual_cover': 'סיעוד שנתי',
            'expected_life_claims': 'תביעות חיים',
            'expected_ltc_claims': 'תביעות 3+',
            'ceded_life_exposure': 'חיים מועברים',
            'ceded_ltc_exposure': 'סיעוד מועבר',
            'joint_credit': 'זיכוי משותף',
            'net_ceded_exposure': 'מועבר נטו',
            'tail_99_exposure': 'זנב 99%',
            'mean_claim_duration_years': 'משך',
            'hedge_share_pct': 'גידור %',
            'mix_standalone_ltc': 'עצמאי',
            'mix_indemnity': 'פיצוי',
            'mix_reimbursement': 'החזר',
            'mix_hybrid_life_ltc': 'משולב',
            'mix_adb_rider': 'הקדמת תגמולים',
            'recommended_hedge': 'גידור מומלץ',
            'forecast_note': 'הערת תחזית',
            'selected_coverage_type': 'כיסוי נבחר',
            'rate_per_1000': 'שיעור / 1,000',
            'life_technical_rate_per_1000': 'טכני חיים',
            'ltc3_technical_rate_per_1000': 'טכני 3+',
            'reinsurance_load': 'עומס משנה',
            'adl': 'פעולה',
            'multiplier': 'מכפיל',
            'trigger': 'הפעלה',
            'note': 'הערה',
        },
    },
}

# Compact column sets so landscape pages stay readable.
PDF_TABLE_COLUMNS: Dict[str, List[str]] = {
    'historical_appetite': [
        'year', 'era', 'life_premium_index', 'ltc3_premium_index',
        'life_appetite_pct', 'ltc3_appetite_pct', 'hybrid_appetite_pct',
        'preferred_structure',
    ],
    'age_cover_matrix': [
        'age_band', 'recommended_life_cover', 'recommended_ltc_annual_cover',
        'life_rate_per_1000', 'ltc3_rate_per_1000', 'life_annual_premium',
        'ltc3_annual_premium', 'combined_annual_premium',
    ],
    'cross_risk_adl_mortality': [
        'age_band', 'healthy_life_expectancy', 'remaining_le_after_3adl',
        'le_reduction_years', 'excess_mortality_multiple',
        'p_death_within_5y_given_3adl', 'frailty_correlation', 'hedge_implication',
    ],
    'reinsurance_exposure': [
        'age_band', 'band_lives', 'expected_life_claims', 'expected_ltc_claims',
        'ceded_life_exposure', 'ceded_ltc_exposure', 'joint_credit',
        'net_ceded_exposure', 'tail_99_exposure', 'mean_claim_duration_years',
    ],
    'coverage_forecast': [
        'year', 'mix_standalone_ltc', 'mix_indemnity', 'mix_reimbursement',
        'mix_hybrid_life_ltc', 'mix_adb_rider', 'life_appetite_pct',
        'ltc3_appetite_pct', 'recommended_hedge',
    ],
    'pricing_overlay': [
        'age_band', 'life_rate_per_1000', 'ltc3_rate_per_1000',
        'life_technical_rate_per_1000', 'ltc3_technical_rate_per_1000',
        'joint_credit', 'reinsurance_load', 'mean_claim_duration_years',
    ],
    'adl_mortality_multipliers': [
        'adl', 'multiplier', 'trigger', 'note',
    ],
}

MONEY_KEYS = {
    'recommended_life_cover', 'recommended_ltc_annual_cover', 'life_face',
    'ltc_annual_cover', 'life_annual_premium', 'ltc3_annual_premium',
    'combined_annual_premium', 'expected_ltc_claim_cost', 'expected_life_claims',
    'expected_ltc_claims', 'ceded_life_exposure', 'ceded_ltc_exposure',
    'joint_credit', 'net_ceded_exposure', 'tail_99_exposure', 'life_cover',
}
PCT_KEYS = {
    'life_appetite_pct', 'ltc3_appetite_pct', 'hybrid_appetite_pct',
    'joint_appetite_pct', 'hedge_share_pct', 'mix_standalone_ltc',
    'mix_indemnity', 'mix_reimbursement', 'mix_hybrid_life_ltc', 'mix_adb_rider',
    'p_death_within_5y_given_3adl',
}
INT_KEYS = {'year', 'age_min', 'age_max', 'band_lives', 'adl', 'lives', 'adl_threshold'}


def _money(value: Any) -> str:
    try:
        return f'${float(value):,.0f}'
    except (TypeError, ValueError):
        return str(value or '—')


def _num(value: Any, digits: int = 2) -> str:
    try:
        return f'{float(value):,.{digits}f}'
    except (TypeError, ValueError):
        return str(value or '—')


def _pct(value: Any, digits: int = 1, already_percent: bool = True) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or '—')
    if not already_percent and number <= 1.5:
        number *= 100.0
    return f'{number:.{digits}f}%'


def _localize_scalar(key: str, value: Any, lang: str, copy: Dict[str, Any]) -> str:
    if value is None or value == '':
        return '—'
    if key == 'trigger':
        return copy['yes'] if value else copy['no']
    if key in ('era', 'preferred_structure'):
        if lang == 'he':
            return ERA_LABELS_HE.get(str(value), str(value))
        return str(value).replace('_', ' ')
    if key in ('recommended_hedge',):
        if lang == 'he':
            return HEDGE_LABELS_HE.get(str(value), str(value))
        return str(value).replace('_', ' ')
    if key in ('coverage_type', 'selected_coverage_type'):
        if lang == 'he':
            return COVER_LABELS_HE.get(str(value), str(value))
        return str(value).replace('_', ' ')
    if key == 'region':
        if lang == 'he':
            return REGION_LABELS_HE.get(str(value), str(value))
        return str(value)
    if key == 'era_note':
        return ERA_NOTES_HE.get(str(value), str(value)) if lang == 'he' else str(value)
    if key == 'forecast_note':
        return FORECAST_NOTES_HE.get(str(value), str(value)) if lang == 'he' else str(value)
    if key == 'hedge_implication':
        if lang != 'he':
            return str(value)
        if 'shared-pool' in str(value) or 'ADB' in str(value) and 'credits' in str(value):
            return HEDGE_IMPLICATIONS_HE['combo']
        return HEDGE_IMPLICATIONS_HE['standalone']
    if key == 'note' and lang == 'he':
        text = str(value)
        if 'Below trigger' in text:
            return 'מתחת לסף — חולשה חיתומית בלבד'
        return 'תמותת תובע ב־3+ פעולות יומיום מול בריא בגיל 70'
    if key in MONEY_KEYS:
        return _money(value)
    if key in PCT_KEYS:
        already = key not in (
            'mix_standalone_ltc', 'mix_indemnity', 'mix_reimbursement',
            'mix_hybrid_life_ltc', 'mix_adb_rider', 'p_death_within_5y_given_3adl',
        )
        digits = 1 if already else 1
        if key == 'p_death_within_5y_given_3adl':
            return _pct(value, 1, already_percent=False)
        if key.startswith('mix_'):
            return _pct(value, 1, already_percent=False)
        return _pct(value, digits, already_percent=already)
    if key in INT_KEYS:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, float):
        return _num(value, 2 if abs(value) >= 1 else 4)
    return str(value)


def _age_band(row: Dict[str, Any]) -> str:
    lo = row.get('age_min')
    hi = row.get('age_max')
    if lo is None or hi is None:
        return '—'
    return f'{lo}–{hi}'


def _localize_row(row: Dict[str, Any], columns: Sequence[str], lang: str,
                  copy: Dict[str, Any]) -> List[str]:
    cells: List[str] = []
    for key in columns:
        if key == 'age_band':
            cells.append(_age_band(row))
            continue
        raw = row.get(key)
        if key == 'era_note':
            raw = row.get('era') or raw
        if key == 'forecast_note':
            # Translate from the hedge key when we have a mapped note.
            raw = row.get('recommended_hedge') if lang == 'he' else raw
        if key == 'era':
            raw = row.get('era') or row.get('preferred_structure')
        cells.append(_localize_scalar(key, raw, lang, copy))
    return cells


def _rtl_break_lines(text: str, font: str, size: float, max_width: float) -> List[str]:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except Exception:
        return [text] if text else ['']
    words = str(text or '').split()
    if not words:
        return ['']
    lines: List[str] = []
    current = ''
    limit = max(1.0, float(max_width or 0) or 460)
    for word in words:
        trial = f'{current} {word}'.strip()
        if not current or stringWidth(trial, font, size) <= limit:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


def _paragraph(text: str, style, rtl: bool, max_width: float = 0):
    from reportlab.platypus import Paragraph

    raw = str(text or '')
    if rtl:
        logical_lines: List[str] = []
        for para in raw.split('\n'):
            if max_width:
                logical_lines.extend(_rtl_break_lines(
                    para, getattr(style, 'fontName', 'Helvetica'),
                    getattr(style, 'fontSize', 9), max_width,
                ))
            else:
                logical_lines.append(para)
        visual = [html.escape(bidi_text(line, rtl=True)) for line in logical_lines]
        return Paragraph('<br/>'.join(visual), style)
    return Paragraph(html.escape(raw).replace('\n', '<br/>'), style)


def _maybe_reverse(values: List[Any], rtl: bool) -> List[Any]:
    return list(reversed(values)) if rtl else values


def build_research_pdf(pack: Dict[str, Any], lang: str = 'en') -> Tuple[str, bytes]:
    """Render the full study. Returns ``(filename, pdf_bytes)``."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    lang = normalize_pdf_lang(lang)
    rtl = lang == 'he'
    copy = COPY[lang]
    title = STUDY_TITLE_HE if rtl else (pack.get('title') or STUDY_TITLE)
    font, font_bold = _register_fonts()
    navy = colors.HexColor(PHINS_NAVY)
    gold = colors.HexColor(PHINS_GOLD)
    light = colors.HexColor(PHINS_WASH)

    buf = io.BytesIO()
    pagesize = landscape(A4)
    usable = pagesize[0] - 22 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize,
        leftMargin=11 * mm, rightMargin=11 * mm,
        topMargin=24 * mm, bottomMargin=14 * mm,
        title=title,
        author=BRAND_NAME,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'LtcTitle', parent=styles['Title'], fontName=font_bold, fontSize=16,
        textColor=navy, alignment=2 if rtl else 0, leading=20, spaceAfter=4,
    )
    h2 = ParagraphStyle(
        'LtcH2', parent=styles['Heading2'], fontName=font_bold, fontSize=12,
        textColor=navy, alignment=2 if rtl else 0, leading=16, spaceBefore=8, spaceAfter=4,
    )
    body = ParagraphStyle(
        'LtcBody', parent=styles['BodyText'], fontName=font, fontSize=9,
        alignment=2 if rtl else 0, leading=13, textColor=colors.HexColor('#1A202C'),
    )
    meta = ParagraphStyle(
        'LtcMeta', parent=body, fontSize=8, textColor=colors.HexColor('#4A5568'),
    )
    cell = ParagraphStyle(
        'LtcCell', parent=body, fontSize=6.5, leading=8.5, alignment=2 if rtl else 0,
    )
    cell_hdr = ParagraphStyle(
        'LtcCellHdr', parent=cell, fontName=font_bold, fontSize=6.5,
        textColor=gold, alignment=2 if rtl else 0,
    )
    source_style = ParagraphStyle(
        'LtcSource', parent=body, fontSize=8, leading=11,
    )

    story: List[Any] = []
    story.append(_paragraph(title, title_style, rtl, usable))
    story.append(_paragraph(BRAND_TAGLINE_HE if rtl else BRAND_TAGLINE, meta, rtl, usable))
    story.append(_paragraph(copy['subtitle'], body, rtl, usable))
    generated = pack.get('generated_at') or datetime.utcnow().isoformat()
    meta_line = (
        f"{copy['generated']}: {generated}  ·  {copy['study_id']}: {pack.get('study_id') or STUDY_ID}  ·  "
        f"{copy['language']}: {copy['language_value']}"
    )
    story.append(_paragraph(meta_line, meta, rtl, usable))
    story.append(Spacer(1, 8))

    story.append(_paragraph(copy['methodology_title'], h2, rtl, usable))
    story.append(_paragraph(copy['methodology'], body, rtl, usable))
    story.append(Spacer(1, 6))

    story.append(_paragraph(copy['narrative_title'], h2, rtl, usable))
    narrative = pack.get('narrative_he') if rtl else pack.get('narrative')
    for para in narrative or []:
        story.append(_paragraph(str(para), body, rtl, usable))
        story.append(Spacer(1, 3))

    story.append(_paragraph(copy['params_title'], h2, rtl, usable))
    params = pack.get('params') or {}
    param_rows = [
        [copy['param_labels']['region'], pack.get('region_label_he') if rtl else pack.get('region_label')],
        [copy['param_labels']['coverage_type'], pack.get('coverage_label_he') if rtl else pack.get('coverage_label')],
        [copy['param_labels']['recommended_hedge'], pack.get('recommended_hedge_he') if rtl else str(pack.get('recommended_hedge') or '').replace('_', ' ')],
        [copy['param_labels']['year_from'], str(params.get('year_from', ''))],
        [copy['param_labels']['year_to'], str(params.get('year_to', ''))],
        [copy['param_labels']['forecast_end'], str(params.get('forecast_end', ''))],
        [copy['param_labels']['age_min'], str(params.get('age_min', ''))],
        [copy['param_labels']['age_max'], str(params.get('age_max', ''))],
        [copy['param_labels']['life_cover'], _money(params.get('life_cover'))],
        [copy['param_labels']['ltc_annual_cover'], _money(params.get('ltc_annual_cover'))],
        [copy['param_labels']['adl_threshold'], f"{params.get('adl_threshold', '')}+"],
        [copy['param_labels']['hedge_share_pct'], _pct(params.get('hedge_share_pct'))],
        [copy['param_labels']['lives'], f"{int(params.get('lives') or 0):,}"],
        [copy['param_labels']['mortality_improvement_pct'], _pct(params.get('mortality_improvement_pct'))],
        [copy['param_labels']['ltc_incidence_load_pct'], _pct(params.get('ltc_incidence_load_pct'))],
        [copy['param_labels']['duration_stress_pct'], _pct(params.get('duration_stress_pct'))],
        [copy['param_labels']['adl_names'], ', '.join(pack.get('adl_names_he') or ADL_NAMES_HE) if rtl else ', '.join(pack.get('adl_names') or [])],
    ]
    story.append(_kv_table(param_rows, copy, font, font_bold, navy, gold, light, cell, cell_hdr, rtl, usable * 0.62))

    story.append(_paragraph(copy['kpis_title'], h2, rtl, usable))
    kpis = pack.get('kpis') or {}
    kpi_rows = []
    for key, label in copy['kpi_labels'].items():
        value = kpis.get(key)
        if key.endswith('_pct'):
            rendered = _pct(value)
        elif 'exposure' in key or 'claims' in key:
            rendered = _money(value)
        else:
            rendered = _num(value, 1)
        kpi_rows.append([label, rendered])
    story.append(_kv_table(kpi_rows, copy, font, font_bold, navy, gold, light, cell, cell_hdr, rtl, usable * 0.62))

    for table_name, columns in PDF_TABLE_COLUMNS.items():
        rows = extract_research_table(pack, table_name)
        story.append(PageBreak())
        story.append(_paragraph(copy['table_titles'][table_name], h2, rtl, usable))
        if table_name == 'pricing_overlay':
            note = PRICING_NOTE_HE if rtl else (pack.get('pricing_use') or {}).get('note')
            if note:
                story.append(_paragraph(str(note), meta, rtl, usable))
                story.append(Spacer(1, 4))
        story.append(_data_table(
            columns, rows, copy, lang, font, navy, gold, light,
            cell, cell_hdr, rtl, usable,
        ))

    story.append(PageBreak())
    story.append(_paragraph(copy['sources_title'], h2, rtl, usable))
    for item in pack.get('sources') or []:
        source_id = item.get('id')
        he = RESEARCH_SOURCES_HE.get(source_id) or {}
        name = he.get('source') if rtl else item.get('source')
        headline = he.get('headline_metric') if rtl else item.get('headline_metric')
        relevance = he.get('relevance') if rtl else item.get('relevance')
        block = (
            f"{name} ({copy['published']} {item.get('published_year', '—')}, "
            f"{copy['period']} {item.get('period_covered', '—')}). "
            f"{headline} {relevance}"
        )
        story.append(_paragraph(f'• {block}', source_style, rtl, usable))
        story.append(Spacer(1, 3))

    story.append(Spacer(1, 8))
    story.append(_paragraph(copy['integrity_title'], h2, rtl, usable))
    integ = pack.get('integrity') or {}
    integ_rows = []
    for key, label in copy['integrity_labels'].items():
        value = integ.get(key, pack.get(key))
        if isinstance(value, bool):
            value = copy['yes'] if value else copy['no']
        elif value in (None, ''):
            value = '—'
        integ_rows.append([label, str(value)])
    story.append(_kv_table(integ_rows, copy, font, font_bold, navy, gold, light, cell, cell_hdr, rtl, usable * 0.85))

    footer_note = (
        'פינס — מסמך אקטוארי סודי · מחקר וביקורת'
        if rtl else
        f'{BRAND_NAME} — Confidential actuarial document · Research & Audit'
    )
    on_first, on_later = page_callbacks(
        pagesize,
        title=title,
        rtl=rtl,
        font=font,
        bold=font_bold,
        badge='מחקר וביקורת' if rtl else 'Research & Audit',
        footer_note=footer_note,
        page_label=copy['page'],
        bidi_fn=(lambda text: bidi_text(text, rtl=True)) if rtl else None,
    )
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    filename = f'phins-{STUDY_ID}-{lang}.pdf'
    return filename, buf.getvalue()


def _kv_table(rows: List[List[str]], copy: Dict[str, Any], font: str, font_bold: str,
              navy, gold, light, cell, cell_hdr, rtl: bool, width: float):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors

    header = _maybe_reverse([
        _paragraph(copy['metric'], cell_hdr, rtl),
        _paragraph(copy['value'], cell_hdr, rtl),
    ], rtl)
    data = [header]
    for label, value in rows:
        pair = [
            _paragraph(str(label), cell, rtl),
            _paragraph(str(value), cell, rtl),
        ]
        data.append(_maybe_reverse(pair, rtl))
    col0 = width * 0.42
    col1 = width * 0.58
    widths = _maybe_reverse([col0, col1], rtl)
    table = Table(data, colWidths=widths, hAlign='RIGHT' if rtl else 'LEFT', repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('BACKGROUND', (0, 1), (-1, -1), light),
        ('TEXTCOLOR', (0, 0), (-1, 0), gold),
        ('FONTNAME', (0, 0), (-1, 0), font_bold),
        ('FONTNAME', (0, 1), (-1, -1), font),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT' if rtl else 'LEFT'),
    ]))
    return table


def _data_table(columns: Sequence[str], rows: Iterable[Dict[str, Any]],
                copy: Dict[str, Any], lang: str, font: str, navy, gold, light,
                cell, cell_hdr, rtl: bool, usable: float):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors

    headers = [_paragraph(copy['headers'].get(col, col), cell_hdr, rtl) for col in columns]
    data = [_maybe_reverse(headers, rtl)]
    for row in rows:
        cells = [
            _paragraph(value, cell, rtl)
            for value in _localize_row(row, columns, lang, copy)
        ]
        data.append(_maybe_reverse(cells, rtl))
    n = max(1, len(columns))
    # Give note / implication columns more room.
    weights = []
    for col in columns:
        if col in ('hedge_implication', 'era_note', 'forecast_note', 'note', 'preferred_structure', 'recommended_hedge'):
            weights.append(1.8)
        elif col == 'age_band':
            weights.append(0.9)
        else:
            weights.append(1.0)
    total = sum(weights)
    widths = [usable * (w / total) for w in weights]
    widths = _maybe_reverse(widths, rtl)
    table = Table(data, colWidths=widths, hAlign='RIGHT' if rtl else 'LEFT', repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('BACKGROUND', (0, 1), (-1, -1), light),
        ('TEXTCOLOR', (0, 0), (-1, 0), gold),
        ('FONTNAME', (0, 0), (-1, -1), font),
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),
        ('GRID', (0, 0), (-1, -1), 0.2, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT' if rtl else 'LEFT'),
    ]))
    return table
