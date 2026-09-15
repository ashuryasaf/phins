# AGENTS.md - PHINS Agent Playbook

Use this file as concise, repo-specific guidance for PHINS contributions.
Keep changes narrow, follow existing patterns, and let direct user instructions
override this document.

## 1) Quick Mental Model

PHINS is a Python platform built around:

- a large `BaseHTTPRequestHandler` app in `web_portal/server.py` (~50k lines)
- optional extension routing in `web_portal/api_extensions.py` (~3450 lines)
  and domain-specific API modules (`api_bi_analytics.py`,
  `api_delivery_bidding.py`, `api_agent_ecosystem.py`,
  `api_assessment_center.py`)
- service-layer logic in `services/` (113 top-level modules plus the `automation/`, `customer_agent/`, `jobs/`, `underwriting_bot/`, `pension/` and `risk_reports/` packages)
- database access in `database/`
- security utilities in `security/`
- scheduled tasks in `scheduler/`
- operational scripts in `scripts/`
- both `tests/test_*.py` (233 files) and root-level `test_*.py` (11 files)
- one generalized job queue (`services/agent_job_queue.py`, table
 `document_processing_jobs`, rows keyed by `subject_type`/`subject_id` and
 `submitted_by`; retries, dead-letter, idempotency keys, handler registry —
 a worker only claims job types it has a handler for). Documents enqueue
 enrichment under `PHINS_DOC_ASYNC=true` via the `document_job_worker.py`
 binding; the agent routes (claims probability report, underwriting
 AI-assess, risk-report analyze/generate, Mislaka import, video submit)
 enqueue under `PHINS_AGENT_ASYNC=true` via `services/jobs/*_job.py`
 adapters and answer `202 {job_id, status, poll_url}`; clients poll
 `GET /api/jobs/{id}` (submitter or staff only, 404 otherwise) —
 dashboards do this through `static/agent-jobs.js` (`phinsAwaitJob`).
 With the flags off the same adapter functions run inline (golden parity).
- durable agent state (`services/hydrated_store.py`, A4): each agent's own
 working records — Claims Bot probability reports, Underwriting Bot
 assessments/metadata/reports, AI Risk Reports documents/analyses/reports —
 live in `agent_artifacts` (one generic table, lossless dataclass codec,
 sha256 checksum verified on load) and Video Agents jobs in `video_jobs`,
 behind a `HydratedStore` read-through cache (TTL-coalesced incremental
 hydration by `updated_date`, periodic full resync, durable write before
 cache write; a failed durable write is reported and retained, never
 silently dropped). Retention caps are DB-side prunes. In memory mode the
 same objects are plain per-instance dicts, so both flows behave as before.
 Because that state is durable, `entrypoint.sh worker` binds every agent
 adapter over the database-backed stores (`services.jobs.worker_context`).
 Facts carry evidence provenance (source snippet, char offsets, PDF page,
 audio/video timestamps) and cross-document contradictions are recorded as
 `contradiction` facts, never silently resolved
- an evaluation and calibration loop (`services/agent_eval.py`, A6): agent
 decisions are **replayed** read-only against recorded human outcomes
 (`ai_decision_log` overrides for the automation controller, `claims_fraud`
 assessment records for the Claims Bot) into per-segment
 precision/recall/confusion reports; `propose_thresholds` only
 **recommends** cut-offs (target precision, monotone, evidence floor — never
 into a score band nobody reviewed) and promotion is a separate audited
 admin step (`POST /api/admin/ai-agents/thresholds/promote` writes
 before/after to `ai_decision_log` and the audit trail, fail-closed).
 Golden sets in `tests/golden/<agent>/*.json` freeze the listed `expected`
 keys per agent and gate CI (`.github/workflows/agent_golden_sets.yml`,
 `scripts/run_agent_eval.py golden`); `--update` is a deliberate, reviewed
 change, never an automatic one
- rule/orchestration split for the automation controller (B2): the pure rules
 live in `services/automation/{quoting,underwriting_gate,fraud,claims_gate,
 billing_schedule,types}.py`; `ai_automation_controller.py` orchestrates
 (metrics, decision log, registry) and re-exports every historical name.
 Underwriting results carry `segment`, `confidence_band`, `threshold_margin`.
 `billing_schedule.invoice_due_date` is the single due-date path
- prompt provenance (B3): every registered `PromptTemplate` exposes
 `provenance()` (`prompt_id`, `prompt_version`, `prompt_version_number`,
 `prompt_sha256`) and the Assessment AI stamps it, plus `schema_id` and any
 `fallback_reason`, on the narrative, the audit record and the persisted
 artefact; `narrative-v2` is structured (`schemas/assessment_narrative.json`)
 and a schema-invalid or unavailable LLM reply falls back to the
 deterministic narrative rather than an unvalidated one
- a shared evidence pipeline for the Underwriting Bot and the Claims Bot (B1):
 `services/evidence_facts.py` is the read side of the fact store
 (`facts_for`, `bundle_for_entity`, SHA-keyed `FeatureCache`); a metadata item
 linked to a `document_id` consumes the pipeline's facts with provenance
 (bytes still win when supplied) and a recorded contradiction sends it to
 `SUSPICIOUS` / lowers the claim document score — never resolved by a bot.
 Audio goes through `transcription_providers` (`NO_STT_AVAILABLE` only when
 disabled, `STT_FAILED` on provider error). Both bots log every
 recommendation to `ai_decision_log` (`underwriting_bot_assessment`,
 `claims_bot_assessment`) with `rule_score` / `model_score` / `divergence`
 from `services/model_shadow.py` — the registry model (`uw_scorer`,
 `claims_scorer`) never changes a decision; p95 drift over
 `PHINS_AI_DRIFT_THRESHOLD` writes an `ai_model_drift` audit row once per
 episode. Human `apply_decision` counter-decisions are recorded as overrides,
 so `evaluate('underwriting_bot')` replays them. The bot lives in
 `services/underwriting_bot/{report,features,service}.py`;
 `services/underwriting_bot_service.py` is the re-exporting facade
- fact-store indexes and an OCR page cache (B4): `AssessmentCenterService`
 keeps `_by_document` / `_by_field` indexes (`facts_for_documents`,
 contradiction detection as bucket lookups); `DocumentProcessingService`
 caches OCR per `(sha256, page, langs, dpi)` and fans pages out over
 `PHINS_OCR_POOL_SIZE` threads — a failed page is never cached
- the Pension Data Agent as a package (B5): `services/pension/{schema,profile,
 parsers,report,cache,agent}.py`, with `services/pension_data_agent.py` the
 re-exporting facade (`MislakaSchemaMapping` still imports from there). Tag
 spellings are precompiled once (`CompiledFields`), `_find_text` reads a
 per-parse thread-local text index, and files at or above
 `PHINS_PENSION_STREAM_MIN_BYTES` (8 MiB) go through the `defusedxml`
 `iterparse` path that harvests and releases one provider block at a time —
 same output as the tree parser, malformed XML and entities still rejected.
 `ParseResultCache` keys the *parser output* (XML dict, ZIP profile) by
 `sha256 + PARSER_VERSION` in a process LRU plus `agent_artifacts`
 (`pension_data_agent` / `parse_result`) in DB mode; values are deep-copied
 both ways, a bad checksum or old version is skipped, and the durable tier
 pauses 60 s after a DB error. Bump `PARSER_VERSION` when parser output
 changes
- AI Risk Reports as a package (B9): `services/risk_reports/{models,parsers,
 analysis,charts,render,service}.py`; `services/ai_risk_reports_service.py`
 is the facade and forwards `AI_REPORTS_DATA_FILE` and the singleton slot in
 both directions, so patching the facade still steers the service.
 `parse_content()` is the pure dispatcher `parse_file()` wraps. PDF and
 image text comes from `DocumentProcessingService` (pypdf → regex → OCR with
 the B4 page cache) as `page_N_text` / `ocr_text` rows plus `parsed['text']`
 and `text_pages`; when present it decides the analysis language and feeds
 Hebrew field extraction. Charts are client-rendered JSON configs built
 eagerly (0.03–0.16 ms; no lazy render or chart cache by design)
- customer-facing agents as a package (B6): `services/customer_agent/
 {communication,service_desk,interaction_log,consent,escalation}.py`;
 `services/customer_communication_agent.py` and root `service_agent.py` are
 shims (agent ids `customer_communication` / `customer_service` unchanged).
 Both facades write every touch to one `InteractionLog` (`agent_artifacts`
 `customer_agent` / `interaction`, durable in DB mode) — `pending` before the
 provider call, `sent` / `failed` / `refused` after, recipients masked. A
 WhatsApp/SMS send passes `MessagingPolicy.authorize` first: relational copy
 (`message`, `offer`) needs consent on file (explicit `ConsentRegistry` entry,
 else customer-record flags), transactional copy (`welcome`, `bill`,
 `reminder`, service acks) is blocked only by an explicit opt-out, and the
 per-customer daily cap counts durable `sent` + `pending` rows. An OTP
 verified against the WhatsApp number is recorded as `otp_verified` consent.
 Escalations go through `EscalationDesk` (durable record → `AuditService`
 `customer_agent.escalated` → timeline row). Service-desk copy lives in the
 process-wide `TemplateEngine` registry (`register_template` /
 `render_registered`). Admin surfaces: `POST /api/admin/customers/{id}/consent`,
 `GET /api/admin/customers/{id}/interactions`; use `customer_record=` when
 calling `send_customer_outreach` so record flags are honoured
- marketing plans are content-addressed and ledger-anchored (B7):
 `compute_input_hash` (scope + BI signals + cohorts + `PLAN_VERSION`) seeds
 the `campaign_id`, sits inside the signed payload and keys an in-process
 LRU; `anchor_publication` appends `marketing_campaign_published` to the
 platform ledger **before** any publish side effect (409 on integrity
 mismatch, 503 on ledger failure), `verify_publication` re-checks `/latest`.
 BI cohorts (`derive_cohorts`) are opt-in per request (`cohorts=1`)
- delivery bidding (B11): a pure-Python geohash index over open requests
 (`find_open_requests_near`), supplier eligibility by haversine radius when
 coordinates exist, `reliability_for` blends self-reported on-time % with
 executed settlement outcomes (`SupplierSettlementService.get_settled_outcomes`,
 ≥ 3 settled orders), and `expire_bidding_windows` closes elapsed windows
 exactly once (`BIDDING_CLOSED` / `CANCELLED`) with one
 `delivery.bidding_window_closed` outbox event — driven by the
 `delivery_bidding_sla_tick` self-rescheduling queue row (`ensure_sla_clock`)
 and lazily on read/bid. `/api/delivery/*` is wired through
 `web_portal/api_delivery_bidding.py` with customer/supplier/admin scoping

Runtime defaults are important:

- `web_portal/server.py` defaults to `USE_DATABASE=true`
- pytest config in root `conftest.py` sets `USE_DATABASE=false`,
  `USE_SQLITE=true`, `PHINS_TEST_MODE=true`, and starts an embedded server on
  `127.0.0.1`; the port prefers `8000` but honors a `TEST_PORT` override and
  falls back to a free kernel-assigned port (read `TEST_BASE_URL`/`TEST_PORT`
  instead of hardcoding `http://localhost:8000`)
- a separate `tests/conftest.py` only adds `sys.path` and sets
  `PHINS_TEST_MODE`; the embedded server and env defaults live in the
  **root** `conftest.py`
- many features still have in-memory/demo behavior, so preserve compatibility
  with both database-backed and in-memory flows unless the task explicitly says
  otherwise

Preferred file-by-task:

| Task | Start here |
|---|---|
| API route/response change | `web_portal/server.py`, then `web_portal/api_extensions.py` |
| BI/analytics API | `web_portal/api_bi_analytics.py`, `services/bi_analytics_service.py` |
| Delivery/bidding API | `web_portal/api_delivery_bidding.py`, `services/delivery_bidding_service.py` |
| Customer messaging / consent / escalation | `services/customer_agent/`, `web_portal/server.py` (`/api/admin/customers/{id}/contact`, `.../consent`, `.../interactions`) |
| Agent ecosystem API | `web_portal/api_agent_ecosystem.py`, `services/agent_ecosystem_service.py` |
| Assessment center API | `web_portal/api_assessment_center.py`, `services/assessment_center_service.py` |
| Business rule/workflow | `services/`, then the route or engine that calls it |
| Database/schema/repository | `database/models.py`, `database/manager.py`, `database/repositories/`, `database/config.py` |
| Billing/accounting behavior | `billing_engine.py`, `accounting_engine.py`, related tests |
| Security/auth/tokens | `security/`, `web_portal/server.py` (session/login routes) |
| Scheduled jobs | `scheduler/runner.py`, `scripts/run_monthly_auto_pay.py` |
| Test harness/debugging | root `conftest.py`, affected `tests/test_*.py`, root `test_*.py` |
| Deployment/config | `DEPLOYMENT.md`, `RAILWAY_*.md`, `railway.json`, `render.yaml`, `Dockerfile` |
| Agent decision rules (quote/underwrite/fraud/claims/billing) | `services/automation/*.py`, then `ai_automation_controller.py`; refresh `tests/golden/ai_automation_controller/` deliberately |
| Agent thresholds / calibration | `services/agent_eval.py`, `services/ai_threshold_config.py`, `web_portal/api_extensions.py` (`/api/admin/ai-agents/eval`, `/thresholds/promote`) |
| LLM prompts / structured output | `prompts/`, `schemas/*.json`, `services/llm_providers.py`, `services/assessment_ai_service.py`; refresh `tests/golden/assessment_ai/` deliberately |
| Underwriting Bot / Claims Bot evidence | `services/evidence_facts.py`, `services/underwriting_bot/*.py`, `services/claims_bot_service.py`, `services/model_shadow.py`; tests in `tests/test_evidence_pipeline.py` |
| Mislaka / pension parsing | `services/pension/{schema,parsers,cache,agent}.py` (facade `services/pension_data_agent.py`); tests in `tests/test_pension_agent.py` |
| Risk Reports intake / analysis / report text | `services/risk_reports/{parsers,analysis,render,charts,service}.py` (facade `services/ai_risk_reports_service.py`); tests in `tests/test_risk_reports_package.py`, `tests/test_ai_risk_reports.py` |

## 2) High-Value Paths

```text
/workspace
|- AGENTS.md
|- README.md
|- DEPLOYMENT.md
|- requirements.txt
|- conftest.py                          # pytest embedded server + env defaults
|- config.py                            # root config module
|- billing_engine.py
|- accounting_engine.py
|- validate_system.py
|- validate_external_services.py
|- check_database_connection.py
|- init_database.py                     # DB bootstrap / schema init
|- web_portal/
|  |- server.py
|  |- api_extensions.py
|  |- api_bi_analytics.py
|  |- api_delivery_bidding.py
|  |- api_agent_ecosystem.py
|  |- api_assessment_center.py
|  |- connectors.py
|  `- static/                           # HTML/JS/CSS dashboards and assets
|                                        # (includes `static/locales/he.json` Hebrew i18n)
|- ai_automation_controller.py          # orchestration only; rules in services/automation/
|- prompts/                             # versioned LLM prompt templates (sha256 provenance)
|  `- assessment/                       # narrative v1 (free text) + v2 (structured); onboarding/service/termination v1
|- schemas/                             # JSON schemas for structured LLM output
|- services/                            # 111 service modules
|  |- agent_eval.py                     # A6 replay / propose_thresholds / golden sets
|  |- automation/                       # B2 pure rules: quoting, underwriting_gate, fraud, claims_gate, billing_schedule
|  |- underwriting_bot/                 # B1 package: report (model+engine), features (analyzers), service
|  |- underwriting_bot_service.py       # facade re-exporting the package
|  |- evidence_facts.py                 # B1 shared evidence pipeline (facts_for, bundles, FeatureCache)
|  |- model_shadow.py                   # B1 shadow scoring + drift monitor (never decides)
|  |- pension/                          # B5 package: schema (mapping + CompiledFields), parsers (tree + iterparse), cache, report, agent
|  |- pension_data_agent.py             # facade re-exporting the package
|  |- risk_reports/                     # B9 package: models, parsers (DocumentProcessingService text), analysis, charts, render, service
|  |- ai_risk_reports_service.py        # facade (two-way forwarding of AI_REPORTS_DATA_FILE / singleton)
|  |- customer_agent/                   # B6 package: communication + service_desk facades, interaction_log, consent, escalation
|  |- customer_communication_agent.py   # shim -> customer_agent.communication
|  |- agent_job_queue.py                # generalized job queue (retry/DLQ/handlers)
|  |- document_job_worker.py            # document binding over the job queue
|  |- jobs/                             # agent job adapters (202 routes; worker_context)
|  |- hydrated_store.py                 # A4 read-through cache over durable agent tables
|  |- llm_providers.py                  # vendor-neutral LLM + schema validation
|  |- transcription_providers.py        # audio speech-to-text abstraction
|  |- external_call_gateway.py          # cache/budget/breaker/retry for provider HTTP
|  |- circuit_breaker.py                # shared breaker (gateway + SMTP)
|  `- ai_usage_service.py               # AI/parse cost metering (agent_id, blocked)
|- database/
|  |- config.py
|  |- manager.py
|  |- models.py
|  |- marketplace_models.py
|  |- notification_models.py
|  |- data_access.py
|  |- seeds.py
|  |- migrate_data.py
|  |- migrations/
|  |- repositories/                     # 20 *_repository.py + base.py
|- security/
|  |- vault.py
|  |- auth_tokens.py
|  |- headers.py
|  |- network.py
|  |- secrets_policy.py
|  |- firewall.py
|  |- intrusion_detector.py
|  |- request_sanitizer.py
|  |- file_scanner.py
|  |- confidential_access.py            # gate for /internal/ + /legal/ docs
|  `- migrate_passwords.py
|- scheduler/
|  `- runner.py
|- scripts/                             # operational utilities
|  |- run_agent_eval.py                 # golden sets + decision replay CLI
|  `- entrypoint.sh                     # container dispatcher (serve/cron/worker/db-init)
|- tests/                               # 225 test files
|  `- golden/<agent>/*.json             # frozen agent outputs ({name, input, expected})
|- docs/
|  |- platform_data_architecture.md
|  |- health_marketplace_architecture.md
|  |- health_marketplace_implementation_spec.md
|  |- agent_ecosystem_design.md
|  |- ai_surface_design_principles.md
|  |- INVESTOR_AI_BI_OPTIMIZATION_REVIEW.md
|  `- uml/
`- .github/workflows/                   # CI (visual_test, security_scan, agent_golden_sets)
```

Start with adjacent code before adding helpers, modules, or abstractions.
`web_portal/server.py` is large and multi-purpose; many patterns are still
implemented inline rather than behind controller-style boundaries.

## 3) Hard Rules

1. Keep route handlers thin where practical.
2. Reuse existing services, repositories, and helper functions first.
3. Preserve JSON error responses as `{ "error": "..." }`.
4. Preserve paginated responses shaped like
   `{ "items": [], "page": 1, "page_size": 50, "total": 0 }` where applicable.
5. Avoid touching unrelated files, even if they are already modified.
6. Add or update tests for behavior changes.
7. Never hardcode secrets, credentials, or environment-specific values.
8. Be careful about cross-customer or cross-tenant data leakage.

## 4) Existing Patterns Worth Reusing

Helpers already in `web_portal/server.py`:

```python
status_eq(item, "approved", "paid")
status_in(item, ["pending", "under_review"])
get_status_lower(item)
safe_float(value, default=0.0)
safe_int(value, default=0)
normalize_marketplace_category(value)
normalize_payment_method(value)
normalize_percentage_input(value, default_value)
get_customer_display_name(customer_id)
get_customer_with_fallback(customer_id)
```

Database patterns:

- Use `DatabaseManager` in `database/manager.py` for repository access.
- Prefer `DatabaseManager.session_scope()` for grouped transactional work.
- Repository writes may auto-commit; read surrounding code before composing
  multiple repository operations.
- `database/config.py` resolves `DATABASE_URL` first, then SQLite settings such
  as `USE_SQLITE` and `SQLITE_PATH`.

`DatabaseManager` repositories (as properties):

- Core: `customers`, `policies`, `claims`, `underwriting`, `billing`
- Auth/audit: `users`, `sessions`, `audit`, `tokens`
- Platform: `platform_ledger`, `actuarial`
- Documents: `documents`, `processing_jobs`
- Supply chain: `suppliers`, `supplier_invitations`, `supplier_offers`,
  `supplier_orders`, `supplier_documents`, `supply_chain_ledger`
- Marketplace/payments: `wallet_accounts`, `wallet_holds`, `wallet_ledger`,
  `payment_intents`, `refunds`, `journal`, `supplier_settlement_runs`,
  `supplier_settlement_items`, `external_payers`, `marketplace_claims`,
  `remittances`, `payer_receivables`, `idempotency`, `outbox`
- Agent ecosystem: `agents`, `agent_invitations`, `agent_affiliations`,
  `agent_commissions`, `agent_payouts`
- Assessment loop / intake / AI cost: `assessment_records`,
  `business_inquiries`, `ai_usage`
- Durable agent state (A4): `agent_artifacts`, `video_jobs`

Common ID prefixes:

- Company: `COM`
- Customer: `CUST`
- Policy: `POL`
- Claim: `CLM`
- Bill: `BILL`
- Order: `ORD`
- Document: `DOC`
- Audit: `AUDIT` / `AUD`
- Ledger: `LEDGER`
- Credit: `CREDIT`
- Agent: `AGT` (invitation `AGI`, affiliation `AFF`, commission `COMM`,
  payout run `APAY`, agent ledger `AGLEDGER`, platform-ledger payout anchor
  `AGPAY-{payout_id}`)

## 5) API Task Playbook

When changing or adding an API endpoint:

1. Inspect the surrounding route in `web_portal/server.py` first.
2. Check whether the endpoint belongs in `server.py`,
   `web_portal/api_extensions.py`, `web_portal/api_bi_analytics.py`,
   `web_portal/api_delivery_bidding.py`, `web_portal/api_agent_ecosystem.py`,
   or `web_portal/api_assessment_center.py`.
3. Verify the extension is actually wired; `server.py` imports extension
   dispatchers conditionally and can run without them.
4. Reuse service-layer logic from `services/` instead of embedding new business
   rules directly in the handler.
5. Validate request payloads and preserve response shape conventions.
6. Confirm whether related dashboard, billing, underwriting, or ledger behavior
   depends on the same data.
7. Add success and failure-path tests.

Watch-outs:

- This is **not** Flask or FastAPI; it uses `BaseHTTPRequestHandler`.
- Changes to handler initialization, port assumptions, or shared module state can
  break many tests.
- Some routes have parallel in-memory and database-backed logic paths.
- `api_extensions.py` covers foundations, OTP/CAPTCHA, contribution payments,
  community messaging, wallet, admin foundation routes, backup/persistence,
  invitation handling, and media/video processing jobs and webhooks.

## 6) Database Task Playbook

When changing persistence or schema behavior:

1. Inspect `database/models.py`, `database/manager.py`, and the relevant
   repository in `database/repositories/`.
2. Update related models, repositories, and dict-compatibility code together if
   the schema affects both DB and in-memory flows.
3. Review `database/seeds.py`, initialization, and migration helpers
   (`database/migrate_data.py`, `database/migrations/`) when schema changes.
4. Check `database/notification_models.py` if notification-related tables are
   involved.
5. Preserve compatibility with the in-memory fallback unless the task explicitly
   removes it.
6. Run database-focused tests plus at least one broader workflow check.

Key facts:

- Storage modes include in-memory, SQLite, and PostgreSQL.
- `DatabaseManager` exposes 43 repository properties (see §4 for the full list).
- Repository modules (20 `*_repository.py` + `base.py`):
  `customer_repository.py`, `policy_repository.py`, `claim_repository.py`,
  `underwriting_repository.py`, `billing_repository.py`,
  `user_repository.py`, `session_repository.py`, `audit_repository.py`,
  `platform_ledger_repository.py`, `actuarial_repository.py`,
  `token_repository.py`, `document_repository.py`, `supplier_repository.py`
  (bundles supplier, invitation, offer, order, document, and supply-chain
  ledger repositories), `marketplace_repository.py` (bundles wallet,
  payment-intent, refund, journal, settlement, external-payer,
  marketplace-claim, remittance, receivable, idempotency, and outbox
  repositories), `agent_repository.py` (bundles agent, agent-invitation,
  agent-affiliation, agent-commission, and agent-payout repositories),
  `assessment_record_repository.py`, `business_inquiry_repository.py`,
  `ai_usage_repository.py`, `agent_artifact_repository.py` (generic durable
  agent state, sha256-checksummed payloads verified on load, DB-side prune)
  and `video_job_repository.py` (video job lifecycle; `mark_terminal` is a
  conditional UPDATE so exactly one racer wins).
- Connection handling includes recovery logic; avoid bypassing existing session
  patterns without a clear reason.

## 7) Deployment Task Playbook

When working on deployment or environment configuration:

1. Read `DEPLOYMENT.md` and any relevant `RAILWAY_*.md` file first.
2. Verify the actual deployment files before editing assumptions:
   - `railway.json`
   - `render.yaml`
   - `Dockerfile`
   - `app.json`, `vercel.json`
3. Confirm how the app starts in production before changing commands or ports.
4. All manifests dispatch through `scripts/entrypoint.sh`
   (`serve` runs `python3 web_portal/server.py`; other modes: `cron`,
   `worker` (standalone async document worker, requires `USE_DATABASE=true`),
   `bi-snapshot` (KPI snapshot + materialized `/api/bi/*` views;
   `--snapshot-only` / `--materialize-only`), `db-init`, `shell`, `exec`).
   Keep startup behavior compatible with it unless the task explicitly
   changes the entrypoint.
5. Document any environment-variable or operator-facing changes.

Railway-specific docs (6 files):
`RAILWAY_DEPLOYMENT.md`, `RAILWAY_QUICKSTART.md`,
`RAILWAY_POSTGRES_SETUP.md`, `RAILWAY_POSTGRES_FIX.md`,
`RAILWAY_DEPLOYMENT_COMPLETE.md`, `RAILWAY_REDEPLOY_REQUIRED.md`

Additional deployment docs:
`DEPLOYMENT_CHECKLIST.md`, `DEPLOYMENT_VALIDATION.md`,
`DEPLOYMENT_READY_REPORT.md`

Environment variables commonly used:

- **Database:** `USE_DATABASE`, `DATABASE_URL`, `DATABASE_PUBLIC_URL`,
  `USE_SQLITE`, `SQLITE_PATH`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
  `DB_PASSWORD`
- **Server:** `PORT`, `HOST`, `BASE_URL`, `PHINS_ENVIRONMENT`,
  `POPULATE_DEMO_DATA`
- **Test:** `PHINS_TEST_MODE`, `TEST_BASE_URL`, `TEST_PORT`,
  `PHINS_ACTUARIAL_STATE_PATH`, `PHINS_INVITATION_CODES_PATH`,
  `PHINS_BI_SNAPSHOT_DIR`
- **Ledger:** `ENABLE_LEDGER_PERSISTENCE`, `LEDGER_PERSISTENCE_VERBOSE`,
  `LEDGER_PERSISTENCE_LOG_INTERVAL`, `PHINS_LEDGER_DB_AUTOREPAIR`
- **Media:** `MEDIA_PROVIDER_WEBHOOK_SECRET`, `DEFAULT_MEDIA_SUBTITLE_PROVIDER`,
 `DEFAULT_MEDIA_VIDEO_PROVIDER`, `PHINS_MEDIA_INLINE_MAX_BYTES`,
 `PHINS_MAX_MEDIA_UPLOAD_SIZE` (0 = no HTTP cap),
 `PHINS_DEFAULT_MEDIA_ASSET_MAX_BYTES` (scanner/disk cap, default 2GB)
- **Video agents (B8):** `VIDEO_AGENTS_COMPLETION_MODE` (`webhook` default,
 `poll`; webhook resolves to poll without a `WEBHOOK_BASE_URL`),
 `VIDEO_AGENTS_POLL_TIMEOUT` (fail a job still in flight after this many
 seconds, default 1800), `MEDIA_WEBHOOK_REPLAY_WINDOW_SECONDS` (callback
 timestamp tolerance, default 300); polls ride the agent queue when
 `PHINS_AGENT_ASYNC` is on, and `rearm_media_video_jobs()` resumes
 in-flight jobs at boot
- **BI analytics (B10):** `PHINS_BI_SNAPSHOT_DIR` also holds
 `materialized_views.json` (served by `/api/bi/*` when fingerprint, checksum
 and age < cache TTL all match); `PHINS_BI_REMATERIALIZE_DELAY_SECONDS`
 (debounce for the write-triggered `bi_materialize` queue job, default 5).
 `DatabaseDict.content_version()` / `add_write_listener` in
 `database/data_access.py` are the DB-mode write hooks; `mark_ledger_dirty()`
 is the in-memory one
- **Job queue:** `PHINS_DOC_ASYNC` (documents enqueue enrichment instead of
 inline processing; default off), `PHINS_AGENT_ASYNC` (agent routes answer
 202 + `poll_url`; default off), `PHINS_DOC_WORKER_CONCURRENCY` (base
 threads), `PHINS_JOB_WORKER_MAX_CONCURRENCY` (burst ceiling),
 `PHINS_JOB_WORKER_IDLE_POLLS`, `PHINS_DOC_WORKER_POLL_INTERVAL`,
 `PHINS_DOC_RETRY_SCHEDULE`, `PHINS_DOC_CLAIM_TIMEOUT`,
 `PHINS_WORKER_AGENT_JOBS` (standalone worker also drains agent jobs;
 default true)
- **Durable agent state:** `PHINS_AGENT_HYDRATE_TTL` (read-path refresh
 coalescing, default 1.5s; shared with AgentOS),
 `PHINS_AGENT_FULL_RESYNC_SECONDS` (full re-pull that reflects peer
 deletions, default 60)
- **OCR / evidence (B4, B1):** `PHINS_OCR_POOL_SIZE` (page fan-out, default
 2), `PHINS_OCR_CACHE_MAX_ENTRIES` (default 2000),
 `PHINS_EVIDENCE_FEATURE_CACHE_MAX` (default 4096)
- **Model shadow (B1):** `PHINS_AI_DRIFT_THRESHOLD` (p95 divergence, default
 0.25), `PHINS_AI_DRIFT_WINDOW` (200), `PHINS_AI_DRIFT_MIN_SAMPLES` (20),
 `PHINS_MODEL_DIR` (registry artifacts; none by default)
- **Pension parsing (B5):** `PHINS_PENSION_STREAM_MIN_BYTES` (iterparse
 threshold, default 8 MiB; `0` streams everything),
 `PHINS_PENSION_PARSE_CACHE` (default true), `PHINS_PENSION_PARSE_CACHE_MAX`
 (process LRU and durable row bound, default 128)
- **Customer messaging (B6):** `PHINS_CUSTOMER_DAILY_MESSAGE_CAP` (WhatsApp +
 SMS per customer per UTC day, default 5, `0` disables),
 `PHINS_CUSTOMER_MESSAGING_CONSENT_ENFORCED` (default on; off skips only the
 consent check for relational copy — an explicit opt-out and the cap still
 apply)
- **Delivery bidding (B11):** `PHINS_DELIVERY_SLA_TICK_SECONDS` (SLA clock
 interval for closing elapsed bidding windows, default 60)
- **Transcription:** `PHINS_TRANSCRIPTION_PROVIDER`
 (`openai_compatible`|`disabled`), `PHINS_TRANSCRIPTION_ENDPOINT`,
 `PHINS_TRANSCRIPTION_API_KEY`, `PHINS_TRANSCRIPTION_MODEL`
- **Advisory LLM:** `PHINS_ASSESSMENT_AI_ENABLED`, `PHINS_ASSESSMENT_AI_ENDPOINT`,
 `PHINS_ASSESSMENT_AI_API_KEY`, `PHINS_ASSESSMENT_AI_MODEL`,
 `PHINS_LLM_ESCALATION_MODEL`, `PHINS_AI_ACCEPT_THRESHOLD`,
 `PHINS_AI_REVIEW_THRESHOLD`, `PHINS_LLM_VALIDATION_RETRIES` (schema-invalid
 structured replies re-asked with the errors appended, default `2`, then
 deterministic fallback), `PHINS_ASSESSMENT_NARRATIVE_PROMPT_VERSION` (pin
 the narrative prompt, e.g. `1` for free-text v1; default = latest v2)
- **AI cost prices:** `PHINS_AI_PRICE_INPUT_PER_MTOK`,
 `PHINS_AI_PRICE_OUTPUT_PER_MTOK`, `PHINS_AI_PRICE_PARSE_PER_PAGE`,
 `PHINS_AI_PRICE_TRANSCRIPTION_PER_MIN`
- **External-call gateway** (`services/external_call_gateway.py`; every LLM,
  transcription and video-provider HTTP call goes through it):
  `PHINS_AI_DAILY_CALL_BUDGET`, `PHINS_AI_DAILY_TOKEN_BUDGET` (per
  customer/agent/UTC day, `0` = unlimited; over budget raises
  `BudgetExceeded` before the provider is contacted and records a
  `blocked=true` usage row), `PHINS_GATEWAY_CACHE_TTL` (seconds, default
  `3600`, `0` disables the response cache), `PHINS_GATEWAY_MAX_RETRIES`
  (default `2`; media `submit` is never retried),
  `PHINS_GATEWAY_RETRY_BASE_SECS`, `PHINS_GATEWAY_RETRY_CAP_SECS`,
  `PHINS_GATEWAY_CB_FAILURE_THRESHOLD`,
  `PHINS_GATEWAY_CB_RECOVERY_TIMEOUT_SECS`; state is visible under
  `gateway` in `GET /api/admin/ai-agents/health`
- **Auto-pay:** `PHINS_DEFAULT_AUTO_PAY_CARD_NUMBER`,
  `MONTHLY_AUTO_PAY_COMMAND_TOKEN`
- **AutoPilot trading safety:** `PHINS_TRADING_HALT` (operator kill switch;
  read on every execution, cannot be lifted via the API),
  `PHINS_TRADING_AUDIT_REQUIRED` (`auto`|`true`|`false`; `auto` fails closed
  whenever the broker reports a live connection),
  `PHINS_TRADING_GLOBAL_DAILY_LOSS_PCT` (default `0.05` of portfolio),
  `PHINS_TRADING_GLOBAL_DAILY_LOSS_ABS` (currency amount, `0` = off);
  runtime halt/resume/promote via `/api/terminal/autopilot/{halt,resume,promote}`
- **Security:** `SESSION_SECRET_KEY`, `PHINS_ENCRYPTION_KEY`,
  `PHINS_ENFORCE_SECRET_POLICY`, `PHINS_EMERGENCY_UNLOCK_KEY`,
  `ALLOW_LEGACY_DEMO_PASSWORDS`
- **Customer identity (personal ID + nationality):**
  `PHINS_IDENTITY_REQUIRED` (strict gate on applications/claims; defaults
  on except under `PHINS_TEST_MODE`), `PHINS_IDENTITY_HASH_KEY` (explicit
  lookup-hash key; otherwise the platform keyring mints one),
  `PHINS_KEYRING_PATH` (key file for no-database deployments),
  `PHINS_IDENTITY_ALLOW_PLAINTEXT_VAULT` (dev-only; when no vault key can be
  resolved at all the service refuses to store an ID, 503
  `identity_vault_unavailable`)
- **Integrations:** `PLAID_*`, `STRIPE_*`, `ACH_*`, `ALPACA_*`, `COINBASE_*`,
  `IB_*`, `WEBHOOK_BASE_URL`, `ALPHA_VANTAGE_API_KEY`

Operational notes:

- `web_portal/server.py` defaults `PORT` to `8000`
- when `PORT` is provided, `HOST` is set to `0.0.0.0`; otherwise local runs use
  `127.0.0.1`
- `Dockerfile` is multi-stage on `python:3.12-slim`, healthcheck hits
  `/api/health`, entrypoint is `./scripts/entrypoint.sh serve`
- `render.yaml` includes a cron service `phins-monthly-auto-pay`
  (`./scripts/entrypoint.sh cron`)
- `entrypoint.sh db-init` refuses to seed demo data when
  `PHINS_ENVIRONMENT=production` (forces `POPULATE_DEMO_DATA=false`)

## 8) Testing Playbook

Run the smallest useful test set first, then broaden if risk is moderate/high.

Useful commands:

```bash
python3 web_portal/server.py --test
python3 validate_system.py
python3 check_database_connection.py
bash quick_smoke_test.sh
pytest tests/test_api_integration.py
pytest tests/test_database.py
pytest tests/test_billing_engine.py
pytest tests/test_accounting_engine.py
pytest tests/ -q --tb=line
bash RUN_ALL_TESTS.sh
python3 scripts/run_agent_eval.py golden            # agent golden sets (CI gate)
python3 scripts/run_agent_eval.py golden --update   # deliberate fixture refresh; review the diff
python3 scripts/run_agent_eval.py replay ai_automation_controller --decisions log.json
```

Important test harness facts:

- **Root `conftest.py`** starts an embedded `ThreadingHTTPServer` on
  `127.0.0.1` with `PortalHandler`; sets env defaults
  (`USE_DATABASE=false`, `USE_SQLITE=true`, `PHINS_TEST_MODE=true`)
- Port selection: honors a `TEST_PORT` env override, prefers `8000`, and
  falls back to a free kernel-assigned port if `8000` is busy; the bound
  port is published via `TEST_PORT` and `TEST_BASE_URL`, so tests should
  read `TEST_BASE_URL` rather than hardcoding `http://localhost:8000`
- Tests that mark a port as initialised (`_TEST_PORTS_INITIALIZED.add(...)`)
  or open raw sockets must derive the port from `TEST_PORT`, never `8000`
- Self-hosted `ServerThread`/`HTTPServer` helpers inside tests bind port `0`
  and read the kernel-assigned port from `server_address`; do not add fixed
  `80xx` ports
- Persisted state is redirected per session so runs never dirty the checkout:
  `PHINS_ACTUARIAL_STATE_PATH` (central pricing snapshot) and
  `PHINS_INVITATION_CODES_PATH` (temp copy of
  `database/invitation_codes.json`) point at `/tmp` files removed at
  session end; `PHINS_BI_SNAPSHOT_DIR` likewise
- The actuarial store is a process-wide singleton; a test that promotes a
  rate table or config must restore it (`reset_tables_to_default`,
  `update_config` back) or use an isolated `ActuarialTablesStore()`
- **`tests/conftest.py`** only adds `sys.path` and sets `PHINS_TEST_MODE`; it
  does **not** start the server
- Tests reset in-memory portal state between cases (clears `POLICIES`,
  `CLAIMS`, `CUSTOMERS`, `SESSIONS`, `BILLING`, etc.)
- Options wheel service and document processing service are also reset per test
- `ThresholdConfig` (`services/ai_threshold_config.py`) and `AIDecisionLog`
  are process-wide singletons; a test that promotes a segment must restore
  the snapshot (`cfg.export()` before, `cfg.import_(snap)` after) or clear
  the log it appended to
- Golden fixtures only freeze the keys listed under `expected`; adding output
  keys never breaks one, changing a frozen value does — update the fixture
  in the same PR as the behaviour change and say why
- 233 test files under `tests/`, 11 root-level `test_*.py` files

Docs-only changes usually do not need tests, but they do require verifying that
referenced files, commands, paths, and ports still exist.

## 9) Common Pitfalls

- Fixing only the database path can leave in-memory HTTP flows inconsistent; if
  a feature exists in both modes, check both code paths before finishing.
- Repository or schema changes can require matching updates in seeds,
  initialization, or migration helpers.
- Route changes may need updates in `web_portal/server.py` **and** one or more
  of the API extension modules; verify actual wiring rather than assuming.
- Handler initialization, port assumptions, or shared module state can break many
  tests because pytest starts a real embedded `PortalHandler` server.
- `supplier_repository.py` and `marketplace_repository.py` each bundle many
  repository classes (suppliers/invitations/offers/orders/documents/ledger,
  and wallet/payments/journal/settlements/claims/outbox respectively);
  changes there can have a wide blast radius.
- Hardcoding `http://localhost:8000` in tests breaks parallel or busy-port
  runs; read `TEST_BASE_URL` instead.
- The two `conftest.py` files (root vs `tests/`) serve different purposes;
  putting server setup in `tests/conftest.py` will not apply to root-level
  test files.
- `detect_sql_injection` in `web_portal/server.py` matches substrings such as
  `EXECUTE`, `UPDATE `, `DROP TABLE`, `--` in query-string values and logs a
  "SQL Injection Attempt" (which can trip the client-IP block and fail every
  later test in the session). Do not name a status/enum value or query
  parameter after one (AgentOS payouts use `settled`, not `executed`).

## 10) Security and Reliability

- Avoid exposing PII, tokens, secrets, or sensitive logs.
- Use defensive numeric conversion and status normalization helpers where
  appropriate.
- Preserve graceful fallback behavior for external dependencies.
- Use audit-oriented patterns for sensitive operations if the surrounding code
  already does so.
- Security utilities live in `security/` (`vault.py`, `auth_tokens.py`,
  `headers.py`, `network.py`, `secrets_policy.py`, `firewall.py`,
  `intrusion_detector.py`, `request_sanitizer.py`, `file_scanner.py`,
  `confidential_access.py`); reuse them rather than rolling custom auth/crypto.
- Data-at-rest keys come from `security/keyring.py`: `PHINS_ENCRYPTION_KEY` /
  `PHINS_IDENTITY_HASH_KEY` when set, otherwise one durable key per purpose
  minted on first use into `platform_keys` (DB mode) or `PHINS_KEYRING_PATH`.
  Never replace an existing ring key, never log material (fingerprints only),
  and route new encryption through `security.vault` so every vaulted dataset
  shares the same key ring.
- Static files under `web_portal/static/` are served with path-traversal
  protection only — they are **public** unless gated. Confidential material
  (`/internal/` investor plans, `/legal/` corporate instruments) goes through
  `security/confidential_access.py`; add new confidential paths there (or via
  `PHINS_CONFIDENTIAL_PATHS`) rather than relying on an obscure filename.
- Never return a live OTP to a caller. `PHINS_EXPOSE_DEMO_OTP` is a
  non-production aid and is refused in production; route any new OTP surface
  through `_demo_otp_exposure_allowed()`.
- Never commit backups. `backups/` is gitignored and
 `scripts/backup_platform.sh` refuses to write into a tracked path; a snapshot
 can contain a full database dump. Each successful run writes
 `restore_record.json` and `backups/RESTORE_INDEX.json`. A metadata-only
 catalog (git SHA + checksums) may be written to
 `PHINS_BACKUP_RECORD_CATALOG` (typically `docs/platform_restore_catalog.json`)
 and listed with `scripts/restore_from_backup.sh --list`.
- Repairs that rewrite ledger/audit rows must write their forensic before/after
  journal first (fail closed) and verify the result after commit — see
  `PlatformEventLedgerService.persist_chain_to_db`.
- AI decision thresholds are never edited in code or by an evaluator. The
  harness (`services/agent_eval.py`) is read-only and only recommends;
  the only mutating path is the admin promotion route, which records the
  before/after snapshot in `ai_decision_log` before it takes effect and
  rolls back if that row cannot be written.
- Structured LLM output is validated twice (provider against the schema,
  service against its own evidence); a reply that fails is replaced by the
  deterministic result with `fallback_reason` recorded, never used as-is.
- A customer's personal ID number has exactly one writer:
  `services/customer_identity_service.py` (`set_identity` /
  `reconcile_pipeline_identity`). Records, responses, audit rows and ledger
  anchors carry only `nationality` + `national_id_hash` + `national_id_last4`
  (`identity_reference()`); the number lives in the vault and
  `reveal_national_id()` is server-side only (Mislaka). Nationality is an ISO
  alpha-2 code via `services/countries.py`. Never add a plaintext `id_number`
  field to a pipeline record — stamp `customer_identity` and, on a conflicting
  payload, `identity_mismatch=True` for review instead of overwriting. External
  lookups that need the number (Mislaka) go through `resolve_lookup_id()`;
  IDs read out of documents (assessment facts, risk reports) are only
  compared with the master (`matches()`), never written to it.

## 11) Minimal Task Workflow

1. Identify the touched layer: API, service, engine, repository, or deployment.
2. Inspect nearby code for the existing pattern.
3. Implement the smallest viable change.
4. Add or update tests if behavior changed.
5. Run targeted validation.
6. Update docs if operator behavior changed.
7. Stage only intended files.
8. Commit with a clear message.

## 12) AGENTS.md Maintenance

If you update this file again:

1. Prefer corrections and targeted restructuring over generic policy text.
2. Validate claims about files, commands, ports, and env vars against the repo.
3. Keep it short and operational.
4. Remove stale guidance instead of preserving it for completeness.

---

Last updated: September 15, 2026
