"""
Tests for the additive primitive classification on the investment AI dispatcher.
Behavior of dispatch_investment_ai is unchanged; these only cover the new
descriptive accessors.
"""

from services import investment_ai_tool_service as ia


def test_module_kind_classification():
    assert ia.module_kind('live_quote') == 'primitive'
    assert ia.module_kind('market_movers') == 'primitive'
    assert ia.module_kind('technical_analysis') == 'workflow'
    assert ia.module_kind('market_research') == 'workflow'


def test_list_primitive_tools_subset_of_modules():
    prims = ia.list_primitive_tools()
    assert set(prims).issubset(set(ia.AVAILABLE_MODULES))
    assert 'live_quote' in prims
    assert 'technical_analysis' not in prims


def test_catalog_includes_kind_and_primitive_list():
    cat = ia.get_modules_catalog()
    assert 'primitive_modules' in cat
    assert cat['modules']['live_quote']['kind'] == 'primitive'
    assert cat['modules']['technical_analysis']['kind'] == 'workflow'
    # Original metadata preserved.
    assert 'handler' in cat['modules']['live_quote']
