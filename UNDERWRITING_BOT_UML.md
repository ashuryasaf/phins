# Underwriting Bot Risk Assessment - Process UML

## Overview

This document defines the process architecture for the AI-powered Underwriting Bot that processes metadata (photos, medical reports, official documents, audio, video) to create comprehensive risk assessment reports for automated and assisted underwriting decisions.

---

## 1. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                            PHINS INSURANCE PLATFORM                                      │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   ┌──────────────┐      ┌─────────────────────────────────────────────────────────────┐ │
│   │   CUSTOMER   │      │               UNDERWRITING BOT SYSTEM                        │ │
│   │   PORTAL     │─────▶│                                                              │ │
│   │              │      │  ┌───────────────┐   ┌─────────────────────────────────────┐│ │
│   │ • Application│      │  │   METADATA    │   │      AI RISK ASSESSMENT ENGINE      ││ │
│   │ • Documents  │      │  │   PROCESSOR   │──▶│                                     ││ │
│   │ • Media      │      │  │               │   │  • Document Analysis                ││ │
│   └──────────────┘      │  │ • Photos      │   │  • Medical Report Parsing           ││ │
│                         │  │ • Medical     │   │  • Identity Verification            ││ │
│   ┌──────────────┐      │  │ • Documents   │   │  • Audio/Video Analysis             ││ │
│   │    ADMIN     │      │  │ • Audio       │   │  • Risk Score Calculation           ││ │
│   │   PORTAL     │◀─────│  │ • Video       │   │  • Recommendation Engine            ││ │
│   │              │      │  └───────────────┘   └─────────────────────────────────────┘│ │
│   │ • Review     │      │                                                              │ │
│   │ • Decision   │      │  ┌───────────────┐   ┌─────────────────────────────────────┐│ │
│   │ • Reports    │      │  │  VALIDATION   │   │         DATA INTEGRITY              ││ │
│   └──────────────┘      │  │   PIPELINE    │──▶│                                     ││ │
│                         │  │               │   │  • Customer Data Protection         ││ │
│   ┌──────────────┐      │  │ • Verify Docs │   │  • Transaction Preservation         ││ │
│   │  EXISTING    │◀────▶│  │ • Check Rules │   │  • Investment Account Safety        ││ │
│   │  DATABASE    │      │  │ • Audit Trail │   │  • Claims History Intact            ││ │
│   │              │      │  └───────────────┘   └─────────────────────────────────────┘│ │
│   │ • Customers  │      │                                                              │ │
│   │ • Policies   │      └─────────────────────────────────────────────────────────────┘ │
│   │ • Claims     │                                                                       │
│   │ • Accounts   │                                                                       │
│   └──────────────┘                                                                       │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Class Diagram - Underwriting Bot Components

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              UNDERWRITING BOT CLASSES                                    │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│       UnderwritingBot           │         │      MetadataProcessor          │
├─────────────────────────────────┤         ├─────────────────────────────────┤
│ - bot_id: str                   │         │ - processor_id: str             │
│ - name: str                     │         │ - supported_types: List[str]    │
│ - version: str                  │         │ - extractors: Dict              │
│ - active_assessments: Dict      │         ├─────────────────────────────────┤
│ - config: BotConfiguration      │────────▶│ + process_photo()               │
├─────────────────────────────────┤         │ + process_medical_report()      │
│ + start_assessment()            │         │ + process_official_document()   │
│ + process_metadata()            │         │ + process_audio()               │
│ + generate_risk_report()        │         │ + process_video()               │
│ + make_decision()               │         │ + validate_metadata()           │
│ + get_decision_explanation()    │         │ + extract_features()            │
└─────────────────────────────────┘         └─────────────────────────────────┘
         │                                              │
         │                                              │
         ▼                                              ▼
┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│       RiskAssessmentEngine      │         │      DocumentAnalyzer           │
├─────────────────────────────────┤         ├─────────────────────────────────┤
│ - engine_id: str                │         │ - analyzer_id: str              │
│ - risk_models: Dict             │         │ - document_types: List          │
│ - threshold_config: Dict        │         │ - ocr_enabled: bool             │
│ - decision_rules: List          │         │ - validation_rules: Dict        │
├─────────────────────────────────┤         ├─────────────────────────────────┤
│ + calculate_risk_score()        │         │ + analyze_passport()            │
│ + apply_risk_factors()          │         │ + analyze_driving_licence()     │
│ + generate_recommendation()     │         │ + analyze_disability_cert()     │
│ + explain_decision()            │         │ + analyze_national_insurance()  │
│ + validate_against_rules()      │         │ + verify_authenticity()         │
└─────────────────────────────────┘         │ + extract_document_data()       │
         │                                  └─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│       RiskAssessmentReport      │         │      MedicalReportAnalyzer      │
├─────────────────────────────────┤         ├─────────────────────────────────┤
│ - report_id: str                │         │ - analyzer_id: str              │
│ - customer_id: str              │         │ - condition_codes: Dict         │
│ - assessment_id: str            │         │ - risk_mappings: Dict           │
│ - overall_risk_score: float     │         ├─────────────────────────────────┤
│ - risk_factors: List            │         │ + parse_medical_report()        │
│ - document_scores: Dict         │         │ + identify_conditions()         │
│ - medical_flags: List           │         │ + calculate_health_risk()       │
│ - identity_verified: bool       │         │ + flag_preexisting()            │
│ - recommendation: str           │         │ + generate_medical_summary()    │
│ - decision: str                 │         └─────────────────────────────────┘
│ - confidence_level: float       │
│ - explanation: str              │         ┌─────────────────────────────────┐
│ - created_at: datetime          │         │      AudioVideoAnalyzer         │
├─────────────────────────────────┤         ├─────────────────────────────────┤
│ + to_dict()                     │         │ - analyzer_id: str              │
│ + generate_summary()            │         │ - transcription_enabled: bool   │
│ + get_risk_breakdown()          │         │ - sentiment_analysis: bool      │
└─────────────────────────────────┘         ├─────────────────────────────────┤
                                            │ + transcribe_audio()            │
                                            │ + analyze_video_content()       │
                                            │ + detect_sentiment()            │
                                            │ + verify_identity_video()       │
                                            │ + extract_health_indicators()   │
                                            └─────────────────────────────────┘
```

---

## 3. Sequence Diagram - Full Risk Assessment Flow

```
┌──────────┐  ┌───────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌────────────┐
│ Customer │  │  Portal   │  │ UnderwritingBot │  │MetadataProcessor│  │RiskAssessEngine │  │  Database  │
└────┬─────┘  └─────┬─────┘  └───────┬─────────┘  └───────┬─────────┘  └───────┬─────────┘  └──────┬─────┘
     │              │                │                     │                     │                  │
     │ Submit App   │                │                     │                     │                  │
     │─────────────▶│                │                     │                     │                  │
     │              │ Create Session │                     │                     │                  │
     │              │───────────────▶│                     │                     │                  │
     │              │                │ Verify Customer     │                     │                  │
     │              │                │────────────────────────────────────────────────────────────▶│
     │              │                │                     │                     │    Customer     │
     │              │                │◀───────────────────────────────────────────────────────────│
     │              │                │                     │                     │     Data        │
     │ Upload Docs  │                │                     │                     │                  │
     │─────────────▶│                │                     │                     │                  │
     │              │ Process Docs   │                     │                     │                  │
     │              │───────────────▶│                     │                     │                  │
     │              │                │ Analyze Metadata    │                     │                  │
     │              │                │────────────────────▶│                     │                  │
     │              │                │                     │                     │                  │
     │              │                │                     │ Process Photo       │                  │
     │              │                │                     │ ─ ─ ─ ─ ─ ─ ─ ▶    │                  │
     │              │                │                     │                     │                  │
     │              │                │                     │ Process Medical     │                  │
     │              │                │                     │ ─ ─ ─ ─ ─ ─ ─ ▶    │                  │
     │              │                │                     │                     │                  │
     │              │                │                     │ Process Documents   │                  │
     │              │                │                     │ ─ ─ ─ ─ ─ ─ ─ ▶    │                  │
     │              │                │                     │                     │                  │
     │              │                │                     │ Process Audio/Video │                  │
     │              │                │                     │ ─ ─ ─ ─ ─ ─ ─ ▶    │                  │
     │              │                │                     │                     │                  │
     │              │                │  Extracted Features │                     │                  │
     │              │                │◀───────────────────│                     │                  │
     │              │                │                     │                     │                  │
     │              │                │ Calculate Risk Score│                     │                  │
     │              │                │───────────────────────────────────────────▶│                  │
     │              │                │                     │                     │                  │
     │              │                │                     │                     │ Check History   │
     │              │                │                     │                     │────────────────▶│
     │              │                │                     │                     │    Claims &     │
     │              │                │                     │                     │◀───────────────│
     │              │                │                     │                     │   Policies      │
     │              │                │                     │                     │                  │
     │              │                │ Risk Assessment     │                     │                  │
     │              │                │◀──────────────────────────────────────────│                  │
     │              │                │                     │                     │                  │
     │              │                │ Store Assessment    │                     │                  │
     │              │                │─────────────────────────────────────────────────────────────▶│
     │              │                │                     │                     │                  │
     │              │                │ Generate Decision   │                     │                  │
     │              │                │─────────────────────────────────────────────────────────────▶│
     │              │                │                     │                     │                  │
     │              │  Assessment    │                     │                     │                  │
     │              │◀──────────────│                     │                     │                  │
     │   Result     │                │                     │                     │                  │
     │◀────────────│                │                     │                     │                  │
     │              │                │                     │                     │                  │
```

---

## 4. State Diagram - Assessment Lifecycle

```
                                    ┌─────────────────┐
                                    │    INITIATED    │
                                    │                 │
                                    │  Assessment     │
                                    │  Created        │
                                    └────────┬────────┘
                                             │
                                             ▼
                    ┌────────────────────────────────────────────────┐
                    │              COLLECTING_METADATA                │
                    │                                                 │
                    │  • Documents uploaded                           │
                    │  • Photos captured                              │
                    │  • Medical reports submitted                    │
                    │  • Audio/Video recordings added                 │
                    └────────────────────┬───────────────────────────┘
                                         │
                                         ▼
                    ┌────────────────────────────────────────────────┐
                    │              VALIDATING_METADATA                │
                    │                                                 │
                    │  • Document authenticity check                  │
                    │  • Image quality validation                     │
                    │  • Format verification                          │
                    │  • Completeness check                           │
                    └────────────────────┬───────────────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         │                               │
                         ▼                               ▼
        ┌────────────────────────┐          ┌────────────────────────┐
        │    VALIDATION_FAILED   │          │    PROCESSING          │
        │                        │          │                        │
        │  • Missing documents   │          │  • Extracting data     │
        │  • Invalid format      │          │  • Parsing medical     │
        │  • Poor quality        │          │  • OCR processing      │
        │                        │          │  • Feature extraction  │
        └────────────────────────┘          └───────────┬────────────┘
                         │                              │
                         │                              ▼
                         │              ┌────────────────────────────┐
                         │              │      RISK_ASSESSING        │
                         │              │                            │
                         │              │  • Scoring risk factors    │
                         │              │  • Medical risk calc       │
                         │              │  • ID verification         │
                         │              │  • History analysis        │
                         │              └───────────┬────────────────┘
                         │                          │
                         │                          ▼
                         │              ┌────────────────────────────┐
                         │              │      DECISION_READY        │
                         │              │                            │
                         │              │  Risk Report Generated     │
                         │              │  AI Recommendation Made    │
                         │              └───────────┬────────────────┘
                         │                          │
                         │          ┌───────────────┼───────────────┬──────────────┐
                         │          │               │               │              │
                         │          ▼               ▼               ▼              ▼
                         │   ┌──────────┐    ┌──────────┐    ┌──────────┐   ┌──────────┐
                         │   │ APPROVED │    │ REJECTED │    │ REFERRED │   │CONDITIONAL│
                         │   │          │    │          │    │          │   │ APPROVAL │
                         │   │Auto/Manual    │Auto/Manual    │To Manual │   │          │
                         │   │Decision  │    │Decision  │    │Review    │   │With Terms│
                         └──▶└──────────┘    └──────────┘    └──────────┘   └──────────┘
                (Resubmit)        │               │               │              │
                                  └───────────────┴───────────────┴──────────────┘
                                                         │
                                                         ▼
                                             ┌────────────────────────┐
                                             │       COMPLETED        │
                                             │                        │
                                             │  Assessment Archived   │
                                             │  Report Finalized      │
                                             │  Audit Trail Complete  │
                                             └────────────────────────┘
```

---

## 5. Activity Diagram - Metadata Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           METADATA PROCESSING PIPELINE                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────────────┐
                                    │     START       │
                                    │   Receive       │
                                    │   Metadata      │
                                    └────────┬────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────┐
                              │    Classify Metadata Type   │
                              │                             │
                              │  • Photo/Image              │
                              │  • Medical Report (PDF)     │
                              │  • Official Document        │
                              │  • Audio Recording          │
                              │  • Video Recording          │
                              └──────────────┬──────────────┘
                                             │
              ┌──────────────┬───────────────┼───────────────┬──────────────┐
              │              │               │               │              │
              ▼              ▼               ▼               ▼              ▼
       ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
       │   PHOTO   │  │  MEDICAL  │  │ OFFICIAL  │  │   AUDIO   │  │   VIDEO   │
       │  PROCESS  │  │  REPORT   │  │ DOCUMENT  │  │  PROCESS  │  │  PROCESS  │
       │           │  │  PROCESS  │  │  PROCESS  │  │           │  │           │
       └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
             │              │               │               │              │
             ▼              ▼               ▼               ▼              ▼
       ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
       │Face Match │  │Parse Text │  │OCR Extract│  │Transcribe │  │Transcribe │
       │Quality Chk│  │Extract    │  │Verify Auth│  │Analyze    │  │Face Match │
       │Health Ind │  │Conditions │  │Extract ID │  │Sentiment  │  │Extract    │
       │           │  │Flag Issues│  │Verify Exp │  │           │  │Sentiment  │
       └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
             │              │               │               │              │
             └──────────────┴───────────────┼───────────────┴──────────────┘
                                            │
                                            ▼
                              ┌─────────────────────────────┐
                              │    AGGREGATE FEATURES       │
                              │                             │
                              │  • Identity Score           │
                              │  • Health Risk Score        │
                              │  • Document Validity Score  │
                              │  • Behavioral Indicators    │
                              │  • Fraud Detection Score    │
                              └──────────────┬──────────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────┐
                              │    VALIDATE DATA INTEGRITY  │
                              │                             │
                              │  ✓ Preserve Customer Data   │
                              │  ✓ No Reset of Transactions │
                              │  ✓ Investment Accts Intact  │
                              │  ✓ Claims History Preserved │
                              └──────────────┬──────────────┘
                                             │
                                             ▼
                                    ┌────────────────┐
                                    │     END        │
                                    │  Features      │
                                    │  Extracted     │
                                    └────────────────┘
```

---

## 6. Data Flow Diagram - Risk Assessment

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              RISK ASSESSMENT DATA FLOW                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                          INPUTS                          PROCESSING                    OUTPUTS
┌──────────────────────────────────────┐    ┌─────────────────────────────┐    ┌─────────────────────┐
│                                      │    │                             │    │                     │
│  ┌────────────────────────────────┐  │    │  ┌─────────────────────┐   │    │  ┌───────────────┐  │
│  │   Customer Application Data    │──┼───▶│  │ Identity           │   │    │  │ Risk Score    │  │
│  │                                │  │    │  │ Verification       │   │    │  │ (0.0 - 1.0)   │  │
│  │   • Personal Details           │  │    │  │                    │   │    │  └───────────────┘  │
│  │   • Contact Info               │  │    │  │ • Face matching    │   │    │                     │
│  │   • Employment                 │  │    │  │ • Document OCR     │   │    │  ┌───────────────┐  │
│  └────────────────────────────────┘  │    │  │ • Liveness check   │───┼───▶│  │ Risk Level    │  │
│                                      │    │  └─────────────────────┘   │    │  │               │  │
│  ┌────────────────────────────────┐  │    │                            │    │  │ Very Low/Low/ │  │
│  │   Official Documents           │──┼───▶│  ┌─────────────────────┐   │    │  │ Medium/High/  │  │
│  │                                │  │    │  │ Document            │   │    │  │ Very High     │  │
│  │   • Passport                   │  │    │  │ Validation          │   │    │  └───────────────┘  │
│  │   • Driving Licence            │  │    │  │                    │   │    │                     │
│  │   • National Insurance         │  │    │  │ • Authenticity     │   │    │  ┌───────────────┐  │
│  │   • Disability Certificate     │  │    │  │ • Expiry check     │───┼───▶│  │ Risk Factors  │  │
│  └────────────────────────────────┘  │    │  │ • Data extraction  │   │    │  │               │  │
│                                      │    │  └─────────────────────┘   │    │  │ • Age         │  │
│  ┌────────────────────────────────┐  │    │                            │    │  │ • Health      │  │
│  │   Medical Reports              │──┼───▶│  ┌─────────────────────┐   │    │  │ • Lifestyle   │  │
│  │                                │  │    │  │ Medical             │   │    │  │ • Occupation  │  │
│  │   • Health Records             │  │    │  │ Analysis            │   │    │  │ • Location    │  │
│  │   • Lab Results                │  │    │  │                    │   │    │  └───────────────┘  │
│  │   • Prescriptions              │  │    │  │ • Condition ID     │   │    │                     │
│  │   • Hospital Reports           │  │    │  │ • Risk mapping     │───┼───▶│  ┌───────────────┐  │
│  └────────────────────────────────┘  │    │  │ • Pre-existing     │   │    │  │ Recommendation│  │
│                                      │    │  └─────────────────────┘   │    │  │               │  │
│  ┌────────────────────────────────┐  │    │                            │    │  │ • APPROVE     │  │
│  │   Photos/Images                │──┼───▶│  ┌─────────────────────┐   │    │  │ • CONDITIONAL │  │
│  │                                │  │    │  │ Visual              │   │    │  │ • REFER       │  │
│  │   • ID Photos                  │  │    │  │ Analysis            │   │    │  │ • DECLINE     │  │
│  │   • Selfies                    │  │    │  │                    │   │    │  └───────────────┘  │
│  │   • Property Photos            │  │    │  │ • Quality check    │───┼───▶│                     │
│  └────────────────────────────────┘  │    │  │ • Face detection   │   │    │  ┌───────────────┐  │
│                                      │    │  │ • Health indicators│   │    │  │ Confidence    │  │
│  ┌────────────────────────────────┐  │    │  └─────────────────────┘   │    │  │ Level         │  │
│  │   Audio Recordings             │──┼───▶│                            │    │  │               │  │
│  │                                │  │    │  ┌─────────────────────┐   │    │  │ 0-100%        │  │
│  │   • Health Statement Audio     │  │    │  │ Audio/Video         │   │    │  └───────────────┘  │
│  │   • Interview Recording        │  │    │  │ Analysis            │   │    │                     │
│  └────────────────────────────────┘  │    │  │                    │   │    │  ┌───────────────┐  │
│                                      │    │  │ • Transcription    │   │    │  │ Explanation   │  │
│  ┌────────────────────────────────┐  │    │  │ • Sentiment        │───┼───▶│  │               │  │
│  │   Video Recordings             │──┼───▶│  │ • Stress detection │   │    │  │ AI-generated  │  │
│  │                                │  │    │  │ • Identity verify  │   │    │  │ reasoning     │  │
│  │   • Video Identity Check       │  │    │  └─────────────────────┘   │    │  │ for decision  │  │
│  │   • Health Assessment Video    │  │    │                            │    │  └───────────────┘  │
│  └────────────────────────────────┘  │    │  ┌─────────────────────┐   │    │                     │
│                                      │    │  │ Historical          │   │    │  ┌───────────────┐  │
│  ┌────────────────────────────────┐  │    │  │ Analysis            │   │    │  │ Full Report   │  │
│  │   Existing Customer Data       │──┼───▶│  │                    │   │    │  │               │  │
│  │   (READ-ONLY - Preserved)      │  │    │  │ • Claims history   │───┼───▶│  │ PDF/JSON      │  │
│  │                                │  │    │  │ • Payment history  │   │    │  │ with all      │  │
│  │   • Transaction History        │  │    │  │ • Policy history   │   │    │  │ details       │  │
│  │   • Investment Accounts        │  │    │  └─────────────────────┘   │    │  └───────────────┘  │
│  │   • Claims History             │  │    │                             │    │                     │
│  │   • Policy History             │  │    └─────────────────────────────┘    └─────────────────────┘
│  └────────────────────────────────┘  │
│                                      │
└──────────────────────────────────────┘
```

---

## 7. Component Diagram - System Integration

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              COMPONENT INTEGRATION                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────────────────────────────┐
    │                           UNDERWRITING BOT SERVICE                                   │
    │                                                                                      │
    │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
    │  │ Photo Analyzer  │  │Medical Analyzer │  │ Doc Analyzer    │  │Audio/Video      │ │
    │  │                 │  │                 │  │                 │  │ Analyzer        │ │
    │  │ • Face detect   │  │ • PDF parse     │  │ • OCR           │  │ • Transcribe    │ │
    │  │ • Quality check │  │ • NLP extract   │  │ • Verify ID     │  │ • Sentiment     │ │
    │  │ • Health hints  │  │ • ICD-10 codes  │  │ • Expiry check  │  │ • Verify voice  │ │
    │  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘ │
    │           │                    │                    │                    │          │
    │           └────────────────────┴────────────────────┴────────────────────┘          │
    │                                         │                                            │
    │                                         ▼                                            │
    │                           ┌─────────────────────────┐                                │
    │                           │   Risk Assessment       │                                │
    │                           │   Engine                │                                │
    │                           │                         │                                │
    │                           │   • Score calculation   │                                │
    │                           │   • Rule evaluation     │                                │
    │                           │   • Decision making     │                                │
    │                           │   • Report generation   │                                │
    │                           └─────────────────────────┘                                │
    │                                         │                                            │
    └─────────────────────────────────────────┼────────────────────────────────────────────┘
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              │                               │                               │
              ▼                               ▼                               ▼
    ┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
    │   PIPELINE SERVICE  │      │  DATA INTEGRITY     │      │    AUDIT SERVICE    │
    │                     │      │    SERVICE          │      │                     │
    │ • Application flow  │      │                     │      │ • Action logging    │
    │ • Status management │      │ • Customer data     │      │ • Decision audit    │
    │ • Approval workflow │      │   protection        │      │ • Access tracking   │
    │                     │      │ • Transaction safe  │      │                     │
    └──────────┬──────────┘      │ • Investment intact │      └──────────┬──────────┘
               │                 │ • Claims preserved  │                 │
               │                 └──────────┬──────────┘                 │
               │                            │                            │
               └────────────────────────────┼────────────────────────────┘
                                            │
                                            ▼
                              ┌─────────────────────────┐
                              │       DATABASE          │
                              │                         │
                              │ ┌───────────────────┐   │
                              │ │ Customers (SAFE)  │   │
                              │ └───────────────────┘   │
                              │ ┌───────────────────┐   │
                              │ │ Policies (SAFE)   │   │
                              │ └───────────────────┘   │
                              │ ┌───────────────────┐   │
                              │ │ Claims (SAFE)     │   │
                              │ └───────────────────┘   │
                              │ ┌───────────────────┐   │
                              │ │ Transactions(SAFE)│   │
                              │ └───────────────────┘   │
                              │ ┌───────────────────┐   │
                              │ │ Investments(SAFE) │   │
                              │ └───────────────────┘   │
                              │ ┌───────────────────┐   │
                              │ │ UW Metadata (NEW) │   │
                              │ └───────────────────┘   │
                              │ ┌───────────────────┐   │
                              │ │ Risk Reports (NEW)│   │
                              │ └───────────────────┘   │
                              └─────────────────────────┘
```

---

## 8. Entity Relationship Diagram - New Tables

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                     NEW DATABASE ENTITIES (Additive - No Existing Data Modified)        │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────┐        ┌──────────────────────────────────────┐
│           UnderwritingMetadata           │        │         RiskAssessmentReport         │
├──────────────────────────────────────────┤        ├──────────────────────────────────────┤
│ PK  id: VARCHAR(50)                      │        │ PK  id: VARCHAR(50)                  │
│     underwriting_id: VARCHAR(50) FK      │───────▶│     underwriting_id: VARCHAR(50) FK  │
│     customer_id: VARCHAR(50) FK          │        │     customer_id: VARCHAR(50) FK      │
│     metadata_type: VARCHAR(50)           │        │     assessment_date: DATETIME        │
│     file_name: VARCHAR(255)              │        │     overall_risk_score: FLOAT        │
│     file_path: VARCHAR(500)              │        │     risk_level: VARCHAR(20)          │
│     file_hash: VARCHAR(64)               │        │     identity_verified: BOOLEAN       │
│     file_size_bytes: INTEGER             │        │     identity_score: FLOAT            │
│     mime_type: VARCHAR(100)              │        │     document_score: FLOAT            │
│     upload_date: DATETIME                │        │     medical_score: FLOAT             │
│     processing_status: VARCHAR(50)       │        │     behavioral_score: FLOAT          │
│     processing_result: TEXT (JSON)       │        │     fraud_score: FLOAT               │
│     extracted_data: TEXT (JSON)          │        │     recommendation: VARCHAR(50)      │
│     validation_status: VARCHAR(50)       │        │     confidence_level: FLOAT          │
│     validation_notes: TEXT               │        │     risk_factors: TEXT (JSON)        │
│     created_date: DATETIME               │        │     explanation: TEXT                │
│     updated_date: DATETIME               │        │     human_override: BOOLEAN          │
└──────────────────────────────────────────┘        │     human_decision: VARCHAR(50)      │
           │                                        │     human_notes: TEXT                │
           │                                        │     created_date: DATETIME           │
           ▼                                        │     updated_date: DATETIME           │
┌──────────────────────────────────────────┐        └──────────────────────────────────────┘
│         MetadataExtractedFeature         │                         │
├──────────────────────────────────────────┤                         │
│ PK  id: VARCHAR(50)                      │                         ▼
│     metadata_id: VARCHAR(50) FK          │        ┌──────────────────────────────────────┐
│     feature_type: VARCHAR(100)           │        │          RiskFactor                  │
│     feature_name: VARCHAR(200)           │        ├──────────────────────────────────────┤
│     feature_value: TEXT                  │        │ PK  id: VARCHAR(50)                  │
│     confidence: FLOAT                    │        │     report_id: VARCHAR(50) FK        │
│     source_location: VARCHAR(100)        │        │     factor_category: VARCHAR(50)     │
│     created_date: DATETIME               │        │     factor_name: VARCHAR(200)        │
└──────────────────────────────────────────┘        │     factor_value: TEXT               │
                                                    │     impact_score: FLOAT              │
                                                    │     impact_direction: VARCHAR(20)    │
                                                    │     source_metadata_id: VARCHAR(50)  │
                                                    │     created_date: DATETIME           │
                                                    └──────────────────────────────────────┘

EXISTING TABLES (READ-ONLY for Risk Assessment - Never Modified):
═══════════════════════════════════════════════════════════════════
│ customers        │ ← Customer details preserved
│ policies         │ ← Policy data preserved
│ claims           │ ← Claims history preserved
│ bills            │ ← Transaction history preserved
│ investment_accts │ ← Investment accounts preserved
│ health_wallets   │ ← Wallet balances preserved
│ audit_logs       │ ← Audit trail preserved
═══════════════════════════════════════════════════════════════════
```

---

## 9. Decision Tree - AI Risk Assessment Logic

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              AI DECISION TREE                                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                                    ┌───────────────────────┐
                                    │   START ASSESSMENT    │
                                    └───────────┬───────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │  Identity Verified?   │
                                    └───────────┬───────────┘
                                                │
                              ┌─────────────────┴─────────────────┐
                              │ NO                                │ YES
                              ▼                                   ▼
                    ┌─────────────────┐              ┌───────────────────────┐
                    │ REFER TO MANUAL │              │  Documents Valid?     │
                    │ (ID Failure)    │              └───────────┬───────────┘
                    └─────────────────┘                          │
                                                   ┌─────────────┴─────────────┐
                                                   │ NO                        │ YES
                                                   ▼                           ▼
                                      ┌─────────────────┐       ┌───────────────────────┐
                                      │ REFER TO MANUAL │       │  Medical Risk Level?  │
                                      │ (Doc Failure)   │       └───────────┬───────────┘
                                      └─────────────────┘                   │
                                                          ┌─────────────────┴─────────────┬───────────────┐
                                                          │ HIGH (>0.7)                   │ MED (0.3-0.7) │ LOW (<0.3)
                                                          ▼                               ▼               ▼
                                            ┌─────────────────┐       ┌───────────────────────┐  ┌──────────────┐
                                            │  Pre-existing   │       │  Overall Risk Score?  │  │  Age Check   │
                                            │  Conditions?    │       └───────────┬───────────┘  └──────┬───────┘
                                            └─────────┬───────┘                   │                     │
                                                      │                   ┌───────┴───────┐            │
                                     ┌────────────────┴────────────┐     │               │   ┌────────┴────────┐
                                     │ YES                         │ NO  │ >0.6    ≤0.6  │   │>65yrs     ≤65yrs│
                                     ▼                             ▼     ▼               ▼   ▼                 ▼
                           ┌─────────────────┐          ┌─────────────┐  │   ┌───────────────────┐  ┌─────────────┐
                           │ CONDITIONAL     │          │ REFER WITH  │  │   │    CONDITIONAL    │  │   APPROVE   │
                           │ APPROVAL        │          │ EXCLUSIONS  │  │   │    APPROVAL       │  │   (Auto)    │
                           │ (Exclusions)    │          │             │  │   └───────────────────┘  └─────────────┘
                           └─────────────────┘          └─────────────┘  │
                                                                         ▼
                                                                ┌─────────────────┐
                                                                │ Fraud Score?    │
                                                                └─────────┬───────┘
                                                                          │
                                                        ┌─────────────────┴─────────────────┐
                                                        │ HIGH (>0.5)                       │ LOW (≤0.5)
                                                        ▼                                   ▼
                                              ┌─────────────────┐              ┌───────────────────┐
                                              │ REFER TO MANUAL │              │ Claims History?   │
                                              │ (Fraud Alert)   │              └─────────┬─────────┘
                                              └─────────────────┘                        │
                                                                          ┌──────────────┴──────────────┐
                                                                          │ MANY (>3)                   │ FEW (≤3)
                                                                          ▼                             ▼
                                                              ┌─────────────────┐          ┌───────────────────┐
                                                              │ CONDITIONAL     │          │     APPROVE       │
                                                              │ (Premium Adj)   │          │     (Standard)    │
                                                              └─────────────────┘          └───────────────────┘
```

---

## 10. Data Integrity Protection

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          DATA INTEGRITY PROTECTION RULES                                 │
└─────────────────────────────────────────────────────────────────────────────────────────┘

╔═══════════════════════════════════════════════════════════════════════════════════════╗
║                            PROTECTED DATA (NEVER MODIFIED)                             ║
╠═══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                         ║
║  1. CUSTOMER MASTER DATA                                                                ║
║     ├── id, name, email, phone, dob, age, address                                       ║
║     ├── created_date (original registration)                                            ║
║     └── password_hash, portal_active (auth data)                                        ║
║                                                                                         ║
║  2. TRANSACTION HISTORY                                                                 ║
║     ├── All payment records                                                             ║
║     ├── Premium payments                                                                ║
║     ├── Claim payments                                                                  ║
║     └── Investment transactions                                                         ║
║                                                                                         ║
║  3. INVESTMENT ACCOUNTS                                                                 ║
║     ├── balance, index_balance, bonds_balance, crypto_balance                           ║
║     ├── deposits history                                                                ║
║     └── allocation history                                                              ║
║                                                                                         ║
║  4. CLAIMS HISTORY                                                                      ║
║     ├── All filed claims                                                                ║
║     ├── Claim statuses                                                                  ║
║     ├── Approved/rejected amounts                                                       ║
║     └── Claim documents                                                                 ║
║                                                                                         ║
║  5. HEALTH WALLETS                                                                      ║
║     ├── Wallet balances                                                                 ║
║     ├── Transaction history                                                             ║
║     └── Monthly deposits                                                                ║
║                                                                                         ║
║  6. EXISTING POLICIES                                                                   ║
║     ├── Active policy details                                                           ║
║     ├── Premium history                                                                 ║
║     └── Coverage details                                                                ║
║                                                                                         ║
╚═══════════════════════════════════════════════════════════════════════════════════════╝

╔═══════════════════════════════════════════════════════════════════════════════════════╗
║                              ADDITIVE-ONLY CHANGES                                     ║
╠═══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                         ║
║  The Underwriting Bot will ONLY:                                                        ║
║                                                                                         ║
║  ✓ ADD new underwriting metadata records                                                ║
║  ✓ ADD new risk assessment reports                                                      ║
║  ✓ ADD new risk factor records                                                          ║
║  ✓ ADD new audit log entries                                                            ║
║  ✓ UPDATE underwriting application status (pending → approved/rejected)                 ║
║  ✓ UPDATE policy status (pending_underwriting → active/rejected)                        ║
║                                                                                         ║
║  The Bot will NEVER:                                                                    ║
║                                                                                         ║
║  ✗ DELETE any customer data                                                             ║
║  ✗ MODIFY transaction history                                                           ║
║  ✗ RESET investment account balances                                                    ║
║  ✗ ALTER claims history                                                                 ║
║  ✗ CHANGE wallet balances                                                               ║
║  ✗ MODIFY existing policy premiums (unless explicit approval)                           ║
║                                                                                         ║
╚═══════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Summary

This UML documentation defines a comprehensive Underwriting Bot system that:

1. **Processes Multiple Metadata Types**: Photos, medical reports, official documents (passport, driving licence, national insurance, disability certificates), audio recordings, and video recordings.

2. **Creates Full Risk Assessment Reports**: Generates comprehensive reports with risk scores, factors, recommendations, and AI-generated explanations.

3. **Supports AI-Based Decisions**: Implements decision trees for auto-approval, conditional approval, referral, or rejection.

4. **Maintains Data Integrity**: All existing customer data, transactions, investment accounts, claims, and wallet balances are protected and never modified.

5. **Integrates with Existing Pipeline**: Works within the existing application → underwriting → policy activation flow.

6. **Provides Audit Trail**: Every action is logged for compliance and review.

---

**Next Step**: With this UML approved, we will proceed to implement the underwriting bot service.
