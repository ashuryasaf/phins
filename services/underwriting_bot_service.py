"""
PHINS Underwriting Bot Service
==============================
AI-powered underwriting bot that processes metadata (photos, medical reports,
official documents, audio, video) and creates comprehensive risk assessment reports
to support automated and assisted underwriting decisions.

Features:
- Multi-type metadata processing (photos, medical reports, documents, audio, video)
- AI-based risk assessment engine
- Full risk assessment report generation
- Integration with existing pipeline (preserves all customer data)
- Validated process as part of the underwriting pipeline
- Data integrity protection (never modifies existing customer data)

Compatibility facade
--------------------
The implementation lives in the :mod:`services.underwriting_bot` package
(``report`` / ``features`` / ``service``). This module re-exports every
historical public name so ``from services.underwriting_bot_service import X``
keeps working for the routes, jobs, demos and tests that use it.

Author: PHINS Platform
Version: 1.1.0
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
    'UnderwritingBotService',
    'get_underwriting_bot_service',
    'init_underwriting_bot_service',
    'MetadataType',
    'ProcessingStatus',
    'ValidationStatus',
    'RiskLevel',
    'DecisionRecommendation',
    'AssessmentStatus',
    'UnderwritingMetadata',
    'ExtractedFeature',
    'RiskFactor',
    'RiskAssessmentReport',
    'BotAssessment',
    'PhotoAnalyzer',
    'MedicalReportAnalyzer',
    'OfficialDocumentAnalyzer',
    'AudioAnalyzer',
    'VideoAnalyzer',
    'RiskAssessmentEngine',
    'ALLOWED_UPLOAD_DIRS',
    'validate_file_path',
    'sanitize_filename',
]
