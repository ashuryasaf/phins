"""
AI Capabilities Catalog
=======================
A single, structured description of the AI features PHINS exposes -- what each
one does, where to reach it, who may use it, and example prompts/actions.

This is the discovery surface the agent-native audit found missing: previously
the seven AI features were only discoverable by hunting through individual
dashboards. Exposing one catalog gives both humans (UI "What can the AI do?"
panels) and programmatic agents the same machine-readable list, which is the
foundation for action parity.

Pure data + helpers; no side effects, no external dependencies.
"""

from typing import Any, Dict, List, Optional

# Each entry is intentionally declarative so it can be rendered in the UI and
# consumed by an agent without code changes -- add a feature by adding an entry.
_CAPABILITIES: List[Dict[str, Any]] = [
    {
        'id': 'claims_bot',
        'name': 'Claims Probability Bot',
        'description': (
            'Generates a fraud/authenticity probability report for a claim by '
            'cross-referencing documents, medical consistency, timing, amount, '
            'customer history, and underwriting alignment.'
        ),
        'entry_url': '/claims-adjuster-dashboard.html',
        'api': {'method': 'POST', 'path': '/api/claims/probability-report'},
        'roles': ['admin', 'claims_adjuster', 'underwriter'],
        'sample_prompts': [
            'Generate a probability report for claim CLM-12345',
            'Is there fraud risk on this claim?',
        ],
        'deterministic': True,
    },
    {
        'id': 'assessment_ai',
        'name': 'Assessment AI Narrative',
        'description': (
            'Produces an advisory, non-authoritative narrative summary of an '
            'assessment from already-extracted facts. Never issues an '
            'underwriting decision; flags items for human review.'
        ),
        'entry_url': '/assessment-center.html',
        'api': {'method': 'POST', 'path': '/api/assessment-center/analysis'},
        'roles': ['admin', 'underwriter', 'analyst'],
        'sample_prompts': [
            'Summarize the assessment findings for this applicant',
        ],
        'deterministic': False,
    },
    {
        'id': 'ai_risk_reports',
        'name': 'AI Risk Reports',
        'description': (
            'Ingests uploaded CSV/XLS/ZIP documents and produces statistical '
            'risk analyses and bilingual reports with charts and recommendations.'
        ),
        'entry_url': '/risk-reports-dashboard.html',
        'api': {'method': 'POST', 'path': '/api/reports/generate'},
        'roles': ['admin', 'underwriter', 'analyst', 'actuary'],
        'sample_prompts': [
            'Analyze this policy export and generate a risk report',
        ],
        'deterministic': True,
    },
    {
        'id': 'investment_ai',
        'name': 'Investment AI Tools',
        'description': (
            'Market trend analysis, portfolio diversification, screeners, '
            'technical analysis, and strategy design over live market data.'
        ),
        'entry_url': '/investment-ai.html',
        'api': {'method': 'POST', 'path': '/api/investment-ai/analyze'},
        'roles': ['admin', 'customer'],
        'sample_prompts': [
            'Run a technical analysis on AAPL',
            'Screen for momentum stocks',
        ],
        'deterministic': True,
    },
    {
        'id': 'ai_trading_engine',
        'name': 'AI Trading & AutoPilot',
        'description': (
            'Computes signals and risk metrics and runs rule-based AutoPilot '
            'bots. Trade execution is risk-gated and audit-logged.'
        ),
        'entry_url': '/trading-terminal.html',
        'api': {'method': 'GET', 'path': '/api/terminal/copilot'},
        'roles': ['admin', 'customer'],
        'sample_prompts': [
            'What is the copilot signal for TSLA?',
            'Show AutoPilot bot performance',
        ],
        'deterministic': True,
    },
    {
        'id': 'video_agents',
        'name': 'Video Agents',
        'description': (
            'Generates insurance-workflow videos (introductions, regulatory, '
            'application/underwriting/claims assistants) with cost controls.'
        ),
        'entry_url': '/video-agents.html',
        'api': {'method': 'POST', 'path': '/api/admin/media/video-jobs/batch'},
        'roles': ['admin', 'media'],
        'sample_prompts': [
            'Generate an introduction video for this campaign',
        ],
        'deterministic': False,
    },
    {
        'id': 'bi_analytics',
        'name': 'BI Analytics & Insights',
        'description': (
            'Executive, delivery, customer, and supplier dashboards plus '
            'rule-based AI insights and revenue forecasting.'
        ),
        'entry_url': '/admin.html',
        'api': {'method': 'GET', 'path': '/api/bi/insights'},
        'roles': ['admin', 'accountant', 'underwriter'],
        'sample_prompts': [
            'What are the current BI insights?',
            'Forecast revenue for the next 6 months',
        ],
        'deterministic': True,
    },
]


def get_capabilities(role: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return the AI capability catalog, optionally filtered to a role.

    ``role`` filtering is inclusive of capabilities open to that role; passing
    ``None`` (or ``'admin'``) returns the full catalog.
    """
    if not role or role == 'admin':
        return [dict(c) for c in _CAPABILITIES]
    return [dict(c) for c in _CAPABILITIES if role in c.get('roles', [])]


def get_capability(capability_id: str) -> Optional[Dict[str, Any]]:
    """Return a single capability by id, or None."""
    for c in _CAPABILITIES:
        if c['id'] == capability_id:
            return dict(c)
    return None


def help_text(role: Optional[str] = None) -> Dict[str, Any]:
    """Return a compact, agent- and human-friendly capability summary."""
    caps = get_capabilities(role)
    return {
        'message': 'PHINS AI capabilities. Use the entry_url (UI) or api (programmatic) for each.',
        'capability_count': len(caps),
        'capabilities': caps,
    }


__all__ = ['get_capabilities', 'get_capability', 'help_text']
