# PHINS Supplier Ecosystem Architecture

## Overview

The PHINS Supplier Ecosystem enables B2B connections between the insurance platform and external service/product providers. Suppliers include healthcare providers (doctors, pharmacies), legal services (lawyers), delivery companies, investment firms, and other service providers that integrate with customer wallets (Health Wallet, Investment Wallet, etc.).

---

## UML Class Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHINS SUPPLIER ECOSYSTEM                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER HIERARCHY                                  │
│                                                                              │
│  ┌──────────┐     ┌──────────────┐     ┌─────────────┐                      │
│  │   User   │◄────│   Customer   │     │  Supplier   │ (NEW)                │
│  │  (Staff) │     │ (Policyholder)│     │  (B2B User) │                      │
│  └────┬─────┘     └──────────────┘     └──────┬──────┘                      │
│       │                                        │                             │
│       ▼                                        ▼                             │
│  [admin, underwriter,              [healthcare_provider, legal_service,     │
│   claims_adjuster,                  pharmacy, delivery, investment_firm,    │
│   accountant, supplier]             equipment_supplier, other]              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           SUPPLIER MODEL                                     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                         Supplier                                    │     │
│  ├────────────────────────────────────────────────────────────────────┤     │
│  │ + id: String (PK) [SUP-XXXX-XXXX]                                  │     │
│  │ + company_name: String                                             │     │
│  │ + business_registration_number: String                             │     │
│  │ + tax_id: String                                                   │     │
│  │ + supplier_type: Enum [healthcare_provider, legal_service,         │     │
│  │                        pharmacy, delivery, investment_firm,        │     │
│  │                        equipment_supplier, tech_provider, other]   │     │
│  │ + category: String [medical, legal, financial, logistics, tech]   │     │
│  │ + sub_category: String                                             │     │
│  │ + description: Text                                                │     │
│  │ + services_offered: JSON                                           │     │
│  │ + products_offered: JSON                                           │     │
│  │                                                                    │     │
│  │ -- Contact Information --                                          │     │
│  │ + contact_name: String                                             │     │
│  │ + contact_email: String (unique)                                   │     │
│  │ + contact_phone: String                                            │     │
│  │ + website: String                                                  │     │
│  │ + address: Text                                                    │     │
│  │ + city: String                                                     │     │
│  │ + state: String                                                    │     │
│  │ + country: String                                                  │     │
│  │ + postal_code: String                                              │     │
│  │                                                                    │     │
│  │ -- Authentication --                                               │     │
│  │ + password_hash: String                                            │     │
│  │ + password_salt: String                                            │     │
│  │ + portal_active: Boolean                                           │     │
│  │ + last_login: DateTime                                             │     │
│  │                                                                    │     │
│  │ -- Approval Workflow --                                            │     │
│  │ + status: Enum [pending, under_review, approved, rejected,         │     │
│  │                 suspended, terminated]                             │     │
│  │ + application_date: DateTime                                       │     │
│  │ + review_date: DateTime                                            │     │
│  │ + approval_date: DateTime                                          │     │
│  │ + approved_by: String                                              │     │
│  │ + rejection_reason: Text                                           │     │
│  │ + suspension_reason: Text                                          │     │
│  │                                                                    │     │
│  │ -- AI Risk Assessment --                                           │     │
│  │ + ai_risk_score: Float [0.0 - 1.0]                                │     │
│  │ + ai_trust_score: Float [0.0 - 1.0]                               │     │
│  │ + ai_recommendation: Enum [approve, review, reject]               │     │
│  │ + verification_status: Enum [pending, verified, failed]           │     │
│  │ + documents_verified: Boolean                                      │     │
│  │                                                                    │     │
│  │ -- Wallet Configuration --                                         │     │
│  │ + wallet_types_supported: JSON [health, investment, general]      │     │
│  │ + payment_methods: JSON [wallet, bank_transfer, crypto]           │     │
│  │ + bank_details: JSON (encrypted)                                   │     │
│  │ + commission_rate: Float [0.0 - 0.30]                             │     │
│  │ + settlement_frequency: Enum [daily, weekly, monthly]             │     │
│  │                                                                    │     │
│  │ -- Performance Metrics --                                          │     │
│  │ + total_orders: Integer                                            │     │
│  │ + total_revenue: Float                                             │     │
│  │ + average_rating: Float [0.0 - 5.0]                               │     │
│  │ + total_reviews: Integer                                           │     │
│  │ + dispute_count: Integer                                           │     │
│  │ + dispute_resolution_rate: Float                                   │     │
│  │                                                                    │     │
│  │ -- Timestamps --                                                   │     │
│  │ + created_date: DateTime                                           │     │
│  │ + updated_date: DateTime                                           │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                        SUPPLIER OFFER MODEL                                  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                      SupplierOffer                                  │     │
│  ├────────────────────────────────────────────────────────────────────┤     │
│  │ + id: String (PK) [OFF-XXXX-XXXX]                                  │     │
│  │ + supplier_id: String (FK -> Supplier)                             │     │
│  │ + name: String                                                     │     │
│  │ + description: Text                                                │     │
│  │ + item_type: Enum [service, product]                              │     │
│  │ + category: String                                                 │     │
│  │ + sub_category: String                                             │     │
│  │ + price: Float                                                     │     │
│  │ + currency: String [USD, EUR, GBP, etc]                           │     │
│  │ + unit: String [per_visit, per_item, per_hour, etc]               │     │
│  │ + min_quantity: Integer                                            │     │
│  │ + max_quantity: Integer                                            │     │
│  │ + wallet_compatible: JSON [health, investment]                     │     │
│  │ + active: Boolean                                                  │     │
│  │ + featured: Boolean                                                │     │
│  │ + image_url: String                                                │     │
│  │ + availability: JSON                                               │     │
│  │ + created_date: DateTime                                           │     │
│  │ + updated_date: DateTime                                           │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                      SUPPLIER ORDER MODEL                                    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                      SupplierOrder                                  │     │
│  ├────────────────────────────────────────────────────────────────────┤     │
│  │ + id: String (PK) [ORD-XXXX-XXXX]                                  │     │
│  │ + supplier_id: String (FK -> Supplier)                             │     │
│  │ + customer_id: String (FK -> Customer)                             │     │
│  │ + offer_id: String (FK -> SupplierOffer)                          │     │
│  │ + order_type: Enum [service, product]                             │     │
│  │ + quantity: Integer                                                │     │
│  │ + unit_price: Float                                                │     │
│  │ + total_amount: Float                                              │     │
│  │ + platform_fee: Float                                              │     │
│  │ + supplier_payout: Float                                           │     │
│  │ + payment_method: Enum [health_wallet, investment_wallet, bank]   │     │
│  │ + wallet_transaction_id: String                                    │     │
│  │ + status: Enum [pending, confirmed, processing, shipped,          │     │
│  │                 delivered, completed, cancelled, refunded]         │     │
│  │ + delivery_address: Text                                           │     │
│  │ + delivery_notes: Text                                             │     │
│  │ + scheduled_date: DateTime                                         │     │
│  │ + completed_date: DateTime                                         │     │
│  │ + rating: Float                                                    │     │
│  │ + review: Text                                                     │     │
│  │ + created_date: DateTime                                           │     │
│  │ + updated_date: DateTime                                           │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ENTITY RELATIONSHIPS                                     │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────┐                                      ┌──────────────┐
  │ Customer │──────────── places ────────────────▶│SupplierOrder │
  │          │                                      │              │
  │          │◀──────────deposits to────────────── │              │
  └────┬─────┘                                      └──────┬───────┘
       │                                                   │
       │ owns                                              │ references
       ▼                                                   ▼
  ┌──────────────┐                                 ┌──────────────┐
  │Health Wallet │◀──pays via───────────────────── │SupplierOffer │
  │Investment    │                                 │              │
  │Wallet        │                                 │              │
  └──────────────┘                                 └──────┬───────┘
                                                          │
                                                          │ belongs to
                                                          ▼
  ┌──────────┐           ┌───────────────┐        ┌──────────────┐
  │  Admin   │──approves▶│SupplierApproval│◀───── │   Supplier   │
  │          │           │   Workflow     │        │              │
  └──────────┘           └───────────────┘        └──────┬───────┘
                                                          │
                                                          │ has
                                                          ▼
                                                   ┌──────────────┐
                                                   │ SupplierDocs │
                                                   │ (verification)│
                                                   └──────────────┘
```

---

## Supplier Types & Categories

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SUPPLIER TAXONOMY                                     │
└─────────────────────────────────────────────────────────────────────────────┘

HEALTHCARE_PROVIDER
├── Hospitals & Clinics
├── Doctors (General Practice)
├── Specialists (Cardiology, Orthopedics, etc.)
├── Mental Health Professionals
├── Physical Therapists
├── Chiropractors
└── Home Care Services

PHARMACY
├── Retail Pharmacies
├── Online Pharmacies
├── Specialty Pharmacies
└── Compounding Pharmacies

LEGAL_SERVICE
├── Insurance Law Firms
├── Personal Injury Attorneys
├── Medical Malpractice Lawyers
├── Estate Planning
└── Corporate Legal Services

DELIVERY
├── Medical Equipment Delivery
├── Prescription Delivery
├── Document Courier
└── Emergency Medical Transport

INVESTMENT_FIRM
├── Asset Management
├── Insurance-Linked Securities
├── Pension Funds
├── Index Fund Providers
└── Crypto Asset Managers

EQUIPMENT_SUPPLIER
├── Medical Equipment (Wheelchairs, CPAP, etc.)
├── Home Healthcare Devices
├── Diagnostic Equipment
└── Rehabilitation Equipment

TECH_PROVIDER
├── Telemedicine Platforms
├── Health Monitoring Apps
├── Insurance Tech Solutions
└── AI/ML Service Providers

OTHER
├── Laboratory Services
├── Imaging Centers
├── Wellness Programs
└── Rehabilitation Centers
```

---

## Registration & Approval Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SUPPLIER REGISTRATION FLOW                                │
└─────────────────────────────────────────────────────────────────────────────┘

     ┌─────────────────────────────────────────────────────────────────────┐
     │                     SUPPLIER REGISTRATION                            │
     │                    (/supplier-register.html)                         │
     └───────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
     ┌─────────────────────────────────────────────────────────────────────┐
     │  Step 1: Basic Information                                          │
     │  - Company Name, Business Registration, Tax ID                      │
     │  - Supplier Type & Category                                         │
     │  - Contact Details (Name, Email, Phone)                             │
     └───────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
     ┌─────────────────────────────────────────────────────────────────────┐
     │  Step 2: Business Details                                           │
     │  - Description of Services/Products                                 │
     │  - Service Areas/Regions                                            │
     │  - Supported Wallet Types (Health, Investment)                      │
     │  - Expected Volume/Capacity                                         │
     └───────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
     ┌─────────────────────────────────────────────────────────────────────┐
     │  Step 3: Document Upload                                            │
     │  - Business License                                                 │
     │  - Professional Certifications                                      │
     │  - Insurance Certificate                                            │
     │  - Bank Details (for settlements)                                   │
     └───────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
     ┌─────────────────────────────────────────────────────────────────────┐
     │  Step 4: Account Setup                                              │
     │  - Create Username/Password                                         │
     │  - Accept Terms & Conditions                                        │
     │  - Commission Rate Agreement                                        │
     └───────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │   Application Submitted        │
                    │   Status: PENDING              │
                    └───────────────┬────────────────┘
                                    │
           ┌────────────────────────┼────────────────────────┐
           ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ AI Risk Analysis │    │ Document Verify  │    │ Background Check │
│                  │    │                  │    │                  │
│ - Business Score │    │ - License Valid  │    │ - Fraud Check    │
│ - Trust Score    │    │ - Certs Verified │    │ - Compliance     │
│ - Risk Factors   │    │ - Insurance OK   │    │ - History        │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌────────────────────────────────┐
                    │   AI Recommendation            │
                    │   - APPROVE (auto)             │
                    │   - REVIEW (manual)            │
                    │   - REJECT (auto)              │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
           ┌────────────┐  ┌────────────┐  ┌────────────┐
           │ Auto-Approve│  │ Manual Rev │  │Auto-Reject │
           │ (Score>0.8) │  │(0.4<S<0.8) │  │ (Score<0.4)│
           └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
                 │               │               │
                 ▼               ▼               ▼
           ┌────────────┐  ┌────────────┐  ┌────────────┐
           │  APPROVED  │  │UNDER_REVIEW│  │  REJECTED  │
           │ Portal Act │  │ Admin Rev. │  │ Notify     │
           └────────────┘  └────────────┘  └────────────┘
```

---

## Admin Dashboard Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ADMIN SUPPLIER DASHBOARD                                  │
│                  (/admin-supplier-dashboard.html)                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  OVERVIEW TAB                                                               │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ Total       │ │ Pending     │ │ Active      │ │ Revenue     │           │
│  │ Suppliers   │ │ Applications│ │ Suppliers   │ │ This Month  │           │
│  │    156      │ │     12      │ │    142      │ │  $145,230   │           │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘           │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  Supplier Distribution by Type                    [PIE CHART]         │ │
│  │  - Healthcare: 45%   - Pharmacy: 20%   - Legal: 15%                  │ │
│  │  - Equipment: 12%    - Other: 8%                                     │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  PENDING APPLICATIONS TAB                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ID         Company          Type        Applied     AI Score  Action │   │
│  │ SUP-0012   MedCare Clinic   Healthcare  2026-01-15  0.85      [Review]│   │
│  │ SUP-0013   FastRx Pharmacy  Pharmacy    2026-01-16  0.72      [Review]│   │
│  │ SUP-0014   Legal Eagles     Legal       2026-01-17  0.45      [Review]│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  [Approve Selected] [Reject Selected] [Request More Info]                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ACTIVE SUPPLIERS TAB                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Filter: [All Types ▼] [All Status ▼] [Search...]                    │   │
│  │                                                                      │   │
│  │ ID         Company          Type        Orders   Revenue   Rating   │   │
│  │ SUP-0001   City Hospital    Healthcare  1,234    $456K     4.8 ★   │   │
│  │ SUP-0002   PharmaCo         Pharmacy      892    $123K     4.5 ★   │   │
│  │ SUP-0003   LawFirst Ltd     Legal         234    $89K      4.2 ★   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  [View Details] [Suspend] [Update Commission] [View Transactions]          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  TRANSACTIONS TAB                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Date        Order ID    Supplier      Customer    Amount   Status    │   │
│  │ 2026-01-18  ORD-5678    MedCare       CUST-001    $250     Completed │   │
│  │ 2026-01-18  ORD-5679    PharmaCo      CUST-023    $85      Delivered │   │
│  │ 2026-01-17  ORD-5680    Legal Eagles  CUST-045    $500     Processing│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Total: $145,230  |  Platform Fees: $14,523  |  Supplier Payouts: $130,707 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  AI/BI ANALYTICS TAB                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  AI-Powered Insights                                                │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │ Recommendations:                                             │   │   │
│  │  │ • 3 suppliers have declining ratings - review recommended    │   │   │
│  │  │ • Healthcare category underserved in Region X                │   │   │
│  │  │ • High demand for delivery services - recruit more          │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │ Risk Alerts:                                                 │   │   │
│  │  │ ⚠ SUP-0045: 5 disputes in last 30 days                      │   │   │
│  │  │ ⚠ SUP-0078: Document expiring in 15 days                    │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Wallet Integration Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WALLET TRANSACTION FLOW                                   │
└─────────────────────────────────────────────────────────────────────────────┘

    Customer                    PHINS Platform                  Supplier
       │                              │                            │
       │  1. Browse Marketplace       │                            │
       │─────────────────────────────▶│                            │
       │                              │                            │
       │  2. Select Service/Product   │                            │
       │─────────────────────────────▶│                            │
       │                              │                            │
       │  3. Choose Payment Method    │                            │
       │     [Health Wallet]          │                            │
       │─────────────────────────────▶│                            │
       │                              │                            │
       │                              │  4. Validate Wallet Balance│
       │                              │───────────────────────────▶│
       │                              │                            │
       │                              │  5. Debit Health Wallet    │
       │                              │◀───────────────────────────│
       │                              │                            │
       │                              │  6. Create Order           │
       │                              │───────────────────────────▶│
       │                              │                            │
       │                              │  7. Notify Supplier        │
       │                              │────────────────────────────│
       │                              │                            │
       │  8. Order Confirmation       │                            │
       │◀─────────────────────────────│                            │
       │                              │                            │
       │                              │  9. Service/Product        │
       │                              │◀────────────────────────────│
       │                              │     Delivered              │
       │                              │                            │
       │                              │ 10. Mark Completed         │
       │                              │────────────────────────────│
       │                              │                            │
       │                              │ 11. Settle Payment         │
       │                              │     (Less Platform Fee)    │
       │                              │────────────────────────────▶│
       │                              │                            │
       │ 12. Rate & Review            │                            │
       │─────────────────────────────▶│                            │
       │                              │                            │
```

---

## Security & Data Integrity

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SECURITY MEASURES                                         │
└─────────────────────────────────────────────────────────────────────────────┘

1. AUTHENTICATION & AUTHORIZATION
   ├── Separate login for Suppliers (role: supplier)
   ├── Multi-factor authentication option
   ├── Session management with expiry
   └── Role-based access control (RBAC)

2. DATA ENCRYPTION
   ├── Passwords: salted SHA-256 hash
   ├── Bank details: encrypted at rest
   ├── API communications: HTTPS only
   └── Sensitive documents: encrypted storage

3. AUDIT TRAIL
   ├── All supplier actions logged
   ├── Approval/rejection history
   ├── Transaction records immutable
   └── Document verification timestamps

4. AI RISK MONITORING
   ├── Continuous trust score updates
   ├── Anomaly detection in transactions
   ├── Fraud pattern recognition
   └── Automated alerts for suspicious activity

5. DATA INTEGRITY
   ├── Transaction ledger validation
   ├── Wallet balance reconciliation
   ├── Double-entry bookkeeping
   └── Periodic integrity checks
```

---

## API Endpoints

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SUPPLIER API ENDPOINTS                                    │
└─────────────────────────────────────────────────────────────────────────────┘

REGISTRATION & AUTH
  POST   /api/supplier/register         - Submit new supplier application
  POST   /api/supplier/login            - Supplier authentication
  POST   /api/supplier/logout           - End session
  GET    /api/supplier/profile          - Get supplier profile

ADMIN MANAGEMENT
  GET    /api/admin/suppliers           - List all suppliers (paginated)
  GET    /api/admin/suppliers/pending   - List pending applications
  GET    /api/admin/suppliers/:id       - Get supplier details
  POST   /api/admin/suppliers/:id/approve  - Approve supplier
  POST   /api/admin/suppliers/:id/reject   - Reject supplier
  POST   /api/admin/suppliers/:id/suspend  - Suspend supplier
  PUT    /api/admin/suppliers/:id       - Update supplier settings

OFFERS (SUPPLIER)
  GET    /api/supplier/offers           - List supplier's offers
  POST   /api/supplier/offers/upsert    - Create/update offer
  DELETE /api/supplier/offers/:id       - Delete offer

ORDERS
  GET    /api/supplier/orders           - List supplier's orders
  POST   /api/supplier/orders/:id/update-status  - Update order status
  GET    /api/orders/:id                - Get order details

ANALYTICS
  GET    /api/supplier/analytics        - Supplier performance metrics
  GET    /api/admin/suppliers/analytics - Platform-wide supplier analytics

WALLET INTEGRATION
  POST   /api/orders/create             - Create order (customer endpoint)
  POST   /api/orders/:id/pay            - Process wallet payment
  GET    /api/orders/:id/track          - Track order status
```

---

## Implementation Files

```
/workspace/
├── database/
│   └── models.py                    # Add Supplier, SupplierOffer, SupplierOrder models
│
├── services/
│   └── supplier_service.py          # Business logic for supplier management
│
├── web_portal/
│   ├── server.py                    # API endpoints
│   └── static/
│       ├── supplier-register.html   # Supplier registration page
│       ├── supplier-portal.html     # Supplier self-service portal
│       └── admin-supplier-dashboard.html  # Admin management dashboard
│
└── SUPPLIER_ECOSYSTEM_ARCHITECTURE.md  # This file
```

---

*Architecture Version: 1.0*
*Last Updated: January 2026*
*Author: PHINS Engineering Team*
