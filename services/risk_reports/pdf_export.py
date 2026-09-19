"""Downloadable Risk Reports PDF (B9).

Mislaka / pension assessments export the extracted identity, accounts,
accumulation and severance — not statistical filler (Data Profile,
correlations, patterns, generic key-metrics). Numbers are copied from the
already-built assessment payload; this module never re-aggregates.
"""

from __future__ import annotations

import html
import io
import json
import os
from typing import Any, Dict, List, Tuple

# Titles that describe analysis-of-the-file, not the Mislaka assessment itself.
# Matched case-insensitively after stripping punctuation/emoji prefixes.
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
})

# Schema-catalog / platform-internal sections that are not customer data.
CATALOG_SECTION_TITLES = frozenset({
    'מפת שיוכים (affiliations)',
    'affiliation mapping snapshot',
})


def _normalize_section_title(title: str) -> str:
    text = str(title or '').strip()
    # Drop leading emoji / decorative marks the renderer prefixes.
    while text and ord(text[0]) > 0x1F300:
        text = text[1:].strip()
    return text.lower()


def is_statistical_section_title(title: str) -> bool:
    """True when a report section is statistical filler, not assessment data."""
    return _normalize_section_title(title) in STATISTICAL_SECTION_TITLES


def is_non_assessment_section_title(title: str) -> bool:
    """True for statistical filler or schema-catalog sections."""
    normalized = _normalize_section_title(title)
    return normalized in STATISTICAL_SECTION_TITLES or normalized in CATALOG_SECTION_TITLES


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


def _style_table(table, header_color: str = '#E3F2FD'):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(header_color)),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#F8FAFC')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    return table


def _safe_paragraph(text: str, style) -> Any:
    from reportlab.platypus import Paragraph

    cleaned = html.escape(str(text or '')).replace('\n', '<br/>')
    return Paragraph(cleaned, style)


def _build_mislaka_assessment_pdf(summary: Dict[str, Any]) -> bytes:
    """Render the Mislaka assessment (identity + accounts + totals) as PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    base_font, bold_font = _register_fonts()
    is_hebrew = (summary.get('language') or '') == 'hebrew'
    assessment = summary.get('pension_assessment') or {}
    client = assessment.get('client') or {}
    totals = assessment.get('totals') or {}
    accounts = assessment.get('accounts') or []
    sci = summary.get('savings_cover_id_summary') or {}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'MislakaPdfTitle', parent=styles['Title'],
        fontName=bold_font, fontSize=16, leading=20,
        alignment=2 if is_hebrew else 0,
    )
    heading_style = ParagraphStyle(
        'MislakaPdfHeading', parent=styles['Heading2'],
        fontName=bold_font, fontSize=12, leading=15,
        alignment=2 if is_hebrew else 0, spaceBefore=8, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        'MislakaPdfBody', parent=styles['BodyText'],
        fontName=base_font, fontSize=9, leading=12,
        alignment=2 if is_hebrew else 0,
    )
    cell_style = ParagraphStyle(
        'MislakaPdfCell', parent=styles['BodyText'],
        fontName=base_font, fontSize=8, leading=10,
    )

    story: List[Any] = []
    title = (
        summary.get('title')
        or ('דו״ח הערכת מסלקה' if is_hebrew else 'Mislaka Assessment Report')
    )
    story.append(Paragraph(html.escape(str(title)), title_style))
    story.append(Spacer(1, 8))

    customer_id = client.get('id_number') or sci.get('customer_id') or ''
    customer_name = client.get('full_name') or client.get('client_name') or ''
    birth_date = client.get('birth_date') or sci.get('birth_date') or ''
    id_valid = client.get('id_israeli_valid')
    if id_valid is None:
        id_valid = sci.get('customer_id_valid')

    identity_heading = 'תעודת זהות ופרטי לקוח' if is_hebrew else 'Customer Identity'
    story.append(Paragraph(identity_heading, heading_style))
    identity_rows = [
        ['תעודת זהות' if is_hebrew else 'National ID', _as_str(customer_id)],
        ['שם מלא' if is_hebrew else 'Full Name', _as_str(customer_name)],
        ['תאריך לידה' if is_hebrew else 'Birth Date', _as_str(birth_date)],
        [
            'תקינות מזהה' if is_hebrew else 'ID Validation',
            ('תקין' if id_valid else 'דורש בדיקה') if is_hebrew else ('Valid' if id_valid else 'Needs review'),
        ],
        ['מזהה דוח' if is_hebrew else 'Report ID', _as_str(summary.get('report_id'))],
        ['נוצר' if is_hebrew else 'Generated At', _as_str(summary.get('generated_at'))],
    ]
    identity_table = Table(identity_rows, colWidths=[150, 340])
    identity_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8F5E9')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('FONTNAME', (0, 0), (-1, -1), base_font),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(identity_table)
    story.append(Spacer(1, 10))

    totals_heading = 'סה״כ צבירה ופיצויים' if is_hebrew else 'Accumulation & Severance'
    story.append(Paragraph(totals_heading, heading_style))
    # Copy totals from the assessment — do not re-sum accounts here.
    total_balance = totals.get('total_balance', sci.get('total_savings', 0))
    total_savings = totals.get('total_savings', totals.get('total_savings_balance', 0))
    total_severance = totals.get('total_severance', totals.get('total_severance_balance', sci.get('total_severance', 0)))
    account_count = totals.get('account_count', len(accounts))
    totals_rows = [
        ['סה״כ צבירה' if is_hebrew else 'Total Accumulation', _as_money(total_balance)],
        ['סה״כ חסכונות' if is_hebrew else 'Total Savings', _as_money(total_savings)],
        ['סה״כ פיצויים' if is_hebrew else 'Total Severance', _as_money(total_severance)],
        ['מספר פוליסות' if is_hebrew else 'Policy Count', _as_str(account_count)],
    ]
    totals_table = Table(totals_rows, colWidths=[150, 340])
    totals_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E3F2FD')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('FONTNAME', (0, 0), (-1, -1), base_font),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 10))

    if accounts:
        accounts_heading = 'חשבונות ופוליסות' if is_hebrew else 'Accounts & Policies'
        story.append(Paragraph(accounts_heading, heading_style))
        header = [
            'פוליסה' if is_hebrew else 'Policy',
            'יצרן' if is_hebrew else 'Provider',
            'מוצר' if is_hebrew else 'Product',
            'צבירה' if is_hebrew else 'Balance',
            'פיצויים' if is_hebrew else 'Severance',
        ]
        table_data: List[List[Any]] = [[_safe_paragraph(h, cell_style) for h in header]]
        for acct in accounts[:80]:
            table_data.append([
                _safe_paragraph(_as_str(acct.get('policy_number')), cell_style),
                _safe_paragraph(_as_str(acct.get('provider')), cell_style),
                _safe_paragraph(_as_str(acct.get('product_type_name') or acct.get('product_type')), cell_style),
                _safe_paragraph(_as_money(acct.get('total_balance', acct.get('savings_balance', 0))), cell_style),
                _safe_paragraph(_as_money(acct.get('severance_balance', 0)), cell_style),
            ])
        accounts_table = Table(table_data, colWidths=[90, 110, 110, 90, 90], repeatRows=1)
        _style_table(accounts_table)
        story.append(accounts_table)
        story.append(Spacer(1, 10))

    integrity_issues = list(sci.get('integrity_issues') or [])
    if integrity_issues:
        story.append(Paragraph('שלמות נתונים' if is_hebrew else 'Data Integrity', heading_style))
        for issue in integrity_issues[:12]:
            story.append(_safe_paragraph(f'• {issue}', body_style))
        story.append(Spacer(1, 8))

    for section in summary.get('assessment_sections') or []:
        title_text = section.get('title') or ''
        if is_non_assessment_section_title(title_text):
            continue
        content = (section.get('content') or '').strip()
        rows = section.get('rows') or []
        if not content and not rows:
            continue
        story.append(Paragraph(html.escape(str(title_text)), heading_style))
        if content:
            # Keep the assessment narrative; cap so the PDF stays a document, not a dump.
            clipped = content if len(content) <= 4000 else content[:4000] + '\n…'
            story.append(_safe_paragraph(clipped, body_style))
            story.append(Spacer(1, 4))
        columns = section.get('columns') or []
        if rows and columns:
            header_cells = [_safe_paragraph(_as_str(col), cell_style) for col in columns]
            table_rows: List[List[Any]] = [header_cells]
            for row in rows[:60]:
                table_rows.append([
                    _safe_paragraph(_as_str(row.get(col, '') if isinstance(row, dict) else row), cell_style)
                    for col in columns
                ])
            width = 490 / max(len(columns), 1)
            data_table = Table(table_rows, colWidths=[width] * len(columns), repeatRows=1)
            _style_table(data_table, '#FFF8E1')
            story.append(data_table)
            story.append(Spacer(1, 8))

    doc.build(story)
    return buffer.getvalue()


def _build_generic_summary_pdf(summary: Dict[str, Any]) -> bytes:
    """Existing generic savings/cover summary PDF (non-Mislaka reports)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    base_font, bold_font = _register_fonts()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph('PHINS Savings & Insurance Report Summary', styles['Title']))
    story.append(Spacer(1, 10))

    info_rows = [
        ['Report ID', _as_str(summary.get('report_id'))],
        ['Title', _as_str(summary.get('title'))],
        ['Language', _as_str(summary.get('language'))],
        ['Report Type', _as_str(summary.get('report_type'))],
        ['Risk Score', _as_str(summary.get('risk_score'))],
        ['Confidence', _as_str(summary.get('confidence'))],
        ['Generated At', _as_str(summary.get('generated_at'))],
    ]
    info_table = Table(info_rows, colWidths=[130, 360])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, -1), base_font),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 12))

    sci = summary.get('savings_cover_id_summary', {}) or {}
    story.append(Paragraph('Savings / Cover / ID Summary', styles['Heading2']))
    sci_rows = [
        ['Customer ID', _as_str(sci.get('customer_id', ''))],
        ['Birth Date', _as_str(sci.get('birth_date', ''))],
        ['Total Savings', _as_str(sci.get('total_savings', 0))],
        ['Total Severance', _as_str(sci.get('total_severance', 0))],
        ['Total Cover', _as_str(sci.get('total_cover', 0))],
    ]
    sci_table = Table(sci_rows, colWidths=[170, 320])
    sci_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8F5E9')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 0), (-1, -1), base_font),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    story.append(sci_table)
    story.append(Spacer(1, 12))

    for section in summary.get('table_sections', []) or []:
        if is_non_assessment_section_title(section.get('title', '')):
            continue
        columns = section.get('columns') or []
        rows = section.get('rows') or []
        if not columns or not rows:
            continue
        story.append(Paragraph(_as_str(section.get('title', 'Section')), styles['Heading3']))
        table_data = [columns]
        for row in rows[:40]:
            table_data.append([_as_str(row.get(col, '') if isinstance(row, dict) else row) for col in columns])
        width = 490 / max(len(columns), 1)
        data_table = Table(table_data, repeatRows=1, colWidths=[width] * len(columns))
        data_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E3F2FD')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTNAME', (0, 0), (-1, -1), base_font),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        story.append(data_table)
        story.append(Spacer(1, 10))

    recs = summary.get('recommendations', []) or []
    if recs:
        story.append(Paragraph('Recommendations', styles['Heading3']))
        for rec in recs[:12]:
            title = f"[{_as_str(rec.get('priority', 'medium')).upper()}] {_as_str(rec.get('title', 'Recommendation'))}"
            desc = _as_str(rec.get('description', ''))
            story.append(Paragraph(title, styles['BodyText']))
            if desc:
                story.append(Paragraph(desc, styles['BodyText']))
            story.append(Spacer(1, 6))

    doc.build(story)
    return buffer.getvalue()


def build_report_pdf_bytes(summary: Dict[str, Any]) -> bytes:
    """Build PDF bytes for a downloadable report summary.

    Pension / Mislaka assessments use the assessment-only renderer so the
    downloaded file matches the uploaded identity, accumulation and
    severance — not the statistical Data Profile trailer.
    """
    try:
        if summary.get('is_pension_data') or summary.get('pension_assessment'):
            return _build_mislaka_assessment_pdf(summary)
        return _build_generic_summary_pdf(summary)
    except Exception:
        fallback_text = json.dumps(summary, ensure_ascii=False, indent=2)
        return fallback_text.encode('utf-8')
