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


def _as_money(val: Any) -> str:
    if val is None or val == '':
        return '₪0.00'
    try:
        number = float(val)
    except (TypeError, ValueError):
        return str(val)
    return f"₪{number:,.2f}"


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


def _style_table(table, header_color: str = PHINS_NAVY, rtl: bool = False):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    align = 'RIGHT' if rtl else 'LEFT'
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(header_color)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(PHINS_GOLD_STRONG)),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor(PHINS_ICE)),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(PHINS_INK)),
        ('LINEBELOW', (0, 0), (-1, 0), 1.2, colors.HexColor(PHINS_GOLD)),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#d7e2f5')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), align),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
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
    try:
        canvas.linearGradient(
            0, height - band, width, height,
            [colors.HexColor(PHINS_NAVY_DEEP), colors.HexColor(PHINS_NAVY_MID)],
            extend=False,
        )
        canvas.rect(0, height - band, width, band, fill=1, stroke=0)
    except Exception:
        canvas.setFillColor(colors.HexColor(PHINS_NAVY))
        canvas.rect(0, height - band, width, band, fill=1, stroke=0)
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
        canvas.setFont(font, 6.6)
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
        canvas.setFont(font, 6.6)
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


def _chart_drawing(chart: Dict[str, Any], width: float, height: float, rtl: bool, font_name: str):
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors

    series = chart.get('series') or []
    labels = [bidi_text(_as_str(point.get('label')), rtl)[:22] for point in series]
    values: List[float] = []
    for point in series:
        try:
            values.append(float(point.get('value') or 0))
        except (TypeError, ValueError):
            values.append(0.0)
    if not values:
        return None
    drawing = Drawing(width, height)
    chart_type = str(chart.get('type') or 'bar').lower()
    palette = [colors.HexColor(code) for code in _BRAND_CHART_COLORS]
    if chart_type in {'pie', 'doughnut'}:
        pie = Pie()
        pie.x = width * 0.08
        pie.y = 10
        size = min(width, height) * 0.62
        pie.width = size
        pie.height = size
        pie.data = values
        pie.labels = labels
        pie.simpleLabels = 0
        pie.slices.strokeWidth = 0.6
        pie.slices.strokeColor = colors.white
        pie.slices.fontName = font_name
        pie.slices.fontSize = 7
        if chart_type == 'doughnut':
            pie.innerRadiusFraction = 0.48
        for index, _value in enumerate(values):
            pie.slices[index].fillColor = palette[index % len(palette)]
        drawing.add(pie)
        return drawing

    bar = VerticalBarChart()
    bar.x = 36
    bar.y = 18
    bar.height = height - 28
    bar.width = width - 48
    bar.data = [values]
    bar.categoryAxis.categoryNames = labels
    bar.categoryAxis.labels.fontName = font_name
    bar.categoryAxis.labels.fontSize = 7
    bar.categoryAxis.labels.angle = 20
    bar.categoryAxis.labels.boxAnchor = 'ne'
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
            chart, cell_width, 150, is_hebrew, heading_style, caption_style, font_name,
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


def _style_kv_table(table, rtl: bool = False):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    label_col = 1 if rtl else 0
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
    identity_rows = _kv_rows([
        ['תעודת זהות' if is_hebrew else 'National ID', _as_str(customer_id)],
        ['שם מלא' if is_hebrew else 'Full Name', _as_str(customer_name)],
        ['תאריך לידה' if is_hebrew else 'Birth Date', _as_str(birth_date)],
        ['נוצר' if is_hebrew else 'Prepared On', _as_str(summary.get('generated_at'))],
    ], is_hebrew)
    identity_display = [
        [_safe_paragraph(cell, cell_style, rtl=is_hebrew, max_width=160) for cell in row]
        for row in identity_rows
    ]
    identity_table = Table(identity_display, colWidths=[150, 340] if not is_hebrew else [340, 150])
    _style_kv_table(identity_table, rtl=is_hebrew)
    story.append(identity_table)
    story.append(Spacer(1, 10))

    totals_heading = 'החיסכון והפיצויים שלך' if is_hebrew else 'Your Savings & Severance'
    story.append(_safe_paragraph(totals_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
    # Copy totals from the assessment — do not re-sum accounts here.
    total_balance = totals.get('total_balance', sci.get('total_savings', 0))
    total_savings = totals.get('total_savings', totals.get('total_savings_balance', 0))
    total_severance = totals.get('total_severance', totals.get('total_severance_balance', sci.get('total_severance', 0)))
    account_count = totals.get('account_count', len(accounts))
    totals_rows = _kv_rows([
        ['סה״כ צבירה' if is_hebrew else 'Total Accumulation', _as_money(total_balance)],
        ['סה״כ חסכונות' if is_hebrew else 'Total Savings', _as_money(total_savings)],
        ['סה״כ פיצויים' if is_hebrew else 'Total Severance', _as_money(total_severance)],
        ['מספר פוליסות' if is_hebrew else 'Number of Policies', _as_str(account_count)],
    ], is_hebrew)
    totals_display = [
        [_safe_paragraph(cell, cell_style, rtl=is_hebrew, max_width=160) for cell in row]
        for row in totals_rows
    ]
    totals_table = Table(totals_display, colWidths=[150, 340] if not is_hebrew else [340, 150])
    _style_kv_table(totals_table, rtl=is_hebrew)
    story.append(totals_table)
    story.append(Spacer(1, 10))
    _append_customer_charts(story, summary, heading_style, is_hebrew, usable_width, base_font)

    if accounts:
        accounts_heading = 'החשבונות והפוליסות שלך' if is_hebrew else 'Your Accounts & Policies'
        story.append(_safe_paragraph(accounts_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
        header = [
            'פוליסה' if is_hebrew else 'Policy',
            'יצרן' if is_hebrew else 'Provider',
            'מוצר' if is_hebrew else 'Product',
            'צבירה' if is_hebrew else 'Balance',
            'פיצויים' if is_hebrew else 'Severance',
        ]
        col_widths = [90, 110, 110, 90, 90]
        if is_hebrew:
            header = list(reversed(header))
            col_widths = list(reversed(col_widths))
        table_data: List[List[Any]] = [[
            _safe_paragraph(h, cell_style, rtl=is_hebrew, max_width=w)
            for h, w in zip(header, col_widths)
        ]]
        for acct in accounts[:80]:
            row = [
                _as_str(acct.get('policy_number')),
                _as_str(acct.get('provider')),
                _as_str(acct.get('product_type_name') or acct.get('product_type')),
                _as_money(acct.get('total_balance', acct.get('savings_balance', 0))),
                _as_money(acct.get('severance_balance', 0)),
            ]
            if is_hebrew:
                row = list(reversed(row))
            table_data.append([
                _safe_paragraph(cell, cell_style, rtl=is_hebrew, max_width=w)
                for cell, w in zip(row, col_widths)
            ])
        accounts_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        _style_table(accounts_table, rtl=is_hebrew)
        story.append(accounts_table)
        story.append(Spacer(1, 10))

    _append_assessment_sections(story, summary, heading_style, body_style, cell_style, is_hebrew, usable_width)

    recs = summary.get('recommendations') or []
    if recs:
        rec_heading = 'נקודות לשיחה עם היועץ' if is_hebrew else 'Talking points for your advisor'
        story.append(_safe_paragraph(rec_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
        for rec in recs[:12]:
            rec_title = _as_str(rec.get('title', ''))
            rec_desc = strip_completeness_copy(_as_str(rec.get('description', '')))
            if rec_title:
                story.append(_safe_paragraph(rec_title, body_style, rtl=is_hebrew, max_width=usable_width))
            if rec_desc:
                story.append(_safe_paragraph(rec_desc, body_style, rtl=is_hebrew, max_width=usable_width))
            story.append(Spacer(1, 6))

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
    from reportlab.platypus import Spacer, Table

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
            display_columns = list(reversed(columns)) if is_hebrew else columns
            width = usable_width / max(len(display_columns), 1)
            header_cells = [
                _safe_paragraph(_as_str(col), cell_style, rtl=is_hebrew, max_width=width)
                for col in display_columns
            ]
            table_rows: List[List[Any]] = [header_cells]
            for row in rows[:60]:
                values = [
                    _as_str(row.get(col, '') if isinstance(row, dict) else row)
                    for col in columns
                ]
                if is_hebrew:
                    values = list(reversed(values))
                table_rows.append([
                    _safe_paragraph(val, cell_style, rtl=is_hebrew, max_width=width)
                    for val in values
                ])
            data_table = Table(table_rows, colWidths=[width] * len(display_columns), repeatRows=1)
            _style_table(data_table, PHINS_NAVY, rtl=is_hebrew)
            story.append(data_table)
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
        overview_rows = _kv_rows([
            ['תעודת זהות' if is_hebrew else 'National ID', _as_str(sci.get('customer_id', ''))],
            ['תאריך לידה' if is_hebrew else 'Birth Date', _as_str(sci.get('birth_date', ''))],
            ['סה״כ חיסכון' if is_hebrew else 'Total Savings', _as_money(sci.get('total_savings', 0))],
            ['סה״כ פיצויים' if is_hebrew else 'Total Severance', _as_money(sci.get('total_severance', 0))],
            ['סה״כ כיסוי' if is_hebrew else 'Total Cover', _as_money(sci.get('total_cover', 0))],
            ['נוצר' if is_hebrew else 'Prepared On', _as_str(summary.get('generated_at'))],
        ], is_hebrew)
        overview_display = [
            [_safe_paragraph(cell, cell_style, rtl=is_hebrew, max_width=160) for cell in row]
            for row in overview_rows
        ]
        overview_table = Table(overview_display, colWidths=[150, 340] if not is_hebrew else [340, 150])
        _style_kv_table(overview_table, rtl=is_hebrew)
        story.append(overview_table)
        story.append(Spacer(1, 12))

    _append_customer_charts(story, summary, heading_style, is_hebrew, usable_width, base_font)
    _append_assessment_sections(story, summary, heading_style, body_style, cell_style, is_hebrew, usable_width)

    recs = summary.get('recommendations', []) or []
    if recs:
        rec_heading = 'נקודות לשיחה עם היועץ' if is_hebrew else 'Talking points for your advisor'
        story.append(_safe_paragraph(rec_heading, heading_style, rtl=is_hebrew, max_width=usable_width))
        for rec in recs[:12]:
            rec_title = _as_str(rec.get('title', ''))
            rec_desc = strip_completeness_copy(_as_str(rec.get('description', '')))
            if rec_title:
                story.append(_safe_paragraph(rec_title, body_style, rtl=is_hebrew, max_width=usable_width))
            if rec_desc:
                story.append(_safe_paragraph(rec_desc, body_style, rtl=is_hebrew, max_width=usable_width))
            story.append(Spacer(1, 6))

    on_first, on_later = _page_callbacks(is_hebrew, title, base_font, bold_font)
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return buffer.getvalue()


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
        writer.writerow(['סה״כ צבירה' if is_hebrew else 'Total Accumulation', totals.get('total_balance', '')])
        writer.writerow(['סה״כ חסכונות' if is_hebrew else 'Total Savings', totals.get('total_savings', '')])
        writer.writerow(['סה״כ פיצויים' if is_hebrew else 'Total Severance', totals.get('total_severance', '')])
        writer.writerow(['מספר פוליסות' if is_hebrew else 'Number of Policies', totals.get('account_count', '')])
        writer.writerow([])
        accounts = pension.get('accounts') or []
        if accounts:
            writer.writerow(['החשבונות והפוליסות שלך' if is_hebrew else 'Your Accounts & Policies'])
            writer.writerow(
                ['פוליסה', 'יצרן', 'מוצר', 'צבירה', 'פיצויים']
                if is_hebrew else
                ['Policy', 'Provider', 'Product', 'Balance', 'Severance']
            )
            for acct in accounts[:80]:
                writer.writerow([
                    acct.get('policy_number', ''),
                    acct.get('provider', ''),
                    acct.get('product_type_name', acct.get('product_type', '')),
                    acct.get('total_balance', ''),
                    acct.get('severance_balance', ''),
                ])
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
        _write_chart_csv_rows(writer, summary, is_hebrew)
        recs = summary.get('recommendations') or []
        if recs:
            writer.writerow(['נקודות לשיחה עם היועץ' if is_hebrew else 'Talking points for your advisor'])
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

    _write_chart_csv_rows(writer, summary, is_hebrew)

    recs = summary.get('recommendations', []) or []
    if recs:
        writer.writerow(['נקודות לשיחה עם היועץ' if is_hebrew else 'Talking points for your advisor'])
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
