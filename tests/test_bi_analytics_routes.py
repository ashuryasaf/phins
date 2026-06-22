"""
Tests for the now-wired canonical BI analytics handlers
=======================================================
``services/bi_analytics_service.py`` is exposed through
``web_portal/api_bi_analytics.py``. These handlers were previously unreachable
(no route registered them). Server route wiring lives in
``web_portal/server.py``; here we exercise the handler + service path directly
with representative in-memory data sources.
"""

from web_portal import api_bi_analytics as bi


def _data_sources():
    return {
        'customers': {'C1': {'status': 'active'}, 'C2': {'status': 'active'}},
        'policies': {
            'P1': {'status': 'active', 'monthly_premium': 100, 'annual_premium': 1200,
                   'coverage_amount': 100000},
        },
        'claims': {'CL1': {'status': 'approved', 'approved_amount': 500}},
        'billing': {'B1': {'status': 'paid', 'amount': 1200}},
        'balance_sheet': {'total_assets': 100000, 'total_liabilities': 20000, 'claims_reserve': 5000},
        'suppliers': {},
        'supplier_orders': {},
        'health_wallets': {},
        'investment_accounts': {},
        'transaction_ledger': {},
        'deliveries': {},
    }


def test_executive_dashboard_handler_returns_200_and_summary():
    status, payload = bi.handle_executive_dashboard(None, _data_sources())
    assert status == 200
    assert isinstance(payload, dict)
    assert 'summary' in payload or 'health_scores' in payload


def test_ai_insights_handler_returns_insights_list():
    status, payload = bi.handle_ai_insights(None, _data_sources())
    assert status == 200
    assert 'insights' in payload
    assert isinstance(payload['insights'], list)
    assert payload['insight_count'] == len(payload['insights'])


def test_revenue_forecast_handler_parses_flat_params():
    # Route passes flattened string params; the handler must coerce them.
    status, payload = bi.handle_revenue_forecast(
        None, _data_sources()['policies'], {'growth_rate': '0.05', 'months_ahead': '6'}
    )
    assert status == 200
    assert isinstance(payload, dict)


def test_bi_routes_registered_in_server_source():
    # Guard against the wiring regressing back to dead code.
    import inspect
    import web_portal.server as server
    src = inspect.getsource(server.PortalHandler.do_GET)
    for route in ('/api/bi/executive-dashboard', '/api/bi/insights',
                  '/api/bi/revenue-forecast'):
        assert route in src
