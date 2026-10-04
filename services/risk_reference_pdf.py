"""
Downloadable Risk Reference report.

Figures are copied from ``build_risk_reference``. This module does not
reprice, refill a missing rate, or plot a withheld value as zero.
The sha256 covers the canonical numeric block so two viewers of the
same forecast share one hash.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.phins_pdf_brand import (
    BRAND_NAME,
    BRAND_TAGLINE,
    PHINS_GOLD,
    PHINS_GREY,
    PHINS_NAVY,
    PHINS_WASH,
    page_callbacks,
)

PDF_FILENAME = 'phins-risk-reference.pdf'

_YEAR_KEYS = (
    'year', 'age', 'age_factor', 'life_sum', 'disability_sum',
    'annual_premium', 'life_monthly', 'disability_monthly',
    'mortality_qx', 'disability_ix', 'rates_resolved',
    'expected_loss', 'loss_ratio',
)
_MAP_KEYS = (
    'age', 'annual_premium', 'expected_loss', 'mortality_qx', 'disability_ix',
    'rates_resolved', 'life_sum', 'disability_sum',
    'healthy_curtate_expectancy', 'disability_curtate_expectancy',
    'male_years', 'female_years', 'pricing_basis_disabled_curtate',
)
_SAVINGS_YEAR_KEYS = (
    'year', 'age', 'annual_risk_premium', 'monthly_contribution',
    'annual_contribution', 'opening_balance', 'yield',
    'management_fee_income', 'gross_closing_aum_before_fee',
    'closing_balance', 'cumulative_contribution',
)


def _bools(block: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    return {
        key: value
        for key, value in (block or {}).items()
        if isinstance(value, bool)
    }


def _pick(row: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    return {key: row.get(key) for key in keys}


def risk_reference_canonical_block(reference: Dict[str, Any]) -> Dict[str, Any]:
    """Numbers and integrity flags the PDF is allowed to restate."""
    ref = reference.get('reference') or {}
    age_map = reference.get('age_map') or {}
    block: Dict[str, Any] = {
        'profile_id': reference.get('profile_id'),
        'face_amount': ref.get('face_amount'),
        'start_age': ref.get('start_age'),
        'projection_years': ref.get('projection_years'),
        'life_sum': ref.get('life_sum'),
        'disability_sum': ref.get('disability_sum'),
        'life_sum_post65': ref.get('life_sum_post65'),
        'disability_sum_post65': ref.get('disability_sum_post65'),
        'yearly': [_pick(row, _YEAR_KEYS) for row in reference.get('yearly_projection') or []],
        'totals': {
            'cumulative_premium': (reference.get('totals') or {}).get('cumulative_premium'),
            'cumulative_expected_loss': (reference.get('totals') or {}).get('cumulative_expected_loss'),
            'average_loss_ratio': (reference.get('totals') or {}).get('average_loss_ratio'),
            'expense_plus_capital_margin': (reference.get('totals') or {}).get('expense_plus_capital_margin'),
        },
        'data_integrity': _bools(reference.get('data_integrity')),
        'age_map': {
            'age_min': age_map.get('age_min'),
            'age_max': age_map.get('age_max'),
            'face_amount': age_map.get('face_amount'),
            'terminal_age': age_map.get('terminal_age'),
            'disability_adl': age_map.get('disability_adl'),
            'disability_mortality_multiplier': age_map.get('disability_mortality_multiplier'),
            'rows': [_pick(row, _MAP_KEYS) for row in age_map.get('rows') or []],
            'data_integrity': _bools(age_map.get('data_integrity')),
        },
    }
    savings = reference.get('savings_accumulation')
    if savings:
        block['savings'] = {
            'savings_rate': savings.get('savings_rate'),
            'savings_yield_pct': savings.get('savings_yield_pct'),
            'management_fee_pct_of_aum': savings.get('management_fee_pct_of_aum'),
            'yearly': [_pick(row, _SAVINGS_YEAR_KEYS) for row in savings.get('yearly') or []],
            'totals': savings.get('totals') or {},
            'data_integrity': _bools(savings.get('data_integrity')),
        }
    return block


def risk_reference_document_hash(reference: Dict[str, Any]) -> str:
    """sha256 of the canonical numeric block. ``None`` stays JSON null."""
    encoded = json.dumps(
        risk_reference_canonical_block(reference),
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _number(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    return number


def _money(value: Any) -> str:
    number = _number(value)
    if number is None:
        return 'withheld'
    sign = '-$' if number < 0 else '$'
    return sign + f'{abs(number):,.2f}'


def _rate(value: Any, digits: int = 3) -> str:
    number = _number(value)
    if number is None:
        return '—'
    return f'{number * 100:.{digits}f}%'


def _plain(value: Any, digits: int = 2) -> str:
    number = _number(value)
    if number is None:
        return '—'
    return f'{number:.{digits}f}'


def _factor(value: Any) -> str:
    number = _number(value)
    if number is None:
        return '—'
    return f'{number:.4f}'


def _flag(value: Any) -> str:
    if value is True:
        return 'PASS'
    if value is False:
        return 'FAIL'
    return '—'


def _source(value: Any) -> str:
    if value == 'published_profile':
        return 'Published'
    if value == 'kernel_table':
        return 'Kernel'
    if value in ('unavailable', None, ''):
        return 'Withheld'
    return str(value)


def _esc(text: Any) -> str:
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def _line_chart(
    ages: Sequence[int],
    series: Sequence[Tuple[str, str, Sequence[Optional[float]]]],
    usable: float,
    y_tick,
) -> Any:
    """Polyline chart. A missing value breaks the line and is not drawn as zero."""
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors

    width = float(usable)
    height = 168.0
    drawing = Drawing(width, height)
    left, right, top, bottom = 48.0, 10.0, 18.0, 22.0
    plot_w = max(10.0, width - left - right)
    plot_h = height - top - bottom
    drawing.add(Rect(
        left, bottom, plot_w, plot_h,
        fillColor=colors.HexColor(PHINS_WASH),
        strokeColor=colors.HexColor('#c5d0e4'),
        strokeWidth=0.4,
    ))
    finite = [value for _label, _color, seq in series for value in seq if value is not None]
    peak = max(finite) if finite else 1.0
    if peak <= 0:
        peak = 1.0
    span = peak * 1.08
    count = max(len(ages), 1)

    def x_of(index: int) -> float:
        if count == 1:
            return left + plot_w / 2.0
        return left + plot_w * index / (count - 1)

    def y_of(value: float) -> float:
        return bottom + plot_h * (value / span)

    for step in range(5):
        yy = bottom + plot_h * step / 4.0
        drawing.add(Line(
            left, yy, left + plot_w, yy,
            strokeColor=colors.HexColor('#d5deee'), strokeWidth=0.3,
        ))
        drawing.add(String(
            left - 4, yy - 2, y_tick(span * step / 4.0),
            fontName='Helvetica', fontSize=6, fillColor=colors.HexColor(PHINS_GREY),
            textAnchor='end',
        ))
    for index, age in enumerate(ages):
        if age % 10 == 0 or index in (0, count - 1):
            drawing.add(String(
                x_of(index), 6, str(age),
                fontName='Helvetica', fontSize=6, fillColor=colors.HexColor(PHINS_GREY),
                textAnchor='middle',
            ))

    legend_x = left
    for label, color, seq in series:
        drawing.add(Line(
            legend_x, height - 7, legend_x + 12, height - 7,
            strokeColor=colors.HexColor(color), strokeWidth=1.6,
        ))
        drawing.add(String(
            legend_x + 14, height - 10, label,
            fontName='Helvetica', fontSize=7, fillColor=colors.HexColor(PHINS_NAVY),
            textAnchor='start',
        ))
        legend_x += 14 + 4.2 * len(label) + 18
        points: List[float] = []
        for index, value in enumerate(seq):
            if value is None:
                if len(points) >= 4:
                    drawing.add(PolyLine(
                        points, strokeColor=colors.HexColor(color), strokeWidth=1.4,
                    ))
                points = []
                continue
            points.extend((x_of(index), y_of(value)))
        if len(points) >= 4:
            drawing.add(PolyLine(
                points, strokeColor=colors.HexColor(color), strokeWidth=1.4,
            ))
    return drawing


def _table(header: Sequence[str], rows: Iterable[Sequence[str]], widths: Sequence[float]):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    data = [list(header)]
    data.extend(list(row) for row in rows)
    table = Table(data, colWidths=list(widths), hAlign='LEFT', repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(PHINS_NAVY)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(PHINS_GOLD)),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor(PHINS_WASH)),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#c5d0e4')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
    ]))
    return table


def _axis_money(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f'${value / 1_000_000:.1f}m'
    if absolute >= 1000:
        return f'${value / 1000:.0f}k'
    return f'${value:.0f}'


def _axis_pct(value: float) -> str:
    return f'{value * 100:.1f}%'


def _axis_years(value: float) -> str:
    return f'{value:.0f}'


def render_risk_reference_pdf(reference: Dict[str, Any]) -> Tuple[str, bytes]:
    """Portrait PHINS letterhead report of one risk-reference payload."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    digest = risk_reference_document_hash(reference)
    ref = reference.get('reference') or {}
    totals = reference.get('totals') or {}
    age_map = reference.get('age_map') or {}
    rows = list(reference.get('yearly_projection') or [])
    map_rows = list(age_map.get('rows') or [])
    face = ref.get('face_amount')

    buf = io.BytesIO()
    pagesize = A4
    usable = pagesize[0] - 24 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=24 * mm, bottomMargin=16 * mm,
        title='PHINS Risk Reference',
        author=BRAND_NAME,
        subject=digest,
    )
    styles = getSampleStyleSheet()
    navy = colors.HexColor(PHINS_NAVY)
    title_style = ParagraphStyle(
        'RrTitle', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=16,
        textColor=navy, alignment=0, leading=20, spaceAfter=4,
    )
    h2 = ParagraphStyle(
        'RrH2', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=12,
        textColor=navy, alignment=0, leading=15, spaceBefore=10, spaceAfter=4,
    )
    body = ParagraphStyle(
        'RrBody', parent=styles['BodyText'], fontName='Helvetica', fontSize=9,
        leading=12, textColor=colors.HexColor('#1A202C'),
    )
    meta = ParagraphStyle(
        'RrMeta', parent=body, fontSize=8, leading=11, textColor=colors.HexColor(PHINS_GREY),
    )

    def para(text: str, style) -> Paragraph:
        return Paragraph(_esc(text), style)

    story: List[Any] = [
        Paragraph('Risk Reference', title_style),
        para(BRAND_TAGLINE, meta),
        Spacer(1, 6),
        para(ref.get('rate_method') or '', body),
        Spacer(1, 4),
        para(age_map.get('method') or '', body),
        Spacer(1, 6),
        para(f'Document hash {digest}', meta),
        para(
            'The hash is the sha256 of the canonical numeric block: profile, face, '
            'projection, age map, totals, and boolean integrity flags. A missing rate '
            'or loss is withheld. It is not printed or drawn as zero.',
            meta,
        ),
        Spacer(1, 8),
    ]

    summary = [
        ['Risk cover', _money(face)],
        ['Life at issue age', _money(ref.get('life_sum'))],
        ['Disability at issue age', _money(ref.get('disability_sum'))],
        ['Life from the benefit band', _money(ref.get('life_sum_post65'))],
        ['Disability from the benefit band', _money(ref.get('disability_sum_post65'))],
        ['Cumulative premium', _money(totals.get('cumulative_premium'))],
        ['Cumulative expected loss', _money(totals.get('cumulative_expected_loss'))],
        ['Average loss ratio', _rate(totals.get('average_loss_ratio'), 2)],
        ['Start age', '—' if ref.get('start_age') is None else str(ref.get('start_age'))],
        ['Projection years', '—' if ref.get('projection_years') is None else str(ref.get('projection_years'))],
    ]
    story.append(_table(
        ['Item', 'Value'],
        summary,
        [usable * 0.62, usable * 0.38],
    ))

    story.append(Paragraph('Projection', h2))
    story.append(para(
        'This table is the selected forecast. Amounts and rates are copied from that forecast.',
        meta,
    ))
    story.append(Spacer(1, 4))
    projection = []
    for row in rows:
        projection.append([
            str(row.get('year') if row.get('year') is not None else '—'),
            str(row.get('age') if row.get('age') is not None else '—'),
            _factor(row.get('age_factor')),
            _money(row.get('life_sum')),
            _money(row.get('disability_sum')),
            _money(row.get('annual_premium')),
            _rate(row.get('mortality_qx'), 3),
            _rate(row.get('disability_ix'), 3),
            _source(row.get('rate_source')),
            _money(row.get('expected_loss')),
            _rate(row.get('loss_ratio'), 2),
        ])
    col = usable / 11.0
    story.append(_table(
        ['Year', 'Age', 'Factor', 'Life', 'Disability', 'Premium', 'q(x)', 'i(x)', 'Source', 'Loss', 'Ratio'],
        projection,
        [col * 0.7, col * 0.7, col * 0.85, col * 1.15, col * 1.15, col * 1.1,
         col * 0.9, col * 0.9, col * 1.05, col * 1.15, col * 0.85],
    ))

    savings = reference.get('savings_accumulation')
    if savings:
        story.append(Paragraph('Savings accumulation', h2))
        story.append(para(
            'Savings rate '
            f"{_plain((savings.get('savings_rate') or 0) * 100, 1)}% of risk premium, yield "
            f"{_plain((savings.get('savings_yield_pct') or 0) * 100, 2)}%, management fee "
            f"{_plain((savings.get('management_fee_pct_of_aum') or 0) * 100, 2)}% of AUM.",
            body,
        ))
        savings_rows = []
        for row in savings.get('yearly') or []:
            savings_rows.append([
                str(row.get('year') if row.get('year') is not None else '—'),
                str(row.get('age') if row.get('age') is not None else '—'),
                _money(row.get('annual_contribution')),
                _money(row.get('yield')),
                _money(row.get('management_fee_income')),
                _money(row.get('closing_balance')),
            ])
        story.append(Spacer(1, 4))
        story.append(_table(
            ['Year', 'Age', 'Contribution', 'Yield', 'Fee', 'Closing'],
            savings_rows,
            [usable * 0.12, usable * 0.12, usable * 0.2, usable * 0.18, usable * 0.18, usable * 0.2],
        ))
        saving_totals = savings.get('totals') or {}
        story.append(Spacer(1, 4))
        story.append(para(
            'Closing AUM '
            f"{_money(saving_totals.get('closing_aum_balance'))}. "
            'Cumulative contribution '
            f"{_money(saving_totals.get('cumulative_contribution'))}.",
            meta,
        ))

    story.append(Paragraph('Age map', h2))
    multiplier = age_map.get('disability_mortality_multiplier')
    mult_note = (
        'Disabled years are the published ADL 3 remaining-life average. '
        'Man and woman are the same study. Healthy years stay curtate survival on pricing q(x). '
        'A missing research age is left blank. The years do not change with the face amount.'
    )
    if multiplier is None:
        mult_note += ' The ADL 10 pricing multiplier is not on the live table.'
    else:
        mult_note += (
            f" The ADL {age_map.get('disability_adl')} pricing multiplier remains "
            f"{_plain(multiplier, 2)} and is not this line."
        )
    story.append(para(mult_note, meta))
    story.append(para(
        'A missing value is a break in the line. It is not drawn as zero.',
        meta,
    ))
    ages = [int(row['age']) for row in map_rows if row.get('age') is not None]

    def series_values(key: str) -> List[Optional[float]]:
        return [_number(row.get(key)) for row in map_rows]

    story.append(Spacer(1, 4))
    story.append(Paragraph('Age vs premium and expected loss', h2))
    story.append(_line_chart(
        ages,
        [
            ('Annual premium', PHINS_NAVY, series_values('annual_premium')),
            ('Expected loss', PHINS_GOLD, series_values('expected_loss')),
        ],
        usable,
        _axis_money,
    ))
    story.append(Paragraph('Mortality and disability probabilities', h2))
    story.append(_line_chart(
        ages,
        [
            ('Mortality q(x)', PHINS_NAVY, series_values('mortality_qx')),
            ('Disability i(x)', '#c45c26', series_values('disability_ix')),
        ],
        usable,
        _axis_pct,
    ))
    story.append(Paragraph('Life expectancy if disabled', h2))
    story.append(_line_chart(
        ages,
        [
            ('Healthy q(x)', PHINS_NAVY, series_values('healthy_curtate_expectancy')),
            ('ADL 3 average', PHINS_GOLD, series_values('disability_curtate_expectancy')),
            ('ADL 3 man', PHINS_GREY, series_values('male_years')),
            ('ADL 3 woman', '#c45c26', series_values('female_years')),
        ],
        usable,
        _axis_years,
    ))

    story.append(Paragraph('Age-map table', h2))
    age_table = []
    for row in map_rows:
        age_table.append([
            str(row.get('age') if row.get('age') is not None else '—'),
            _money(row.get('annual_premium')),
            _money(row.get('expected_loss')),
            _rate(row.get('mortality_qx'), 3),
            _rate(row.get('disability_ix'), 3),
            _plain(row.get('healthy_curtate_expectancy'), 2),
            _plain(row.get('disability_curtate_expectancy'), 2),
        ])
    story.append(_table(
        ['Age', 'Premium', 'Expected loss', 'q(x)', 'i(x)', 'Healthy years', 'Disabled years'],
        age_table,
        [usable * 0.1, usable * 0.16, usable * 0.16, usable * 0.13, usable * 0.13, usable * 0.16, usable * 0.16],
    ))

    story.append(Paragraph('Data integrity', h2))
    integrity_rows = []
    for key, value in _bools(reference.get('data_integrity')).items():
        integrity_rows.append([key.replace('_', ' '), _flag(value)])
    for key, value in _bools(age_map.get('data_integrity')).items():
        integrity_rows.append([f'age map {key.replace("_", " ")}', _flag(value)])
    if savings:
        for key, value in _bools(savings.get('data_integrity')).items():
            integrity_rows.append([f'savings {key.replace("_", " ")}', _flag(value)])
    severity = (reference.get('data_integrity') or {}).get('severity_assumptions') or {}
    if severity:
        integrity_rows.append([
            'mortality severity',
            _plain(severity.get('mortality_severity'), 2),
        ])
        integrity_rows.append([
            'disability severity',
            _plain(severity.get('disability_severity'), 2),
        ])
    story.append(_table(['Check', 'Result'], integrity_rows, [usable * 0.72, usable * 0.28]))
    story.append(Spacer(1, 8))
    story.append(para(f'Document hash {digest}', meta))

    on_first, on_later = page_callbacks(
        pagesize,
        title='Risk Reference',
        font='Helvetica',
        bold='Helvetica-Bold',
        badge='Research & Audit',
        footer_note=f'{BRAND_NAME} — Confidential actuarial document · Research & Audit',
    )
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return PDF_FILENAME, buf.getvalue()
