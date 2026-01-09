# PHINS Invitation-Only Registration System
## UML Design Document

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    INVITATION-ONLY REGISTRATION SYSTEM                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │    ADMIN     │────▶│  INVITATION  │────▶│  NEW USER    │                │
│  │  Generates   │     │    CODE      │     │  Registers   │                │
│  │    Code      │     │   System     │     │  with Code   │                │
│  └──────────────┘     └──────────────┘     └──────────────┘                │
│                              │                    │                         │
│                              ▼                    ▼                         │
│                       ┌──────────────┐     ┌──────────────┐                │
│                       │  VALIDATION  │     │  CUSTOMER    │                │
│                       │   Engine     │     │   Record     │                │
│                       └──────────────┘     └──────────────┘                │
│                                                   │                         │
│                                                   ▼                         │
│                                            ┌──────────────┐                │
│                                            │  PERSISTENCE │                │
│                                            │   (Seeds +   │                │
│                                            │   Database)  │                │
│                                            └──────────────┘                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Invitation Code Data Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INVITATION_CODES                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  {                                                                           │
│    code: "PHINS-2026-XXXX",        // Unique invitation code                │
│    created_at: "2026-01-09T...",   // When code was generated               │
│    created_by: "admin",             // Who generated the code               │
│    expires_at: "2026-02-09T...",   // Expiration (30 days default)          │
│    max_uses: 1,                     // How many times can be used           │
│    used_count: 0,                   // How many times used                  │
│    used_by: [],                     // List of users who used it            │
│    status: "active",                // active, used, expired, revoked       │
│    notes: "VIP customer referral"   // Optional admin notes                 │
│  }                                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Enhanced Customer Data Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CUSTOMER RECORD (Enhanced)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  {                                                                           │
│    // Identity                                                               │
│    customer_id: "CUST-20260109-XXXX",                                       │
│    email: "user@example.com",                                               │
│    name: "Full Name",                                                        │
│    phone: "+1234567890",                                                    │
│                                                                              │
│    // Registration                                                           │
│    invitation_code: "PHINS-2026-XXXX",    // Code used to register         │
│    registered_at: "2026-01-09T10:30:00",  // Date/time of registration     │
│    registered_ip: "192.168.1.1",          // IP address at registration    │
│                                                                              │
│    // Applications                                                           │
│    applications: [                                                           │
│      {                                                                       │
│        id: "APP-001",                                                        │
│        type: "disability",                                                   │
│        submitted_at: "2026-01-09T11:00:00",                                 │
│        status: "pending|approved|rejected",                                  │
│        policy_id: "POL-001" // if approved                                  │
│      }                                                                       │
│    ],                                                                        │
│                                                                              │
│    // Policies                                                               │
│    policies: [                                                               │
│      {                                                                       │
│        policy_id: "POL-001",                                                │
│        activated_at: "2026-01-10T...",                                      │
│        status: "active|cancelled|expired"                                   │
│      }                                                                       │
│    ],                                                                        │
│                                                                              │
│    // Claims                                                                 │
│    claims: [                                                                 │
│      {                                                                       │
│        claim_id: "CLM-001",                                                 │
│        filed_at: "2026-06-15T...",                                          │
│        status: "pending|approved|rejected|paid"                             │
│      }                                                                       │
│    ],                                                                        │
│                                                                              │
│    // Financial                                                              │
│    wallet: {                                                                 │
│      balance: 5000.00,                                                       │
│      transactions: [...]                                                     │
│    },                                                                        │
│    investments: {                                                            │
│      positions: [...],                                                       │
│      total_value: 25000.00                                                  │
│    },                                                                        │
│                                                                              │
│    // Metadata                                                               │
│    last_login: "2026-01-09T...",                                            │
│    updated_at: "2026-01-09T..."                                             │
│  }                                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Registration Flow Sequence

```
┌────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  User  │     │ Register │     │  Server  │     │ Database │     │  Seeds   │
│        │     │   Page   │     │          │     │          │     │          │
└───┬────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
    │               │                │                │                │
    │ 1. Click      │                │                │                │
    │   "Register"  │                │                │                │
    │──────────────▶│                │                │                │
    │               │                │                │                │
    │◀──────────────│                │                │                │
    │ 2. Show form  │                │                │                │
    │   with code   │                │                │                │
    │   input       │                │                │                │
    │               │                │                │                │
    │ 3. Enter      │                │                │                │
    │   details +   │                │                │                │
    │   invite code │                │                │                │
    │──────────────▶│                │                │                │
    │               │                │                │                │
    │               │ 4. POST        │                │                │
    │               │  /api/register │                │                │
    │               │───────────────▶│                │                │
    │               │                │                │                │
    │               │                │ 5. Validate    │                │
    │               │                │    code        │                │
    │               │                │───────────────▶│                │
    │               │                │                │                │
    │               │                │◀───────────────│                │
    │               │                │ 6. Code valid  │                │
    │               │                │                │                │
    │               │                │ 7. Create user │                │
    │               │                │───────────────▶│                │
    │               │                │                │                │
    │               │                │ 8. Save to     │                │
    │               │                │    seeds file  │                │
    │               │                │────────────────────────────────▶│
    │               │                │                │                │
    │               │                │ 9. Mark code   │                │
    │               │                │    as used     │                │
    │               │                │───────────────▶│                │
    │               │                │                │                │
    │               │◀───────────────│                │                │
    │               │ 10. Success    │                │                │
    │               │                │                │                │
    │◀──────────────│                │                │                │
    │ 11. Redirect  │                │                │                │
    │    to login   │                │                │                │
    │               │                │                │                │
```

---

## 5. Admin Code Generation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      ADMIN INVITATION MANAGEMENT                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Location: /admin.html → "Invitation Codes" Section                         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  🎟️ Generate New Invitation Code                                    │   │
│  │                                                                      │   │
│  │  Number of Uses: [ 1 ▼ ]     Expires In: [ 30 days ▼ ]             │   │
│  │  Notes: [ VIP referral from partner                    ]            │   │
│  │                                                                      │   │
│  │  [ 🎫 Generate Code ]                                                │   │
│  │                                                                      │   │
│  │  Generated: PHINS-2026-A7X9  [ Copy ] [ Send via Email ]            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  📋 Active Invitation Codes                                         │   │
│  │                                                                      │   │
│  │  Code              Created     Expires      Uses    Status          │   │
│  │  ─────────────────────────────────────────────────────────────────  │   │
│  │  PHINS-2026-A7X9   Jan 9       Feb 9        0/1     ✅ Active       │   │
│  │  PHINS-2026-B3K2   Jan 8       Feb 8        1/1     ⚫ Used         │   │
│  │  PHINS-2026-C5M1   Jan 5       Jan 6        0/1     ❌ Expired      │   │
│  │                                                                      │   │
│  │  [ 🗑️ Revoke ] [ 📊 Export ]                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Persistence Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PERSISTENCE STRATEGY                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ON NEW CUSTOMER REGISTRATION:                                              │
│  ─────────────────────────────                                              │
│  1. Create user in USERS dictionary (with hashed password)                  │
│  2. Create customer in CUSTOMERS dictionary                                 │
│  3. Save to database (if enabled)                                           │
│  4. Append to seeds file for restart persistence                            │
│  5. Save to ledger persistence file                                         │
│                                                                              │
│  ON NEW APPLICATION:                                                        │
│  ──────────────────                                                         │
│  1. Create in UNDERWRITING_APPLICATIONS                                     │
│  2. Link to customer record                                                 │
│  3. Save application_date                                                   │
│  4. Persist to ledger                                                       │
│                                                                              │
│  ON POLICY ACTIVATION:                                                      │
│  ─────────────────────                                                      │
│  1. Create in POLICIES                                                      │
│  2. Link to customer                                                        │
│  3. Save activation_date                                                    │
│  4. Persist to ledger                                                       │
│                                                                              │
│  ON CLAIM FILED:                                                            │
│  ──────────────                                                             │
│  1. Create in CLAIMS                                                        │
│  2. Link to customer & policy                                               │
│  3. Save filed_date                                                         │
│  4. Persist to ledger                                                       │
│                                                                              │
│  ON FINANCIAL TRANSACTION:                                                  │
│  ─────────────────────────                                                  │
│  1. Update HEALTH_WALLETS / INVESTMENT_ACCOUNTS                             │
│  2. Create entry in TRANSACTION_LEDGER                                      │
│  3. Save transaction_date                                                   │
│  4. Persist to ledger                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Implementation Checklist

- [ ] Create INVITATION_CODES storage in server.py
- [ ] Add invitation code validation API endpoint
- [ ] Update register.html with invitation code field
- [ ] Update register.js to send invitation code
- [ ] Create admin UI for generating codes
- [ ] Add persistence for invitation codes
- [ ] Enhance customer record with all dates
- [ ] Auto-append new customers to seeds file
- [ ] Test full registration flow
- [ ] Deploy and verify

---

## Confirmation Required

Please confirm to proceed with implementation.
