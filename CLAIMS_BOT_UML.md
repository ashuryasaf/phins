# PHINS Claims Bot - AI/BI Risk Assessment System
## Comprehensive UML Architecture Documentation

**Version:** 1.0.0  
**Date:** January 7, 2026  
**Author:** PHINS Platform AI Engine

---

## 1. SYSTEM CONTEXT DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          PHINS CLAIMS BOT ECOSYSTEM                             │
│                                                                                 │
│  ┌──────────────┐        ┌──────────────────────────────────────────────────┐  │
│  │              │        │              CLAIMS BOT CORE                      │  │
│  │   CUSTOMER   │◄──────►│  ┌─────────────────────────────────────────────┐ │  │
│  │  (Claimant)  │        │  │       METADATA PROCESSING ENGINE           │ │  │
│  │              │ Submit │  │  ┌─────────┐ ┌─────────┐ ┌──────────────┐  │ │  │
│  └──────────────┘ Claim  │  │  │ Photos  │ │ Medical │ │  Documents   │  │ │  │
│         │                │  │  │Analyzer │ │ Report  │ │  Analyzer    │  │ │  │
│         │ Upload         │  │  │         │ │Analyzer │ │(Receipts/ID) │  │ │  │
│         │ Metadata       │  │  └────┬────┘ └────┬────┘ └──────┬───────┘  │ │  │
│         ▼                │  │       │           │             │          │ │  │
│  ┌──────────────┐        │  │       └───────────┼─────────────┘          │ │  │
│  │   Metadata   │───────►│  │                   ▼                        │ │  │
│  │   Storage    │        │  │  ┌─────────────────────────────────────┐   │ │  │
│  └──────────────┘        │  │  │     FEATURE EXTRACTION ENGINE       │   │ │  │
│                          │  │  └───────────────┬─────────────────────┘   │ │  │
│  ┌──────────────┐        │  │                  │                         │ │  │
│  │ Underwriting │◄───────│  │                  ▼                         │ │  │
│  │   Records    │        │  │  ┌─────────────────────────────────────┐   │ │  │
│  │ (Historical) │────────│──│  │   FRAUD DETECTION & CROSS-REF       │   │ │  │
│  └──────────────┘        │  │  │   ┌─────────────────────────────┐   │   │ │  │
│                          │  │  │   │ Compare vs Underwriting     │   │   │ │  │
│  ┌──────────────┐        │  │  │   │ Assessment for Hidden       │   │   │ │  │
│  │   Claims     │◄───────│  │  │   │ Conditions Detection        │   │   │ │  │
│  │   History    │────────│──│  │   └─────────────────────────────┘   │   │ │  │
│  └──────────────┘        │  │  └───────────────┬─────────────────────┘   │ │  │
│                          │  │                  │                         │ │  │
│  ┌──────────────┐        │  │                  ▼                         │ │  │
│  │   Policy     │◄───────│  │  ┌─────────────────────────────────────┐   │ │  │
│  │   Records    │────────│──│  │   BI/AI RISK ASSESSMENT ENGINE      │   │ │  │
│  └──────────────┘        │  │  │   ┌───────────┐ ┌───────────────┐   │   │ │  │
│                          │  │  │   │ ML Models │ │ Rule Engine   │   │   │ │  │
│                          │  │  │   └─────┬─────┘ └───────┬───────┘   │   │ │  │
│                          │  │  │         │               │           │   │ │  │
│  ┌──────────────┐        │  │  │         └───────┬───────┘           │   │ │  │
│  │   Adjuster   │◄───────│  │  │                 ▼                   │   │ │  │
│  │   (Manual    │        │  │  │   ┌─────────────────────────────┐   │   │ │  │
│  │    Review)   │        │  │  │   │   DECISION RECOMMENDATION   │   │   │ │  │
│  └──────────────┘        │  │  │   │  ┌──────┐ ┌────────┐ ┌────┐ │   │   │ │  │
│         │                │  │  │   │  │Approve│ │Refer  │ │Deny│ │   │   │ │  │
│         │ Override       │  │  │   │  └──────┘ └────────┘ └────┘ │   │   │ │  │
│         ▼                │  │  │   └─────────────────────────────┘   │   │ │  │
│  ┌──────────────┐        │  │  └─────────────────────────────────────┘   │ │  │
│  │   Payment    │◄───────│  └─────────────────────────────────────────────┘ │  │
│  │   Gateway    │        │                                                   │  │
│  └──────────────┘        └──────────────────────────────────────────────────┘  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. CLASS DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         CLAIMS BOT CLASS HIERARCHY                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────┐        ┌────────────────────────────────────┐ │
│  │      «enumeration»          │        │        «enumeration»               │ │
│  │    ClaimMetadataType        │        │      ClaimDecisionType             │ │
│  ├─────────────────────────────┤        ├────────────────────────────────────┤ │
│  │ INJURY_PHOTO                │        │ APPROVE_FULL                       │ │
│  │ MEDICAL_REPORT              │        │ APPROVE_PARTIAL                    │ │
│  │ RECEIPT                     │        │ REFER_INVESTIGATION                │ │
│  │ POLICE_REPORT               │        │ REFER_MEDICAL_REVIEW               │ │
│  │ HOSPITAL_BILL               │        │ DENY_FRAUD_SUSPECTED               │ │
│  │ PRESCRIPTION                │        │ DENY_NOT_COVERED                   │ │
│  │ DISABILITY_UPDATE           │        │ DENY_HIDDEN_CONDITION              │ │
│  │ DEATH_CERTIFICATE           │        │ PENDING_MORE_INFO                  │ │
│  │ WITNESS_STATEMENT           │        └────────────────────────────────────┘ │
│  │ VIDEO_EVIDENCE              │                                               │
│  │ AUDIO_STATEMENT             │        ┌────────────────────────────────────┐ │
│  └─────────────────────────────┘        │        «enumeration»               │ │
│                                         │      FraudIndicatorType            │ │
│  ┌─────────────────────────────┐        ├────────────────────────────────────┤ │
│  │      «enumeration»          │        │ TIMING_SUSPICIOUS                  │ │
│  │   ClaimAssessmentStatus     │        │ CONDITION_HIDDEN_AT_UW             │ │
│  ├─────────────────────────────┤        │ DOCUMENT_TAMPERED                  │ │
│  │ INITIATED                   │        │ INCONSISTENT_STATEMENTS            │ │
│  │ COLLECTING_EVIDENCE         │        │ EXCESSIVE_CLAIM_HISTORY            │ │
│  │ VALIDATING_EVIDENCE         │        │ PROVIDER_FLAGGED                   │ │
│  │ CROSS_REFERENCING_UW        │        │ AMOUNT_SUSPICIOUS                  │ │
│  │ FRAUD_ANALYSIS              │        │ PATTERN_MATCH_FRAUD                │ │
│  │ BI_ASSESSMENT               │        │ IDENTITY_MISMATCH                  │ │
│  │ DECISION_READY              │        │ PRE_EXISTING_UNDISCLOSED           │ │
│  │ APPROVED                    │        └────────────────────────────────────┘ │
│  │ DENIED                      │                                               │
│  │ REFERRED                    │                                               │
│  │ PAYMENT_PROCESSING          │                                               │
│  │ COMPLETED                   │                                               │
│  └─────────────────────────────┘                                               │
│                                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                              CORE DATA CLASSES                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                          ClaimMetadata                                   │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + id: str                                                                │  │
│  │ + claim_id: str                                                          │  │
│  │ + customer_id: str                                                       │  │
│  │ + metadata_type: ClaimMetadataType                                       │  │
│  │ + file_name: str                                                         │  │
│  │ + file_hash: str                                                         │  │
│  │ + upload_date: datetime                                                  │  │
│  │ + processing_status: ProcessingStatus                                    │  │
│  │ + extracted_data: Dict[str, Any]                                         │  │
│  │ + validation_score: float                                                │  │
│  │ + tampering_detected: bool                                               │  │
│  │ + confidence_score: float                                                │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + to_dict(): Dict                                                        │  │
│  │ + validate(): bool                                                       │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                      UnderwritingCrossReference                          │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + id: str                                                                │  │
│  │ + claim_id: str                                                          │  │
│  │ + underwriting_id: str                                                   │  │
│  │ + policy_id: str                                                         │  │
│  │ + policy_start_date: datetime                                            │  │
│  │ + claim_date: datetime                                                   │  │
│  │ + time_since_policy_years: float                                         │  │
│  │ + declared_conditions_at_uw: List[Dict]                                  │  │
│  │ + current_claimed_conditions: List[Dict]                                 │  │
│  │ + hidden_conditions_detected: List[HiddenCondition]                      │  │
│  │ + material_misrepresentation: bool                                       │  │
│  │ + contestability_period_active: bool                                     │  │
│  │ + risk_delta: float                                                      │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + analyze_hidden_conditions(): List[HiddenCondition]                     │  │
│  │ + calculate_risk_delta(): float                                          │  │
│  │ + check_contestability(): bool                                           │  │
│  │ + generate_timeline(): Dict                                              │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                         HiddenCondition                                  │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + condition_name: str                                                    │  │
│  │ + icd_code: str                                                          │  │
│  │ + evidence_source: str                                                   │  │
│  │ + detection_confidence: float                                            │  │
│  │ + estimated_onset_date: datetime                                         │  │
│  │ + was_before_policy: bool                                                │  │
│  │ + causal_link_to_claim: bool                                             │  │
│  │ + severity: str                                                          │  │
│  │ + deliberate_concealment_score: float                                    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                       FraudIndicator                                     │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + id: str                                                                │  │
│  │ + assessment_id: str                                                     │  │
│  │ + indicator_type: FraudIndicatorType                                     │  │
│  │ + severity: float (0.0-1.0)                                              │  │
│  │ + evidence: List[str]                                                    │  │
│  │ + explanation: str                                                       │  │
│  │ + recommendation: str                                                    │  │
│  │ + requires_investigation: bool                                           │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                    ClaimRiskAssessmentReport                             │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + id: str                                                                │  │
│  │ + claim_id: str                                                          │  │
│  │ + customer_id: str                                                       │  │
│  │ + policy_id: str                                                         │  │
│  │ + assessment_date: datetime                                              │  │
│  │ + overall_risk_score: float                                              │  │
│  │ + legitimacy_score: float                                                │  │
│  │ + fraud_score: float                                                     │  │
│  │ + document_authenticity_score: float                                     │  │
│  │ + medical_consistency_score: float                                       │  │
│  │ + underwriting_alignment_score: float                                    │  │
│  │ + claim_amount_reasonability: float                                      │  │
│  │ + recommendation: ClaimDecisionType                                      │  │
│  │ + confidence_level: float                                                │  │
│  │ + fraud_indicators: List[FraudIndicator]                                 │  │
│  │ + hidden_conditions: List[HiddenCondition]                               │  │
│  │ + cross_reference: UnderwritingCrossReference                            │  │
│  │ + explanation: str                                                       │  │
│  │ + human_override: bool                                                   │  │
│  │ + adjuster_notes: str                                                    │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + generate_summary(): Dict                                               │  │
│  │ + generate_detailed_report(): str                                        │  │
│  │ + get_risk_breakdown(): Dict                                             │  │
│  │ + recommend_action(): ClaimDecisionType                                  │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                              SERVICE CLASSES                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                        ClaimsBotService                                  │  │
│  │                    (Main Orchestration Class)                            │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ - _customers: Dict (READ-ONLY)                                           │  │
│  │ - _policies: Dict (READ-ONLY)                                            │  │
│  │ - _claims: Dict                                                          │  │
│  │ - _underwriting: Dict (READ-ONLY)                                        │  │
│  │ - _audit: AuditService                                                   │  │
│  │ - assessments: Dict[str, ClaimBotAssessment]                             │  │
│  │ - reports: Dict[str, ClaimRiskAssessmentReport]                          │  │
│  │ - photo_analyzer: InjuryPhotoAnalyzer                                    │  │
│  │ - medical_analyzer: ClaimMedicalAnalyzer                                 │  │
│  │ - document_analyzer: ClaimDocumentAnalyzer                               │  │
│  │ - cross_ref_engine: UnderwritingCrossRefEngine                           │  │
│  │ - fraud_detector: FraudDetectionEngine                                   │  │
│  │ - bi_engine: ClaimBIEngine                                               │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │ + start_assessment(claim_id, customer_id): ClaimBotAssessment            │  │
│  │ + add_evidence(assessment_id, evidence_type, file): ClaimMetadata        │  │
│  │ + process_all_evidence(assessment_id): Dict                              │  │
│  │ + run_cross_reference(assessment_id): UnderwritingCrossReference         │  │
│  │ + run_fraud_analysis(assessment_id): List[FraudIndicator]                │  │
│  │ + run_bi_assessment(assessment_id): ClaimRiskAssessmentReport            │  │
│  │ + get_recommendation(assessment_id): ClaimDecisionType                   │  │
│  │ + apply_decision(assessment_id, decision, adjuster): Dict                │  │
│  │ + override_decision(assessment_id, new_decision, notes): Dict            │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  ┌─────────────────────────────────────────┐                                   │
│  │      UnderwritingCrossRefEngine         │                                   │
│  ├─────────────────────────────────────────┤                                   │
│  │ - _underwriting_data: Dict              │                                   │
│  │ - _ml_model: HiddenConditionDetector    │                                   │
│  ├─────────────────────────────────────────┤                                   │
│  │ + compare_declared_vs_claimed(): Dict   │                                   │
│  │ + detect_hidden_conditions(): List      │                                   │
│  │ + calculate_time_based_risk(): float    │                                   │
│  │ + check_material_misrep(): bool         │                                   │
│  │ + analyze_medical_timeline(): Dict      │                                   │
│  └─────────────────────────────────────────┘                                   │
│                                                                                 │
│  ┌─────────────────────────────────────────┐                                   │
│  │         FraudDetectionEngine            │                                   │
│  ├─────────────────────────────────────────┤                                   │
│  │ - _pattern_db: FraudPatternDB           │                                   │
│  │ - _ml_models: Dict[str, MLModel]        │                                   │
│  │ - _rules_engine: RulesEngine            │                                   │
│  ├─────────────────────────────────────────┤                                   │
│  │ + analyze_timing_patterns(): float      │                                   │
│  │ + analyze_amount_patterns(): float      │                                   │
│  │ + detect_document_tampering(): Dict     │                                   │
│  │ + detect_provider_fraud(): Dict         │                                   │
│  │ + match_known_fraud_patterns(): List    │                                   │
│  │ + calculate_fraud_probability(): float  │                                   │
│  └─────────────────────────────────────────┘                                   │
│                                                                                 │
│  ┌─────────────────────────────────────────┐                                   │
│  │            ClaimBIEngine                │                                   │
│  ├─────────────────────────────────────────┤                                   │
│  │ - _prediction_models: Dict              │                                   │
│  │ - _historical_data: ClaimHistoryDB      │                                   │
│  │ - _risk_calculator: RiskCalculator      │                                   │
│  ├─────────────────────────────────────────┤                                   │
│  │ + predict_claim_legitimacy(): float     │                                   │
│  │ + predict_optimal_settlement(): float   │                                   │
│  │ + analyze_claim_history(): Dict         │                                   │
│  │ + calculate_expected_loss(): float      │                                   │
│  │ + recommend_decision(): ClaimDecision   │                                   │
│  └─────────────────────────────────────────┘                                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. SEQUENCE DIAGRAM - Full Claim Assessment Flow

```
┌────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌─────────────┐   ┌────────────┐
│Customer│   │Claims Portal│   │ Claims Bot   │   │ CrossRef    │   │ Fraud       │   │ BI Engine  │
│        │   │             │   │   Service    │   │ Engine      │   │ Detector    │   │            │
└───┬────┘   └──────┬──────┘   └──────┬───────┘   └──────┬──────┘   └──────┬──────┘   └─────┬──────┘
    │               │                 │                  │                 │                │
    │ Submit Claim  │                 │                  │                 │                │
    │──────────────►│                 │                  │                 │                │
    │               │                 │                  │                 │                │
    │ Upload Photos │                 │                  │                 │                │
    │ Medical Docs  │                 │                  │                 │                │
    │ Receipts etc  │                 │                  │                 │                │
    │──────────────►│                 │                  │                 │                │
    │               │                 │                  │                 │                │
    │               │ start_assessment│                  │                 │                │
    │               │────────────────►│                  │                 │                │
    │               │                 │                  │                 │                │
    │               │                 │ Load Customer    │                 │                │
    │               │                 │ Policy & UW Data │                 │                │
    │               │                 │ (READ-ONLY)      │                 │                │
    │               │                 │◄────────────────►│                 │                │
    │               │                 │                  │                 │                │
    │               │ add_evidence()  │                  │                 │                │
    │               │ for each file   │                  │                 │                │
    │               │────────────────►│                  │                 │                │
    │               │                 │                  │                 │                │
    │               │ process_all_    │                  │                 │                │
    │               │ evidence()      │                  │                 │                │
    │               │────────────────►│                  │                 │                │
    │               │                 │                  │                 │                │
    │               │                 │ ┌──────────────────────────────────────────────┐  │
    │               │                 │ │ PROCESS EACH EVIDENCE TYPE:                  │  │
    │               │                 │ │ • Injury Photos → InjuryPhotoAnalyzer       │  │
    │               │                 │ │ • Medical Reports → ClaimMedicalAnalyzer    │  │
    │               │                 │ │ • Receipts/Bills → ClaimDocumentAnalyzer    │  │
    │               │                 │ │ • Statements → StatementAnalyzer            │  │
    │               │                 │ │                                              │  │
    │               │                 │ │ EXTRACT:                                     │  │
    │               │                 │ │ • Injuries/conditions from photos           │  │
    │               │                 │ │ • Diagnoses from medical reports            │  │
    │               │                 │ │ • Treatment costs from bills                │  │
    │               │                 │ │ • Authenticity scores                        │  │
    │               │                 │ └──────────────────────────────────────────────┘  │
    │               │                 │                  │                 │                │
    │               │                 │ run_cross_       │                 │                │
    │               │                 │ reference()      │                 │                │
    │               │                 │─────────────────►│                 │                │
    │               │                 │                  │                 │                │
    │               │                 │                  │ ┌────────────────────────────┐  │
    │               │                 │                  │ │ CROSS-REFERENCE:           │  │
    │               │                 │                  │ │ 1. Load UW application     │  │
    │               │                 │                  │ │ 2. Get declared conditions │  │
    │               │                 │                  │ │ 3. Compare to claim data   │  │
    │               │                 │                  │ │ 4. Calculate time delta    │  │
    │               │                 │                  │ │ 5. Detect hidden conditions│  │
    │               │                 │                  │ │ 6. Check contestability    │  │
    │               │                 │                  │ │ 7. Score risk delta        │  │
    │               │                 │                  │ └────────────────────────────┘  │
    │               │                 │                  │                 │                │
    │               │                 │◄─────────────────│                 │                │
    │               │                 │ CrossReference   │                 │                │
    │               │                 │ Result           │                 │                │
    │               │                 │                  │                 │                │
    │               │                 │ run_fraud_       │                 │                │
    │               │                 │ analysis()       │                 │                │
    │               │                 │────────────────────────────────────►│                │
    │               │                 │                  │                 │                │
    │               │                 │                  │                 │ ┌──────────────┐
    │               │                 │                  │                 │ │FRAUD CHECK:  │
    │               │                 │                  │                 │ │• Timing      │
    │               │                 │                  │                 │ │• Amount      │
    │               │                 │                  │                 │ │• Documents   │
    │               │                 │                  │                 │ │• Patterns    │
    │               │                 │                  │                 │ │• Provider    │
    │               │                 │                  │                 │ │• History     │
    │               │                 │                  │                 │ └──────────────┘
    │               │                 │                  │                 │                │
    │               │                 │◄───────────────────────────────────│                │
    │               │                 │ Fraud Indicators │                 │                │
    │               │                 │                  │                 │                │
    │               │                 │ run_bi_          │                 │                │
    │               │                 │ assessment()     │                 │                │
    │               │                 │─────────────────────────────────────────────────────►│
    │               │                 │                  │                 │                │
    │               │                 │                  │                 │                │ ┌─────────────┐
    │               │                 │                  │                 │                │ │BI ANALYSIS: │
    │               │                 │                  │                 │                │ │• ML predict │
    │               │                 │                  │                 │                │ │• Risk calc  │
    │               │                 │                  │                 │                │ │• History    │
    │               │                 │                  │                 │                │ │• Settlement │
    │               │                 │                  │                 │                │ │• Decision   │
    │               │                 │                  │                 │                │ └─────────────┘
    │               │                 │                  │                 │                │
    │               │                 │◄────────────────────────────────────────────────────│
    │               │                 │ Risk Assessment  │                 │                │
    │               │                 │ Report           │                 │                │
    │               │                 │                  │                 │                │
    │               │◄────────────────│                  │                 │                │
    │               │ Assessment      │                  │                 │                │
    │               │ Complete +      │                  │                 │                │
    │               │ Recommendation  │                  │                 │                │
    │               │                 │                  │                 │                │
```

---

## 4. STATE DIAGRAM - Claim Assessment Lifecycle

```
                                    ┌─────────────────────────────┐
                                    │                             │
                                    │      CLAIM SUBMITTED        │
                                    │                             │
                                    └──────────────┬──────────────┘
                                                   │
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │                             │
                                    │   ASSESSMENT_INITIATED      │
                                    │                             │
                                    └──────────────┬──────────────┘
                                                   │
                                    Evidence uploaded
                                                   │
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │                             │
                                    │  COLLECTING_EVIDENCE        │
                                    │  • Injury photos            │
                                    │  • Medical reports          │
                                    │  • Receipts/bills           │
                                    │  • Statements               │
                                    │                             │
                                    └──────────────┬──────────────┘
                                                   │
                                    All evidence received
                                                   │
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │                             │
                                    │  VALIDATING_EVIDENCE        │
                                    │  • Authenticity check       │
                                    │  • Tampering detection      │
                                    │  • OCR extraction           │
                                    │  • Medical parsing          │
                                    │                             │
                                    └────────────┬─┬──────────────┘
                                                 │ │
                     ┌───────────────────────────┘ └────────────────────────┐
                     │                                                      │
          Evidence valid                                        Evidence invalid
                     │                                                      │
                     ▼                                                      ▼
    ┌─────────────────────────────┐                      ┌─────────────────────────────┐
    │                             │                      │                             │
    │  CROSS_REFERENCING_UW       │                      │   VALIDATION_FAILED         │
    │  • Load underwriting data   │                      │   • Request more docs       │
    │  • Compare declarations     │                      │   • Flag for review         │
    │  • Detect hidden conditions │                      │                             │
    │  • Calculate time risk      │                      └──────────────┬──────────────┘
    │                             │                                     │
    └──────────────┬──────────────┘                                     │
                   │                                                    │
                   ▼                                                    │
    ┌─────────────────────────────┐                                     │
    │                             │                                     │
    │     FRAUD_ANALYSIS          │                                     │
    │  • Pattern matching         │                                     │
    │  • Timing analysis          │                                     │
    │  • Amount verification      │                                     │
    │  • Provider check           │                                     │
    │  • History analysis         │                                     │
    │                             │                                     │
    └──────────────┬──────────────┘                                     │
                   │                                                    │
                   ▼                                                    │
    ┌─────────────────────────────┐                                     │
    │                             │                                     │
    │      BI_ASSESSMENT          │                                     │
    │  • ML prediction            │                                     │
    │  • Risk calculation         │                                     │
    │  • Settlement optimization  │                                     │
    │  • Decision scoring         │                                     │
    │                             │                                     │
    └──────────────┬──────────────┘                                     │
                   │                                                    │
                   ▼                                                    │
    ┌─────────────────────────────┐                                     │
    │                             │◄────────────────────────────────────┘
    │     DECISION_READY          │
    │  • Report generated         │
    │  • Recommendation made      │
    │  • Awaiting action          │
    │                             │
    └────────────┬─┬─┬────────────┘
                 │ │ │
      ┌──────────┘ │ └──────────┐
      │            │            │
Auto-Approve  Manual Review  Auto-Deny
      │            │            │
      ▼            ▼            ▼
┌───────────┐ ┌───────────┐ ┌───────────┐
│           │ │           │ │           │
│ APPROVED  │ │ REFERRED  │ │  DENIED   │
│           │ │           │ │           │
└─────┬─────┘ └─────┬─────┘ └─────┬─────┘
      │             │             │
      │     Adjuster decision     │
      │             │             │
      │      ┌──────┴──────┐      │
      │      │             │      │
      │      ▼             ▼      │
      │ ┌───────────┐ ┌───────────┐
      │ │ Override  │ │ Override  │
      │ │ Approve   │ │ Deny      │
      │ └─────┬─────┘ └─────┬─────┘
      │       │             │      │
      └───────┼─────────────┼──────┘
              │             │
              ▼             ▼
       ┌─────────────┐ ┌─────────────┐
       │             │ │             │
       │  PAYMENT_   │ │  CLOSED_    │
       │  PROCESSING │ │  DENIED     │
       │             │ │             │
       └──────┬──────┘ └─────────────┘
              │
              ▼
       ┌─────────────┐
       │             │
       │  COMPLETED  │
       │  (Paid)     │
       │             │
       └─────────────┘
```

---

## 5. ACTIVITY DIAGRAM - Hidden Condition Detection Algorithm

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    HIDDEN CONDITION DETECTION WORKFLOW                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│                              ┌─────────────┐                                    │
│                              │   START     │                                    │
│                              └──────┬──────┘                                    │
│                                     │                                           │
│                                     ▼                                           │
│                    ┌────────────────────────────────┐                           │
│                    │ Load Underwriting Application  │                           │
│                    │ • Declared medical conditions  │                           │
│                    │ • Health questionnaire         │                           │
│                    │ • Risk assessment report       │                           │
│                    │ • Policy start date            │                           │
│                    └───────────────┬────────────────┘                           │
│                                    │                                            │
│                                    ▼                                            │
│                    ┌────────────────────────────────┐                           │
│                    │ Extract Claim Medical Data     │                           │
│                    │ • Current diagnoses from docs  │                           │
│                    │ • Treatment history            │                           │
│                    │ • Hospitalization dates        │                           │
│                    │ • Prescription history         │                           │
│                    └───────────────┬────────────────┘                           │
│                                    │                                            │
│                                    ▼                                            │
│         ┌────────────────────────────────────────────────────────┐              │
│         │         COMPARE DECLARED vs CLAIMED CONDITIONS         │              │
│         └────────────────────────────┬───────────────────────────┘              │
│                                      │                                          │
│                    ┌─────────────────┼─────────────────┐                        │
│                    │                 │                 │                        │
│                    ▼                 ▼                 ▼                        │
│        ┌──────────────────┐ ┌──────────────┐ ┌─────────────────────┐           │
│        │ Condition        │ │ Condition    │ │ New Condition       │           │
│        │ DECLARED &       │ │ DECLARED     │ │ NOT DECLARED        │           │
│        │ CLAIMED          │ │ NOT CLAIMED  │ │ BUT CLAIMED         │           │
│        │ (Expected)       │ │ (Normal)     │ │ (SUSPICIOUS)        │           │
│        └────────┬─────────┘ └──────┬───────┘ └──────────┬──────────┘           │
│                 │                  │                    │                       │
│                 │                  │                    ▼                       │
│                 │                  │     ┌─────────────────────────────┐        │
│                 │                  │     │ ANALYZE ONSET DATE          │        │
│                 │                  │     │ • Extract from medical docs │        │
│                 │                  │     │ • Check prescription dates  │        │
│                 │                  │     │ • Analyze treatment history │        │
│                 │                  │     └─────────────┬───────────────┘        │
│                 │                  │                   │                        │
│                 │                  │     ┌─────────────┴──────────────┐         │
│                 │                  │     │                            │         │
│                 │                  │     ▼                            ▼         │
│                 │                  │ ┌────────────────┐  ┌─────────────────────┐│
│                 │                  │ │ Onset AFTER    │  │ Onset BEFORE        ││
│                 │                  │ │ Policy Start   │  │ Policy Start        ││
│                 │                  │ │ (Legitimate)   │  │ (HIDDEN CONDITION!) ││
│                 │                  │ └───────┬────────┘  └──────────┬──────────┘│
│                 │                  │         │                      │           │
│                 │                  │         │                      ▼           │
│                 │                  │         │    ┌─────────────────────────┐   │
│                 │                  │         │    │ CALCULATE CONCEALMENT   │   │
│                 │                  │         │    │ SCORE                   │   │
│                 │                  │         │    │ • How severe?           │   │
│                 │                  │         │    │ • Was it known?         │   │
│                 │                  │         │    │ • Did it affect UW?     │   │
│                 │                  │         │    │ • Causal link to claim? │   │
│                 │                  │         │    └───────────┬─────────────┘   │
│                 │                  │         │                │                 │
│                 │                  │         │                ▼                 │
│                 │                  │         │    ┌─────────────────────────┐   │
│                 │                  │         │    │ CHECK CONTESTABILITY    │   │
│                 │                  │         │    │ PERIOD                  │   │
│                 │                  │         │    │ (Usually 2 years)       │   │
│                 │                  │         │    └───────────┬─────────────┘   │
│                 │                  │         │                │                 │
│                 │                  │         │   ┌────────────┴───────────┐     │
│                 │                  │         │   │                        │     │
│                 │                  │         │   ▼                        ▼     │
│                 │                  │         │ ┌────────────┐  ┌─────────────┐  │
│                 │                  │         │ │ WITHIN     │  │ OUTSIDE     │  │
│                 │                  │         │ │ 2 YEARS    │  │ 2 YEARS     │  │
│                 │                  │         │ │ → CAN DENY │  │ → LIMITED   │  │
│                 │                  │         │ └──────┬─────┘  └──────┬──────┘  │
│                 │                  │         │        │               │         │
│                 └──────────────────┴─────────┴────────┼───────────────┘         │
│                                                       │                         │
│                                                       ▼                         │
│                              ┌─────────────────────────────────────┐            │
│                              │     GENERATE HIDDEN CONDITION       │            │
│                              │     REPORT                          │            │
│                              │     • Conditions found              │            │
│                              │     • Evidence sources              │            │
│                              │     • Concealment scores            │            │
│                              │     • Recommendations               │            │
│                              └───────────────┬─────────────────────┘            │
│                                              │                                  │
│                                              ▼                                  │
│                                       ┌─────────────┐                           │
│                                       │     END     │                           │
│                                       └─────────────┘                           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. DATA FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     CLAIMS BOT DATA FLOW ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   EXTERNAL DATA SOURCES (READ-ONLY)          CLAIMS BOT PROCESSING              │
│   ═══════════════════════════════           ════════════════════════            │
│                                                                                 │
│   ┌────────────────┐                       ┌────────────────────────┐           │
│   │   CUSTOMERS    │──────────────────────►│                        │           │
│   │   • Name       │   Customer Profile    │    EVIDENCE PROCESSOR  │           │
│   │   • DOB        │                       │    ┌────────────────┐  │           │
│   │   • Contact    │                       │    │ Photo Analyzer │  │           │
│   │   • History    │                       │    │ Medical Parser │  │           │
│   └────────────────┘                       │    │ Doc Validator  │  │           │
│                                            │    │ Audio/Video    │  │           │
│   ┌────────────────┐                       │    └───────┬────────┘  │           │
│   │   POLICIES     │──────────────────────►│            │           │           │
│   │   • Type       │   Policy Details      │            ▼           │           │
│   │   • Coverage   │                       │    ┌────────────────┐  │           │
│   │   • Start Date │                       │    │ EXTRACTED      │  │           │
│   │   • Status     │                       │    │ FEATURES       │  │           │
│   └────────────────┘                       │    │ • Diagnoses    │  │           │
│                                            │    │ • Injuries     │  │           │
│   ┌────────────────┐                       │    │ • Amounts      │  │           │
│   │ UNDERWRITING   │──────────────────────►│    │ • Dates        │  │           │
│   │   • Risk Score │   UW Assessment       │    └───────┬────────┘  │           │
│   │   • Conditions │                       │            │           │           │
│   │   • Documents  │                       └────────────┼───────────┘           │
│   │   • Decisions  │                                    │                       │
│   └────────────────┘                                    │                       │
│                                                         ▼                       │
│   ┌────────────────┐                       ┌────────────────────────┐           │
│   │ CLAIMS HISTORY │──────────────────────►│   CROSS-REFERENCE      │           │
│   │   • Past claims│   Claims Patterns     │   ENGINE               │           │
│   │   • Frequencies│                       │   ┌────────────────┐   │           │
│   │   • Outcomes   │                       │   │ UW Comparison  │   │           │
│   └────────────────┘                       │   │ Hidden Detect  │   │           │
│                                            │   │ Timeline Build │   │           │
│                                            │   │ Risk Delta     │   │           │
│   NEW CLAIM DATA                           │   └───────┬────────┘   │           │
│   ══════════════                           │           │            │           │
│                                            └───────────┼────────────┘           │
│   ┌────────────────┐                                   │                        │
│   │ CLAIM METADATA │───────────────────────────────────┤                        │
│   │   • Photos     │                                   │                        │
│   │   • Documents  │                                   ▼                        │
│   │   • Reports    │                       ┌────────────────────────┐           │
│   │   • Statements │                       │   FRAUD DETECTION      │           │
│   └────────────────┘                       │   ┌────────────────┐   │           │
│                                            │   │ Pattern Match  │   │           │
│   ┌────────────────┐                       │   │ Timing Check   │   │           │
│   │  CLAIM FORM    │──────────────────────►│   │ Amount Verify  │   │           │
│   │   • Type       │   Claim Details       │   │ Doc Integrity  │   │           │
│   │   • Amount     │                       │   └───────┬────────┘   │           │
│   │   • Date       │                       │           │            │           │
│   │   • Desc       │                       └───────────┼────────────┘           │
│   └────────────────┘                                   │                        │
│                                                        ▼                        │
│                                            ┌────────────────────────┐           │
│                                            │   BI/AI ASSESSMENT     │           │
│                                            │   ┌────────────────┐   │           │
│                                            │   │ ML Prediction  │   │           │
│                                            │   │ Risk Scoring   │   │           │
│                                            │   │ Decision Logic │   │           │
│                                            │   └───────┬────────┘   │           │
│                                            └───────────┼────────────┘           │
│                                                        │                        │
│                                                        ▼                        │
│   OUTPUT                                   ┌────────────────────────┐           │
│   ══════                                   │  CLAIM RISK REPORT     │           │
│                                            │  ┌────────────────┐    │           │
│   ┌────────────────┐◄──────────────────────│  │ Risk Score     │    │           │
│   │  CLAIM STATUS  │                       │  │ Fraud Score    │    │           │
│   │  (Updated)     │                       │  │ Hidden Cond    │    │           │
│   └────────────────┘                       │  │ Recommendation │    │           │
│                                            │  │ Explanation    │    │           │
│   ┌────────────────┐◄──────────────────────│  └────────────────┘    │           │
│   │  AUDIT LOG     │                       └────────────────────────┘           │
│   │  (All Actions) │                                                            │
│   └────────────────┘                                                            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. FRAUD DETECTION DECISION TREE

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        FRAUD DETECTION DECISION TREE                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│                            ┌─────────────────────┐                              │
│                            │  START FRAUD CHECK  │                              │
│                            └──────────┬──────────┘                              │
│                                       │                                         │
│                                       ▼                                         │
│                    ┌──────────────────────────────────┐                         │
│                    │ CHECK #1: TIMING ANALYSIS        │                         │
│                    │ Time since policy start?         │                         │
│                    └─────────────────┬────────────────┘                         │
│                                      │                                          │
│           ┌──────────────────────────┼──────────────────────────┐               │
│           │                          │                          │               │
│           ▼                          ▼                          ▼               │
│   ┌───────────────┐        ┌───────────────┐        ┌───────────────┐          │
│   │   < 90 DAYS   │        │  90d - 2yrs   │        │   > 2 YEARS   │          │
│   │ HIGH SUSPICION│        │   MODERATE    │        │   NORMAL      │          │
│   │ Score: +0.35  │        │ Score: +0.15  │        │ Score: +0.00  │          │
│   └───────────────┘        └───────────────┘        └───────────────┘          │
│                                      │                                          │
│                                      ▼                                          │
│                    ┌──────────────────────────────────┐                         │
│                    │ CHECK #2: CLAIM AMOUNT           │                         │
│                    │ Amount vs coverage ratio?        │                         │
│                    └─────────────────┬────────────────┘                         │
│                                      │                                          │
│           ┌──────────────────────────┼──────────────────────────┐               │
│           │                          │                          │               │
│           ▼                          ▼                          ▼               │
│   ┌───────────────┐        ┌───────────────┐        ┌───────────────┐          │
│   │   > 80%       │        │  30% - 80%    │        │   < 30%       │          │
│   │ HIGH SUSPICION│        │   NORMAL      │        │   LOW RISK    │          │
│   │ Score: +0.25  │        │ Score: +0.05  │        │ Score: +0.00  │          │
│   └───────────────┘        └───────────────┘        └───────────────┘          │
│                                      │                                          │
│                                      ▼                                          │
│                    ┌──────────────────────────────────┐                         │
│                    │ CHECK #3: HIDDEN CONDITIONS      │                         │
│                    │ Undisclosed pre-existing?        │                         │
│                    └─────────────────┬────────────────┘                         │
│                                      │                                          │
│           ┌──────────────────────────┼──────────────────────────┐               │
│           │                          │                          │               │
│           ▼                          ▼                          ▼               │
│   ┌───────────────┐        ┌───────────────┐        ┌───────────────┐          │
│   │ CAUSALLY      │        │ FOUND BUT     │        │ NONE FOUND    │          │
│   │ LINKED TO     │        │ NOT LINKED    │        │               │          │
│   │ CLAIM         │        │ TO CLAIM      │        │ Score: +0.00  │          │
│   │ Score: +0.50  │        │ Score: +0.20  │        │               │          │
│   │ → DENY        │        │ → INVESTIGATE │        └───────────────┘          │
│   └───────────────┘        └───────────────┘                                    │
│                                      │                                          │
│                                      ▼                                          │
│                    ┌──────────────────────────────────┐                         │
│                    │ CHECK #4: DOCUMENT INTEGRITY     │                         │
│                    │ Any tampering detected?          │                         │
│                    └─────────────────┬────────────────┘                         │
│                                      │                                          │
│           ┌──────────────────────────┼──────────────────────────┐               │
│           │                          │                          │               │
│           ▼                          ▼                          ▼               │
│   ┌───────────────┐        ┌───────────────┐        ┌───────────────┐          │
│   │   TAMPERING   │        │  SUSPICIOUS   │        │   AUTHENTIC   │          │
│   │   DETECTED    │        │  ELEMENTS     │        │               │          │
│   │ Score: +0.60  │        │ Score: +0.20  │        │ Score: +0.00  │          │
│   │ → DENY        │        │ → INVESTIGATE │        │               │          │
│   └───────────────┘        └───────────────┘        └───────────────┘          │
│                                      │                                          │
│                                      ▼                                          │
│                    ┌──────────────────────────────────┐                         │
│                    │ CHECK #5: CLAIM HISTORY          │                         │
│                    │ Frequency of past claims?        │                         │
│                    └─────────────────┬────────────────┘                         │
│                                      │                                          │
│           ┌──────────────────────────┼──────────────────────────┐               │
│           │                          │                          │               │
│           ▼                          ▼                          ▼               │
│   ┌───────────────┐        ┌───────────────┐        ┌───────────────┐          │
│   │   > 3/YEAR    │        │  1-3/YEAR     │        │  < 1/YEAR     │          │
│   │ HIGH FREQUENCY│        │   MODERATE    │        │   NORMAL      │          │
│   │ Score: +0.20  │        │ Score: +0.10  │        │ Score: +0.00  │          │
│   └───────────────┘        └───────────────┘        └───────────────┘          │
│                                      │                                          │
│                                      ▼                                          │
│                    ┌──────────────────────────────────┐                         │
│                    │  CALCULATE TOTAL FRAUD SCORE     │                         │
│                    │  Sum of all check scores         │                         │
│                    └─────────────────┬────────────────┘                         │
│                                      │                                          │
│           ┌──────────────────────────┼──────────────────────────┐               │
│           │                          │                          │               │
│           ▼                          ▼                          ▼               │
│   ┌───────────────┐        ┌───────────────┐        ┌───────────────┐          │
│   │ SCORE > 0.70  │        │ 0.35 - 0.70   │        │ SCORE < 0.35  │          │
│   │               │        │               │        │               │          │
│   │ FRAUD LIKELY  │        │ INVESTIGATE   │        │ LOW FRAUD     │          │
│   │ → AUTO DENY   │        │ → REFER SIU   │        │ RISK          │          │
│   │ → SIU ALERT   │        │               │        │ → CONTINUE    │          │
│   └───────────────┘        └───────────────┘        └───────────────┘          │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

SPECIAL CASE: 7.66 YEAR RULE
═══════════════════════════════════════════════════════════════════════════════════

When claim_time_since_policy ≈ 7.66 years AND claim_amount ≈ full_coverage:

┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ┌───────────────────────────────────────────────────────────────────────┐    │
│   │                    ENHANCED SCRUTINY TRIGGER                          │    │
│   │                                                                       │    │
│   │   IF (time_since_policy >= 7 years AND time_since_policy <= 8 years)  │    │
│   │   AND (claim_amount >= coverage * 0.85)                               │    │
│   │                                                                       │    │
│   │   THEN:                                                               │    │
│   │   1. MANDATORY deep medical history scan                              │    │
│   │   2. Cross-reference ALL underwriting documents                       │    │
│   │   3. Request additional medical records (5 year history)              │    │
│   │   4. Check for progressive conditions hidden at UW                    │    │
│   │   5. Analyze if condition was PREDICTABLE at policy start             │    │
│   │   6. Calculate probability of deliberate concealment                  │    │
│   │                                                                       │    │
│   │   FRAUD_SCORE_MODIFIER: +0.25 (added suspicion for timing)            │    │
│   │                                                                       │    │
│   └───────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. BI/ML PREDICTION MODEL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     BI/ML CLAIM PREDICTION ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   INPUT FEATURES                        ML MODELS                               │
│   ══════════════                        ═════════                               │
│                                                                                 │
│   ┌──────────────────┐                  ┌────────────────────────────────────┐ │
│   │ CLAIM FEATURES   │                  │                                    │ │
│   │ • Type           │                  │    LEGITIMACY PREDICTOR            │ │
│   │ • Amount         │─────────────────►│    (Gradient Boosting)             │ │
│   │ • Date           │                  │    ┌────────────────────────────┐  │ │
│   │ • Description    │                  │    │ Training: 100K+ claims     │  │ │
│   │ • Category       │                  │    │ Features: 45               │  │ │
│   └──────────────────┘                  │    │ Output: P(legitimate)      │  │ │
│                                         │    │ Accuracy: 94.2%            │  │ │
│   ┌──────────────────┐                  │    └────────────────────────────┘  │ │
│   │ CUSTOMER PROFILE │                  │                                    │ │
│   │ • Age            │                  └────────────────────────────────────┘ │
│   │ • Occupation     │                                                        │
│   │ • Tenure         │                  ┌────────────────────────────────────┐ │
│   │ • Claim History  │─────────────────►│                                    │ │
│   │ • Payment History│                  │    FRAUD DETECTOR                  │ │
│   └──────────────────┘                  │    (Random Forest + Rules)         │ │
│                                         │    ┌────────────────────────────┐  │ │
│   ┌──────────────────┐                  │    │ Training: Fraud cases      │  │ │
│   │ POLICY FEATURES  │                  │    │ Features: 32               │  │ │
│   │ • Type           │─────────────────►│    │ Output: P(fraud)           │  │ │
│   │ • Coverage       │                  │    │ Precision: 89.1%           │  │ │
│   │ • Start Date     │                  │    │ Recall: 76.3%              │  │ │
│   │ • Premium Paid   │                  │    └────────────────────────────┘  │ │
│   │ • Risk Score     │                  │                                    │ │
│   └──────────────────┘                  └────────────────────────────────────┘ │
│                                                                                │
│   ┌──────────────────┐                  ┌────────────────────────────────────┐ │
│   │ UW CROSS-REF     │                  │                                    │ │
│   │ • Hidden Cond    │─────────────────►│    HIDDEN CONDITION DETECTOR       │ │
│   │ • Risk Delta     │                  │    (NLP + Medical Ontology)        │ │
│   │ • Time Factor    │                  │    ┌────────────────────────────┐  │ │
│   │ • Declaration    │                  │    │ Medical entity extraction  │  │ │
│   └──────────────────┘                  │    │ ICD-10 code mapping        │  │ │
│                                         │    │ Temporal analysis          │  │ │
│   ┌──────────────────┐                  │    │ Causality inference        │  │ │
│   │ DOCUMENT SCORES  │                  │    └────────────────────────────┘  │ │
│   │ • Authenticity   │─────────────────►│                                    │ │
│   │ • Consistency    │                  └────────────────────────────────────┘ │
│   │ • Completeness   │                                                        │
│   └──────────────────┘                  ┌────────────────────────────────────┐ │
│                                         │                                    │ │
│                                         │    SETTLEMENT OPTIMIZER            │ │
│                         ───────────────►│    (Regression + Actuarial)        │ │
│                                         │    ┌────────────────────────────┐  │ │
│                                         │    │ Optimal settlement amount  │  │ │
│                                         │    │ Expected loss calculation  │  │ │
│                                         │    │ Reserve requirement        │  │ │
│                                         │    └────────────────────────────┘  │ │
│                                         │                                    │ │
│                                         └────────────────────────────────────┘ │
│                                                                                │
│                                         ┌────────────────────────────────────┐ │
│   OUTPUT                                │                                    │ │
│   ══════                                │    DECISION AGGREGATOR             │ │
│                                         │    (Ensemble + Business Rules)     │ │
│   ┌──────────────────────────────────┐  │    ┌────────────────────────────┐  │ │
│   │                                  │◄─┤    │ Combine all model outputs  │  │ │
│   │    FINAL DECISION                │  │    │ Apply business rules       │  │ │
│   │    ┌──────────────────────────┐  │  │    │ Generate explanation       │  │ │
│   │    │ • Decision: APPROVE/DENY │  │  │    │ Calculate confidence       │  │ │
│   │    │ • Confidence: 0-100%     │  │  │    └────────────────────────────┘  │ │
│   │    │ • Recommended Amount     │  │  │                                    │ │
│   │    │ • Risk Factors           │  │  └────────────────────────────────────┘ │
│   │    │ • Explanation            │  │                                        │
│   │    └──────────────────────────┘  │                                        │
│   │                                  │                                        │
│   └──────────────────────────────────┘                                        │
│                                                                                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. DATA INTEGRITY PROTECTION RULES

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     DATA INTEGRITY PROTECTION MATRIX                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   DATA STORE              ACCESS MODE       CLAIMS BOT OPERATIONS               │
│   ══════════              ═══════════       ═══════════════════                 │
│                                                                                 │
│   ┌────────────────────┐  ┌──────────┐   ┌──────────────────────────────────┐  │
│   │     CUSTOMERS      │  │READ-ONLY │   │ • Load customer profile          │  │
│   │                    │  │          │   │ • Verify identity                │  │
│   │ • id               │──┤ ✓ READ   │──►│ • Get contact for notifications  │  │
│   │ • name             │  │ ✗ WRITE  │   │ • Historical data reference      │  │
│   │ • email            │  │ ✗ DELETE │   │                                  │  │
│   │ • transactions     │  │          │   │ NEVER: Modify customer records   │  │
│   │ • investments      │  │          │   │                                  │  │
│   └────────────────────┘  └──────────┘   └──────────────────────────────────┘  │
│                                                                                 │
│   ┌────────────────────┐  ┌──────────┐   ┌──────────────────────────────────┐  │
│   │     POLICIES       │  │READ-ONLY │   │ • Load policy details            │  │
│   │                    │  │          │   │ • Verify coverage limits         │  │
│   │ • id               │──┤ ✓ READ   │──►│ • Check policy status            │  │
│   │ • type             │  │ ✗ WRITE  │   │ • Get start date for timing      │  │
│   │ • coverage         │  │ ✗ DELETE │   │ • Verify claim eligibility       │  │
│   │ • status           │  │          │   │                                  │  │
│   │ • start_date       │  │          │   │ NEVER: Modify policy records     │  │
│   └────────────────────┘  └──────────┘   └──────────────────────────────────┘  │
│                                                                                 │
│   ┌────────────────────┐  ┌──────────┐   ┌──────────────────────────────────┐  │
│   │   UNDERWRITING     │  │READ-ONLY │   │ • Load UW assessment             │  │
│   │                    │  │          │   │ • Get declared conditions        │  │
│   │ • id               │──┤ ✓ READ   │──►│ • Compare to claim data          │  │
│   │ • conditions       │  │ ✗ WRITE  │   │ • Detect hidden conditions       │  │
│   │ • risk_score       │  │ ✗ DELETE │   │ • Calculate risk delta           │  │
│   │ • documents        │  │          │   │                                  │  │
│   │ • decision         │  │          │   │ NEVER: Modify UW records         │  │
│   └────────────────────┘  └──────────┘   └──────────────────────────────────┘  │
│                                                                                 │
│   ┌────────────────────┐  ┌──────────┐   ┌──────────────────────────────────┐  │
│   │   CLAIMS HISTORY   │  │READ-ONLY │   │ • Load past claims               │  │
│   │                    │  │          │   │ • Analyze claim patterns         │  │
│   │ • past_claims      │──┤ ✓ READ   │──►│ • Calculate frequency            │  │
│   │ • outcomes         │  │ ✗ WRITE  │   │ • Fraud pattern matching         │  │
│   │ • amounts          │  │ ✗ DELETE │   │                                  │  │
│   │ • dates            │  │          │   │ NEVER: Modify past claims        │  │
│   └────────────────────┘  └──────────┘   └──────────────────────────────────┘  │
│                                                                                 │
│   ┌────────────────────┐  ┌──────────┐   ┌──────────────────────────────────┐  │
│   │   CURRENT CLAIM    │  │READ/WRITE│   │ • Load claim details             │  │
│   │                    │  │          │   │ • Update status                  │  │
│   │ • id               │──┤ ✓ READ   │──►│ • Add assessment results         │  │
│   │ • status           │  │ ✓ WRITE* │   │ • Record decision                │  │
│   │ • evidence         │  │ ✗ DELETE │   │ • Link to report                 │  │
│   │ • assessment       │  │          │   │                                  │  │
│   └────────────────────┘  └──────────┘   │ * Only additive updates          │  │
│                                          │   (status, assessment, notes)    │  │
│                                          │   NEVER delete or reset claim    │  │
│                                          └──────────────────────────────────┘  │
│                                                                                 │
│   ┌────────────────────┐  ┌──────────┐   ┌──────────────────────────────────┐  │
│   │  BOT ASSESSMENTS   │  │ WRITE    │   │ • Create new assessments         │  │
│   │  (Bot's own data)  │  │          │   │ • Store processed evidence       │  │
│   │                    │──┤ ✓ READ   │──►│ • Generate reports               │  │
│   │ • assessments      │  │ ✓ WRITE  │   │ • Record decisions               │  │
│   │ • reports          │  │ ✓ DELETE │   │                                  │  │
│   │ • metadata         │  │          │   │ This is the bot's working space  │  │
│   └────────────────────┘  └──────────┘   └──────────────────────────────────┘  │
│                                                                                 │
│   ┌────────────────────┐  ┌──────────┐   ┌──────────────────────────────────┐  │
│   │   AUDIT LOG        │  │APPEND    │   │ • Log all actions                │  │
│   │                    │  │ONLY      │   │ • Record decisions               │  │
│   │ • events           │──┤ ✗ READ*  │──►│ • Track evidence processing      │  │
│   │ • timestamps       │  │ ✓ APPEND │   │ • Store fraud alerts             │  │
│   │ • actors           │  │ ✗ DELETE │   │                                  │  │
│   └────────────────────┘  └──────────┘   │ * Read only for authorized users │  │
│                                          │   NEVER modify or delete logs    │  │
│                                          └──────────────────────────────────┘  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. IMPLEMENTATION PLAN

### Phase 1: Core Infrastructure
- [ ] Create `ClaimsBotService` class
- [ ] Implement metadata analyzers for claims
- [ ] Build evidence processing pipeline

### Phase 2: Cross-Reference Engine
- [ ] Implement `UnderwritingCrossRefEngine`
- [ ] Build hidden condition detection algorithm
- [ ] Create medical timeline analyzer

### Phase 3: Fraud Detection
- [ ] Implement `FraudDetectionEngine`
- [ ] Build pattern matching system
- [ ] Create timing and amount analyzers

### Phase 4: BI/ML Integration
- [ ] Implement `ClaimBIEngine`
- [ ] Build decision aggregator
- [ ] Create settlement optimizer

### Phase 5: API Integration
- [ ] Add claim bot endpoints
- [ ] Integrate with existing claims flow
- [ ] Build adjuster interface

---

**Document Version:** 1.0.0  
**Status:** Ready for Implementation  
**Approval Required:** Yes - before coding begins
