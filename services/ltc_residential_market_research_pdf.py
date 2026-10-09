"""
PDF export for the LTC residential services market & hedging study.

Renders the full research pack built by ``ltc_residential_market_research`` as
a portrait A4 PHINS document: letterhead, methodology, narrative, parameters,
KPIs, hedge summary, three research charts, every table (column groups of a
readable width), the source register and the integrity block. English only;
figures are taken verbatim from the pack so the PDF never diverges from the
dashboard or the CSV downloads.
"""

from __future__ import annotations

import html
import io
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from services.phins_pdf_brand import (
    BRAND_NAME,
    BRAND_TAGLINE,
    PHINS_GOLD,
    PHINS_NAVY,
    PHINS_WASH,
    page_callbacks,
)
from services.ltc_residential_market_research import (
    STUDY_ID,
    STUDY_TITLE,
    TABLE_COLUMNS,
    extract_research_table,
)


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


METHODOLOGY = (
    'History (1975–2025) is anchored on published series: CMS National Health Expenditure tables 14 and 15, '
    'Genworth/CareScout cost-of-care medians, KFF facility characteristics, MedPAC margins, OECD Health at a Glance, '
    'the Taub Center and the State Comptroller for Israel, and company filings for operators. The outlook (2026–2075) '
    'multiplies the UN 80+ population share by a healthy-ageing offset and a scenario factor to form a recipients index; '
    'the residential share of recipients moves linearly to its 2050 target; spend as a share of GDP scales with recipients, '
    'the cost-weighted setting mix (home ≈ 0.55 × residential) and relative care-cost inflation. TAM is nominal spend, SAM the '
    'share flowing to privately operated providers, SOM the obtainable share entered on the dashboard. The hedge model prices a '
    '3+ADL book on the same incidence and remaining-life-expectancy curves as the PHINS LTC/Life study and compares expected '
    'claims with income from care operators, care real estate, home-care platforms and a liquidity reserve. Every row carries '
    'a figure basis (published, derived, estimate, projection or model) and source ids; integrity checks and sha256 hashes '
    'are printed at the end.'
)

TABLE_TITLES: Dict[str, str] = {
    'spending_history': 'US long-term care spending 1970–2024 (CMS NHE, $bn)',
    'cost_of_care': 'US cost of care by setting 2004–2025 (annual medians, USD)',
    'payer_mix': 'Payer mix — who pays for care',
    'market_structure': 'Market structure by region',
    'setting_comparison': 'Private vs public institutions vs home care',
    'operators': 'Main players — operators, REITs, home-care platforms',
    'margin_benchmarks': 'Revenue-margin benchmarks by segment',
    'workforce': 'Workforce',
    'regulation': 'Regulation, financing and standards by jurisdiction',
    'demand_forecast': 'Demand and spend forecast (selected region and scenario)',
    'tam_sam_som': 'TAM / SAM / SOM by milestone year',
    'scenarios': 'Scenario comparison',
    'hedge_book': 'Hedge model — 3+ADL book by age band',
    'hedge_allocation': 'Hedge model — care-sector allocation',
    'swot': 'SWOT — investing in LTC residential services',
    'case_studies': 'Case studies',
    'eras': 'Market eras 1965–2075',
}

# Columns rendered per table, in groups narrow enough for portrait A4.
PDF_TABLE_GROUPS: Dict[str, List[List[str]]] = {
    'spending_history': [['year', 'era', 'nursing_care_bn', 'home_health_bn', 'total_ltc_bn', 'home_health_share_pct', 'cagr_since_prior_row_pct', 'figure_basis']],
    'cost_of_care': [['year', 'setting_label', 'annual_cost_usd', 'monthly_cost_usd', 'relative_to_semi_private', 'cagr_since_first_survey_pct', 'figure_basis']],
    'payer_mix': [['region', 'segment', 'year', 'public_pct', 'medicare_pct', 'medicaid_pct', 'private_insurance_pct', 'out_of_pocket_pct', 'other_pct', 'shares_total_pct'], ['region', 'segment', 'year', 'figure_basis', 'note']],
    'market_structure': [['label', 'ltc_spend_gdp_pct', 'ltc_spend_year', 'public_share_pct', 'residential_recipient_share_pct', 'beds_per_1000_65plus', 'workers_per_100_65plus', 'for_profit_share_pct'], ['label', 'private_provision_share_pct', 'pop80_share_2025_pct', 'pop80_share_2050_pct', 'pop80_growth_to_2050_pct', 'ltc_spend_2025_usd_bn', 'note']],
    'setting_comparison': [['label', 'us_share_of_facilities_pct', 'typical_occupancy_pct', 'median_annual_cost_usd', 'nurse_hprd_typical', 'rn_hprd_typical', 'medicaid_share_pct', 'ebitdar_margin_pct'], ['label', 'deficiencies_per_survey', 'labor_cost_share_pct', 'capital_intensity', 'regulatory_intensity', 'typical_acuity', 'note']],
    'operators': [['player', 'country', 'segment', 'ownership', 'revenue_bn', 'currency', 'fiscal_year'], ['player', 'margin_metric', 'margin_pct', 'beds_or_units', 'unit_label', 'countries', 'occupancy_pct', 'figure_basis'], ['player', 'note']],
    'margin_benchmarks': [['segment', 'metric', 'low_pct', 'mid_pct', 'high_pct', 'year', 'figure_basis', 'note']],
    'workforce': [['region', 'metric', 'value', 'unit', 'year', 'figure_basis', 'note']],
    'regulation': [['jurisdiction', 'financing_model', 'founding_statute', 'key_reform'], ['jurisdiction', 'staffing_standard', 'quality_regime', 'accommodation_standard', 'direction']],
    'demand_forecast': [['year', 'era', 'pop80_share_pct', 'recipients_index', 'home_share_pct', 'residential_demand_index', 'home_demand_index', 'ltc_spend_gdp_pct'], ['year', 'gdp_usd_bn', 'ltc_spend_usd_bn', 'ltc_spend_at_2025_gdp_usd_bn', 'residential_spend_usd_bn', 'home_spend_usd_bn', 'public_share_pct', 'private_spend_usd_bn', 'relative_cost_index']],
    'tam_sam_som': [['year', 'segment', 'tam_usd_bn', 'tam_at_2025_gdp_usd_bn', 'sam_usd_bn', 'som_usd_bn', 'private_provision_share_pct', 'som_share_of_sam_pct', 'public_share_pct']],
    'scenarios': [['label', 'selected', 'home_share_target_pct', 'recipients_index_2050', 'residential_demand_index_2050', 'ltc_spend_gdp_pct_2050', 'ltc_spend_usd_bn_2050'], ['label', 'recipients_index_end', 'residential_demand_index_end', 'ltc_spend_gdp_pct_end', 'ltc_spend_usd_bn_end', 'public_share_pct_end', 'end_year', 'note']],
    'hedge_book': [['age_min', 'age_max', 'band_lives', 'incidence_per_1000', 'mean_claim_duration_years', 'steady_state_prevalence_pct', 'expected_annual_claims', 'expected_new_claim_cost', 'stressed_annual_claims']],
    'hedge_allocation': [['label', 'allocation_pct', 'capital', 'yield_pct', 'claim_beta', 'expected_income', 'stressed_income', 'income_uplift_under_stress', 'income_to_claims_pct'], ['label', 'liquidity', 'volatility', 'rationale']],
    'swot': [['quadrant', 'item', 'weight', 'applies_to', 'source_ids', 'figure_basis']],
    'case_studies': [['title', 'period', 'segment', 'what_happened'], ['title', 'lesson', 'metric', 'source_ids', 'figure_basis']],
    'eras': [['start', 'end', 'era', 'kind', 'description', 'figure_basis']],
}

# Demand-forecast rows are sampled every five years in the PDF.
SAMPLED_TABLES = {'demand_forecast'}

MONEY_KEYS = {
    'annual_cost_usd', 'monthly_cost_usd', 'median_annual_cost_usd', 'capital', 'expected_income', 'stressed_income',
    'income_uplift_under_stress', 'expected_annual_claims', 'expected_new_claim_cost', 'stressed_annual_claims',
}
PCT_KEYS = {k for k in {
    'home_health_share_pct', 'cagr_since_prior_row_pct', 'cagr_since_first_survey_pct', 'public_pct', 'medicare_pct',
    'medicaid_pct', 'private_insurance_pct', 'out_of_pocket_pct', 'other_pct', 'shares_total_pct', 'ltc_spend_gdp_pct',
    'public_share_pct', 'residential_recipient_share_pct', 'for_profit_share_pct', 'private_provision_share_pct',
    'pop80_share_2025_pct', 'pop80_share_2050_pct', 'pop80_growth_to_2050_pct', 'us_share_of_facilities_pct',
    'typical_occupancy_pct', 'medicaid_share_pct', 'ebitdar_margin_pct', 'labor_cost_share_pct', 'margin_pct',
    'occupancy_pct', 'low_pct', 'mid_pct', 'high_pct', 'pop80_share_pct', 'home_share_pct', 'residential_share_pct',
    'som_share_of_sam_pct', 'home_share_target_pct', 'ltc_spend_gdp_pct_2050', 'ltc_spend_gdp_pct_end',
    'public_share_pct_end', 'steady_state_prevalence_pct', 'allocation_pct', 'yield_pct', 'income_to_claims_pct',
}}
INT_KEYS = {'year', 'start', 'end', 'age_min', 'age_max', 'band_lives', 'fiscal_year', 'countries', 'end_year', 'ltc_spend_year', 'weight', 'beds_or_units'}


def _fmt(key: str, value: Any) -> str:
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, (list, tuple)):
        return ', '.join(str(v) for v in value)
    if key in MONEY_KEYS:
        try:
            return f'${float(value):,.0f}'
        except (TypeError, ValueError):
            return str(value)
    if key in INT_KEYS:
        try:
            return f'{int(float(value)):,}'
        except (TypeError, ValueError):
            return str(value)
    if key in PCT_KEYS:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        digits = 3 if key.startswith('ltc_spend_gdp_pct') else (2 if 'cagr' in key or key.endswith('prevalence_pct') else 1)
        return f'{number:.{digits}f}%'
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f'{value:,.1f}'
        return f'{value:,.2f}'.rstrip('0').rstrip('.') if value != int(value) else f'{int(value):,}'
    return str(value)


def _header(key: str) -> str:
    special = {
        'ltc_spend_gdp_pct': 'LTC % GDP', 'pop80_share_pct': '80+ share', 'pop80_share_2025_pct': '80+ 2025',
        'pop80_share_2050_pct': '80+ 2050', 'pop80_growth_to_2050_pct': '80+ growth to 2050',
        'beds_per_1000_65plus': 'Beds / 1,000 65+', 'workers_per_100_65plus': 'Workers / 100 65+',
        'nurse_hprd_typical': 'Nurse HPRD', 'rn_hprd_typical': 'RN HPRD', 'ebitdar_margin_pct': 'EBITDAR %',
        'tam_usd_bn': 'TAM $bn', 'sam_usd_bn': 'SAM $bn', 'som_usd_bn': 'SOM $bn',
        'tam_at_2025_gdp_usd_bn': 'TAM at 2025 GDP $bn', 'ltc_spend_at_2025_gdp_usd_bn': 'Spend at 2025 GDP $bn',
        'ltc_spend_usd_bn': 'Spend $bn', 'gdp_usd_bn': 'GDP $bn', 'nursing_care_bn': 'Nursing care $bn',
        'home_health_bn': 'Home health $bn', 'total_ltc_bn': 'Total $bn', 'revenue_bn': 'Revenue (bn)',
        'us_share_of_facilities_pct': 'US facilities %', 'cagr_since_prior_row_pct': 'CAGR since prior row',
        'cagr_since_first_survey_pct': 'CAGR since first survey', 'relative_to_semi_private': '× semi-private bed',
        'ltc_spend_2025_usd_bn': 'LTC spend 2025 $bn', 'income_to_claims_pct': 'Income / claims',
    }
    if key in special:
        return special[key]
    return key.replace('_pct', ' %').replace('_usd', ' $').replace('_', ' ').capitalize()


def _paragraph(text: Any, style):
    from reportlab.platypus import Paragraph
    return Paragraph(html.escape(str(text if text is not None else '')).replace('\n', '<br/>'), style)


def research_chart_size(usable_width: float) -> Tuple[float, float]:
    return usable_width, usable_width * 0.46


def _line_chart(rows: Sequence[Dict[str, Any]], series: Sequence[Tuple[str, str, str]], font: str, usable: float,
                x_key: str = 'year', y_label: str = '', unit: str = '', right_series: Sequence[Tuple[str, str, str]] = (),
                right_label: str = ''):
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors

    width, height = research_chart_size(usable)
    drawing = Drawing(width, height)
    left, right, top, bottom = 48.0, 48.0 if right_series else 14.0, 24.0, 26.0
    plot_w = width - left - right
    plot_h = height - top - bottom
    drawing.add(Rect(left, bottom, plot_w, plot_h, fillColor=colors.HexColor('#f7fafc'),
                     strokeColor=colors.HexColor('#e2e8f0'), strokeWidth=0.6))
    xs = [float(r.get(x_key) or 0) for r in rows]
    if len(xs) < 2 or xs[-1] == xs[0]:
        return drawing

    def _vals(key: str) -> List[float]:
        out = []
        for r in rows:
            try:
                out.append(float(r.get(key) or 0))
            except (TypeError, ValueError):
                out.append(0.0)
        return out

    left_max = max([v for key, _c, _l in series for v in _vals(key)] + [1e-9]) * 1.08
    right_max = max([v for key, _c, _l in right_series for v in _vals(key)] + [1e-9]) * 1.08 if right_series else 1.0
    x0, x1 = xs[0], xs[-1]

    def x_of(x: float) -> float:
        return left + (x - x0) / (x1 - x0) * plot_w

    def y_of(v: float, scale: float) -> float:
        return bottom + (v / scale) * plot_h

    for step in range(5):
        yy = bottom + plot_h * step / 4.0
        drawing.add(Line(left, yy, left + plot_w, yy, strokeColor=colors.HexColor('#e2e8f0'), strokeWidth=0.4))
        drawing.add(String(left - 4, yy - 2, f'{left_max * step / 4.0:,.0f}{unit}', fontName=font, fontSize=6,
                           fillColor=colors.HexColor('#0e2f63'), textAnchor='end'))
        if right_series:
            drawing.add(String(left + plot_w + 4, yy - 2, f'{right_max * step / 4.0:,.1f}', fontName=font, fontSize=6,
                               fillColor=colors.HexColor('#38a169'), textAnchor='start'))

    def _plot(items, scale):
        for key, color, _label in items:
            pts: List[float] = []
            for r, x in zip(rows, xs):
                try:
                    v = float(r.get(key) or 0)
                except (TypeError, ValueError):
                    v = 0.0
                pts.extend((x_of(x), y_of(v, scale)))
            drawing.add(PolyLine(pts, strokeColor=colors.HexColor(color), strokeWidth=1.5))

    _plot(series, left_max)
    _plot(right_series, right_max)

    for x in xs:
        if int(x) % 10 == 0 or x in (xs[0], xs[-1]):
            drawing.add(String(x_of(x), 8, f'{int(x)}', fontName=font, fontSize=6,
                               fillColor=colors.HexColor('#4a5568'), textAnchor='middle'))
    legend_x = left
    for key, color, label in list(series) + list(right_series):
        drawing.add(Rect(legend_x, height - 12, 8, 5, fillColor=colors.HexColor(color), strokeColor=None))
        drawing.add(String(legend_x + 11, height - 11, label, fontName=font, fontSize=6, fillColor=colors.HexColor('#2d3748')))
        legend_x += 11 + 4.2 * len(label) + 12
    if y_label:
        drawing.add(String(left, height - 22, y_label, fontName=font, fontSize=6.5, fillColor=colors.HexColor('#0e2f63')))
    if right_label:
        drawing.add(String(left + plot_w, height - 22, right_label, fontName=font, fontSize=6.5,
                           fillColor=colors.HexColor('#38a169'), textAnchor='end'))
    return drawing


def _bar_chart(rows: Sequence[Dict[str, Any]], font: str, usable: float):
    """TAM / SAM / SOM grouped bars for the total segment by milestone year."""
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors

    width, height = research_chart_size(usable)
    drawing = Drawing(width, height)
    left, right, top, bottom = 48.0, 14.0, 24.0, 26.0
    plot_w = width - left - right
    plot_h = height - top - bottom
    drawing.add(Rect(left, bottom, plot_w, plot_h, fillColor=colors.HexColor('#f7fafc'),
                     strokeColor=colors.HexColor('#e2e8f0'), strokeWidth=0.6))
    totals = [r for r in rows if r.get('segment') == 'total']
    if not totals:
        return drawing
    peak = max(float(r.get('tam_usd_bn') or 0) for r in totals) * 1.08 or 1.0
    group_w = plot_w / len(totals)
    bar_w = group_w / 4.0
    palette = (('tam_usd_bn', '#0e2f63', 'TAM'), ('sam_usd_bn', '#c9a04e', 'SAM'), ('som_usd_bn', '#4fd8ff', 'SOM'))
    for step in range(5):
        yy = bottom + plot_h * step / 4.0
        drawing.add(Line(left, yy, left + plot_w, yy, strokeColor=colors.HexColor('#e2e8f0'), strokeWidth=0.4))
        drawing.add(String(left - 4, yy - 2, f'{peak * step / 4.0:,.0f}', fontName=font, fontSize=6,
                           fillColor=colors.HexColor('#0e2f63'), textAnchor='end'))
    for i, r in enumerate(totals):
        gx = left + i * group_w + bar_w / 2.0
        for j, (key, color, _label) in enumerate(palette):
            v = float(r.get(key) or 0)
            h = plot_h * v / peak
            drawing.add(Rect(gx + j * bar_w, bottom, bar_w * 0.9, h, fillColor=colors.HexColor(color), strokeColor=None))
        drawing.add(String(gx + 1.5 * bar_w, 8, str(r.get('year')), fontName=font, fontSize=6,
                           fillColor=colors.HexColor('#4a5568'), textAnchor='middle'))
    legend_x = left
    for _key, color, label in palette:
        drawing.add(Rect(legend_x, height - 12, 8, 5, fillColor=colors.HexColor(color), strokeColor=None))
        drawing.add(String(legend_x + 11, height - 11, label, fontName=font, fontSize=6, fillColor=colors.HexColor('#2d3748')))
        legend_x += 40
    drawing.add(String(left, height - 22, 'Total LTC spend, $bn nominal (SOM on same scale)', fontName=font, fontSize=6.5,
                       fillColor=colors.HexColor('#0e2f63')))
    return drawing


def build_residential_research_pdf(pack: Dict[str, Any]) -> Tuple[str, bytes]:
    """Render the full study. Returns ``(filename, pdf_bytes)``."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, PageBreak, SimpleDocTemplate, Spacer

    title = pack.get('title') or STUDY_TITLE
    font, font_bold = _register_fonts()
    navy = colors.HexColor(PHINS_NAVY)
    gold = colors.HexColor(PHINS_GOLD)
    light = colors.HexColor(PHINS_WASH)

    buf = io.BytesIO()
    pagesize = A4
    usable = pagesize[0] - 24 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=24 * mm, bottomMargin=16 * mm, title=title, author=BRAND_NAME,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ResTitle', parent=styles['Title'], fontName=font_bold, fontSize=15,
                                 textColor=navy, alignment=0, leading=19, spaceAfter=4)
    h2 = ParagraphStyle('ResH2', parent=styles['Heading2'], fontName=font_bold, fontSize=12, textColor=navy,
                        leading=16, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle('ResBody', parent=styles['BodyText'], fontName=font, fontSize=9, leading=13,
                          textColor=colors.HexColor('#1A202C'))
    meta = ParagraphStyle('ResMeta', parent=body, fontSize=8, textColor=colors.HexColor('#4A5568'))
    cell = ParagraphStyle('ResCell', parent=body, fontSize=6.3, leading=8.2)
    cell_hdr = ParagraphStyle('ResCellHdr', parent=cell, fontName=font_bold, textColor=gold)
    source_style = ParagraphStyle('ResSource', parent=body, fontSize=8, leading=11)

    story: List[Any] = []
    story.append(_paragraph(title, title_style))
    story.append(_paragraph(BRAND_TAGLINE, meta))
    story.append(_paragraph(
        'Private institutions vs public institutions vs home care — statistics, standards, costs, workforce, '
        'accommodation, fifty years of market evolution and a fifty-year outlook, main OECD players, margins, '
        'SWOT, TAM/SAM/SOM and the care-sector hedge for a 3+ADL insurance book.', body))
    generated = pack.get('generated_at') or datetime.utcnow().isoformat()
    story.append(_paragraph(
        f"Generated: {generated}  ·  Study id: {pack.get('study_id') or STUDY_ID}  ·  Region: {pack.get('region_label')}"
        f"  ·  Scenario: {pack.get('scenario_label')}", meta))
    story.append(Spacer(1, 8))

    story.append(_paragraph('Methodology', h2))
    story.append(_paragraph(METHODOLOGY, body))
    story.append(Spacer(1, 6))

    story.append(_paragraph('Study narrative', h2))
    for para in pack.get('narrative') or []:
        story.append(_paragraph(para, body))
        story.append(Spacer(1, 3))

    story.append(_paragraph('Parameters', h2))
    params = pack.get('params') or {}
    param_labels = [
        ('region', 'Region'), ('scenario', 'Scenario'), ('forecast_end', 'Forecast end'),
        ('care_cost_inflation_pct', 'Care-cost inflation % / yr'), ('gdp_growth_pct', 'Nominal GDP growth % / yr'),
        ('healthy_ageing_pct', 'Healthy-ageing offset % / yr'), ('home_care_share_target_pct', 'Home-share target % (−1 = scenario default)'),
        ('lives', 'Lives in book'), ('age_min', 'Age min'), ('age_max', 'Age max'), ('ltc_annual_cover', 'LTC annual cover'),
        ('adl_threshold', 'ADL threshold'), ('hedge_capital', 'Hedge capital'), ('hedge_allocation', 'Hedge allocation preset'),
        ('incidence_stress_pct', 'Incidence stress %'), ('discount_rate_pct', 'Discount rate %'), ('som_share_pct', 'SOM share of SAM %'),
    ]
    param_rows = []
    for key, label in param_labels:
        value = params.get(key)
        if key in ('ltc_annual_cover', 'hedge_capital'):
            rendered = f'${float(value or 0):,.0f}'
        elif key == 'lives':
            rendered = f'{int(value or 0):,}'
        else:
            rendered = str(value)
        param_rows.append([label, rendered])
    story.append(_kv_table(param_rows, font, font_bold, navy, gold, light, cell, cell_hdr, usable * 0.62))

    story.append(_paragraph('Key figures', h2))
    kpis = pack.get('kpis') or {}
    kpi_labels = [
        ('region_ltc_spend_gdp_pct', 'Region LTC spend % GDP', 'pct'), ('region_public_share_pct', 'Public share of spend', 'pct'),
        ('region_residential_share_pct', 'Residential share of recipients', 'pct'), ('us_ltc_spend_2024_bn', 'US nursing + home health 2024 ($bn)', 'num'),
        ('us_nursing_home_residents_2025', 'US nursing-home residents 2025', 'int'), ('us_nursing_home_occupancy_2025_pct', 'US nursing-home occupancy 2025', 'pct'),
        ('oecd_ltc_spend_gdp_pct', 'OECD LTC spend % GDP (2023)', 'pct'), ('tam_2025_usd_bn', 'TAM 2025 ($bn)', 'num'),
        ('tam_end_usd_bn', f"TAM {kpis.get('end_year')} ($bn nominal)", 'num'), ('sam_end_usd_bn', f"SAM {kpis.get('end_year')} ($bn)", 'num'),
        ('som_end_usd_bn', f"SOM {kpis.get('end_year')} ($bn)", 'num'), ('ltc_spend_gdp_pct_end', f"LTC spend % GDP {kpis.get('end_year')}", 'pct3'),
        ('residential_demand_index_end', 'Residential demand index at end (2025 = 100)', 'num'), ('home_demand_index_end', 'Home demand index at end', 'num'),
        ('expected_annual_claims', 'Expected annual 3+ADL claims', 'money'), ('hedge_ratio_pct', 'Hedge income / claims', 'pct'),
        ('stress_offset_pct', 'Stress offset (income Δ / claims Δ)', 'pct'),
    ]
    kpi_rows = []
    for key, label, kind in kpi_labels:
        value = kpis.get(key)
        if value is None:
            rendered = '—'
        elif kind == 'pct':
            rendered = f'{float(value):.1f}%'
        elif kind == 'pct3':
            rendered = f'{float(value):.3f}%'
        elif kind == 'money':
            rendered = f'${float(value):,.0f}'
        elif kind == 'int':
            rendered = f'{int(value):,}'
        else:
            rendered = f'{float(value):,.1f}'
        kpi_rows.append([label, rendered])
    story.append(_kv_table(kpi_rows, font, font_bold, navy, gold, light, cell, cell_hdr, usable * 0.62))

    story.append(_paragraph('Hedge summary', h2))
    hedge = pack.get('hedge_summary') or {}
    hedge_rows = []
    for key, value in hedge.items():
        label = key.replace('_', ' ').capitalize()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if key.endswith('_pct'):
                rendered = f'{float(value):.2f}%'
            elif key in ('book_lives',):
                rendered = f'{int(value):,}'
            elif 'multiple' in key or 'beta' in key:
                rendered = f'{float(value):.2f}'
            else:
                rendered = f'${float(value):,.0f}'
        else:
            rendered = str(value)
        hedge_rows.append([label, rendered])
    story.append(_kv_table(hedge_rows, font, font_bold, navy, gold, light, cell, cell_hdr, usable * 0.62))

    tables = pack.get('tables') or {}
    story.append(PageBreak())
    story.append(_paragraph('Research charts', h2))
    spending = tables.get('spending_history') or []
    if spending:
        story.append(KeepTogether([
            _line_chart(spending, (('nursing_care_bn', '#0e2f63', 'Nursing care $bn'), ('home_health_bn', '#c9a04e', 'Home health $bn'),
                                   ('total_ltc_bn', '#4fd8ff', 'Total $bn')), font, usable, y_label='US LTC spend, $bn (CMS NHE)'),
            Spacer(1, 3),
            _paragraph('Chart 1 — US nursing care and home health spending 1970–2024 (CMS National Health Expenditure Accounts).', meta),
        ]))
        story.append(Spacer(1, 8))
    forecast = tables.get('demand_forecast') or []
    if forecast:
        story.append(KeepTogether([
            _line_chart(forecast, (('recipients_index', '#0e2f63', 'Recipients idx'), ('residential_demand_index', '#c9a04e', 'Residential idx'),
                                   ('home_demand_index', '#4fd8ff', 'Home idx')), font, usable, y_label='Demand index (2025 = 100)',
                        right_series=(('ltc_spend_gdp_pct', '#38a169', 'LTC % GDP'),), right_label='LTC spend % GDP'),
            Spacer(1, 3),
            _paragraph('Chart 2 — Demand indices and LTC spend as a share of GDP for the selected region and scenario (projection).', meta),
        ]))
        story.append(Spacer(1, 8))
    tam = tables.get('tam_sam_som') or []
    if tam:
        story.append(KeepTogether([
            _bar_chart(tam, font, usable),
            Spacer(1, 3),
            _paragraph('Chart 3 — TAM, SAM and SOM for total LTC spend by milestone year ($bn nominal).', meta),
        ]))

    for table_name, groups in PDF_TABLE_GROUPS.items():
        try:
            rows = extract_research_table(pack, table_name)
        except KeyError:
            continue
        if table_name in SAMPLED_TABLES:
            rows = [r for i, r in enumerate(rows) if int(r.get('year') or 0) % 5 == 0 or i == len(rows) - 1]
        story.append(PageBreak())
        story.append(_paragraph(TABLE_TITLES.get(table_name, table_name), h2))
        for index, columns in enumerate(groups):
            if index:
                story.append(Spacer(1, 8))
                story.append(_paragraph('(continued — further columns)', meta))
                story.append(Spacer(1, 3))
            story.append(_data_table(columns, rows, font, navy, gold, light, cell, cell_hdr, usable))

    story.append(PageBreak())
    story.append(_paragraph('Sources', h2))
    for item in pack.get('sources') or []:
        block = (
            f"[{item.get('id')}] {item.get('source')} (published {item.get('published_year', '—')}, "
            f"period {item.get('period_covered', '—')}). {item.get('headline_metric')} {item.get('relevance')} {item.get('url')}"
        )
        story.append(_paragraph(f'• {block}', source_style))
        story.append(Spacer(1, 3))

    story.append(Spacer(1, 8))
    story.append(_paragraph('Integrity', h2))
    integ = pack.get('integrity') or {}
    integ_rows = []
    for key, value in integ.items():
        if isinstance(value, bool):
            rendered = 'pass' if value else 'FAIL'
        elif isinstance(value, dict):
            rendered = ', '.join(f'{k}={v}' for k, v in value.items())
        elif isinstance(value, list):
            rendered = ', '.join(str(v) for v in value) or '—'
        else:
            rendered = str(value) if value not in (None, '') else '—'
        integ_rows.append([key.replace('_', ' '), rendered])
    story.append(_kv_table(integ_rows, font, font_bold, navy, gold, light, cell, cell_hdr, usable * 0.9))

    on_first, on_later = page_callbacks(
        pagesize, title=title, rtl=False, font=font, bold=font_bold, badge='Research & Audit',
        footer_note=f'{BRAND_NAME} — Confidential actuarial document · Research & Audit', page_label='Page',
    )
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    filename = f'phins-{STUDY_ID}-en.pdf'
    return filename, buf.getvalue()


def _kv_table(rows: List[List[str]], font: str, font_bold: str, navy, gold, light, cell, cell_hdr, width: float):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    data = [[_paragraph('Metric', cell_hdr), _paragraph('Value', cell_hdr)]]
    for label, value in rows:
        data.append([_paragraph(label, cell), _paragraph(value, cell)])
    table = Table(data, colWidths=[width * 0.48, width * 0.52], hAlign='LEFT', repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('BACKGROUND', (0, 1), (-1, -1), light),
        ('TEXTCOLOR', (0, 0), (-1, 0), gold),
        ('FONTNAME', (0, 0), (-1, 0), font_bold),
        ('FONTNAME', (0, 1), (-1, -1), font),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return table


_WIDE_COLUMNS = {
    'note', 'what_happened', 'lesson', 'item', 'rationale', 'description', 'financing_model', 'founding_statute',
    'key_reform', 'staffing_standard', 'quality_regime', 'accommodation_standard', 'direction', 'metric', 'label',
    'segment', 'ownership', 'setting_label', 'typical_acuity', 'title', 'era_note', 'theme',
}


def _data_table(columns: Sequence[str], rows: Iterable[Dict[str, Any]], font: str, navy, gold, light,
                cell, cell_hdr, usable: float):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    weights = [2.2 if col in _WIDE_COLUMNS else 1.0 for col in columns]
    total = sum(weights) or 1.0
    widths = [usable * (w / total) for w in weights]
    data = [[_paragraph(_header(col), cell_hdr) for col in columns]]
    for row in rows:
        data.append([_paragraph(_fmt(col, row.get(col)), cell) for col in columns])
    table = Table(data, colWidths=widths, hAlign='LEFT', repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('BACKGROUND', (0, 1), (-1, -1), light),
        ('TEXTCOLOR', (0, 0), (-1, 0), gold),
        ('FONTNAME', (0, 0), (-1, -1), font),
        ('FONTSIZE', (0, 0), (-1, -1), 6.3),
        ('GRID', (0, 0), (-1, -1), 0.2, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    return table


__all__ = ['build_residential_research_pdf', 'PDF_TABLE_GROUPS', 'TABLE_TITLES']
