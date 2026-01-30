# PHINS Supply Chain Ecosystem Architecture

## Executive Summary

The PHINS Supply Chain Ecosystem is an invitation-only B2B marketplace that connects healthcare providers, legal services, pharmacies, and delivery partners with insurance customers. The system features adjustable management fees (default 11% commission), full health wallet integration, and enterprise-grade data integrity through cryptographic ledgers and NFT token verification.

---

## System Overview

```
+------------------------------------------------------------------+
|                   PHINS SUPPLY CHAIN ECOSYSTEM                    |
+------------------------------------------------------------------+
|                                                                   |
|  +--------------------+    +--------------------+                 |
|  |   ADMIN PORTAL     |    |  SUPPLIER PORTAL   |                 |
|  |                    |    |                    |                 |
|  | - Invite Suppliers |    | - Register (Invite)|                 |
|  | - Approve/Reject   |    | - Manage Offers    |                 |
|  | - Fee Management   |    | - View Orders      |                 |
|  | - Analytics & BI   |    | - P&L Reports      |                 |
|  | - Settlement Ops   |    | - Settlement Info  |                 |
|  +--------------------+    +--------------------+                 |
|            |                        |                             |
|            v                        v                             |
|  +----------------------------------------------------------+    |
|  |              SUPPLY CHAIN ECOSYSTEM SERVICE               |    |
|  |                                                           |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  | | Invitation    |  | Fee Schedule  |  | Order         |   |    |
|  | | Management    |  | Management    |  | Processing    |   |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  |                                                           |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  | | Supplier      |  | Settlement    |  | P&L Reports   |   |    |
|  | | Registry      |  | Engine        |  | Generator     |   |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  +----------------------------------------------------------+    |
|            |                        |                             |
|            v                        v                             |
|  +----------------------------------------------------------+    |
|  |                   DATA INTEGRITY LAYER                    |    |
|  |                                                           |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  | | Cryptographic |  | NFT Token     |  | Transaction   |   |    |
|  | | Ledger        |  | Registry      |  | Ledger        |   |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  +----------------------------------------------------------+    |
|            |                        |                             |
|            v                        v                             |
|  +----------------------------------------------------------+    |
|  |                   INTEGRATION LAYER                       |    |
|  |                                                           |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  | | Health        |  | Billing       |  | Marketplace   |   |    |
|  | | Wallets       |  | System        |  | Service       |   |    |
|  | +---------------+  +---------------+  +---------------+   |    |
|  +----------------------------------------------------------+    |
|                                                                   |
+------------------------------------------------------------------+
```

---

## UML Diagrams

### 1. Supplier Registration Process (Sequence Diagram)

```
┌─────────┐      ┌─────────┐      ┌────────────┐      ┌─────────┐      ┌────────┐
│  Admin  │      │Supplier │      │Supply Chain│      │ Ledger  │      │  NFT   │
│ Portal  │      │ Portal  │      │  Service   │      │ Store   │      │Registry│
└────┬────┘      └────┬────┘      └─────┬──────┘      └────┬────┘      └───┬────┘
     │                │                  │                  │               │
     │ Generate       │                  │                  │               │
     │ Invitation     │                  │                  │               │
     │───────────────────────────────────>                  │               │
     │                │                  │                  │               │
     │                │                  │ Create Code      │               │
     │                │                  │──────────────────>               │
     │                │                  │                  │               │
     │<──────────────────────────────────│                  │               │
     │ Return Code:   │                  │                  │               │
     │ PHINS-SUP-XXX  │                  │                  │               │
     │                │                  │                  │               │
     │ Send Invite    │                  │                  │               │
     │ (Email/B2B)    │                  │                  │               │
     │────────────────>                  │                  │               │
     │                │                  │                  │               │
     │                │ Register with    │                  │               │
     │                │ Invitation Code  │                  │               │
     │                │─────────────────>│                  │               │
     │                │                  │                  │               │
     │                │                  │ Validate Code    │               │
     │                │                  │──────────────────>               │
     │                │                  │<─────────────────│               │
     │                │                  │                  │               │
     │                │                  │ AI Risk          │               │
     │                │                  │ Assessment       │               │
     │                │                  │────────┐         │               │
     │                │                  │        │         │               │
     │                │                  │<───────┘         │               │
     │                │                  │                  │               │
     │                │                  │ Create Supplier  │               │
     │                │                  │ Record           │               │
     │                │                  │──────────────────>               │
     │                │                  │                  │               │
     │                │                  │ Record on        │               │
     │                │                  │ Ledger           │               │
     │                │                  │──────────────────>               │
     │                │                  │                  │               │
     │                │                  │ Mint NFT Token   │               │
     │                │                  │──────────────────────────────────>
     │                │                  │                  │               │
     │                │<─────────────────│                  │               │
     │                │ Registration     │                  │               │
     │                │ Complete         │                  │               │
     │                │ (Pending Approval)                  │               │
     │                │                  │                  │               │
     │ Review         │                  │                  │               │
     │ Notification   │                  │                  │               │
     │<──────────────────────────────────│                  │               │
     │                │                  │                  │               │
     │ Approve        │                  │                  │               │
     │───────────────────────────────────>                  │               │
     │                │                  │                  │               │
     │                │                  │ Update Status    │               │
     │                │                  │──────────────────>               │
     │                │                  │                  │               │
     │                │                  │ Record Approval  │               │
     │                │                  │──────────────────>               │
     │                │                  │                  │               │
     │                │<─────────────────────────────────────               │
     │                │ Approval         │                  │               │
     │                │ Notification     │                  │               │
     │                │                  │                  │               │
```

### 2. Order Processing with Health Wallet (Sequence Diagram)

```
┌─────────┐   ┌─────────┐   ┌────────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│Customer │   │Marketplace   │Supply Chain│   │ Health │   │ Ledger │   │Supplier│
│ Portal  │   │ Service │   │  Service   │   │ Wallet │   │        │   │        │
└────┬────┘   └────┬────┘   └─────┬──────┘   └───┬────┘   └───┬────┘   └───┬────┘
     │             │              │               │            │            │
     │ Browse      │              │               │            │            │
     │ Marketplace │              │               │            │            │
     │────────────>│              │               │            │            │
     │             │              │               │            │            │
     │<────────────│              │               │            │            │
     │ Display     │              │               │            │            │
     │ Offers      │              │               │            │            │
     │             │              │               │            │            │
     │ Select      │              │               │            │            │
     │ Service     │              │               │            │            │
     │────────────>│              │               │            │            │
     │             │              │               │            │            │
     │             │ Create Order │               │            │            │
     │             │─────────────>│               │            │            │
     │             │              │               │            │            │
     │             │              │ Calculate     │            │            │
     │             │              │ Fees (11%)    │            │            │
     │             │              │───────┐       │            │            │
     │             │              │       │       │            │            │
     │             │              │<──────┘       │            │            │
     │             │              │               │            │            │
     │             │              │ Check Balance │            │            │
     │             │              │──────────────>│            │            │
     │             │              │               │            │            │
     │             │              │<──────────────│            │            │
     │             │              │ Balance: $500 │            │            │
     │             │              │               │            │            │
     │             │              │ Deduct Amount │            │            │
     │             │              │──────────────>│            │            │
     │             │              │               │            │            │
     │             │              │ Record Order  │            │            │
     │             │              │───────────────────────────>│            │
     │             │              │               │            │            │
     │             │              │ Generate NFT  │            │            │
     │             │              │───────────────────────────>│            │
     │             │              │               │            │            │
     │             │              │ Notify        │            │            │
     │             │              │───────────────────────────────────────>│
     │             │              │               │            │            │
     │             │<─────────────│               │            │            │
     │<────────────│              │               │            │            │
     │ Order       │              │               │            │            │
     │ Confirmed   │              │               │            │            │
     │             │              │               │            │            │
     │             │              │               │            │ Fulfill    │
     │             │              │               │            │<───────────│
     │             │              │               │            │            │
     │             │              │ Complete Order│            │            │
     │             │              │<──────────────────────────────────────│
     │             │              │               │            │            │
     │             │              │ Add to        │            │            │
     │             │              │ Settlement    │            │            │
     │             │              │───────────────────────────>│            │
     │             │              │               │            │            │
     │<────────────────────────────               │            │            │
     │ Order       │              │               │            │            │
     │ Complete    │              │               │            │            │
```

### 3. Fee Calculation and Settlement (Class Diagram)

```
┌─────────────────────────────────────────────────────────────────┐
│                         FeeSchedule                              │
├─────────────────────────────────────────────────────────────────┤
│ - base_commission_pct: float = 11.0                             │
│ - category_adjustments: Dict[str, float]                        │
│ - volume_discounts: List[Dict]                                  │
│ - promotional_rates: List[Dict]                                 │
│ - minimum_fee: float = 1.0                                      │
│ - maximum_fee_pct: float = 25.0                                 │
├─────────────────────────────────────────────────────────────────┤
│ + calculate_commission(amount, supplier_type, volume, promo)    │
│   -> {base_rate, volume_discount, promo_discount,               │
│       effective_rate, commission, supplier_payout}              │
└─────────────────────────────────────────────────────────────────┘
                               │
                               │ uses
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Category Commission Rates                      │
├─────────────────────────────────────────────────────────────────┤
│ DOCTOR:        8%   │ Lower rate for medical providers          │
│ LAWYER:       12%   │ Standard legal services rate              │
│ PHARMACY:      9%   │ Regulated product margins                 │
│ DELIVERY:     15%   │ Logistics services rate                   │
│ HOSPITAL:      6%   │ Lowest for healthcare institutions        │
│ CLINIC:        8%   │ Same as doctor rate                       │
│ LABORATORY:   10%   │ Diagnostic services                       │
│ EQUIPMENT:    12%   │ Medical equipment sales                   │
│ WELLNESS:     14%   │ Wellness programs                         │
│ FINANCIAL:     5%   │ Investment services (lowest)              │
│ TECH:         15%   │ Technology providers                      │
│ OTHER:        11%   │ Default rate                              │
└─────────────────────────────────────────────────────────────────┘
                               │
                               │ applied to
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Volume Discounts                          │
├─────────────────────────────────────────────────────────────────┤
│ Monthly Volume >= $10,000   -> 1% discount                      │
│ Monthly Volume >= $50,000   -> 2% discount                      │
│ Monthly Volume >= $100,000  -> 3% discount                      │
│ Monthly Volume >= $500,000  -> 5% discount                      │
└─────────────────────────────────────────────────────────────────┘
```

### 4. Supplier P&L Report Structure (Class Diagram)

```
┌─────────────────────────────────────────────────────────────────┐
│                     SupplierPnLReport                            │
├─────────────────────────────────────────────────────────────────┤
│ IDENTIFICATION                                                   │
│ - supplier_id: str                                               │
│ - period_start: str                                              │
│ - period_end: str                                                │
├─────────────────────────────────────────────────────────────────┤
│ REVENUE                                                          │
│ - gross_sales: float                                             │
│ - refunds: float                                                 │
│ - net_sales: float (gross - refunds)                            │
├─────────────────────────────────────────────────────────────────┤
│ DEDUCTIONS                                                       │
│ - platform_commission: float                                     │
│ - payment_processing_fees: float (2.5%)                         │
│ - other_fees: float                                              │
│ - total_deductions: float                                        │
├─────────────────────────────────────────────────────────────────┤
│ PAYOUTS                                                          │
│ - net_payout: float                                              │
│ - pending_settlement: float                                      │
│ - settled_amount: float                                          │
├─────────────────────────────────────────────────────────────────┤
│ METRICS                                                          │
│ - total_orders: int                                              │
│ - completed_orders: int                                          │
│ - cancelled_orders: int                                          │
│ - average_order_value: float                                     │
│ - commission_rate_avg: float                                     │
├─────────────────────────────────────────────────────────────────┤
│ PERFORMANCE                                                      │
│ - delivery_on_time_pct: float                                    │
│ - customer_rating_avg: float                                     │
│ - dispute_rate_pct: float                                        │
├─────────────────────────────────────────────────────────────────┤
│ INTEGRITY                                                        │
│ - generated_at: str                                              │
│ - hash_signature: str (HMAC-SHA256)                             │
└─────────────────────────────────────────────────────────────────┘
```

### 5. Data Integrity Flow (Activity Diagram)

```
                        ┌─────────────────┐
                        │ Transaction     │
                        │ Initiated       │
                        └────────┬────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Create Ledger Entry    │
                    │ - entry_id             │
                    │ - timestamp            │
                    │ - entry_type           │
                    │ - amount, commission   │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Get Previous Hash      │
                    │ from Ledger Chain      │
                    │ (or "GENESIS" if first)│
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Calculate Entry Hash   │
                    │ HMAC-SHA256(          │
                    │   entry_data +         │
                    │   previous_hash +      │
                    │   secret_key           │
                    │ )                      │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Generate NFT Token     │
                    │ NFT-SCL-XXXXXX         │
                    └────────────┬───────────┘
                                 │
                    ┌────────────┴───────────┐
                    │                        │
                    ▼                        ▼
        ┌────────────────────┐    ┌────────────────────┐
        │ Store in Ledger    │    │ Store in NFT       │
        │ {entry_id: entry}  │    │ Registry           │
        └────────────┬───────┘    └────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │ Append Hash to         │
        │ Ledger Chain           │
        │ ledger_chain.append()  │
        └────────────┬───────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │ Transaction Complete   │
        │ with Integrity Token   │
        └────────────────────────┘
```

### 6. B2B/B2C Order Flow (State Diagram)

```
                              ┌─────────────┐
                              │   PENDING   │
                              └──────┬──────┘
                                     │
                         ┌───────────┴───────────┐
                         │                       │
                         ▼                       ▼
              ┌──────────────────┐    ┌──────────────────┐
              │    CONFIRMED     │    │    CANCELLED     │
              │  (Payment OK)    │    │  (By Customer)   │
              └────────┬─────────┘    └──────────────────┘
                       │
                       ▼
              ┌──────────────────┐
              │   PROCESSING     │
              │ (Supplier Prep)  │
              └────────┬─────────┘
                       │
           ┌───────────┴───────────┐
           │                       │
           ▼                       ▼
┌──────────────────┐    ┌──────────────────┐
│   IN_TRANSIT     │    │   IN_PROGRESS    │
│   (Products)     │    │   (Services)     │
└────────┬─────────┘    └────────┬─────────┘
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
              ┌──────────────────┐
              │    DELIVERED     │
              │ (Received/Done)  │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │    COMPLETED     │──────────┐
              │ (Rated/Settled)  │          │
              └──────────────────┘          │
                                            │
                                            ▼
                                 ┌──────────────────┐
                                 │  ADD TO PENDING  │
                                 │   SETTLEMENT     │
                                 └──────────────────┘
```

### 7. Multi-Process Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHINS INSURANCE PLATFORM                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         CUSTOMER LAYER                               │    │
│  │                                                                      │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │    │
│  │  │ Policies   │  │ Claims     │  │ Health     │  │ Marketplace│    │    │
│  │  │            │  │            │  │ Wallet     │  │ Browse     │    │    │
│  │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘    │    │
│  └────────┼───────────────┼───────────────┼───────────────┼───────────┘    │
│           │               │               │               │                 │
│           └───────────────┴───────┬───────┴───────────────┘                 │
│                                   │                                          │
│                                   ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                       BUSINESS LOGIC LAYER                           │    │
│  │                                                                      │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │    │
│  │  │ Policy     │  │ Claims     │  │ Billing    │  │ Supply     │    │    │
│  │  │ Service    │  │ Service    │  │ Service    │  │ Chain Svc  │    │    │
│  │  └────────────┘  └────────────┘  └────────────┘  └─────┬──────┘    │    │
│  │                                                         │           │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐        │           │    │
│  │  │ Underwrite │  │ Portfolio  │  │ Savings    │        │           │    │
│  │  │ Service    │  │ Tracker    │  │ Pipeline   │        │           │    │
│  │  └────────────┘  └────────────┘  └────────────┘        │           │    │
│  └────────────────────────────────────────────────────────┼───────────┘    │
│                                                            │                 │
│                                                            ▼                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    SUPPLY CHAIN ECOSYSTEM                            │    │
│  │                                                                      │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │                   INVITATION MANAGEMENT                        │  │    │
│  │  │  - Generate invitation codes                                   │  │    │
│  │  │  - Validate codes for registration                            │  │    │
│  │  │  - Track referrals and special rates                          │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  │                                                                      │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │                   SUPPLIER REGISTRY                            │  │    │
│  │  │  Types: Doctor | Lawyer | Pharmacy | Delivery | Hospital |    │  │    │
│  │  │         Clinic | Laboratory | Equipment | Wellness | Financial│  │    │
│  │  │                                                                │  │    │
│  │  │  Status: Pending -> Under Review -> Approved/Rejected         │  │    │
│  │  │                                     -> Suspended/Terminated   │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  │                                                                      │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │                   FEE SCHEDULE ENGINE                          │  │    │
│  │  │  Base Commission: 11% (adjustable per category)               │  │    │
│  │  │  Volume Discounts: 1-5% based on monthly volume               │  │    │
│  │  │  Promotional Rates: Special codes and campaigns               │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  │                                                                      │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │                   ORDER PROCESSING                             │  │    │
│  │  │  1. Customer selects offer from marketplace                   │  │    │
│  │  │  2. Calculate fees and deduct from health wallet              │  │    │
│  │  │  3. Create order with NFT token                               │  │    │
│  │  │  4. Notify supplier                                           │  │    │
│  │  │  5. Track fulfillment                                         │  │    │
│  │  │  6. Complete and add to settlement queue                      │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  │                                                                      │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │                   SETTLEMENT ENGINE                            │  │    │
│  │  │  Frequency: Daily | Weekly | Bi-Weekly | Monthly              │  │    │
│  │  │  - Aggregate completed orders                                 │  │    │
│  │  │  - Deduct commissions                                         │  │    │
│  │  │  - Process payout to supplier                                 │  │    │
│  │  │  - Record on ledger                                           │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  │                                                                      │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │                   REPORTING & ANALYTICS                        │  │    │
│  │  │  - Supplier P&L Reports (gross, commission, net payout)       │  │    │
│  │  │  - B2B vs B2C Statistics                                      │  │    │
│  │  │  - Delivery Performance Metrics                               │  │    │
│  │  │  - Platform-wide Analytics                                    │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     DATA INTEGRITY LAYER                             │    │
│  │                                                                      │    │
│  │  ┌────────────────────┐  ┌────────────────────┐  ┌───────────────┐  │    │
│  │  │ Cryptographic      │  │ NFT Token          │  │ Transaction   │  │    │
│  │  │ Ledger             │  │ Registry           │  │ Ledger        │  │    │
│  │  │                    │  │                    │  │               │  │    │
│  │  │ - Hash chains      │  │ - Ownership proof  │  │ - All txns    │  │    │
│  │  │ - HMAC-SHA256      │  │ - Authenticity     │  │ - Audit trail │  │    │
│  │  │ - Immutable        │  │ - Transfer history │  │ - P&L source  │  │    │
│  │  └────────────────────┘  └────────────────────┘  └───────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         STORAGE LAYER                                │    │
│  │                                                                      │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │    │
│  │  │ Suppliers  │  │ Invitations│  │ Orders     │  │ Offers     │    │    │
│  │  │ Store      │  │ Store      │  │ Store      │  │ Store      │    │    │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘    │    │
│  │                                                                      │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │    │
│  │  │ Health     │  │ Billing    │  │ NFT        │  │ Ledger     │    │    │
│  │  │ Wallets    │  │ Records    │  │ Registry   │  │ Entries    │    │    │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘    │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## API Endpoints Summary

### Admin Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/supply-chain/invitations` | POST | Generate invitation code |
| `/api/supply-chain/invitations` | GET | List all invitation codes |
| `/api/supply-chain/invitations/{code}/revoke` | POST | Revoke an invitation |
| `/api/supply-chain/suppliers/pending` | GET | List pending suppliers |
| `/api/supply-chain/suppliers/{id}/approve` | POST | Approve supplier |
| `/api/supply-chain/suppliers/{id}/reject` | POST | Reject supplier |
| `/api/supply-chain/fee-schedule` | GET/PUT | View/Update fee schedule |
| `/api/supply-chain/settlements` | GET | View pending settlements |
| `/api/supply-chain/settlements/{supplier_id}` | POST | Process settlement |
| `/api/supply-chain/analytics` | GET | Platform analytics |
| `/api/supply-chain/ledger/verify` | GET | Verify ledger integrity |

### Supplier Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/supply-chain/register` | POST | Register with invitation |
| `/api/supply-chain/supplier/login` | POST | Supplier authentication |
| `/api/supply-chain/supplier/offers` | GET/POST | List/Create offers |
| `/api/supply-chain/supplier/orders` | GET | View supplier orders |
| `/api/supply-chain/supplier/statistics` | GET | Supplier statistics |
| `/api/supply-chain/supplier/pnl` | GET | Generate P&L report |
| `/api/supply-chain/supplier/settlement` | GET | View pending settlement |

### Customer/Marketplace Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/marketplace/offers` | GET | Browse marketplace offers |
| `/api/marketplace/offers/{category}` | GET | Browse by category |
| `/api/marketplace/order` | POST | Place an order |
| `/api/marketplace/orders` | GET | Customer order history |

---

## Data Integrity Model

### Ledger Entry Structure

```json
{
  "entry_id": "SCL-20260128-ABCD1234",
  "timestamp": "2026-01-28T12:00:00Z",
  "entry_type": "order_completed",
  "supplier_id": "SUP-202601-XXXX",
  "customer_id": "CUST-001",
  "order_id": "ORD-20260128-YYYY",
  "amount": 150.00,
  "commission": 16.50,
  "supplier_payout": 133.50,
  "currency": "USD",
  "description": "Order completed: Medical Consultation",
  "metadata": {
    "offer_id": "OFF-001",
    "is_b2b": false,
    "nft_token_id": "NFT-ORD-ZZZZ"
  },
  "previous_hash": "a1b2c3d4e5f6...",
  "entry_hash": "f6e5d4c3b2a1...",
  "nft_token_id": "NFT-SCL-WWWW",
  "verified": true
}
```

### Hash Chain Verification

```
Entry 1 (Genesis)
  └── hash_1 = HMAC(data_1 + "GENESIS" + secret)

Entry 2
  └── hash_2 = HMAC(data_2 + hash_1 + secret)

Entry 3
  └── hash_3 = HMAC(data_3 + hash_2 + secret)

...

Entry N
  └── hash_N = HMAC(data_N + hash_(N-1) + secret)
```

---

## Security Considerations

1. **Invitation Codes**: Single-use or limited-use codes with expiration
2. **Password Hashing**: SHA-256 with random salt per supplier
3. **Ledger Integrity**: HMAC-SHA256 hash chains for tamper detection
4. **NFT Verification**: Authenticity tokens for all transactions
5. **Role-Based Access**: Admin, Supplier, Customer role separation
6. **Data Isolation**: Suppliers can only access their own data

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 1.0 | 2026-01-15 | Initial supplier management |
| 2.0 | 2026-01-28 | Full supply chain ecosystem with invitation-only B2B |

---

*Document generated: January 28, 2026*
*PHINS Engineering Team*
