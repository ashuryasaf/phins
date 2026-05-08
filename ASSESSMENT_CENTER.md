# PHINS Assessment Center

The Assessment Center is the single, unified place where the platform turns
**uploaded documents and ingested external facts** into actionable
underwriting, risk and savings intelligence.

It exists to consolidate previously scattered behaviour across the upload
surface:

- many upload routes used to perform their own ad-hoc extraction or skipped
  it entirely;
- some files were written to temp storage only and lost on restart;
- the Mislaka dashboard re-aggregated the clearinghouse response on top of
  itself, presenting "statistical reviews" of data that is already a fact;
- there was no shared Customer 360 view that risk, claims, billing and
  underwriting could rely on.

The Assessment Center addresses these by providing one pipeline that:

1. **Persists every upload** through
   [`services/document_processing_service.py`](services/document_processing_service.py)
   (with SHA-256 integrity, disk + database persistence, and duplicate
   detection).
2. **Mines documents** for classic insurance, risk and savings indicators -
   government IDs (any country in the regex pack), addresses, dates of birth,
   contact details, medical conditions, medications, allergies, vital signs,
   premiums, sums insured, deductibles, savings balances, IBANs, etc.
3. **Aggregates** the extracted facts per `customer_id` into a deterministic
   **Customer 360 profile** with full provenance back to source documents.
4. **Computes risk, underwriting and chart-ready data series** on top of the
   unified fact store. Statistical analysis only happens here, never in the
   external-data dashboards.
5. **Accepts external clearing-house rows as facts** (Mislaka first; the same
   path is reusable for Swiftness, Plaid, etc.). The Assessment Center is the
   only component that ever aggregates them.
6. **Exports a re-uploadable JSON pack** with a SHA-256 integrity envelope so
   data can leave the platform and come back without losing its provenance.

---

## Architecture

```
┌──────────────────────────┐    ┌────────────────────────────┐
│ All upload entrypoints    │    │  External clearinghouses   │
│  (HTTP API + scripts)     │    │  (Mislaka, Plaid, etc.)    │
└──────────────┬────────────┘    └─────────────┬──────────────┘
               │                                │
               ▼                                ▼
┌──────────────────────────────────────────────────────────────┐
│            DocumentProcessingService (persistent)             │
│      services/document_processing_service.py                  │
│  - Disk + DB storage, SHA-256 integrity, duplicate detection  │
└──────────────┬────────────────────────────┬──────────────────┘
               │                            │
               ▼                            ▼
┌──────────────────────────────────────────────────────────────┐
│                AssessmentCenterService                        │
│             services/assessment_center_service.py             │
│  - Multi-country ID + medical + insurance + savings mining    │
│  - Customer 360 aggregation                                   │
│  - Risk indicator scoring                                     │
│  - Chart-ready data series                                    │
│  - External fact ingestion (no re-aggregation upstream)       │
│  - Re-uploadable JSON packs (SHA-256 integrity envelope)      │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│   Dashboards, underwriting bots, risk reports, claims tools  │
└──────────────────────────────────────────────────────────────┘
```

---

## HTTP surface

All endpoints use the standard PHINS JSON envelope. Errors are
`{"error": "..."}`. Authorization rules:

- `customer` sessions can only read or write their own `customer_id`;
- `admin`, `underwriter`, `actuary`, `analyst`, `claims*` and
  `underwriting_admin` may target any `customer_id`.

### POST `/api/assessment-center/upload`

Persist a fresh upload and immediately mine facts into Customer 360.

```json
{
  "file_name": "intake.txt",
  "file_data_b64": "base64...",
  "mime_type": "text/plain",
  "category": "general",
  "entity_type": "underwriting",
  "entity_id": "UW-001",
  "customer_id": "CUST-1",
  "description": "Initial customer intake"
}
```

Response: `AssessmentResult.to_dict()` - includes the list of extracted facts
(with provenance) and a summary count by `fact_type`.

### POST `/api/assessment-center/scan`

Re-run extraction on a document already stored by the
`DocumentProcessingService`.

### POST `/api/assessment-center/mislaka/link`

Issue a Mislaka query and push the raw rows into the Customer 360 fact store.

```json
{ "id_number": "123456782", "product_type": "all", "customer_id": "CUST-1" }
```

The Assessment Center stores each policy row verbatim with provenance; it
never invents totals on top of the clearinghouse response.

### POST `/api/assessment-center/external-facts`

Generic external fact ingestion (Swiftness, internal exports, etc.).

```json
{
  "customer_id": "CUST-1",
  "source": "swiftness",
  "fact_type": "external_account",
  "records": [{"account_number": "ACC-1", "balance": 25000}]
}
```

### POST `/api/assessment-center/import`

Re-import a previously exported customer pack. Verifies the SHA-256 envelope
and reports whether integrity is intact.

### GET `/api/assessment-center/customer/<id>/profile`

Returns the deterministic Customer 360 snapshot.

### GET `/api/assessment-center/customer/<id>/facts[?fact_type=]`

Flat fact list; optional `fact_type` filter.

### GET `/api/assessment-center/customer/<id>/risk-indicators`

Deterministic risk score derived from the unified fact store. Each
contributor is included with its weight so dashboards can explain the score.

### GET `/api/assessment-center/customer/<id>/charts`

Chart-ready data series for dashboards. Every series is a list of
`{label, value}` entries so the frontend can render with whichever charting
library it likes.

### GET `/api/assessment-center/customer/<id>/export`

Returns a re-uploadable JSON pack of every fact for the customer with a
SHA-256 envelope.

### GET `/api/assessment-center/upload-endpoints`

Live registry of every upload route on the platform plus whether each one is
already routed through the Assessment Center.

### GET `/api/assessment-center/customers` (admin-only)

Lists every customer with assessment facts on file plus their fact count,
linked document count, breakdown by `fact_type`, latest capture timestamp
and current risk score / level. Used by the Assessment Center dashboard to
populate the admin customer picker.

### GET `/api/assessment-center/backfill-status`

Reports how many already-stored documents still need to be mined for facts:

```json
{
  "total_documents": 137,
  "with_facts": 12,
  "without_facts": 125,
  "legacy_pending": 4,
  "pending_total": 129,
  "customer_id": ""
}
```

`legacy_pending` counts files that only exist in the legacy in-memory
`POLICY_DOCUMENTS` mirror and have not yet been written to the document
service. The backfill endpoint will bridge those automatically.

### POST `/api/assessment-center/backfill` (admin-only)

Re-runs the assessment pipeline on every previously uploaded document.
The operation is idempotent - a document that already has facts is
skipped unless `force=true` is passed. Optional body:

```json
{
  "customer_id": "CUST-1",      // restrict to a single customer
  "limit": 200,                  // hard cap on docs processed in this run
  "force": false,                // re-extract even when facts already exist
  "include_legacy": true         // also bridge POLICY_DOCUMENTS into the doc service
}
```

Response:

```json
{
  "success": true,
  "bridge": {"bridged": 4, "ids": ["DOC-..."], "errors": []},
  "result": {
    "scanned": 137,
    "assessed": 129,
    "skipped": 8,
    "error_count": 0,
    "errors": [],
    "customers_updated": ["CUST-1", "CUST-2", "..."],
    "deltas": {"CUST-1": 14, "CUST-2": 7}
  }
}
```

---

## Where to see the changes in the UI

After uploading a document you should now see assessment progress in **four**
places:

1. **`/documents.html` upload status banner** - the green confirmation now
   reads e.g. `🧠 Extracted 14 facts → Customer 360 updated (identity:1,
   medical_condition:3, insurance:6, savings:4). View Assessment Center →`.
2. **`/documents.html` documents table** - a new `360° Facts` column shows a
   `🧠 N facts` chip per document; clicking it opens the Assessment Center
   pre-filtered to that customer.
3. **Customer dashboard (`/dashboard.html`)** - a new green
   `🧠 Assessment Center` action card displays live `N facts` and risk level.
4. **Admin dashboard (`/admin.html`)** - a `🧠 Assessment Center` stat tile
   shows the total number of customers with facts, the platform-wide fact
   count and the high-risk customer count.

### `/assessment-center.html` (new dedicated page)

Available to every logged-in role from the nav bar of the customer
dashboard, admin portal, underwriter dashboard and documents page. It
provides:

- a customer picker (admin only; customers see only themselves);
- four snapshot tiles (facts on file, risk score, documents linked,
  external rows);
- four Customer 360 cards (identity, contact, medical, insurance &
  savings);
- a risk indicator panel with weighted contributors;
- chart-ready data series (risk breakdown, condition distribution,
  external sources, coverage / savings) rendered as in-page bar charts
  with no external libraries;
- an external sources card listing each Mislaka / Swiftness row verbatim
  for full provenance;
- a fact table filterable by `fact_type` with a column linking back to the
  source document SHA-256;
- a Mislaka quick-link form that calls `/api/assessment-center/mislaka/link`
  for the picked customer;
- a re-uploadable pack export button that downloads the SHA-256-sealed JSON;
- the live upload endpoint registry (admin only);
- a backfill banner (admin only) that surfaces how many previously
  uploaded documents still need to be mined for facts and runs the
  pipeline against them with optional customer/limit/force controls.

---

## Upload endpoint registry

The registry below is also returned live from
`GET /api/assessment-center/upload-endpoints` so it cannot drift from the
codebase. Statuses:

- `True` - native Assessment Center route.
- `"delegated"` - route already persists via `DocumentProcessingService`.
- `"supersede"` - kept for backward compatibility but dashboards should now
  prefer the unified pipeline.
- `False` - intentionally not routed through the Assessment Center
  (e.g. binary multipart media uploads).

| Route | Module | Status |
| --- | --- | --- |
| `POST /api/assessment-center/upload` | `web_portal/api_assessment_center.py` | True |
| `POST /api/doc-service/upload` | `web_portal/server.py` | delegated |
| `POST /api/documents/upload` | `web_portal/server.py` | delegated |
| `POST /api/documents/analyze` | `web_portal/server.py` | supersede |
| `POST /api/reports/upload` | `web_portal/server.py` | supersede |
| `POST /api/risk-dashboard/upload` | `web_portal/server.py` | supersede |
| `POST /api/risk-assessment/upload` | `web_portal/server.py` | supersede |
| `POST /api/admin/actuarial-tables/upload` | `web_portal/server.py` | supersede |
| `POST /api/admin/actuarial-tables/upload-file` | `web_portal/server.py` | supersede |
| `POST /api/admin/customers/upload` | `web_portal/server.py` | supersede |
| `POST /api/contribution-documents/upload` | `web_portal/api_extensions.py` | supersede |
| `POST /api/media/upload` | `web_portal/server.py` | False (binary media) |
| `POST /api/mislaka/policies` | `web_portal/server.py` | delegated |

The legacy `/api/documents/upload` and `/api/doc-service/upload` routes are
both wired so that every successful upload triggers
`AssessmentCenterService.assess_document(...)` automatically. Customer 360
data therefore stays current regardless of which entrypoint the client used.

---

## Mislaka behaves as a fact source, not an analyst

The Mislaka clearinghouse already returns *authoritative* policy rows. The
platform now treats every row as a fact:

- `services/mislaka_report_generator.py` exposes `mislaka_facts(result)` which
  emits a flat list of records.
- `link_to_assessment_center(result, customer_id=...)` pushes those rows into
  the Assessment Center as `external_policy` facts.
- `normalize_mislaka_result(result)` no longer includes aggregate totals by
  default - statistics are produced by the Assessment Center on top of the
  unified fact store. Pass `include_aggregates=True` for legacy callers that
  still expect totals in the printout.

Risk scoring, savings totals and chart synthesis live in
`AssessmentCenterService.compute_risk_indicators` /
`AssessmentCenterService.build_chart_data`.

---

## What the extractor recognises

| Category | Examples |
| --- | --- |
| Identity | Israeli ID (Luhn), US SSN (rule-validated), Spanish DNI, UK NIN, Italian Codice Fiscale, German Steuer-ID, French INSEE, Indian Aadhaar (Verhoeff), Brazilian CPF (mod 11), generic passports |
| Contact | Email, phone, postal address (`address:`/`כתובת:`), date of birth |
| Photo | Portrait crop hint (normalised + pixel coordinates) for ID images |
| Medical conditions | diabetes, hypertension, asthma, cancer, stroke, heart disease, COPD, HIV, hepatitis, depression, ... |
| Medications | metformin, insulin, atorvastatin, warfarin, omeprazole, levothyroxine, fluoxetine, chemotherapy, ... |
| Allergies | penicillin, peanut, latex, shellfish, iodine, sulfa, ... |
| Vital signs | BMI, systolic / diastolic blood pressure |
| Insurance | premium, sum insured, cover amount, deductible, policy number, beneficiary, claim |
| Savings | balance, deposit, contribution, pension, provident, education fund, IBAN |
| Risk markers | high risk, very high risk, terminal, fatal, fraud, denied |

Each fact carries `source_document_id`, `source_document_sha256`, `source`,
`confidence` and `metadata`, so dashboards can audit every claim end-to-end.

---

## Data integrity guarantees

- Every uploaded document is persisted to disk via
  `DocumentProcessingService` with SHA-256 verification on read and write.
- Every fact stores the SHA-256 of the source document.
- The fact store is mirrored to disk under
  `data/assessment_center/<customer_id>.json` (configurable via
  `PHINS_ASSESSMENT_FACT_STORE`). Writes use atomic temp + `os.replace`.
- `export_customer_pack` produces a SHA-256-sealed JSON snapshot.
- `import_customer_pack` re-checks the envelope and reports
  `integrity_ok=false` if any byte was tampered with.

---

## Tests

- [`tests/test_assessment_center_service.py`](tests/test_assessment_center_service.py)
  - 16 cases covering ID validators, document extraction, Customer 360,
    risk scoring, chart shape, external facts, and round-trip pack import.
- [`tests/test_assessment_center_api.py`](tests/test_assessment_center_api.py)
  - 9 HTTP-level cases covering upload-and-assess, profile/risk/chart reads,
    external fact ingestion, export/import round-trip, and access control.

Run with:

```bash
pytest tests/test_assessment_center_service.py tests/test_assessment_center_api.py -q
```
