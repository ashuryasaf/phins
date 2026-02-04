# Risk Dashboard Upload - Architecture Diagram

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                      RISK DASHBOARD UPLOAD ARCHITECTURE                       ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌──────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND LAYER                                   │
│                     /web_portal/static/risk-dashboard.html                    │
└──────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  1. PAGE LOAD                                                │
    │     - Check session token (cookie/localStorage)              │
    │     - Call /api/session/verify                               │
    │     - Validate user role                                     │
    │     - Show upload UI or redirect                             │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  2. FILE SELECTION                                           │
    │     - Drag & drop or browse                                  │
    │     - Validate file type (JSON/CSV)                          │
    │     - Validate file size (max 10MB)                          │
    │     - Display file info                                      │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  3. PROCESS UPLOAD                                           │
    │     - Read file content                                      │
    │     - Parse JSON or CSV                                      │
    │     - Send to /api/risk-assessment/upload                    │
    │     - Show progress bar                                      │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  4. DISPLAY RESULTS                                          │
    │     - Show success message                                   │
    │     - Display counts (processed/created/updated)             │
    │     - List errors if any                                     │
    │     - Provide upload ID for tracking                         │
    └─────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND LAYER                                    │
│                         /web_portal/server.py                                 │
└──────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  GET /api/session/verify                                     │
    │     INPUT:  Authorization: Bearer <token>                    │
    │     OUTPUT: {valid, username, role, customer_id}             │
    │     ROLE:   Any authenticated user                           │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  POST /api/risk-assessment/upload                            │
    │                                                              │
    │  AUTHORIZATION CHECK:                                        │
    │     require_role(session, ['admin', 'underwriter',          │
    │                            'actuary'])                       │
    │     ↓ YES                         ↓ NO                      │
    │  Continue                   Return 403 Unauthorized          │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  DATA VALIDATION LOOP                                        │
    │     For each record in data array:                           │
    │                                                              │
    │     1. Validate required fields                              │
    │        - customer_id or email                                │
    │        - risk_score                                          │
    │                                                              │
    │     2. Validate risk_score                                   │
    │        - Must be numeric                                     │
    │        - Must be 0-100                                       │
    │                                                              │
    │     3. Find/verify customer                                  │
    │        - By customer_id or                                   │
    │        - By email lookup                                     │
    │                                                              │
    │     4. Check if application exists                           │
    │        - If exists: UPDATE (preserve fields)                 │
    │        - If new: CREATE                                      │
    │                                                              │
    │     5. Track errors per row                                  │
    │        - Continue processing on error                        │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  DATA PERSISTENCE                                            │
    │                                                              │
    │  IN-MEMORY:                                                  │
    │     UNDERWRITING_APPLICATIONS[app_id] = app_data             │
    │                                                              │
    │  DATABASE (if enabled):                                      │
    │     - Create/Update UnderwritingApplication record           │
    │     - Handle database errors gracefully                      │
    │     - In-memory data preserved even if DB fails              │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  AUDIT LOGGING                                               │
    │     audit.log(actor, 'upload', 'risk_assessments',          │
    │               upload_id, {                                   │
    │                 'filename': filename,                        │
    │                 'processed': count,                          │
    │                 'created': count,                            │
    │                 'updated': count,                            │
    │                 'errors': count                              │
    │               })                                             │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  RETURN RESPONSE                                             │
    │     Status: 201 (created) or 200 (updated)                   │
    │     Body: {                                                  │
    │       success: true,                                         │
    │       upload_id: "RISK-UPLOAD-...",                          │
    │       processed: 10,                                         │
    │       created: 8,                                            │
    │       updated: 2,                                            │
    │       errors: ["Row 3: ...", "Row 5: ..."],                 │
    │       total_errors: 2                                        │
    │     }                                                        │
    └─────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                            DATA LAYER                                         │
└──────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  IN-MEMORY STORAGE                                           │
    │     UNDERWRITING_APPLICATIONS (dict)                         │
    │     CUSTOMERS (dict)                                         │
    │     SESSIONS (dict)                                          │
    │     USERS (dict)                                             │
    └─────────────────────────────────────────────────────────────┘
                                ↓
    ┌─────────────────────────────────────────────────────────────┐
    │  DATABASE (if USE_DATABASE=true)                             │
    │     underwriting_applications (table)                        │
    │     customers (table)                                        │
    │     audit_logs (table)                                       │
    └─────────────────────────────────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════════════════╗
║                         AUTHORIZATION MATRIX                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌──────────────┬────────────────┬────────────────┬─────────────────────────────┐
│ Role         │ View Page      │ Upload Data    │ Notes                       │
├──────────────┼────────────────┼────────────────┼─────────────────────────────┤
│ admin        │ ✅ YES         │ ✅ YES         │ Full access                 │
│ underwriter  │ ✅ YES         │ ✅ YES         │ Primary use case            │
│ actuary      │ ✅ YES         │ ✅ YES         │ Risk analysis               │
│ accountant   │ ❌ NO          │ ❌ NO          │ Redirected to dashboard     │
│ claims       │ ❌ NO          │ ❌ NO          │ Redirected to dashboard     │
│ customer     │ ❌ NO          │ ❌ NO          │ Redirected to dashboard     │
│ (not logged) │ ❌ NO          │ ❌ NO          │ Redirected to login         │
└──────────────┴────────────────┴────────────────┴─────────────────────────────┘

╔══════════════════════════════════════════════════════════════════════════════╗
║                         DATA VALIDATION RULES                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌────────────────────────┬─────────────────┬───────────────────────────────────┐
│ Field                  │ Required        │ Validation Rules                  │
├────────────────────────┼─────────────────┼───────────────────────────────────┤
│ customer_id            │ Yes (or email)  │ Must exist in CUSTOMERS           │
│ email                  │ Yes (or cust_id)│ Must match existing customer      │
│ risk_score             │ Yes             │ Numeric, 0-100                    │
│ assessment_date        │ No              │ Date format (YYYY-MM-DD)          │
│ medical_conditions     │ No              │ String, any length                │
│ occupation_risk        │ No              │ String (Low/Medium/High)          │
│ lifestyle_factors      │ No              │ String, any length                │
│ premium_loading        │ No              │ Numeric, >= 0                     │
│ status                 │ No              │ String (defaults to 'pending')    │
│ application_id         │ No              │ For updates, auto-gen for new     │
└────────────────────────┴─────────────────┴───────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════════════════╗
║                         ERROR HANDLING FLOW                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

    Record Processing:
    
    ┌─────────────┐
    │ For Each    │
    │ Record      │
    └──────┬──────┘
           │
           ↓
    ┌──────────────────┐
    │ Validate         │
    │ Required Fields  │
    └──────┬───────────┘
           │
           ↓
    ┌──────────────────┐      ❌ Invalid
    │ Valid?           │──────────────→ Add to errors array
    └──────┬───────────┘                Continue to next record
           │ ✅ Valid
           ↓
    ┌──────────────────┐
    │ Process          │
    │ Record           │
    └──────┬───────────┘
           │
           ↓
    ┌──────────────────┐      ❌ Error
    │ Success?         │──────────────→ Add to errors array
    └──────┬───────────┘                Continue to next record
           │ ✅ Success
           ↓
    Increment processed/created/updated counter
    Continue to next record

    Result: Partial success possible
    - Valid records are saved
    - Invalid records are reported
    - No data corruption

╔══════════════════════════════════════════════════════════════════════════════╗
║                         DEPLOYMENT VERIFICATION                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

✅ 1. Page accessible at /risk-dashboard.html
✅ 2. Authentication check working
✅ 3. Role-based authorization enforced
✅ 4. File upload validates properly
✅ 5. API endpoint accepts data
✅ 6. Data validation working
✅ 7. Error handling graceful
✅ 8. Data integrity preserved
✅ 9. Audit logging functional
✅ 10. Test suite passing

```
