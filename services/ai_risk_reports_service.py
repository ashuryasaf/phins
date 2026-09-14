"""
AI Risk & Reports Analysis Service
===================================
Compatibility facade for :mod:`services.risk_reports` (B9 package split).

The implementation lives in ``services/risk_reports/{models,parsers,analysis,
charts,render,service}.py``; this module re-exports the public API so every
historical import keeps working::

    from services.ai_risk_reports_service import get_ai_reports_service

The two module-level *mutable* names callers and tests rebind -
``AI_REPORTS_DATA_FILE`` and the ``_ai_reports_service`` singleton slot - are
forwarded in both directions to :mod:`services.risk_reports.service`, so
``monkeypatch.setattr(services.ai_risk_reports_service, 'AI_REPORTS_DATA_FILE',
...)`` still steers the service exactly as before the split.

Author: PHINS Platform
"""

import sys
import types

from services.risk_reports import service as _service
from services.risk_reports.analysis import (  # noqa: F401
    AnalysisMixin, DataClassifier, HebrewDocumentExtractor, LanguageDetector,
)
from services.risk_reports.charts import ChartsMixin  # noqa: F401
from services.risk_reports.models import (  # noqa: F401
    AnalysisResult, Anomaly, ChartConfig, ChartType, ColumnInfo, DataType, Factor,
    GeneratedReport, Pattern, Priority, Recommendation, ReportSection, Severity,
    _risk_report_audit, logger,  # noqa: F401
)
from services.risk_reports.parsers import ParserMixin  # noqa: F401
from services.risk_reports.render import RenderMixin  # noqa: F401
from services.risk_reports.service import (  # noqa: F401
    AIRiskReportsService, _risk_reports_health, get_ai_reports_service,  # noqa: F401
    init_ai_reports_service,
)

#: Names that live in ``services.risk_reports.service`` and must stay a single
#: binding no matter which module path a caller reads or writes them through.
_FORWARDED = frozenset({'AI_REPORTS_DATA_FILE', '_ai_reports_service'})


class _Facade(types.ModuleType):
    def __getattr__(self, name):
        if name in _FORWARDED:
            return getattr(_service, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in _FORWARDED:
            setattr(_service, name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in _FORWARDED:
            delattr(_service, name)
        else:
            super().__delattr__(name)


sys.modules[__name__].__class__ = _Facade

__all__ = [
    'AIRiskReportsService', 'get_ai_reports_service', 'init_ai_reports_service',
    'AnalysisResult', 'Anomaly', 'ChartConfig', 'ChartType', 'ColumnInfo', 'DataType',
    'Factor', 'GeneratedReport', 'Pattern', 'Priority', 'Recommendation',
    'ReportSection', 'Severity',
    'AnalysisMixin', 'DataClassifier', 'HebrewDocumentExtractor', 'LanguageDetector',
    'ParserMixin', 'ChartsMixin', 'RenderMixin',
    'AI_REPORTS_DATA_FILE', 'logger',  # noqa: F822 (forwarded)
]
