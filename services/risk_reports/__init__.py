"""AI Risk Reports agent as a package (B9).

Layers::

    models.py    enums, dataclasses, audit mirror
    parsers.py   CSV / Excel / ZIP / Mislaka XML / image / PDF intake
    analysis.py  language + classification + statistical analysis
    charts.py    chart configurations (client-rendered)
    render.py    report sections and recommendations
    service.py   AIRiskReportsService, stores, persistence, registration

``services.ai_risk_reports_service`` remains the public import path.
"""

from services.risk_reports.models import (  # noqa: F401
    AnalysisResult, Anomaly, ChartConfig, ChartType, ColumnInfo, DataType, Factor,
    GeneratedReport, Pattern, Priority, Recommendation, ReportSection, Severity,
)
from services.risk_reports.analysis import (  # noqa: F401
    AnalysisMixin, DataClassifier, HebrewDocumentExtractor, LanguageDetector,
)
from services.risk_reports.parsers import ParserMixin  # noqa: F401
from services.risk_reports.charts import ChartsMixin  # noqa: F401
from services.risk_reports.render import RenderMixin  # noqa: F401
from services.risk_reports.service import (  # noqa: F401
    AIRiskReportsService, get_ai_reports_service, init_ai_reports_service,
)

__all__ = [
    'AnalysisResult', 'Anomaly', 'ChartConfig', 'ChartType', 'ColumnInfo', 'DataType',
    'Factor', 'GeneratedReport', 'Pattern', 'Priority', 'Recommendation',
    'ReportSection', 'Severity',
    'AnalysisMixin', 'DataClassifier', 'HebrewDocumentExtractor', 'LanguageDetector',
    'ParserMixin', 'ChartsMixin', 'RenderMixin',
    'AIRiskReportsService', 'get_ai_reports_service', 'init_ai_reports_service',
]
