# Sully Chain - Supplier Management & Allocation System
## Comprehensive Architecture Document

---

## Executive Summary

**Sully Chain** is an advanced, allocation-based supplier management ecosystem designed to integrate seamlessly with the PHINS Insurance Platform. It provides a unified dashboard for managing diverse supplier types, handling service requests through competitive bidding, and maintaining an immutable ledger of all transactions and interactions.

### Key Capabilities
- **Multi-Type Supplier Registry**: Lawyers, doctors, medical service providers, reinsurance companies, banks, trading companies, delivery services, transportation providers, pharmacies
- **Allocation-Based Bidding**: Service requests generate allocation opportunities where registered suppliers submit fixed-price bids
- **Immutable Ledger**: Complete audit trail of every action, client interaction, and specialization
- **AI/BI Analytics**: Real-time insights, supplier performance scoring, fraud detection, and predictive analytics
- **NFT-Based Transaction Integrity**: Blockchain-verified transaction records for provenance and compliance

---

## 1. Database Schema (Entity Relationship Diagram)

```mermaid
erDiagram
    %% Core Supplier Entities
    SUPPLIER {
        uuid id PK
        string supplier_code UK
        string name
        string supplier_type
        string registration_number
        text address
        string phone
        string email UK
        string status
        json credentials
        json certifications
        float rating
        int total_allocations
        decimal wallet_balance
        datetime registered_at
        datetime last_active_at
    }
    
    SUPPLIER_TYPE {
        uuid id PK
        string code UK
        string name
        string category
        text description
        json required_credentials
        json service_categories
        boolean is_active
    }
    
    SUPPLIER_SPECIALTY {
        uuid id PK
        uuid supplier_id FK
        string specialty_code
        string specialty_name
        string certification_level
        date certified_until
        boolean is_primary
    }
    
    SUPPLIER_CREDENTIAL {
        uuid id PK
        uuid supplier_id FK
        string credential_type
        string credential_number
        string issuing_authority
        date issued_date
        date expiry_date
        string verification_status
        text document_url
    }
    
    %% Allocation & Bidding Entities
    SERVICE_REQUEST {
        uuid id PK
        string request_code UK
        uuid customer_id FK
        uuid policy_id FK
        string service_type
        string urgency_level
        text description
        json requirements
        decimal estimated_value
        string status
        datetime request_date
        datetime deadline
        uuid assigned_supplier_id FK
    }
    
    ALLOCATION {
        uuid id PK
        string allocation_code UK
        uuid service_request_id FK
        string allocation_type
        string status
        datetime opened_at
        datetime closes_at
        decimal reserve_price
        json eligible_criteria
        int bid_count
        uuid winning_bid_id FK
    }
    
    BID {
        uuid id PK
        string bid_code UK
        uuid allocation_id FK
        uuid supplier_id FK
        decimal bid_amount
        text proposal
        json deliverables
        int estimated_days
        string status
        datetime submitted_at
        float supplier_rating_at_bid
    }
    
    %% Service Fulfillment
    SERVICE_FULFILLMENT {
        uuid id PK
        uuid allocation_id FK
        uuid supplier_id FK
        uuid customer_id FK
        string status
        datetime started_at
        datetime completed_at
        json deliverables_submitted
        text notes
        decimal final_amount
    }
    
    SERVICE_MILESTONE {
        uuid id PK
        uuid fulfillment_id FK
        string milestone_name
        int sequence_order
        string status
        datetime due_date
        datetime completed_date
        decimal milestone_amount
    }
    
    %% Ledger & Audit
    SULLY_LEDGER {
        uuid id PK
        string ledger_code UK
        string entity_type
        uuid entity_id
        string action_type
        uuid actor_id
        string actor_type
        json previous_state
        json new_state
        json metadata
        string hash
        string previous_hash
        datetime timestamp
        string nft_token_id
    }
    
    CLIENT_INTERACTION {
        uuid id PK
        uuid customer_id FK
        uuid supplier_id FK
        uuid service_request_id FK
        string interaction_type
        text summary
        json details
        int satisfaction_score
        datetime interaction_date
    }
    
    %% Financial
    SUPPLIER_TRANSACTION {
        uuid id PK
        uuid supplier_id FK
        uuid allocation_id FK
        string transaction_type
        decimal amount
        string currency
        string status
        string payment_method
        string reference_number
        datetime transaction_date
    }
    
    ESCROW_ACCOUNT {
        uuid id PK
        uuid allocation_id FK
        decimal held_amount
        string status
        datetime created_at
        datetime released_at
    }
    
    %% AI/BI Analytics
    SUPPLIER_SCORE {
        uuid id PK
        uuid supplier_id FK
        float performance_score
        float reliability_score
        float quality_score
        float price_competitiveness
        float response_time_score
        float overall_score
        json score_breakdown
        datetime calculated_at
    }
    
    ALLOCATION_ANALYTICS {
        uuid id PK
        uuid allocation_id FK
        int total_views
        int total_bids
        decimal avg_bid_amount
        decimal winning_bid_amount
        float price_efficiency
        int time_to_award_hours
        json supplier_demographics
    }
    
    %% Relationships
    SUPPLIER ||--o{ SUPPLIER_SPECIALTY : has
    SUPPLIER ||--o{ SUPPLIER_CREDENTIAL : holds
    SUPPLIER ||--o{ BID : submits
    SUPPLIER ||--o{ SERVICE_FULFILLMENT : performs
    SUPPLIER ||--o{ CLIENT_INTERACTION : participates
    SUPPLIER ||--o{ SUPPLIER_TRANSACTION : has
    SUPPLIER ||--|| SUPPLIER_SCORE : rated_by
    SUPPLIER }o--|| SUPPLIER_TYPE : categorized_as
    
    SERVICE_REQUEST ||--o| ALLOCATION : generates
    SERVICE_REQUEST ||--o{ CLIENT_INTERACTION : has
    
    ALLOCATION ||--o{ BID : receives
    ALLOCATION ||--|| ESCROW_ACCOUNT : secured_by
    ALLOCATION ||--|| SERVICE_FULFILLMENT : results_in
    ALLOCATION ||--|| ALLOCATION_ANALYTICS : analyzed_by
    
    BID }o--|| SUPPLIER : submitted_by
    BID }o--|| ALLOCATION : for
    
    SERVICE_FULFILLMENT ||--o{ SERVICE_MILESTONE : contains
    
    SULLY_LEDGER }o--|| SUPPLIER : tracks
    SULLY_LEDGER }o--|| ALLOCATION : tracks
    SULLY_LEDGER }o--|| BID : tracks
```

---

## 2. Supplier Type Hierarchy

```mermaid
classDiagram
    class SupplierBase {
        <<abstract>>
        +uuid id
        +string name
        +string status
        +float rating
        +register()
        +updateProfile()
        +submitBid()
        +fulfillService()
    }
    
    class LegalSupplier {
        +string bar_association_number
        +list~string~ practice_areas
        +validateBarLicense()
        +handleLegalConsultation()
    }
    
    class MedicalSupplier {
        +string medical_license
        +string hospital_affiliation
        +list~string~ specializations
        +validateMedicalCredentials()
        +handleMedicalService()
    }
    
    class DoctorSupplier {
        +string doctor_registration
        +string specialty
        +string hospital
        +scheduleAppointment()
        +provideDiagnosis()
    }
    
    class PharmacySupplier {
        +string pharmacy_license
        +bool is_24hour
        +list~string~ available_medications
        +checkDrugAvailability()
        +fulfillPrescription()
    }
    
    class ReinsuranceSupplier {
        +string reinsurance_license
        +float capacity
        +list~string~ risk_categories
        +evaluateRisk()
        +provideQuote()
    }
    
    class BankingSupplier {
        +string banking_license
        +list~string~ services
        +processPayment()
        +verifyAccount()
    }
    
    class TradingSupplier {
        +string trading_license
        +list~string~ commodities
        +executeTrade()
        +provideMarketData()
    }
    
    class DeliverySupplier {
        +string fleet_size
        +list~string~ coverage_areas
        +bool express_available
        +calculateDeliveryTime()
        +trackShipment()
    }
    
    class TransportSupplier {
        +string transport_license
        +list~string~ vehicle_types
        +int capacity
        +scheduleTransport()
        +trackVehicle()
    }
    
    class MedicalEquipmentSupplier {
        +list~string~ equipment_categories
        +bool maintenance_included
        +provideEquipment()
        +scheduleMaintenance()
    }
    
    SupplierBase <|-- LegalSupplier
    SupplierBase <|-- MedicalSupplier
    SupplierBase <|-- ReinsuranceSupplier
    SupplierBase <|-- BankingSupplier
    SupplierBase <|-- TradingSupplier
    SupplierBase <|-- DeliverySupplier
    SupplierBase <|-- TransportSupplier
    
    MedicalSupplier <|-- DoctorSupplier
    MedicalSupplier <|-- PharmacySupplier
    MedicalSupplier <|-- MedicalEquipmentSupplier
```

---

## 3. System Architecture (Component Diagram)

```mermaid
flowchart TB
    subgraph Presentation["Presentation Layer"]
        direction TB
        SD[Sully Chain Dashboard]
        SP[Supplier Portal]
        CP[Customer Portal]
        AP[Admin Panel]
        MA[Mobile App API]
    end
    
    subgraph Application["Application Layer - Service Mesh"]
        direction TB
        
        subgraph CoreServices["Core Services"]
            SMS[Supplier Management Service]
            ALS[Allocation Service]
            BDS[Bidding Service]
            FFS[Fulfillment Service]
        end
        
        subgraph FinancialServices["Financial Services"]
            ESS[Escrow Service]
            PGS[Payment Gateway Service]
            TXS[Transaction Service]
        end
        
        subgraph LedgerServices["Ledger & Audit"]
            SLS[Sully Ledger Service]
            AUS[Audit Service]
            NTS[NFT Token Service]
        end
        
        subgraph AIServices["AI/BI Services"]
            PSS[Performance Scoring Service]
            FDS[Fraud Detection Service]
            AAS[Allocation Analytics Service]
            RES[Recommendation Engine]
            PRS[Price Prediction Service]
        end
        
        subgraph IntegrationServices["Integration Services"]
            PHI[PHINS Integration Service]
            EXS[External API Service]
            NOS[Notification Service]
        end
    end
    
    subgraph Data["Data Layer"]
        direction TB
        PDB[(PostgreSQL<br/>Primary DB)]
        RDS[(Redis<br/>Cache)]
        MDB[(MongoDB<br/>Analytics)]
        ES[(Elasticsearch<br/>Search)]
        BLK[(Blockchain<br/>Ledger)]
    end
    
    subgraph External["External Systems"]
        PHINS[PHINS Platform]
        BANK[Banking APIs]
        GOV[Government Verification]
        NFT[NFT Marketplace]
    end
    
    %% Connections
    SD --> CoreServices
    SP --> CoreServices
    CP --> ALS
    AP --> CoreServices
    MA --> CoreServices
    
    CoreServices --> FinancialServices
    CoreServices --> LedgerServices
    CoreServices --> AIServices
    
    LedgerServices --> BLK
    FinancialServices --> PGS
    
    AIServices --> MDB
    CoreServices --> PDB
    CoreServices --> RDS
    IntegrationServices --> ES
    
    PHI --> PHINS
    PGS --> BANK
    SMS --> GOV
    NTS --> NFT
```

---

## 4. Allocation Workflow (Sequence Diagram)

```mermaid
sequenceDiagram
    autonumber
    participant C as Customer
    participant SR as Service Request
    participant AL as Allocation Service
    participant LD as Ledger Service
    participant NS as Notification Service
    participant S1 as Supplier 1
    participant S2 as Supplier 2
    participant BD as Bidding Service
    participant AI as AI Scoring
    participant ES as Escrow Service
    participant FF as Fulfillment Service
    
    C->>SR: Submit Service Request
    SR->>LD: Log Request Creation
    LD-->>SR: Ledger Entry Created
    
    SR->>AL: Create Allocation
    AL->>AL: Determine Eligible Suppliers
    AL->>LD: Log Allocation Created
    
    AL->>NS: Notify Eligible Suppliers
    NS-->>S1: Allocation Available
    NS-->>S2: Allocation Available
    
    par Supplier Bidding
        S1->>BD: Submit Bid
        BD->>AI: Validate & Score Bid
        AI-->>BD: Bid Score
        BD->>LD: Log Bid Submission
        BD-->>S1: Bid Confirmed
    and
        S2->>BD: Submit Bid
        BD->>AI: Validate & Score Bid
        AI-->>BD: Bid Score
        BD->>LD: Log Bid Submission
        BD-->>S2: Bid Confirmed
    end
    
    Note over AL: Allocation Closes
    
    AL->>AI: Evaluate All Bids
    AI->>AI: Apply Scoring Algorithm
    AI-->>AL: Ranked Bids with Scores
    
    AL->>AL: Select Winning Bid
    AL->>LD: Log Winner Selection
    
    AL->>ES: Create Escrow Hold
    ES->>C: Request Payment Authorization
    C-->>ES: Payment Authorized
    ES->>LD: Log Escrow Created
    
    AL->>NS: Notify All Bidders
    NS-->>S1: You Won!
    NS-->>S2: Bid Not Selected
    
    AL->>FF: Initialize Fulfillment
    FF->>LD: Log Fulfillment Started
    
    S1->>FF: Complete Service
    FF->>AI: Evaluate Fulfillment Quality
    AI-->>FF: Quality Score
    
    FF->>C: Request Confirmation
    C-->>FF: Service Confirmed
    
    FF->>ES: Release Escrow
    ES->>S1: Payment Released
    ES->>LD: Log Payment Released
    
    FF->>AI: Update Supplier Rating
    AI->>LD: Log Rating Update
```

---

## 5. Ledger System Architecture

```mermaid
flowchart TB
    subgraph Events["Event Sources"]
        E1[Supplier Registration]
        E2[Allocation Created]
        E3[Bid Submitted]
        E4[Winner Selected]
        E5[Service Completed]
        E6[Payment Processed]
        E7[Rating Updated]
    end
    
    subgraph LedgerCore["Sully Ledger Core"]
        direction TB
        EQ[Event Queue]
        LP[Ledger Processor]
        HG[Hash Generator]
        VS[Validation Service]
        
        EQ --> LP
        LP --> HG
        LP --> VS
    end
    
    subgraph Storage["Ledger Storage"]
        direction LR
        PLS[(PostgreSQL<br/>Ledger Table)]
        BCS[(Blockchain<br/>Anchoring)]
        NRS[(NFT Registry)]
    end
    
    subgraph Verification["Verification Layer"]
        IV[Integrity Validator]
        AR[Audit Reporter]
        CB[Compliance Bot]
    end
    
    Events --> EQ
    
    HG --> PLS
    HG --> BCS
    VS --> NRS
    
    PLS --> IV
    BCS --> IV
    NRS --> IV
    
    IV --> AR
    IV --> CB
    
    subgraph LedgerEntry["Ledger Entry Structure"]
        LE["
        {
          ledger_code: 'SL-2024-000001',
          entity_type: 'ALLOCATION',
          entity_id: 'uuid',
          action_type: 'BID_SUBMITTED',
          actor_id: 'supplier_uuid',
          actor_type: 'SUPPLIER',
          previous_state: {...},
          new_state: {...},
          metadata: {
            ip_address: '...',
            user_agent: '...',
            geo_location: '...'
          },
          hash: 'sha256_hash',
          previous_hash: 'prev_sha256',
          timestamp: 'ISO8601',
          nft_token_id: 'NFT-xxx'
        }
        "]
    end
```

---

## 6. AI/BI Analytics Engine

```mermaid
flowchart TB
    subgraph DataSources["Data Sources"]
        SLD[(Sully Ledger)]
        SPD[(Supplier Data)]
        ALD[(Allocation Data)]
        TXD[(Transaction Data)]
        CID[(Client Interactions)]
    end
    
    subgraph ETL["ETL Pipeline"]
        DC[Data Collector]
        DT[Data Transformer]
        DL[Data Loader]
        
        DC --> DT --> DL
    end
    
    subgraph AnalyticsEngine["AI/BI Analytics Engine"]
        direction TB
        
        subgraph ML["Machine Learning Models"]
            PSM[Performance Scoring Model]
            FDM[Fraud Detection Model]
            PPM[Price Prediction Model]
            SRM[Supplier Recommendation Model]
            RTM[Risk Assessment Model]
        end
        
        subgraph BI["Business Intelligence"]
            DW[(Data Warehouse)]
            OLAP[OLAP Cube]
            RPT[Report Generator]
        end
        
        subgraph RealTime["Real-Time Analytics"]
            CEP[Complex Event Processing]
            ASM[Alert State Machine]
            DSH[Live Dashboard]
        end
    end
    
    subgraph Outputs["Analytics Outputs"]
        SCS[Supplier Scores]
        FRA[Fraud Alerts]
        PPR[Price Predictions]
        SPR[Supplier Recommendations]
        RRA[Risk Reports]
        DBD[Dashboards]
        NTF[Notifications]
    end
    
    DataSources --> ETL
    ETL --> AnalyticsEngine
    
    ML --> SCS
    ML --> FRA
    ML --> PPR
    ML --> SPR
    ML --> RRA
    
    BI --> DBD
    BI --> RPT
    
    RealTime --> DSH
    RealTime --> NTF
```

### AI Scoring Algorithm

```mermaid
flowchart LR
    subgraph Inputs["Scoring Inputs"]
        I1[Completion Rate]
        I2[Average Rating]
        I3[Response Time]
        I4[Price Competitiveness]
        I5[Dispute Rate]
        I6[Credential Status]
        I7[Years Active]
        I8[Total Allocations]
    end
    
    subgraph Weights["Dynamic Weights"]
        W1["Completion: 0.20"]
        W2["Rating: 0.25"]
        W3["Response: 0.15"]
        W4["Price: 0.15"]
        W5["Disputes: 0.10"]
        W6["Credentials: 0.05"]
        W7["Experience: 0.05"]
        W8["Volume: 0.05"]
    end
    
    subgraph Calculation["Score Calculation"]
        AGG[Weighted Aggregation]
        NRM[Normalization 0-100]
        ADJ[Recency Adjustment]
    end
    
    subgraph Output["Final Score"]
        FS["Overall Score<br/>Performance Tier<br/>Trend Indicator"]
    end
    
    Inputs --> Weights
    Weights --> Calculation
    Calculation --> Output
```

---

## 7. Service Layer Class Diagram

```mermaid
classDiagram
    class SullyChainService {
        <<interface>>
        +initialize()
        +shutdown()
        +health_check() HealthStatus
    }
    
    class SupplierManagementService {
        -supplier_repo: SupplierRepository
        -credential_validator: CredentialValidator
        -ledger: LedgerService
        +register_supplier(data: SupplierData) Supplier
        +update_supplier(id: uuid, data: SupplierData) Supplier
        +verify_credentials(supplier_id: uuid) VerificationResult
        +get_supplier_profile(id: uuid) SupplierProfile
        +search_suppliers(criteria: SearchCriteria) List~Supplier~
        +deactivate_supplier(id: uuid) bool
    }
    
    class AllocationService {
        -allocation_repo: AllocationRepository
        -supplier_matcher: SupplierMatcher
        -ledger: LedgerService
        +create_allocation(request: ServiceRequest) Allocation
        +get_eligible_suppliers(allocation_id: uuid) List~Supplier~
        +close_allocation(id: uuid) AllocationResult
        +cancel_allocation(id: uuid, reason: str) bool
        +get_allocation_status(id: uuid) AllocationStatus
    }
    
    class BiddingService {
        -bid_repo: BidRepository
        -validator: BidValidator
        -scorer: AIScorer
        -ledger: LedgerService
        +submit_bid(allocation_id: uuid, supplier_id: uuid, data: BidData) Bid
        +withdraw_bid(bid_id: uuid) bool
        +get_bids_for_allocation(allocation_id: uuid) List~Bid~
        +evaluate_bids(allocation_id: uuid) RankedBids
        +select_winner(allocation_id: uuid, bid_id: uuid) Bid
    }
    
    class FulfillmentService {
        -fulfillment_repo: FulfillmentRepository
        -milestone_tracker: MilestoneTracker
        -quality_assessor: QualityAssessor
        -ledger: LedgerService
        +start_fulfillment(allocation_id: uuid) Fulfillment
        +update_milestone(fulfillment_id: uuid, milestone_id: uuid, status: str) Milestone
        +submit_deliverables(fulfillment_id: uuid, deliverables: List) bool
        +complete_fulfillment(fulfillment_id: uuid) FulfillmentResult
        +dispute_fulfillment(fulfillment_id: uuid, reason: str) Dispute
    }
    
    class LedgerService {
        -ledger_repo: LedgerRepository
        -hash_generator: HashGenerator
        -nft_service: NFTService
        +log_event(event: LedgerEvent) LedgerEntry
        +get_history(entity_type: str, entity_id: uuid) List~LedgerEntry~
        +verify_integrity(from_date: datetime, to_date: datetime) IntegrityReport
        +export_audit_trail(criteria: AuditCriteria) AuditReport
        +anchor_to_blockchain(entry_id: uuid) BlockchainReceipt
    }
    
    class EscrowService {
        -escrow_repo: EscrowRepository
        -payment_gateway: PaymentGateway
        -ledger: LedgerService
        +create_escrow(allocation_id: uuid, amount: Decimal) Escrow
        +hold_funds(escrow_id: uuid) HoldResult
        +release_funds(escrow_id: uuid, recipient_id: uuid) ReleaseResult
        +refund_escrow(escrow_id: uuid) RefundResult
        +get_escrow_status(escrow_id: uuid) EscrowStatus
    }
    
    class SupplierScoringService {
        -score_repo: ScoreRepository
        -ml_model: PerformanceModel
        -ledger: LedgerService
        +calculate_score(supplier_id: uuid) SupplierScore
        +get_score_history(supplier_id: uuid) List~SupplierScore~
        +get_top_suppliers(category: str, limit: int) List~RankedSupplier~
        +recalculate_all_scores() BatchResult
    }
    
    class FraudDetectionService {
        -fraud_model: FraudModel
        -alert_service: AlertService
        -ledger: LedgerService
        +analyze_bid(bid: Bid) FraudScore
        +analyze_supplier_pattern(supplier_id: uuid) RiskAssessment
        +detect_collusion(allocation_id: uuid) CollusionReport
        +flag_suspicious_activity(entity_type: str, entity_id: uuid, reason: str) Alert
    }
    
    class RecommendationService {
        -rec_model: RecommendationModel
        -supplier_service: SupplierManagementService
        +recommend_suppliers(request: ServiceRequest) List~RecommendedSupplier~
        +predict_bid_range(allocation_id: uuid) PriceRange
        +suggest_optimal_deadline(request: ServiceRequest) datetime
    }
    
    SullyChainService <|.. SupplierManagementService
    SullyChainService <|.. AllocationService
    SullyChainService <|.. BiddingService
    SullyChainService <|.. FulfillmentService
    SullyChainService <|.. LedgerService
    SullyChainService <|.. EscrowService
    SullyChainService <|.. SupplierScoringService
    SullyChainService <|.. FraudDetectionService
    SullyChainService <|.. RecommendationService
    
    SupplierManagementService --> LedgerService
    AllocationService --> LedgerService
    BiddingService --> LedgerService
    FulfillmentService --> LedgerService
    EscrowService --> LedgerService
    SupplierScoringService --> LedgerService
    FraudDetectionService --> LedgerService
```

---

## 8. Integration with PHINS Platform

```mermaid
flowchart TB
    subgraph PHINS["PHINS Insurance Platform"]
        PC[Policy Service]
        CC[Claims Service]
        US[Underwriting Service]
        CS[Customer Service]
        PS[Payment Service]
    end
    
    subgraph Integration["Integration Layer"]
        direction TB
        EH[Event Hub]
        API[REST API Gateway]
        SYNC[Data Synchronizer]
    end
    
    subgraph SullyChain["Sully Chain"]
        SMS[Supplier Management]
        ALS[Allocation Service]
        LDS[Ledger Service]
        AIS[AI Analytics]
    end
    
    %% PHINS to Sully Chain
    PC -->|Policy Requires Service| EH
    CC -->|Claim Needs Provider| EH
    US -->|Underwriting Review| EH
    
    EH --> ALS
    
    %% Sully Chain to PHINS
    SMS -->|Supplier Verified| SYNC
    ALS -->|Allocation Complete| SYNC
    
    SYNC --> CS
    SYNC --> PS
    
    %% Bidirectional API
    API <--> PC
    API <--> CC
    API <--> SMS
    API <--> ALS
    
    %% Shared Ledger
    LDS <-->|Unified Audit| PHINS
```

### Integration Events

| Event | Source | Target | Description |
|-------|--------|--------|-------------|
| `POLICY_SERVICE_REQUIRED` | PHINS Policy Service | Sully Allocation | Policy requires external service (medical exam, legal review) |
| `CLAIM_PROVIDER_NEEDED` | PHINS Claims Service | Sully Allocation | Claim requires provider (doctor, repair service) |
| `SUPPLIER_ASSIGNED` | Sully Allocation | PHINS Services | Supplier has been allocated to request |
| `SERVICE_COMPLETED` | Sully Fulfillment | PHINS Services | Supplier completed the service |
| `PAYMENT_PROCESSED` | Sully Escrow | PHINS Payment | Payment released to supplier |

---

## 9. Security Architecture

```mermaid
flowchart TB
    subgraph Authentication["Authentication Layer"]
        JWT[JWT Token Service]
        MFA[Multi-Factor Auth]
        SSO[SSO Integration]
    end
    
    subgraph Authorization["Authorization Layer"]
        RBAC[Role-Based Access Control]
        ABAC[Attribute-Based Access]
        POL[Policy Engine]
    end
    
    subgraph DataSecurity["Data Security"]
        ENC[Encryption at Rest]
        TLS[TLS 1.3 in Transit]
        HSM[Hardware Security Module]
        MASK[Data Masking]
    end
    
    subgraph AuditSecurity["Audit & Compliance"]
        LOG[Security Logging]
        SIEM[SIEM Integration]
        COMP[Compliance Checks]
    end
    
    subgraph Roles["System Roles"]
        R1[Platform Admin]
        R2[Supplier Admin]
        R3[Supplier User]
        R4[Customer]
        R5[Auditor]
        R6[AI System]
    end
    
    Roles --> Authentication
    Authentication --> Authorization
    Authorization --> DataSecurity
    DataSecurity --> AuditSecurity
```

### Role Permissions Matrix

| Permission | Platform Admin | Supplier Admin | Supplier User | Customer | Auditor |
|------------|----------------|----------------|---------------|----------|---------|
| Manage Suppliers | ✓ | Own Only | - | - | View |
| Create Allocations | ✓ | - | - | ✓ | - |
| Submit Bids | - | ✓ | ✓ | - | - |
| View All Bids | ✓ | - | Own Only | Own Allocations | ✓ |
| Select Winners | ✓ | - | - | ✓ | - |
| Access Ledger | ✓ | Own Only | Own Only | Own Only | ✓ |
| View Analytics | ✓ | Own Only | - | - | ✓ |
| Manage Escrow | ✓ | - | - | - | View |

---

## 10. Dashboard Wireframe

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SULLY CHAIN - Supplier Management Dashboard                    👤 Admin ▼  │
├─────────────────────────────────────────────────────────────────────────────┤
│  📊 Overview │ 🏢 Suppliers │ 📋 Allocations │ 💰 Transactions │ 📈 Analytics │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌────────────┐│
│  │ Active Suppliers│ │ Open Allocations│ │  Pending Bids   │ │ Escrow Held││
│  │      247       │ │       34        │ │       156       │ │  $2.4M     ││
│  │   ▲ 12% MTD    │ │   ▼ 5% MTD     │ │   ▲ 23% MTD    │ │  ▲ 8% MTD  ││
│  └─────────────────┘ └─────────────────┘ └─────────────────┘ └────────────┘│
│                                                                             │
│  ┌─────────────────────────────────────┐ ┌─────────────────────────────────┐│
│  │ Recent Allocations                  │ │ Top Suppliers by Score          ││
│  │ ─────────────────────────────────── │ │ ─────────────────────────────── ││
│  │ AL-2024-0892 Medical Exam    🟢 Open│ │ 1. HealthFirst Medical    98.5  ││
│  │ AL-2024-0891 Legal Review    🟡 Bid │ │ 2. Swift Delivery Co      97.2  ││
│  │ AL-2024-0890 Equipment       🔵 Won │ │ 3. LegalEase Partners     96.8  ││
│  │ AL-2024-0889 Transport       🟢 Open│ │ 4. MedEquip Solutions     95.4  ││
│  │ AL-2024-0888 Pharmacy        ✅ Done│ │ 5. SecureBank Financial   94.1  ││
│  └─────────────────────────────────────┘ └─────────────────────────────────┘│
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │ Allocation Trends (Last 30 Days)                                        ││
│  │  ^                                                                      ││
│  │  │     ╭──╮                                      ╭───╮                  ││
│  │  │    ╱    ╲    ╭──────╮                       ╱     ╲                 ││
│  │  │───╱      ╲──╱        ╲─────────────────────╱       ╲────           ││
│  │  │                                                                      ││
│  │  └──────────────────────────────────────────────────────────────────▶  ││
│  │    Week 1      Week 2      Week 3      Week 4                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│  ┌─────────────────────────────────────┐ ┌─────────────────────────────────┐│
│  │ Supplier Distribution by Type       │ │ Recent Ledger Activity          ││
│  │                                     │ │ ─────────────────────────────── ││
│  │      Medical 28%  ████████          │ │ 10:45 BID_SUBMITTED  AL-0892    ││
│  │        Legal 18%  █████             │ │ 10:42 SUPPLIER_REG   SP-1247    ││
│  │     Delivery 15%  ████              │ │ 10:38 ESCROW_CREATED AL-0891    ││
│  │      Banking 12%  ███               │ │ 10:35 WINNER_SELECT  AL-0889    ││
│  │        Other 27%  ███████           │ │ 10:30 SERVICE_DONE   AL-0885    ││
│  └─────────────────────────────────────┘ └─────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. API Specification Summary

### Supplier Management APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/suppliers` | POST | Register new supplier |
| `/api/v1/suppliers/{id}` | GET | Get supplier profile |
| `/api/v1/suppliers/{id}` | PUT | Update supplier |
| `/api/v1/suppliers/{id}/credentials` | POST | Add credential |
| `/api/v1/suppliers/{id}/verify` | POST | Trigger verification |
| `/api/v1/suppliers/search` | POST | Search suppliers |

### Allocation APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/allocations` | POST | Create allocation |
| `/api/v1/allocations/{id}` | GET | Get allocation details |
| `/api/v1/allocations/{id}/bids` | GET | List bids |
| `/api/v1/allocations/{id}/bids` | POST | Submit bid |
| `/api/v1/allocations/{id}/winner` | POST | Select winner |
| `/api/v1/allocations/{id}/close` | POST | Close allocation |

### Ledger APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/ledger/entries` | GET | Query ledger entries |
| `/api/v1/ledger/entities/{type}/{id}` | GET | Get entity history |
| `/api/v1/ledger/audit-report` | POST | Generate audit report |
| `/api/v1/ledger/verify-integrity` | POST | Verify chain integrity |

---

## 12. Deployment Architecture

```mermaid
flowchart TB
    subgraph Cloud["Cloud Infrastructure (AWS/Railway)"]
        subgraph LB["Load Balancer"]
            ALB[Application Load Balancer]
        end
        
        subgraph Compute["Compute Layer"]
            subgraph K8s["Kubernetes Cluster"]
                API1[API Pod 1]
                API2[API Pod 2]
                API3[API Pod 3]
                WRK1[Worker Pod 1]
                WRK2[Worker Pod 2]
            end
        end
        
        subgraph Data["Data Layer"]
            PG[(PostgreSQL<br/>Primary)]
            PGR[(PostgreSQL<br/>Replica)]
            RD[(Redis Cluster)]
            S3[(S3 Storage)]
        end
        
        subgraph Analytics["Analytics Layer"]
            MG[(MongoDB Atlas)]
            ES[(Elasticsearch)]
        end
        
        subgraph Queue["Message Queue"]
            SQS[SQS/RabbitMQ]
        end
    end
    
    subgraph External["External Services"]
        BLK[Blockchain Network]
        PAY[Payment Providers]
        GOV[Government APIs]
    end
    
    ALB --> K8s
    K8s --> PG
    K8s --> RD
    K8s --> SQS
    PG --> PGR
    WRK1 --> MG
    WRK2 --> ES
    API1 --> S3
    K8s --> External
```

---

## 13. Implementation Phases

### Phase 1: Foundation (Weeks 1-4)
- [ ] Database schema implementation
- [ ] Core supplier management service
- [ ] Basic allocation workflow
- [ ] Ledger service foundation
- [ ] Authentication/Authorization

### Phase 2: Bidding & Fulfillment (Weeks 5-8)
- [ ] Complete bidding system
- [ ] Escrow service integration
- [ ] Fulfillment tracking
- [ ] Milestone management
- [ ] Notification system

### Phase 3: AI/BI Integration (Weeks 9-12)
- [ ] Supplier scoring algorithm
- [ ] Fraud detection model
- [ ] Recommendation engine
- [ ] Analytics dashboard
- [ ] Reporting system

### Phase 4: Advanced Features (Weeks 13-16)
- [ ] NFT integration for ledger
- [ ] Blockchain anchoring
- [ ] Mobile API
- [ ] Advanced analytics
- [ ] PHINS deep integration

---

## 14. Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | React/Vue.js | Dashboard UI |
| **API Gateway** | Flask/FastAPI | REST endpoints |
| **Services** | Python 3.11+ | Business logic |
| **ORM** | SQLAlchemy | Database abstraction |
| **Primary DB** | PostgreSQL 15 | Transactional data |
| **Cache** | Redis | Session, caching |
| **Analytics DB** | MongoDB | Time-series, analytics |
| **Search** | Elasticsearch | Full-text search |
| **Queue** | RabbitMQ/SQS | Async processing |
| **ML Framework** | scikit-learn/TensorFlow | AI models |
| **Blockchain** | Ethereum/Polygon | Ledger anchoring |
| **Monitoring** | Prometheus/Grafana | Observability |

---

## Conclusion

The Sully Chain architecture provides a comprehensive, scalable, and secure supplier management ecosystem that seamlessly integrates with the PHINS Insurance Platform. Key architectural decisions include:

1. **Modular Service Design**: Each capability is encapsulated in dedicated services for maintainability
2. **Event-Driven Architecture**: Enables loose coupling and real-time processing
3. **Immutable Ledger**: Provides complete audit trail with blockchain anchoring
4. **AI-First Analytics**: Embedded intelligence for scoring, fraud detection, and recommendations
5. **Multi-Tenant Security**: Role-based access with attribute-level permissions

This architecture supports the full lifecycle of supplier management from registration through service fulfillment, with complete transparency and accountability at every step.

---

*Document Version: 1.0*  
*Last Updated: January 2026*  
*Author: PHINS Architecture Team*
