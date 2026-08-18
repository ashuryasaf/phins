# PHINS Multimodal Document Intelligence & AI Assessment Pipeline — Pre-Code Implementation Assessment

Status: **PLAN ONLY — no code written.** This document adjusts the external
ChatGPT specification ("Multimodal Document Intelligence & AI Assessment
Pipeline") to the real PHINS codebase so cost, effect, and memory impact can
be evaluated before implementation is approved.

Scope: all PHINS assessment surfaces that consume uploaded data — application
/ onboarding, underwriting, claims, bills, Mislaka/Customer 360, and future
assessment types.

---

## Executive summary

The external spec assumes a greenfield TypeScript/AWS stack (SQS, Lambda, S3,
signed URLs). PHINS is a Python `BaseHTTPRequestHandler` platform deployed on
Railway/Render with disk/volume storage and SQLite/Postgres. **Roughly 60% of
the spec already exists** in some form; the correct strategy is to harden and
connect existing pieces, not to build the spec's architecture literally.

| Spec layer (§4) | PHINS today | Verdict |
|---|---|---|
| Upload API | `/api/documents/upload`, `/api/assessment-center/upload`, `/api/doc-service/upload`, `/api/claims/files`, `/api/underwriting/files`, `/api/contribution-documents/upload` | **Exists** (fragmented; base64-in-JSON) |
| Secure object storage | Disk/volume via `DocumentProcessingService._resolve_document_storage_root()` (`PHINS_DOCUMENT_STORAGE` → Railway volume → `/data/documents`), SHA-256/MD5 checksums, `security/file_scanner.py` | **Exists** (no S3; not needed initially) |
| Processing queue | `document_processing_jobs` table + `DocumentProcessingJobRepository.get_pending_jobs()` — but processing runs **synchronously** on upload | **Schema exists, worker missing** |
| File classification | Extension + magic-byte MIME in `file_scanner.py` + category heuristics in `DocumentProcessingService` | **Exists** |
| OCR / parsing | Real: `pypdf`, `pdf2image`+poppler, `pytesseract` (heb+eng+ara), `openpyxl`/`xlrd`, CSV/JSON/ZIP. Missing: DOCX (no `python-docx`) | **Mostly exists** |
| Audio transcription | Stub in `_analyze_audio` (size→duration estimate); subtitle webhook job model exists (`bridge` provider) | **Gap** |
| Video analysis | Stub in `_analyze_video`; real Gemini/Kling video *generation* exists in `services/media_generation_service.py` | **Gap** |
| Normalized document model | `Document` model (`extracted_text`, `extracted_metadata`, `ai_summary`, `ai_tags`, `confidence_score`) | **Exists** (needs pages/tables/segments detail) |
| Evidence layer | `Fact` dataclass in `services/assessment_center_service.py` with `source_document_id`, `source_document_sha256`, `confidence` | **Exists** (needs page/offset/source-text granularity) |
| Assessment engine | `AssessmentCenterService.run_analysis` (customer_360, risk, cross_document, unified), `underwriting_risk_scoring`, `claims_bot_service` | **Exists** (rule-based, deterministic) |
| Structured LLM output | `AssessmentAIService` (OpenAI-compatible, feature-flagged, advisory-only, confidence capped 0.4) | **Partial** (no JSON-schema validation, single provider) |
| Confidence + human review | `needs_review` always true on AI narrative; `human_override` on `RiskAssessmentReportModel`; thresholds in `ai_threshold_config.py` | **Partial** |
| Contradiction detection | `services/underwriting_integrity_service.py` (`detect_statement_contradictions`, `detect_claim_statement_contradictions`) | **Exists** (extend to cross-document facts) |
| Assessment history | `AssessmentRecordService` — append-only `assessment_records` (types `underwriting_risk`, `claims_fraud`, `customer_risk`) | **Exists** |
| Idempotency | `idempotency_keys` table + `DatabaseManager.idempotency` repo (schema present, unused); per-row keys on wallet tables | **Schema exists, unused for docs** |
| Retries / DLQ | None for document jobs | **Gap** |
| Cost tracking | None for AI/parse operations (`platform_ledger` exists but no usage metering) | **Gap** |
| Observability | `PlatformEventLedgerService` hash-chained events, `/api/health`, `/api/metrics`, `AuditService` dual-write to `platform_ledger_entries` | **Exists** (add document-event vocabulary) |
| UI | `assessment-center.html`, `unified-workbench.html`, `risk-assessment-viewer.html`, `underwriter-dashboard.html`, `claims-adjuster-dashboard.html` | **Exists** (add evidence drill-down + processing status) |

Design constraint carried over from `docs/ai_surface_design_principles.md` and
preserved throughout this plan: **adjudication stays deterministic; the LLM
explains, it does not decide.** This matches the spec's own requirement that
the LLM must not be the system of record for extracted facts.

---

## A. Current architecture (what exists — verified against the repo)

- **Ingestion.** Six upload surfaces (see table above). The primary paths accept
  base64 inside JSON bodies. `/api/media/upload` accepts multipart but
  `_stream_multipart_to_disk` in `web_portal/server.py` still reads the whole
  body into memory before writing. Limits: 25MB (`MAX_POLICY_DOCUMENT_SIZE_BYTES`),
  50MB (`PHINS_MAX_DOCUMENT_SIZE`), 500MB (contribution uploads), 10MB default
  HTTP body cap (`PHINS_MAX_REQUEST_SIZE`).
- **Storage.** File bytes on disk/volume (never DB blobs); `documents` table
  holds metadata, paths, checksums, and extracted text. Legacy paths
  (`POLICY_DOCUMENTS`, `CLAIM_FILES`, `UNDERWRITING_FILES`) also keep base64
  copies in process memory / ledger snapshots — the largest memory liability
  in the current design.
- **Processing.** `DocumentProcessingService` (~1,470 lines) runs jobs
  synchronously at upload time: metadata, PDF text layer, OCR fallback,
  spreadsheet/CSV/JSON/ZIP extraction, heuristic identity/medical/legal
  analysis, template "AI" summary/tags. Audio/video are explicit stubs.
  `ProcessingJobType` already enumerates 12 job types including
  `audio_transcription` and `video_analysis`.
- **Assessment.** `AssessmentCenterService` mines facts (16 fact types) from
  uploads and Mislaka, stores them append-only with dedupe in an encrypted
  disk fact store (`PHINS_ASSESSMENT_FACT_STORE` / `/data/assessment_center`),
  and computes risk on read. Underwriting (`underwriting_risk_scoring`) and
  claims (`claims_bot_service`) are separate rule engines whose decisions are
  snapshotted via `AssessmentRecordService` (append-only).
- **AI.** One real LLM path: `AssessmentAIService`, OpenAI-compatible HTTP,
  gated by `PHINS_ASSESSMENT_AI_ENABLED` + endpoint/key, always advisory.
  Gemini/Kling HTTP integrations exist for media generation. No AI SDKs in
  `requirements.txt`.
- **Async infrastructure.** No standing worker. Render runs one monthly cron
  (`scripts/entrypoint.sh cron`); `entrypoint.sh` also supports `bi-snapshot`,
  `db-init`, `exec`. Marketplace outbox (`marketplace_outbox_events`) is a
  working transactional-event pattern with a poll consumer.
- **Security.** `security/file_scanner.py` (magic bytes, executables, macros,
  double extensions, quarantine), `confidential_access.py`, vault encryption,
  audit dual-write. Documents are served through authenticated routes, not raw
  storage URLs.

## B. Proposed integration (where the pipeline connects)

The pipeline is realized as **five targeted changes** to existing components
plus **three new modules**, not a parallel system:

```text
Existing upload APIs ──► DocumentProcessingService.upload_document (unchanged contract)
                              │  NEW: enqueue instead of _run_immediate_processing
                              ▼
                    document_processing_jobs (existing table; add attempts/priority/idempotency columns)
                              │
                              ▼
              NEW: services/document_job_worker.py  (drain loop; in-process thread
              by default, standalone via `entrypoint.sh worker` for scale-out)
                              │
        ┌──── existing parsers (pypdf/OCR/openpyxl) ── NEW: docx parser
        ├──── NEW: services/transcription_providers.py (audio → transcript)
        └──── NEW: multimodal video path (transcribe track + keyframe OCR first;
                    LLM only on the reduced representation)
                              │
                              ▼
        Document.extracted_text / extracted_metadata (existing normalized model,
        extended with pages[], tables[], transcript segments[])
                              │
                              ▼
        AssessmentCenterService.assess_document (existing fact mining,
        extended Fact provenance: page, char offsets, source_text, timestamps)
                              │
                              ▼
        Existing engines: assessment center risk, underwriting_risk_scoring,
        claims_bot, mislaka_report_generator  (unchanged decision logic)
                              │
                              ▼
        AssessmentAIService (extended: provider abstraction + JSON-schema
        validation + prompt versioning)  → advisory narrative only
                              │
                              ▼
        AssessmentRecordService (existing append-only history)
                              │
                              ▼
        Existing UI pages + evidence drill-down / processing-status panels
```

Data integrity guarantees (explicitly preserved):

1. Facts remain append-only with dedupe; assessment records are never
   overwritten (existing behavior, untouched).
2. Every fact keeps `source_document_id` + `source_document_sha256`; new
   granularity (page, offsets, timestamps) is **additive** — no migration of
   existing fact files, old facts stay valid.
3. LLM output is never written into facts or decisions; it is stored as a
   separate advisory artifact with `prompt_version`, `model`, `schema_valid`
   flags, mirroring the existing `advisory=True` contract.
4. Queue processing is idempotent: job rows carry an idempotency key
   (`sha256 + job_type`); re-delivery updates the same row, never duplicates
   documents, facts, or assessments.
5. Checksums verified before and after every parse (existing
   `verify-integrity` machinery reused).

## C. Files to add (new modules — kept to a minimum)

| File | Purpose | Approx. size |
|---|---|---|
| `services/document_job_worker.py` | Drain loop over `document_processing_jobs`: claim → run → retry with backoff (30s / 2m / 10m) → `dead_letter` status. Configurable concurrency (`PHINS_DOC_WORKER_CONCURRENCY`, default 2) and poll interval. Runs as daemon thread inside the web process by default; same module runs standalone for a dedicated worker service. | ~350 lines |
| `services/transcription_providers.py` | `AudioTranscriptionProvider` protocol + implementations: `openai_compatible` (Whisper-style `/v1/audio/transcriptions` HTTP, no SDK), existing `bridge` webhook flow, and `disabled`. Selected by `PHINS_TRANSCRIPTION_PROVIDER`. Returns `{text, language, segments[{start,end,text}]}`. | ~250 lines |
| `services/llm_providers.py` | `LLMProvider` protocol: `structured_completion(prompt, schema)` with stdlib JSON-schema validation (required keys, types, enums — no new dependency), retry-on-invalid (max 2), and escalation model option. Implementations: `openai_compatible`, `disabled`. `AssessmentAIService` becomes a consumer. | ~300 lines |
| `services/ai_usage_service.py` | Usage metering: one row per external AI/parse operation (provider, operation, pages, tokens in/out, duration, estimated cost from **configurable** unit prices `PHINS_AI_PRICE_*`). Aggregations: per document / assessment / customer / provider. Dual-write to `platform_ledger` with `ledger_type="ai_usage"`. | ~250 lines |
| `prompts/__init__.py` + `prompts/assessment/onboarding_v1.py`, `service_v1.py`, `termination_v1.py`, `unified_v1.py` | Versioned prompt templates (moved out of `assessment_ai_service.py`); registry maps `(assessment_type, version)` → template; every advisory artifact records `prompt_version`. | ~200 lines total |
| `tests/test_document_job_worker.py`, `tests/test_transcription_providers.py`, `tests/test_llm_providers.py`, `tests/test_ai_usage_service.py`, `tests/test_evidence_provenance.py` | Success/failure paths per AGENTS.md rule 6, including duplicate-delivery, retry, dead-letter, invalid-JSON-from-LLM, cross-customer access denial. | ~900 lines total |

Not added (spec items rejected as unnecessary for the PHINS stack): SQS/queue
provider SDKs, S3 client for documents, a second framework, GPU/self-hosted
OCR, LangChain or any AI SDK (all providers via plain HTTP like
`media_generation_service.py` does today).

## D. Files to modify (existing — invasiveness noted)

| File | Change | Invasiveness |
|---|---|---|
| `services/document_processing_service.py` | Add `enqueue` mode (default via `PHINS_DOC_ASYNC=true`; sync path kept for tests/small files); implement `_analyze_audio`/`_analyze_video` against the new transcription provider; add DOCX text extraction; extend parse output with `pages[]`/`tables[]` detail in `extracted_metadata`. | Medium — additive; sync fallback preserves current test behavior |
| `services/assessment_center_service.py` | Extend `Fact` with optional `page`, `char_start`, `char_end`, `source_text`, `timestamp_start`, `timestamp_end`; populate them during mining; add cross-document contradiction pass (reuse `underwriting_integrity_service` patterns) that emits `CONFLICT` facts instead of silently choosing a value. | Medium — additive dataclass fields, backward-compatible JSON |
| `services/assessment_ai_service.py` | Route through `llm_providers.py`; validate output against per-assessment-type JSON schema; record `prompt_version`/`model`/usage; keep `advisory=True` and confidence cap unchanged. | Low-medium |
| `database/models.py` | Extend `DocumentProcessingJob` (columns: `attempts`, `max_attempts`, `next_retry_at`, `priority`, `idempotency_key` unique, `worker_id`); add `AIUsageRecord` model; widen job `status` vocabulary (`pending/claimed/completed/failed/dead_letter`). | Low — new columns + one new table |
| `database/repositories/document_repository.py` | `claim_pending_jobs()` (atomic claim with row update), `get_by_idempotency_key()`, retry/dead-letter helpers. | Low |
| `database/migrations/` + `database/seeds.py` | Migration for the above; no changes to existing rows. | Low |
| `web_portal/server.py` | Wire worker thread startup (behind `PHINS_DOC_ASYNC`); add `GET /api/doc-service/jobs` status endpoint; extend `/api/health` with queue depth; emit `DOCUMENT_QUEUED`/`DOCUMENT_PARSED`/`ASSESSMENT_*` platform-ledger events at existing call sites. | Medium — small edits in a 54k-line file; highest regression-risk file, so edits are confined to upload handlers and startup |
| `web_portal/api_assessment_center.py` | Expose evidence detail + contradictions + processing status on `customer/<id>/unified` and `documents` responses; add per-assessment usage/cost summary. | Low |
| `web_portal/static/assessment-center.html`, `unified-workbench.html` | Evidence drill-down ("value → source doc, page, snippet"), processing-status column, review-queue filter, conflict badges. | Low-medium (JS/HTML only) |
| `scripts/entrypoint.sh`, `render.yaml`, `railway.json`, `Dockerfile` | Add `worker` mode; document optional dedicated worker service (off by default — in-process thread is the default). Add `ffmpeg` to Dockerfile **only in Phase 5** (audio/video). | Low |
| `AGENTS.md`, `DEPLOYMENT.md`, `ASSESSMENT_CENTER.md` | Document new env vars and operator behavior. | Low |

## E. Database changes

```text
document_processing_jobs  (existing table — additive columns)
  + attempts            INTEGER  DEFAULT 0
  + max_attempts        INTEGER  DEFAULT 3
  + next_retry_at       DATETIME NULL
  + priority            INTEGER  DEFAULT 100
  + idempotency_key     VARCHAR  UNIQUE NULL   -- sha256(file)+job_type+assessment scope
  + worker_id           VARCHAR  NULL
  status vocabulary extended: pending | claimed | completed | failed | dead_letter

ai_usage_records  (new table)
  id, created_date, customer_id, assessment_id, document_id, job_id,
  provider, operation,                -- document_parse | ocr | transcription | llm_completion
  pages, input_tokens, output_tokens, duration_ms,
  unit_price_snapshot, estimated_cost, currency,
  prompt_version, model

assessment_records  (existing — no schema change)
  new assessment_type values used: 'onboarding', 'service', 'termination'
  (column is free-text; zero migration)

facts (disk JSON store — additive optional keys, no migration)
  + page, char_start, char_end, source_text (≤300 chars),
  + timestamp_start, timestamp_end
```

Both SQLite and Postgres paths are covered by the existing
`database/config.py` resolution; the in-memory fallback keeps working because
all new columns default and the worker simply no-ops when `USE_DATABASE=false`
(sync processing path retained).

## F. Provider decision (initial configuration for the actual stack)

| Function | Recommended initial provider | Rationale |
|---|---|---|
| OCR / PDF / images | **Keep self-hosted tesseract + pypdf (already in the Docker image, heb+eng+ara)** | Zero marginal cost, Hebrew support already configured, no data leaves the platform. Managed parser (Azure Document Intelligence / Google Document AI) added later behind the same interface only if OCR quality on real Mislaka/medical scans proves insufficient. |
| DOCX | `python-docx` (one new pip dependency, ~MB scale) | Closes the biggest parsing gap at zero runtime cost. |
| Spreadsheets | Keep `openpyxl`/`xlrd` | Already real. |
| Audio transcription | **OpenAI-compatible HTTP endpoint** (`PHINS_TRANSCRIPTION_PROVIDER=openai_compatible`) with existing `bridge` webhook as alternative | Matches the existing OpenAI-compatible pattern in `assessment_ai_service.py`; works with OpenAI, Groq, Deepgram-compatible gateways, or a self-hosted Whisper endpoint by changing two env vars. |
| Video | Extract audio track → transcription; keyframe sampling → existing OCR; **no raw video to LLMs** | Implements the spec's cost rule (§10) with tools already in the image (plus `ffmpeg`). |
| LLM (advisory narratives, summaries) | OpenAI-compatible endpoint via `llm_providers.py`; default model cost-efficient tier; optional `PHINS_LLM_ESCALATION_MODEL` used only on low confidence / conflicts | Preserves vendor neutrality; Anthropic/Gemini adapters are ~50-line additions later. |

All prices configurable via env (`PHINS_AI_PRICE_TRANSCRIPTION_PER_MIN`,
`PHINS_AI_PRICE_INPUT_PER_MTOK`, `PHINS_AI_PRICE_OUTPUT_PER_MTOK`,
`PHINS_AI_PRICE_PARSE_PER_PAGE`) — never hard-coded, per spec §22.

## G. Implementation order (safest incremental sequence)

Each phase is independently shippable, tested, and leaves the platform fully
working. Phases map to the spec's §29 but re-scoped to what is missing.

1. **Phase 1 — Async backbone.** Job-table columns + migration, worker module,
   enqueue mode (default off → on after tests), retries/dead-letter,
   idempotency keys, queue-depth in `/api/health`, platform-ledger events.
   *Risk: low. No behavior change until `PHINS_DOC_ASYNC=true`.*
2. **Phase 2 — Parsing completeness.** DOCX parser, pages/tables detail in
   `extracted_metadata`, richer `Fact` provenance (page/offset/source_text),
   contradiction pass emitting `CONFLICT` facts. *Risk: low-medium (touches
   fact mining; covered by new provenance tests).*
3. **Phase 3 — LLM hardening.** `llm_providers.py`, JSON-schema validation,
   prompt versioning under `prompts/`, escalation rule, review thresholds
   read from `ai_threshold_config.py` (configurable: ≥0.90 auto-accept,
   0.70–0.89 flagged, <0.70 review). *Risk: low — advisory path only.*
4. **Phase 4 — Cost tracking + UI.** `ai_usage_records`, aggregation
   endpoints, evidence drill-down and processing-status UI, review queue.
   *Risk: low.*
5. **Phase 5 — Multimodal.** Transcription provider, audio jobs, video
   audio-track + keyframe pipeline, timestamped evidence, `ffmpeg` in
   Dockerfile. *Risk: medium (new external dependency surface; feature-flagged
   per provider).*
6. **Phase 6 — Scale-out (only if measured load requires).** `worker`
   entrypoint mode as a dedicated Railway/Render service, per-provider rate
   limits, load tests, optional managed-parser adapter, optional
   direct-to-storage uploads. *Risk: low — pure ops addition.*

Testing per phase: targeted pytest files above + `pytest tests/test_api_integration.py
tests/test_database.py`, `python3 web_portal/server.py --test`, and the
security cases from spec §30 (cross-customer denial, unsigned access,
oversized/invalid MIME, duplicate queue delivery).

---

## Cost model (decision inputs)

Assumptions for sizing: 100,000 customers × 2 assessments × 10 documents avg
= **2M documents lifetime**, bursty. Unit prices below are *indicative
mid-2026 list prices* — the system stores them as configurable env values and
snapshots the price on every usage row.

| Operation | Provider class | Indicative unit price | Cost per 1,000 assessments (10 docs, ~8 pages each) |
|---|---|---|---|
| OCR + parse (self-hosted tesseract) | none (CPU already paid) | $0 marginal | **$0** (+ CPU time, see memory/CPU section) |
| OCR + parse (managed, if later adopted) | Azure DI / Google Doc AI "read" tier | ~$1.5 / 1,000 pages | ~$120 |
| Managed layout/tables tier | Azure DI layout | ~$10 / 1,000 pages | ~$800 — **avoid by default; per-document opt-in only** |
| Audio transcription | Whisper-class API | ~$0.006 / minute | ~$60 per 1,000 assessments if each includes one 10-min call recording |
| LLM advisory narrative | cost-efficient tier (~$0.15–0.60 / M input tokens) | ~6k in + 1k out tokens per assessment | **$2–8** |
| LLM escalation model | premium tier (~$3–15 / M input tokens) | applied to <10% of assessments | ~$5–15 |

Bottom line: with the recommended defaults (self-hosted OCR, LLM advisory
only, transcription only when audio exists), the marginal AI cost is on the
order of **$0.01–0.10 per assessment**, dominated by transcription minutes
when present. The expensive failure modes the spec warns about (raw video to
LLMs, layout-tier parsing of every page, one giant prompt with every file)
are structurally excluded by the design.

Engineering cost (invasiveness, not calendar time): ~1,350 lines of new
service code + ~900 lines of tests + additive schema migration + confined
edits in `server.py` upload/startup paths. No rewrite of any existing engine,
route contract, or storage layout.

## Memory & resource impact

Current liabilities (measured from code, not speculation):

- Base64-in-JSON uploads hold ~2.3× the file size in RAM per request (JSON
  body + decoded bytes); `_stream_multipart_to_disk` also reads the full body.
  A 50MB upload ≈ ~120MB transient RSS in the single web process.
- Synchronous OCR at upload time: `pdf2image` rasterizes pages (~4–8MB per
  page at default DPI); a 30-page scanned PDF can transiently use 150–250MB
  and block the handler thread for tens of seconds.
- Legacy stores (`POLICY_DOCUMENTS`, `CLAIM_FILES`, `UNDERWRITING_FILES`) keep
  base64 copies resident in process memory for the process lifetime.

Post-change profile:

- Upload handler returns after disk write + checksum + scan (§ Phase 1):
  transient memory bounded by upload size only; handler latency drops from
  seconds-to-minutes to sub-second.
- Worker memory is bounded and configurable: `concurrency × max_page_image`
  ≈ 2 × ~8MB pages ≈ **well under 200MB steady-state** with default
  `PHINS_DOC_WORKER_CONCURRENCY=2` and existing `PHINS_OCR_MAX_PDF_PAGES` /
  `PHINS_OCR_MAX_IMAGE_BYTES` caps enforced.
- Queue-based backpressure (claim-limit + priority) protects the DB, provider
  rate limits, and cost exposure exactly as spec §27 requires — a burst of
  10,000 uploads queues rather than forking 10,000 OCR runs.
- Recommended (separate, optional follow-up): stop writing new base64 blobs
  into `POLICY_DOCUMENTS`-style in-memory stores and reference
  `DocumentProcessingService` IDs instead. This is the single largest
  steady-state memory reduction available, but it touches legacy read paths,
  so it is scoped as its own change with its own tests.

## Effects on existing behavior

- **No breaking API changes.** All upload routes keep their request/response
  contracts; a `processing_status` field they already expose becomes
  meaningful (`queued → processing → parsed/needs_review/failed`).
- **Deterministic engines untouched.** Underwriting, claims, billing, and
  Customer 360 risk logic are not modified; they gain better inputs (more
  fact types, provenance, conflict facts) and their outputs continue to be
  snapshotted append-only.
- **Test harness unaffected.** With `PHINS_DOC_ASYNC` defaulting off in
  `PHINS_TEST_MODE`, the embedded-server pytest suite keeps its current
  synchronous semantics; async behavior gets its own tests.
- **Security posture unchanged or improved.** Same scanner, same
  authenticated serving (no raw URLs), plus: LLM payload minimization (only
  extracted snippets, never whole raw documents), no sensitive content in
  logs, audit rows for every job transition, usage rows for every external
  call.

## Open decisions for the owner (before coding starts)

1. **Worker topology:** in-process daemon thread (zero infra cost, dies with
   web dyno) vs. dedicated Railway/Render worker service (~one extra small
   instance/month). Recommendation: start in-process, promote in Phase 6.
2. **Transcription provider + jurisdiction:** which OpenAI-compatible endpoint
   is acceptable for customer audio (data-residency), or keep `bridge`/manual.
3. **Managed parser trigger:** accept self-hosted OCR quality initially, with
   a measured-quality gate (e.g. fact-extraction confidence distribution)
   deciding whether to pay for a managed parser tier.
4. **Legacy base64 store deprecation:** approve as a follow-up work item or
   defer.

---

Last updated: August 18, 2026. All file paths, env vars, and behavior claims
in this document were verified against the repository at the time of writing.
