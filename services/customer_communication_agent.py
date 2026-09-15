"""
Compatibility shim — the Customer Communication Agent now lives in
:mod:`services.customer_agent.communication` (B6). Import from there for new
code; this module re-exports the public names so existing imports keep working.
"""

from __future__ import annotations

from services.customer_agent.communication import (  # noqa: F401
    AGENT_NAME,
    CustomerCommunicationAgent,
    ExecutiveReport,
    _safe_float,
    _status,
    get_customer_communication_agent,
)

__all__ = ['CustomerCommunicationAgent', 'ExecutiveReport', 'get_customer_communication_agent']
