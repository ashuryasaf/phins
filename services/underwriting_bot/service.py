"""
Underwriting Bot — service orchestration (B1 split).

:class:`UnderwritingBotService` runs the assessment lifecycle (start, add
evidence, process, score, decide) over durable artifact stores, logs every
recommendation to the AI decision log (with the shadow model score when a
``uw_scorer`` artifact exists) and never modifies customer data.
"""

from datetime import datetime, date
from typing import Dict, List, Any, Optional

import hashlib
import threading
import uuid
import logging

from services.hydrated_store import artifact_store
from services.agent_metrics import instrument_agent
from services.underwriting_bot.report import (
    MetadataType, ProcessingStatus, ValidationStatus, AssessmentStatus, UnderwritingMetadata,
    RiskAssessmentReport, BotAssessment, RiskAssessmentEngine,
)
from services.underwriting_bot.features import (
    validate_file_path, sanitize_filename,
    PhotoAnalyzer, MedicalReportAnalyzer, OfficialDocumentAnalyzer, AudioAnalyzer, VideoAnalyzer,
)

_logger = logging.getLogger('phins.underwriting_bot')


class UnderwritingBotService:
    """
    Main Underwriting Bot Service.
    
    Orchestrates the entire underwriting assessment process:
    1. Receives metadata (photos, documents, medical reports, audio, video)
    2. Processes and validates all metadata
    3. Extracts features from each metadata type
    4. Calculates risk scores using AI engine
    5. Generates comprehensive risk assessment reports
    6. Makes or recommends underwriting decisions
    
    IMPORTANT: This service NEVER modifies existing customer data.

    Retention: the bot's own artifacts are advisory (the authoritative
    decision lives on the underwriting application), so at most
    ``MAX_RETAINED_ASSESSMENTS`` assessments/reports are kept — a DB-side
    prune in durable mode, oldest-first eviction in memory mode.
    All customer data (details, transactions, investments, claims) is READ-ONLY.
    """
    
    def __init__(self,
                 customers: Dict = None,
                 policies: Dict = None,
                 underwriting_apps: Dict = None,
                 claims: Dict = None,
                 audit_service = None,
                 pipeline_service = None):
        """
        Initialize the Underwriting Bot Service.
        
        Args:
            customers: CUSTOMERS data store (READ-ONLY access)
            policies: POLICIES data store (READ-ONLY for existing, write for new UW status)
            underwriting_apps: UNDERWRITING_APPLICATIONS data store
            claims: CLAIMS data store (READ-ONLY for history)
            audit_service: Audit service for logging
            pipeline_service: Pipeline service for workflow integration
        """
        self.bot_id = f"UW-BOT-{uuid.uuid4().hex[:8]}"
        self.version = "1.0.0"
        
        # Data stores (preserving references, never resetting). An empty
        # portal dict is still the live dict: keep the reference so records
        # added after start-up are visible and the accessor can recognise it.
        self._customers = customers if customers is not None else {}
        self._policies = policies if policies is not None else {}
        self._underwriting = underwriting_apps if underwriting_apps is not None else {}
        self._claims = claims if claims is not None else {}
        self._audit = audit_service
        self._pipeline = pipeline_service
        
        # Bot-specific data stores (new data only). Durable in DB mode (A4):
        # rows in ``agent_artifacts`` (agent underwriting_bot) behind a
        # read-through cache, so a multi-step assessment survives a restart
        # and any web/worker instance can continue it. Every step method
        # re-reads its assessment from the store and checkpoints it at the
        # end, because a hydrated object is a copy, not the one mutated here.
        self.assessments: Dict[str, BotAssessment] = artifact_store(
            'underwriting_bot.assessments', agent_id='underwriting_bot', kind='assessment',
            record_type=BotAssessment, subject=lambda a: ('application', a.underwriting_id))
        self.metadata_store: Dict[str, UnderwritingMetadata] = artifact_store(
            'underwriting_bot.metadata', agent_id='underwriting_bot', kind='metadata',
            record_type=UnderwritingMetadata, subject=lambda m: ('application', m.underwriting_id))
        self.reports: Dict[str, RiskAssessmentReport] = artifact_store(
            'underwriting_bot.reports', agent_id='underwriting_bot', kind='risk_report',
            record_type=RiskAssessmentReport, subject=lambda r: ('application', r.underwriting_id))
        
        # Initialize analyzers
        self.photo_analyzer = PhotoAnalyzer()
        self.medical_analyzer = MedicalReportAnalyzer()
        self.document_analyzer = OfficialDocumentAnalyzer()
        self.audio_analyzer = AudioAnalyzer()
        self.video_analyzer = VideoAnalyzer()
        
        # Initialize risk engine
        self.risk_engine = RiskAssessmentEngine()
        
        self._log_event('system', 'bot_initialized', 'underwriting_bot', self.bot_id, {
            'version': self.version
        })
    
    def _log_event(self, actor: str, action: str, entity: str, entity_id: str, details: Dict = None):
        """Log event to audit service"""
        if self._audit:
            try:
                self._audit.log(actor, action, entity, entity_id, details or {})
            except:
                pass
        print(f"[UW-BOT] {action}: {entity}:{entity_id}")
    
    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique = uuid.uuid4().hex[:6].upper()
        return f"{prefix}-{timestamp}-{unique}"
    
    # =========================================================================
    # Assessment Lifecycle
    # =========================================================================
    
    def start_assessment(self, 
                        underwriting_id: str,
                        customer_id: str,
                        policy_id: str) -> BotAssessment:
        """
        Start a new bot assessment session.
        
        This creates a new assessment without modifying any existing customer data.
        Customer data is read-only and snapshotted for reference.
        """
        assessment_id = self._generate_id('BOT-ASS')
        
        # Read-only snapshot of customer data (NEVER MODIFIED)
        customer = self._customers.get(customer_id, {})
        customer_snapshot = {
            'name': customer.get('name', ''),
            'email': customer.get('email', ''),
            'age': customer.get('age', 0),
            'occupation': customer.get('occupation', ''),
            'snapshot_date': datetime.now().isoformat()
        }
        
        # Count existing policies and claims (READ-ONLY)
        existing_policies = sum(1 for p in self._policies.values() 
                               if p.get('customer_id') == customer_id)
        existing_claims = sum(1 for c in self._claims.values() 
                            if c.get('customer_id') == customer_id)
        
        assessment = BotAssessment(
            id=assessment_id,
            underwriting_id=underwriting_id,
            customer_id=customer_id,
            policy_id=policy_id,
            status=AssessmentStatus.INITIATED,
            customer_snapshot=customer_snapshot,
            existing_policies_count=existing_policies,
            existing_claims_count=existing_claims
        )
        
        self.assessments[assessment_id] = assessment
        
        self._log_event('bot', 'assessment_started', 'assessment', assessment_id, {
            'underwriting_id': underwriting_id,
            'customer_id': customer_id,
            'existing_policies': existing_policies,
            'existing_claims': existing_claims
        })
        self._enforce_retention()
        
        return assessment

    MAX_RETAINED_ASSESSMENTS = 5000

    def _enforce_retention(self) -> None:
        """Cap the bot's artifact stores (see class docstring)."""
        cap = self.MAX_RETAINED_ASSESSMENTS
        try:
            if getattr(self.assessments, 'durable', False):
                self.assessments.prune_durable(cap)
                self.reports.prune_durable(cap)
                self.metadata_store.prune_durable(cap * 10)
                return
            for store, key in ((self.assessments, lambda a: a.started_at),
                               (self.reports, lambda r: r.created_date),
                               (self.metadata_store, lambda m: m.created_date)):
                limit = cap * 10 if store is self.metadata_store else cap
                overflow = len(store) - limit
                if overflow > 0:
                    for item in sorted(store.values(), key=key)[:overflow]:
                        store.pop(item.id, None)
        except Exception as exc:
            _logger.warning("underwriting_bot retention enforcement failed: %s", exc)
    
    def add_metadata(self,
                    assessment_id: str,
                    metadata_type: MetadataType,
                    file_name: str,
                    file_path: str,
                    file_content: bytes = None,
                    mime_type: str = "",
                    expiry_date: date = None,
                    document_id: Optional[str] = None) -> UnderwritingMetadata:
        """
        Add metadata item to assessment.
        
        This creates a new metadata record - never modifies customer data.
        
        Security: File paths are validated to prevent path traversal attacks.

        ``document_id`` links the item to a Document Intelligence record; its
        facts (with provenance) are then consumed by ``process_metadata``.
        """
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        
        # SECURITY: Validate and sanitize file path
        safe_file_name = sanitize_filename(file_name)
        is_valid, safe_path, error = validate_file_path(file_path, safe_file_name)
        if not is_valid:
            raise ValueError(f"Invalid file path: {error}")
        
        # Update assessment status
        if assessment.status == AssessmentStatus.INITIATED:
            assessment.status = AssessmentStatus.COLLECTING_METADATA
        
        # Calculate file hash for integrity
        file_hash = hashlib.sha256(file_content or b'').hexdigest() if file_content else ""
        file_size = len(file_content) if file_content else 0
        
        metadata_id = self._generate_id('META')
        metadata = UnderwritingMetadata(
            id=metadata_id,
            underwriting_id=assessment.underwriting_id,
            customer_id=assessment.customer_id,
            metadata_type=metadata_type,
            file_name=safe_file_name,  # Use sanitized filename
            file_path=safe_path,  # Use validated path
            file_hash=file_hash,
            file_size_bytes=file_size,
            mime_type=mime_type,
            upload_date=datetime.now(),
            document_id=(str(document_id).strip() or None) if document_id else None,
        )
        
        assessment.metadata_items.append(metadata)
        self.metadata_store[metadata_id] = metadata
        self._checkpoint(assessment)
        
        self._log_event('bot', 'metadata_added', 'metadata', metadata_id, {
            'assessment_id': assessment_id,
            'type': metadata_type.value,
            'file_name': file_name
        })
        
        return metadata
    
    def process_metadata(self, metadata_id: str, file_content: bytes = None,
                         assessment: Optional['BotAssessment'] = None) -> Dict[str, Any]:
        """
        Process a single metadata item through appropriate analyzer.

        ``assessment`` lets ``process_all_metadata`` pass the object it is
        mutating so the processed item is synced into that same object.
        """
        metadata = self.metadata_store.get(metadata_id)
        if not metadata:
            return {'success': False, 'error': 'Metadata not found'}
        
        metadata.processing_status = ProcessingStatus.PROCESSING
        metadata.updated_date = datetime.now()
        
        try:
            result = self._analyze_with_cache(metadata, file_content)
            self._merge_evidence_facts(metadata, result)
            
            # Update metadata with results
            if result.get('processing_success'):
                metadata.processing_status = ProcessingStatus.COMPLETED
                metadata.processing_result = result
                metadata.extracted_data = result.get('extracted_fields', result.get('features', {}))
                _scores = result.get('scores', {}) or {}
                _conf = _scores.get('authenticity_score')
                if _conf is None:
                    _conf = _scores.get('quality_score')
                if _conf is None:
                    _conf = _scores.get('completeness_score')
                if _conf is None:
                    _conf = _scores.get('identity_confidence')
                metadata.confidence_score = float(_conf) if _conf is not None else 0.0
                
                # Set validation status
                if result.get('flags'):
                    if 'DOCUMENT_EXPIRED' in result['flags'] or 'LIVENESS_FAILED' in result['flags']:
                        metadata.validation_status = ValidationStatus.INVALID
                    elif any('SUSPICIOUS' in f or 'FRAUD' in f for f in result['flags']):
                        metadata.validation_status = ValidationStatus.SUSPICIOUS
                    else:
                        metadata.validation_status = ValidationStatus.VALID
                else:
                    metadata.validation_status = ValidationStatus.VALID
            else:
                metadata.processing_status = ProcessingStatus.FAILED
                metadata.validation_status = ValidationStatus.INVALID
                metadata.validation_notes = result.get('error', 'Processing failed')
            
            metadata.updated_date = datetime.now()
            self._sync_metadata(metadata, assessment)
            return {'success': True, 'result': result}
            
        except Exception as e:
            metadata.processing_status = ProcessingStatus.FAILED
            metadata.validation_notes = str(e)
            metadata.updated_date = datetime.now()
            self._sync_metadata(metadata, assessment)
            return {'success': False, 'error': str(e)}

    # Analyzer results whose flags mean "degraded because a provider was
    # missing/failing" are not cached: enabling STT later must take effect.
    _UNCACHEABLE_FLAGS = ('NO_STT_AVAILABLE', 'STT_FAILED', 'MISSING_CONTENT')

    def _run_analyzer(self, metadata: UnderwritingMetadata, file_content: Optional[bytes]) -> Dict[str, Any]:
        if metadata.metadata_type == MetadataType.PHOTO:
            return self.photo_analyzer.analyze(metadata, file_content)
        if metadata.metadata_type == MetadataType.MEDICAL_REPORT:
            return self.medical_analyzer.analyze(metadata, file_content)
        if metadata.metadata_type in (MetadataType.PASSPORT, MetadataType.DRIVING_LICENCE,
                                      MetadataType.NATIONAL_INSURANCE, MetadataType.DISABILITY_CERTIFICATE):
            return self.document_analyzer.analyze(metadata, file_content, metadata.metadata_type.value)
        if metadata.metadata_type == MetadataType.AUDIO:
            return self.audio_analyzer.analyze(metadata, file_content)
        if metadata.metadata_type == MetadataType.VIDEO:
            return self.video_analyzer.analyze(metadata, file_content)
        return {'processing_success': False, 'error': 'Unsupported metadata type'}

    def _analyze_with_cache(self, metadata: UnderwritingMetadata,
                            file_content: Optional[bytes]) -> Dict[str, Any]:
        """Run the analyzer for ``metadata``, reusing a SHA-keyed cached result.

        The key is ``(analyzer, sha256(bytes))`` so only byte-identical
        evidence can hit; the cached value is deep-copied by the cache.
        Analyzers that depend on expiry dates are keyed by day as well so a
        document cannot stay "valid" in cache past its expiry.
        """
        if not file_content:
            return self._run_analyzer(metadata, file_content)
        sha = metadata.file_hash or hashlib.sha256(file_content).hexdigest()
        namespace = f"uw:{metadata.metadata_type.value}:{datetime.now().date().isoformat()}"
        try:
            from services.evidence_facts import get_feature_cache
            cache = get_feature_cache()
        except Exception:  # cache is an optimisation, never a dependency
            return self._run_analyzer(metadata, file_content)
        cached, hit = cache.get(namespace, sha)
        if hit:
            cached['feature_cache'] = 'hit'
            return cached
        result = self._run_analyzer(metadata, file_content)
        flags = result.get('flags') or []
        if result.get('processing_success') and not any(f in self._UNCACHEABLE_FLAGS for f in flags):
            cache.put(namespace, sha, result)
        result['feature_cache'] = 'miss'
        return result

    _EVIDENCE_SKIP_TYPES = ('document_meta', 'extraction_hint', 'contradiction')
    # Analyzer flags meaning "nothing to parse" (as opposed to a real failure).
    _NO_BYTES_FLAGS = ('MISSING_CONTENT', 'NO_CONTENT', 'NO_TEXT_CONTENT')

    def _merge_evidence_facts(self, metadata: UnderwritingMetadata, result: Dict[str, Any]) -> None:
        """Consume Document Intelligence facts for ``metadata.document_id``.

        Facts never overwrite what the analyzer extracted from the bytes; they
        fill gaps (and can stand alone when no bytes were supplied). Each fact
        is attached with its provenance. A recorded cross-document
        contradiction flags the item ``SUSPICIOUS_EVIDENCE_CONTRADICTION`` so
        it lands in human review — the conflict itself is never resolved here.
        """
        doc_id = getattr(metadata, 'document_id', None)
        if not doc_id:
            return
        try:
            from services.evidence_facts import bundle_for, provenance_of
            bundle = bundle_for([doc_id])
        except Exception as exc:
            _logger.warning("evidence bundle unavailable for %s: %s", doc_id, exc)
            return
        result['evidence'] = bundle.to_dict()
        if not bundle.facts and not bundle.contradictions:
            return
        facts = [f for f in bundle.facts if f.get('fact_type') not in self._EVIDENCE_SKIP_TYPES]
        result['evidence_facts'] = [{
            'fact_type': f.get('fact_type'), 'label': f.get('label'), 'value': f.get('value'),
            'confidence': f.get('confidence'), 'provenance': provenance_of(f),
        } for f in facts[:200]]
        flags = result.setdefault('flags', [])
        fields_key = 'extracted_fields' if 'extracted_fields' in result or 'features' not in result else 'features'
        fields = result.get(fields_key)
        if not isinstance(fields, dict):
            fields = {}
            result[fields_key] = fields
        for f in facts:
            label = f.get('label')
            if label and label not in fields:
                fields[label] = f.get('value')
        if facts:
            flags.append('EVIDENCE_FROM_DOCUMENT_PIPELINE')
            scores = result.get('scores')
            if not isinstance(scores, dict):
                scores = {}
                result['scores'] = scores
            top = max(float(f.get('confidence') or 0.0) for f in facts)
            scores['evidence_confidence'] = round(top, 3)
            if (not any(scores.get(k) is not None for k in
                        ('authenticity_score', 'quality_score', 'identity_confidence'))
                    and not scores.get('completeness_score')):
                scores['completeness_score'] = round(top, 3)
            if not result.get('processing_success') and any(
                    f in flags for f in self._NO_BYTES_FLAGS):
                # No bytes were supplied but the pipeline already extracted
                # the document: the facts are the evidence.
                result['processing_success'] = True
                result.pop('error', None)
        if bundle.extraction_incomplete():
            flags.append('EVIDENCE_EXTRACTION_INCOMPLETE')
        if bundle.contradictions:
            flags.append('SUSPICIOUS_EVIDENCE_CONTRADICTION')
            result['evidence_contradictions'] = [
                {'field': c.get('label'),
                 'label': (c.get('metadata') or {}).get('label'),
                 'fact_type': (c.get('metadata') or {}).get('fact_type'),
                 'values': (c.get('value') or {}).get('values')}
                for c in bundle.contradictions[:50]
            ]

    def _checkpoint(self, assessment: 'BotAssessment') -> None:
        """Write the assessment back to its store (durable write in DB mode)."""
        self.assessments[assessment.id] = assessment

    def _sync_metadata(self, metadata: 'UnderwritingMetadata',
                       assessment: Optional['BotAssessment'] = None) -> None:
        """Persist a processed metadata item and mirror it into its assessment.

        In memory mode the assessment's list holds the very same object, so
        this is a no-op rewrite; after a hydration it is a copy that must be
        replaced by id. When ``assessment`` is not given the owning one is
        looked up and checkpointed here.
        """
        self.metadata_store[metadata.id] = metadata
        owners = [assessment] if assessment is not None else [
            a for a in self.assessments.values()
            if a.underwriting_id == metadata.underwriting_id
            and any(m.id == metadata.id for m in a.metadata_items)
        ]
        for owner in owners:
            for idx, item in enumerate(owner.metadata_items):
                if item.id == metadata.id and item is not metadata:
                    owner.metadata_items[idx] = metadata
            if assessment is None:
                self._checkpoint(owner)
    
    @instrument_agent('underwriting_bot')
    def process_all_metadata(self, assessment_id: str) -> Dict[str, Any]:
        """
        Process all metadata items in an assessment.
        """
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            return {'success': False, 'error': 'Assessment not found'}
        
        assessment.status = AssessmentStatus.VALIDATING_METADATA
        
        results = []
        all_passed = True
        
        for metadata in list(assessment.metadata_items):
            result = self.process_metadata(metadata.id, assessment=assessment)
            results.append({
                'metadata_id': metadata.id,
                'type': metadata.metadata_type.value,
                'success': result.get('success', False)
            })
            if not result.get('success'):
                all_passed = False
        
        if not all_passed:
            assessment.status = AssessmentStatus.VALIDATION_FAILED
        else:
            assessment.status = AssessmentStatus.PROCESSING
        self._checkpoint(assessment)
        
        return {
            'success': all_passed,
            'results': results,
            'total_processed': len(results),
            'status': assessment.status.value
        }
    
    # =========================================================================
    # Risk Assessment
    # =========================================================================
    
    @instrument_agent('underwriting_bot', decision_key='recommendation')
    def run_risk_assessment(self, assessment_id: str) -> RiskAssessmentReport:
        """
        Run full risk assessment for an assessment.
        
        This aggregates all processed metadata and generates a comprehensive
        risk assessment report. Customer data is READ-ONLY.
        """
        start_time = datetime.now()
        
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        
        assessment.status = AssessmentStatus.RISK_ASSESSING
        
        # Aggregate scores from processed metadata
        identity_scores = []
        document_scores = []
        medical_scores = []
        behavioral_scores = []
        fraud_indicators = []
        all_flags = []
        
        for metadata in assessment.metadata_items:
            if metadata.processing_status != ProcessingStatus.COMPLETED:
                continue
            
            result = metadata.processing_result
            scores = result.get('scores', {})
            flags = result.get('flags', [])
            all_flags.extend(flags)
            
            if metadata.metadata_type == MetadataType.PHOTO:
                id_conf = scores.get('identity_confidence')
                if id_conf is not None:
                    identity_scores.append(id_conf)
            elif metadata.metadata_type == MetadataType.VIDEO:
                id_conf = scores.get('identity_confidence')
                if id_conf is not None:
                    identity_scores.append(id_conf)
                beh = scores.get('behavioral_score')
                if beh is not None:
                    behavioral_scores.append(beh)
                is_live = result.get('liveness', {}).get('is_live')
                if is_live is False:
                    fraud_indicators.append(0.9)
            elif metadata.metadata_type == MetadataType.MEDICAL_REPORT:
                med = scores.get('medical_risk_score')
                if med is not None:
                    medical_scores.append(med)
            elif metadata.metadata_type in [MetadataType.PASSPORT, MetadataType.DRIVING_LICENCE,
                                            MetadataType.NATIONAL_INSURANCE, MetadataType.DISABILITY_CERTIFICATE]:
                # Prefer measured authenticity; fall back to completeness only (never invent high authenticity)
                auth = scores.get('authenticity_score')
                if auth is not None:
                    document_scores.append(auth)
                else:
                    completeness = scores.get('completeness_score')
                    if completeness is not None:
                        document_scores.append(completeness)
                if 'DOCUMENT_EXPIRED' in flags:
                    document_scores.append(0.0)
            elif metadata.metadata_type == MetadataType.AUDIO:
                stress = scores.get('stress_score')
                if stress is not None:
                    behavioral_scores.append(1.0 - stress)
        
        # Calculate average scores
        identity_score = sum(identity_scores) / len(identity_scores) if identity_scores else 0.5
        document_score = sum(document_scores) / len(document_scores) if document_scores else 0.5
        medical_score = sum(medical_scores) / len(medical_scores) if medical_scores else 0.3
        behavioral_score = sum(behavioral_scores) / len(behavioral_scores) if behavioral_scores else 0.7
        fraud_score = sum(fraud_indicators) / len(fraud_indicators) if fraud_indicators else 0.1
        
        # Get claims history risk (READ-ONLY from existing data)
        claims_count = assessment.existing_claims_count
        history_score = min(claims_count * 0.15, 0.6)  # More claims = higher risk
        
        # Get customer age from snapshot
        age = assessment.customer_snapshot.get('age', 0)
        
        # Calculate overall risk
        overall_risk, risk_factors = self.risk_engine.calculate_risk_score(
            identity_score=identity_score,
            document_score=document_score,
            medical_score=medical_score,
            behavioral_score=behavioral_score,
            fraud_score=fraud_score,
            history_score=history_score,
            age=age if age > 0 else None
        )
        
        # Determine risk level
        risk_level = self.risk_engine.determine_risk_level(overall_risk)
        
        # Identity verified check
        identity_verified = identity_score >= 0.7 and not any('IDENTITY' in f or 'FACE' in f for f in all_flags if 'FAILED' in f or 'LOW' in f)
        
        # Make recommendation
        recommendation, confidence, explanation = self.risk_engine.make_recommendation(
            risk_score=overall_risk,
            identity_verified=identity_verified,
            identity_score=identity_score,
            fraud_score=fraud_score,
            document_score=document_score,
            medical_flags=all_flags
        )
        
        # Create report
        report_id = self._generate_id('REPORT')
        report = RiskAssessmentReport(
            id=report_id,
            underwriting_id=assessment.underwriting_id,
            customer_id=assessment.customer_id,
            assessment_date=datetime.now(),
            overall_risk_score=overall_risk,
            risk_level=risk_level,
            identity_verified=identity_verified,
            identity_score=identity_score,
            document_score=document_score,
            medical_score=medical_score,
            behavioral_score=behavioral_score,
            fraud_score=fraud_score,
            recommendation=recommendation,
            confidence_level=confidence,
            risk_factors=risk_factors,
            explanation=explanation,
            metadata_processed=[m.id for m in assessment.metadata_items],
            processing_time_seconds=(datetime.now() - start_time).total_seconds()
        )
        
        # Update risk factor report IDs
        for factor in report.risk_factors:
            factor.report_id = report_id

        # Shadow model + AI decision log (B1). The rules above decided; the
        # ``uw_scorer`` artifact (if any) is only compared and logged.
        shadow_features = {
            'identity_score': identity_score, 'document_score': document_score,
            'medical_score': medical_score, 'behavioral_score': behavioral_score,
            'fraud_score': fraud_score, 'history_score': history_score,
            'age': age if age > 0 else 0,
        }
        shadow = self._shadow(shadow_features, overall_risk, assessment.underwriting_id)
        report.model_shadow = shadow
        report.decision_id = self._record_decision(assessment, report, shadow_features, shadow)
        
        # Store report
        self.reports[report_id] = report
        assessment.risk_report = report
        assessment.status = AssessmentStatus.DECISION_READY
        self._checkpoint(assessment)
        
        self._log_event('bot', 'risk_assessment_complete', 'report', report_id, {
            'assessment_id': assessment_id,
            'risk_score': overall_risk,
            'risk_level': risk_level.value,
            'recommendation': recommendation.value,
            'decision_id': report.decision_id,
            'model_score': shadow.get('model_score'),
            'divergence': shadow.get('divergence'),
        })
        
        return report

    SHADOW_MODEL_NAME = 'uw_scorer'

    def _shadow(self, features: Dict[str, Any], rule_score: float, entity_id: str) -> Dict[str, Any]:
        try:
            from services.model_shadow import shadow_score
            return shadow_score(self.SHADOW_MODEL_NAME, features, rule_score,
                                agent_id='underwriting_bot', entity_id=entity_id).as_log_fields()
        except Exception as exc:  # shadowing is observability, never a dependency
            _logger.warning("model shadow skipped: %s", exc)
            return {'rule_score': round(float(rule_score), 4), 'model_score': None,
                    'model_version': 'rules-v1', 'divergence': None, 'drift_alert': False}

    def _record_decision(self, assessment: 'BotAssessment', report: RiskAssessmentReport,
                         features: Dict[str, Any], shadow: Dict[str, Any]) -> str:
        """Append the recommendation to the AI decision log; '' if unavailable."""
        try:
            from services.ai_decision_log import get_ai_decision_log
            return get_ai_decision_log().record(
                decision_type='underwriting_bot_assessment',
                output={
                    'decision': report.recommendation.value,
                    'risk_score': round(report.overall_risk_score, 4),
                    'risk_level': report.risk_level.value,
                    'identity_verified': report.identity_verified,
                    'report_id': report.id,
                    **shadow,
                },
                inputs={**{k: round(v, 4) if isinstance(v, float) else v for k, v in features.items()},
                        'metadata_items': len(assessment.metadata_items),
                        'existing_claims_count': assessment.existing_claims_count},
                entity_type='underwriting_application',
                entity_id=assessment.underwriting_id,
                model_version=shadow.get('model_version') or 'rules-v1',
                confidence=report.confidence_level,
                segment=self._segment_for(assessment),
            ) or ''
        except Exception as exc:
            _logger.warning("decision log unavailable for %s: %s", report.id, exc)
            return ''

    #: Human decision words and bot recommendations mapped onto the three
    #: harness classes (approve / reject / review).
    _DECISION_CLASSES = {
        'approve': 'approve', 'approved': 'approve', 'approve_conditional': 'approve',
        'conditional': 'approve', 'conditional_approval': 'approve',
        'reject': 'reject', 'rejected': 'reject', 'decline': 'reject', 'declined': 'reject',
        'refer': 'review', 'referred': 'review', 'refer_manual': 'review',
        'pending_info': 'review', 'human_review': 'review',
    }

    @classmethod
    def _normalize_decision(cls, decision: str) -> str:
        return cls._DECISION_CLASSES.get(str(decision or '').strip().lower(), 'review')

    def _record_override(self, decision_id: str, decision: str, notes: str, decided_by: str) -> None:
        try:
            from services.ai_decision_log import get_ai_decision_log
            get_ai_decision_log().record_override(
                decision_id, self._normalize_decision(decision),
                reason=notes or None, overridden_by=decided_by)
        except Exception as exc:
            _logger.warning("override not recorded for %s: %s", decision_id, exc)

    @staticmethod
    def _segment_for(assessment: 'BotAssessment') -> str:
        """Same age-band segmentation the calibration loop uses for the controller."""
        try:
            from services.ai_threshold_config import segment_key
            return segment_key(dict(assessment.customer_snapshot or {}))
        except Exception:
            return 'global'
    
    def get_assessment_summary(self, assessment_id: str) -> Dict[str, Any]:
        """Get summary of an assessment"""
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            return {'error': 'Assessment not found'}
        
        summary = assessment.to_dict()
        
        if assessment.risk_report:
            summary['risk_summary'] = assessment.risk_report.get_summary()
            summary['full_explanation'] = self.risk_engine.generate_full_explanation(
                assessment.risk_report,
                assessment.customer_snapshot.get('name', 'Applicant')
            )
        
        return summary
    
    # =========================================================================
    # Decision and Pipeline Integration
    # =========================================================================
    
    def apply_decision(self, 
                      assessment_id: str,
                      decision: str,
                      decided_by: str = "bot",
                      notes: str = "",
                      override_recommendation: bool = False) -> Dict[str, Any]:
        """
        Apply underwriting decision based on assessment.
        
        This updates the underwriting application status and policy status,
        but NEVER modifies customer data, transactions, or history.
        """
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            return {'success': False, 'error': 'Assessment not found'}
        
        if not assessment.risk_report:
            return {'success': False, 'error': 'Risk assessment not completed'}
        
        # Map decision to status
        decision_map = {
            'approve': AssessmentStatus.APPROVED,
            'approved': AssessmentStatus.APPROVED,
            'reject': AssessmentStatus.REJECTED,
            'rejected': AssessmentStatus.REJECTED,
            'decline': AssessmentStatus.REJECTED,
            'refer': AssessmentStatus.REFERRED,
            'referred': AssessmentStatus.REFERRED,
            'conditional': AssessmentStatus.CONDITIONAL_APPROVAL,
            'conditional_approval': AssessmentStatus.CONDITIONAL_APPROVAL
        }
        
        new_status = decision_map.get(decision.lower())
        if not new_status:
            return {'success': False, 'error': f'Invalid decision: {decision}'}
        
        # Check if overriding bot recommendation
        if override_recommendation:
            assessment.risk_report.human_override = True
            assessment.risk_report.human_decision = decision
            assessment.risk_report.human_notes = notes
            assessment.risk_report.updated_date = datetime.now()

        # Calibration loop (B1/A6): every human decision that differs from
        # the bot's recommendation is a labelled counter-decision on the
        # logged AI decision, whether or not the caller flagged it.
        recommended = assessment.risk_report.recommendation.value
        if decided_by != 'bot' and assessment.risk_report.decision_id and (
                override_recommendation or self._normalize_decision(decision) != self._normalize_decision(recommended)):
            self._record_override(assessment.risk_report.decision_id, decision, notes, decided_by)
        
        # Update assessment status
        assessment.status = new_status
        assessment.completed_at = datetime.now()
        if assessment.risk_report is not None:
            self.reports[assessment.risk_report.id] = assessment.risk_report
        self._checkpoint(assessment)
        
        # Update underwriting application (additive only, never resets data)
        uw_app = self._underwriting.get(assessment.underwriting_id)
        if uw_app:
            uw_app['status'] = 'approved' if new_status == AssessmentStatus.APPROVED else (
                'rejected' if new_status == AssessmentStatus.REJECTED else (
                    'referred' if new_status == AssessmentStatus.REFERRED else 'conditional'
                )
            )
            uw_app['decision_date'] = datetime.now().isoformat()
            uw_app['decided_by'] = decided_by
            uw_app['bot_assessment_id'] = assessment_id
            uw_app['bot_report_id'] = assessment.risk_report.id
            uw_app['notes'] = notes
            uw_app['updated_date'] = datetime.now().isoformat()
        
        # Integrate with pipeline if available
        if self._pipeline and new_status == AssessmentStatus.APPROVED:
            # Call pipeline approval (which will also update policy status)
            try:
                self._pipeline.approve_underwriting(
                    uw_id=assessment.underwriting_id,
                    approved_by=decided_by,
                    premium_adjustment_pct=0.0,  # Could be based on risk factors
                    notes=f"Bot Assessment: {assessment.risk_report.recommendation.value}. {notes}"
                )
            except:
                pass  # Pipeline integration is optional
        
        self._log_event(decided_by, 'decision_applied', 'assessment', assessment_id, {
            'decision': decision,
            'status': new_status.value,
            'override': override_recommendation
        })
        
        return {
            'success': True,
            'assessment_id': assessment_id,
            'decision': decision,
            'status': new_status.value,
            'report_id': assessment.risk_report.id
        }
    
    def get_pending_assessments(self) -> List[Dict[str, Any]]:
        """Get all assessments pending decision"""
        pending = []
        for assessment in self.assessments.values():
            if assessment.status == AssessmentStatus.DECISION_READY:
                summary = assessment.to_dict()
                if assessment.risk_report:
                    summary['risk_summary'] = assessment.risk_report.get_summary()
                pending.append(summary)
        return pending
    
    def get_report(self, report_id: str) -> Optional[RiskAssessmentReport]:
        """Get a specific report"""
        return self.reports.get(report_id)
    
    def get_report_as_dict(self, report_id: str) -> Dict[str, Any]:
        """Get report as dictionary"""
        report = self.reports.get(report_id)
        if report:
            return report.to_dict()
        return {}


# ============================================================================
# Factory and Singleton
# ============================================================================

_bot_instance: Optional[UnderwritingBotService] = None
_bot_lock = threading.Lock()


def get_underwriting_bot_service(customers: Dict = None,
                                  policies: Dict = None,
                                  underwriting_apps: Dict = None,
                                  claims: Dict = None,
                                  audit_service = None,
                                  pipeline_service = None) -> UnderwritingBotService:
    """Get or create the process-wide underwriting bot service instance.

    The instance is rebuilt when the caller passes store objects that differ
    (by identity) from the ones the current instance is bound to, so a route
    or worker whose ``JobContext`` supplies different portal stores never
    reads another context's customers through a stale singleton. Calls with
    no arguments always return the existing instance.
    """
    global _bot_instance
    with _bot_lock:
        requested = {
            '_customers': customers, '_policies': policies,
            '_underwriting': underwriting_apps, '_claims': claims,
        }
        current = _bot_instance
        if current is not None and any(
                store is not None and getattr(current, attr, None) is not store
                for attr, store in requested.items()):
            current = None
        if current is None:
            current = UnderwritingBotService(
                customers=customers,
                policies=policies,
                underwriting_apps=underwriting_apps,
                claims=claims,
                audit_service=audit_service,
                pipeline_service=pipeline_service
            )
            _bot_instance = current
        elif audit_service is not None and current._audit is None:
            current._audit = audit_service
        return current


def init_underwriting_bot_service(customers: Dict,
                                   policies: Dict,
                                   underwriting_apps: Dict,
                                   claims: Dict,
                                   audit_service = None,
                                   pipeline_service = None) -> UnderwritingBotService:
    """Initialize underwriting bot service with dependencies"""
    global _bot_instance
    with _bot_lock:
        _bot_instance = UnderwritingBotService(
            customers=customers,
            policies=policies,
            underwriting_apps=underwriting_apps,
            claims=claims,
            audit_service=audit_service,
            pipeline_service=pipeline_service
        )
        return _bot_instance


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# ---------------------------------------------------------------------------
def _underwriting_bot_health() -> Dict[str, Any]:
    """Read-only probe: never instantiates the service."""
    instance = _bot_instance
    if instance is None:
        return {'status': 'ok', 'initialized': False}
    def _cached(store) -> int:
        # Probe the cache, not the table: a health check must not issue queries.
        return store.snapshot()['cached'] if hasattr(store, 'snapshot') else len(store or {})

    assessments = getattr(instance, 'assessments', {})
    return {
        'status': 'ok',
        'initialized': True,
        'bot_id': getattr(instance, 'bot_id', None),
        'version': getattr(instance, 'version', None),
        'assessments': _cached(assessments),
        'reports': _cached(getattr(instance, 'reports', {})),
        'durable': bool(getattr(assessments, 'durable', False)),
    }


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='underwriting_bot',
        name='Underwriting Bot',
        version='1.0.0',
        module='services.underwriting_bot_service',
        description=(
            'Processes application evidence (photos, medical reports, official '
            'documents, audio, video), scores risk with a deterministic engine, '
            'and recommends an underwriting decision without modifying customer data.'
        ),
        entry_url='/risk-dashboard.html',
        api={'method': 'POST', 'path': '/api/risk-dashboard/ai-assess'},
        roles=('admin', 'underwriter'),
        deterministic=True,
        sample_prompts=(
            'Assess the uploaded medical report for this applicant',
            'What is the risk level for assessment UWA-1234?',
        ),
    ), health_fn=_underwriting_bot_health)
except Exception as _reg_exc:  # pragma: no cover
    _logger.warning("underwriting bot agent registration skipped: %s", _reg_exc)

