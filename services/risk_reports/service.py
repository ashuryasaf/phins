"""Risk Reports service (B9).

``AIRiskReportsService`` orchestrates intake (:mod:`.parsers`), analysis
(:mod:`.analysis`), report text (:mod:`.render`) and charts (:mod:`.charts`),
owns the durable stores (A4 ``artifact_store`` over ``agent_artifacts``),
authorisation, persistence and the agent-runtime registration. The historical
import path ``services.ai_risk_reports_service`` re-exports everything here.
"""

import json
import os
import random
import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from services.agent_metrics import instrument_agent
from services.hydrated_store import artifact_store
from services.risk_reports.analysis import AnalysisMixin, DataClassifier, LanguageDetector
from services.risk_reports.charts import ChartsMixin
from services.risk_reports.models import (
    AnalysisResult, Anomaly, ChartConfig, ChartType, DataType, Factor,
    GeneratedReport, Pattern, Priority, Recommendation, ReportSection, Severity,
    _risk_report_audit, logger,
)
from services.risk_reports.parsers import ParserMixin
from services.risk_reports.render import RenderMixin


class AIRiskReportsService(ParserMixin, AnalysisMixin, ChartsMixin, RenderMixin):
    """Main service for AI-powered risk and reports analysis"""
    
    def __init__(self):
        # Durable in DB mode (A4): rows in ``agent_artifacts`` (agent
        # ai_risk_reports) behind a read-through cache so uploads, analyses and
        # reports survive restarts and are visible to every web/worker
        # instance (the parsed rows travel with the document so a peer can run
        # the analysis). In memory mode these are per-instance dicts and the
        # JSON file in ``AI_REPORTS_DATA_FILE`` remains the persistence layer.
        self.documents: Dict[str, Dict] = artifact_store(
            'ai_risk_reports.documents', agent_id='ai_risk_reports', kind='document',
            subject=lambda d: ('owner', str(d.get('owner_id') or '') or None))
        self.analyses: Dict[str, AnalysisResult] = artifact_store(
            'ai_risk_reports.analyses', agent_id='ai_risk_reports', kind='analysis',
            record_type=AnalysisResult, subject=lambda a: ('document', a.document_id))
        self.reports: Dict[str, GeneratedReport] = artifact_store(
            'ai_risk_reports.reports', agent_id='ai_risk_reports', kind='report',
            record_type=GeneratedReport, subject=lambda r: ('analysis', r.analysis_id))

    def _durable(self) -> bool:
        return bool(getattr(self.documents, 'durable', False))

    def parse_file(self, filename: str, file_content: bytes, file_type: str, 
                   owner_id: str = None, owner_role: str = None) -> Dict[str, Any]:
        """
        Parse uploaded file and extract structured data.
        Supports CSV, XLS (as CSV), and ZIP containing CSV files.
        
        Args:
            filename: Name of the uploaded file
            file_content: Raw bytes of the file
            file_type: Type of file (csv, xls, xlsx, zip)
            owner_id: ID of the user who uploaded the file (for data isolation)
            owner_role: Role of the user (admin, customer, etc.)
        """
        doc_id = f"DOC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        result = {
            'document_id': doc_id,
            'filename': filename,
            'file_type': file_type,
            'file_size': len(file_content),
            'status': 'processing',
            'parsed_data': None,
            'error': None,
            'owner_id': owner_id,
            'owner_role': owner_role,
            'created_at': datetime.now().isoformat()
        }
        
        try:
            parsed, encoding = self.parse_content(filename, file_content, file_type)

            result['encoding'] = encoding
            result['parsed_data'] = parsed
            result['status'] = 'completed'
            result['row_count'] = len(parsed.get('rows', []))
            result['column_count'] = len(parsed.get('columns', []))
            
            # Store document
            self.documents[doc_id] = result
            
            # Auto-save for persistence
            self.save_data()

            _risk_report_audit('risk_report_document_uploaded', doc_id, {
                'row_count': result.get('row_count'),
                'column_count': result.get('column_count'),
                'status': result.get('status'),
            })
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result


    @instrument_agent('ai_risk_reports')
    def analyze(self, document_id: str) -> AnalysisResult:
        """
        Perform advanced AI/BI analysis on parsed document using inductive reasoning.
        
        This method learns from the uploaded data through:
        1. Statistical profiling of all columns
        2. Inductive pattern recognition
        3. Correlation analysis between fields
        4. Domain-specific semantic analysis
        5. Language-aware interpretation
        
        Returns comprehensive analysis with factors, patterns, and risk assessment.
        """
        start_time = datetime.now()
        
        if document_id not in self.documents:
            raise ValueError(f"Document {document_id} not found")
        
        doc = self.documents[document_id]
        parsed = doc.get('parsed_data', {})
        columns = parsed.get('columns', [])
        rows = parsed.get('rows', [])
        
        # =====================================================================
        # PHASE 1: INDUCTIVE DATA PROFILING
        # Learn the structure and semantics of the uploaded data
        # =====================================================================
        
        # Combine all text for language detection
        all_text = ' '.join(columns)
        for row in rows[:50]:  # Sample more rows for better detection
            all_text += ' ' + ' '.join(str(v) for v in row.values() if v)

        # B9: PDFs/images carry the text Document Intelligence extracted. The
        # document's own words decide its language and feed field extraction;
        # otherwise the Latin property names of the metadata table would
        # outweigh a Hebrew scan. Tabular uploads have no 'text' and are
        # analysed exactly as before.
        content_text = parsed.get('text') if isinstance(parsed.get('text'), str) else ''
        if content_text:
            all_text = content_text[:200_000] + '\n' + all_text
        
        # Detect language with confidence
        lang_code, lang_name, lang_confidence = LanguageDetector.detect(
            content_text[:20_000] if content_text else all_text)
        
        # Classify data type using semantic analysis
        data_type, type_confidence = DataClassifier.classify(columns, rows)
        
        # =====================================================================
        # PHASE 2: HEBREW DOCUMENT EXTRACTION (for Hebrew insurance documents)
        # Extract structured fields from Hebrew documents using pattern recognition
        # =====================================================================
        
        hebrew_extracted = {}
        # The extracted PDF/image text is scanned on its own: its page rows sit
        # after the metadata rows, so the row sample below never reaches them,
        # and a number-heavy or bilingual document can still detect as English.
        has_hebrew_content = bool(re.search(r'[\u0590-\u05FF]', content_text[:200_000]))
        if lang_code == 'hebrew' or has_hebrew_content or any(re.search(r'[\u0590-\u05FF]', str(v)) for row in rows[:10] for v in row.values()):
            hebrew_extracted = self._extract_hebrew_document_data(all_text, rows)
        
        # =====================================================================
        # PHASE 3: ADVANCED STATISTICAL ANALYSIS (BI)
        # Compute comprehensive statistics for each column
        # =====================================================================
        
        column_profiles = self._profile_columns(columns, rows)
        
        # =====================================================================
        # PHASE 4: CORRELATION & RELATIONSHIP DISCOVERY
        # Find relationships between different data fields
        # =====================================================================
        
        correlations = self._find_correlations(columns, rows, column_profiles)
        
        # =====================================================================
        # PHASE 5: INDUCTIVE PATTERN LEARNING
        # Discover patterns and rules from the data
        # =====================================================================
        
        # Extract factors with enhanced analysis
        factors = self._extract_factors_advanced(columns, rows, data_type, column_profiles)
        
        # Add Hebrew document factors if available
        if hebrew_extracted:
            factors.extend(self._create_hebrew_document_factors(hebrew_extracted, lang_code))
        
        # Find patterns using inductive reasoning
        patterns = self._find_patterns_advanced(rows, data_type, column_profiles, correlations)
        
        # Add Hebrew-specific patterns
        if hebrew_extracted:
            patterns.extend(self._find_hebrew_patterns(hebrew_extracted))
        
        # Detect anomalies with statistical backing
        anomalies = self._detect_anomalies_advanced(rows, data_type, column_profiles)

        # Identity master cross-check: an ID number read out of a customer's
        # own document that is not the identity recorded for that customer is
        # an anomaly for review (never used to change the record).
        identity_check = self._identity_cross_check(doc, hebrew_extracted, lang_code)
        if identity_check.get('anomaly') is not None:
            anomalies.append(identity_check['anomaly'])
        
        # =====================================================================
        # PHASE 6: DOMAIN-SPECIFIC INSIGHTS
        # Apply domain knowledge based on detected data type
        # =====================================================================
        
        domain_insights = self._generate_domain_insights(data_type, column_profiles, rows, lang_code, hebrew_extracted)
        
        # =====================================================================
        # PHASE 6: RISK ASSESSMENT
        # Calculate comprehensive risk score
        # =====================================================================
        
        risk_score = self._calculate_risk_score_advanced(
            factors, patterns, anomalies, correlations, domain_insights
        )
        
        # Generate language-aware summary with insights
        summary = self._generate_summary_advanced(
            lang_code, data_type, len(rows), factors, risk_score, 
            column_profiles, domain_insights
        )
        
        # Extract comprehensive key metrics
        key_metrics = self._extract_key_metrics_advanced(
            rows, columns, data_type, column_profiles, correlations, domain_insights
        )
        if identity_check.get('status'):
            key_metrics['identity_check'] = identity_check['status']
        
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        analysis_id = f"ANA-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        result = AnalysisResult(
            id=analysis_id,
            document_id=document_id,
            language=lang_code,
            language_name=lang_name,
            data_classification=data_type,
            extracted_factors=factors,
            patterns_found=patterns,
            anomalies=anomalies,
            risk_score=risk_score,
            confidence=min((lang_confidence + type_confidence) / 2, 1.0),
            processing_time_ms=processing_time,
            summary=summary,
            key_metrics=key_metrics
        )
        
        self.analyses[analysis_id] = result
        
        # Auto-save for persistence
        self.save_data()
        
        return result


    def _identity_cross_check(self, doc: Dict[str, Any], hebrew_extracted: Dict[str, Any],
                              lang_code: str) -> Dict[str, Any]:
        """Compare the ID number extracted from a document with the identity
        master of the customer who owns the document.

        Returns ``{'status': {...}, 'anomaly': Anomaly|None}``; ``status`` is a
        PII-free summary (``match`` / ``mismatch`` / ``no_master`` /
        ``not_applicable``) written to ``key_metrics``. Staff uploads have no
        owning customer, so nothing is compared.
        """
        extracted = str((hebrew_extracted or {}).get('id_number') or '').strip()
        owner_id = str(doc.get('owner_id') or '').strip()
        if not extracted or not owner_id or str(doc.get('owner_role') or '').lower() != 'customer':
            return {'status': None, 'anomaly': None}
        try:
            import sys
            from services import customer_identity_service as cis
            portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
            customers = getattr(portal, 'CUSTOMERS', None) if portal is not None else None
            record = customers.get(owner_id) if customers is not None and hasattr(customers, 'get') else None
        except Exception as exc:  # the identity master is advisory for a report
            logger.debug("identity cross-check unavailable: %s", exc)
            return {'status': None, 'anomaly': None}
        if not isinstance(record, dict) or not cis.is_complete(record):
            return {'status': {'result': 'no_master', 'customer_id': owner_id}, 'anomaly': None}
        same = cis.matches(record, extracted)
        status = {'result': 'match' if same else 'mismatch', 'customer_id': owner_id,
                  'document_id_last4': extracted[-4:], 'master_last4': record.get('national_id_last4')}
        if same:
            return {'status': status, 'anomaly': None}
        is_hebrew = lang_code == 'hebrew'
        return {'status': status, 'anomaly': Anomaly(
            type='identity_mismatch',
            severity=Severity.CRITICAL,
            description=("מספר הזהות במסמך אינו תואם את הזהות הרשומה של הלקוח"
                         if is_hebrew else
                         "The ID number in this document does not match the identity recorded for the customer"),
            affected_data=status,
            recommendation=("יש לוודא שהמסמך שייך ללקוח לפני שימוש בדוח"
                            if is_hebrew else
                            "Confirm the document belongs to this customer before relying on the report"),
        )}

    @instrument_agent('ai_risk_reports', decision_key='language')
    def generate_report(self, analysis_id: str, language: str = None) -> GeneratedReport:
        """Generate a comprehensive report from analysis results"""
        if analysis_id not in self.analyses:
            raise ValueError(f"Analysis {analysis_id} not found")
        
        analysis = self.analyses[analysis_id]
        lang = language or analysis.language
        
        report_id = f"RPT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        # Retrieve original document data for content analysis
        doc_data = None
        pension_data = None
        pension_report = None
        if analysis.document_id in self.documents:
            doc = self.documents[analysis.document_id]
            doc_data = doc.get('parsed_data', {})
            # Check for pension data from ZIP files
            if doc_data:
                pension_data = doc_data.get('pension_data')
                pension_report = doc_data.get('pension_report')
        
        # Build affiliated savings/coverage/ID summary for sections/charts/downloads
        affiliated_summary = self._extract_savings_cover_id_summary(doc_data, pension_data)

        # Generate sections based on data type (now with original data and pension data)
        sections = self._generate_sections(
            analysis,
            lang,
            doc_data,
            pension_data,
            pension_report,
            affiliated_summary
        )
        
        # Generate charts - pass pension_data and affiliated summary for specialized charts
        charts = self._generate_charts(analysis, pension_data, doc_data, affiliated_summary)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(analysis, lang)
        
        # Customer-facing title. Staff analysis labels ("דו״ח ניתוח נתונים")
        # stay out of the generated report and the download.
        titles = {
            'hebrew': {
                'insurance': 'הערכת הביטוח שלך',
                'investment': 'הערכת ההשקעות שלך',
                'risk': 'הערכת הסיכונים שלך',
                'savings': 'הערכת החיסכון שלך',
                'default': 'ההערכה שלך'
            },
            'english': {
                'insurance': 'Your Insurance Assessment',
                'investment': 'Your Investment Assessment',
                'risk': 'Your Risk Assessment',
                'savings': 'Your Savings Assessment',
                'default': 'Your Assessment'
            }
        }
        
        lang_titles = titles.get(lang, titles['english'])
        title = lang_titles.get(analysis.data_classification.value, lang_titles['default'])
        
        report = GeneratedReport(
            id=report_id,
            analysis_id=analysis_id,
            report_type=analysis.data_classification.value,
            language=lang,
            title=title,
            sections=sections,
            charts=charts,
            recommendations=recommendations,
            generated_at=datetime.now().isoformat(),
            metadata={
                'document_id': analysis.document_id,
                'risk_score': analysis.risk_score,
                'confidence': analysis.confidence,
                'processing_time_ms': analysis.processing_time_ms,
                'pension_data': pension_data if pension_data else None,
                'is_pension_data': pension_data is not None or pension_report is not None,
                'affiliation_snapshot': self._build_affiliation_snapshot_metadata(),
                'savings_cover_id_summary': affiliated_summary,
                'report_model': self._get_report_model_metadata(),
            }
        )
        
        self.reports[report_id] = report
        
        # Auto-save for persistence
        self.save_data()

        _risk_report_audit('risk_report_generated', report_id, {
            'analysis_id': analysis_id,
            'document_id': getattr(analysis, 'document_id', None),
            'language': lang,
        })
        
        return report


    def get_documents_for_user(self, user_id: str, user_role: str) -> List[Dict]:
        """
        Get all documents accessible to a user.
        Admins can see all documents, customers only see their own.
        
        Args:
            user_id: The user's ID
            user_role: The user's role (admin, customer, etc.)
            
        Returns:
            List of document metadata (without parsed_data for efficiency)
        """
        results = []
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        
        for doc_id, doc in self.documents.items():
            # Admin roles can see all documents
            if is_admin or doc.get('owner_id') == user_id:
                # Return summary without heavy parsed_data
                results.append({
                    'document_id': doc['document_id'],
                    'filename': doc['filename'],
                    'file_type': doc['file_type'],
                    'file_size': doc['file_size'],
                    'status': doc['status'],
                    'row_count': doc.get('row_count', 0),
                    'column_count': doc.get('column_count', 0),
                    'owner_id': doc.get('owner_id'),
                    'created_at': doc.get('created_at')
                })
        
        # Sort by created_at descending
        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return results
    
    def get_reports_for_user(self, user_id: str, user_role: str) -> List[Dict]:
        """
        Get all reports accessible to a user.
        Admins can see all reports, customers only see their own.
        
        Args:
            user_id: The user's ID
            user_role: The user's role
            
        Returns:
            List of report summaries
        """
        results = []
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        
        for report_id, report in self.reports.items():
            # Get the associated analysis to check ownership
            analysis = self.analyses.get(report.analysis_id)
            if not analysis:
                continue
            
            doc = self.documents.get(analysis.document_id)
            if not doc:
                continue
            
            # Check access permission
            if is_admin or doc.get('owner_id') == user_id:
                results.append({
                    'report_id': report.id,
                    'title': report.title,
                    'report_type': report.report_type,
                    'language': report.language,
                    'generated_at': report.generated_at,
                    'analysis_id': report.analysis_id,
                    'document_id': analysis.document_id,
                    'filename': doc.get('filename'),
                    'risk_score': report.metadata.get('risk_score'),
                    'confidence': report.metadata.get('confidence'),
                    'owner_id': doc.get('owner_id')
                })
        
        # Sort by generated_at descending
        results.sort(key=lambda x: x.get('generated_at', ''), reverse=True)
        return results

    def revoke_reports_for_date(self, user_id: str, user_role: str, target_date: date,
                                scope: str = "self") -> Dict[str, Any]:
        """
        Revoke (delete) reports generated on a specific date.
        Also removes orphaned analyses/documents when possible.

        Args:
            user_id: The requesting user ID
            user_role: The requesting user role
            target_date: Date to revoke (date object)
            scope: "self" (default) or "all" (admin only)

        Returns:
            Summary dict with counts of removed items.
        """
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        allow_all = is_admin and scope == "all"

        reports_to_remove = []
        analyses_to_check = set()
        documents_to_check = set()

        for report_id, report in list(self.reports.items()):
            report_dt = self._parse_report_datetime(report.generated_at)
            if not report_dt or report_dt.date() != target_date:
                continue

            analysis = self.analyses.get(report.analysis_id)
            if not analysis:
                continue

            doc = self.documents.get(analysis.document_id)
            if not doc:
                continue

            if not allow_all and doc.get('owner_id') != user_id:
                continue

            reports_to_remove.append(report_id)
            analyses_to_check.add(report.analysis_id)
            documents_to_check.add(analysis.document_id)

        # Remove reports
        for report_id in reports_to_remove:
            self.reports.pop(report_id, None)

        # Remove analyses not referenced by any remaining report
        analyses_removed = 0
        for analysis_id in analyses_to_check:
            if not any(r.analysis_id == analysis_id for r in self.reports.values()):
                self.analyses.pop(analysis_id, None)
                analyses_removed += 1

        # Remove documents not referenced by any remaining analysis
        documents_removed = 0
        for document_id in documents_to_check:
            if not any(a.document_id == document_id for a in self.analyses.values()):
                self.documents.pop(document_id, None)
                documents_removed += 1

        # Persist changes
        self.save_data()

        _risk_report_audit('risk_report_revoked', None, {
            'target_date': str(target_date),
            'reports_removed': len(reports_to_remove),
            'analyses_removed': analyses_removed,
            'documents_removed': documents_removed,
            'scope': scope,
            'user_id': user_id,
            'user_role': user_role,
        })

        return {
            'success': True,
            'target_date': target_date.isoformat(),
            'reports_removed': len(reports_to_remove),
            'analyses_removed': analyses_removed,
            'documents_removed': documents_removed
        }

    def _parse_report_datetime(self, date_str: str) -> Optional[datetime]:
        """Parse report datetime from stored string values."""
        if not date_str:
            return None
        try:
            if date_str.endswith('Z'):
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return datetime.fromisoformat(date_str)
        except ValueError:
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return None
    
    def authorize_access(self, resource_type: str, resource_id: str, 
                        user_id: str, user_role: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a user is authorized to access a specific resource.
        
        Args:
            resource_type: 'document', 'analysis', or 'report'
            resource_id: The ID of the resource
            user_id: The user's ID
            user_role: The user's role
            
        Returns:
            Tuple of (is_authorized, error_message)
        """
        is_admin = user_role in ['admin', 'actuary', 'underwriter', 'analyst']
        
        if is_admin:
            return True, None
        
        if resource_type == 'document':
            doc = self.documents.get(resource_id)
            if not doc:
                return False, f"Document {resource_id} not found"
            if doc.get('owner_id') != user_id:
                return False, "Access denied: You can only access your own documents"
            return True, None
        
        elif resource_type == 'analysis':
            analysis = self.analyses.get(resource_id)
            if not analysis:
                return False, f"Analysis {resource_id} not found"
            doc = self.documents.get(analysis.document_id)
            if not doc:
                return False, "Associated document not found"
            if doc.get('owner_id') != user_id:
                return False, "Access denied: You can only access your own analyses"
            return True, None
        
        elif resource_type == 'report':
            report = self.reports.get(resource_id)
            if not report:
                return False, f"Report {resource_id} not found"
            analysis = self.analyses.get(report.analysis_id)
            if not analysis:
                return False, "Associated analysis not found"
            doc = self.documents.get(analysis.document_id)
            if not doc:
                return False, "Associated document not found"
            if doc.get('owner_id') != user_id:
                return False, "Access denied: You can only access your own reports"
            return True, None
        
        return False, f"Unknown resource type: {resource_type}"
    
    def get_report_by_id(self, report_id: str, user_id: str = None, user_role: str = None) -> Optional[GeneratedReport]:
        """
        Get a specific report by ID with access control.
        
        Args:
            report_id: The report ID
            user_id: The requesting user's ID (for access control)
            user_role: The requesting user's role
            
        Returns:
            The report if found and authorized, None otherwise
        """
        if user_id and user_role:
            is_authorized, error = self.authorize_access('report', report_id, user_id, user_role)
            if not is_authorized:
                return None
        
        return self.reports.get(report_id)

    def build_report_download_summary(self, report_id: str, user_id: str, user_role: str) -> Dict[str, Any]:
        """
        Build a sanitized report summary payload for downloadable exports.
        This payload excludes source URLs/credentials and focuses on report metrics.
        """
        report = self.get_report_by_id(report_id, user_id=user_id, user_role=user_role)
        if not report:
            raise ValueError('Report not found or access denied')

        analysis = self.analyses.get(report.analysis_id)
        if not analysis:
            raise ValueError('Associated analysis not found')

        doc = self.documents.get(analysis.document_id, {}) if analysis.document_id else {}
        doc_data = doc.get('parsed_data', {}) if isinstance(doc, dict) else {}
        pension_data = doc_data.get('pension_data') if isinstance(doc_data, dict) else None
        if not pension_data and isinstance(report.metadata, dict):
            pension_data = report.metadata.get('pension_data')
        is_pension_data = bool(
            pension_data
            or (isinstance(report.metadata, dict) and report.metadata.get('is_pension_data'))
        )
        summary = self._extract_savings_cover_id_summary(doc_data, pension_data)

        from services.risk_reports.pdf_export import (
            customer_report_title,
            is_non_assessment_section_title,
            prepare_customer_download_charts,
            prepare_customer_download_recommendations,
            prepare_customer_download_sections,
            strip_completeness_copy,
        )

        table_sections: List[Dict[str, Any]] = []
        assessment_sections: List[Dict[str, Any]] = []
        for section in report.sections:
            section_title = section.title or ''
            title_lower = section_title.lower()
            if 'swiftness' in title_lower or 'resource' in title_lower:
                continue
            if is_non_assessment_section_title(section_title):
                continue

            data_table = section.data_table if isinstance(section.data_table, dict) else {}
            columns = data_table.get('columns', []) if data_table else []
            rows = data_table.get('rows', []) if data_table else []
            if not isinstance(rows, list):
                rows = []
            assessment_sections.append({
                'title': section_title,
                'content': strip_completeness_copy(section.content or ''),
                'columns': [str(c) for c in columns] if isinstance(columns, list) else [],
                'rows': [row for row in rows[:80] if isinstance(row, dict)],
            })

            if not section.data_table:
                continue

            data_table = section.data_table if isinstance(section.data_table, dict) else {}
            columns = data_table.get('columns', [])
            rows = data_table.get('rows', [])

            # Support key/value maps (e.g. key metrics) in addition to tabular structures.
            if not isinstance(rows, list):
                rows = []
            if not rows and data_table:
                rows = [{'Metric': key, 'Value': value} for key, value in data_table.items() if not isinstance(value, dict)]
                columns = ['Metric', 'Value']

            cleaned_rows: List[Dict[str, Any]] = []
            for row in rows[:80]:
                if not isinstance(row, dict):
                    continue
                cleaned_row = {}
                for key, value in row.items():
                    if isinstance(value, str):
                        cleaned_value = re.sub(r'https?://\S+', '[redacted]', value)
                    else:
                        cleaned_value = value
                    cleaned_row[str(key)] = cleaned_value
                cleaned_rows.append(cleaned_row)

            if not isinstance(columns, list) or not columns:
                columns = list(cleaned_rows[0].keys()) if cleaned_rows else []

            table_sections.append({
                'title': section_title,
                'columns': [str(c) for c in columns],
                'rows': cleaned_rows
            })

        chart_summaries: List[Dict[str, Any]] = []
        for chart in report.charts:
            chart_data = chart.data if isinstance(chart.data, dict) else {}
            labels = chart_data.get('labels', [])
            values = chart_data.get('values', [])
            if isinstance(labels, list) and isinstance(values, list):
                series = [
                    {
                        'label': str(label),
                        'value': values[index] if index < len(values) else None
                    }
                    for index, label in enumerate(labels[:30])
                ]
            else:
                series = [{'label': 'value', 'value': chart_data.get('value')}]

            chart_type = chart.type.value if isinstance(chart.type, Enum) else str(chart.type)
            chart_summaries.append({
                'title': chart.title,
                'type': chart_type,
                'series': series
            })

        recommendations = [{
            'priority': rec.priority.value if isinstance(rec.priority, Enum) else str(rec.priority),
            'title': rec.title,
            'description': rec.description,
            'action_items': rec.action_items,
            'expected_impact': rec.expected_impact,
        } for rec in report.recommendations]

        pension_assessment: Optional[Dict[str, Any]] = None
        if is_pension_data:
            client = {}
            totals = {}
            accounts: List[Dict[str, Any]] = []
            if isinstance(pension_data, dict):
                client = pension_data.get('client') or {}
                if isinstance(client, list):
                    client = client[0] if client else {}
                if not isinstance(client, dict):
                    client = {}
                totals = pension_data.get('totals') or pension_data.get('summary') or {}
                if not isinstance(totals, dict):
                    totals = {}
                for acct in (pension_data.get('accounts') or [])[:80]:
                    if not isinstance(acct, dict):
                        continue
                    # Copy the stored amounts — never re-sum or invent values.
                    accounts.append({
                        'policy_number': acct.get('policy_number', ''),
                        'provider': acct.get('provider', ''),
                        'product_type': acct.get('product_type', ''),
                        'product_type_name': acct.get('product_type_name', acct.get('product_name', '')),
                        'status': acct.get('status', ''),
                        'total_balance': acct.get('total_balance', acct.get('savings_balance', 0)),
                        'savings_balance': acct.get('savings_balance', 0),
                        'severance_balance': acct.get('severance_balance', 0),
                        'employer_name': acct.get('employer_name', ''),
                    })
            if not client.get('id_number') and summary.get('customer_id'):
                client = dict(client)
                client['id_number'] = summary.get('customer_id')
            if not client.get('birth_date') and summary.get('birth_date'):
                client = dict(client)
                client['birth_date'] = summary.get('birth_date')
            pension_assessment = {
                'client': client,
                'totals': {
                    'total_balance': totals.get('total_balance', summary.get('total_savings', 0)),
                    'total_savings': totals.get('total_savings', totals.get('total_savings_balance', 0)),
                    'total_severance': totals.get(
                        'total_severance',
                        totals.get('total_severance_balance', summary.get('total_severance', 0)),
                    ),
                    'account_count': totals.get('account_count', len(accounts)),
                },
                'accounts': accounts,
            }

        # Customer download: omit staff completeness / integrity notes.
        download_summary = dict(summary or {})
        download_summary.pop('integrity_issues', None)

        payload = {
            'report_id': report.id,
            'title': report.title,
            'language': report.language,
            'generated_at': report.generated_at,
            'report_type': report.report_type,
            'risk_score': report.metadata.get('risk_score'),
            'confidence': report.metadata.get('confidence'),
            'is_pension_data': is_pension_data,
            'pension_assessment': pension_assessment,
            'assessment_sections': assessment_sections,
            'savings_cover_id_summary': download_summary,
            'table_sections': table_sections,
            'chart_summaries': chart_summaries,
            'recommendations': recommendations,
        }
        payload['title'] = customer_report_title(payload)
        payload['assessment_sections'] = prepare_customer_download_sections(
            payload.get('assessment_sections')
        )
        payload['table_sections'] = [
            section for section in payload.get('table_sections') or []
            if not is_non_assessment_section_title(section.get('title', ''))
        ]
        payload['chart_summaries'] = prepare_customer_download_charts(
            payload.get('chart_summaries')
        )
        payload['recommendations'] = prepare_customer_download_recommendations(
            payload.get('recommendations')
        )
        return payload
    
    def to_dict(self, obj) -> Dict:
        """Convert dataclass objects to dictionaries for JSON serialization"""
        if hasattr(obj, '__dataclass_fields__'):
            result = {}
            for field_name in obj.__dataclass_fields__:
                value = getattr(obj, field_name)
                result[field_name] = self.to_dict(value)
            return result
        elif isinstance(obj, list):
            return [self.to_dict(item) for item in obj]
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, dict):
            return {k: self.to_dict(v) for k, v in obj.items()}
        else:
            return obj


    # =========================================================================
    # PERSISTENCE - Save and Load Data
    # =========================================================================
    
    def save_data(self, filepath: str = None) -> bool:
        """
        Save all documents, analyses, and reports to a JSON file.
        
        Args:
            filepath: Optional custom filepath. Defaults to AI_REPORTS_DATA_FILE.
            
        Returns:
            True if successful, False otherwise
        """
        if filepath is None:
            if self._durable():
                # The agent_artifacts table is the store in DB mode; every
                # write above already went through it.
                return True
            filepath = AI_REPORTS_DATA_FILE
        
        try:
            # Convert analyses to serializable format
            analyses_data = {}
            for aid, analysis in self.analyses.items():
                analyses_data[aid] = self.to_dict(analysis)
            
            # Convert reports to serializable format
            reports_data = {}
            for rid, report in self.reports.items():
                reports_data[rid] = self.to_dict(report)
            
            # Prepare documents (remove parsed_data to save space - can be re-parsed)
            documents_data = {}
            for did, doc in self.documents.items():
                doc_copy = doc.copy()
                # Keep only metadata, not the full parsed data
                if 'parsed_data' in doc_copy:
                    doc_copy['has_parsed_data'] = doc_copy['parsed_data'] is not None
                    # Store column info but not full row data to save space
                    if doc_copy['parsed_data']:
                        doc_copy['columns'] = doc_copy['parsed_data'].get('columns', [])
                    del doc_copy['parsed_data']
                documents_data[did] = doc_copy
            
            data = {
                'saved_at': datetime.now().isoformat(),
                'version': '1.0',
                'documents': documents_data,
                'analyses': analyses_data,
                'reports': reports_data,
                'stats': {
                    'total_documents': len(self.documents),
                    'total_analyses': len(self.analyses),
                    'total_reports': len(self.reports)
                }
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
            
            # Write to temp file first for atomic operation
            temp_file = filepath + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, default=str, indent=2, ensure_ascii=False)
            
            # Atomic rename
            os.rename(temp_file, filepath)
            print(f"[AI_REPORTS] Saved data to {filepath} ({len(self.documents)} docs, {len(self.analyses)} analyses, {len(self.reports)} reports)")
            return True
            
        except Exception as e:
            print(f"[AI_REPORTS] Error saving data: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def load_data(self, filepath: str = None) -> bool:
        """
        Load documents, analyses, and reports from a JSON file.
        
        Args:
            filepath: Optional custom filepath. Defaults to AI_REPORTS_DATA_FILE.
            
        Returns:
            True if successful, False otherwise
        """
        if filepath is None:
            filepath = AI_REPORTS_DATA_FILE
            if self._durable() and (len(self.documents) or len(self.analyses) or len(self.reports)):
                # DB mode with durable rows present: the table is the source
                # of truth; the legacy JSON file is only read once to migrate
                # a pre-A4 deployment whose table is still empty.
                return True
        
        if not os.path.exists(filepath):
            print(f"[AI_REPORTS] No saved data file found at {filepath}")
            return False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Load documents
            documents_data = data.get('documents', {})
            for did, doc in documents_data.items():
                # Restore minimal document structure
                doc['parsed_data'] = None  # Will need to re-upload to re-parse
                self.documents[did] = doc
            
            # Load analyses - reconstruct AnalysisResult objects
            analyses_data = data.get('analyses', {})
            for aid, analysis_dict in analyses_data.items():
                try:
                    # Reconstruct factors
                    factors = [Factor(**f) for f in analysis_dict.get('extracted_factors', [])]
                    
                    # Reconstruct patterns
                    patterns = [Pattern(**p) for p in analysis_dict.get('patterns_found', [])]
                    
                    # Reconstruct anomalies
                    anomalies = []
                    for a in analysis_dict.get('anomalies', []):
                        a_copy = a.copy()
                        a_copy['severity'] = Severity(a_copy['severity'])
                        anomalies.append(Anomaly(**a_copy))
                    
                    # Reconstruct analysis
                    analysis = AnalysisResult(
                        id=analysis_dict['id'],
                        document_id=analysis_dict['document_id'],
                        language=analysis_dict['language'],
                        language_name=analysis_dict['language_name'],
                        data_classification=DataType(analysis_dict['data_classification']),
                        extracted_factors=factors,
                        patterns_found=patterns,
                        anomalies=anomalies,
                        risk_score=analysis_dict['risk_score'],
                        confidence=analysis_dict['confidence'],
                        processing_time_ms=analysis_dict['processing_time_ms'],
                        summary=analysis_dict['summary'],
                        key_metrics=analysis_dict['key_metrics']
                    )
                    self.analyses[aid] = analysis
                except Exception as e:
                    print(f"[AI_REPORTS] Error loading analysis {aid}: {e}")
            
            # Load reports - reconstruct GeneratedReport objects
            reports_data = data.get('reports', {})
            for rid, report_dict in reports_data.items():
                try:
                    # Reconstruct sections
                    sections = [ReportSection(**s) for s in report_dict.get('sections', [])]
                    
                    # Reconstruct charts
                    charts = []
                    for c in report_dict.get('charts', []):
                        c_copy = c.copy()
                        c_copy['type'] = ChartType(c_copy['type'])
                        charts.append(ChartConfig(**c_copy))
                    
                    # Reconstruct recommendations
                    recommendations = []
                    for r in report_dict.get('recommendations', []):
                        r_copy = r.copy()
                        r_copy['priority'] = Priority(r_copy['priority'])
                        recommendations.append(Recommendation(**r_copy))
                    
                    # Reconstruct report
                    report = GeneratedReport(
                        id=report_dict['id'],
                        analysis_id=report_dict['analysis_id'],
                        report_type=report_dict['report_type'],
                        language=report_dict['language'],
                        title=report_dict['title'],
                        sections=sections,
                        charts=charts,
                        recommendations=recommendations,
                        generated_at=report_dict['generated_at'],
                        metadata=report_dict.get('metadata', {})
                    )
                    self.reports[rid] = report
                except Exception as e:
                    print(f"[AI_REPORTS] Error loading report {rid}: {e}")
            
            print(f"[AI_REPORTS] Loaded data from {filepath} ({len(self.documents)} docs, {len(self.analyses)} analyses, {len(self.reports)} reports)")
            return True
            
        except Exception as e:
            print(f"[AI_REPORTS] Error loading data: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_persistence_stats(self) -> Dict[str, Any]:
        """Get statistics about stored data"""
        return {
            'total_documents': len(self.documents),
            'total_analyses': len(self.analyses),
            'total_reports': len(self.reports),
            'documents_by_owner': self._count_by_owner(self.documents),
            'reports_by_type': self._count_by_type()
        }
    
    def _count_by_owner(self, collection: Dict) -> Dict[str, int]:
        """Count items by owner"""
        counts = {}
        for item in collection.values():
            owner = item.get('owner_id', 'unknown')
            counts[owner] = counts.get(owner, 0) + 1
        return counts
    
    def _count_by_type(self) -> Dict[str, int]:
        """Count reports by type"""
        counts = {}
        for report in self.reports.values():
            rtype = report.report_type
            counts[rtype] = counts.get(rtype, 0) + 1
        return counts


# Persistence file path (in-memory mode). Rebound at runtime by tests through
# the ``services.ai_risk_reports_service`` facade, which forwards to this module.
AI_REPORTS_DATA_FILE = os.environ.get('AI_REPORTS_DATA_FILE', 'data/ai_reports_data.json')

# Singleton instance
_ai_reports_service: AIRiskReportsService = None


def get_ai_reports_service() -> AIRiskReportsService:
    """Get or create the AI reports service singleton, loading saved data if available"""
    global _ai_reports_service
    if _ai_reports_service is None:
        _ai_reports_service = AIRiskReportsService()
        # Load persisted data on first access
        _ai_reports_service.load_data()
    return _ai_reports_service


def init_ai_reports_service(load_persisted: bool = True) -> AIRiskReportsService:
    """
    Initialize the AI reports service.
    
    Args:
        load_persisted: If True, load previously saved data from disk.
                       Set to False for testing with fresh state.
    """
    global _ai_reports_service
    _ai_reports_service = AIRiskReportsService()
    if load_persisted:
        _ai_reports_service.load_data()
    return _ai_reports_service


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# ---------------------------------------------------------------------------
def _risk_reports_health() -> Dict[str, Any]:
    """Read-only probe: never instantiates the service or loads persisted data."""
    instance = _ai_reports_service
    if instance is None:
        return {'status': 'ok', 'initialized': False}
    def _cached(store) -> int:
        # Probe the cache, not the table: a health check must not issue queries.
        return store.snapshot()['cached'] if hasattr(store, 'snapshot') else len(store or {})

    documents = getattr(instance, 'documents', {})
    return {
        'status': 'ok',
        'initialized': True,
        'documents': _cached(documents),
        'analyses': _cached(getattr(instance, 'analyses', {})),
        'reports': _cached(getattr(instance, 'reports', {})),
        'durable': bool(getattr(documents, 'durable', False)),
    }


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='ai_risk_reports',
        name='AI Risk Reports',
        version='1.0.0',
        # Historical import path; the package is an implementation detail.
        module='services.ai_risk_reports_service',
        description=(
            'Ingests uploaded CSV/XLS/ZIP documents and produces statistical '
            'risk analyses and bilingual reports with charts and recommendations.'
        ),
        entry_url='/risk-reports-dashboard.html',
        api={'method': 'POST', 'path': '/api/reports/generate'},
        roles=('admin', 'underwriter', 'analyst', 'actuary'),
        deterministic=True,
        sample_prompts=(
            'Analyze this policy export and generate a risk report',
        ),
    ), health_fn=_risk_reports_health)
except Exception as _reg_exc:  # pragma: no cover
    logger.warning("AI risk reports agent registration skipped: %s", _reg_exc)

