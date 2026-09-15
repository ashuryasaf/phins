"""
Pension Data Agent Service - Enhanced Mislaka Support
=====================================================
Processes Israeli pension and insurance XML data files according to
the Mislaka (מסלקה) interface standards based on official XSD schemas.

Compatibility facade (B5). The implementation lives in the
``services.pension`` package:

- ``services.pension.schema``  — ``MislakaSchemaMapping`` + precompiled lookups
- ``services.pension.profile`` — ``ClientProfile`` (multi-file aggregate)
- ``services.pension.parsers`` — XML (tree + streaming), Excel, CSV parsers
- ``services.pension.report``  — enrichment, health score, Hebrew report
- ``services.pension.cache``   — content-addressed parse cache (``agent_artifacts``)
- ``services.pension.agent``   — ``PensionDataAgent``, singleton, health, registration

Every historical name is re-exported here so ``from services.pension_data_agent
import ...`` keeps working; the agent descriptor still names this module.

Supported Interfaces:
- Holdings Interface (v9.7.7): kupotgemel, karnotpensiavatikot,
  karnotpensiahadashot, hevrotbituah
- Severance Interface (v5.9.38): interface codes 9300-9306
- Event Interface (v7.6.30)
- Transference Interface (v3.7.2)

Data Source: swiftness.co.il / Mislaka clearinghouse
Author: PHINS Platform
"""

from services.pension import agent as _agent
from services.pension.agent import (  # noqa: F401
    LXML_AVAILABLE,
    PensionDataAgent,
    _pension_agent_health,
    get_pension_agent,
    is_pension_xml,
    logger,
)
from services.pension.cache import PARSER_VERSION, ParseResultCache  # noqa: F401
from services.pension.parsers import MislakaParserMixin  # noqa: F401
from services.pension.profile import ClientProfile  # noqa: F401
from services.pension.report import PensionReportMixin  # noqa: F401
from services.pension.schema import CompiledFields, MislakaSchemaMapping  # noqa: F401


def __getattr__(name):
    # ``_pension_agent`` is the live singleton slot in ``services.pension.agent``.
    if name == '_pension_agent':
        return _agent._pension_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'MislakaSchemaMapping', 'CompiledFields', 'ClientProfile', 'PensionDataAgent',
    'MislakaParserMixin', 'PensionReportMixin', 'ParseResultCache', 'PARSER_VERSION',
    'get_pension_agent', 'is_pension_xml', 'LXML_AVAILABLE', 'logger',
]
