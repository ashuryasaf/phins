"""
AI Capabilities Catalog
=======================
A single, structured description of the AI features PHINS exposes -- what each
one does, where to reach it, who may use it, and example prompts/actions.

This is the discovery surface the agent-native audit found missing: previously
the AI features were only discoverable by hunting through individual
dashboards. Exposing one catalog gives both humans (UI "What can the AI do?"
panels) and programmatic agents the same machine-readable list, which is the
foundation for action parity.

The catalog is the union of the static entries below (authoritative for the
user-facing name/description/roles of the original six features) and the
descriptors every software agent registers in ``services.agent_runtime`` at
import time. ``ensure_agents_loaded()`` imports the agent modules so the
registry is complete before the catalog is read; each import is guarded so a
missing optional dependency only drops that one agent from the catalog.

No side effects beyond importing agent modules; no external dependencies.
"""

import importlib
import logging
import threading
from typing import Any, Dict, List, Optional

from services import agent_runtime

logger = logging.getLogger('phins.ai_capabilities')

# Modules that register an AgentDescriptor at import time. Kept as a plain
# list (not imported at module load) so ``ai_capabilities`` stays cheap to
# import and can never participate in an import cycle.
AGENT_MODULES: List[str] = [
    'services.underwriting_bot_service',
    'services.claims_bot_service',
    'ai_automation_controller',
    'underwriting_assistant',
    'services.assessment_ai_service',
    'services.pension_data_agent',
    'services.document_processing_service',
    'services.customer_communication_agent',
    'service_agent',
    'services.marketing_sales_agent_service',
    'services.video_agents_service',
    'services.ai_risk_reports_service',
    'services.bi_analytics_service',
    'services.delivery_bidding_service',
    'services.ai_trading_engine',
]

_LOAD_LOCK = threading.Lock()
_LOADED = False
_LOAD_FAILURES: Dict[str, str] = {}

# Registry-only fields merged into static entries (static text wins).
_RUNTIME_FIELDS = ('version', 'module', 'executes_async', 'moves_money')

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


def ensure_agents_loaded(force: bool = False) -> Dict[str, str]:
    """Import every agent module once so its descriptor is registered.

    Returns the map of module -> error for modules that failed to import.
    Failures are logged once and never raised: a broken optional agent must
    not take the capability catalog (or the admin health panel) down.
    """
    global _LOADED
    with _LOAD_LOCK:
        if _LOADED and not force:
            return dict(_LOAD_FAILURES)
        _LOAD_FAILURES.clear()
        for module_name in AGENT_MODULES:
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 - one bad agent must not hide the rest
                _LOAD_FAILURES[module_name] = f"{type(exc).__name__}: {exc}"[:300]
                logger.warning("agent module %s not loaded for catalog: %s", module_name, exc)
        _LOADED = True
        return dict(_LOAD_FAILURES)


def load_failures() -> Dict[str, str]:
    """Agent modules that could not be imported (module -> error)."""
    ensure_agents_loaded()
    return dict(_LOAD_FAILURES)


def _full_catalog() -> List[Dict[str, Any]]:
    """Static entries (text authoritative) merged with registered descriptors."""
    ensure_agents_loaded()
    by_id: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for entry in _CAPABILITIES:
        by_id[entry['id']] = dict(entry)
        order.append(entry['id'])
    for desc in agent_runtime.registry():
        cap = desc.to_capability()
        if desc.id in by_id:
            for key in _RUNTIME_FIELDS:
                by_id[desc.id][key] = cap[key]
        else:
            by_id[desc.id] = cap
            order.append(desc.id)
    return [by_id[cid] for cid in order]


def get_capabilities(role: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return the AI capability catalog, optionally filtered to a role.

    ``role`` filtering is inclusive of capabilities open to that role; passing
    ``None`` (or ``'admin'``) returns the full catalog.
    """
    catalog = _full_catalog()
    if not role or role == 'admin':
        return catalog
    return [c for c in catalog if role in c.get('roles', [])]


def get_capability(capability_id: str) -> Optional[Dict[str, Any]]:
    """Return a single capability by id, or None."""
    for c in _full_catalog():
        if c['id'] == capability_id:
            return c
    return None


def help_text(role: Optional[str] = None, *, include_health: bool = False) -> Dict[str, Any]:
    """Return a compact, agent- and human-friendly capability summary.

    ``include_health`` (admin surfaces only) attaches each registered agent's
    health probe and metrics snapshot; it is never attached for other roles so
    operational detail is not exposed to customers.
    """
    caps = get_capabilities(role)
    if include_health:
        for cap in caps:
            if agent_runtime.is_registered(cap['id']):
                cap['health'] = agent_runtime.health(cap['id'])
                cap['metrics'] = agent_runtime.metrics(cap['id'])
    payload = {
        'message': 'PHINS AI capabilities. Use the entry_url (UI) or api (programmatic) for each.',
        'capability_count': len(caps),
        'capabilities': caps,
    }
    if include_health:
        payload['load_failures'] = load_failures()
    return payload


__all__ = [
    'AGENT_MODULES', 'ensure_agents_loaded', 'load_failures',
    'get_capabilities', 'get_capability', 'help_text',
]
