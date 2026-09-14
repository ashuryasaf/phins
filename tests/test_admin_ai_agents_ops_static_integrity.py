"""
Static integrity checks for the AI Agents Operations panel on admin.html
(docs/agent_operations_optimization_design.md §A5).
"""

import re
from pathlib import Path

ADMIN_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def _content() -> str:
    return ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")


def test_ai_agents_ops_panel_present_and_collapsed_by_default():
    content = _content()
    assert 'id="ai-agents-ops"' in content
    panel = re.search(r'<div id="ai-agents-ops"[^>]*>', content).group(0)
    assert 'data-collapsible="true"' in panel
    assert 'data-collapsed="true"' in panel
    assert 'AI Agents Operations' in content
    for element_id in ('ai-agents-ops-summary', 'ai-agents-ops-breaches',
                       'ai-agents-ops-table', 'ai-agents-ops-body'):
        assert f'id="{element_id}"' in content, element_id


def test_ai_agents_ops_panel_reads_admin_health_route_with_bearer_token():
    content = _content()
    assert "fetch('/api/admin/ai-agents/health'" in content
    loader = content[content.index('async function loadAIAgentsOps'):]
    loader = loader[:loader.index('loadAIAgentsOps();')]
    assert "localStorage.getItem('phins_token')" in loader
    assert "'Authorization': 'Bearer ' + token" in loader
    # Read-only: the panel only ever issues a GET.
    assert 'method:' not in loader and "method: 'POST'" not in loader


def test_ai_agents_ops_panel_escapes_server_values():
    content = _content()
    assert 'function _aiAgentsEsc(' in content
    loader = content[content.index('async function loadAIAgentsOps'):]
    loader = loader[:loader.index('loadAIAgentsOps();')]
    for field in ('a.name', 'a.id', 'h.status', 'b.agent_id', 'm.last_call_at'):
        assert f'_aiAgentsEsc({field}' in loader, field


def test_ai_agents_ops_panel_surfaces_slo_breaches_and_flags():
    content = _content()
    assert 'data.slo_breaches' in content
    assert 'data.load_failures' in content
    assert "a.moves_money" in content and "a.executes_async" in content
    assert "a.deterministic === false" in content
