# PHINS Insurance Platform - Database Architecture UML

## Overview

This document provides a comprehensive DBA UML sketch of the PHINS Insurance Platform's architectural structure, including entity-relationship diagrams, system layer architecture, and data flow patterns.

---

## 1. Entity-Relationship Diagram (ERD)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           PHINS DATABASE SCHEMA - ERD                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

                                    ┌──────────────────────┐
                                    │       USERS          │
                                    ├──────────────────────┤
                                    │ PK username VARCHAR  │
                                    │    password_hash     │
                                    │    password_salt     │
                                    │    role              │
                                    │    name              │
                                    │    email             │
                                    │    active            │
                                    │    created_date      │
                                    │    last_login        │
                                    └──────────┬───────────┘
                                               │
                                               │ 1:N (manages)
                                               ▼
┌──────────────────────┐          ┌──────────────────────┐          ┌──────────────────────┐
│    AUDIT_LOGS        │          │      SESSIONS        │          │  ACTUARIAL_TABLES    │
├──────────────────────┤          ├──────────────────────┤          ├──────────────────────┤
│ PK id INTEGER        │          │ PK token VARCHAR     │          │ PK id VARCHAR        │
│    timestamp         │          │ FK username          │          │    name              │
│ FK username          │◄─────────│ FK customer_id       │          │    table_type        │
│ FK customer_id       │          │    ip_address        │          │    version           │
│    action            │          │    expires           │          │    effective_date    │
│    entity_type       │          │    created_date      │          │    payload (encrypted)│
│    entity_id         │          └──────────────────────┘          │    classification    │
│    details (JSON)    │                                            │ FK created_by        │
│    ip_address        │                                            │    created_date      │
│    success           │                                            └──────────────────────┘
└──────────────────────┘

                                    ┌──────────────────────┐
                                    │     CUSTOMERS        │
                                    ├──────────────────────┤
                                    │ PK id VARCHAR        │
                                    │    name              │
                                    │    first_name        │
                                    │    last_name         │
                                    │    email (UNIQUE)    │
                                    │    phone             │
                                    │    dob               │
                                    │    age               │
                                    │    gender            │
                                    │    address           │
                                    │    city              │
                                    │    state             │
                                    │    zip               │
                                    │    occupation        │
                                    │    created_date      │
                                    │    updated_date      │
                                    └──────────┬───────────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          │                    │                    │
                          │ 1:N               │ 1:N               │ 1:N
                          ▼                    ▼                    ▼
┌──────────────────────┐  │   ┌──────────────────────┐  ┌──────────────────────┐
│      POLICIES        │  │   │       CLAIMS         │  │        BILLS         │
├──────────────────────┤  │   ├──────────────────────┤  ├──────────────────────┤
│ PK id VARCHAR        │  │   │ PK id VARCHAR        │  │ PK id VARCHAR        │
│ FK customer_id       │◄─┤   │ FK policy_id         │  │ FK policy_id         │
│    type              │  │   │ FK customer_id       │◄─┤ FK customer_id       │
│    coverage_amount   │  │   │    type              │  │    amount            │
│    annual_premium    │  │   │    description       │  │    amount_paid       │
│    monthly_premium   │  │   │    claimed_amount    │  │    status            │
│    quarterly_premium │  │   │    approved_amount   │  │    due_date          │
│    status            │  │   │    status            │  │    paid_date         │
│ FK underwriting_id   │  │   │    filed_date        │  │    payment_method    │
│    risk_score        │  │   │    approval_date     │  │    transaction_id    │
│    start_date        │  │   │    payment_date      │  │    late_fee          │
│    end_date          │  │   │    rejection_reason  │  │    created_date      │
│    approval_date     │  │   │    created_date      │  │    updated_date      │
│    created_date      │  │   │    updated_date      │  └──────────────────────┘
│    updated_date      │  │   └──────────────────────┘
│    uw_status         │  │            ▲
└──────────┬───────────┘  │            │
           │              │            │ 1:N
           │ 1:N          │            │
           ▼              │            │
┌──────────────────────┐  │   ┌───────┴──────────────┐
│ UNDERWRITING_APPS    │  │   │                      │
├──────────────────────┤  │   │   (claims linked to  │
│ PK id VARCHAR        │  │   │    both policy and   │
│ FK policy_id         │◄─┘   │    customer for      │
│ FK customer_id       │      │    data integrity)   │
│    status            │      │                      │
│    risk_assessment   │      └──────────────────────┘
│    medical_exam_req  │
│    add_docs_required │
│    notes             │
│    submitted_date    │
│    decision_date     │
│    decided_by        │
│    created_date      │
│    updated_date      │
└──────────────────────┘


┌──────────────────────┐
│   TOKEN_REGISTRY     │
├──────────────────────┤
│ PK id VARCHAR        │
│    symbol            │
│    name              │
│    asset_type        │
│    chain             │
│    contract_address  │
│    decimals          │
│    enabled           │
│    metadata (JSON)   │
│    classification    │
│ FK created_by        │
│    created_date      │
└──────────────────────┘
```

---

## 2. Table Relationships Summary

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                              RELATIONSHIP CARDINALITY                                      │
├─────────────────────┬──────────────────────┬──────────────────────────────────────────────┤
│   Parent Entity     │   Child Entity       │   Relationship                               │
├─────────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│   customers         │   policies           │   1:N (one customer, many policies)          │
│   customers         │   claims             │   1:N (one customer, many claims)            │
│   policies          │   claims             │   1:N (one policy, many claims)              │
│   policies          │   underwriting_apps  │   1:1 (one policy, one underwriting app)     │
│   policies          │   bills              │   1:N (one policy, many bills)               │
│   customers         │   bills              │   1:N (one customer, many bills)             │
│   users             │   sessions           │   1:N (one user, many sessions)              │
│   users             │   audit_logs         │   1:N (one user, many audit entries)         │
│   customers         │   sessions           │   1:N (one customer, many sessions)          │
│   users             │   actuarial_tables   │   1:N (creator relationship)                 │
│   users             │   token_registry     │   1:N (creator relationship)                 │
└─────────────────────┴──────────────────────┴──────────────────────────────────────────────┘
```

---

## 3. System Layer Architecture (Component Diagram)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              PHINS PLATFORM ARCHITECTURE                                     │
│                               (3-Tier Architecture)                                          │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

╔═════════════════════════════════════════════════════════════════════════════════════════════╗
║                                  PRESENTATION LAYER                                          ║
║                                    (Web Portal)                                              ║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                              ║
║   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        ║
║   │  Client Portal  │  │  Admin Portal   │  │   Underwriter   │  │ Claims Adjuster │        ║
║   │                 │  │                 │  │   Dashboard     │  │   Dashboard     │        ║
║   │  - Login        │  │  - User Mgmt    │  │                 │  │                 │        ║
║   │  - Register     │  │  - System Config│  │  - Risk Assess  │  │  - Claim Review │        ║
║   │  - Quote        │  │  - Reports      │  │  - Approve/Deny │  │  - Approve/Deny │        ║
║   │  - Apply        │  │  - Audit Logs   │  │  - Refer        │  │  - Pay Claims   │        ║
║   │  - Dashboard    │  │                 │  │                 │  │                 │        ║
║   │  - Billing      │  │                 │  │                 │  │                 │        ║
║   └─────────────────┘  └─────────────────┘  └─────────────────┘  └─────────────────┘        ║
║                                                                                              ║
║   ┌─────────────────┐  ┌───────────────────────────────────────────────────────────┐        ║
║   │   Accountant    │  │                      Static Assets                        │        ║
║   │   Dashboard     │  │  (HTML, CSS, JavaScript - web_portal/static/)             │        ║
║   │                 │  │                                                           │        ║
║   │  - Billing Mgmt │  │  ├── index.html, login.html, register.html                │        ║
║   │  - Payments     │  │  ├── dashboard.html, quote.html, apply.html               │        ║
║   │  - Reports      │  │  ├── admin-portal.html, underwriter-dashboard.html        │        ║
║   │                 │  │  ├── claims-adjuster-dashboard.html, accountant.html      │        ║
║   └─────────────────┘  │  └── styles.css, app.js, admin-app.js                     │        ║
║                        └───────────────────────────────────────────────────────────┘        ║
╚═════════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            │ HTTP/REST API
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════════╗
║                                  APPLICATION LAYER                                           ║
║                              (Business Logic & Services)                                     ║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                              ║
║   ┌───────────────────────────────────────────────────────────────────────────────────┐     ║
║   │                          Web Portal Server (Flask)                                 │     ║
║   │                         (web_portal/server.py)                                     │     ║
║   │                                                                                    │     ║
║   │   REST API Endpoints:                                                              │     ║
║   │   /api/auth/*        - Authentication & Session Management                         │     ║
║   │   /api/customers/*   - Customer CRUD Operations                                    │     ║
║   │   /api/policies/*    - Policy Management                                           │     ║
║   │   /api/claims/*      - Claims Processing                                           │     ║
║   │   /api/billing/*     - Billing & Payments                                          │     ║
║   │   /api/underwriting/*- Underwriting Operations                                     │     ║
║   │   /api/admin/*       - Admin Functions                                             │     ║
║   └───────────────────────────────────────────────────────────────────────────────────┘     ║
║                                            │                                                 ║
║              ┌─────────────────────────────┼─────────────────────────────┐                  ║
║              ▼                             ▼                             ▼                  ║
║   ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐              ║
║   │   PolicyService     │   │   ClaimsService     │   │   BillingService    │              ║
║   │                     │   │                     │   │                     │              ║
║   │ - create()          │   │ - create()          │   │ - create_bill()     │              ║
║   │ - renew()           │   │ - approve()         │   │ - record_payment()  │              ║
║   │ - set_status()      │   │ - reject()          │   │ - apply_late_fee()  │              ║
║   └─────────────────────┘   └─────────────────────┘   └─────────────────────┘              ║
║              │                             │                             │                  ║
║              │         ┌───────────────────┼───────────────────┐         │                  ║
║              │         ▼                   ▼                   ▼         │                  ║
║              │   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐│                  ║
║              │   │Underwriting   │   │  AuditService │   │MarketData     ││                  ║
║              │   │   Service     │   │               │   │  Service      ││                  ║
║              │   │               │   │ - log()       │   │               ││                  ║
║              │   │ - initiate()  │   │ - recent()    │   │ - get_rates() ││                  ║
║              │   │ - assess_risk │   │               │   │ - forecasts() ││                  ║
║              │   │ - approve()   │   │               │   │               ││                  ║
║              │   │ - refer()     │   │               │   │               ││                  ║
║              │   └───────────────┘   └───────────────┘   └───────────────┘│                  ║
║              │                                                           │                  ║
║              └───────────────────────────┬───────────────────────────────┘                  ║
║                                          │                                                  ║
║   ┌──────────────────────────────────────┼──────────────────────────────────────┐          ║
║   │                        Security Layer (security/vault.py)                    │          ║
║   │                                                                              │          ║
║   │   - Encryption/Decryption (Fernet AES-128)                                  │          ║
║   │   - Key Derivation (PBKDF2-HMAC-SHA256)                                     │          ║
║   │   - Data Classification Enforcement                                          │          ║
║   │   - Session Token Management                                                 │          ║
║   └──────────────────────────────────────────────────────────────────────────────┘          ║
╚═════════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            │ SQLAlchemy ORM
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════════╗
║                                    DATA ACCESS LAYER                                         ║
║                               (Repository Pattern)                                           ║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                              ║
║   ┌───────────────────────────────────────────────────────────────────────────────────┐     ║
║   │                              BaseRepository<T>                                     │     ║
║   │                         (database/repositories/base.py)                            │     ║
║   │                                                                                    │     ║
║   │   Generic CRUD Operations:                                                         │     ║
║   │   - create(**kwargs) → T                                                           │     ║
║   │   - get_by_id(id) → T                                                              │     ║
║   │   - get_all(limit, offset) → List[T]                                               │     ║
║   │   - update(id, **kwargs) → T                                                       │     ║
║   │   - delete(id) → bool                                                              │     ║
║   │   - filter_by(**kwargs) → List[T]                                                  │     ║
║   │   - count() → int                                                                  │     ║
║   └───────────────────────────────────────────────────────────────────────────────────┘     ║
║                                            │                                                 ║
║                                            │ extends                                         ║
║       ┌────────────────────────────────────┼────────────────────────────────────┐           ║
║       ▼                    ▼               ▼               ▼                    ▼           ║
║   ┌──────────┐   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    ║
║   │Customer  │   │   Policy     │  │    Claim     │  │   Billing    │  │ Underwriting │    ║
║   │Repository│   │  Repository  │  │  Repository  │  │  Repository  │  │  Repository  │    ║
║   └──────────┘   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    ║
║                                                                                              ║
║   ┌──────────┐   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    ║
║   │  User    │   │   Session    │  │    Audit     │  │  Actuarial   │  │    Token     │    ║
║   │Repository│   │  Repository  │  │  Repository  │  │  Repository  │  │  Repository  │    ║
║   └──────────┘   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    ║
║                                                                                              ║
║   ┌───────────────────────────────────────────────────────────────────────────────────┐     ║
║   │                           DatabaseManager                                          │     ║
║   │                       (database/manager.py)                                        │     ║
║   │                                                                                    │     ║
║   │   - Context manager for transaction scope                                          │     ║
║   │   - Provides access to all repositories                                            │     ║
║   │   - Handles connection pooling                                                     │     ║
║   └───────────────────────────────────────────────────────────────────────────────────┘     ║
╚═════════════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                                            │ Connection Pool
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════════════╗
║                                    DATABASE LAYER                                            ║
║                            (PostgreSQL / SQLite)                                             ║
╠═════════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                              ║
║   ┌───────────────────────────────────────────────────────────────────────────────────┐     ║
║   │                         SQLAlchemy Engine & Connection Pool                        │     ║
║   │                              (database/__init__.py)                                │     ║
║   │                                                                                    │     ║
║   │   PostgreSQL (Production):                                                         │     ║
║   │   - Pool Size: 20 connections                                                      │     ║
║   │   - Max Overflow: 10 additional connections                                        │     ║
║   │   - Pool Timeout: 30 seconds                                                       │     ║
║   │   - Pool Recycle: 3600 seconds (1 hour)                                            │     ║
║   │                                                                                    │     ║
║   │   SQLite (Development):                                                            │     ║
║   │   - check_same_thread: False (multi-threaded access)                               │     ║
║   └───────────────────────────────────────────────────────────────────────────────────┘     ║
║                                                                                              ║
║   ┌─────────────────────────────────────┐  ┌─────────────────────────────────────┐         ║
║   │         PostgreSQL                  │  │           SQLite                    │         ║
║   │        (Production)                 │  │        (Development)                │         ║
║   │                                     │  │                                     │         ║
║   │  ┌─────────────────────────────┐   │  │  ┌─────────────────────────────┐   │         ║
║   │  │ customers                   │   │  │  │ phins.db                    │   │         ║
║   │  │ policies                    │   │  │  │                             │   │         ║
║   │  │ claims                      │   │  │  │ All tables in single file   │   │         ║
║   │  │ bills                       │   │  │  │                             │   │         ║
║   │  │ underwriting_applications   │   │  │  └─────────────────────────────┘   │         ║
║   │  │ users                       │   │  │                                     │         ║
║   │  │ sessions                    │   │  │                                     │         ║
║   │  │ audit_logs                  │   │  │                                     │         ║
║   │  │ actuarial_tables            │   │  │                                     │         ║
║   │  │ token_registry              │   │  │                                     │         ║
║   │  └─────────────────────────────┘   │  │                                     │         ║
║   └─────────────────────────────────────┘  └─────────────────────────────────────┘         ║
╚═════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 4. Data Flow Diagram (DFD)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           DATA FLOW - POLICY LIFECYCLE                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

    ┌──────────┐                                                         ┌──────────────┐
    │ Customer │                                                         │  Underwriter │
    └────┬─────┘                                                         └──────┬───────┘
         │                                                                      │
         │ 1. Submit Application                                                │
         ▼                                                                      │
    ┌─────────────────┐                                                         │
    │   Quote Engine  │                                                         │
    │                 │                                                         │
    │ - Calculate     │                                                         │
    │   premium       │                                                         │
    │ - Risk factors  │                                                         │
    └────────┬────────┘                                                         │
             │                                                                   │
             │ 2. Create Policy (pending_underwriting)                          │
             ▼                                                                   │
    ┌─────────────────┐          3. Create Underwriting           ┌─────────────┴─────────────┐
    │    POLICIES     │─────────────Application──────────────────▶│  UNDERWRITING_APPLICATIONS │
    │                 │                                           │                            │
    │ status:         │◀──────────5. Update Status────────────────│  status: pending          │
    │ pending_uw      │                                           │  → approved/rejected       │
    └────────┬────────┘                                           └────────────┬───────────────┘
             │                                                                  │
             │                                                                  │ 4. Risk Assessment
             │                                                                  ▼
             │                                                         ┌──────────────────┐
             │                                                         │ - Medical Review │
             │                                                         │ - Credit Check   │
             │                                                         │ - Risk Scoring   │
             │                                                         └──────────────────┘
             │
             │ 6. Policy Activated
             ▼
    ┌─────────────────┐                              ┌─────────────────┐
    │    POLICIES     │───────7. Generate Bills────▶│      BILLS      │
    │                 │                              │                 │
    │ status: active  │                              │ status:         │
    │                 │                              │ outstanding     │
    └────────┬────────┘                              └────────┬────────┘
             │                                                │
             │                                                │ 8. Payment Received
             │                                                ▼
             │                                       ┌─────────────────┐
             │                                       │      BILLS      │
             │                                       │                 │
             │                                       │ status: paid    │
             │                                       └─────────────────┘
             │
             │ 9. Claim Filed
             ▼
    ┌─────────────────┐                              ┌─────────────────┐
    │     CLAIMS      │◀──────────────────────────────│ Claims Adjuster │
    │                 │        10. Review & Process   └─────────────────┘
    │ status: pending │
    │   → approved    │
    │   → rejected    │
    │   → paid        │
    └─────────────────┘
```

---

## 5. Class Diagram (ORM Models)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              ORM MODEL CLASS DIAGRAM                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

                                        ┌─────────────────────────┐
                                        │      <<abstract>>       │
                                        │          Base           │
                                        │   (declarative_base)    │
                                        └────────────┬────────────┘
                                                     │
           ┌─────────────────┬─────────────────┬─────┴─────┬─────────────────┬─────────────────┐
           │                 │                 │           │                 │                 │
           ▼                 ▼                 ▼           ▼                 ▼                 ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐ ┌────────────┐
│     Customer     │ │      Policy      │ │  Claim   │ │   Bill   │ │ UnderwritingApp  │ │    User    │
├──────────────────┤ ├──────────────────┤ ├──────────┤ ├──────────┤ ├──────────────────┤ ├────────────┤
│ +id: String(50)  │ │ +id: String(50)  │ │ +id      │ │ +id      │ │ +id: String(50)  │ │ +username  │
│ +name: String    │ │ +customer_id: FK │ │ +policy_ │ │ +policy_ │ │ +policy_id       │ │ +password_ │
│ +first_name      │ │ +type: String    │ │   id: FK │ │   id     │ │ +customer_id     │ │   hash     │
│ +last_name       │ │ +coverage_amount │ │ +customer│ │ +customer│ │ +status          │ │ +password_ │
│ +email: String   │ │ +annual_premium  │ │   _id:FK │ │   _id    │ │ +risk_assessment │ │   salt     │
│ +phone           │ │ +monthly_premium │ │ +type    │ │ +amount  │ │ +medical_exam_   │ │ +role      │
│ +dob             │ │ +quarterly_prem  │ │ +descr   │ │ +amount_ │ │   required       │ │ +name      │
│ +age             │ │ +status          │ │ +claimed │ │   paid   │ │ +add_docs_req    │ │ +email     │
│ +gender          │ │ +underwriting_id │ │   _amount│ │ +status  │ │ +notes           │ │ +active    │
│ +address         │ │ +risk_score      │ │ +approved│ │ +due_date│ │ +submitted_date  │ │ +created_  │
│ +city            │ │ +start_date      │ │   _amount│ │ +paid_   │ │ +decision_date   │ │   date     │
│ +state           │ │ +end_date        │ │ +status  │ │   date   │ │ +decided_by      │ │ +last_login│
│ +zip             │ │ +approval_date   │ │ +filed_  │ │ +payment │ │ +created_date    │ └────────────┘
│ +occupation      │ │ +created_date    │ │   date   │ │   _method│ │ +updated_date    │
│ +created_date    │ │ +updated_date    │ │ +approval│ │ +trans_  │ └──────────────────┘
│ +updated_date    │ │ +uw_status       │ │   _date  │ │   id     │
├──────────────────┤ ├──────────────────┤ │ +payment │ │ +late_fee│
│ +to_dict()       │ │ +to_dict()       │ │   _date  │ │ +created │ ┌──────────────────┐
│                  │ │                  │ │ +reject_ │ │   _date  │ │    Session       │
│ «relationships»  │ │ «relationships»  │ │   reason │ │ +updated │ ├──────────────────┤
│ policies: 1:N    │ │ customer: N:1    │ │ +created │ │   _date  │ │ +token: PK       │
│ claims: 1:N      │ │ claims: 1:N      │ │   _date  │ ├──────────┤ │ +username        │
└──────────────────┘ └──────────────────┘ │ +updated │ │ +to_dict │ │ +customer_id     │
                                          │   _date  │ └──────────┘ │ +ip_address      │
                                          ├──────────┤              │ +expires         │
                                          │ +to_dict │              │ +created_date    │
                                          │          │              ├──────────────────┤
                                          │«rels»    │              │ +to_dict()       │
                                          │policy:N:1│              └──────────────────┘
                                          │customer: │
                                          │  N:1     │
                                          └──────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│    AuditLog      │  │ ActuarialTable   │  │  TokenRegistry   │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│ +id: Integer PK  │  │ +id: String(50)  │  │ +id: String(50)  │
│ +timestamp       │  │ +name            │  │ +symbol          │
│ +username        │  │ +table_type      │  │ +name            │
│ +customer_id     │  │ +version         │  │ +asset_type      │
│ +action          │  │ +effective_date  │  │ +chain           │
│ +entity_type     │  │ +payload (encr.) │  │ +contract_addr   │
│ +entity_id       │  │ +classification  │  │ +decimals        │
│ +details (JSON)  │  │ +created_by      │  │ +enabled         │
│ +ip_address      │  │ +created_date    │  │ +metadata (JSON) │
│ +success         │  ├──────────────────┤  │ +classification  │
├──────────────────┤  │ +to_dict()       │  │ +created_by      │
│ +to_dict()       │  └──────────────────┘  │ +created_date    │
└──────────────────┘                        ├──────────────────┤
                                            │ +to_dict()       │
                                            └──────────────────┘


┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    ENUMERATIONS                                               │
├────────────────────┬────────────────────┬────────────────────┬────────────────────────────────┤
│   PolicyStatus     │ UnderwritingStatus │   ClaimStatus      │        BillStatus              │
├────────────────────┼────────────────────┼────────────────────┼────────────────────────────────┤
│ ACTIVE             │ PENDING            │ PENDING            │ OUTSTANDING                    │
│ INACTIVE           │ APPROVED           │ UNDER_REVIEW       │ PARTIAL                        │
│ CANCELLED          │ REJECTED           │ APPROVED           │ PAID                           │
│ LAPSED             │ REFERRED           │ REJECTED           │ OVERDUE                        │
│ SUSPENDED          │ APPROVED_COND.     │ PAID               │ CANCELLED                      │
│ PENDING_UW         │                    │ CLOSED             │                                │
└────────────────────┴────────────────────┴────────────────────┴────────────────────────────────┘

┌────────────────────┬────────────────────┐
│ DataClassification │  TokenAssetType    │
├────────────────────┼────────────────────┤
│ PUBLIC             │ CURRENCY           │
│ INTERNAL           │ STABLECOIN         │
│ CONFIDENTIAL       │ NFT                │
│ RESTRICTED         │ INDEX              │
└────────────────────┴────────────────────┘
```

---

## 6. Database Indexes

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              DATABASE INDEX STRATEGY                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

Table: customers
├── PRIMARY KEY (id)
├── UNIQUE INDEX (email)
└── INDEX (email) - for login lookups

Table: policies
├── PRIMARY KEY (id)
├── INDEX (customer_id) - FK lookups
└── INDEX (underwriting_id) - status tracking

Table: claims
├── PRIMARY KEY (id)
├── INDEX (policy_id) - FK lookups
└── INDEX (customer_id) - customer history

Table: underwriting_applications
├── PRIMARY KEY (id)
├── INDEX (policy_id) - FK lookups
└── INDEX (customer_id) - customer applications

Table: bills
├── PRIMARY KEY (id)
├── INDEX (policy_id) - policy billing
└── INDEX (customer_id) - customer billing

Table: users
├── PRIMARY KEY (username)
└── (implicit index on PK)

Table: sessions
├── PRIMARY KEY (token)
├── INDEX (username) - user sessions
├── INDEX (customer_id) - customer sessions
└── INDEX (expires) - session cleanup

Table: audit_logs
├── PRIMARY KEY (id) - auto-increment
├── INDEX (timestamp) - time-based queries
├── INDEX (username) - user audit trail
└── INDEX (customer_id) - customer audit trail

Table: actuarial_tables
├── PRIMARY KEY (id)
├── INDEX (name) - name lookups
├── INDEX (table_type) - type filtering
├── INDEX (version) - version control
├── INDEX (effective_date) - date-based queries
├── INDEX (classification) - security filtering
└── INDEX (created_by) - creator tracking

Table: token_registry
├── PRIMARY KEY (id)
├── INDEX (symbol) - symbol lookups
├── INDEX (asset_type) - type filtering
├── INDEX (enabled) - active tokens
├── INDEX (classification) - security filtering
└── INDEX (created_by) - creator tracking
```

---

## 7. Sequence Diagram - New Policy Application

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                         SEQUENCE: NEW POLICY APPLICATION FLOW                                │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

  Customer        Web Portal       PolicyService    UnderwritingService    Database
     │                │                  │                  │                  │
     │  1. Submit     │                  │                  │                  │
     │  Application   │                  │                  │                  │
     ├───────────────▶│                  │                  │                  │
     │                │                  │                  │                  │
     │                │  2. Validate &   │                  │                  │
     │                │  Create Customer │                  │                  │
     │                ├─────────────────────────────────────────────────────▶│
     │                │                  │                  │        INSERT   │
     │                │◀─────────────────────────────────────────────────────┤
     │                │                  │                  │     customer_id │
     │                │                  │                  │                  │
     │                │  3. create()     │                  │                  │
     │                ├─────────────────▶│                  │                  │
     │                │                  │                  │                  │
     │                │                  │  4. INSERT       │                  │
     │                │                  │  policy          │                  │
     │                │                  ├─────────────────────────────────▶│
     │                │                  │◀─────────────────────────────────┤
     │                │                  │     policy_id    │                  │
     │                │                  │                  │                  │
     │                │                  │  5. initiate()   │                  │
     │                │                  ├─────────────────▶│                  │
     │                │                  │                  │                  │
     │                │                  │                  │  6. INSERT       │
     │                │                  │                  │  underwriting    │
     │                │                  │                  ├────────────────▶│
     │                │                  │                  │◀────────────────┤
     │                │                  │                  │     uw_id       │
     │                │                  │                  │                  │
     │                │                  │◀─────────────────┤                  │
     │                │                  │    uw_app        │                  │
     │                │◀─────────────────┤                  │                  │
     │                │    policy        │                  │                  │
     │                │                  │                  │                  │
     │  7. Success    │                  │                  │                  │
     │◀───────────────┤                  │                  │                  │
     │   Response     │                  │                  │                  │
     │                │                  │                  │                  │

  Underwriter                                                                 
     │                │                  │                  │                  │
     │  8. Review     │                  │                  │                  │
     │  Application   │                  │                  │                  │
     ├───────────────▶│                  │                  │                  │
     │                │                  │                  │                  │
     │                │  9. assess_risk()│                  │                  │
     │                ├─────────────────────────────────▶│                  │
     │                │                  │                  │  10. UPDATE      │
     │                │                  │                  │  uw_application  │
     │                │                  │                  ├────────────────▶│
     │                │                  │                  │◀────────────────┤
     │                │                  │                  │                  │
     │                │                  │  11. approve()   │                  │
     │                ├─────────────────────────────────▶│                  │
     │                │                  │                  │  12. UPDATE      │
     │                │                  │                  │  uw + policy     │
     │                │                  │                  ├────────────────▶│
     │                │                  │                  │◀────────────────┤
     │                │◀────────────────────────────────────┤                  │
     │  13. Approved  │                  │                  │                  │
     │◀───────────────┤                  │                  │                  │
     │                │                  │                  │                  │
```

---

## 8. Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              DEPLOYMENT ARCHITECTURE                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

                              ┌──────────────────────────────────────┐
                              │            Load Balancer             │
                              │           (Railway/Cloud)            │
                              └─────────────────┬────────────────────┘
                                                │
                                                │ HTTPS (443)
                                                ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    APPLICATION CONTAINER                                     │
│                                        (Docker)                                              │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────────────────┐     │
│   │                              Python Application                                    │     │
│   │                                                                                    │     │
│   │   ┌─────────────────────────────────────────────────────────────────────────┐     │     │
│   │   │                      Flask Web Server                                    │     │     │
│   │   │                    (web_portal/server.py)                                │     │     │
│   │   │                                                                          │     │     │
│   │   │   • Static File Serving (HTML, CSS, JS)                                  │     │     │
│   │   │   • REST API Endpoints                                                   │     │     │
│   │   │   • Session Management                                                   │     │     │
│   │   │   • Request Routing                                                      │     │     │
│   │   └─────────────────────────────────────────────────────────────────────────┘     │     │
│   │                                                                                    │     │
│   │   ┌─────────────────────────────────────────────────────────────────────────┐     │     │
│   │   │                      Business Services                                   │     │     │
│   │   │                                                                          │     │     │
│   │   │   PolicyService │ ClaimsService │ BillingService │ UnderwritingService  │     │     │
│   │   │   AuditService  │ MetricsService │ MarketDataService                    │     │     │
│   │   └─────────────────────────────────────────────────────────────────────────┘     │     │
│   │                                                                                    │     │
│   │   ┌─────────────────────────────────────────────────────────────────────────┐     │     │
│   │   │                    SQLAlchemy ORM + Repositories                         │     │     │
│   │   │                                                                          │     │     │
│   │   │   Connection Pool (20 + 10 overflow) │ Transaction Management            │     │     │
│   │   └─────────────────────────────────────────────────────────────────────────┘     │     │
│   │                                                                                    │     │
│   └───────────────────────────────────────────────────────────────────────────────────┘     │
│                                                                                              │
│   Environment Variables:                                                                     │
│   ├── DATABASE_URL      (PostgreSQL connection string)                                       │
│   ├── SECRET_KEY        (Flask session secret)                                              │
│   ├── VAULT_KEY         (Encryption master key)                                             │
│   └── PORT              (Server port, default 8080)                                         │
│                                                                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                                │
                                                │ PostgreSQL Protocol (5432)
                                                ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   DATABASE SERVER                                            │
│                                    (PostgreSQL)                                              │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐       │
│   │                           PHINS Database                                         │       │
│   │                                                                                  │       │
│   │   Schema: public                                                                 │       │
│   │   ├── customers                (Customer master data)                            │       │
│   │   ├── policies                 (Insurance policies)                              │       │
│   │   ├── claims                   (Insurance claims)                                │       │
│   │   ├── bills                    (Billing/invoices)                                │       │
│   │   ├── underwriting_applications (UW workflow)                                    │       │
│   │   ├── users                    (Staff accounts)                                  │       │
│   │   ├── sessions                 (Active sessions)                                 │       │
│   │   ├── audit_logs               (Audit trail)                                     │       │
│   │   ├── actuarial_tables         (Actuarial data, encrypted)                       │       │
│   │   └── token_registry           (Supported tokens/currencies)                     │       │
│   │                                                                                  │       │
│   │   Features:                                                                      │       │
│   │   • ACID compliance                                                              │       │
│   │   • Foreign key constraints                                                      │       │
│   │   • Cascade deletes                                                              │       │
│   │   • Index optimization                                                           │       │
│   │   • Connection pooling                                                           │       │
│   └─────────────────────────────────────────────────────────────────────────────────┘       │
│                                                                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Security Model

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 SECURITY ARCHITECTURE                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  AUTHENTICATION FLOW                                          │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                               │
│   User/Customer                    Web Portal                         Database                │
│        │                              │                                  │                    │
│        │   1. Login Request           │                                  │                    │
│        │   (username/password)        │                                  │                    │
│        ├─────────────────────────────▶│                                  │                    │
│        │                              │                                  │                    │
│        │                              │  2. Query User                   │                    │
│        │                              ├─────────────────────────────────▶│                    │
│        │                              │                                  │                    │
│        │                              │  3. User Record                  │                    │
│        │                              │◀─────────────────────────────────┤                    │
│        │                              │  (password_hash, salt)           │                    │
│        │                              │                                  │                    │
│        │                              │  4. PBKDF2-HMAC-SHA256           │                    │
│        │                              │     Verify Password              │                    │
│        │                              │                                  │                    │
│        │                              │  5. Generate Session Token       │                    │
│        │                              │     (secrets.token_hex)          │                    │
│        │                              │                                  │                    │
│        │                              │  6. Store Session                │                    │
│        │                              ├─────────────────────────────────▶│                    │
│        │                              │                                  │                    │
│        │   7. Session Token           │                                  │                    │
│        │◀─────────────────────────────┤                                  │                    │
│        │   (HTTP-only cookie)         │                                  │                    │
│        │                              │                                  │                    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA CLASSIFICATION & ENCRYPTION                                 │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                               │
│   Classification Levels:                                                                      │
│   ├── PUBLIC        - Non-sensitive, can be shared externally                                │
│   ├── INTERNAL      - Internal use only, not for external sharing                            │
│   ├── CONFIDENTIAL  - Sensitive business data, limited access                                │
│   └── RESTRICTED    - Highly sensitive (actuarial tables, PII)                               │
│                                                                                               │
│   Encryption (security/vault.py):                                                            │
│   ├── Algorithm: Fernet (AES-128-CBC with HMAC-SHA256)                                       │
│   ├── Key Derivation: PBKDF2-HMAC-SHA256 (100,000 iterations)                                │
│   └── Usage: Actuarial table payloads, sensitive configuration                               │
│                                                                                               │
│   Password Storage:                                                                           │
│   ├── Hash: PBKDF2-HMAC-SHA256                                                               │
│   ├── Salt: Random per-user (stored in password_salt)                                        │
│   └── Iterations: 100,000+                                                                   │
│                                                                                               │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  ROLE-BASED ACCESS CONTROL                                    │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                               │
│   Role: admin                                                                                 │
│   ├── Full system access                                                                     │
│   ├── User management                                                                        │
│   ├── System configuration                                                                   │
│   └── All data access                                                                        │
│                                                                                               │
│   Role: underwriter                                                                           │
│   ├── View/approve/reject underwriting applications                                          │
│   ├── View customer and policy data                                                          │
│   └── Risk assessment                                                                        │
│                                                                                               │
│   Role: claims                                                                                │
│   ├── View/approve/reject claims                                                             │
│   ├── View customer and policy data                                                          │
│   └── Process claim payments                                                                 │
│                                                                                               │
│   Role: accountant                                                                            │
│   ├── Billing management                                                                     │
│   ├── Payment processing                                                                     │
│   ├── Financial reports                                                                      │
│   └── View customer data                                                                     │
│                                                                                               │
│   Role: customer (portal access)                                                              │
│   ├── View own policies                                                                      │
│   ├── View own claims                                                                        │
│   ├── View own bills                                                                         │
│   ├── Submit new applications                                                                │
│   └── File claims                                                                            │
│                                                                                               │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Summary Statistics

| Component | Count | Description |
|-----------|-------|-------------|
| Database Tables | 10 | Core data entities |
| ORM Models | 10 | SQLAlchemy model classes |
| Repositories | 10 | Data access layer classes |
| Services | 7 | Business logic services |
| Enumerations | 6 | Status/type definitions |
| API Endpoints | ~30+ | REST API routes |
| Web Portals | 5 | User interface dashboards |

---

## Document Information

- **Platform**: PHINS Insurance Platform
- **Database**: PostgreSQL (production) / SQLite (development)
- **ORM**: SQLAlchemy 2.x
- **Architecture**: 3-Tier (Presentation → Application → Data)
- **Pattern**: Repository Pattern with Service Layer

---

*Generated: December 2024*
