"""
Underwriting Bot package (B1 split of ``services/underwriting_bot_service.py``).

* :mod:`~services.underwriting_bot.report`   — enums, dataclasses, ``RiskAssessmentEngine``
* :mod:`~services.underwriting_bot.features` — path validation + per-modality analyzers
* :mod:`~services.underwriting_bot.service`  — ``UnderwritingBotService`` and accessors

``services.underwriting_bot_service`` re-exports every historical name, so
existing imports keep working; new code may import from the sub-modules.
"""

from services.underwriting_bot.report import (  # noqa: F401
    MetadataType, ProcessingStatus, ValidationStatus, RiskLevel, DecisionRecommendation,
    AssessmentStatus, UnderwritingMetadata, ExtractedFeature, RiskFactor,
    RiskAssessmentReport, BotAssessment, RiskAssessmentEngine,
)
from services.underwriting_bot.features import (  # noqa: F401
    ALLOWED_UPLOAD_DIRS, validate_file_path, sanitize_filename,
    PhotoAnalyzer, MedicalReportAnalyzer, OfficialDocumentAnalyzer, AudioAnalyzer, VideoAnalyzer,
)
from services.underwriting_bot.service import (  # noqa: F401
    UnderwritingBotService, get_underwriting_bot_service, init_underwriting_bot_service,
)

__all__ = [
    'UnderwritingBotService', 'get_underwriting_bot_service', 'init_underwriting_bot_service',
    'MetadataType', 'ProcessingStatus', 'ValidationStatus', 'RiskLevel', 'DecisionRecommendation',
    'AssessmentStatus', 'UnderwritingMetadata', 'ExtractedFeature', 'RiskFactor',
    'RiskAssessmentReport', 'BotAssessment', 'RiskAssessmentEngine',
    'PhotoAnalyzer', 'MedicalReportAnalyzer', 'OfficialDocumentAnalyzer', 'AudioAnalyzer',
    'VideoAnalyzer', 'ALLOWED_UPLOAD_DIRS', 'validate_file_path', 'sanitize_filename',
]
