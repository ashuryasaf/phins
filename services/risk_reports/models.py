"""Risk Reports data model (B9).

Enums, dataclasses and the audit mirror shared by the parser, analysis,
chart and render layers of :mod:`services.risk_reports`.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
logger = logging.getLogger('phins.ai_risk_reports')


def _risk_report_audit(action: str, entity_id: Optional[str], details: Dict[str, Any]) -> None:
    """Mirror a risk-report lifecycle event into the durable audit store.

    Best-effort and non-fatal. The report artifacts themselves persist in the
    service's JSON store; this adds a durable compliance trail of who/what was
    produced, independent of that store. No-op without a database.
    """
    try:
        from services.ai_audit_bridge import record_ai_audit
        record_ai_audit(
            action=action,
            entity_type='risk_report',
            entity_id=entity_id,
            details=details,
            username='ai_risk_reports',
        )
    except Exception as exc:
        logger.warning("risk report audit mirror failed (non-fatal): %s", exc)


class DataType(Enum):
    INSURANCE = "insurance"
    INVESTMENT = "investment"
    RISK = "risk"
    SAVINGS = "savings"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ChartType(Enum):
    PIE = "pie"
    BAR = "bar"
    LINE = "line"
    GAUGE = "gauge"
    SCATTER = "scatter"
    DOUGHNUT = "doughnut"


class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    sample_values: List[Any]
    semantic_type: str = ""
    is_key_field: bool = False


@dataclass
class Factor:
    name: str
    value: Any
    importance: float
    category: str


@dataclass
class Pattern:
    type: str
    description: str
    affected_rows: List[int]
    significance: float


@dataclass
class Anomaly:
    type: str
    severity: Severity
    description: str
    affected_data: Dict
    recommendation: str


@dataclass
class ChartConfig:
    type: ChartType
    title: str
    data: Dict
    options: Dict = field(default_factory=dict)


@dataclass
class ReportSection:
    title: str
    content: str
    data_table: Optional[Dict] = None
    order: int = 0


@dataclass
class Recommendation:
    id: str
    category: str
    priority: Priority
    title: str
    description: str
    action_items: List[str]
    expected_impact: str


@dataclass
class AnalysisResult:
    id: str
    document_id: str
    language: str
    language_name: str
    data_classification: DataType
    extracted_factors: List[Factor]
    patterns_found: List[Pattern]
    anomalies: List[Anomaly]
    risk_score: float
    confidence: float
    processing_time_ms: int
    summary: str
    key_metrics: Dict[str, Any]


@dataclass
class GeneratedReport:
    id: str
    analysis_id: str
    report_type: str
    language: str
    title: str
    sections: List[ReportSection]
    charts: List[ChartConfig]
    recommendations: List[Recommendation]
    generated_at: str
    metadata: Dict[str, Any]

