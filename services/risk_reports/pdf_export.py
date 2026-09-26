"""Downloadable Risk Reports PDF (B9).

Customer downloads present only the assessment produced after Analyse —
identity, accounts, accumulation, severance, the shown charts, and the
customer-facing narrative. Statistical filler (Data Profile, correlations,
patterns, generic key-metrics), the "דו״ח ניתוח נתונים" dump and
"שלמות נתונים" are omitted. Pages use the PHINS navy/gold letterhead,
shield emblem, wordmark and tagline. Hebrew is right-aligned and
bidi-reordered.
"""

from __future__ import annotations

import html
import io
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Titles that describe analysis-of-the-file, not the customer assessment.
# Matched case-insensitively after stripping punctuation/emoji prefixes
# and Hebrew gershayim / ASCII quotes.
STATISTICAL_SECTION_TITLES = frozenset({
    'פרופיל נתונים',
    'data profile',
    'ניתוח סטטיסטי',
    'statistical analysis',
    'ניתוח מתאמים',
    'correlation analysis',
    'דפוסים ומגמות',
    'patterns & trends',
    'patterns and trends',
    'הערכת סיכון',
    'risk assessment',
    'מדדים מרכזיים',
    'key metrics',
    'דוח ניתוח נתונים',
    'data analysis report',
    'תוכן הנתונים שהועלו',
    'uploaded data content',
})

# Schema-catalog / platform-internal sections that are not customer data.
CATALOG_SECTION_TITLES = frozenset({
    'מפת שיוכים (affiliations)',
    'מפת שיוכים affiliations',
    'affiliation mapping snapshot',
})

# Completeness / integrity headings — never shown on a customer download.
COMPLETENESS_SECTION_TITLES = frozenset({
    'שלמות נתונים',
    'data integrity',
    'data completeness',
    'כללי שלמות נתונים',
})

_COMPLETENESS_MARKERS = (
    'שלמות נתונים',
    'data completeness',
    'data integrity',
    'כללי שלמות נתונים',
    'תקינות מזהה',
    'id validation',
    'missing values',
    'data collection process',
    'ערכים חסרים',
)

# Staff-facing analysis titles rewritten for the customer download.
_GENERIC_ANALYSIS_TITLES = frozenset({
    'דוח ניתוח נתונים',
    'data analysis report',
    'דוח ניתוח ביטוח',
    'insurance analysis report',
    'דוח ניתוח השקעות',
    'investment analysis report',
    'דוח הערכת סיכונים',
    'risk assessment report',
    'דוח ניתוח חיסכון',
    'savings analysis report',
})

_CUSTOMER_SECTION_TITLES = {
    'תקציר מנהלים': 'סיכום ההערכה',
    'סיכום ההערכה': 'סיכום ההערכה',
    'executive summary': 'Assessment Summary',
    'assessment summary': 'Assessment Summary',
    'דוח ניתוח פנסיה וביטוח': 'הערכת הפנסיה והביטוח שלך',
    'pension & insurance analysis report': 'Your Pension & Insurance Assessment',
    'פרטי פוליסת ביטוח': 'פרטי הפוליסה שלך',
    'insurance policy details': 'Your Policy Details',
    'חריגות ואזהרות': 'נקודות לתשומת לב',
    'anomalies & warnings': 'Points to Review',
    'anomalies and warnings': 'Points to Review',
    'סיכום מסונף - חיסכון, כיסוי וזיהוי': 'סיכום החיסכון והכיסוי שלך',
    'affiliated summary - savings, cover & id': 'Your Savings & Cover Summary',
    'פרופיל לקוח (שיוך)': 'הפרטים שלך',
    'סטטוס פוליסות (טבלת שיוכים)': 'הפוליסות שלך',
    'רשימת תוכניות (פירוט טבלאי)': 'התוכניות שלך',
    'סיכום כספי (מודל דוח)': 'הסיכום הכספי שלך',
}

_STAFF_COLUMN_TITLES = frozenset({
    'אימות מזהה',
    'id validation',
    'פורמט גולמי',
    'raw format',
    'מזהה (מוסתר)',
    'masked id',
})

_STATISTICAL_NARRATIVE_MARKERS = (
    'ניתוח AI מקיף',
    'comprehensive ai analysis',
    'סטטיסטיקה:',
    'statistics:',
    'רשומות נותחו',
    'records analyzed',
    'שדות זוהו',
    'fields identified',
    'גורמים מרכזיים חולצו',
    'key factors extracted',
)

_QUOTE_CHARS = (
    '\u05f4',  # Hebrew gershayim ״
    '\u05f3',  # Hebrew geresh ׳
    '"',
    "'",
    '\u201c',
    '\u201d',
    '\u2018',
    '\u2019',
)

_HEBREW_RE = re.compile(r'[\u0590-\u05FF]')

try:
    from bidi.algorithm import get_display as _bidi_get_display
except Exception:  # pragma: no cover - optional at import; required for RTL
    _bidi_get_display = None


def _normalize_section_title(title: str) -> str:
    text = str(title or '').strip()
    # Drop leading emoji / decorative marks the renderer prefixes.
    while text and ord(text[0]) > 0x1F300:
        text = text[1:].strip()
    for quote in _QUOTE_CHARS:
        text = text.replace(quote, '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text.lower()


def is_statistical_section_title(title: str) -> bool:
    """True when a report section is statistical filler, not assessment data."""
    return _normalize_section_title(title) in STATISTICAL_SECTION_TITLES


def is_completeness_section_title(title: str) -> bool:
    """True when a section is the data-completeness / integrity block."""
    normalized = _normalize_section_title(title)
    if normalized in COMPLETENESS_SECTION_TITLES:
        return True
    return any(marker in str(title or '') or marker in normalized for marker in _COMPLETENESS_MARKERS)


def is_non_assessment_section_title(title: str) -> bool:
    """True for statistical filler, completeness, or schema-catalog sections."""
    normalized = _normalize_section_title(title)
    if (
        normalized in STATISTICAL_SECTION_TITLES
        or normalized in CATALOG_SECTION_TITLES
        or normalized in COMPLETENESS_SECTION_TITLES
    ):
        return True
    return is_completeness_section_title(title)


def has_hebrew(text: str) -> bool:
    return bool(_HEBREW_RE.search(str(text or '')))


def is_rtl_language(language: Any) -> bool:
    return str(language or '').strip().lower() in {'hebrew', 'he', 'iw'}


def bidi_text(text: str, rtl: bool = False) -> str:
    """Reorder logical Hebrew to visual order. Leave numbers and Latin as-is."""
    value = str(text or '')
    if not value or not rtl or not has_hebrew(value):
        return value
    if _bidi_get_display is None:
        return value
    return _bidi_get_display(value, base_dir='R')


def strip_completeness_copy(text: str) -> str:
    """Drop completeness / integrity lines from a customer-facing narrative."""
    kept: List[str] = []
    for line in str(text or '').splitlines():
        lowered = line.lower()
        if any(marker in line or marker in lowered for marker in _COMPLETENESS_MARKERS):
            continue
        kept.append(line)
    cleaned = '\n'.join(kept)
    return re.sub(r'\n{3,}', '\n\n', cleaned).strip()


def customer_assessment_narrative(text: str) -> str:
    """Keep the Analyse result; drop the statistical data-analysis dump."""
    cleaned = strip_completeness_copy(text)
    if not cleaned:
        return ''
    lowered = cleaned.lower()
    if not any(marker in cleaned or marker in lowered for marker in _STATISTICAL_NARRATIVE_MARKERS):
        return cleaned
    kept: List[str] = []
    for line in cleaned.splitlines():
        line_lower = line.lower()
        if any(marker in line or marker in line_lower for marker in _STATISTICAL_NARRATIVE_MARKERS):
            continue
        kept.append(line)
    rewritten = strip_completeness_copy('\n'.join(kept))
    lines = [line for line in rewritten.splitlines()]
    while lines:
        tail = lines[-1].strip().lower()
        if not tail or 'תובנות' in lines[-1] or 'key insights' in tail:
            lines.pop()
            continue
        break
    return '\n'.join(lines).strip()


def _is_staff_column(name: str) -> bool:
    return _normalize_section_title(name) in _STAFF_COLUMN_TITLES


def customer_section_title(title: str) -> str:
    """Map staff/analysis headings to customer-facing copy."""
    mapped = _CUSTOMER_SECTION_TITLES.get(_normalize_section_title(title))
    return mapped or str(title or '')


def customer_report_title(summary: Dict[str, Any]) -> str:
    """Customer-facing title for the downloaded assessment."""
    is_hebrew = is_rtl_language(summary.get('language'))
    raw = str(summary.get('title') or '').strip()
    normalized = _normalize_section_title(raw)
    if summary.get('is_pension_data') or summary.get('pension_assessment'):
        if not raw or normalized in _GENERIC_ANALYSIS_TITLES:
            return 'ההערכה שלך' if is_hebrew else 'Your Assessment'
        if normalized in {
            'דוח ניתוח פנסיה וביטוח',
            'pension & insurance analysis report',
        }:
            return 'הערכת הפנסיה והביטוח שלך' if is_hebrew else 'Your Pension & Insurance Assessment'
        return raw
    if not raw or normalized in _GENERIC_ANALYSIS_TITLES:
        report_type = str(summary.get('report_type') or '').strip().lower()
        hebrew_by_type = {
            'insurance': 'הערכת הביטוח שלך',
            'investment': 'הערכת ההשקעות שלך',
            'risk': 'הערכת הסיכונים שלך',
            'savings': 'הערכת החיסכון שלך',
        }
        english_by_type = {
            'insurance': 'Your Insurance Assessment',
            'investment': 'Your Investment Assessment',
            'risk': 'Your Risk Assessment',
            'savings': 'Your Savings Assessment',
        }
        if is_hebrew:
            return hebrew_by_type.get(report_type, 'ההערכה שלך')
        return english_by_type.get(report_type, 'Your Assessment')
    return raw


def prepare_customer_download_sections(sections: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Keep assessment sections only; strip completeness copy; rename headings."""
    prepared: List[Dict[str, Any]] = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        title = section.get('title') or ''
        if is_non_assessment_section_title(title):
            continue
        content = customer_assessment_narrative(section.get('content') or '')
        rows = [row for row in (section.get('rows') or []) if isinstance(row, dict)]
        columns = [
            str(col) for col in (section.get('columns') or [])
            if not _is_staff_column(str(col))
        ]
        if rows and columns:
            rows = [
                {col: row.get(col, '') for col in columns}
                for row in rows
            ]
        elif rows:
            columns = [
                key for key in rows[0].keys()
                if not _is_staff_column(str(key))
            ]
            rows = [{col: row.get(col, '') for col in columns} for row in rows]
        if not content and not rows:
            continue
        prepared.append({
            **section,
            'title': customer_section_title(title),
            'content': content,
            'columns': columns,
            'rows': rows,
        })
    return prepared


# Completeness / staff-only charts that appear on the dashboard but are not
# part of the customer briefing.
_STAFF_CHART_TITLES = frozenset({
    'כיסוי שדות זיהוי',
    'id field coverage',
    'factors importance',
    'data distribution',
    'סהכ חיסכון',
    'total savings',
    'risk score',
})

BRAND_NAME = 'PHINS'
BRAND_TAGLINE = 'Personal Health Insurance & Savings · AI-Operated Insurance Platform'
BRAND_TAGLINE_HE = 'פלטפורמת ביטוח מופעלת-AI · ביטוח בריאות אישי וחיסכון'
PHINS_NAVY = '#0e2f63'
PHINS_NAVY_DEEP = '#060d1f'
PHINS_NAVY_MID = '#123f82'
PHINS_GOLD = '#c9a04e'
PHINS_GOLD_STRONG = '#f7e2a0'
PHINS_CYAN = '#4fd8ff'
PHINS_INK = '#12284c'
PHINS_ICE = '#f3f7fd'
PHINS_GREY = '#5b6b82'
_BRAND_CHART_COLORS = (
    PHINS_NAVY, PHINS_GOLD, PHINS_NAVY_MID, PHINS_CYAN, '#e3bf6f', '#6ea8ff',
)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_STATIC_DIR = os.path.join(_REPO_ROOT, 'web_portal', 'static')
_LOGO_PNG_CANDIDATES = (
    os.path.join(_STATIC_DIR, 'phins-logo.png'),
    os.path.join(_STATIC_DIR, 'phins-logo.svg'),
)


def is_staff_chart_title(title: str) -> bool:
    normalized = _normalize_section_title(title)
    if normalized in _STAFF_CHART_TITLES:
        return True
    return 'כיסוי שדות זיהוי' in str(title or '') or 'id field coverage' in normalized


_STAFF_RECOMMENDATION_MARKERS = (
    'missing values',
    'missing data',
    'data collection process',
    'columns have',
    'data completeness',
    'שלמות נתונים',
    'ערכים חסרים',
    'נתונים חסרים',
)


def prepare_customer_download_recommendations(
    recs: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Keep advisor talking points; drop file-quality / completeness notes."""
    prepared: List[Dict[str, Any]] = []
    for rec in recs or []:
        if not isinstance(rec, dict):
            continue
        title = str(rec.get('title') or '')
        raw_desc = str(rec.get('description') or '')
        blob = f'{title} {raw_desc}'.lower()
        if any(marker in blob for marker in _STAFF_RECOMMENDATION_MARKERS):
            continue
        desc = strip_completeness_copy(raw_desc)
        if not title.strip() and not desc.strip():
            continue
        prepared.append({**rec, 'title': title, 'description': desc})
    return prepared


def prepare_customer_download_charts(charts: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Keep the Analyse dashboard charts that help a consultant brief the customer."""
    prepared: List[Dict[str, Any]] = []
    for chart in charts or []:
        if not isinstance(chart, dict):
            continue
        title = chart.get('title') or ''
        chart_type = str(chart.get('type') or '').lower()
        if is_staff_chart_title(title) or is_non_assessment_section_title(title):
            continue
        if chart_type == 'gauge':
            continue
        series = []
        for point in chart.get('series') or []:
            if not isinstance(point, dict):
                continue
            if point.get('value') in (None, ''):
                continue
            series.append({
                'label': str(point.get('label') or ''),
                'value': point.get('value'),
            })
        if not series:
            continue
        prepared.append({
            'title': title,
            'type': chart_type or 'bar',
            'series': series[:12],
        })
    return prepared


# Uploaded risk-cover types a consultant walks through with the customer.
# Only rows with an uploaded amount or cost are shown — never invented.
_COVER_FIELD_SPECS = (
    ('death_lump_sum', 'death_lump_sum', '', 'סכום ביטוח למקרה מוות – חד פעמי', 'Lump-sum death benefit'),
    ('life', 'death_coverage', 'death_premium', 'ביטוח חיים', 'Life Insurance'),
    ('disability_work', 'disability_coverage', 'disability_premium', 'אבדן כושר עבודה', 'Loss of Work Capacity'),
    ('disability_work', 'work_disability_coverage', 'work_disability_premium', 'אבדן כושר עבודה', 'Loss of Work Capacity'),
    ('invalidity', 'invalidity_coverage', 'invalidity_premium', 'נכות', 'Disability'),
    ('waiver', 'waiver_coverage', 'waiver_premium', 'שחרור', 'Premium Waiver'),
    ('survivors', 'survivors_coverage', 'survivors_premium', 'שארים', 'Survivors'),
    ('ltc', 'ltc_coverage', 'ltc_premium', 'סיעוד', 'Long-Term Care'),
    ('severance', 'severance_balance', 'severance_premium', 'פיצויים', 'Severance'),
)

_COVER_CODE_LABELS = {
    '1': ('life', 'ביטוח חיים', 'Life Insurance'),
    '2': ('disability_work', 'אבדן כושר עבודה', 'Loss of Work Capacity'),
    '3': ('invalidity', 'נכות', 'Disability'),
    '4': ('waiver', 'שחרור', 'Premium Waiver'),
    '5': ('survivors', 'שארים', 'Survivors'),
    '6': ('ltc', 'סיעוד', 'Long-Term Care'),
}

ACCOUNT_COVER_COPY_KEYS = (
    'death_lump_sum',
    'death_coverage', 'death_premium',
    'disability_coverage', 'disability_premium',
    'work_disability_coverage', 'work_disability_premium',
    'invalidity_coverage', 'invalidity_premium',
    'waiver_coverage', 'waiver_premium',
    'survivors_coverage', 'survivors_premium',
    'ltc_coverage', 'ltc_premium',
    'severance_premium',
    'coverage_amount',
    'risk_covers',
)

# Holdings columns kept distinct from צבירה. Copied only when uploaded.
ACCOUNT_DETAIL_COPY_KEYS = (
    'product_name', 'balance', 'tagmulim_balance',
    'start_date', 'liquidity_date', 'status_date',
    'management_fee', 'management_fee_savings', 'management_fee_deposits',
    'last_deposit', 'last_deposit_date', 'contribution_type',
    'monthly_premium', 'investment_track', 'track_percent', 'yield_rate',
)


def _as_cover_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def classify_cover_type(code: Any, name: Any) -> Tuple[str, str, str]:
    """Map an uploaded cover code/name to a consultant-facing type."""
    from services.pension.schema import DEATH_LUMP_SUM_LABEL, normalize_hebrew_header

    label = str(name or '').strip()
    code_text = str(code or '').strip()
    normalized = normalize_hebrew_header(label)
    if 'למקרה מוות' in normalized and 'חד פעמי' in normalized:
        return 'death_lump_sum', DEATH_LUMP_SUM_LABEL, 'Lump-sum death benefit'
    mapped = _COVER_CODE_LABELS.get(code_text)
    if mapped and not label:
        return mapped
    blob = label
    lowered = label.lower()
    if 'פיצויים' in blob or 'pitzuim' in lowered or 'severance' in lowered:
        return 'severance', 'פיצויים', 'Severance'
    if 'סיעוד' in blob or 'long-term' in lowered or 'long term' in lowered or 'ltc' in lowered:
        return 'ltc', 'סיעוד', 'Long-Term Care'
    if 'שארים' in blob or 'survivor' in lowered:
        return 'survivors', 'שארים', 'Survivors'
    if 'שחרור' in blob or 'waiver' in lowered:
        return 'waiver', 'שחרור', 'Premium Waiver'
    if 'אבדן כושר' in blob or 'אובדן כושר' in blob or 'akw' in lowered or 'work capacity' in lowered:
        return 'disability_work', 'אבדן כושר עבודה', 'Loss of Work Capacity'
    if ('נכות' in blob and 'כושר' not in blob) or (lowered == 'disability'):
        return 'invalidity', 'נכות', 'Disability'
    if 'חיים' in blob or 'מוות' in blob or 'life' in lowered or 'death' in lowered:
        return 'life', 'ביטוח חיים', 'Life Insurance'
    if mapped:
        return mapped
    return 'other', label or code_text or 'כיסוי', label or code_text or 'Cover'


def _severance_uploaded_amount(record: Dict[str, Any]) -> float:
    """First uploaded פיצויים figure on a severance record — never inferred."""
    for key in ('total_severance', 'severance_balance', 'available_severance', 'amount'):
        amount = _as_cover_number(record.get(key))
        if amount > 0:
            return amount
    return 0.0


def collect_uploaded_risk_covers(
    accounts: Optional[List[Dict[str, Any]]],
    severance_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build cover rows only from values present on the uploaded accounts."""
    collected: List[Dict[str, Any]] = []
    seen: set = set()

    def add_row(row: Dict[str, Any]) -> None:
        amount = _as_cover_number(row.get('amount'))
        cost = _as_cover_number(row.get('cost'))
        if amount <= 0 and cost <= 0:
            return
        key = (
            row.get('type_key'),
            row.get('policy_number'),
            row.get('provider'),
            round(amount, 2),
            round(cost, 2),
        )
        if key in seen:
            return
        seen.add(key)
        collected.append({
            'type_key': row.get('type_key') or 'other',
            'title_he': row.get('title_he') or '',
            'title_en': row.get('title_en') or '',
            'amount': amount,
            'cost': cost,
            'policy_number': row.get('policy_number') or '',
            'provider': row.get('provider') or '',
        })

    for acct in accounts or []:
        if not isinstance(acct, dict):
            continue
        policy = str(acct.get('policy_number') or '')
        provider = str(acct.get('provider') or '')
        nested = [item for item in (acct.get('risk_covers') or []) if isinstance(item, dict)]
        stamped: set = set()
        for item in nested:
            type_key, title_he, title_en = classify_cover_type(item.get('code'), item.get('name'))
            add_row({
                'type_key': type_key,
                'title_he': title_he,
                'title_en': title_en,
                'amount': item.get('amount'),
                'cost': item.get('cost'),
                'policy_number': policy,
                'provider': provider,
            })
            stamped.add(type_key)
        for type_key, amount_field, cost_field, title_he, title_en in _COVER_FIELD_SPECS:
            if type_key in stamped:
                continue
            add_row({
                'type_key': type_key,
                'title_he': title_he,
                'title_en': title_en,
                'amount': acct.get(amount_field),
                'cost': acct.get(cost_field),
                'policy_number': policy,
                'provider': provider,
            })

    for record in severance_records or []:
        if not isinstance(record, dict):
            continue
        add_row({
            'type_key': 'severance',
            'title_he': 'פיצויים',
            'title_en': 'Severance',
            'amount': _severance_uploaded_amount(record),
            'cost': record.get('severance_premium') or record.get('cost'),
            'policy_number': record.get('policy_number') or '',
            'provider': record.get('provider') or record.get('employer_name') or '',
        })
    return collected


def cover_chart_summaries(covers: Optional[List[Dict[str, Any]]], is_hebrew: bool) -> List[Dict[str, Any]]:
    """Bar configs for uploaded cover amounts and costs (only when values exist)."""
    amounts: Dict[str, float] = {}
    costs: Dict[str, float] = {}
    for cover in covers or []:
        label = (cover.get('title_he') if is_hebrew else cover.get('title_en')) or cover.get('title_he') or ''
        if not label:
            continue
        amount = _as_cover_number(cover.get('amount'))
        cost = _as_cover_number(cover.get('cost'))
        if amount > 0:
            amounts[label] = amounts.get(label, 0.0) + amount
        if cost > 0:
            costs[label] = costs.get(label, 0.0) + cost
    charts: List[Dict[str, Any]] = []
    if amounts:
        charts.append({
            'title': 'כיסויים ביטוחיים' if is_hebrew else 'Insurance Coverage',
            'type': 'bar',
            'series': [{'label': label, 'value': value} for label, value in amounts.items()],
        })
    if costs:
        charts.append({
            'title': 'עלות הכיסויים' if is_hebrew else 'Cover Costs',
            'type': 'bar',
            'series': [{'label': label, 'value': value} for label, value in costs.items()],
        })
    return charts


def customer_signature_identity(summary: Dict[str, Any]) -> Tuple[str, str]:
    """Name and national ID printed on the customer signature block."""
    pension = summary.get('pension_assessment') or {}
    client = pension.get('client') or {}
    sci = summary.get('savings_cover_id_summary') or {}
    name = (
        client.get('full_name')
        or client.get('client_name')
        or ' '.join(part for part in (client.get('first_name'), client.get('last_name')) if part)
        or sci.get('customer_name')
        or ''
    )
    ident = client.get('id_number') or sci.get('customer_id') or ''
    return str(name or '').strip(), str(ident or '').strip()


def consultant_intro_copy(is_hebrew: bool) -> str:
    if is_hebrew:
        return (
            'מסמך זה מיועד לשיחה עם היועץ שלך. הוא מציג את ההערכה אחרי הניתוח — '
            'החיסכון, הפיצויים, הפוליסות והתרשימים — כדי שתוכלו לעבור יחד על המספרים.'
        )
    return (
        'Use this briefing in a conversation with your advisor. It shows the '
        'assessment after Analyse — savings, severance, policies and the charts '
        'on screen — so you can walk through the numbers together.'
    )


def _as_str(val: Any) -> str:
    if val is None:
        return ''
    if isinstance(val, float):
        if val == int(val):
            return f"{int(val)}"
        return f"{val:,.2f}"
    return str(val)


def _as_when(val: Any) -> str:
    """Compact prepared-on stamp a consultant can read at a glance."""
    text = str(val or '').strip()
    if not text:
        return ''
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        return parsed.strftime('%d %b %Y  %H:%M')
    except Exception:
        return text.replace('T', ' ')[:16]


def _as_money(val: Any) -> str:
    if val is None or val == '':
        return '₪0.00'
    try:
        number = float(val)
    except (TypeError, ValueError):
        return str(val)
    return f"₪{number:,.2f}"


def _uploaded(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    text = str(value).strip()
    return text not in {'', '0', '0.0', '0.00'}


def _active_holdings_table(specs, records):
    """Keep a column only when some row actually uploaded a value.

    ``specs`` entries are ``(header, getter, kind)`` with kind ``id``,
    ``text`` or ``money``.
    """
    active = []
    for header, getter, kind in specs:
        if kind == 'id' or any(_uploaded(getter(record)) for record in records):
            active.append((header, getter, kind))
    if not active:
        return [], []
    headers = [header for header, _getter, _kind in active]
    rows = []
    for record in records:
        row = []
        for _header, getter, kind in active:
            value = getter(record)
            if kind == 'money':
                row.append(_as_money(value) if _uploaded(value) else '')
            elif kind == 'percent':
                try:
                    row.append(f"{float(value):.2f}%" if _uploaded(value) else '')
                except (TypeError, ValueError):
                    row.append(_as_str(value) if _uploaded(value) else '')
            else:
                row.append(_as_str(value) if _uploaded(value) or kind == 'id' else '')
        rows.append(row)
    return headers, rows


def _holdings_money_specs(is_hebrew: bool):
    from services.pension.schema import account_accumulation, tagmulim_amount
    return [
        ('פוליסה' if is_hebrew else 'Policy', lambda account: account.get('policy_number'), 'id'),
        ('יצרן' if is_hebrew else 'Provider', lambda account: account.get('provider'), 'id'),
        ('סה״כ חיסכון' if is_hebrew else 'Accumulation', account_accumulation, 'money'),
        ('תגמולים' if is_hebrew else 'Tagmulim', tagmulim_amount, 'money'),
        ('פיצויים' if is_hebrew else 'Severance', lambda account: account.get('severance_balance'), 'money'),
        ('יתרה' if is_hebrew else 'Balance', lambda account: account.get('balance'), 'money'),
    ]


def _holdings_detail_specs(is_hebrew: bool):
    """Two narrower tables so dates, fees and track percents stay readable."""
    policy = ('פוליסה' if is_hebrew else 'Policy', lambda account: account.get('policy_number'), 'id')
    dates = [
        policy,
        ('סוג מוצר' if is_hebrew else 'Product Type', lambda account: account.get('product_type_name') or account.get('product_type'), 'text'),
        ('שם מוצר' if is_hebrew else 'Product Name', lambda account: account.get('product_name'), 'text'),
        ('סטטוס' if is_hebrew else 'Status', lambda account: account.get('status'), 'text'),
        ('מסלול' if is_hebrew else 'Track', lambda account: account.get('investment_track'), 'text'),
        ('תאריך הצטרפות' if is_hebrew else 'Join Date', lambda account: account.get('start_date'), 'text'),
        ('תאריך נזילות' if is_hebrew else 'Liquidity Date', lambda account: account.get('liquidity_date'), 'text'),
        ('תאריך סטטוס' if is_hebrew else 'Status Date', lambda account: account.get('status_date'), 'text'),
    ]
    fees = [
        policy,
        ('דמי ניהול מצבירה' if is_hebrew else 'Fee on Savings', lambda account: account.get('management_fee_savings'), 'percent'),
        ('דמי ניהול מהפקדה' if is_hebrew else 'Fee on Deposits', lambda account: account.get('management_fee_deposits'), 'percent'),
        ('הפקדה אחרונה' if is_hebrew else 'Last Deposit', lambda account: account.get('last_deposit'), 'money'),
        ('תאריך הפקדה אחרונה' if is_hebrew else 'Last Deposit Date', lambda account: account.get('last_deposit_date'), 'text'),
        ('מעסיק' if is_hebrew else 'Employer', lambda account: account.get('employer_name'), 'text'),
        ('סוג הפרשה' if is_hebrew else 'Contribution Type', lambda account: account.get('contribution_type'), 'text'),
        ('סה״כ פרמיה חודשית' if is_hebrew else 'Monthly Premium', lambda account: account.get('monthly_premium'), 'money'),
        ('אחוז במסלול' if is_hebrew else 'Track Percent', lambda account: account.get('track_percent'), 'percent'),
        ('תשואה' if is_hebrew else 'Yield', lambda account: account.get('yield_rate'), 'percent'),
    ]
    return dates, fees


def _accumulation_total_pairs(totals: Dict[str, Any], is_hebrew: bool) -> List[List[Any]]:
    """Headline צבירה, then תגמולים / פיצויים / יתרה only when uploaded separately."""
    def money(key, default=0):
        try:
            return float(totals.get(key, default) or 0)
        except (TypeError, ValueError):
            return 0.0

    accumulation = money('total_balance')
    tagmulim = money('total_tagmulim')
    savings = money('total_savings')
    severance = money('total_severance')
    yitra = money('total_yitra')
    pairs = []
    if accumulation or savings:
        pairs.append(['סה״כ צבירה' if is_hebrew else 'Total Accumulation', _as_money(accumulation or savings)])
    if tagmulim > 0:
        pairs.append(['סה״כ תגמולים' if is_hebrew else 'Total Tagmulim', _as_money(tagmulim)])
    elif savings > 0 and abs(savings - accumulation) > 0.01:
        pairs.append(['סה״כ חיסכון' if is_hebrew else 'Total Savings', _as_money(savings)])
    if severance > 0:
        pairs.append(['סה״כ פיצויים' if is_hebrew else 'Total Severance', _as_money(severance)])
    if yitra > 0 and abs(yitra - (accumulation or savings)) > 0.01:
        pairs.append(['סה״כ יתרה' if is_hebrew else 'Ledger Balance', _as_money(yitra)])
    count = totals.get('account_count')
    if count not in (None, ''):
        pairs.append(['מספר פוליסות' if is_hebrew else 'Number of Policies', _as_str(count)])
    return pairs


def _register_fonts() -> Tuple[str, str]:
    """Register a Hebrew-capable pair; fall back to Helvetica if unavailable."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        return 'Helvetica', 'Helvetica-Bold'

    candidates = (
        (os.path.join(_STATIC_DIR, 'fonts', 'DejaVuSans.ttf'),
         os.path.join(_STATIC_DIR, 'fonts', 'DejaVuSans-Bold.ttf'),
         'DejaVuSans', 'DejaVuSans-Bold'),
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
         'DejaVuSans', 'DejaVuSans-Bold'),
        ('/workspace/web_portal/static/fonts/DejaVuSans.ttf',
         '/workspace/web_portal/static/fonts/DejaVuSans-Bold.ttf',
         'DejaVuSans', 'DejaVuSans-Bold'),
    )
    registered = set(pdfmetrics.getRegisteredFontNames())
    for regular_path, bold_path, regular_name, bold_name in candidates:
        if os.path.exists(regular_path):
            if regular_name not in registered:
                pdfmetrics.registerFont(TTFont(regular_name, regular_path))
            if os.path.exists(bold_path) and bold_name not in registered:
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            return regular_name, bold_name if os.path.exists(bold_path) else regular_name
    return 'Helvetica', 'Helvetica-Bold'


def _measure_text_width(text: str, font: str, size: float) -> float:
    """Width of one cell's text in the PDF font — used to size columns."""
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except Exception:
        return max(8.0, float(len(str(text or ''))) * max(size, 1.0) * 0.5)
    return float(stringWidth(str(text or ''), font, size))


def text_adjusted_col_widths(
    columns: List[List[str]],
    *,
    usable_width: float,
    font: str,
    size: float,
    padding: float = 14.0,
    min_width: float = 36.0,
) -> List[float]:
    """Column widths from the longest cell in each column, then fit the text column.

    Each column is at least as wide as its text (plus padding). Extra room in
    the page text column is shared by text weight so long Hebrew labels keep
    their share instead of being clipped by equal-width slots.
    """
    if not columns:
        return []
    page_width = max(1.0, float(usable_width or 0) or 1.0)
    natural: List[float] = []
    for col in columns:
        widest = 0.0
        for cell in col:
            widest = max(widest, _measure_text_width(cell, font, size))
        natural.append(max(min_width, widest + padding))
    total = sum(natural)
    if total <= 0:
        return [page_width / len(columns)] * len(columns)
    if total > page_width:
        scale = page_width / total
        return [width * scale for width in natural]
    extra = page_width - total
    return [width + extra * (width / total) for width in natural]


def kv_text_adjusted_widths(
    label_texts: List[str],
    value_texts: List[str],
    *,
    usable_width: float,
    font: str,
    size: float,
    rtl: bool,
) -> List[float]:
    """Label column follows its text; the value column takes the remaining text width."""
    page_width = max(1.0, float(usable_width or 0) or 1.0)
    padding = 16.0
    min_width = 40.0
    label_width = max(
        min_width,
        max((_measure_text_width(text, font, size) for text in label_texts), default=0.0) + padding,
    )
    label_width = min(label_width, page_width * 0.42)
    value_width = max(min_width, page_width - label_width)
    if label_width + value_width > page_width:
        value_width = max(min_width, page_width - label_width)
    return [value_width, label_width] if rtl else [label_width, value_width]


def _style_table(table, header_color: str = PHINS_NAVY, rtl: bool = False):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    align = 'RIGHT' if rtl else 'LEFT'
    table.hAlign = 'RIGHT' if rtl else 'LEFT'
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(header_color)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(PHINS_GOLD_STRONG)),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor(PHINS_ICE)),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(PHINS_INK)),
        ('LINEBELOW', (0, 0), (-1, 0), 1.2, colors.HexColor(PHINS_GOLD)),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#d7e2f5')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), align),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    return table


def _rtl_break_lines(text: str, font: str, size: float, max_width: float) -> List[str]:
    """Greedy wrap of logical text so each line can be bidi-reordered."""
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


def _safe_paragraph(text: str, style, rtl: bool = False, max_width: float = 0) -> Any:
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

    cleaned = html.escape(raw).replace('\n', '<br/>')
    return Paragraph(cleaned, style)


def _kv_rows(rows: List[List[str]], rtl: bool) -> List[List[str]]:
    """Put the label on the visual right for Hebrew key/value tables."""
    if not rtl:
        return rows
    return [list(reversed(row)) for row in rows]


def _navy_cell_style(cell_style):
    """Gold-on-navy clone of a cell style for labels and table headers.

    A table's TEXTCOLOR never reaches Paragraph flowables, so a cell that
    sits on the navy fill has to carry the complementary colour itself.
    """
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        f'{getattr(cell_style, "name", "Cell")}OnNavy', parent=cell_style,
        textColor=colors.HexColor(PHINS_GOLD_STRONG),
    )


def _kv_display(
    rows: List[List[str]],
    cell_style,
    label_style,
    rtl: bool,
    col_widths: Optional[List[float]] = None,
) -> List[List[Any]]:
    """Render key/value rows, keeping the label column readable on navy."""
    label_col = 1 if rtl else 0
    widths = list(col_widths or [])
    return [
        [
            _safe_paragraph(
                cell, label_style if index == label_col else cell_style,
                rtl=rtl, max_width=widths[index] if index < len(widths) else 160,
            )
            for index, cell in enumerate(row)
        ]
        for row in rows
    ]


def _build_kv_table(
    pairs: List[List[str]],
    cell_style,
    label_style,
    *,
    rtl: bool,
    usable_width: float,
    font: str,
    size: float = 9,
):
    from reportlab.platypus import Table

    raw = _kv_rows(pairs, rtl)
    if rtl:
        value_texts = [row[0] for row in raw]
        label_texts = [row[1] for row in raw]
    else:
        label_texts = [row[0] for row in raw]
        value_texts = [row[1] for row in raw]
    widths = kv_text_adjusted_widths(
        label_texts, value_texts,
        usable_width=usable_width, font=font, size=size, rtl=rtl,
    )
    display = _kv_display(raw, cell_style, label_style, rtl, widths)
    table = Table(display, colWidths=widths)
    _style_kv_table(table, rtl=rtl)
    return table


def _build_text_table(
    headers: List[str],
    rows: List[List[str]],
    *,
    cell_style,
    header_style,
    rtl: bool,
    usable_width: float,
    font: str,
    size: float = 8,
):
    from reportlab.platypus import Table

    display_headers = list(reversed(headers)) if rtl else list(headers)
    display_rows = [list(reversed(row)) if rtl else list(row) for row in rows]
    column_count = len(display_headers)
    columns: List[List[str]] = []
    for index in range(column_count):
        column = [display_headers[index]]
        for row in display_rows:
            column.append(row[index] if index < len(row) else '')
        columns.append(column)
    widths = text_adjusted_col_widths(
        columns, usable_width=usable_width, font=font, size=size,
    )
    table_data: List[List[Any]] = [[
        _safe_paragraph(header, header_style, rtl=rtl, max_width=width)
        for header, width in zip(display_headers, widths)
    ]]
    for row in display_rows:
        table_data.append([
            _safe_paragraph(cell, cell_style, rtl=rtl, max_width=width)
            for cell, width in zip(row, widths)
        ])
    table = Table(table_data, colWidths=widths, repeatRows=1)
    _style_table(table, rtl=rtl)
    return table


def _logo_png_path() -> Optional[str]:
    png = os.path.join(_STATIC_DIR, 'phins-logo.png')
    if os.path.isfile(png):
        return png
    return None


def _draw_phins_emblem(canvas, x: float, y: float, size: float) -> None:
    """Draw the PHINS shield emblem (navy fill, gold rim) at bottom-left x,y."""
    from reportlab.lib import colors

    scale = size / 120.0
    canvas.saveState()
    canvas.translate(x, y)
    canvas.scale(scale, scale)
    # SVG y-down → PDF y-up: Y' = 120 - y
    path = canvas.beginPath()
    path.moveTo(60, 114)
    path.lineTo(106, 98)
    path.lineTo(106, 63)
    path.curveTo(106, 32, 86, 12, 60, 4)
    path.curveTo(34, 12, 14, 32, 14, 63)
    path.lineTo(14, 98)
    path.close()
    canvas.setFillColor(colors.HexColor(PHINS_NAVY))
    canvas.setStrokeColor(colors.HexColor(PHINS_GOLD))
    canvas.setLineWidth(4)
    canvas.setLineJoin(1)
    canvas.drawPath(path, fill=1, stroke=1)
    star = canvas.beginPath()
    star.moveTo(60, 98)
    star.lineTo(62.2, 91.8)
    star.lineTo(68.5, 91.6)
    star.lineTo(63.5, 87.8)
    star.lineTo(65.3, 81.7)
    star.lineTo(60, 85.3)
    star.lineTo(54.7, 81.7)
    star.lineTo(56.5, 87.8)
    star.lineTo(51.5, 91.6)
    star.lineTo(57.8, 91.8)
    star.close()
    canvas.setFillColor(colors.HexColor(PHINS_GOLD_STRONG))
    canvas.drawPath(star, fill=1, stroke=0)
    fin = canvas.beginPath()
    fin.moveTo(40, 44)
    fin.curveTo(44.5, 63, 57, 76, 80, 81.5)
    fin.curveTo(72.5, 69.5, 70.5, 59, 73, 46.5)
    fin.curveTo(61.5, 53.5, 49, 51, 40, 44)
    fin.close()
    canvas.setFillColor(colors.HexColor(PHINS_CYAN))
    canvas.drawPath(fin, fill=1, stroke=0)
    canvas.restoreState()


def _draw_brand_header(canvas, doc, *, rtl: bool, title: str, font: str, bold: str) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    width, height = A4
    band = 54
    canvas.saveState()
    # shade() fills the current clip — keep the navy gradient on the letterhead
    # band so the assessment page stays white and easy to read.
    clip = canvas.beginPath()
    clip.rect(0, height - band, width, band)
    canvas.clipPath(clip, stroke=0, fill=0)
    try:
        canvas.linearGradient(
            0, height - band, 0, height,
            [colors.HexColor(PHINS_NAVY_DEEP), colors.HexColor(PHINS_NAVY_MID)],
            extend=False,
        )
    except Exception:
        canvas.setFillColor(colors.HexColor(PHINS_NAVY))
        canvas.rect(0, height - band, width, band, fill=1, stroke=0)
    canvas.restoreState()
    canvas.saveState()
    canvas.setFillColor(colors.HexColor(PHINS_GOLD))
    canvas.rect(0, height - band - 3, width, 3, fill=1, stroke=0)

    emblem_size = 28
    left = 16 * 2.83465  # ~16mm
    right = width - left
    emblem_y = height - band + 12
    logo = _logo_png_path()
    if rtl:
        if logo:
            canvas.drawImage(logo, right - emblem_size, emblem_y, width=emblem_size,
                             height=emblem_size, mask='auto', preserveAspectRatio=True)
        else:
            _draw_phins_emblem(canvas, right - emblem_size, emblem_y, emblem_size)
        text_x = right - emblem_size - 10
        canvas.setFillColor(colors.white)
        canvas.setFont(bold, 16)
        canvas.drawRightString(text_x, emblem_y + 14, BRAND_NAME)
        canvas.setFillColor(colors.HexColor(PHINS_GOLD_STRONG))
        canvas.setFont(font, 7.2)
        tag = bidi_text(BRAND_TAGLINE_HE, rtl=True)
        canvas.drawRightString(text_x, emblem_y + 3, tag)
    else:
        if logo:
            canvas.drawImage(logo, left, emblem_y, width=emblem_size,
                             height=emblem_size, mask='auto', preserveAspectRatio=True)
        else:
            _draw_phins_emblem(canvas, left, emblem_y, emblem_size)
        text_x = left + emblem_size + 10
        canvas.setFillColor(colors.white)
        canvas.setFont(bold, 16)
        canvas.drawString(text_x, emblem_y + 14, BRAND_NAME)
        canvas.setFillColor(colors.HexColor(PHINS_GOLD_STRONG))
        canvas.setFont(font, 7.2)
        canvas.drawString(text_x, emblem_y + 3, BRAND_TAGLINE)
    canvas.restoreState()


def _draw_brand_footer(canvas, doc, *, rtl: bool, font: str) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    width, _height = A4
    left = 16 * 2.83465
    right = width - left
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor(PHINS_GOLD))
    canvas.setLineWidth(0.9)
    canvas.line(left, 28, right, 28)
    note = (
        bidi_text('פינס — הערכת לקוח לשיחת ייעוץ', rtl=True)
        if rtl else
        'PHINS — Customer assessment for advisor conversation'
    )
    canvas.setFillColor(colors.HexColor(PHINS_GREY))
    canvas.setFont(font, 7)
    _draw_phins_emblem(canvas, left, 10, 12)
    canvas.drawString(left + 16, 13, note)
    canvas.drawRightString(right, 13, f"{doc.page}")
    canvas.restoreState()


def _page_callbacks(rtl: bool, title: str, font: str, bold: str):
    def on_first(canvas, doc):
        _draw_brand_header(canvas, doc, rtl=rtl, title=title, font=font, bold=bold)
        _draw_brand_footer(canvas, doc, rtl=rtl, font=font)

    def on_later(canvas, doc):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        width, height = A4
        left = 16 * 2.83465
        right = width - left
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(PHINS_NAVY))
        canvas.rect(0, height - 22, width, 22, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor(PHINS_GOLD))
        canvas.rect(0, height - 25, width, 3, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor(PHINS_GOLD_STRONG))
        canvas.setFont(bold, 8)
        running = bidi_text(title, rtl=True) if rtl else title
        if rtl:
            canvas.drawRightString(right, height - 16, running)
        else:
            canvas.drawString(left, height - 16, f"{BRAND_NAME}  ·  {running}")
        canvas.restoreState()
        _draw_brand_footer(canvas, doc, rtl=rtl, font=font)

    return on_first, on_later


def _consultant_intro_box(is_hebrew: bool, body_style, usable_width: float):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    text = consultant_intro_copy(is_hebrew)
    para = _safe_paragraph(text, body_style, rtl=is_hebrew, max_width=usable_width - 16)
    box = Table([[para]], colWidths=[usable_width])
    box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(PHINS_ICE)),
        ('BOX', (0, 0), (-1, -1), 1.1, colors.HexColor(PHINS_GOLD)),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return box


def chart_category_label(
    text: str,
    *,
    rtl: bool,
    font_name: str,
    font_size: float,
    max_width: float,
) -> str:
    """Wrap a chart name in logical order, then bidi each finished line.

    ReportLab splits whatever string it is given. Slicing or wrapping after
    ``bidi_text`` cuts a visual Hebrew line into fragments that no longer
    read as the original phrase ("הכשרה ביטוח", "ביטוח סיכונים - חד פעמי").
    """
    raw = _as_str(text).strip()
    if not raw:
        return ''
    width = max(24.0, float(max_width or 0) or 120.0)
    lines = None
    # Product types read better as two clauses ("ביטוח סיכונים" / "חד פעמי")
    # than as a line that stops in the middle of the second clause.
    if ' - ' in raw and _measure_text_width(raw, font_name, font_size) > width:
        left, right = raw.split(' - ', 1)
        if (
            _measure_text_width(left, font_name, font_size) <= width
            and _measure_text_width(right, font_name, font_size) <= width
        ):
            lines = [left, right]
    if lines is None:
        lines = _rtl_break_lines(raw, font_name, font_size, width)
    if rtl and has_hebrew(raw):
        lines = [bidi_text(line, rtl=True) for line in lines]
    return '\n'.join(lines)


def _chart_series_values(series: List[Dict[str, Any]]) -> List[float]:
    values: List[float] = []
    for point in series:
        try:
            values.append(float(point.get('value') or 0))
        except (TypeError, ValueError):
            values.append(0.0)
    return values


def _chart_legend(series, palette, font_name, width, height, rtl, text_width):
    """Color key with the full category name, beside the pie."""
    from reportlab.graphics.shapes import Group, Rect, String
    from reportlab.lib import colors

    font_size = 8.0
    ink = colors.HexColor(PHINS_INK)
    prepared = None
    while font_size >= 6:
        leading = font_size * 1.25
        rows = []
        total = 0.0
        for index, point in enumerate(series):
            lines = [
                line for line in chart_category_label(
                    point.get('label'), rtl=rtl, font_name=font_name,
                    font_size=font_size, max_width=text_width,
                ).split('\n') if line
            ] or ['']
            rows.append((index, lines))
            total += len(lines) * leading + 3
        if total <= height - 6 or font_size <= 6:
            prepared = (font_size, leading, rows, total)
            break
        font_size -= 0.5
    font_size, leading, rows, total = prepared
    legend = Group()
    y = height - max(4.0, (height - total) / 2) - font_size
    swatch = 7
    if rtl:
        swatch_x = width - 4 - swatch
        text_x = swatch_x - 4
        anchor = 'end'
    else:
        swatch_x = width - text_width - swatch - 8
        text_x = swatch_x + swatch + 4
        anchor = 'start'
    for index, lines in rows:
        legend.add(Rect(
            swatch_x, y - 1, swatch, swatch,
            fillColor=palette[index % len(palette)],
            strokeColor=None,
        ))
        for line in lines:
            legend.add(String(
                text_x, y, line,
                fontName=font_name, fontSize=font_size,
                textAnchor=anchor, fillColor=ink,
            ))
            y -= leading
        y -= 3
    return legend


def _chart_drawing(chart: Dict[str, Any], width: float, height: float, rtl: bool, font_name: str):
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors

    series = [point for point in (chart.get('series') or []) if isinstance(point, dict)]
    values = _chart_series_values(series)
    if not values:
        return None
    drawing = Drawing(width, height)
    chart_type = str(chart.get('type') or 'bar').lower()
    palette = [colors.HexColor(code) for code in _BRAND_CHART_COLORS]
    if chart_type in {'pie', 'doughnut'}:
        pie = Pie()
        size = min(height - 16, width * 0.42)
        size = max(48.0, size)
        pie.x = 4
        pie.y = max(6, (height - size) / 2)
        pie.width = size
        pie.height = size
        pie.data = values
        # Names live in the legend. Wedge labels overlap and were sliced
        # after bidi, so a long product type lost its first letter.
        pie.labels = [''] * len(values)
        pie.simpleLabels = 1
        pie.slices.strokeWidth = 0.6
        pie.slices.strokeColor = colors.white
        if chart_type == 'doughnut':
            pie.innerRadiusFraction = 0.48
        for index, _value in enumerate(values):
            pie.slices[index].fillColor = palette[index % len(palette)]
        text_width = max(48.0, width - size - 28)
        drawing.add(pie)
        drawing.add(_chart_legend(
            series, palette, font_name, width, height, rtl, text_width,
        ))
        return drawing

    count = max(1, len(series))
    font_size = 8 if count <= 4 else 7
    slot = max(28.0, (width - 52) / count - 4)
    labels = [
        chart_category_label(
            point.get('label'), rtl=rtl, font_name=font_name,
            font_size=font_size, max_width=slot,
        )
        for point in series
    ]
    line_count = max((text.count('\n') + 1 for text in labels), default=1)
    leading = font_size * 1.2
    label_band = line_count * leading + 8
    bar = VerticalBarChart()
    bar.x = 42
    bar.y = label_band
    bar.height = max(36, height - label_band - 8)
    bar.width = max(40, width - 54)
    bar.data = [values]
    bar.categoryAxis.categoryNames = labels
    # maxWidth stays unset: simpleSplit must not re-break the visual lines.
    bar.categoryAxis.labels.fontName = font_name
    bar.categoryAxis.labels.fontSize = font_size
    bar.categoryAxis.labels.leading = leading
    bar.categoryAxis.labels.angle = 0
    bar.categoryAxis.labels.boxAnchor = 'n'
    bar.categoryAxis.labels.textAnchor = 'middle'
    bar.categoryAxis.labels.dy = -2
    bar.valueAxis.valueMin = 0
    bar.valueAxis.labels.fontName = font_name
    bar.valueAxis.labels.fontSize = 7
    bar.bars[0].fillColor = colors.HexColor(PHINS_NAVY)
    bar.bars.strokeWidth = 0
    for index, _value in enumerate(values):
        try:
            bar.bars[(0, index)].fillColor = palette[index % len(palette)]
        except Exception:
            pass
    drawing.add(bar)
    return drawing


def _chart_value_caption(chart: Dict[str, Any], style, rtl: bool, max_width: float):
    """Short number line so a consultant can talk through the chart without guessing."""
    parts: List[str] = []
    for point in (chart.get('series') or [])[:8]:
        label = _as_str(point.get('label'))
        value = point.get('value')
        try:
            number = float(value)
            value_text = f"₪{number:,.0f}" if abs(number) >= 100 else _as_str(value)
        except (TypeError, ValueError):
            value_text = _as_str(value)
        if label:
            parts.append(f'{label}: {value_text}')
        elif value_text:
            parts.append(value_text)
    return _safe_paragraph('  ·  '.join(parts), style, rtl=rtl, max_width=max_width)


def _chart_card(
    chart: Dict[str, Any],
    width: float,
    height: float,
    rtl: bool,
    heading_style,
    caption_style,
    font_name: str,
):
    """Title + drawing + numbers as a finite-height nested table (never KeepTogether)."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    drawing = _chart_drawing(chart, width, height, rtl, font_name)
    if drawing is None:
        return None
    drawing.wrap(width, height)
    title = _safe_paragraph(
        chart.get('title') or '', heading_style, rtl=rtl, max_width=width,
    )
    legend = _chart_value_caption(chart, caption_style, rtl, width)
    card = Table([[title], [drawing], [legend]], colWidths=[width])
    card.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(PHINS_ICE)),
        ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#d7e2f5')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.8, colors.HexColor(PHINS_GOLD)),
    ]))
    return card


def _append_customer_charts(
    story: List[Any],
    summary: Dict[str, Any],
    heading_style,
    is_hebrew: bool,
    usable_width: float,
    font_name: str,
) -> None:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Spacer, Table, TableStyle

    charts = prepare_customer_download_charts(summary.get('chart_summaries') or [])
    if not charts:
        return
    heading = 'התרשימים מההערכה' if is_hebrew else 'Charts from your assessment'
    story.append(_safe_paragraph(heading, heading_style, rtl=is_hebrew, max_width=usable_width))
    story.append(Spacer(1, 4))
    caption_style = ParagraphStyle(
        'CustomerChartCaption',
        fontName=font_name,
        fontSize=8,
        leading=10,
        alignment=getattr(heading_style, 'alignment', 0),
        textColor=getattr(heading_style, 'textColor', None) or PHINS_INK,
    )
    cell_width = (usable_width - 10) / 2
    row: List[Any] = []
    for chart in charts[:6]:
        card = _chart_card(
            chart, cell_width, 188, is_hebrew, heading_style, caption_style, font_name,
        )
        if card is None:
            continue
        row.append(card)
        if len(row) == 2:
            table = Table([row], colWidths=[cell_width, cell_width])
            table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(table)
            story.append(Spacer(1, 8))
            row = []
    if row:
        if len(row) == 1:
            row.append('')
        table = Table([row], colWidths=[cell_width, cell_width])
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(table)
        story.append(Spacer(1, 8))


def _append_risk_covers(
    story: List[Any],
    summary: Dict[str, Any],
    heading_style,
    cell_style,
    is_hebrew: bool,
    usable_width: float,
) -> None:
    from reportlab.platypus import Spacer

    covers = summary.get('risk_covers') or []
    if not covers:
        return
    header_style = _navy_cell_style(cell_style)
    heading = 'הכיסויים והעלויות שלך' if is_hebrew else 'Your Covers & Costs'
    story.append(_safe_paragraph(heading, heading_style, rtl=is_hebrew, max_width=usable_width))
    note = (
        'כיסויים שהופיעו בקובץ שהועלה — סכום ועלויות כפי שנשמרו, בלי השלמה.'
        if is_hebrew else
        'Covers that were on the uploaded file — amounts and costs as stored, nothing added.'
    )
    story.append(_safe_paragraph(note, cell_style, rtl=is_hebrew, max_width=usable_width))
    story.append(Spacer(1, 4))
    headers = [
        'סוג כיסוי' if is_hebrew else 'Cover',
        'סכום' if is_hebrew else 'Amount',
        'עלות' if is_hebrew else 'Cost',
        'פוליסה' if is_hebrew else 'Policy',
        'יצרן' if is_hebrew else 'Provider',
    ]
    rows: List[List[str]] = []
    total_amount = 0.0
    total_cost = 0.0
    for cover in covers[:40]:
        amount = _as_cover_number(cover.get('amount'))
        cost = _as_cover_number(cover.get('cost'))
        total_amount += amount
        total_cost += cost
        title = cover.get('title_he') if is_hebrew else cover.get('title_en')
        rows.append([
            _as_str(title or cover.get('title_he') or cover.get('title_en')),
            _as_money(amount) if amount else '—',
            _as_money(cost) if cost else '—',
            _as_str(cover.get('policy_number')),
            _as_str(cover.get('provider')),
        ])
    if len(covers) > 1:
        rows.append([
            'סה״כ' if is_hebrew else 'Total',
            _as_money(total_amount) if total_amount else '—',
            _as_money(total_cost) if total_cost else '—',
            '',
            '',
        ])
    story.append(_build_text_table(
        headers, rows,
        cell_style=cell_style, header_style=header_style,
        rtl=is_hebrew, usable_width=usable_width,
        font=getattr(cell_style, 'fontName', 'Helvetica'),
    ))
    story.append(Spacer(1, 10))


def _append_agent_recommendation_space(
    story: List[Any],
    summary: Dict[str, Any],
    heading_style,
    body_style,
    is_hebrew: bool,
    usable_width: float,
) -> None:
    from reportlab.lib import colors
    from reportlab.platypus import Spacer, Table, TableStyle

    heading = 'המלצות היועץ' if is_hebrew else 'Agent recommendations'
    story.append(_safe_paragraph(heading, heading_style, rtl=is_hebrew, max_width=usable_width))
    recs = prepare_customer_download_recommendations(summary.get('recommendations') or [])
    if recs:
        for rec in recs[:12]:
            rec_title = _as_str(rec.get('title', ''))
            rec_desc = strip_completeness_copy(_as_str(rec.get('description', '')))
            if rec_title:
                story.append(_safe_paragraph(rec_title, body_style, rtl=is_hebrew, max_width=usable_width))
            if rec_desc:
                story.append(_safe_paragraph(rec_desc, body_style, rtl=is_hebrew, max_width=usable_width))
            story.append(Spacer(1, 4))
    prompt = (
        'מקום פתוח להמלצות היועץ — ניתן להשלים בכתב או בעריכת הקובץ.'
        if is_hebrew else
        'Open space for the advisor — fill in by hand or when editing the file.'
    )
    lines = [prompt] + [''] * 5
    box = Table(
        [[_safe_paragraph('\n'.join(lines), body_style, rtl=is_hebrew, max_width=usable_width - 16)]],
        colWidths=[usable_width],
        rowHeights=[92],
    )
    box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(PHINS_ICE)),
        ('BOX', (0, 0), (-1, -1), 1.1, colors.HexColor(PHINS_GOLD)),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(box)
    story.append(Spacer(1, 12))


def _append_signature_block(
    story: List[Any],
    summary: Dict[str, Any],
    heading_style,
    body_style,
    cell_style,
    is_hebrew: bool,
    usable_width: float,
) -> None:
    from reportlab.lib import colors
    from reportlab.platypus import Spacer, Table, TableStyle

    heading = 'חתימות' if is_hebrew else 'Signatures'
    story.append(_safe_paragraph(heading, heading_style, rtl=is_hebrew, max_width=usable_width))
    name, ident = customer_signature_identity(summary)
    customer_title = 'הלקוח' if is_hebrew else 'Customer'
    advisor_title = 'היועץ / הסוכן' if is_hebrew else 'Advisor / agent'
    name_label = 'שם' if is_hebrew else 'Name'
    id_label = 'תעודת זהות' if is_hebrew else 'National ID'
    sign_label = 'חתימה' if is_hebrew else 'Signature'
    date_label = 'תאריך' if is_hebrew else 'Date'
    license_label = 'מספר רישיון' if is_hebrew else 'License no.'
    customer_name = name or ('—' if is_hebrew else '—')
    customer_id = ident or ('—' if is_hebrew else '—')
    half = (usable_width - 10) / 2

    def _party_card(title: str, identity_lines: List[str]) -> Any:
        body = [title] + identity_lines
        para = _safe_paragraph('\n'.join(body), body_style, rtl=is_hebrew, max_width=half - 16)
        card = Table([[para]], colWidths=[half])
        card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(PHINS_ICE)),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor(PHINS_NAVY)),
            ('LINEBEFORE', (0, 0), (0, 0), 3, colors.HexColor(PHINS_GOLD)),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        return card

    customer_lines = [
        f'{name_label}: {customer_name}',
        f'{id_label}: {customer_id}',
        f'{sign_label}: ________________________',
        f'{date_label}: ______________',
    ]
    advisor_lines = [
        f'{name_label}: ________________________',
        f'{license_label}: ______________',
        f'{sign_label}: ________________________',
        f'{date_label}: ______________',
    ]
    customer_card = _party_card(customer_title, customer_lines)
    advisor_card = _party_card(advisor_title, advisor_lines)
    pair = [advisor_card, customer_card] if is_hebrew else [customer_card, advisor_card]
    table = Table([pair], colWidths=[half, half])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))


def _style_kv_table(table, rtl: bool = False):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    label_col = 1 if rtl else 0
    table.hAlign = 'RIGHT' if rtl else 'LEFT'
    table.setStyle(TableStyle([
        ('BACKGROUND', (label_col, 0), (label_col, -1), colors.HexColor(PHINS_NAVY)),
        ('TEXTCOLOR', (label_col, 0), (label_col, -1), colors.HexColor(PHINS_GOLD_STRONG)),
        ('BACKGROUND', (1 - label_col, 0), (1 - label_col, -1), colors.HexColor(PHINS_ICE)),
        ('TEXTCOLOR', (1 - label_col, 0), (1 - label_col, -1), colors.HexColor(PHINS_INK)),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#d7e2f5')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT' if rtl else 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    return table


def _build_mislaka_assessment_pdf(summary: Dict[str, Any]) -> bytes:
    """Render the Mislaka assessment (identity + accounts + totals) as PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

    base_font, bold_font = _register_fonts()
    is_hebrew = is_rtl_language(summary.get('language'))
    align = TA_RIGHT if is_hebrew else TA_LEFT
    assessment = summary.get('pension_assessment') or {}
    client = assessment.get('client') or {}
    totals = assessment.get('totals') or {}
    accounts = assessment.get('accounts') or []
    sci = summary.get('savings_cover_id_summary') or {}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=26 * mm, bottomMargin=18 * mm,
    )
    usable_width = A4[0] - 32 * mm
    styles = getSampleStyleSheet()
    from reportlab.lib import colors as rl_colors
    title_style = ParagraphStyle(
        'MislakaPdfTitle', parent=styles['Title'],
        fontName=bold_font, fontSize=16, leading=20,
        alignment=align, textColor=rl_colors.HexColor(PHINS_NAVY),
    )
    heading_style = ParagraphStyle(
        'MislakaPdfHeading', parent=styles['Heading2'],
        fontName=bold_font, fontSize=12, leading=15,
        alignment=align, spaceBefore=8, spaceAfter=4,
        textColor=rl_colors.HexColor(PHINS_NAVY),
    )
    body_style = ParagraphStyle(
        'MislakaPdfBody', parent=styles['BodyText'],
        fontName=base_font, fontSize=9, leading=13,
        alignment=align, textColor=rl_colors.HexColor(PHINS_INK),
    )
    cell_style = ParagraphStyle(
        'MislakaPdfCell', parent=styles['BodyText'],
        fontName=base_font, fontSize=8, leading=10,
        alignment=align, textColor=rl_colors.HexColor(PHINS_INK),
    )
    navy_cell_style = _navy_cell_style(cell_style)

    story: List[Any] = []
    title = customer_report_title(summary)
    story.append(_safe_paragraph(title, title_style, rtl=is_hebrew, max_width=usable_width))
    story.append(Spacer(1, 6))
    story.append(_consultant_intro_box(is_hebrew, body_style, usable_width))
    story.append(Spacer(1, 10))

    customer_id = client.get('id_number') or sci.get('customer_id') or ''
    customer_name = client.get('full_name') or client.get('client_name') or ''
    birth_date = client.get('birth_date') or sci.get('birth_date') or ''

    identity_heading = 'הפרטים שלך' if is_hebrew else 'Your Details'
    story.append(_safe_paragraph(identity_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
    identity_pairs = [
        ['תעודת זהות' if is_hebrew else 'National ID', _as_str(customer_id)],
        ['שם מלא' if is_hebrew else 'Full Name', _as_str(customer_name)],
        ['תאריך לידה' if is_hebrew else 'Birth Date', _as_str(birth_date)],
        ['נוצר' if is_hebrew else 'Prepared On', _as_when(summary.get('generated_at'))],
    ]
    identity_pairs = [pair for pair in identity_pairs if _uploaded(pair[1])]
    identity_table = _build_kv_table(
        identity_pairs,
        cell_style, navy_cell_style,
        rtl=is_hebrew, usable_width=usable_width,
        font=getattr(cell_style, 'fontName', 'Helvetica'),
    )
    story.append(identity_table)
    story.append(Spacer(1, 10))

    totals_heading = 'החיסכון והפיצויים שלך' if is_hebrew else 'Your Savings & Severance'
    story.append(_safe_paragraph(totals_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
    # Copy totals from the assessment — do not re-sum accounts here.
    display_totals = dict(totals)
    if not display_totals.get('total_balance'):
        display_totals['total_balance'] = sci.get('total_savings', 0)
    if not display_totals.get('total_severance'):
        display_totals['total_severance'] = sci.get('total_severance', 0)
    if not display_totals.get('account_count'):
        display_totals['account_count'] = len(accounts)
    totals_table = _build_kv_table(
        _accumulation_total_pairs(display_totals, is_hebrew),
        cell_style, navy_cell_style,
        rtl=is_hebrew, usable_width=usable_width,
        font=getattr(cell_style, 'fontName', 'Helvetica'),
    )
    story.append(totals_table)
    by_provider = display_totals.get('by_provider') or {}
    if isinstance(by_provider, dict) and any(_uploaded(amount) for amount in by_provider.values()):
        provider_heading = 'צבירות לפי יצרן' if is_hebrew else 'Accumulation by Provider'
        story.append(Spacer(1, 8))
        story.append(_safe_paragraph(provider_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
        provider_headers = ['יצרן' if is_hebrew else 'Provider', 'סה״כ חיסכון' if is_hebrew else 'Accumulation']
        provider_rows = [
            [_as_str(name), _as_money(amount)]
            for name, amount in by_provider.items()
            if _uploaded(amount)
        ]
        story.append(_build_text_table(
            provider_headers, provider_rows,
            cell_style=cell_style, header_style=navy_cell_style,
            rtl=is_hebrew, usable_width=usable_width,
            font=getattr(cell_style, 'fontName', 'Helvetica'),
        ))
    story.append(Spacer(1, 10))
    _append_customer_charts(story, summary, heading_style, is_hebrew, usable_width, base_font)

    if accounts:
        shown = accounts[:80]
        money_headers, money_rows = _active_holdings_table(_holdings_money_specs(is_hebrew), shown)
        if money_headers:
            accounts_heading = 'החשבונות והפוליסות שלך' if is_hebrew else 'Your Accounts & Policies'
            story.append(_safe_paragraph(accounts_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
            story.append(_build_text_table(
                money_headers, money_rows,
                cell_style=cell_style, header_style=navy_cell_style,
                rtl=is_hebrew, usable_width=usable_width,
                font=getattr(cell_style, 'fontName', 'Helvetica'),
            ))
            story.append(Spacer(1, 8))
        detail_groups = _holdings_detail_specs(is_hebrew)
        detail_titles = (
            ['הפוליסה והמסלול' if is_hebrew else 'Policy and Track',
             'הפקדות ודמי ניהול' if is_hebrew else 'Deposits and Fees']
        )
        for detail_heading, detail_specs in zip(detail_titles, detail_groups):
            detail_headers, detail_rows = _active_holdings_table(detail_specs, shown)
            detail_has_value = any(any(cell for cell in row[1:]) for row in detail_rows)
            if not detail_headers or not detail_has_value:
                continue
            story.append(_safe_paragraph(detail_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
            story.append(_build_text_table(
                detail_headers, detail_rows,
                cell_style=cell_style, header_style=navy_cell_style,
                rtl=is_hebrew, usable_width=usable_width,
                font=getattr(cell_style, 'fontName', 'Helvetica'),
            ))
            story.append(Spacer(1, 8))

    _append_risk_covers(story, summary, heading_style, cell_style, is_hebrew, usable_width)
    _append_assessment_sections(story, summary, heading_style, body_style, cell_style, is_hebrew, usable_width)
    _append_agent_recommendation_space(story, summary, heading_style, body_style, is_hebrew, usable_width)
    _append_signature_block(story, summary, heading_style, body_style, cell_style, is_hebrew, usable_width)

    on_first, on_later = _page_callbacks(is_hebrew, title, base_font, bold_font)
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return buffer.getvalue()


def _append_assessment_sections(
    story: List[Any],
    summary: Dict[str, Any],
    heading_style,
    body_style,
    cell_style,
    is_hebrew: bool,
    usable_width: float,
) -> None:
    from reportlab.platypus import Spacer

    header_style = _navy_cell_style(cell_style)
    for section in prepare_customer_download_sections(summary.get('assessment_sections') or []):
        title_text = section.get('title') or ''
        content = (section.get('content') or '').strip()
        rows = section.get('rows') or []
        if not content and not rows:
            continue
        story.append(_safe_paragraph(title_text, heading_style, rtl=is_hebrew, max_width=usable_width))
        if content:
            clipped = content if len(content) <= 4000 else content[:4000] + '\n…'
            story.append(_safe_paragraph(clipped, body_style, rtl=is_hebrew, max_width=usable_width))
            story.append(Spacer(1, 4))
        columns = list(section.get('columns') or [])
        if rows and columns:
            table_rows = [
                [
                    _as_str(row.get(col, '') if isinstance(row, dict) else row)
                    for col in columns
                ]
                for row in rows[:60]
            ]
            story.append(_build_text_table(
                [_as_str(col) for col in columns],
                table_rows,
                cell_style=cell_style, header_style=header_style,
                rtl=is_hebrew, usable_width=usable_width,
                font=getattr(cell_style, 'fontName', 'Helvetica'),
            ))
            story.append(Spacer(1, 8))


def _build_generic_summary_pdf(summary: Dict[str, Any]) -> bytes:
    """Customer-facing assessment PDF for non-Mislaka reports."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

    base_font, bold_font = _register_fonts()
    is_hebrew = is_rtl_language(summary.get('language')) or has_hebrew(str(summary.get('title') or ''))
    align = TA_RIGHT if is_hebrew else TA_LEFT
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=26 * mm, bottomMargin=18 * mm,
    )
    usable_width = A4[0] - 32 * mm
    styles = getSampleStyleSheet()
    from reportlab.lib import colors as rl_colors
    title_style = ParagraphStyle(
        'CustomerPdfTitle', parent=styles['Title'],
        fontName=bold_font, fontSize=16, leading=20, alignment=align,
        textColor=rl_colors.HexColor(PHINS_NAVY),
    )
    heading_style = ParagraphStyle(
        'CustomerPdfHeading', parent=styles['Heading2'],
        fontName=bold_font, fontSize=12, leading=15,
        alignment=align, spaceBefore=8, spaceAfter=4,
        textColor=rl_colors.HexColor(PHINS_NAVY),
    )
    body_style = ParagraphStyle(
        'CustomerPdfBody', parent=styles['BodyText'],
        fontName=base_font, fontSize=9, leading=13, alignment=align,
        textColor=rl_colors.HexColor(PHINS_INK),
    )
    cell_style = ParagraphStyle(
        'CustomerPdfCell', parent=styles['BodyText'],
        fontName=base_font, fontSize=8, leading=10, alignment=align,
        textColor=rl_colors.HexColor(PHINS_INK),
    )
    navy_cell_style = _navy_cell_style(cell_style)

    story: List[Any] = []
    title = customer_report_title(summary)
    story.append(_safe_paragraph(title, title_style, rtl=is_hebrew, max_width=usable_width))
    story.append(Spacer(1, 6))
    story.append(_consultant_intro_box(is_hebrew, body_style, usable_width))
    story.append(Spacer(1, 10))

    sci = summary.get('savings_cover_id_summary', {}) or {}
    has_customer_totals = any(
        sci.get(key) not in (None, '', 0, 0.0)
        for key in ('customer_id', 'birth_date', 'total_savings', 'total_severance', 'total_cover')
    )
    if has_customer_totals:
        overview_heading = 'הסיכום שלך' if is_hebrew else 'Your Summary'
        story.append(_safe_paragraph(overview_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
        overview_table = _build_kv_table(
            [
                ['תעודת זהות' if is_hebrew else 'National ID', _as_str(sci.get('customer_id', ''))],
                ['תאריך לידה' if is_hebrew else 'Birth Date', _as_str(sci.get('birth_date', ''))],
                ['סה״כ חיסכון' if is_hebrew else 'Total Savings', _as_money(sci.get('total_savings', 0))],
                ['סה״כ פיצויים' if is_hebrew else 'Total Severance', _as_money(sci.get('total_severance', 0))],
                ['סה״כ כיסוי' if is_hebrew else 'Total Cover', _as_money(sci.get('total_cover', 0))],
                ['נוצר' if is_hebrew else 'Prepared On', _as_when(summary.get('generated_at'))],
            ],
            cell_style, navy_cell_style,
            rtl=is_hebrew, usable_width=usable_width,
            font=getattr(cell_style, 'fontName', 'Helvetica'),
        )
        story.append(overview_table)
        story.append(Spacer(1, 12))

    _append_customer_charts(story, summary, heading_style, is_hebrew, usable_width, base_font)
    _append_risk_covers(story, summary, heading_style, cell_style, is_hebrew, usable_width)
    _append_assessment_sections(story, summary, heading_style, body_style, cell_style, is_hebrew, usable_width)
    _append_agent_recommendation_space(story, summary, heading_style, body_style, is_hebrew, usable_width)
    _append_signature_block(story, summary, heading_style, body_style, cell_style, is_hebrew, usable_width)

    on_first, on_later = _page_callbacks(is_hebrew, title, base_font, bold_font)
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return buffer.getvalue()


def _write_cover_csv_rows(writer, summary: Dict[str, Any], is_hebrew: bool) -> None:
    covers = summary.get('risk_covers') or []
    if not covers:
        return
    writer.writerow(['הכיסויים והעלויות שלך' if is_hebrew else 'Your Covers & Costs'])
    writer.writerow(
        ['סוג כיסוי', 'סכום', 'עלות', 'פוליסה', 'יצרן']
        if is_hebrew else
        ['Cover', 'Amount', 'Cost', 'Policy', 'Provider']
    )
    for cover in covers[:40]:
        title = cover.get('title_he') if is_hebrew else cover.get('title_en')
        writer.writerow([
            title or cover.get('title_he') or cover.get('title_en') or '',
            cover.get('amount', ''),
            cover.get('cost', ''),
            cover.get('policy_number', ''),
            cover.get('provider', ''),
        ])
    writer.writerow([])


def _write_chart_csv_rows(writer, summary: Dict[str, Any], is_hebrew: bool) -> None:
    charts = prepare_customer_download_charts(summary.get('chart_summaries') or [])
    if not charts:
        return
    writer.writerow(['התרשימים מההערכה' if is_hebrew else 'Charts from your assessment'])
    writer.writerow(
        ['תרשים', 'פריט', 'ערך'] if is_hebrew else ['Chart', 'Item', 'Value']
    )
    for chart in charts[:6]:
        for point in chart.get('series') or []:
            writer.writerow([
                chart.get('title', ''),
                point.get('label', ''),
                point.get('value', ''),
            ])
    writer.writerow([])


def build_report_csv_bytes(summary: Dict[str, Any]) -> bytes:
    """Build CSV bytes for the customer-facing downloadable assessment."""
    import csv
    from datetime import datetime

    out = io.StringIO()
    writer = csv.writer(out)
    is_hebrew = is_rtl_language(summary.get('language'))
    title = customer_report_title(summary)

    writer.writerow([title])
    writer.writerow([
        'נוצר' if is_hebrew else 'Prepared On',
        summary.get('generated_at') or datetime.now().isoformat(),
    ])
    writer.writerow([])

    pension = summary.get('pension_assessment') or {}
    if summary.get('is_pension_data') or pension:
        client = pension.get('client') or {}
        totals = pension.get('totals') or {}
        writer.writerow(['הפרטים שלך' if is_hebrew else 'Your Details'])
        writer.writerow(['תעודת זהות' if is_hebrew else 'National ID', client.get('id_number', '')])
        writer.writerow(['שם מלא' if is_hebrew else 'Full Name', client.get('full_name', client.get('client_name', ''))])
        writer.writerow(['תאריך לידה' if is_hebrew else 'Birth Date', client.get('birth_date', '')])
        for label, value in _accumulation_total_pairs(totals, is_hebrew):
            writer.writerow([label, value])
        by_provider = totals.get('by_provider') or {}
        if isinstance(by_provider, dict) and any(_uploaded(amount) for amount in by_provider.values()):
            writer.writerow([])
            writer.writerow(['צבירות לפי יצרן' if is_hebrew else 'Accumulation by Provider'])
            writer.writerow(['יצרן' if is_hebrew else 'Provider', 'סה״כ חיסכון' if is_hebrew else 'Accumulation'])
            for name, amount in by_provider.items():
                if _uploaded(amount):
                    writer.writerow([name, amount])
        writer.writerow([])
        accounts = pension.get('accounts') or []
        if accounts:
            shown = accounts[:80]
            money_headers, money_rows = _active_holdings_table(_holdings_money_specs(is_hebrew), shown)
            if money_headers:
                writer.writerow(['החשבונות והפוליסות שלך' if is_hebrew else 'Your Accounts & Policies'])
                writer.writerow(money_headers)
                for row in money_rows:
                    writer.writerow(row)
                writer.writerow([])
            for detail_heading, detail_specs in zip(
                ['הפוליסה והמסלול' if is_hebrew else 'Policy and Track',
                 'הפקדות ודמי ניהול' if is_hebrew else 'Deposits and Fees'],
                _holdings_detail_specs(is_hebrew),
            ):
                detail_headers, detail_rows = _active_holdings_table(detail_specs, shown)
                if detail_headers and any(any(cell for cell in row[1:]) for row in detail_rows):
                    writer.writerow([detail_heading])
                    writer.writerow(detail_headers)
                    for row in detail_rows:
                        writer.writerow(row)
                    writer.writerow([])
        for section in prepare_customer_download_sections(summary.get('assessment_sections') or []):
            writer.writerow([section.get('title', '')])
            content = strip_completeness_copy(section.get('content') or '')
            if content:
                writer.writerow([content])
            columns = section.get('columns', []) or []
            rows = section.get('rows', []) or []
            if columns:
                writer.writerow(columns)
            for row in rows[:120]:
                writer.writerow([row.get(col, '') for col in columns] if isinstance(row, dict) else [row])
            writer.writerow([])
        _write_cover_csv_rows(writer, summary, is_hebrew)
        _write_chart_csv_rows(writer, summary, is_hebrew)
        recs = prepare_customer_download_recommendations(summary.get('recommendations') or [])
        if recs:
            writer.writerow(['המלצות היועץ' if is_hebrew else 'Agent recommendations'])
            for rec in recs[:12]:
                writer.writerow([
                    rec.get('title', ''),
                    strip_completeness_copy(rec.get('description', '')),
                ])
        return out.getvalue().encode('utf-8')

    sci = summary.get('savings_cover_id_summary', {}) or {}
    writer.writerow(['הסיכום שלך' if is_hebrew else 'Your Summary'])
    writer.writerow(['תעודת זהות' if is_hebrew else 'National ID', sci.get('customer_id', '')])
    writer.writerow(['תאריך לידה' if is_hebrew else 'Birth Date', sci.get('birth_date', '')])
    writer.writerow(['סה״כ חיסכון' if is_hebrew else 'Total Savings', sci.get('total_savings', 0)])
    writer.writerow(['סה״כ פיצויים' if is_hebrew else 'Total Severance', sci.get('total_severance', 0)])
    writer.writerow(['סה״כ כיסוי' if is_hebrew else 'Total Cover', sci.get('total_cover', 0)])
    writer.writerow([])

    for section in prepare_customer_download_sections(summary.get('assessment_sections') or []):
        writer.writerow([section.get('title', '')])
        content = strip_completeness_copy(section.get('content') or '')
        if content:
            writer.writerow([content])
        columns = section.get('columns', []) or []
        rows = section.get('rows', []) or []
        if columns:
            writer.writerow(columns)
        for row in rows[:120]:
            writer.writerow([row.get(col, '') for col in columns] if isinstance(row, dict) else [row])
        writer.writerow([])

    _write_cover_csv_rows(writer, summary, is_hebrew)
    _write_chart_csv_rows(writer, summary, is_hebrew)

    recs = prepare_customer_download_recommendations(summary.get('recommendations', []) or [])
    if recs:
        writer.writerow(['המלצות היועץ' if is_hebrew else 'Agent recommendations'])
        writer.writerow(
            ['עדיפות', 'כותרת', 'פירוט'] if is_hebrew else ['Priority', 'Title', 'Description']
        )
        for rec in recs[:40]:
            writer.writerow([
                rec.get('priority', ''),
                rec.get('title', ''),
                strip_completeness_copy(rec.get('description', '')),
            ])

    return out.getvalue().encode('utf-8')


def build_report_pdf_bytes(summary: Dict[str, Any]) -> bytes:
    """Build PDF bytes for a downloadable report summary.

    Downloads use the customer assessment renderer so the file matches
    the post-Analyse result — not the statistical Data Analysis trailer
    or the completeness block.
    """
    try:
        if summary.get('is_pension_data') or summary.get('pension_assessment'):
            return _build_mislaka_assessment_pdf(summary)
        return _build_generic_summary_pdf(summary)
    except Exception:
        fallback_text = json.dumps(summary, ensure_ascii=False, indent=2)
        return fallback_text.encode('utf-8')
