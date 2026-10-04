"""
Tests for the new PHINS actuarial primitives:
- ReserveCalculator (IBNR, IFRS 17 BEL/RA/CSM, dividends/tax/reserves waterfall)
- apply_savings_allocation
- build_risk_reference (must reproduce the locked public model exactly)
- normalize_uploaded_rate_table (custom uploaded mortality/disability tables)

These tests are unit-style so they do not depend on the embedded HTTP server.
"""

from __future__ import annotations

import copy
import io
import json
import os
import threading
import time
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
from services.actuarial_service import (
    SimulationParams,
    ReserveCalculator,
    _coerce_reserve_config,
    apply_savings_allocation,
    build_risk_reference,
    curtate_life_expectancy,
    get_risk_reference_profile,
    resolve_reference_incidence,
    risk_reference_age_factor,
    risk_reference_monthly_premiums,
    risk_reference_query_kwargs,
    get_portfolio_simulator,
    get_actuarial_store,
    normalize_uploaded_rate_table,
    apply_uploaded_table_to_store,
)
from services.risk_reference_pdf import (
    render_risk_reference_pdf,
    risk_reference_document_hash,
)


def _tiny_simulation() -> dict:
    """Run a deterministic, small simulation that the reserve tests can rely on."""
    params = SimulationParams(
        customer_count=200,
        age_min=25, age_max=55, age_mean=40.0, age_std=8.0,
        coverage_min=100000, coverage_max=500000, coverage_median=200000,
        policy_term_mode='fixed', policy_term_fixed=10,
        savings_allocation_pct=0.0,
    )
    sim = get_portfolio_simulator().generate_portfolio(params)
    assert sim['portfolio_summary']['accepted_customers'] > 0
    return sim


def test_risk_reference_age_factor_anchors():
    """Anchor ages must exactly match the published curve."""
    from services.pricing_kernel import RISK_REFERENCE_V1_PARAMS as P
    assert risk_reference_age_factor(P['youth_anchor_age']) == P['youth_anchor_factor']
    assert risk_reference_age_factor(P['adult_anchor_age']) == P['adult_anchor_factor']
    # Core slope reaches expected value at age 65 (1.0 + 40*0.015 = 1.6)
    expected_65 = round(P['adult_anchor_factor'] + (65 - P['adult_anchor_age']) * P['core_slope'], 4)
    assert risk_reference_age_factor(65) == expected_65


def test_risk_reference_matches_published_anchors():
    """The locked 5-year reference forecast must remain deterministic and self-consistent."""
    ref = build_risk_reference()
    assert ref['source']['url'].endswith('fefferman.html')  # the locked public URL
    assert ref['profile_id'] == 'phins_published_v1'
    assert len(ref['yearly_projection']) == 5
    # The first row must hit the documented life-monthly premium for age 35
    age35 = risk_reference_monthly_premiums(35)
    assert age35['life_monthly'] > 0
    assert age35['disability_monthly'] > 0
    assert age35['annual_premium'] == ref['yearly_projection'][0]['annual_premium']
    # Cumulative premium reconciles to the sum of yearly premiums
    cum = sum(row['annual_premium'] for row in ref['yearly_projection'])
    assert abs(cum - ref['totals']['cumulative_premium']) < 0.5
    # Draft 3.1: disability continues at 65 with life stepped to face÷4
    age65 = risk_reference_monthly_premiums(65)
    assert age65['disability_monthly'] > 0
    assert age65['life_sum'] == 125000.0
    assert age65['disability_sum'] == 125000.0
    assert abs(age65['life_monthly'] - 50.0) < 0.01
    assert abs(age65['disability_monthly'] - 40.0) < 0.01
    # Integrity checks must all be True
    assert ref['data_integrity']['cumulative_premium_check']
    assert ref['data_integrity']['cumulative_loss_check']
    assert ref['data_integrity']['disability_sum_matches_age_band']


def test_risk_reference_is_modular_for_any_age_term_lifesum():
    """The risk reference must accept any starting age, term, and life sum."""
    # 10-year forecast starting at age 30 with a $1.5M life sum
    ref = build_risk_reference(start_age=30, projection_years=10, life_sum=1_500_000)
    assert ref['reference']['start_age'] == 30
    assert ref['reference']['projection_years'] == 10
    assert ref['reference']['life_sum'] == 1_500_000.0
    assert len(ref['yearly_projection']) == 10
    # Senior-curve sanity (Draft 3.1): from 65 life=face÷4 and disability continues at D=life
    senior_ref = build_risk_reference(start_age=65, projection_years=3)
    assert senior_ref['reference']['life_sum'] == 125000.0
    assert senior_ref['reference']['disability_sum'] == 125000.0
    for row in senior_ref['yearly_projection']:
        if row['age'] >= 65:
            assert row['life_sum'] == 125000.0
            assert row['disability_sum'] == 125000.0
            assert row['disability_monthly'] > 0
            assert row['disability_ix'] >= 0
    assert senior_ref['data_integrity']['disability_sum_matches_age_band']
    # Senior issue age must compare D to the post-65 share (1.0), not pre-65 0.25.
    assert senior_ref['data_integrity']['issue_age_disability_sum_matches_ratio'] is True
    assert ref['data_integrity']['cumulative_premium_check']
    assert ref['data_integrity']['cumulative_loss_check']


def test_risk_reference_cover_scales_with_chosen_face():
    """A non-default face reprices sums, premium, and expected loss.

    The published example stays $500,000. Doubling the cover doubles the
    attained-age sums. Premium and expected loss follow those sums. q(x)
    and i(x) stay on the age, and from age 65 life is one quarter of the face.
    """
    base = build_risk_reference(start_age=35, projection_years=1)
    doubled = build_risk_reference(start_age=35, projection_years=1, life_sum=1_000_000)
    base_row = base['yearly_projection'][0]
    doubled_row = doubled['yearly_projection'][0]
    assert base['reference']['face_amount'] == 500_000.0
    assert doubled['reference']['face_amount'] == 1_000_000.0
    assert doubled['reference']['life_sum'] == 1_000_000.0
    assert doubled['reference']['disability_sum'] == 250_000.0
    assert doubled_row['life_sum'] == base_row['life_sum'] * 2
    assert doubled_row['disability_sum'] == base_row['disability_sum'] * 2
    assert doubled_row['mortality_qx'] == base_row['mortality_qx']
    assert doubled_row['disability_ix'] == base_row['disability_ix']
    assert abs(doubled_row['annual_premium'] - base_row['annual_premium'] * 2) < 1.0
    assert abs(doubled_row['expected_loss'] - base_row['expected_loss'] * 2) < 0.05
    assert doubled['data_integrity']['disability_sum_matches_age_band'] is True
    assert doubled['data_integrity']['cumulative_premium_check'] is True
    assert doubled['data_integrity']['cumulative_loss_check'] is True

    senior_base = build_risk_reference(start_age=70, projection_years=1)
    senior = build_risk_reference(start_age=70, projection_years=1, life_sum=1_000_000)
    assert senior['reference']['face_amount'] == 1_000_000.0
    assert senior['reference']['life_sum'] == 250_000.0
    assert senior['reference']['disability_sum'] == 250_000.0
    senior_row = senior['yearly_projection'][0]
    senior_base_row = senior_base['yearly_projection'][0]
    assert senior_row['life_sum'] == 250_000.0
    assert senior_row['disability_sum'] == 250_000.0
    assert senior_row['life_sum'] == senior_base_row['life_sum'] * 2
    assert abs(senior_row['annual_premium'] - senior_base_row['annual_premium'] * 2) < 1.0
    assert abs(senior_row['expected_loss'] - senior_base_row['expected_loss'] * 2) < 0.05
    assert senior_row['mortality_qx'] == senior_base_row['mortality_qx']

    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dashboard = open(
        os.path.join(root, 'web_portal', 'static', 'actuary-dashboard.html'),
        encoding='utf-8',
    ).read()
    assert 'id="risk-ref-cover"' in dashboard
    assert 'Risk cover ($)' in dashboard
    assert 'id="risk-ref-life-sum"' in dashboard
    assert 'bindRiskCoverControls' in dashboard
    assert 'ref.reference.face_amount' in dashboard
    assert 'value="500000"' in dashboard


def test_curtate_life_expectancy_sums_survival_and_withholds():
    """e_x is the sum of survival probabilities. A hole in q(x) is withheld."""
    def flat(_age):
        return 0.1

    assert curtate_life_expectancy(40, flat, 42, 1.0) == round(0.9 + 0.81 + 0.729, 4)
    assert curtate_life_expectancy(40, flat, 42, 2.0) == round(0.8 + 0.64 + 0.512, 4)

    def hole(age):
        return None if age == 41 else 0.1

    assert curtate_life_expectancy(40, hole, 42, 1.0) is None
    assert curtate_life_expectancy(40, flat, None, 1.0) is None


def test_risk_reference_age_map_matches_tariff_and_disability_expectancy():
    """The age map is the one-year tariff. Disabled years are the ADL 3 study."""
    ref = build_risk_reference(start_age=35, projection_years=1)
    age_map = ref['age_map']
    assert age_map['face_amount'] == 500_000.0
    assert age_map['age_min'] == 20
    assert age_map['age_max'] == 85
    assert age_map['disability_adl'] == 10
    assert age_map['disability_mortality_multiplier'] == 1.8
    assert age_map['terminal_age'] == 119
    by_age = {row['age']: row for row in age_map['rows']}
    assert set(by_age) == set(range(20, 86))

    published = ref['yearly_projection'][0]
    row35 = by_age[35]
    assert row35['annual_premium'] == published['annual_premium']
    assert row35['expected_loss'] == published['expected_loss']
    assert row35['mortality_qx'] == 0.00133
    assert row35['disability_ix'] == 0.00450
    assert row35['rate_source'] == 'published_profile'

    row42 = by_age[42]
    one42 = build_risk_reference(start_age=42, projection_years=1)['yearly_projection'][0]
    assert row42['mortality_qx'] == 0.0025
    assert row42['disability_ix'] == 0.008
    assert row42['annual_premium'] == one42['annual_premium']
    assert row42['expected_loss'] == one42['expected_loss']
    assert row42['rate_source'] == 'kernel_table'

    premium65 = risk_reference_monthly_premiums(65)
    assert by_age[65]['annual_premium'] == premium65['annual_premium']
    assert abs(premium65['life_monthly'] - 50.0) < 0.01
    assert abs(premium65['disability_monthly'] - 40.0) < 0.01
    assert by_age[65]['life_sum'] == 125000.0
    assert by_age[64]['life_sum'] == 500000.0

    row70 = by_age[70]
    one70 = build_risk_reference(start_age=70, projection_years=1)['yearly_projection'][0]
    assert row70['expected_loss'] == one70['expected_loss']
    assert row70['annual_premium'] == one70['annual_premium']
    assert row70['life_sum'] == 125000.0
    assert row70['disability_sum'] == 125000.0

    profile = get_risk_reference_profile()
    tables = get_actuarial_store().get_current_tables()
    mort = list(tables.get('mortality_rates') or [])
    dis = list(tables.get('disability_incidence_rates') or [])

    def qx_at(age):
        return resolve_reference_incidence(age, profile, mort, dis)['mortality_qx']

    assert row70['healthy_curtate_expectancy'] == curtate_life_expectancy(
        70, qx_at, age_map['terminal_age'], 1.0
    )
    # Plotted disability years are the published research average, not q×1.80.
    assert row70['disability_curtate_expectancy'] == 4.912557052
    assert row70['male_years'] == 4.17
    assert row70['female_years'] == 5.66
    assert row70['female_excess_pct'] == 36
    assert row70['pricing_basis_disabled_curtate'] == curtate_life_expectancy(
        70, qx_at, age_map['terminal_age'], 1.8
    )
    assert row35['disability_curtate_expectancy'] == 5.248615017
    assert row35['male_years'] == 4.95
    assert row35['female_years'] == 5.54
    assert row35['pricing_basis_disabled_curtate'] == curtate_life_expectancy(
        35, qx_at, age_map['terminal_age'], 1.8
    )
    assert abs(row35['disability_curtate_expectancy'] - ((4.95 + 5.54) / 2)) > 1e-6
    assert row70['disability_curtate_expectancy'] < row70['healthy_curtate_expectancy']
    assert row35['pricing_basis_disabled_curtate'] != row35['disability_curtate_expectancy']
    assert all(flag is True for flag in age_map['data_integrity'].values())

    doubled = build_risk_reference(start_age=35, projection_years=1, life_sum=1_000_000)
    d35 = {row['age']: row for row in doubled['age_map']['rows']}[35]
    assert abs(d35['annual_premium'] - row35['annual_premium'] * 2) < 1.0
    assert abs(d35['expected_loss'] - row35['expected_loss'] * 2) < 0.05
    assert d35['mortality_qx'] == row35['mortality_qx']
    assert d35['disability_ix'] == row35['disability_ix']
    assert d35['healthy_curtate_expectancy'] == row35['healthy_curtate_expectancy']
    assert d35['disability_curtate_expectancy'] == row35['disability_curtate_expectancy']
    assert d35['male_years'] == row35['male_years']
    assert d35['female_years'] == row35['female_years']
    assert d35['pricing_basis_disabled_curtate'] == row35['pricing_basis_disabled_curtate']

    saved = list(tables.get('mortality_rates') or [])
    try:
        tables['mortality_rates'] = [{'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.5}]
        broken = build_risk_reference(start_age=42, projection_years=1)['age_map']['rows']
        broken_by_age = {row['age']: row for row in broken}
        assert broken_by_age[42]['mortality_qx'] is None
        assert broken_by_age[42]['expected_loss'] is None
        assert broken_by_age[42]['healthy_curtate_expectancy'] is None
        assert broken_by_age[42]['pricing_basis_disabled_curtate'] is None
        # Research years do not depend on q(x). A missing kernel rate withholds
        # the loss, not the published expectancy.
        assert broken_by_age[42]['disability_curtate_expectancy'] is not None
        assert broken_by_age[35]['mortality_qx'] == 0.00133
        assert broken_by_age[35]['healthy_curtate_expectancy'] is None
        assert broken_by_age[35]['disability_curtate_expectancy'] == 5.248615017
    finally:
        tables['mortality_rates'] = saved

    saved_research = tables.get('adl3_disabled_life_expectancy')
    try:
        tables['adl3_disabled_life_expectancy'] = [
            row for row in (saved_research or []) if int(row.get('age')) != 50
        ]
        holed = {
            row['age']: row
            for row in build_risk_reference(start_age=35, projection_years=1)['age_map']['rows']
        }
        assert holed[50]['disability_curtate_expectancy'] is None
        assert holed[50]['male_years'] is None
        assert holed[50]['expected_loss'] == by_age[50]['expected_loss']
        assert holed[35]['annual_premium'] == row35['annual_premium']
        assert holed[35]['mortality_qx'] == 0.00133
        del tables['adl3_disabled_life_expectancy']
        filled = {
            row['age']: row
            for row in build_risk_reference(start_age=35, projection_years=1)['age_map']['rows']
        }
        assert filled[50]['disability_curtate_expectancy'] == by_age[50]['disability_curtate_expectancy']
    finally:
        if saved_research is None:
            tables.pop('adl3_disabled_life_expectancy', None)
        else:
            tables['adl3_disabled_life_expectancy'] = saved_research

    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dashboard = open(
        os.path.join(root, 'web_portal', 'static', 'actuary-dashboard.html'),
        encoding='utf-8',
    ).read()
    assert 'id="rr-chart-loss"' in dashboard
    assert 'id="rr-chart-prob"' in dashboard
    assert 'id="rr-chart-le"' in dashboard
    assert 'drawRiskReferenceCharts' in dashboard
    assert 'healthy_curtate_expectancy' in dashboard
    assert 'disability_curtate_expectancy' in dashboard
    assert 'Research average years after ADL 3' in dashboard
    assert 'adl3_disabled_life_expectancy' in dashboard


def test_risk_reference_kernel_rates_cover_any_age():
    """Published ages stay locked. Every other covered age uses the kernel bracket.

    The age curve is not applied a second time. An age outside every bracket
    is withheld instead of printed as a zero loss.
    """
    store = get_actuarial_store()
    tables = store.get_current_tables()
    saved_m = list(tables.get('mortality_rates') or [])
    saved_d = list(tables.get('disability_incidence_rates') or [])
    default_m = [
        {'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.5},
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.2},
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 2.5},
        {'age_min': 50, 'age_max': 60, 'rate_per_1000': 5.0},
        {'age_min': 60, 'age_max': 70, 'rate_per_1000': 12.0},
        {'age_min': 70, 'age_max': 80, 'rate_per_1000': 30.0},
        {'age_min': 80, 'age_max': 120, 'rate_per_1000': 75.0},
    ]
    default_d = [
        {'age_min': 0, 'age_max': 30, 'rate_per_1000': 2.0},
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 4.0},
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 8.0},
        {'age_min': 50, 'age_max': 60, 'rate_per_1000': 15.0},
        {'age_min': 60, 'age_max': 70, 'rate_per_1000': 30.0},
        {'age_min': 70, 'age_max': 80, 'rate_per_1000': 50.0},
        {'age_min': 80, 'age_max': 120, 'rate_per_1000': 80.0},
    ]
    locked_q = {35: 0.00133, 36: 0.00141, 37: 0.00150, 38: 0.00160, 39: 0.00171}
    locked_i = {35: 0.00450, 36: 0.00468, 37: 0.00487, 38: 0.00507, 39: 0.00528}
    try:
        tables['mortality_rates'] = default_m
        tables['disability_incidence_rates'] = default_d

        published = build_risk_reference()
        for row in published['yearly_projection']:
            assert row['mortality_qx'] == locked_q[row['age']]
            assert row['disability_ix'] == locked_i[row['age']]
            assert row['rate_source'] == 'published_profile'
            assert row['expected_loss'] > 0
        assert published['data_integrity']['published_ages_match_locked_profile'] is True
        assert published['data_integrity']['rates_resolved_for_every_age'] is True
        assert published['data_integrity']['kernel_rates_match_bracket_identity'] is True

        mixed = build_risk_reference(start_age=30, projection_years=10)
        for row in mixed['yearly_projection']:
            if row['age'] < 35:
                assert row['rate_source'] == 'kernel_table'
                assert row['mortality_qx'] == 0.0012
                assert row['disability_ix'] == 0.0040
            else:
                assert row['rate_source'] == 'published_profile'
                assert row['mortality_qx'] == locked_q[row['age']]
        assert mixed['data_integrity']['kernel_rates_match_bracket_identity'] is True
        assert mixed['data_integrity']['rates_resolved_for_every_age'] is True

        age42 = build_risk_reference(start_age=42, projection_years=1)['yearly_projection'][0]
        premium42 = risk_reference_monthly_premiums(42)
        assert age42['mortality_qx'] == 0.0025
        assert age42['disability_ix'] == 0.008
        assert age42['rate_source'] == 'kernel_table'
        assert age42['annual_premium'] == premium42['annual_premium']
        assert abs(age42['mortality_qx'] - 0.0025 * premium42['age_factor']) > 1e-6
        assert age42['life_sum'] == premium42['life_sum']
        assert age42['disability_sum'] == premium42['disability_sum']
        assert age42['expected_loss'] == round(
            0.0025 * age42['life_sum'] + 0.008 * age42['disability_sum'] * 0.55, 2
        )

        age70 = build_risk_reference(start_age=70, projection_years=1)['yearly_projection'][0]
        premium70 = risk_reference_monthly_premiums(70)
        assert age70['mortality_qx'] == 0.030
        assert age70['disability_ix'] == 0.050
        assert age70['life_sum'] == premium70['life_sum']
        assert age70['disability_sum'] == premium70['disability_sum']
        assert age70['life_monthly'] == premium70['life_monthly']
        assert age70['expected_loss'] == round(
            0.030 * age70['life_sum'] + 0.050 * age70['disability_sum'] * 0.55, 2
        )

        tables['mortality_rates'] = [{'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.5}]
        missing = build_risk_reference(start_age=42, projection_years=1)
        row = missing['yearly_projection'][0]
        assert row['mortality_qx'] is None
        assert row['mortality_rate_source'] == 'unavailable'
        assert row['expected_loss'] is None
        assert row['loss_ratio'] is None
        assert missing['data_integrity']['rates_resolved_for_every_age'] is False
        assert missing['data_integrity']['cumulative_loss_check'] is False
        assert missing['totals']['cumulative_expected_loss'] is None
        still = build_risk_reference(start_age=35, projection_years=1)['yearly_projection'][0]
        assert still['mortality_qx'] == 0.00133
        assert still['rate_source'] == 'published_profile'
        assert still['expected_loss'] is not None
    finally:
        tables['mortality_rates'] = saved_m
        tables['disability_incidence_rates'] = saved_d


def _pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


def test_risk_reference_pdf_restates_the_forecast_and_hash():
    """The PDF copies the forecast. A missing loss is withheld, not zero."""
    ref = build_risk_reference(start_age=35, projection_years=5, life_sum=500_000)
    digest = risk_reference_document_hash(ref)
    assert digest == risk_reference_document_hash(copy.deepcopy(ref))
    filename, pdf = render_risk_reference_pdf(ref)
    assert filename == 'phins-risk-reference.pdf'
    assert pdf.startswith(b'%PDF')
    text = _pdf_text(pdf)
    flat = ''.join(text.split())
    assert digest in flat
    assert '$2,070.00' in text
    assert '$974.38' in text
    assert '5.25' in text
    assert '$1,248.75' in text
    assert '4.91' in text
    assert '38.92' not in text
    assert 'published ADL 3' in text
    assert 'PASS' in text
    from pypdf import PdfReader
    assert PdfReader(io.BytesIO(pdf)).metadata.subject == digest

    doubled = build_risk_reference(start_age=35, projection_years=5, life_sum=1_000_000)
    doubled_hash = risk_reference_document_hash(doubled)
    assert doubled_hash != digest
    _name, doubled_pdf = render_risk_reference_pdf(doubled)
    doubled_text = _pdf_text(doubled_pdf)
    assert '$4,140.00' in doubled_text
    assert '5.25' in doubled_text
    assert '4.91' in doubled_text
    assert '38.92' not in doubled_text
    assert doubled_hash in ''.join(doubled_text.split())

    withheld = copy.deepcopy(ref)
    withheld['yearly_projection'][0]['expected_loss'] = None
    withheld['yearly_projection'][0]['mortality_qx'] = None
    withheld['yearly_projection'][0]['loss_ratio'] = None
    withheld['totals']['cumulative_expected_loss'] = None
    withheld['totals']['average_loss_ratio'] = None
    for row in withheld['age_map']['rows']:
        if row['age'] == 35:
            row['expected_loss'] = None
            row['mortality_qx'] = None
    _name, gap_pdf = render_risk_reference_pdf(withheld)
    gap_text = _pdf_text(gap_pdf)
    assert 'withheld' in gap_text
    assert '$974.38' not in gap_text
    assert '$0.00' not in gap_text
    assert risk_reference_document_hash(withheld) != digest

    saved = build_risk_reference(start_age=35, projection_years=5, savings_rate=0.1)
    savings_pdf_text = _pdf_text(render_risk_reference_pdf(saved)[1])
    assert 'Savings accumulation' in savings_pdf_text
    assert risk_reference_document_hash(saved) != digest

    kwargs = risk_reference_query_kwargs({
        'start_age': ['35'],
        'projection_years': ['5'],
        'life_sum': ['1000000'],
        'savings_rate': [''],
    })
    assert kwargs['life_sum'] == 1_000_000.0
    assert kwargs['savings_rate'] is None
    assert kwargs['start_age'] == 35

    dashboard = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'web_portal', 'static', 'actuary-dashboard.html',
    )
    html = open(dashboard, encoding='utf-8').read()
    assert 'downloadRiskReferencePdf' in html
    assert 'riskReferenceQuery' in html
    assert 'id="risk-ref-download-pdf"' in html


def test_presentation_rates_match_kernel_brackets():
    """Fefferman and Goldsobel share the same lookup as the kernel brackets."""
    import os
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, 'web_portal', 'static', 'risk-reference-rates.js')
    node = r'''
const fs = require('fs');
const vm = require('vm');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const rates = sandbox.window.phinsReferenceRates;
const model = {
  mortality: { 35: 0.00133, 36: 0.00141, 37: 0.00150, 38: 0.00160, 39: 0.00171 },
  disabilityIncidence: { 35: 0.00450, 36: 0.00468, 37: 0.00487, 38: 0.00507, 39: 0.00528 },
};
process.stdout.write(JSON.stringify({
  a35: rates(35, model),
  a42: rates(42, model),
  a70: rates(70, model),
  a200: rates(200, model),
}));
'''
    proc = subprocess.run(
        ['node', '-e', node, script],
        check=True, capture_output=True, text=True,
    )
    out = json.loads(proc.stdout)
    assert out['a35']['qx'] == 0.00133
    assert out['a35']['ix'] == 0.00450
    assert out['a35']['source'] == 'published_profile'
    assert out['a42']['qx'] == 0.0025
    assert out['a42']['ix'] == 0.008
    assert out['a42']['source'] == 'kernel_table'
    assert out['a70']['qx'] == 0.030
    assert out['a70']['ix'] == 0.050
    assert out['a200']['qx'] is None
    assert out['a200']['source'] == 'unavailable'
    for fname in (
        'phins-risk-1pager-fefferman.html',
        'phins-risk-1pager-goldsobel.html',
    ):
        html = open(os.path.join(root, 'web_portal', 'static', fname), encoding='utf-8').read()
        assert '/risk-reference-rates.js' in html
        assert 'phinsReferenceRates' in html
        assert 'never shown as zero' in html


def test_reserve_calculator_waterfall_consistency():
    sim = _tiny_simulation()
    cfg = _coerce_reserve_config({
        'dividends_pct': 0.30,
        'tax_pct': 0.23,
        'ibnr_pct': 0.12,
        'reserve_contribution_pct': 0.40,
        'risk_adjustment_pct': 0.06,
        'projection_years': 5,
        'initial_reserve': 0.0,
        'savings_allocation_pct': 0.10,
        'savings_yield_pct': 0.04,
    })

    projection = ReserveCalculator().project(sim, cfg)
    yearly = projection['yearly_projection']
    assert len(yearly) == cfg.projection_years

    for row in yearly:
        # Operating profit = tax + after-tax profit (within rounding)
        assert abs(row['operating_profit'] - (row['tax'] + row['after_tax_profit'])) < 0.5
        # Dividends + retained = after-tax profit (within rounding)
        assert abs(row['after_tax_profit'] - (row['dividends'] + row['retained_earnings'])) < 0.5
        # CSM balance cannot be negative
        assert row['ifrs17']['csm_balance'] >= -0.5
        # IBNR is non-negative
        assert row['ibnr_provision'] >= -0.5
        # In-force factor monotonically decreases
        assert 0.0 <= row['in_force_factor'] <= 1.0

    # In-force factor decays year over year
    factors = [row['in_force_factor'] for row in yearly]
    assert factors == sorted(factors, reverse=True)

    assert projection['data_integrity']['profit_waterfall_consistent']
    assert projection['data_integrity']['csm_non_negative']
    assert projection['data_integrity']['savings_balance_non_negative']
    for flag in (
        'bel_rollforward_holds',
        'ra_equals_pct_of_bel',
        'reserve_delta_equals_retained_share',
        'undistributed_earnings_explain_reserve_gap',
        'savings_net_change_rolls_forward',
        'ibnr_equals_pct_of_claims',
        'operating_profit_bridge_holds',
        'loss_component_rolls_forward',
        'csm_per_year_continuity_holds',
        'csm_sum_reconciles_to_opening',
    ):
        assert projection['data_integrity'][flag] is True, flag

    # Closing reserve is the running sum of Reserve Δ, and the CSM column
    # moves by the net change (accretion − release), not by a linear runoff.
    running_reserve = cfg.initial_reserve
    running_csm = projection['opening_balances']['csm']
    running_savings = cfg.initial_savings_fund_balance
    for row in yearly:
        running_reserve = round(running_reserve + row['reserve_contribution'], 2)
        assert abs(running_reserve - row['closing_reserve']) < 1.0
        running_csm = round(running_csm + row['ifrs17']['csm_net_change'], 2)
        assert abs(running_csm - row['ifrs17']['csm_balance']) < 1.0
        running_savings = round(running_savings + row['savings_fund']['net_change'], 2)
        assert abs(running_savings - row['savings_fund']['closing_balance']) < 1.0
        assert abs(
            row['ifrs17']['bel_opening'] * (1.0 + projection['discount_rate'])
            - row['in_force_expected_claims']
            - row['ifrs17']['bel_balance']
        ) < 1.0


def test_reserve_calculator_zero_savings_disables_growth():
    sim = _tiny_simulation()
    cfg = _coerce_reserve_config({'savings_allocation_pct': 0.0, 'savings_yield_pct': 0.0,
                                  'projection_years': 3})
    projection = ReserveCalculator().project(sim, cfg)
    final_balance = projection['totals']['closing_savings_balance']
    assert final_balance == 0.0


def test_apply_savings_allocation_reconciles():
    sim = _tiny_simulation()
    allocation = apply_savings_allocation(sim, 0.40)
    integrity = allocation['data_integrity']
    assert integrity['gross_premium_reconciles']
    assert abs(integrity['sum_of_shares'] - 1.0) < 1e-6
    assert allocation['savings_allocation_pct'] == 40.0


def test_normalize_uploaded_rate_table_handles_qx_probabilities():
    rows = [
        {'age_min': 30, 'age_max': 40, 'qx': 0.00141},  # raw probability < 0.5 -> per-1000
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 8.0},
        {'invalid': 'row'},  # should be skipped
        {'Age Min': 50, 'Age Max': 60, 'Rate Per 1000': 15.0},  # case-insensitive headers
    ]
    out = normalize_uploaded_rate_table('mortality_rates', rows)
    assert out['valid'] is True
    assert out['rows_normalized'] == 3
    assert out['rows_skipped'] == 1
    # qx 0.00141 -> 1.41 per 1000
    assert out['normalized'][0] == {'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.41}


def test_normalize_uploaded_rate_table_rejects_unsupported_type():
    out = normalize_uploaded_rate_table('pricing', [{'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.0}])
    assert out['valid'] is False
    assert out['reason'] == 'unsupported_table_type'


def test_apply_uploaded_table_to_store_round_trip():
    store = get_actuarial_store()
    new_table = [
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 0.9},
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 2.0},
    ]
    try:
        result = apply_uploaded_table_to_store('mortality_rates', new_table, user='pytest')
        assert result.get('success') is True
        # Round-trip: rate at age 35 must come from the new table
        rate = store.get_mortality_rate(35)
        assert abs(rate - (0.9 / 1000.0)) < 1e-9
    finally:
        # The store is a process-wide singleton shared with every later test
        # (pricing kernel, simulator, reserves). Leaving a two-band table in
        # place zeroes mortality above age 50 and silently changes their
        # numbers, so put the default table back.
        store.reset_tables_to_default('mortality_rates', user='pytest')
    assert abs(store.get_mortality_rate(35) - (1.2 / 1000.0)) < 1e-9


# ----------------------------------------------------------------------------
# HTTP integration test for the new endpoints
# ----------------------------------------------------------------------------

class _ServerThread(threading.Thread):
    def __init__(self, port: int = 0):
        super().__init__(daemon=True)
        # Port 0 -> kernel-assigned free port, published as ``self.port``.
        self.httpd = HTTPServer(('127.0.0.1', port), portal.PortalHandler)
        self.port = self.httpd.server_address[1]

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _post_json(url: str, payload: dict, token: str | None = None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urlopen(req) as resp:
        return resp.read(), resp.status, dict(resp.getheaders())


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read(), resp.status, dict(resp.getheaders())


def test_risk_reference_pdf_route_matches_the_json_forecast():
    """The download uses the same query as the JSON forecast."""
    srv = _ServerThread()
    srv.start()
    try:
        time.sleep(0.2)
        base = f'http://127.0.0.1:{srv.port}'
        login_body, _, _ = _post_json(base + '/api/login', {
            'username': 'admin', 'password': 'admin123',
        })
        token = json.loads(login_body)['token']
        query = 'start_age=35&projection_years=5&life_sum=500000'
        json_body, status, _ = _get(base + '/api/actuarial/risk-reference?' + query, token)
        assert status == 200
        reference = json.loads(json_body)['reference']
        pdf_body, status, headers = _get(base + '/api/actuarial/risk-reference/pdf?' + query, token)
        assert status == 200
        assert pdf_body.startswith(b'%PDF')
        header_map = {key.lower(): value for key, value in headers.items()}
        assert header_map['content-type'] == 'application/pdf'
        assert 'phins-risk-reference.pdf' in header_map['content-disposition']
        assert header_map['x-phins-risk-reference-hash'] == risk_reference_document_hash(reference)
        assert header_map['cache-control'] == 'no-store'
        try:
            _get(base + '/api/actuarial/risk-reference/pdf?' + query)
            raise AssertionError('anonymous download should be refused')
        except HTTPError as exc:
            assert exc.code == 403
            assert json.loads(exc.read())['error']
    finally:
        srv.stop()


def test_actuarial_endpoints_end_to_end(tmp_path):
    srv = _ServerThread()
    port = srv.port
    srv.start()
    try:
        time.sleep(0.3)
        base = f'http://127.0.0.1:{port}'

        login_body, _, _ = _post_json(base + '/api/login', {
            'username': 'admin', 'password': 'admin123'
        })
        admin_token = json.loads(login_body)['token']

        # 1) Risk Reference must be reachable, deterministic, and modular
        body, status, _ = _get(base + '/api/actuarial/risk-reference', admin_token)
        assert status == 200
        ref = json.loads(body)['reference']
        assert ref['source']['url'].endswith('fefferman.html')
        assert ref['profile_id'] == 'phins_published_v1'
        assert len(ref['yearly_projection']) == 5

        # Modular: 10-year horizon, custom life sum, must still pass integrity
        body, status, _ = _get(
            base
            + '/api/actuarial/risk-reference?projection_years=10&start_age=30&life_sum=1500000',
            admin_token,
        )
        assert status == 200
        modular = json.loads(body)['reference']
        assert modular['reference']['projection_years'] == 10
        assert modular['reference']['start_age'] == 30
        assert modular['reference']['life_sum'] == 1_500_000.0
        assert modular['data_integrity']['cumulative_premium_check']

        # Backwards-compatibility: the deprecated path still works and returns
        # a deprecation notice in the JSON body.
        body, status, _ = _get(base + '/api/actuarial/fefferman-reference', admin_token)
        assert status == 200
        alias_payload = json.loads(body)
        assert alias_payload['reference']['profile_id'] == 'phins_published_v1'
        assert 'deprecated' in alias_payload

        # 7) Cross-system reconciler must pass for a freshly run simulation
        body, status, _ = _post_json(base + '/api/actuarial/simulate', {
            'customer_count': 50, 'age_min': 25, 'age_max': 50,
            'policy_term_mode': 'fixed', 'policy_term_fixed': 12,
        }, admin_token)
        assert status == 200
        recon_sim_id = json.loads(body)['simulation']['simulation_id']
        body, status, _ = _post_json(base + '/api/actuarial/reconcile', {
            'simulation_id': recon_sim_id,
        }, admin_token)
        assert status == 200
        rec = json.loads(body)['reconciliation']
        assert rec['reconciled'] is True
        assert abs(rec['portfolio_reconciliation']['delta']) < 1.0

        # 8) Reserve projection without projection_years should default the
        # horizon from the policy book (G7)
        body, status, _ = _post_json(base + '/api/actuarial/reserves/project', {
            'simulation_id': recon_sim_id,
        }, admin_token)
        assert status == 200
        auto_horizon = json.loads(body)['projection']
        # Fixed-term simulation -> projection_years equals the fixed policy term
        assert auto_horizon['projection_years'] == 12

        # 9) Canonical contract specification must be reachable + locked
        body, status, _ = _get(base + '/api/actuarial/contract-spec', admin_token)
        assert status == 200
        contract = json.loads(body)['contract']
        assert contract['product_id'] == 'phins_pure_risk_adjustable'
        # The contract draft mandates exactly these covered risks in order
        risk_factors = [r['risk_factor'] for r in contract['covered_risks']]
        assert 'Death — natural or accidental' in risk_factors[0]
        assert 'Permanent total disability' in risk_factors[1]
        assert 'Long-term loss of earning capacity' in risk_factors[2]
        assert contract['savings_addon']['formula'] == 'risk_premium_markup'

        # 10) End-to-end markup flow: 300% savings on top of risk premium
        body, status, _ = _post_json(base + '/api/actuarial/simulate', {
            'customer_count': 60, 'age_min': 30, 'age_max': 50,
            'policy_term_mode': 'fixed', 'policy_term_fixed': 15,
            'savings_rate': 3.0,  # 300% of risk premium per the user's brief
            'savings_formula': 'risk_premium_markup',
            'product_id': 'phins_pure_risk_adjustable',
        }, admin_token)
        assert status == 200
        markup_sim = json.loads(body)['simulation']
        rp = markup_sim['profitability']['risk_premium']
        sp = markup_sim['profitability']['savings_premium']
        assert abs(sp - 3.0 * rp) < 1.0, (sp, rp)
        assert markup_sim['profitability']['components_match']
        assert markup_sim['pricing_kernel']['savings_formula'] == 'risk_premium_markup'
        assert markup_sim['pricing_kernel']['savings_rate'] == 3.0
        assert markup_sim['pricing_kernel']['product_id'] == 'phins_pure_risk_adjustable'
        # Premium reconciliation block must report all identities passing
        assert markup_sim['premium_reconciliation']['all_identities_pass'] is True

        # 11.5) Contract ratio adjustable from the actuary table: setting
        # POST /api/actuarial/config { disability_share_of_life } must flow
        # through to every priced simulation customer + the risk reference.
        body, status, _ = _post_json(base + '/api/actuarial/config', {
            'disability_share_of_life': 0.20,  # 1:5 contract
        }, admin_token)
        assert status == 200

        body, status, _ = _get(base + '/api/actuarial/config', admin_token)
        assert json.loads(body)['config']['disability_share_of_life'] == 0.20

        body, status, _ = _post_json(base + '/api/actuarial/simulate', {
            'customer_count': 40, 'age_min': 30, 'age_max': 50,
            'policy_term_mode': 'fixed', 'policy_term_fixed': 10,
        }, admin_token)
        assert status == 200
        cfg_sim = json.loads(body)['simulation']
        assert cfg_sim['pricing_kernel']['disability_share_of_life'] == 0.20

        body, status, _ = _get(base + '/api/actuarial/risk-reference', admin_token)
        assert status == 200
        cfg_ref = json.loads(body)['reference']['reference']
        assert cfg_ref['disability_share_of_life'] == 0.20
        assert cfg_ref['disability_to_life_ratio_display'] == '1:5'

        body, status, _ = _get(base + '/api/actuarial/contract-spec', admin_token)
        assert status == 200
        ratios = json.loads(body)['contract']['contract_ratios']
        assert ratios['disability_share_of_life'] == 0.20
        assert ratios['adjustable_from_dashboard'] is True

        # Restore the default 0.25 for downstream subtests
        _post_json(base + '/api/actuarial/config', {
            'disability_share_of_life': 0.25,
        }, admin_token)

        # 11.7) Portfolio Valuation endpoint: best estimate vs conservative
        # for Insurance, Risk Portfolio and Company (PHINS Technologies)
        body, status, _ = _post_json(base + '/api/actuarial/simulate', {
            'customer_count': 80, 'age_min': 30, 'age_max': 55,
            'policy_term_mode': 'fixed', 'policy_term_fixed': 15,
            'savings_rate': 1.0,
        }, admin_token)
        assert status == 200
        val_sim = json.loads(body)['simulation']
        body, status, _ = _post_json(base + '/api/actuarial/valuation', {
            'simulation_id': val_sim['simulation_id'],
            'prudence_margin_pct': 0.15,
            'tech_multiplier': 4.0,
            'tech_revenue_share_pct': 0.10,
            'savings_aum_value_pct': 0.10,
            'projection_years': 10,
            'new_business_value_per_year': 1_000_000,
        }, admin_token)
        assert status == 200
        valuation = json.loads(body)['valuation']
        bands = valuation['bands']
        assert bands['insurance_portfolio']['best_estimate'] >= bands['insurance_portfolio']['conservative']
        assert bands['risk_portfolio']['conservative'] >= bands['risk_portfolio']['best_estimate']
        for k, v in valuation['data_integrity'].items():
            assert v is True, (k, v)
        assert len(valuation['integrity_hash']) == 16
        # Excel + PDF reports must now include valuation + savings sheets
        body, status, headers = _post_json(base + '/api/actuarial/reports/export', {
            'simulation_id': val_sim['simulation_id'],
            'format': 'xlsx',
            'valuation_config': {'tech_multiplier': 4.0},
        }, admin_token)
        assert status == 200
        assert body[:2] == b'PK'
        assert len(body) > 5000  # the workbook should now be bigger with new sheets

        # 11) Legacy UI fallback: callers that still send the old
        # 'savings_allocation_pct' field (e.g. cached/old dashboards) and
        # no explicit savings_rate must now ALSO get a priced savings
        # premium under the canonical markup formula. This is the fix for
        # the user's bug report ("putting any number on Savings Allocation
        # makes no calculation for savings").
        body, status, _ = _post_json(base + '/api/actuarial/simulate', {
            'customer_count': 50, 'age_min': 30, 'age_max': 50,
            'policy_term_mode': 'fixed', 'policy_term_fixed': 12,
            'savings_allocation_pct': 100,  # 100% as a legacy percentage value
        }, admin_token)
        assert status == 200
        legacy = json.loads(body)['simulation']
        # 100% legacy input -> savings premium equals risk premium to the cent
        assert abs(legacy['profitability']['savings_premium']
                    - legacy['profitability']['risk_premium']) < 1.0
        assert legacy['premium_reconciliation']['all_identities_pass'] is True
        # And the saved snapshot must record that the markup formula was used
        assert legacy['pricing_kernel']['savings_formula'] == 'risk_premium_markup'
        assert legacy['pricing_kernel']['savings_rate'] == 1.0

        # 2) Run a small simulation
        body, status, _ = _post_json(base + '/api/actuarial/simulate', {
            'customer_count': 100, 'age_min': 25, 'age_max': 50,
            'policy_term_mode': 'fixed', 'policy_term_fixed': 10,
            'savings_allocation_pct': 0.20,
        }, admin_token)
        assert status == 200
        sim_payload = json.loads(body)
        simulation_id = sim_payload['simulation']['simulation_id']
        # Saving allocation block must be present
        assert 'savings_allocation' in sim_payload['simulation']

        # 3) Project reserves for that simulation
        body, status, _ = _post_json(base + '/api/actuarial/reserves/project', {
            'simulation_id': simulation_id,
            'projection_years': 4,
            'dividends_pct': 0.25,
            'tax_pct': 0.22,
            'ibnr_pct': 0.10,
            'reserve_contribution_pct': 0.50,
            'risk_adjustment_pct': 0.06,
            'savings_allocation_pct': 0.20,
            'savings_yield_pct': 0.045,
        }, admin_token)
        assert status == 200
        projection = json.loads(body)['projection']
        assert projection['projection_years'] == 4
        assert projection['data_integrity']['profit_waterfall_consistent']

        # 4) Savings allocation endpoint
        body, status, _ = _post_json(base + '/api/actuarial/savings-allocation', {
            'simulation_id': simulation_id,
            'savings_allocation_pct': 25,
        }, admin_token)
        assert status == 200
        alloc = json.loads(body)['allocation']
        assert alloc['savings_allocation_pct'] == 25.0
        assert alloc['data_integrity']['gross_premium_reconciles']

        # 5) Excel report generation — money cells must carry a
        # thousands-separator + 2-decimal number format so the workbook is
        # audit-ready out of the box.
        body, status, headers = _post_json(base + '/api/actuarial/reports/export', {
            'simulation_id': simulation_id,
            'format': 'xlsx',
            'projection_years': 3,
        }, admin_token)
        assert status == 200
        assert headers.get('Content-Type', '').endswith('sheet')
        assert body[:2] == b'PK'  # XLSX is a zip envelope
        # Inspect the workbook to verify number formatting on money columns.
        import io as _io, openpyxl
        wb = openpyxl.load_workbook(_io.BytesIO(body), data_only=False)
        ws_res = wb['Reserves Projection']
        headers_row = [c.value for c in ws_res[1]]
        money_headers = (
            'In-Force Premium', 'Closing Reserve', 'IBNR Provision',
            'IFRS17 CSM Release', 'IFRS17 CSM Balance',
        )
        for header in money_headers:
            col_idx = headers_row.index(header) + 1
            sample = None
            for row in ws_res.iter_rows(min_row=2, max_col=col_idx, max_row=ws_res.max_row):
                cell = row[col_idx - 1]
                if isinstance(cell.value, (int, float)):
                    sample = cell
                    break
            assert sample is not None, header
            assert '#,##0.00' in (sample.number_format or ''), (
                header, sample.number_format,
            )

        # 6) PDF report generation (basic content sniff)
        body, status, headers = _post_json(base + '/api/actuarial/reports/export', {
            'simulation_id': simulation_id,
            'format': 'pdf',
            'projection_years': 3,
        }, admin_token)
        assert status == 200
        assert headers.get('Content-Type') == 'application/pdf'
        assert body[:4] == b'%PDF'
    finally:
        srv.stop()
