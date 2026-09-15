"""
Tests for the AI capability discovery catalog.
"""

import inspect

from services import ai_capabilities as cap
import web_portal.server as server


def test_full_catalog_for_admin_and_none():
    full = cap.get_capabilities()
    assert len(full) == 15, sorted(c['id'] for c in full)
    assert cap.get_capabilities('admin') == full
    ids = {c['id'] for c in full}
    assert {'claims_bot', 'ai_trading_engine', 'bi_analytics'} <= ids
    assert {'underwriting_bot', 'ai_automation_controller', 'pension_data_agent',
            'document_intelligence', 'customer_communication', 'customer_service',
            'marketing_sales', 'delivery_bidding', 'underwriting_assistant'} <= ids
    assert 'investment_ai' not in ids      # feature removed
    assert cap.load_failures() == {}


def test_static_text_wins_but_runtime_fields_merge():
    """The six original entries keep their user-facing text; the registry
    only contributes runtime metadata."""
    trading = cap.get_capability('ai_trading_engine')
    assert trading['name'] == 'AI Trading & AutoPilot'
    assert trading['module'] == 'services.ai_trading_engine'
    assert trading['moves_money'] is True
    assert trading['version']
    for c in cap.get_capabilities():
        assert 'module' in c and 'version' in c, c['id']


def test_every_entry_has_unique_id_and_required_keys():
    full = cap.get_capabilities()
    ids = [c['id'] for c in full]
    assert len(ids) == len(set(ids))
    for c in full:
        for key in ('name', 'description', 'entry_url', 'api', 'roles',
                    'sample_prompts', 'deterministic'):
            assert key in c, (c['id'], key)
        assert c['api'].get('method') and c['api'].get('path')
        assert c['roles']


def test_role_filtering_is_inclusive():
    customer_caps = cap.get_capabilities('customer')
    ids = {c['id'] for c in customer_caps}
    assert 'ai_trading_engine' in ids      # open to customers
    assert 'video_agents' not in ids       # admin/media only


def test_get_capability_and_missing():
    assert cap.get_capability('claims_bot')['name'] == 'Claims Probability Bot'
    assert cap.get_capability('nope') is None


def test_help_text_shape():
    ht = cap.help_text('underwriter')
    assert ht['capability_count'] == len(ht['capabilities'])
    assert all('api' in c and 'entry_url' in c for c in ht['capabilities'])
    assert all('health' not in c for c in ht['capabilities'])
    assert 'load_failures' not in ht


def test_help_text_health_is_opt_in():
    ht = cap.help_text('admin', include_health=True)
    assert ht['load_failures'] == {}
    for c in ht['capabilities']:
        assert c['health']['status'] in ('ok', 'degraded', 'unavailable', 'unknown'), c['id']
        assert 'calls' in c['metrics'], c['id']


def test_customer_view_excludes_operational_agents():
    ids = {c['id'] for c in cap.get_capabilities('customer')}
    assert 'ai_trading_engine' in ids
    assert 'delivery_bidding' in ids
    for hidden in ('underwriting_bot', 'claims_bot', 'customer_communication',
                   'document_intelligence', 'marketing_sales'):
        assert hidden not in ids


def test_capabilities_route_registered():
    src = inspect.getsource(server.PortalHandler.do_GET)
    assert '/api/ai/capabilities' in src
