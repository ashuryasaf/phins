# Dashboard Access Failure Analysis - 72-Hour Assessment

## Executive Summary

Customer access to the dashboard has been broken since **January 30, 2026 14:00** despite 8+ PR attempts to fix it. The root cause is a **systemic pipeline flaw** in how customer authentication and data isolation work together.

## Timeline of Failed PRs (Jan 30 - Feb 2, 2026)

| PR | Title | Merged | Issue |
|----|-------|--------|-------|
| #72 | Customer login dashboard access | Jan 30 12:54 | Initial fix attempt |
| #73 | Customer login redirection | Jan 30 19:41 | Redirect logic |
| #80 | Portal customer access | Jan 31 21:55 | Validation script |
| #81 | Customer dashboard access | Feb 1 11:29 | Access issues |
| #82 | Production database connectivity | Feb 1 13:25 | DB connection |
| #83 | Phins-portal database connection | Feb 1 14:48 | PostgreSQL recovery |
| #84 | Dashboard endless rendering | Feb 1 19:38 | Corrupted session init |
| #85 | Dashboard endless rendering | Feb 1 19:47 | Session cache hardening |
| #88 | Dashboard data issues | Feb 2 19:27 | JS syntax errors |

**Pattern**: Each PR fixed a symptom but missed the systemic issue.

---

## Root Cause Analysis

### The Pipeline Has 4 Critical Flaws:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION PIPELINE FLAWS                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  FLAW 1: Multiple Auth Sources with Inconsistent customer_id            │
│  ─────────────────────────────────────────────────────────────          │
│  Login tries 4 sources in order:                                        │
│    1. USERS dict (staff) → customer_id from staff record                │
│    2. Database customers → customer_id from DB (correct)                │
│    3. _FALLBACK_USERS → customer_id may be None                         │
│    4. In-memory CUSTOMERS → customer_id from dict key                   │
│                                                                         │
│  If source #2 fails (DB issue), falls to #3/#4 which may lack           │
│  customer_id, creating a broken token.                                  │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  FLAW 2: Token Contains Empty customer_id                               │
│  ─────────────────────────────────────────────                          │
│  Token format: phins_{base64(username|role|customer_id|expires)}.sig    │
│                                                                         │
│  If customer_id is None during login:                                   │
│    → Token created with customer_id=''                                  │
│    → When parsed, '' becomes None                                       │
│    → Session has customer_id=None                                       │
│    → All customer APIs return 403                                       │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  FLAW 3: Dashboard JS Crashes Before Data Load                          │
│  ─────────────────────────────────────────────                          │
│  dashboard.html had:                                                    │
│    - Missing function closing brace                                     │
│    - Duplicate variable declarations                                    │
│    - Corrupted initialization code                                      │
│                                                                         │
│  → JavaScript parsing fails                                             │
│  → DOMContentLoaded never completes                                     │
│  → Splash screen shows forever                                          │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  FLAW 4: API Data Isolation Blocks Valid Customers                      │
│  ───────────────────────────────────────────────                        │
│  /api/customers checks:                                                 │
│    if role == 'customer' and not session_customer_id:                   │
│        return 403 "Customer session invalid"                            │
│                                                                         │
│  Even with valid login, if customer_id was lost in token creation,      │
│  all customer-specific APIs fail with 403.                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagram (Current Broken State)

```
┌──────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Browser    │────▶│ /api/login  │────▶│ Auth Sources     │
│ login.html   │     │             │     │                  │
└──────────────┘     └──────┬──────┘     │ 1. USERS dict    │
                           │            │ 2. DB Customers ◀──── May fail!
                           │            │ 3. Fallback      │
                           │            │ 4. CUSTOMERS     │
                           ▼            └────────┬─────────┘
                    ┌──────────────┐              │
                    │ Create Token │◀─────────────┘
                    │ with:        │     customer_id may be NULL
                    │ - username   │     if DB lookup failed
                    │ - role       │
                    │ - customer_id│ ◀──── CRITICAL: May be empty!
                    │ - expires    │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Store Token  │
                    │ localStorage │
                    │ sessionStore │
                    └──────┬───────┘
                           │
                           ▼
┌──────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Browser    │────▶│ dashboard   │────▶│ Session Validate │
│ dashboard    │     │ .html       │     │ /api/session/    │
│              │     │             │     │ validate         │
└──────────────┘     └──────┬──────┘     └────────┬─────────┘
                           │                      │
                    JS may crash ◀────────────────┘
                    before this!        Returns customer_id=null
                           │            if token was broken
                           ▼
                    ┌──────────────┐
                    │ Load Data    │
                    │ /api/customers│
                    │ /api/policies │
                    │ /api/claims   │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │    403       │
                    │ "Customer    │ ◀──── FAILURE POINT
                    │  session     │
                    │  invalid"    │
                    └──────────────┘
```

---

## UML Sequence Diagram - Current Flow

```
┌─────────┐          ┌─────────┐          ┌────────────┐          ┌─────────────┐
│ Browser │          │ Server  │          │ Database   │          │ In-Memory   │
│         │          │         │          │            │          │ Dictionaries│
└────┬────┘          └────┬────┘          └─────┬──────┘          └──────┬──────┘
     │                    │                     │                        │
     │ POST /api/login    │                     │                        │
     │ {email, password}  │                     │                        │
     │───────────────────▶│                     │                        │
     │                    │                     │                        │
     │                    │ Check USERS dict    │                        │
     │                    │────────────────────────────────────────────▶│
     │                    │                     │                        │
     │                    │◀────────────────────────────────────────────│
     │                    │ Not found (customer)│                        │
     │                    │                     │                        │
     │                    │ Query customers     │                        │
     │                    │────────────────────▶│                        │
     │                    │                     │                        │
     │                    │     ╔═══════════════════════════════╗       │
     │                    │     ║ DATABASE CONNECTION MAY FAIL  ║       │
     │                    │     ║ → customer_id stays NULL      ║       │
     │                    │     ╚═══════════════════════════════╝       │
     │                    │                     │                        │
     │                    │◀────────────────────│                        │
     │                    │ Customer found OR   │                        │
     │                    │ Connection error    │                        │
     │                    │                     │                        │
     │                    │ Create signed token │                        │
     │                    │ with customer_id    │                        │
     │                    │ (may be empty!)     │                        │
     │                    │                     │                        │
     │◀───────────────────│                     │                        │
     │ {token, role,      │                     │                        │
     │  customer_id: ???} │ ◀──── MAY BE NULL   │                        │
     │                    │                     │                        │
     │                    │                     │                        │
     │ GET dashboard.html │                     │                        │
     │───────────────────▶│                     │                        │
     │                    │                     │                        │
     │◀───────────────────│                     │                        │
     │ [Corrupted JS]     │ ◀──── JS ERRORS     │                        │
     │                    │                     │                        │
     │    ╔════════════════════════════════════════════════════╗        │
     │    ║ BROWSER: JavaScript parsing fails                  ║        │
     │    ║ DOMContentLoaded never fires properly              ║        │
     │    ║ Splash screen shows forever                        ║        │
     │    ╚════════════════════════════════════════════════════╝        │
     │                    │                     │                        │
     │ (If JS works)      │                     │                        │
     │ GET /api/customers │                     │                        │
     │───────────────────▶│                     │                        │
     │                    │                     │                        │
     │                    │ Check session       │                        │
     │                    │ customer_id=NULL    │                        │
     │                    │                     │                        │
     │◀───────────────────│                     │                        │
     │ 403 "Customer      │ ◀──── BLOCKED       │                        │
     │ session invalid"   │                     │                        │
     │                    │                     │                        │
     ▼                    ▼                     ▼                        ▼
```

---

## UML Sequence Diagram - Fixed Flow

```
┌─────────┐          ┌─────────┐          ┌────────────┐          ┌─────────────┐
│ Browser │          │ Server  │          │ Database   │          │ In-Memory   │
│         │          │         │          │            │          │ Dictionaries│
└────┬────┘          └────┬────┘          └─────┬──────┘          └──────┬──────┘
     │                    │                     │                        │
     │ POST /api/login    │                     │                        │
     │ {email, password}  │                     │                        │
     │───────────────────▶│                     │                        │
     │                    │                     │                        │
     │                    │ 1. Check USERS dict │                        │
     │                    │────────────────────────────────────────────▶│
     │                    │◀────────────────────────────────────────────│
     │                    │                     │                        │
     │                    │ 2. Check Database   │                        │
     │                    │────────────────────▶│                        │
     │                    │◀────────────────────│                        │
     │                    │                     │                        │
     │                    │ 3. GUARANTEED customer_id resolution:        │
     │                    │    - From DB Customer.id                     │
     │                    │    - OR from dynamic_customers.json          │
     │                    │    - OR generate new CUST-XXXXX              │
     │                    │                     │                        │
     │                    │ ╔═══════════════════════════════════════╗   │
     │                    │ ║ NEVER create token with empty         ║   │
     │                    │ ║ customer_id for role='customer'       ║   │
     │                    │ ╚═══════════════════════════════════════╝   │
     │                    │                     │                        │
     │                    │ Create signed token │                        │
     │                    │ with VALID customer_id                       │
     │                    │                     │                        │
     │◀───────────────────│                     │                        │
     │ {token, role,      │                     │                        │
     │  customer_id: ✓}   │                     │                        │
     │                    │                     │                        │
     │ GET dashboard.html │                     │                        │
     │───────────────────▶│                     │                        │
     │◀───────────────────│                     │                        │
     │ [Fixed JS]         │ ◀──── JS WORKS     │                        │
     │                    │                     │                        │
     │ ╔═════════════════════════════════════════════════════════╗      │
     │ ║ BROWSER: JavaScript executes correctly                  ║      │
     │ ║ DOMContentLoaded fires, splash hides                    ║      │
     │ ║ API calls made with valid customer_id                   ║      │
     │ ╚═════════════════════════════════════════════════════════╝      │
     │                    │                     │                        │
     │ GET /api/customers │                     │                        │
     │───────────────────▶│                     │                        │
     │                    │                     │                        │
     │                    │ Check session       │                        │
     │                    │ customer_id=CUST-XXX│                        │
     │                    │                     │                        │
     │                    │ Fetch customer data │                        │
     │                    │────────────────────▶│                        │
     │                    │◀────────────────────│                        │
     │                    │                     │                        │
     │◀───────────────────│                     │                        │
     │ 200 {customer data}│ ◀──── SUCCESS      │                        │
     │                    │                     │                        │
     ▼                    ▼                     ▼                        ▼
```

---

## Class Diagram - Authentication Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                         AUTHENTICATION SYSTEM                          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌─────────────────┐      ┌─────────────────┐      ┌────────────────┐ │
│  │     USERS       │      │   CUSTOMERS     │      │   Database     │ │
│  │  (Dict/Wrapper) │      │     (Dict)      │      │   (PostgreSQL) │ │
│  ├─────────────────┤      ├─────────────────┤      ├────────────────┤ │
│  │ username (key)  │      │ customer_id(key)│      │ Customer table │ │
│  │ password_hash   │      │ email           │      │ - id (PK)      │ │
│  │ password_salt   │      │ password_hash   │      │ - email        │ │
│  │ role            │      │ password_salt   │      │ - password_hash│ │
│  │ customer_id?    │      │ name            │      │ - password_salt│ │
│  │ name            │      │                 │      │ - portal_active│ │
│  └────────┬────────┘      └────────┬────────┘      └───────┬────────┘ │
│           │                        │                       │          │
│           │         Auth Flow      │                       │          │
│           └────────────┬───────────┴───────────────────────┘          │
│                        │                                              │
│                        ▼                                              │
│           ┌────────────────────────┐                                  │
│           │   LoginHandler         │                                  │
│           ├────────────────────────┤                                  │
│           │ - check_users()        │                                  │
│           │ - check_database()     │                                  │
│           │ - check_fallback()     │                                  │
│           │ - check_customers()    │                                  │
│           │ - verify_password()    │                                  │
│           │ - create_token()       │                                  │
│           └───────────┬────────────┘                                  │
│                       │                                               │
│                       ▼                                               │
│           ┌────────────────────────┐                                  │
│           │   SignedToken          │                                  │
│           ├────────────────────────┤                                  │
│           │ - username: str        │                                  │
│           │ - role: str            │                                  │
│           │ - customer_id: str?    │ ◀──── MUST NOT BE EMPTY FOR     │
│           │ - expires: datetime    │       CUSTOMER ROLE!             │
│           │ - signature: str       │                                  │
│           └────────────────────────┘                                  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Fix Requirements

### 1. Login Endpoint Must Guarantee customer_id
```python
# BEFORE (broken):
if user:
    token = _create_signed_token(username, role, customer_id, expires)
    # customer_id may be None!

# AFTER (fixed):
if user:
    # For customer role, MUST have valid customer_id
    if role == 'customer' and not customer_id:
        # Recovery: lookup by email in CUSTOMERS dict
        for cid, cust in CUSTOMERS.items():
            if cust.get('email', '').lower() == username.lower():
                customer_id = cid
                break
        
        # Last resort: generate new customer_id
        if not customer_id:
            customer_id = f"CUST-{random.randint(10000, 99999)}"
            CUSTOMERS[customer_id] = {
                'id': customer_id,
                'email': username,
                'name': user.get('name', username.split('@')[0]),
                'created_date': datetime.now().isoformat()
            }
    
    token = _create_signed_token(username, role, customer_id, expires)
```

### 2. Dashboard JS Must Be Valid
- Fixed in PR #88 (syntax errors)
- Verified no duplicate declarations
- Verified all functions properly closed

### 3. API Endpoints Must Have Recovery Path
```python
# If customer_id missing from session, try to recover
if role == 'customer' and not session_customer_id:
    # Try database lookup by username (email)
    # Try in-memory CUSTOMERS lookup
    # If all fail, return clear error message
```

---

## Files Changed

| File | Changes |
|------|---------|
| `web_portal/server.py` | Fix login customer_id guarantee |
| `web_portal/static/dashboard.html` | Fix JS syntax errors (done in PR #88) |

---

## Testing Checklist

- [ ] Customer can login with email/password
- [ ] Login response includes valid customer_id
- [ ] Dashboard loads without JS errors
- [ ] /api/customers returns customer data
- [ ] /api/policies returns customer policies
- [ ] /api/claims returns customer claims
- [ ] Session validation returns correct customer_id

---

*Generated: February 2, 2026*
