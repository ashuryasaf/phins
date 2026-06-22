"""
Tests for the AI capability discovery catalog.
"""

import inspect

from services import ai_capabilities as cap
import web_portal.server as server


def test_full_catalog_for_admin_and_none():
    full = cap.get_capabilities()
    assert len(full) == 7
    assert cap.get_capabilities('admin') == full
    ids = {c['id'] for c in full}
    assert {'claims_bot', 'ai_trading_engine', 'bi_analytics'} <= ids


def test_role_filtering_is_inclusive():
    customer_caps = cap.get_capabilities('customer')
    ids = {c['id'] for c in customer_caps}
    assert 'investment_ai' in ids          # open to customers
    assert 'video_agents' not in ids       # admin/media only


def test_get_capability_and_missing():
    assert cap.get_capability('claims_bot')['name'] == 'Claims Probability Bot'
    assert cap.get_capability('nope') is None


def test_help_text_shape():
    ht = cap.help_text('underwriter')
    assert ht['capability_count'] == len(ht['capabilities'])
    assert all('api' in c and 'entry_url' in c for c in ht['capabilities'])


def test_capabilities_route_registered():
    src = inspect.getsource(server.PortalHandler.do_GET)
    assert '/api/ai/capabilities' in src
