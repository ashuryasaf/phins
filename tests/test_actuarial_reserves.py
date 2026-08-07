"""
Tests for the new PHINS actuarial primitives:
- ReserveCalculator (IBNR, IFRS 17 BEL/RA/CSM, dividends/tax/reserves waterfall)
- apply_savings_allocation
- build_risk_reference (must reproduce the locked public model exactly)
- normalize_uploaded_rate_table (custom uploaded mortality/disability tables)

These tests are unit-style so they do not depend on the embedded HTTP server.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import HTTPServer
from urllib.request import Request, urlopen

import web_portal.server as portal
from services.actuarial_service import (
    SimulationParams,
    ReserveCalculator,
    _coerce_reserve_config,
    apply_savings_allocation,
    build_risk_reference,
    risk_reference_age_factor,
    risk_reference_monthly_premiums,
    get_portfolio_simulator,
    get_actuarial_store,
    normalize_uploaded_rate_table,
    apply_uploaded_table_to_store,
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
    version_before = store.current_version
    new_table = [
        {'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.4},
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 0.9},
        {'age_min': 40, 'age_max': 120, 'rate_per_1000': 2.0},
    ]
    result = apply_uploaded_table_to_store('mortality_rates', new_table, user='pytest')
    assert result.get('success') is True
    # Promoting a table snapshots a new immutable version
    assert result.get('version') and result['version'] != version_before
    assert store.current_version == result['version']
    # Round-trip: rate at age 35 must come from the new table
    rate = store.get_mortality_rate(35)
    assert abs(rate - (0.9 / 1000.0)) < 1e-9
    # Restore defaults so other tests see the standard tables
    store.reset_tables_to_default('mortality_rates', 'pytest')


def test_apply_uploaded_table_to_store_rejects_partial_coverage():
    """A global rate band with gaps / missing ages must be rejected."""
    store = get_actuarial_store()
    version_before = store.current_version
    tables_before = store.get_current_tables().get('mortality_rates')
    partial = [
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 0.9},
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 2.0},
    ]
    result = apply_uploaded_table_to_store('mortality_rates', partial, user='pytest')
    assert result.get('success') is False
    assert 'start at age 0' in result.get('error', '')
    # The rejected update must not create a version or mutate the tables
    assert store.current_version == version_before
    assert store.get_current_tables().get('mortality_rates') == tables_before


# ----------------------------------------------------------------------------
# HTTP integration test for the new endpoints
# ----------------------------------------------------------------------------

class _ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(('127.0.0.1', port), portal.PortalHandler)

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


def test_actuarial_endpoints_end_to_end(tmp_path):
    port = 8174
    srv = _ServerThread(port)
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
