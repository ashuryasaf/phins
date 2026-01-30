# PHINS Supplier Marketplace Pipeline - Data Integrity & Flow Documentation

## Overview

This document describes the complete data pipeline flow for the PHINS B2B Supplier Marketplace, ensuring proper access controls, data isolation, and integrity across all three perspectives: **Supplier**, **Customer**, and **Admin**.

## Key Principles

1. **Unique Credentials**: Each supplier has unique login credentials (email/password)
2. **Data Isolation**: Suppliers can only access their own data (offers, orders, profile)
3. **Approval Workflow**: Suppliers must be approved before their offerings appear in marketplace
4. **Wallet Integration**: Customers purchase from Health Wallet; transactions are tracked
5. **Admin Oversight**: Full macro view of all transactions, suppliers, and wallets

---

## UML Sequence Diagram: Supplier Application to Customer Purchase

```
┌─────────────┐       ┌──────────────┐       ┌────────────┐       ┌────────────┐       ┌─────────────┐
│  Supplier   │       │    Server    │       │   Admin    │       │  Customer  │       │  Database   │
└──────┬──────┘       └──────┬───────┘       └─────┬──────┘       └─────┬──────┘       └──────┬──────┘
       │                     │                     │                     │                     │
       │  1. Register        │                     │                     │                     │
       │  ─────────────────► │                     │                     │                     │
       │  POST /api/supplier/register              │                     │                     │
       │  {company_name, email, password, type}    │                     │                     │
       │                     │                     │                     │                     │
       │                     │  2. AI Risk Assessment                    │                     │
       │                     │  ─────────────────────────────────────────────────────────────► │
       │                     │  Store: status='pending', ai_score, ai_recommendation           │
       │                     │                     │                     │                     │
       │  3. Return supplier_id                    │                     │                     │
       │  ◄───────────────── │                     │                     │                     │
       │                     │                     │                     │                     │
       │                     │  4. Pending Alert   │                     │                     │
       │                     │  ─────────────────► │                     │                     │
       │                     │  (Admin Dashboard   │                     │                     │
       │                     │   shows pending)    │                     │                     │
       │                     │                     │                     │                     │
       │                     │  5. Review & Approve│                     │                     │
       │                     │  ◄───────────────── │                     │                     │
       │                     │  POST /api/admin/suppliers/{id}/approve   │                     │
       │                     │                     │                     │                     │
       │                     │  6. Update Status   │                     │                     │
       │                     │  ──────────────────────────────────────────────────────────────►│
       │                     │  status='approved', portal_active=true    │                     │
       │                     │                     │                     │                     │
       │  7. Login (now works)                     │                     │                     │
       │  ─────────────────► │                     │                     │                     │
       │  POST /api/supplier/login                 │                     │                     │
       │                     │                     │                     │                     │
       │  8. Session Token   │                     │                     │                     │
       │  ◄───────────────── │                     │                     │                     │
       │  {token, supplier_id, role='supplier'}    │                     │                     │
       │                     │                     │                     │                     │
       │  9. Create Offer    │                     │                     │                     │
       │  ─────────────────► │                     │                     │                     │
       │  POST /api/supplier/offers/upsert         │                     │                     │
       │  {name, price, category, wallet_compatible}                     │                     │
       │                     │                     │                     │                     │
       │                     │  10. Store Offer    │                     │                     │
       │                     │  ──────────────────────────────────────────────────────────────►│
       │                     │  SUPPLIER_OFFERS[offer_id] = {..., supplier_id, active: true}   │
       │                     │                     │                     │                     │
       │                     │                     │                     │                     │
       │                     │                     │  11. Browse Marketplace                   │
       │                     │                     │  ◄──────────────────│                     │
       │                     │                     │  GET /api/marketplace/offerings           │
       │                     │                     │  ?category=devices&wallet=health          │
       │                     │                     │                     │                     │
       │                     │  12. Filter: approved suppliers only      │                     │
       │                     │  ◄──────────────────────────────────────────────────────────────│
       │                     │  Returns enriched offers with supplier info                     │
       │                     │                     │                     │                     │
       │                     │                     │  13. Display in Health Wallet             │
       │                     │                     │  ────────────────────►                    │
       │                     │                     │  (Dashboard shows products/services)      │
       │                     │                     │                     │                     │
       │                     │                     │  14. Add to Cart & Purchase               │
       │                     │  ◄──────────────────────────────────────── │                     │
       │                     │  POST /api/marketplace/product/purchase   │                     │
       │                     │  {customer_id, product_id, quantity}      │                     │
       │                     │                     │                     │                     │
       │                     │  15. Create Transaction                   │                     │
       │                     │  ──────────────────────────────────────────────────────────────►│
       │                     │  - Deduct from customer wallet            │                     │
       │                     │  - Create order record                    │                     │
       │                     │  - Generate NFT receipt                   │                     │
       │                     │  - Calculate supplier payout              │                     │
       │                     │  - Calculate platform fee                 │                     │
       │                     │                     │                     │                     │
       │  16. Order Notification                   │                     │                     │
       │  ◄───────────────── │                     │                     │                     │
       │  (Supplier portal shows new order)        │                     │                     │
       │                     │                     │                     │                     │
       │                     │  17. Admin sees transaction               │                     │
       │                     │  ─────────────────► │                     │                     │
       │                     │  (Marketplace Division dashboard)         │                     │
       │                     │                     │                     │                     │
       └──────┬──────┘       └──────┬───────┘       └─────┬──────┘       └─────┬──────┘       └──────┬──────┘
```

---

## Data Flow Diagram: Access Control Matrix

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                           PHINS ACCESS CONTROL MATRIX                                     │
├────────────────────┬──────────────────┬───────────────────┬──────────────────────────────┤
│  RESOURCE          │  SUPPLIER        │  CUSTOMER         │  ADMIN                       │
├────────────────────┼──────────────────┼───────────────────┼──────────────────────────────┤
│ Own Profile        │ ✅ Read/Update   │ ✅ Read/Update    │ ✅ Read All                  │
│ Own Offers         │ ✅ CRUD          │ ❌ N/A            │ ✅ Read/Approve/Delete All   │
│ Other Offers       │ ❌ N/A           │ ✅ Read (approved)│ ✅ Read All                  │
│ Own Orders         │ ✅ Read/Update   │ ✅ Read           │ ✅ Read All                  │
│ All Orders         │ ❌ N/A           │ ❌ N/A            │ ✅ Read All                  │
│ Own Wallet         │ ❌ N/A           │ ✅ Read/Transact  │ ✅ Read All                  │
│ All Wallets        │ ❌ N/A           │ ❌ N/A            │ ✅ Read All                  │
│ Supplier List      │ ❌ N/A           │ ✅ Read (approved)│ ✅ CRUD All                  │
│ Analytics          │ ✅ Own stats     │ ✅ Own activity   │ ✅ Platform-wide             │
│ Settlements        │ ✅ Own           │ ❌ N/A            │ ✅ Process All               │
│ Fee Schedule       │ ❌ Read only     │ ❌ N/A            │ ✅ CRUD                      │
└────────────────────┴──────────────────┴───────────────────┴──────────────────────────────┘
```

---

## Pipeline State Diagram

```
                              ┌─────────────────────────────────────────────┐
                              │           SUPPLIER LIFECYCLE                 │
                              └─────────────────────────────────────────────┘

    ┌──────────┐      AI Risk      ┌───────────────┐     Admin      ┌───────────────┐
    │ REGISTER │ ────Assessment───►│    PENDING    │ ───Review────►│   APPROVED    │
    └──────────┘                   └───────────────┘                └───────┬───────┘
                                           │                                │
                                           │ Auto-Reject                    │ Violation
                                           │ (risk > 0.7)                   │ detected
                                           ▼                                ▼
                                   ┌───────────────┐               ┌───────────────┐
                                   │   REJECTED    │               │   SUSPENDED   │
                                   └───────────────┘               └───────┬───────┘
                                                                           │
                                                                           │ Reactivate
                                                                           │ (Admin)
                                                                           ▼
                                                                    ┌─────────────┐
                                                                    │ RE-APPROVED │
                                                                    └─────────────┘


                              ┌─────────────────────────────────────────────┐
                              │             OFFER LIFECYCLE                  │
                              └─────────────────────────────────────────────┘

    ┌───────────────┐       Supplier       ┌───────────────┐      Supplier     ┌───────────────┐
    │    CREATE     │ ─────uploads────────►│    ACTIVE     │ ───deactivates───►│   INACTIVE    │
    └───────────────┘                      └───────┬───────┘                   └───────────────┘
                                                   │                                   │
                                                   │ Visible to                        │ Not visible
                                                   │ customers                         │ to customers
                                                   ▼                                   │
                                            ┌─────────────┐                            │
                                            │ MARKETPLACE │◄───────reactivate──────────┘
                                            └─────────────┘


                              ┌─────────────────────────────────────────────┐
                              │              ORDER LIFECYCLE                 │
                              └─────────────────────────────────────────────┘

    ┌─────────────┐    Supplier     ┌─────────────┐    Supplier     ┌─────────────┐
    │   PENDING   │ ──confirms────►│  CONFIRMED  │ ───starts──────►│ PROCESSING  │
    └─────────────┘                └─────────────┘                  └──────┬──────┘
          │                                                                │
          │ Customer                                                       │ Supplier
          │ cancels                                                        │ completes
          ▼                                                                ▼
    ┌─────────────┐                                                 ┌─────────────┐
    │  CANCELLED  │                                                 │  COMPLETED  │
    └─────────────┘                                                 └─────────────┘
                                                                           │
                                                                           │ Triggers
                                                                           │ settlement
                                                                           ▼
                                                                    ┌─────────────┐
                                                                    │ SETTLEMENT  │
                                                                    │   PENDING   │
                                                                    └─────────────┘
```

---

## Database Schema: Key Entities

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              SUPPLIERS TABLE                                             │
├─────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ id              │ SUP-YYYYMM-XXXXXXXX (unique supplier ID)                                │
│ company_name    │ Legal business name                                                     │
│ contact_email   │ Unique email (used for login)                                           │
│ password_hash   │ SHA256(password + salt)                                                 │
│ password_salt   │ Random 32-byte salt                                                     │
│ supplier_type   │ healthcare_provider, pharmacy, legal_service, delivery, etc.            │
│ status          │ pending | approved | rejected | suspended                               │
│ portal_active   │ boolean - can login only if true                                        │
│ ai_risk_score   │ 0.0 - 1.0 (AI-calculated risk)                                          │
│ ai_trust_score  │ 0.0 - 1.0 (AI-calculated trust)                                         │
│ commission_rate │ Platform fee percentage (5-15%)                                         │
│ total_orders    │ Cumulative order count                                                  │
│ total_revenue   │ Cumulative revenue (supplier payout)                                    │
│ average_rating  │ Customer rating average (0-5)                                           │
└─────────────────┴─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              SUPPLIER_OFFERS TABLE                                       │
├─────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ id              │ OFF-YYYYMM-XXXXXXXX (unique offer ID)                                   │
│ supplier_id     │ FK to SUPPLIERS - enforces data isolation                               │
│ name            │ Product/service name                                                    │
│ item_type       │ 'service' or 'product'                                                  │
│ category        │ consultation, devices, supplies, pharmacy, homecare                     │
│ price           │ Unit price                                                              │
│ currency        │ USD, EUR, GBP, ILS                                                      │
│ wallet_compatible│ JSON array: ['health', 'investment', 'general']                        │
│ active          │ boolean - only active offers appear in marketplace                      │
│ featured        │ boolean - featured offers appear first                                  │
└─────────────────┴─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              ORDERS TABLE                                                │
├─────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ id              │ ORD-YYYYMM-XXXXXXXX (unique order ID)                                   │
│ supplier_id     │ FK to SUPPLIERS                                                         │
│ customer_id     │ FK to CUSTOMERS                                                         │
│ offer_id        │ FK to SUPPLIER_OFFERS                                                   │
│ total_amount    │ Total customer payment                                                  │
│ platform_fee    │ PHINS commission (total_amount * commission_rate)                       │
│ supplier_payout │ total_amount - platform_fee                                             │
│ status          │ pending | confirmed | processing | completed | cancelled                │
│ payment_method  │ health_wallet, investment_wallet, general_wallet                        │
│ nft_token_id    │ Receipt NFT token for customer ledger                                   │
└─────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

---

## API Endpoint Reference

### Supplier Portal APIs (Authentication Required - Supplier Role)

| Endpoint | Method | Description | Access |
|----------|--------|-------------|--------|
| `/api/supplier/register` | POST | Register new supplier (public) | Public |
| `/api/supplier/login` | POST | Supplier authentication | Public |
| `/api/supplier/profile` | GET | Get own profile | Supplier only |
| `/api/supplier/offers` | GET | List own offers | Supplier only |
| `/api/supplier/offers/upsert` | POST | Create/update offer | Supplier only |
| `/api/supplier/offers/delete` | POST | Delete offer | Supplier only |
| `/api/supplier/orders` | GET | List own orders | Supplier only |
| `/api/supplier/orders/update-status` | POST | Update order status | Supplier only |

### Customer Marketplace APIs (Authentication Required - Customer Role)

| Endpoint | Method | Description | Access |
|----------|--------|-------------|--------|
| `/api/marketplace/offerings` | GET | Browse approved supplier offerings | Customer/Public |
| `/api/marketplace/product/purchase` | POST | Purchase product from supplier | Customer |
| `/api/marketplace/service/purchase` | POST | Purchase service from supplier | Customer |
| `/api/marketplace/transactions` | POST | Get customer purchase history | Customer |

### Admin APIs (Authentication Required - Admin Role)

| Endpoint | Method | Description | Access |
|----------|--------|-------------|--------|
| `/api/admin/suppliers` | GET | List all suppliers | Admin only |
| `/api/admin/suppliers/pending` | GET | List pending applications | Admin only |
| `/api/admin/suppliers/{id}` | GET | Get supplier details | Admin only |
| `/api/admin/suppliers/{id}/approve` | POST | Approve supplier | Admin only |
| `/api/admin/suppliers/{id}/reject` | POST | Reject supplier | Admin only |
| `/api/admin/suppliers/{id}/suspend` | POST | Suspend supplier | Admin only |
| `/api/admin/suppliers/{id}/reactivate` | POST | Reactivate supplier | Admin only |
| `/api/admin/suppliers/analytics` | GET | Platform-wide analytics | Admin only |
| `/api/admin/suppliers/insights` | GET | AI insights and alerts | Admin only |
| `/api/admin/suppliers/orders` | GET | All marketplace orders | Admin only |

---

## Data Integrity Validations

### 1. Supplier Registration
- ✅ Email uniqueness check
- ✅ Password strength validation (min 8 chars)
- ✅ Required fields validation
- ✅ AI risk assessment on submission

### 2. Offer Creation
- ✅ Supplier must be approved (`status == 'approved'`)
- ✅ Portal must be active (`portal_active == true`)
- ✅ Required fields: name, price, category, item_type
- ✅ Offer tied to supplier_id from session (cannot create for others)

### 3. Customer Purchase
- ✅ Offer must be active
- ✅ Supplier must be approved
- ✅ Customer wallet must have sufficient balance
- ✅ Transaction atomicity (deduct wallet, create order, generate NFT)

### 4. Order Processing
- ✅ Supplier can only update own orders
- ✅ Status transitions validated (pending → confirmed → processing → completed)
- ✅ Settlement calculated on completion

---

## Dashboard Views Summary

### Supplier Portal (`/supplier-portal.html`)
- Own profile and company info
- Own offers (create, edit, activate/deactivate)
- Own orders (view, update status)
- Own statistics (total orders, revenue, rating)

### Customer Dashboard (`/dashboard.html`)
- Health Wallet balance
- Browse marketplace (approved supplier offerings only)
- Shopping cart and checkout
- Purchase history with NFT receipts
- Activity log

### Admin Dashboard (`/admin.html` + `/admin-supplier-dashboard.html`)
- Platform-wide statistics
- Pending supplier applications with AI recommendations
- All active suppliers with performance metrics
- All marketplace transactions
- Fee schedule management
- Settlement processing
- AI/BI analytics and insights

---

## Live URLs

- **Production Portal**: https://phins-portal-production.up.railway.app
- **Supplier Portal**: https://phins-portal-production.up.railway.app/supplier-portal.html
- **Supplier Login**: https://phins-portal-production.up.railway.app/supplier-login.html
- **Supplier Register**: https://phins-portal-production.up.railway.app/supplier-register.html
- **Admin Supplier Dashboard**: https://phins-portal-production.up.railway.app/admin-supplier-dashboard.html

---

*Document Version: 1.0*
*Last Updated: January 2026*
*Author: PHINS Engineering Team*
