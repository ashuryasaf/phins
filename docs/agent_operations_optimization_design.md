# PHINS Agent Operations — Optimization Design

> **Status: IMPLEMENTING — §D steps 1–5 (A1, A5, B12, A2, A3, A4, A6, B2, B3) and step 6 parts 1–3 (B1, B4, B5, B9, B8, B10) shipped.** This document turns
> the agent inventory and the optimization proposal into a concrete,
> file-level plan with a test plan per workstream. It is the model of record
> for the implementation PRs that follow. Each workstream is independently
> shippable; sequencing is by dependency (§D), not calendar. See
> §G for what is in the tree versus still planned.
>
> Governing constraint (unchanged): **AI recommends, the ledger decides.**
> Nothing here moves payout, pricing, underwriting, or trade-execution
> decisions into prompts or models. See `docs/ai_surface_design_principles.md`.

## 0. Scope and inventory

Software operators in scope (15 modules below; the investor deck's "15" counted
the removed Investment AI and not the Underwriting Assistant):

| # | Agent | Module | Lines | Entry routes today |
|---|---|---|---|---|
| 1 | Underwriting Bot | `services/underwriting_bot_service.py` | 2127 | `POST /api/risk-dashboard/ai-assess` (inline, `server.py`) |
| 2 | Claims Bot | `services/claims_bot_service.py` | 1311 | `POST /api/claims/probability-report`, `GET /api/claims/bot-threshold-calibration` |
| 3 | AI Automation Controller | `ai_automation_controller.py` | 838 | library only — no `server.py`/extension route references it; exercised by root `test_integration.py`, `test_pr_complete.py` |
| 4 | Underwriting Assistant | `underwriting_assistant.py` | — | library used by `service_agent.py`, demos, CLI |
| 5 | Assessment AI (Hermes) | `services/assessment_ai_service.py` | 668 | `POST /api/assessment-center/analysis` (`api_assessment_center.py`) |
| 6 | Pension Data Agent | `services/pension_data_agent.py` | 2226 | `/api/mislaka/{import,policies,summary,report,companies,status,affiliations}` |
| 7 | Document Intelligence | `services/document_processing_service.py` + `services/document_job_worker.py` | 1898 + 439 | `/api/doc-service/jobs`, `/api/doc-service/jobs/requeue`, all upload paths |
| 8 | Customer Communication Agent | `services/customer_communication_agent.py` | 825 | `api_extensions.py` (`CUSTOMER_COMMUNICATION_AGENT_AVAILABLE`) |
| 9 | Customer Service Agent | `service_agent.py` | 177 | library only |
| 10 | Marketing / Sales Agent | `services/marketing_sales_agent_service.py` | 550 | `/api/admin/marketing-sales-agent{,/latest,/publish}` |
| 11 | Video Agents | `services/video_agents_service.py` | 1023 | `/api/admin/media/video-agents/*`, `/api/admin/media/video-jobs/*` (`api_extensions.py`) |
| 12 | AI Risk Reports | `services/ai_risk_reports_service.py` | 5229 | `/api/reports/{upload,generate,view,download-summary}` |
| 13 | BI Analytics | `services/bi_analytics_service.py` | 1373 | `/api/bi/*` (`api_bi_analytics.py`) |
| 14 | Delivery Bidding AI | `services/delivery_bidding_service.py` | 822 | `/api/delivery/*` (`api_delivery_bidding.py`) |
| 15 | AI Trading / AutoPilot | `services/ai_trading_engine.py` | 1818 | `/api/terminal/copilot`, `/api/terminal/autopilot/{bots,strategies,create,execute,control}` |

Shared infrastructure already present and reused throughout:
`services/ai_capabilities.py`, `services/ai_audit_bridge.py`,
`services/ai_decision_log.py`, `services/ai_threshold_config.py`,
`services/ai_model_registry.py`, `services/ai_usage_service.py`,
`services/llm_providers.py`, `services/transcription_providers.py`,
`services/media_generation_service.py`, `services/metrics_service.py`,
`services/assessment_record_service.py`, `database/models.py`
(`DocumentProcessingJob`, `AuditLog`), `scripts/entrypoint.sh` (`worker`,
`cron`, `bi-snapshot` modes).

---

## A. Cross-cutting platform work

### A1. Agent runtime contract + full capability catalog

**Problem.** Each agent is a bespoke class with its own singleton accessor,
duplicated helpers (`_safe_float`/`_status`/`_safe_int` exist in 8 service
modules), its own in-memory store, and ad-hoc audit wiring. Only 6 of 14
agents appear in `/api/ai/capabilities`.

**Design.**

- New `services/agent_runtime.py`:
  - `AgentDescriptor` dataclass: `id`, `name`, `version`, `module`,
    `deterministic: bool`, `roles`, `entry_url`, `api`, `executes_async: bool`,
    `moves_money: bool`.
  - `AgentRuntime` protocol: `describe() -> AgentDescriptor`,
    `health() -> dict`, `metrics() -> dict`. No `run()` in v1 — the agents
    keep their existing public methods; the contract is for discovery,
    health, and metrics only, which keeps the change non-invasive.
  - `register(descriptor, health_fn, metrics_fn)` +
    `registry() -> list[AgentDescriptor]`.
- New `services/agent_helpers.py`: canonical `safe_float`, `safe_int`,
  `status_lower`, `status_eq`, `status_in`, `utc_now_iso`. Each agent module
  replaces its private copy with an import (mechanical, one module per
  commit to keep diffs reviewable).
- `services/ai_capabilities.py`: `_CAPABILITIES` becomes the union of the
  static list and `agent_runtime.registry()`; add the 8 missing entries
  (underwriting_bot, ai_automation_controller, pension_data_agent,
  document_intelligence, customer_communication, customer_service,
  marketing_sales, delivery_bidding). `help_text()` gains
  `health` per capability when the caller is admin.
- `web_portal/server.py` `/api/ai/capabilities`: no route change; response
  gains `health` (admin only) and the extra entries.
- New `GET /api/admin/agents/health` (admin) in `web_portal/api_extensions.py`
  returning `{items: [descriptor + health + metrics], total}`. Note: the
  `/api/admin/agents*` namespace is currently AgentOS (human brokers); use
  `/api/admin/ai-agents/health` to avoid the collision.

**Touch points.** `services/agent_runtime.py` (new), `services/agent_helpers.py`
(new), `services/ai_capabilities.py`, `web_portal/api_extensions.py`, each of
the 14 agent modules (registration call at module bottom, helper import),
`web_portal/static/admin.html` (health panel, later in A5).

**Tests.**
- `tests/test_agent_runtime.py` (new): registry returns 14 descriptors;
  duplicate `id` raises; every descriptor's `module` is importable; every
  `api.path` string appears in `server.py`, `api_extensions.py`, or the
  domain API module (mirrors `test_capabilities_route_registered`).
- `tests/test_ai_capabilities.py`: update count assertions; role filter still
  excludes admin-only agents for `customer`.
- `tests/test_agent_helpers.py` (new): parity tests proving each replaced
  private helper produced identical results on a fixture of edge values
  (`None`, `"1,234.5"`, bools, `"  Approved "`).
- Regression: full `pytest tests/ -q` because helper swaps touch many modules.

### A2. Single external-call gateway

**Problem.** `llm_providers.py`, `transcription_providers.py`, and
`media_generation_service.py` each open HTTP independently; only the LLM path
has schema validation and a `usage_hook`; none has a circuit breaker or
result cache. `notification_service.py` already has `_SMTPCircuitBreaker` —
the pattern exists but is not shared.

**Design.**

- New `services/external_call_gateway.py`:
  - `ExternalCallGateway.call(provider_kind, request_fn, *, cache_key=None,
    timeout, budget_scope, agent_id)`.
  - Circuit breaker per `(provider_kind, endpoint)` — lift
    `_SMTPCircuitBreaker` from `notification_service.py` into
    `services/circuit_breaker.py` and reuse it in both places.
  - Bounded retry with full jitter (`PHINS_GATEWAY_MAX_RETRIES`, default 2),
    honoring `Retry-After`.
  - Response cache keyed by `sha256(provider_kind + normalized request)` with
    TTL (`PHINS_GATEWAY_CACHE_TTL`, default 3600s); in-memory with optional
    DB backing via a new `ai_call_cache` table (`database/models.py`,
    `database/repositories/ai_usage_repository.py` sibling).
  - Budget enforcement: per `(tenant/customer, agent_id, day)` token and
    call caps (`PHINS_AI_DAILY_TOKEN_BUDGET`, `PHINS_AI_DAILY_CALL_BUDGET`);
    over budget returns a typed `BudgetExceeded` so callers fall back to
    deterministic mode (Assessment AI already has that fallback; Video
    Agents already have job caps — unify on the gateway's counters).
  - Every call reports to `ai_usage_service.record_usage` with `agent_id`
    (new column on the AI usage record).
- `services/llm_providers.py`, `services/transcription_providers.py`,
  `services/media_generation_service.py`: route their `urllib`/HTTP calls
  through the gateway; keep their public signatures unchanged.
- `services/ai_usage_service.py`: add `agent_id` to the record schema,
  `summarize(group_by="agent")`.

**Touch points.** `services/external_call_gateway.py` (new),
`services/circuit_breaker.py` (new, extracted), `services/llm_providers.py`,
`services/transcription_providers.py`, `services/media_generation_service.py`,
`services/notification_service.py` (import the extracted breaker),
`services/ai_usage_service.py`, `database/models.py` (+ `ai_call_cache`,
`agent_id` on usage), `database/repositories/ai_usage_repository.py`,
`database/__init__.py` (`upgrade_schema`), `AGENTS.md` env-var list.

**Tests.**
- `tests/test_external_call_gateway.py` (new): breaker opens after N
  failures and half-opens after cooldown; retry honors `Retry-After`; cache
  hit skips `request_fn`; budget exceeded raises `BudgetExceeded` and records
  a usage row with `blocked=True`; every successful call produces exactly one
  usage record with `agent_id`.
- `tests/test_llm_providers.py`, `tests/test_transcription_providers.py`,
  `tests/test_video_agents_service.py`: existing suites must pass unchanged
  (gateway is transparent); add one case each asserting the gateway was
  invoked (monkeypatched).
- `tests/test_notification_service.py`: SMTP breaker behavior unchanged
  after extraction.
- `tests/test_ai_usage_service.py`: `group_by="agent"` aggregation.

### A3. Generalized job queue (off the request thread)

**Problem.** `web_portal/server.py` is a `ThreadingHTTPServer` of
`BaseHTTPRequestHandler`; Underwriting Bot, Claims Bot, Risk Reports, Pension
import, and Video Agents run inline on the handler thread. Only documents use
`document_job_worker.py`.

**Design.**

- Generalize `services/document_job_worker.py` into
  `services/agent_job_queue.py` without breaking its API:
  - Keep `DocumentJobWorker` as a thin subclass/alias so
    `get_document_job_worker()` and `entrypoint.sh worker` keep working.
  - Add a job-type registry: `register_handler(job_type, fn)`; the
    `process_once` loop dispatches by `job_type` instead of assuming a
    document.
  - `DocumentProcessingJob.document_id` becomes nullable and a new
    `subject_type`/`subject_id` pair (`claim`, `application`, `report`,
    `pension_import`, `video_job`) is added, so the same table serves all
    agents. Idempotency key semantics unchanged
    (`sha256(content) + job_type`).
  - Concurrency: `PHINS_DOC_WORKER_CONCURRENCY` stays; add
    `PHINS_JOB_WORKER_MAX_CONCURRENCY` and scale threads on
    `queue_stats()['pending']` between min and max.
- Agent-side adapters (one per migrated agent), each a small module
  `services/jobs/<agent>_job.py` exposing `enqueue_<x>()` and the handler:
  `underwriting_bot_job.py`, `claims_bot_job.py`, `risk_report_job.py`,
  `pension_import_job.py`, `video_job.py`.
- API contract change: the five migrated POST routes return
  `202 {job_id, status: "queued", poll_url}` when `PHINS_AGENT_ASYNC=true`
  (default off, mirroring `PHINS_DOC_ASYNC`), and the existing synchronous
  body otherwise. New `GET /api/jobs/{job_id}` (role-scoped to the
  submitter or admin) returns the job row + result.
- Dashboards (`risk-dashboard.html`, `claims-adjuster-dashboard.html`,
  `risk-reports-dashboard.html`, `video-agents.html`, Mislaka workbench)
  poll `poll_url` when they receive 202.

**Touch points.** `services/agent_job_queue.py` (new, extracted),
`services/document_job_worker.py` (becomes shim), `services/jobs/*.py` (new),
`database/models.py` (`DocumentProcessingJob` columns), `database/__init__.py`
(`upgrade_schema`), `database/repositories/document_repository.py`,
`web_portal/server.py` (5 routes + `GET /api/jobs/{id}`), the five static
dashboards, `scripts/entrypoint.sh` (`worker` help text), `AGENTS.md`.

**Tests.**
- `tests/test_document_job_worker.py`: must pass unchanged (shim).
- `tests/test_agent_job_queue.py` (new): handler registry dispatch; nullable
  `document_id`; per-type idempotency; retry schedule and dead-letter per
  type; claim expiry recovery; concurrency scales up and back down.
- Per agent job test (`tests/test_jobs_<agent>.py`): enqueue → process_once
  → result equals the synchronous call's result on the same fixture (golden
  parity), for both in-memory and SQLite modes.
- HTTP: with `PHINS_AGENT_ASYNC=true`, each migrated route returns 202 and
  `GET /api/jobs/{id}` transitions to `completed`; with the flag off, the
  existing response body is byte-identical (snapshot compare against current
  test fixtures in `tests/test_underwriting_bot.py`,
  `tests/test_ai_risk_reports.py`, `tests/test_video_agents_service.py`).
- IDOR: a second user cannot read another submitter's job (pattern from
  `tests/test_assessment_center_document_idor.py`).

### A4. Durable agent state (read-through cache over tables)

**Problem.** Claims Bot caps 5,000 reports in RAM, Video Agents' `_JobStore`
and Risk Reports' artifacts are process-local; restarts lose them and
multi-instance deployments disagree. AgentOS already solved this with a
TTL-hydrated cache (`PHINS_AGENT_HYDRATE_TTL`) over durable tables.

**Design.**

- Extract that pattern into `services/hydrated_store.py`:
  `HydratedStore(table_repo, ttl, key_fn)` with `get`, `put`, `list`,
  `_hydrate(force)`; forced refresh on write, coalesced refresh on read.
- New tables in `database/models.py`: `agent_artifacts`
  (`id`, `agent_id`, `subject_type`, `subject_id`, `kind`, `payload_json`,
  `checksum`, `created_date`) — one generic table rather than one per agent;
  `video_jobs` gets its own table because it has lifecycle columns.
- Repos: `database/repositories/agent_artifact_repository.py` (new),
  `video_job_repository.py` (new); wire as `DatabaseManager.agent_artifacts`,
  `.video_jobs`.
- Consumers: `ClaimsBotService.reports` → `HydratedStore`; Video Agents
  `_JobStore` → `HydratedStore` over `video_jobs` (keep `mark_terminal`
  atomicity via a conditional UPDATE); Risk Reports report store →
  `agent_artifacts`. Underwriting Bot reports likewise.
- `ai_audit_bridge` mirroring stays as-is; it is the compliance trail, not
  the working store.

**Touch points.** `services/hydrated_store.py` (new),
`services/agent_ecosystem_service.py` (adopt the extracted store, no
behavior change), `database/models.py`, `database/repositories/*` (2 new),
`database/repositories/__init__.py`, `database/manager.py`,
`database/__init__.py`, `services/claims_bot_service.py`,
`services/video_agents_service.py`, `services/ai_risk_reports_service.py`,
`services/underwriting_bot_service.py`.

**Tests.**
- `tests/test_hydrated_store.py` (new): TTL coalescing; forced refresh on
  write; two store instances over one SQLite file see each other's writes
  (port `test_db_mode_cross_instance_visibility`).
- `tests/test_agent_ecosystem.py`: unchanged and green after adoption.
- Claims Bot: report survives `reset` + re-init in SQLite mode; retention cap
  becomes a DB-side prune, tested via `MAX_RETAINED_REPORTS=2` as in
  `tests/test_ai_audit_bridge.py`.
- Video Agents: `mark_terminal` race test (webhook and poll both attempt
  terminal; exactly one wins) ported to the DB-backed store.

### A5. Per-agent observability

**Problem.** `services/metrics_service.py` is 41 lines of business KPIs;
there is no latency/error/queue/cost view per agent.

**Design.**

- New `services/agent_metrics.py`: in-process counters and histograms keyed
  by `agent_id` (`calls`, `errors`, `latency_ms` p50/p95, `decisions{label}`,
  `queue_depth`, `cost_usd` from `ai_usage_service`). Thread-safe, bounded
  reservoir per agent.
- `@instrument_agent("claims_bot")` decorator applied to each agent's public
  entry method(s); the decorator also emits the `ai_decision_log` record
  where a decision label is returned, so decision distribution is derived
  from one source.
- `GET /api/admin/ai-agents/health` (from A1) includes these metrics;
  `GET /api/metrics` gains an `agents` block.
- `web_portal/static/admin.html`: "AI agents" panel — table of 14 rows with
  health dot, p95, error rate, today's cost, queue depth; links to each
  `entry_url`.
- Alert rule (cron-friendly): `scheduler/runner.py` gains
  `check_agent_slo()` that writes an `AuditLog` row when p95 or error rate
  crosses `PHINS_AGENT_SLO_P95_MS` / `PHINS_AGENT_SLO_ERROR_RATE`.

**Touch points.** `services/agent_metrics.py` (new), each agent module
(decorator on entry methods), `services/metrics_service.py`,
`web_portal/api_extensions.py`, `web_portal/server.py` (`/api/metrics`),
`web_portal/static/admin.html`, `scheduler/runner.py`.

**Tests.**
- `tests/test_agent_metrics.py` (new): decorator records call/latency/error;
  reservoir bounded; decision label counted once and appears in
  `ai_decision_log`.
- `tests/test_automation_metrics_observed.py`: extend to assert the
  controller's decisions appear under `agents.ai_automation_controller`.
- Static integrity test for the admin panel following
  `tests/test_admin_dashboard_assistant_static_integrity.py` conventions
  (panel present, no inline secrets, i18n keys in `static/locales/he.json`).

### A6. Evaluation harness and calibration loop

**Problem.** `ai_threshold_config.py` can `promote()` per-segment thresholds
and `ai_decision_log.record_override()` captures human overrides, but nothing
replays logged decisions to propose calibrated values. Claims Bot has a
read-only calibration endpoint; UW and the controller do not.

**Design.**

- New `services/agent_eval.py`:
  - `replay(decisions, overrides, scorer, thresholds) -> EvalReport`
    (precision/recall/F1 per segment, confusion matrix, override rate,
    minimum-sample guard like `calibrate_claims_thresholds`).
  - `propose_thresholds(report, target_precision)` → candidate per-segment
    `(approve, reject)`; never auto-promotes.
  - Golden-set runner: `run_golden(agent_id, fixtures_dir)` that executes
    the agent on `tests/golden/<agent>/*.json` and diffs against expected
    output (used by CI for Assessment AI prompts and any scorer change).
- Routes (admin/actuary): `GET /api/admin/ai-agents/eval/{agent_id}`
  (replay report), `POST /api/admin/ai-agents/thresholds/promote`
  (calls `ThresholdConfig.promote`, writes an `AuditLog` row and an
  `ai_decision_log.record_override`-style audit entry with before/after).
- `scripts/run_agent_eval.py` (new) for CI and `entrypoint.sh exec` use.

**Touch points.** `services/agent_eval.py` (new),
`services/ai_threshold_config.py` (`export()`/`import_()` for audit
snapshot), `services/claims_bot_service.py` (`calibrate_claims_thresholds`
delegates to `agent_eval`), `web_portal/api_extensions.py`,
`scripts/run_agent_eval.py` (new), `tests/golden/` (new fixture dir),
`.github/workflows/` (golden-set job).

**Tests.**
- `tests/test_agent_eval.py` (new): replay on a synthetic labelled set
  yields known P/R; minimum-sample guard returns `insufficient_data`;
  `propose_thresholds` is monotone in `target_precision`.
- `tests/test_claims_bot_threshold_calibration.py`: unchanged results after
  delegation.
- Promotion route: non-admin 403; promotion writes audit row; `ThresholdConfig`
  restored in test teardown (process-wide singleton, same caveat as the
  actuarial store in `AGENTS.md`).

---

## B. Per-agent designs

### B1. Underwriting Bot and Claims Bot

**Changes.**
- Shared evidence pipeline: both bots stop parsing photos/PDFs/audio/video
  themselves and consume `DocumentProcessingService` facts (with provenance:
  snippet, offsets, page, timestamps). New `services/evidence_facts.py`
  exposes `facts_for(document_ids) -> list[Fact]` and a feature cache keyed
  by document SHA-256 so re-scoring a claim with unchanged evidence is a
  cache hit.
- Real STT: `AudioAnalyzer.analyze` in the Underwriting Bot and the Claims
  Bot audio path call `transcription_providers.get_transcription_provider()`
  when no `transcription` is supplied; `NO_STT_AVAILABLE` only when the
  provider is `disabled`.
- Model behind rules: both bots ask `ai_model_registry.get_model("uw_scorer")`
  / `("claims_scorer")`; if present, the model score is logged alongside the
  rule score (`ai_decision_log` `model_score`, `rule_score`, `divergence`)
  and does not change the decision. Drift alert when divergence p95 exceeds
  `PHINS_AI_DRIFT_THRESHOLD`.
- Route: `POST /api/risk-dashboard/ai-assess` stops constructing a fresh
  `UnderwritingBotService` per request; use a module accessor
  `get_underwriting_bot_service(...)` like the Claims Bot's.
- Split `underwriting_bot_service.py` (2127 lines) into
  `services/underwriting_bot/{service,features,report}.py` with the old
  module re-exporting names.

**Touch points.** `services/evidence_facts.py` (new),
`services/underwriting_bot_service.py` (+ package split),
`services/claims_bot_service.py`, `services/document_processing_service.py`
(stable fact accessor), `services/ai_model_registry.py` (named-model
lookup), `web_portal/server.py` (`/api/risk-dashboard/ai-assess`,
`/api/claims/probability-report`).

**Tests.**
- `tests/test_underwriting_bot.py`, `tests/test_claims_bot_threshold_calibration.py`
  green after split (re-export test: every previously importable name still
  imports).
- `tests/test_evidence_facts.py` (new): cache hit on identical SHA; miss on
  changed bytes; provenance preserved through to the report.
- STT: provider `disabled` → flag present; mocked `openai_compatible` →
  transcript text used in features (extend
  `tests/test_transcription_providers.py`).
- Model shadow: with a stub model in `PHINS_MODEL_DIR`, decision equals
  rule decision and `divergence` is logged; drift threshold triggers audit.
- Read-only guarantee: fixture `CUSTOMERS`/`POLICIES` deep-equal before and
  after both bots run (both docstrings promise it; make it a test).

### B2. AI Automation Controller

**Changes.**
- Split `ai_automation_controller.py` into
  `services/automation/{quoting,underwriting_gate,fraud,billing_schedule}.py`;
  root module keeps `get_automation_controller`, `auto_underwrite`,
  `detect_fraud`, `generate_auto_quote` re-exports.
- Fix the quarter-rollover due-date bug flagged in
  `PHINS_PLATFORM_ASSESSMENT.md` (D3) inside `billing_schedule.py` with an
  explicit `next_quarter_start(date)` helper.
- Wire `ai_threshold_config.segment_key()` into every decision (currently
  best-effort import) and return `confidence_band` in responses.

**Touch points.** `ai_automation_controller.py`, `services/automation/*`
(new), `web_portal/server.py` (quote/UW handlers read `confidence_band`),
`AI_ARCHITECTURE.md`.

**Tests.**
- `tests/test_ai_bi_optimizations.py`, `tests/test_decision_loop_integration.py`,
  `tests/test_automation_metrics_observed.py`: green after split.
- `tests/test_billing_schedule.py` (new): parametrized dates across
  Dec 31 / Jan 1 / leap day; both quarter paths produce one answer.
- Segment thresholds: a promoted segment changes the decision for that
  segment only; global default unchanged elsewhere.

### B3. Assessment AI (Hermes)

**Changes.**
- Prompt versioning: every template under `prompts/assessment/` carries a
  `version` and the service records `prompt_id`, `prompt_version`,
  `prompt_sha256` in its audit record (partially present; make it complete
  and asserted).
- Structured output via `llm_providers` schema validation
  (`schemas/assessment_narrative.json`, new) instead of free text.
- Golden set: `tests/golden/assessment_ai/*.json` with deterministic-mode
  expected narratives; CI fails on unexpected diff.
- Route unchanged (`POST /api/assessment-center/analysis`).

**Touch points.** `services/assessment_ai_service.py`,
`services/llm_providers.py` (schema loader), `prompts/assessment/*`,
`schemas/assessment_narrative.json` (new), `tests/golden/assessment_ai/`.

**Tests.**
- `tests/test_assessment_ai_narrative.py`: extend with prompt hash presence,
  schema-invalid mock response → retry then deterministic fallback, redaction
  on when `PHINS_ENVIRONMENT=production`.
- Golden-set runner (A6) covers narrative regressions.

### B4. Document Intelligence

**Changes.**
- Page-level OCR cache keyed by `(sha256, page)`; parallel page fan-out
  bounded by `PHINS_OCR_MAX_PDF_PAGES` and a small pool.
- Fact-store index: `(subject_id, fact_key)` index so contradiction detection
  is a lookup; contradictions remain recorded as `contradiction` facts.
- Worker autoscaling per A3.

**Touch points.** `services/document_processing_service.py`,
`services/agent_job_queue.py`, `database/models.py` (index on facts table
if persisted; otherwise in-memory dict index).

**Tests.**
- `tests/test_document_processing_service.py`: OCR called once per page
  across two identical uploads; contradiction still recorded, never
  resolved; page cap respected.
- `tests/test_document_job_worker.py`: concurrency scales with pending depth.

### B5. Pension Data Agent

**Changes.**
- Stream parsing with `defusedxml` `iterparse` for holdings/severance files;
  clear elements after processing.
- Precompile `MislakaSchemaMapping` lookups into dicts at import.
- Move `POST /api/mislaka/import` to the job queue (A3).
- Cache the aggregated `ClientProfile` by ZIP SHA-256 in `agent_artifacts`
  so Risk Reports "pension mode" reuses it.
- Split the module into `services/pension/{schema,parsers,profile,report}.py`
  with re-exports (`services/mislaka_affiliations.py` imports
  `MislakaSchemaMapping` and must keep working).

**Touch points.** `services/pension_data_agent.py` (+ package),
`services/mislaka_affiliations.py`, `services/ai_risk_reports_service.py`
(consume cached profile), `web_portal/server.py` (`/api/mislaka/import`).

**Tests.**
- `tests/test_mislaka_affiliations.py`, `tests/test_mislaka_workbench_surface.py`,
  `tests/test_ai_risk_reports.py::test_multi_xml_zip_merges_affiliated_pension_data`
  green.
- New: peak-memory test on a synthetic 50 MB XML (tracemalloc bound);
  streaming output equals tree-parse output on the fixture set; malformed
  XML rejected (`defusedxml` still in path, no `lxml` fallback bypass).

### B6. Customer Communication + Customer Service agents

**Changes.**
- One template registry in `notification_service.TemplateEngine`; `service_agent.py`
  drops its `underwriting_assistant.NotificationManager` dependency and uses
  `notification_service`.
- Merge into `services/customer_agent/` with two facades
  (`communication.py`, `service_desk.py`) sharing one interaction log
  (persisted via `agent_artifacts`) and one escalation path
  (`pipeline_service` ticket + `AuditLog`).
- Consent and throttle: check a per-customer channel consent flag and a
  per-customer daily send cap before WhatsApp/SMS
  (`RateLimiter` already exists in `notification_service.py`).
- `service_agent.py` remains as a compatibility shim exporting
  `CustomerServiceAgent`.

**Touch points.** `services/customer_agent/*` (new),
`services/customer_communication_agent.py` (shim),
`service_agent.py` (shim), `services/notification_service.py`,
`web_portal/api_extensions.py` (communication routes), `database/models.py`
(customer consent columns if absent).

**Tests.**
- `tests/test_customer_communication_agent.py`, `tests/test_service_agent.py`
  green through shims; add a test that both facades write to the same
  interaction log.
- Consent: WhatsApp send refused without consent; SMS cap enforced; OTP-gated
  path unchanged (`tests/test_otp_whatsapp_delivery.py`).

### B7. Marketing / Sales Agent

**Changes.**
- Anchor each published plan's HMAC and input hash on the platform ledger
  (`PlatformEventLedgerService`), not only in `DESIGN_SETTINGS`.
- Accept BI cohort inputs (`bi_analytics_service.get_customer_analytics`
  segments) as optional targeting; plan cache keyed by input hash.

**Touch points.** `services/marketing_sales_agent_service.py`,
`web_portal/server.py` (`/api/admin/marketing-sales-agent/publish`),
`services/platform_event_ledger_service.py` (event type).

**Tests.**
- `tests/test_marketing_sales_agent_service.py`: signature still verifies;
  publish writes a ledger entry; identical inputs hit the cache; cohort
  inputs change the playbook deterministically.

### B8. Video Agents

**Changes.**
- Default completion mode `webhook`, polling as fallback (invert current
  default; keep `VIDEO_AGENTS_*` env names).
- Durable `video_jobs` table via `HydratedStore` (A4); poll threads become
  queue jobs (A3) so a restart re-arms outstanding polls.
- Request dedupe: identical `(pipeline_type, prompt, provider, model)` within
  a campaign returns the existing job.
- Webhook signature verification is already present
  (`MEDIA_PROVIDER_WEBHOOK_SECRET`); add replay protection (nonce + timestamp
  window).

**Touch points.** `services/video_agents_service.py`,
`web_portal/api_extensions.py` (video routes),
`database/models.py`, `web_portal/static/video-agents.html`.

**Tests.**
- `tests/test_video_agents_service.py`, `tests/test_video_agents_integrity.py`
  green; add: restart re-arms in-flight jobs (SQLite mode); duplicate submit
  returns same `job_id`; replayed webhook rejected; webhook-then-poll and
  poll-then-webhook races produce exactly one terminal transition.

### B9. AI Risk Reports

**Changes.**
- Split 5,229 lines into `services/risk_reports/{parsers,analysis,charts,render,service}.py`
  with a re-exporting shim.
- Parsers delegate to `DocumentProcessingService` table extraction.
- Charts rendered lazily on `GET /api/reports/view` and cached in
  `agent_artifacts`.
- Generation moved to the job queue (A3).

**Touch points.** `services/ai_risk_reports_service.py` (+ package),
`web_portal/server.py` (`/api/reports/*`),
`web_portal/static/risk-reports-dashboard.html`, `risk-dashboard.html`.

**Tests.**
- `tests/test_ai_risk_reports.py` green (re-export test); generate without
  charts is faster than baseline on the fixture (assert charts not rendered
  until view); view renders once then hits cache; Hebrew/Arabic detection
  unchanged.

### B10. BI Analytics

**Changes.**
- Incremental invalidation: `invalidate_cache()` called from policy, claim,
  and billing write paths (currently fingerprint-based recompute on read).
- Scheduled materialization: `scheduler/runner.py` job writes dashboards to
  `PHINS_BI_SNAPSHOT_DIR` (machinery exists via `entrypoint.sh bi-snapshot`);
  `/api/bi/*` serves the snapshot when fresher than `cache_ttl_seconds`.
- `predict_revenue_forecast` becomes a scheduled job; route returns the last
  materialized forecast with `computed_at`.

**Touch points.** `services/bi_analytics_service.py`,
`web_portal/api_bi_analytics.py`, `scheduler/runner.py`,
`web_portal/server.py` (write-path invalidation hooks).

**Tests.**
- `tests/test_bi_analytics.py`, `tests/test_bi_analytics_routes.py`,
  `tests/test_bi_snapshots.py`: green; add: write to `POLICIES` invalidates;
  route serves snapshot with `computed_at`; forecast job idempotent.

### B11. Delivery Bidding AI

**Changes.**
- Geohash index on open requests for location matching.
- Supplier reliability score fed from settled-order outcomes
  (`supplier_settlement_service`), blended into bid ranking with a
  documented weight.
- SLA clock: bidding window expiry closes requests and emits an outbox event.

**Touch points.** `services/delivery_bidding_service.py`,
`web_portal/api_delivery_bidding.py` (`/api/delivery/evaluate-bids`),
`services/supplier_settlement_service.py` (read-only outcome accessor),
`database/marketplace_models.py` (window expiry column if persisted).

**Tests.**
- `tests/test_delivery_bidding.py`: geohash neighbors found, far suppliers
  excluded; ranking monotone in reliability; expired window rejects new bids
  and emits event.

### B12. AI Trading / AutoPilot

**Changes (safety first, self-contained).**
- Kill switch: `PHINS_TRADING_HALT=true` and an admin route
  `POST /api/terminal/autopilot/halt` stop all `execute_bot_trades`.
- Daily loss cap per bot and global, enforced before order submission.
- Shadow/paper mode for any new strategy version: `strategy_version` on the
  bot; a bot with an unpromoted version records intended trades without
  submitting.
- `_audit_bot_trade` becomes fail-closed on the execution path: if the audit
  row cannot be written, the order is not submitted (matching the
  ledger-repair posture in `PlatformEventLedgerService.persist_chain_to_db`).

**Touch points.** `services/ai_trading_engine.py` (`AutoPilotEngine`,
`execute_bot_trades`, `_audit_bot_trade`), `web_portal/server.py`
(`/api/terminal/autopilot/*`), `web_portal/static/trading-terminal.html`,
`algo-trading.html`, `AGENTS.md` env list.

**Tests.**
- `tests/test_ai_trading_engine.py`, `tests/test_algo_trading.py`,
  `tests/test_trading_platform_service.py`: green; add: halt flag blocks
  execution; loss cap blocks at threshold and logs; shadow bot never submits;
  audit persister raising → no order submitted and error surfaced.

---

## C. Human AgentOS follow-ups

- Per-renewal recurring commission: key accrual on `(affiliation_id,
  source_event_id, period)`; `services/agent_ecosystem_service.py`
  `_ACCRUED_KEYS` semantics extended; billing hook passes `period`.
- `agent_payouts`: new model + repository following
  `supplier_settlement_service.py`; admin routes
  `POST /api/admin/agents/payouts/run`, `GET /api/admin/agents/payouts`.
- Broker funnel metrics: `GET /api/agent/funnel` from BI customer analytics
  scoped to the agent's subtree (PII-minimized like the customer outline).

**Touch points.** `services/agent_ecosystem_service.py`,
`web_portal/api_agent_ecosystem.py`, `database/models.py`,
`database/repositories/agent_repository.py`, `docs/agent_ecosystem_design.md`,
`docs/uml/agent_ecosystem.puml`, `web_portal/static/agent-portal.html`,
`admin-agents.html`.

**Tests.** `tests/test_agent_ecosystem.py`: renewal accrues once per period,
never twice; payout run is idempotent and ledger-anchored; funnel endpoint
excludes other agents' subtrees.

---

## D. Sequencing (by dependency)

1. **A1 + A5 foundation**: runtime contract, helpers, metrics decorator,
   catalog completion. Low risk, touches every agent mechanically.
2. **A2 gateway** and **B12 trading safety** in parallel (independent).
3. **A3 job queue** generalization; migrate Document Intelligence first
   (already async), then B1 bots, B5 pension, B9 risk reports, B8 video.
4. **A4 durable state** for the migrated agents.
5. **A6 evaluation harness**; then B2 controller split and B3 golden sets.
6. Remaining per-agent refactors (B4, B6, B7, B10, B11) and C.

Every step ships behind a flag or a shim so `main` stays deployable through
`scripts/entrypoint.sh serve`.

## E. Cross-workstream verification

Run after each merged step:

```bash
pytest tests/test_agent_runtime.py tests/test_ai_capabilities.py -q
pytest tests/test_document_job_worker.py tests/test_agent_job_queue.py -q
pytest tests/test_ai_audit_bridge.py tests/test_ai_usage_service.py -q
pytest tests/ -q --tb=line          # full suite; embedded server on TEST_PORT
python3 web_portal/server.py --test
python3 validate_system.py
bash quick_smoke_test.sh
```

Acceptance criteria per workstream are the test lists above plus:
no change to JSON error shape `{"error": ...}` or pagination shape;
`/api/health` unchanged; no new hardcoded ports or `localhost:8000` in tests;
all new env vars documented in `AGENTS.md` §7.

## F. Risks and mitigations

| Risk | Mitigation |
|---|---|
| 202/job-id contract breaks dashboards | Flag-gated (`PHINS_AGENT_ASYNC`), sync path byte-identical, dashboards handle both |
| Durable state increases DB load | TTL read-through cache (proven in AgentOS), DB-side prune |
| Model registry scorer treated as authoritative | Decision computed from rules only; model score logged; test asserts equality |
| Module splits break imports | Shim modules re-export; import-parity tests per split |
| Fail-closed trading audit blocks trading during DB outage | That is the intended posture; halt is surfaced on the terminal UI |
| Shared helper swap changes edge-case behavior | Parity tests over edge fixtures before each swap |
| Two customer agents merged; `test_service_agent.py` depends on old shape | Compatibility shim keeps `CustomerServiceAgent` importable |

## G. Implementation status

### Shipped — §D step 1: A1 + A5 foundation

| Piece | Where | Notes |
|---|---|---|
| Runtime contract | `services/agent_runtime.py` | `AgentDescriptor`, `register()`, `registry()`, `health()`, `metrics()`, `overview()`. Discovery only; probes are read-only and never raise; same-module re-registration is idempotent, cross-module id claims are rejected. |
| Canonical helpers | `services/agent_helpers.py` | `safe_float/safe_int/status_lower/status_eq/status_in/utc_now_iso`. Variants of the private copies (comma stripping, `str()` coercion, finite-only, falsy-as-empty, no-strip) are explicit keyword options so any adoption is byte-for-byte identical. Parity tests in `tests/test_agent_helpers.py` cover the copies in `customer_communication_agent`, `marketing_sales_agent_service`, `ai_trading_engine`, `metrics_service`, and `web_portal/server.py`. The private copies are **not yet swapped**; that happens one module per commit with the parity test as the gate. |
| Per-agent metrics | `services/agent_metrics.py` | `instrument_agent` decorator (calls, errors, bounded latency reservoir, decision-label counts, in-flight), `set_gauge`, `snapshot_all`, `public_snapshot_all`, `check_slo` (`PHINS_AGENT_SLO_P95_MS`, `PHINS_AGENT_SLO_ERROR_RATE`, `PHINS_AGENT_SLO_MIN_CALLS`). Observation only: arguments and results pass through untouched, exceptions re-raise unchanged. |
| Registration + instrumentation | all 15 agent modules (§0 table plus `underwriting_assistant`) | Each module appends a `register(AgentDescriptor(...), health_fn=...)` block and decorates its entry methods. Health probes read module singletons only; they never instantiate a service. |
| Catalog | `services/ai_capabilities.py` | `ensure_agents_loaded()` imports `AGENT_MODULES` (guarded) and the catalog is static entries (text authoritative) merged with registry descriptors: 6 → 15 entries. `help_text(role, include_health=True)` attaches health + metrics for admin surfaces only. |
| Health route | `web_portal/api_extensions.py` → `GET /api/admin/ai-agents/health` | Admin only (401/403 otherwise). Returns descriptors, health, metrics, `slo_breaches`, `load_failures`, `health_summary`. |
| Metrics block | `web_portal/server.py` → `GET /api/metrics` | `metrics.agents` = `public_snapshot_all()` (counts/latency only; the endpoint is unauthenticated, so `last_error`/`last_error_at` and decision-label counts are withheld and stay on the admin health route). Business metrics unchanged. |
| Admin panel | `web_portal/static/admin.html` → `#ai-agents-ops` | Collapsed-by-default table over the health route with SLO/load-failure banner; all server values HTML-escaped. |
| Tests | `tests/test_agent_runtime.py`, `tests/test_agent_helpers.py`, `tests/test_agent_metrics.py`, `tests/test_agent_health_route.py`, `tests/test_admin_ai_agents_ops_static_integrity.py`, `tests/test_ai_capabilities.py` | Includes: every registered HTTP `api.path` is present in a real dispatcher; `LIB` agents resolve to an importable symbol; health view does not instantiate singletons. |

Deviations from the A1/A5 text above, and why:

- **The decorator does not write `ai_decision_log` records.** Emitting from the
  decorator as well as from the controller would double-record decisions.
  Decision *records* stay with the agents that own them; the decorator only
  counts labels. A6 will derive distributions from the log, not the counter.
- **Three agents have no HTTP route of their own** and are registered with
  `api.method = "LIB"`: `ai_automation_controller` (only exercised by root
  `test_integration.py`/`test_pr_complete.py`), `underwriting_assistant`, and
  `customer_service` (`service_agent.py`). The investor deck counts them; the
  portal does not currently call them. B2/B7 decide whether to wire or retire.
- **SLO evaluation is in-process** (`check_slo` surfaced by the health route
  and the admin panel) rather than a `scheduler/runner.py` job. The metrics
  live in the web process; a cron process would see an empty snapshot until
  A4 persists them. `scheduler/runner.py` is a one-line delegate for monthly
  auto-pay and was left untouched.
- **15 agents, not 14**: `underwriting_assistant` is registered separately
  from `customer_service` because they are distinct modules with distinct
  entry points.

### Shipped — §D step 2 (part): B12 AutoPilot safety controls

| Piece | Where | Notes |
|---|---|---|
| Kill switch | `services/ai_trading_engine.py` (`env_trading_halted`, `AutoPilotEngine.halt_trading/resume_trading/halt_status`) | Two levels: `PHINS_TRADING_HALT` (operator; read on every call; cannot be lifted via API) and a runtime halt. `execute_bot_trades` refuses before any evaluation or broker call and re-checks before **each** order so a halt that trips mid-run stops the remaining orders. Halt/resume are audited (`ai_trading_halted` / `ai_trading_resumed`, entity `trading_control`) and published as the `halted` gauge. |
| Loss caps | `AutoPilotEngine._loss_cap_block_locked` | Per-bot (`max_daily_loss`, existing) **and** global across bots (`PHINS_TRADING_GLOBAL_DAILY_LOSS_PCT` default 5% of portfolio, `PHINS_TRADING_GLOBAL_DAILY_LOSS_ABS` optional; the tighter wins). Evaluated before the loop and again before each submission. Blocks are audited (`ai_bot_trade_blocked`) and counted on the bot (`blocked_count`, `last_block`). `daily_pnl` now rolls over per UTC day (`pnl_day`); previously nothing ever called `reset_daily_pnl`, so the cap compared against a lifetime figure. |
| Shadow / paper mode | `strategy_version` on the bot; `AutoPilotEngine.promote_strategy_version/promoted_versions` | Only promoted versions (default `1.0`, `DEFAULT_STRATEGY_VERSION`) submit. Unpromoted versions, or `config.shadow=true`, record intents in `shadow_trades` (bounded, 500) — never in `trades`/`trade_count`, so P&L, win-rate and `record_trade_exit` matching are untouched. Audited as `ai_bot_trade_shadow`. Promotion is audited and takes effect on the next execution. |
| Fail-closed audit | `_audit_bot_trade(..., required=)` + execution path | The helper now **returns** whether a row persisted (still never raises). Before `submit_order` an `ai_bot_trade_intent` row is written; when `audit_required(platform)` and it did not persist, the order is not submitted, the run stops, and `audit_degraded_at` is set on the halt status. Policy `PHINS_TRADING_AUDIT_REQUIRED`: `auto` (default) = required exactly when the platform reports `is_connected` (paper or live broker), `true` always, `false` never. Post-execution row keeps parity; its result is stored on the trade as `audit_persisted`. |
| Routes | `web_portal/server.py` → `GET/POST /api/terminal/autopilot/halt`, `POST .../resume`, `POST .../promote` | Terminal access key **or** admin session (`PortalHandler._autopilot_control_actor`); the actor label is carried into the audit row. Existing autopilot routes and their response shapes are unchanged; `bots`/`create`/`performance` gain `mode`, `strategy_version`, `shadow_trade_count`, `blocked_count`. |
| UI | `web_portal/static/trading-terminal.html` AutoPilot tab | Halt banner + HALT ALL / RESUME ALL (env halt shown as non-resumable), Mode column (LIVE/SHADOW + version), shadow/blocked counts, EXEC gated while halted. Server text HTML-escaped. `algo-trading.html` has no AutoPilot surface, so it was left untouched. |
| Tests | `tests/test_ai_trading_safety.py` (22), `tests/test_autopilot_safety_routes.py` (6, HTTP through the embedded server), `tests/test_trading_terminal_static_integrity.py` (+4) | Existing `test_ai_trading_engine.py`, `test_algo_trading.py`, `test_trading_platform_service.py`, `test_ai_audit_bridge.py` pass unchanged. |

Deviations from the B12 text above, and why:

- **Demo/simulated platforms keep best-effort audit.** In `auto` mode the
  fail-closed rule applies only when `submit_order` reaches a real broker;
  otherwise every in-memory demo and test run would submit nothing without a
  database. Set `PHINS_TRADING_AUDIT_REQUIRED=true` to fail closed everywhere.
- **Halt is not admin-only.** The terminal access key already authorizes
  bot creation and execution, and the terminal UI has no session, so the same
  credential may halt/resume; an admin session also works. The env switch is
  the level that only an operator can lift.
- **Halt responses stay HTTP 200** with `[{"error": "Trading halted", ...}]`
  from `/execute`, matching the existing "Daily loss limit reached" shape the
  terminal UI already handles.

### Shipped — §D step 2 (remaining): A2 external-call gateway

| Piece | Where | Notes |
|---|---|---|
| Shared breaker | `services/circuit_breaker.py` (new); `services/notification_service.py` | `CircuitBreaker` lifted verbatim from `_SMTPCircuitBreaker`, which now subclasses it and only binds the SMTP thresholds/name. `test_notification_service.py` passes unchanged. |
| Gateway | `services/external_call_gateway.py` (new) — `ExternalCallGateway.call(provider_kind, request_fn, *, endpoint, operation, agent_id, budget_scope, budget, cache_key, cache_ttl, cache_when, max_retries, usage_from, meter, context)` | Order of policy: cache → budget → breaker → retry → meter. Cache values are deep-copied in **and** out (a caller can never mutate what another caller receives); failures are never cached, and neither is a result the caller's `cache_when` predicate rejects (schema-invalid completions). Budget is per `(scope, agent_id, UTC day)`; scope defaults to `context.customer_id`, else `global`; calls the provider does not bill pass `budget=False` and are neither charged nor refused. `BudgetExceeded` is raised **before** the provider is contacted and a `blocked=True` usage row (zero cost, no tokens) is recorded so refusals show in cost reporting. Transient = connection/timeout or HTTP 408/425/429/5xx; only those retry (full jitter, `Retry-After` honoured) and count toward the breaker. `snapshot()` / `reset()` for the admin health view and tests; `conftest.py` resets it before every test. |
| Metering schema | `services/ai_usage_service.py`, `database/models.py` (`AIUsageRecord.agent_id`, `.blocked`), `database/repositories/ai_usage_repository.py`, `database/__init__.py` (`_UPGRADE_NEW_COLUMNS`) | `record_usage(agent_id=, blocked=)`, `summarize(group_by="agent")`, `blocked` count per bucket and in totals, in memory **and** in SQL (`SUM(CASE WHEN blocked ...)`). Existing databases get both columns via `upgrade_schema`; `blocked` defaults to false for pre-existing rows. `usage_hook` no longer mutates the caller's context dict. |
| LLM | `services/llm_providers.py` (`OpenAICompatibleProvider._chat`), `services/assessment_ai_service.py` | HTTP + parse + `usage_hook` run **inside** `request_fn`, so the hook fires exactly once per real provider call — never on a cache hit, never on a failed attempt. Cache key = sha256 of endpoint + full chat payload (model, messages, temperature 0). Per-call usage is captured in a local box (provider instances are shared). `structured_completion` caches only schema-valid completions, so a bad reply is never replayed for later identical prompts. `agent_id` (default `assessment_ai`) and `call_context` (assessment service sets `customer_id`) drive budget scope and usage attribution. Budget refusal surfaces as a provider failure → the existing deterministic fallback. |
| Transcription | `services/transcription_providers.py` | Cache key = sha256 of the audio bytes + model + language hint, so an identical upload is not transcribed or billed twice within the TTL. Parsing and `_meter` also moved inside `request_fn` (one usage row per real call). |
| Media generation | `services/media_generation_service.py` (`_read_json_with_diagnostics`) | Breaker per provider host. `submit` is **never retried** (a 5xx after the provider may already have accepted a paid job would double-bill) and is metered as `video_submit` and charged to the daily budget; `poll`/`download` retry, are not billable, and pass `budget=False` so polling an in-flight job can neither exhaust the cap nor be refused by it. No cache on any media call (poll results change). Gateway refusals raise `MediaGenerationError` like any provider failure. |
| Admin view | `web_portal/api_extensions.py` → `GET /api/admin/ai-agents/health` | Additive `gateway` block: stats, breaker states, today's budget usage. |
| Tenant-scoped budgets (follow-up, PR #589) | `services/transcription_providers.py` (`transcribe(..., context=)`), `services/document_processing_service.py` (thread-local document scope), `services/media_generation_service.py` (`submit_video_generation(..., attribution=)`), `services/video_agents_service.py` | Closes the #588 security finding: transcription and video submits no longer fall back to one shared `global` bucket. Transcription is scoped by the owning customer (the document service binds `document_id`/`customer_id` to the processing thread for the duration of a pass, released in `finally`, so the 12 `(raw, mime, ext)` handlers are untouched); video submits scope to the customer when present, else `user:<submitter>`. Only `customer_id`/`document_id`/`job_id` are accepted from caller context so nothing else can reach metering. |
| Tests | `tests/test_external_call_gateway.py` (19), `tests/test_gateway_provider_integration.py` (15), `tests/test_ai_usage_service.py` (+3: `group_by="agent"`, SQLite persistence round-trip for `agent_id`/`blocked`, legacy-table `upgrade_schema`) | Existing `test_llm_providers.py`, `test_transcription_providers.py`, `test_video_agents_service.py`, `test_video_agents_integrity.py`, `test_notification_service.py`, `test_media_processing.py`, `test_document*`, `test_assessment_*` pass unchanged. |

Deviations from the A2 text above, and why:

- **No `ai_call_cache` table.** The cache is in-memory only (bounded, 2048
  entries, soonest-expiring evicted first). A durable cache would add one
  write per external call and a stale-completion risk across deploys for a
  saving that only matters within a process's lifetime; revisit with A4 if
  cross-instance hit rates justify it.
- **Provider-invocation cases live in `tests/test_gateway_provider_integration.py`**
  rather than one per existing provider suite, so the wiring can be reviewed
  and reverted as a unit; the existing suites are left byte-for-byte unchanged
  as the "gateway is transparent" proof.
- **Video Agents' job caps were not replaced.** They cap *jobs per user per
  day* (a product rule); the gateway caps *provider calls/tokens per
  customer/agent/day* (a cost rule). Both apply; unifying them would change
  product behaviour, which is out of scope here.

### Shipped — §D step 3: A3 generalized job queue

| Piece | Where | Notes |
|---|---|---|
| Queue | `services/agent_job_queue.py` (new, extracted) — `AgentJobQueue.register_handler(job_type, fn)`, `register_dead_letter_hook(subject_type, fn)`, `enqueue(job_type, *, document_id, subject_type, subject_id, submitted_by, priority, idempotency_key, input_params, max_attempts)`, `process_once`, `start/stop`, `get_job`, `list_jobs(...)`, `queue_stats`, `requeue_dead_letter`, `handlers()`, `active_threads()` | One table, one claim query, priority order preserved. `_claim_due` claims **only job types this process has a handler for**, so a worker never takes a job it cannot run (and a stale claim is recovered after `PHINS_DOC_CLAIM_TIMEOUT` as before). Retries follow `PHINS_DOC_RETRY_SCHEDULE` per job with an explicit `max_attempts` override (video submit uses 1). Concurrency: `PHINS_DOC_WORKER_CONCURRENCY` baseline, `PHINS_JOB_WORKER_MAX_CONCURRENCY` burst ceiling; burst threads spawn while `pending` exceeds the running threads and exit after `PHINS_JOB_WORKER_IDLE_POLLS` empty polls. Ledger events: documents keep `DOCUMENT_QUEUED/CLAIMED/...` names; other subjects emit `JOB_*` with their `subject_type` as entity type. In-memory and database modes share one code path. |
| Document binding | `services/document_job_worker.py` (shim) — `DocumentJobWorker(AgentJobQueue)`, `_DocumentBinding`, `bind_document_handlers`, `get_document_job_worker()` | Same public API; `get_document_job_worker()` and `get_job_queue()` return the **same** singleton. `tests/test_document_job_worker.py` (11) passes unchanged. |
| Schema | `database/models.py` (`DocumentProcessingJob.document_id` nullable; `subject_type`, `subject_id`, `submitted_by` indexed), `database/__init__.py` (`_UPGRADE_NEW_COLUMNS`, new `_UPGRADE_NULLABLE_COLUMNS`, `_sqlite_rebuild_table`) | PostgreSQL: `ALTER TABLE ... ALTER COLUMN document_id DROP NOT NULL`. SQLite cannot alter a column, so the table is rebuilt inside one transaction: create `<table>__rebuild_tmp` from the current model (FK target tables copied into the scratch metadata so DDL compiles), `INSERT ... SELECT` the shared columns, row-count check, drop old, rename, recreate indexes; any failure rolls back and leaves the original table untouched. Schema fingerprint includes the nullable list so an already-upgraded database is skipped. Document jobs mirror `document_id` into `subject_type='document'`/`subject_id`. |
| Adapters | `services/jobs/__init__.py` (`JobContext`, `register_all`, `queued_response`, `public_job_view`), `underwriting_bot_job.py`, `claims_bot_job.py`, `risk_report_job.py`, `pension_import_job.py`, `video_job.py` | Each adapter owns the route's former inline logic as a plain function (`run_*`) that **both** the synchronous branch and the queue handler call — one implementation, so parity is structural, not tested-in. Idempotency: underwriting = sha256(file bytes + filename) per submitter; claims = sha256(claim row) per submitter; risk reports and video accept an optional client `idempotency_key`. PII: Mislaka `id_number` is Fernet-encrypted (`security.vault`) inside `input_params` and only its sha256 prefix appears in `subject_id`; `public_job_view` strips `input_params` and `worker_id` from every HTTP job view, so neither uploaded file bytes nor the vault blob is ever served. Typed failures (`MislakaNotConfigured` → 503, `NoPoliciesFound` → 404) keep the synchronous status codes. The two bots get a `JobContext` (live references to `CUSTOMERS`/`POLICIES`/`UNDERWRITING_APPLICATIONS`/`CLAIMS`, `audit`, `sanitize_claim_probability_report`) — registered only when a context is supplied, which is why the standalone `entrypoint.sh worker` stays documents-only until A4 makes their state durable. |
| Routes | `web_portal/server.py` (`get_agent_job_queue()`, `get_agent_job_context()`, `_job_visible_to()`; `POST /api/claims/probability-report`, `POST /api/risk-dashboard/ai-assess`, `POST /api/reports/analyze`, `POST /api/reports/generate`, `POST /api/mislaka/import`; `GET /api/jobs/{id}`; `GET /api/doc-service/jobs`; `/api/health`), `web_portal/api_extensions.py` (`handle_video_jobs_submit`) | Under `PHINS_AGENT_ASYNC=true` each route validates and authorizes exactly as before, then enqueues and answers `202 {job_id, status, poll_url}` (an idempotent re-submit returns the existing job with its real status); with the flag off it calls the same adapter function inline. `GET /api/jobs/{id}` is scoped to the submitter (matched on username / user_id / customer_id, whichever the route recorded) or a document-admin role; anyone else receives 404 so ids cannot be enumerated. `/api/doc-service/jobs` (staff) gains `subject_type`/`subject_id`/`job_type`/`submitted_by` filters and reports `handlers` and `threads`. `/api/health` gains `agent_jobs {async_enabled, queue, threads, max_threads}`. `get_agent_job_queue()` binds the adapters at startup (so agent jobs left pending by a previous process are claimed at boot) and re-binds if the store globals are swapped by database recovery. Finding: `/api/admin/media/video-agents/submit` in `api_extensions.dispatch_post` is not forwarded by `do_POST` (only the security/foundations prefixes are); it is reachable only via the dispatcher, which is how its existing tests and the new one drive it. Wiring it over HTTP is a separate decision. |
| Dashboards | `web_portal/static/agent-jobs.js` (new, `phinsAwaitJob`), `admin.html`, `claims-adjuster-dashboard.html`, `risk-reports-dashboard.html`, `risk-dashboard.html` | `phinsAwaitJob(response, {token, onProgress})` returns any non-202 response untouched; for a job envelope it polls `poll_url` with the bearer token (1s → 5s, 3-minute cap) and returns a Response-like object whose `json()` is the job result — `failed` → 500 `{error}`, `dead_letter` → 503, timeout → 504 — so each page's existing `if (!response.ok) ... await response.json()` is unchanged. All seven static callers of the migrated routes are wrapped (`video-agents.html` uses the inline `/api/admin/media/video-jobs/batch` route, which was not migrated). |
| Ops | `scripts/entrypoint.sh`, `scripts/run_document_worker.py`, `AGENTS.md` | Worker help text and docstring state the documents-only scope of the standalone worker; `AGENTS.md` documents the queue, `PHINS_AGENT_ASYNC`, the concurrency variables, `GET /api/jobs/{id}` and `agent-jobs.js`. |
| Tests | `tests/test_agent_job_queue.py` (24), `tests/test_jobs_adapters.py` (15), `tests/test_agent_async_routes.py` (10), `tests/test_agent_jobs_static.py` (4) | Queue: registry dispatch, subject mirroring, unregistered types stay pending, per-type idempotency, retry → dead-letter, claim-expiry recovery, priority, events, filters, burst scaling up and down, singleton identity, SQLite persistence of a non-document job, SQLite `document_id` rebuild migration (data, indexes, FKs preserved). Adapters: golden parity per agent in memory and (claims) in SQLite, idempotency scope, PII never in `subject_id`/views, typed failures, `max_attempts=1` for video. HTTP: flag-off bodies unchanged, 202 → pending → completed with `_stable(result) == _stable(sync_body)`, validation/authorization before enqueue, submitter/staff/intruder scope (401/404/200), admin listing redaction and filters, national ID absent from every view, 503/404 mapping for Mislaka. Static: every caller wrapped, helper exercised under node. Existing `test_document_job_worker.py`, `test_video_agents_service.py`, `test_ai_risk_reports.py`, `test_claims_bot*.py`, `test_underwriting_bot*.py`, `test_mislaka*.py`, `test_document_processing*.py` pass unchanged. |

Deviations from the A3 text above, and why:

- **Five adapter tests live in one file** (`tests/test_jobs_adapters.py`)
  rather than `tests/test_jobs_<agent>.py` each, because they share the
  `_stable()` normaliser and the fixture that builds a `JobContext`.
- **`submitted_by` column added** beyond `subject_type`/`subject_id`: the
  submitter scope for `GET /api/jobs/{id}` needs a principal on the row, and
  encoding it inside `input_params` would have meant reading the private
  field to authorize.
- **Video Agents' route stays dispatcher-level** (see the wiring finding in
  the Routes row); the dashboard uses the inline batch route, which keeps its
  own queue and was not part of A3.

### Shipped — §D step 4: A4 durable agent state

| Piece | Where | Notes |
|---|---|---|
| Store | `services/hydrated_store.py` (new) — `RefreshCoalescer(ttl)`, `db_mode_enabled()`, `to_jsonable`/`from_jsonable`, `HydratedStore(loader, saver, deleter, key_fn, ttl, full_resync_seconds, enabled)`, `ArtifactStore`, `artifact_store(agent_id, kind, cls)`, `reset_shared_stores()` | A `MutableMapping`, so every consumer keeps its `dict` call sites. Read path: TTL-coalesced (`PHINS_AGENT_HYDRATE_TTL`, shared with AgentOS) **incremental** hydration by `updated_date` watermark, plus a periodic full re-pull (`PHINS_AGENT_FULL_RESYNC_SECONDS`, default 60) so a peer's deletes are seen. Write path: durable write **first**, then cache; a failed durable write raises the error to the caller's log, keeps the record in cache and in an `unsaved` set that is re-merged after every full resync, so nothing is silently dropped and the health probe can count it. Loader failures serve the current cache and are reported (`load_failures`), never treated as "empty". Codec is lossless for nested dataclasses, `Enum`, `datetime` and dict/list containers, and refuses unknown objects rather than stringifying them. `enabled` is re-evaluated per call, so runtime database recovery / tests flipping `USE_DATABASE` take effect without re-instantiation. In memory mode a store is a plain per-instance dict with no table access at all. |
| Schema | `database/models.py` (`AgentArtifact`: `id`, `agent_id`, `subject_type`, `subject_id`, `kind`, `payload_json`, `checksum`, `created_date`, `updated_date`, all lookup columns indexed; `VideoJob`: lifecycle columns + `payload_json`) | No `database/__init__.py` change was needed: both tables are in `Base.metadata`, `create_all` creates them and `_schema_fingerprint()` folds every table name in, so an already-initialised deployment re-runs the DDL sync once on first boot after deploy (verified against SQLite). |
| Repos | `database/repositories/agent_artifact_repository.py`, `video_job_repository.py` (new); `DatabaseManager.agent_artifacts`, `.video_jobs` | Artifacts: `canonical_payload()` = sorted-key JSON + sha256; `upsert` is idempotent and leaves `subject_type`/`subject_id` alone when the caller omits them; every load path runs `_verified()`, and a row whose checksum does not match its payload is **skipped and logged**, never served; `prune(agent_id, kind, keep)` deletes oldest-first by `updated_date`. Video jobs: `mark_terminal` and `update_fields` are read-merge-CAS conditional UPDATEs on `status` (+`updated_at`), so of two racers exactly one row transition commits and the loser is told so — the in-process `_JobStore` guarantee now holds across processes. |
| Claims Bot | `services/claims_bot_service.py` | `self.reports` is `artifact_store("claims_bot", "probability_report", ClaimProbabilityReport)`. `MAX_RETAINED_REPORTS` is a DB-side `prune_durable` in DB mode (in-memory eviction otherwise). `_claims_bot_health` reads `snapshot()` (cached counts, `durable`, `unsaved`, `load_failures`) — no table query on the health path. `_analyze_document_authenticity` now tolerates a `None` description, which the DB-backed `CLAIMS` dict yields where the in-memory dict yielded `''`. |
| Underwriting Bot | `services/underwriting_bot_service.py` | `assessments`, `metadata_store`, `reports` are all artifact stores; every mutation point (`start_assessment`, `add_metadata`, `process_metadata`, `process_all_metadata`, `run_risk_assessment`, `apply_decision`) checkpoints the owning assessment, so a **multi-step assessment started in one process can be continued and decided in another** with identical `extracted_data`. `MAX_RETAINED_ASSESSMENTS` with `prune_durable`. |
| Video Agents | `services/video_agents_service.py` | `_JobStore` keeps its API but is a `HydratedStore` over `video_jobs`; `update`/`mark_terminal` go through the repository's conditional UPDATE in DB mode, so the webhook handler and a poller in different processes cannot both finalise a job. Per-user/per-campaign/per-day counts read the cache. |
| Risk Reports | `services/ai_risk_reports_service.py` | `documents`, `analyses`, `reports` are artifact stores. `save_data()` is a no-op for the default path in DB mode (each write already went to the table); `load_data()` performs a **one-time migration** of an existing legacy JSON file into `agent_artifacts` only when the table is empty for that agent, so no records are duplicated or lost on the first durable boot. Memory mode keeps the JSON file exactly as before. |
| AgentOS | `services/agent_ecosystem_service.py` | Adopts `RefreshCoalescer` and `db_mode_enabled()`; behaviour unchanged (`tests/test_agent_ecosystem.py`, `test_agent_runtime.py` green). |
| Worker | `services/jobs/__init__.py` (`worker_context()`), `services/jobs/claims_bot_job.py` (`sanitize_claim_probability_report` moved here; `web_portal/server.py` delegates to it), `scripts/run_document_worker.py`, `scripts/entrypoint.sh` | With agent state durable, the standalone `entrypoint.sh worker` now binds **every** adapter (`PHINS_WORKER_AGENT_JOBS`, default true) over the `database.data_access` DB-backed dicts and a real `AuditService`; it produces the same sanitised report body as the web process for the same claim (parity test). `PHINS_WORKER_AGENT_JOBS=false` restores documents-only. |
| Docs | `AGENTS.md` | Durable-state paragraph, `agent_artifacts`/`video_jobs` in the repository list, the two new environment variables and `PHINS_WORKER_AGENT_JOBS`, refreshed module/repository counts (108 services, 20 repositories, 42 `DatabaseManager` properties, 223 test files). |
| Tests | `tests/test_hydrated_store.py` (16), `tests/test_agent_durable_state.py` (13) | Store: TTL gating/force/reset; memory mode never touches the table; write-then-forced-refresh; incremental hydration and full resync surfacing peer deletes; loader and saver failure handling (cache served, error reported, unsaved retained); `enabled` re-evaluation; lossless codec round-trip. Repos over one shared SQLite file: cross-instance visibility, corrupted-checksum row skipped, `prune`, `mark_terminal` race (exactly one winner). End-to-end in DB mode: claims report survives restart and is shared; retention is a DB prune; health probe reports durability without querying; underwriting assessment continued by a fresh instance; `process_all_metadata` keeps items/status consistent; video store durable and shared, webhook path, cross-store terminal race; risk-reports pipeline continued by a peer; legacy JSON migrated once; standalone worker ↔ web parity for the claims job; memory mode untouched. Existing `test_claims_bot*.py`, `test_underwriting_bot*.py`, `test_video_agents_service.py`, `test_ai_risk_reports.py`, `test_ai_audit_bridge.py`, `test_jobs_adapters.py`, `test_agent_ecosystem.py`, `test_agent_runtime.py` pass unchanged. |

Deviations from the A4 text above, and why:

- **Constructor shape** is `HydratedStore(loader, saver, deleter, ...)` rather
  than `HydratedStore(table_repo, ...)`: the four consumers need different
  repository methods (artifact upsert vs. video conditional update), and
  passing callables keeps the store free of any repository import, so it is
  testable with a fake table.
- **`updated_date` added** to `agent_artifacts` beyond the listed columns:
  incremental hydration and oldest-first pruning both need it.
- **Underwriting assessments and metadata** are durable too, not only its
  reports: a report cannot be regenerated after a restart if the assessment
  it summarises is gone, and the multi-step flow is exactly the case a
  restart breaks.
- **Shared store instances in DB mode** (`artifact_store` returns one object
  per `(agent_id, kind)` per process): two `ClaimsBotService` instances in
  one process would otherwise hydrate the same rows twice. Memory mode keeps
  per-instance dicts so existing unit tests see isolated state.
- **`database/__init__.py` untouched**: `create_all` and the schema
  fingerprint already cover new tables (see the Schema row).

### Shipped — §D step 5: A6 evaluation harness, B2 controller split, B3 Assessment AI golden set

| Piece | Where | Notes |
|---|---|---|
| Harness | `services/agent_eval.py` (new) — `LabelledSample`, `samples_from_decision_log`, `underwriting_scorer`, `confusion_counts`, `score_segment`, `replay`, `propose_thresholds`, `evaluate(agent_id)`, `run_golden` / `run_all_golden`, `register_golden_runner` | Read-only over the append-only decision log / assessment records / fixture files. `replay` reports per-segment confusion, approve/reject precision-recall-F1, agreement rate, review share, override rate and the two costly disagreements (`approved_but_rejected`, `rejected_but_approved`); segments below `min_samples` are `insufficient_data`. Labels: a human override is **explicit**; an un-overridden auto approve/reject is an **implicit** confirmation, counted separately (`implicit=false` excludes them); `human_review` without an override is unlabelled. `propose_thresholds` picks, per segment, the most automated grid cut-off meeting `target_precision`, is monotone in the target, and — an addition to the §A6 text — enforces an **evidence floor**: a cut-off may move toward more automation only if the newly automated band holds ≥ `max(5, min_samples//4)` labelled decisions, and never past the highest/lowest reviewed score in that band. Precision alone cannot vouch for a band nobody has reviewed. Never promotes. |
| Claims Bot | `services/claims_bot_service.py` | `calibrate_claims_thresholds` keeps its report shape and grid but tallies through `agent_eval.confusion_counts` (`tests/test_claims_bot_threshold_calibration.py` unchanged, 7/7). Exposed as `evaluate('claims_bot')`. |
| Threshold snapshot | `services/ai_threshold_config.py` — `ThresholdConfig.export()` / `import_(snapshot)` | Deep-copied snapshot for before/after audit records and test teardown; `import_` validates every segment like `promote` and replaces the map atomically (all-or-nothing). |
| Routes | `web_portal/api_extensions.py` — `GET /api/admin/ai-agents/eval/{agent_id}` (admin/actuary; `min_samples`, `target_precision`, `implicit`), `POST /api/admin/ai-agents/thresholds/promote` (admin); `web_portal/server.py` forwards the `/api/admin/ai-agents/` POST prefix to the extension dispatcher | Promotion requires `segment`, `approve`, `reject`, `reason`; validates ranges and `reject < approve`; records **before/after** twice — an `ai_decision_log` row (`decision_type=threshold_promotion`, the fail-closed gate: if it cannot be written the promotion is rolled back with 503) and an `ai_threshold_promoted` audit row through the portal `AuditService` (durable in DB mode, in-memory otherwise; `record_ai_audit` fallback when the server module is not loaded). Unknown agent → 404 with the available list. |
| CLI + CI | `scripts/run_agent_eval.py` (`golden [--agent] [--update] [--json]`, `replay <agent> [--decisions|--records] [--min-samples] [--target-precision] [--explicit-only]`), `.github/workflows/agent_golden_sets.yml` | Golden fixtures `tests/golden/<agent>/*.json` = `{name, input, expected}`; only the keys `expected` lists are frozen (additive output changes never break a fixture; a changed value or missing key does; floats at 1e-6). `--update` rewrites `expected` keeping the fixture's key selection — an intentional, reviewed change. The CI job runs on `ai_automation_controller.py`, `services/**`, `prompts/**`, `schemas/**`, `tests/golden/**` changes. During this step the gate caught the `narrative-v1 → narrative-v2` prompt change before the fixtures were deliberately updated. |
| B2 split | `services/automation/{types,quoting,underwriting_gate,fraud,claims_gate,billing_schedule}.py` (new); `ai_automation_controller.py` orchestrates and re-exports every historical name | Rules are pure functions (no metrics, log, registry). `billing_schedule.next_quarter_start` / `invoice_due_date` is the single due-date path (assessment **D3 resolved**; Dec 31 / Jan 1 / Q4-start / leap-day / century edges tested). `segment_key` is derived on every underwriting decision; results and the decision-log row carry `segment`, `confidence_band` (`auto_approve` / `review_upper` / `review_lower` / `auto_reject` / `fraud_hold`) and `threshold_margin` (distance to the nearest cut-off). The function-based `auto_underwrite` gains the same three keys additively. Metrics counters, result dicts and `auto_generate_invoice`'s datetime shape are unchanged. |
| B3 prompts | `prompts/__init__.py` (`PromptTemplate.sha256`, `.provenance()`; `list_prompts` includes `sha256`), `prompts/assessment/narrative_v2.py` (new, structured), `schemas/assessment_narrative.json` (new), `services/llm_providers.py` (`load_schema(name)`; validator gains `minItems`/`maxItems`) | `narrative-v1` stays registered and immutable (pin with `PHINS_ASSESSMENT_NARRATIVE_PROMPT_VERSION=1`); `get_prompt("narrative")` now resolves to v2, whose response must validate against `schemas/assessment_narrative.json` (`summary_text`, `key_points[{point, evidence_index}]`, `review_flags`, `needs_review`). |
| B3 service | `services/assessment_ai_service.py` | Every narrative, its audit record and the persisted assessment artefact carry `prompt_id`, `prompt_version` (kept as the platform-wide versioned-id string), `prompt_version_number`, `prompt_sha256`, `schema_id`. The live path is `structured_completion` (provider retries a schema-invalid reply `PHINS_LLM_VALIDATION_RETRIES` times with the errors appended); the service re-validates the object, rejects `needs_review != true` and any `evidence_index` outside the evidence it sent, and on any failure falls back to the deterministic narrative with `fallback_reason` recorded in the narrative and the audit trail. `key_points` / `review_flags` are new additive fields (empty in deterministic mode). Production redaction unchanged. |
| Golden sets | `tests/golden/ai_automation_controller/` (3: auto-approve, auto-reject, mid-band review), `tests/golden/assessment_ai/` (2: two-document onboarding, no-evidence service) | Controller fixtures freeze `decision`, `risk_score`, `segment`, `confidence_band`, `threshold_margin` and the ladder's details; narrative fixtures freeze mode/model, prompt provenance (including `prompt_sha256`), `summary_text`, `highlights`, `evidence`, `facts_digest`, `key_points`, `review_flags`. |
| Docs | `AGENTS.md`, `AI_ARCHITECTURE.md` (module layout, calibration loop replaces "edit the constants"), `PHINS_PLATFORM_ASSESSMENT.md` (D3 marked resolved) | |
| Tests | `tests/test_agent_eval.py` (19), `tests/test_billing_schedule.py` (23), `tests/test_assessment_ai_narrative.py` (+7), `tests/test_llm_providers.py` (registry/provenance asserts) | Replay P/R/confusion on a synthetic labelled set; min-sample guard; explicit/implicit/skip mapping; monotone proposals, unreachable target, evidence floor; `ThresholdConfig` round-trip and all-or-nothing import; end-to-end replay over the real decision log with a promoted segment (config restored); golden pass/fail/missing-key/error/update; committed fixtures pass; eval route authz/404/400/200; promote route validation, admin-only, before/after in decision log and audit row, rollback when the decision log refuses; both routes over HTTP through the embedded server. B2: quarter edges, single schedule path via frozen clock, re-exports, rule/controller parity, `confidence_band`, promoted segment changes only its own segment. B3: prompt hash on narrative and audit, hash changes only with text, valid structured reply used, schema-invalid reply retried then deterministic fallback with reason, service rejects out-of-range `evidence_index` / `needs_review=false`, production payload redacted, pinned v1 free-text path. |

Deviations from the §A6/§B2/§B3 text above, and why:

- **Evidence floor on proposals** (not in §A6): a target-precision search
  over a sparse log would otherwise recommend widening automation into score
  bands with zero reviewed decisions; in regulated underwriting a proposal has
  to point at the reviews that justify it.
- **`prompt_version` stays a string** (`narrative-v2`), with the integer in
  `prompt_version_number`: usage metering, persisted artefacts and existing
  tests already treat `prompt_version` as the versioned id.
- **`services/automation/claims_gate.py`** is a fifth module beyond the four
  §B2 lists: the claims ladder is neither fraud nor underwriting.
- **Promotion is admin-only** (eval is admin/actuary): it is the one mutating
  step and the test plan already required non-admin → 403.
- **Evaluators exist for `ai_automation_controller` and `claims_bot`**: they
  are the two agents whose decisions and human outcomes are both on record
  (`ai_decision_log` and `claims_fraud` assessment records). The Underwriting
  Bot's `apply_decision` had no logged human counter-decision at that point;
  it joined the harness in step 6 (B1, below).

### Shipped — §D step 6 (part 1): B1 Underwriting Bot + Claims Bot, B4 Document Intelligence

| Piece | Where | Notes |
|---|---|---|
| Fact-store indexes (B4) | `services/assessment_center_service.py` — `_by_document` (`source_document_id → facts`), `_by_field` (`customer_id → (fact_type, label) → facts`), `facts_for_documents(ids)`, `_index_fact` / `_rebuild_indexes` | Maintained incrementally in `_store_facts`, rebuilt on retention trim and disk load, cleared on `reset`. `detect_fact_conflicts` now visits only the `(fact_type, label)` buckets that can conflict (`CONFLICT_SENSITIVE_LABELS` + numeric `CONFLICT_NUMERIC_TYPES`) instead of scanning every fact; `get_document_assessments` reads the document index. Output of both is unchanged — contradictions are still stored as `contradiction` facts and both values stay on file. |
| OCR page cache (B4) | `services/document_processing_service.py` — class-level LRU keyed `(sha256(bytes), page, langs, dpi)`; `ocr_cache_stats()` / `reset_ocr_cache()`; `PHINS_OCR_POOL_SIZE` (default 2), `PHINS_OCR_CACHE_MAX_ENTRIES` (default 2000) | A PDF whose page count and every page text are cached is returned without rasterising; otherwise pages fan out over a `ThreadPoolExecutor` bounded by the pool size and `PHINS_OCR_MAX_PDF_PAGES`. A page whose OCR raised is returned as `''` and **not** cached, so the next run retries it. Single images cache under page `0`. `document_intelligence` health reports `ocr_cache` counters. |
| Shared evidence pipeline (B1) | `services/evidence_facts.py` (new) — `facts_for(document_ids)`, `documents_for_entity(entity_type, entity_id)`, `bundle_for` / `bundle_for_entity` → `EvidenceBundle` (facts, contradictions citing those documents, order-independent SHA fingerprint, provenance projection), `FeatureCache` (`(namespace, sha256)` LRU, deep-copied in and out) | Read side of the fact store for the bots; writes nothing. Contradictions travel with the bundle so a consumer can lower a score and flag a human, never resolve. |
| Underwriting Bot package (B1) | `services/underwriting_bot/{report,features,service}.py` (new); `services/underwriting_bot_service.py` is a facade re-exporting every historical name (plus `ALLOWED_UPLOAD_DIRS`, `validate_file_path`, `sanitize_filename`) | Enums/dataclasses/`RiskAssessmentEngine` in `report`; path validation + analyzers in `features`; orchestration and accessors in `service`. The durable codec is annotation-driven, so rows written before the move load unchanged. Agent descriptor keeps `module='services.underwriting_bot_service'`. |
| Underwriting Bot behaviour (B1) | `services/underwriting_bot/service.py` — `add_metadata(document_id=…)`, `_analyze_with_cache`, `_merge_evidence_facts`, `run_risk_assessment` → `_shadow` + `_record_decision`, `apply_decision` → `_record_override`, `get_underwriting_bot_service` rebinding; `services/underwriting_bot/features.py` — `AudioAnalyzer._transcribe` | Analyzer results are cached by `(analyzer, sha256(bytes), day)`; degraded results (`NO_STT_AVAILABLE`, `STT_FAILED`, `MISSING_CONTENT`) are never cached so enabling a provider takes effect immediately. A metadata item linked to a `document_id` consumes the pipeline's facts: they fill gaps in what the analyzer read from the bytes (bytes win), are attached with full provenance under `evidence_facts`, and can stand alone when no bytes were supplied (`EVIDENCE_FROM_DOCUMENT_PIPELINE`). A recorded contradiction flags `SUSPICIOUS_EVIDENCE_CONTRADICTION` → `ValidationStatus.SUSPICIOUS`. Audio: caller transcript wins, else `get_transcription_provider().transcribe(...)`; `NO_STT_AVAILABLE` only when the provider is disabled, `STT_FAILED` when a configured provider errors, `stt` block records provider/model/language/segments. Every recommendation is appended to `ai_decision_log` (`decision_type=underwriting_bot_assessment`, `segment` from the customer snapshot, `rule_score` = `overall_risk_score`, shadow fields) and the report carries `decision_id` + `model_shadow`; a human `apply_decision` that differs from the recommendation (or sets `override_recommendation`) is recorded as the override — `decided_by='bot'` never is. The accessor rebuilds the singleton only when a caller passes store objects that differ by identity (a different `JobContext`), and both bots now keep the reference to an **empty** portal dict instead of replacing it with a fresh `{}`. |
| Claims Bot (B1) | `services/claims_bot_service.py` — `_evidence_bundle`, `_analyze_document_authenticity(claim, evidence)`, `_append_evidence_findings`, `_provenance_refs`, `_shadow`, `_record_decision`; `ClaimProbabilityReport.{evidence, evidence_provenance, decision_id, model_shadow}` | Documents attached to the claim through the document service count as supporting evidence (+0.05, same as `claim['files']`); a recorded contradiction subtracts 0.25 and adds a red flag naming the field; a document with no extractable text subtracts 0.05. Reports carry provenance **references** (fact id, document id/sha, page, offsets, timestamps) — never the source snippet — so the UI payload stays free of raw document text. Every report is logged (`decision_type=claims_bot_assessment`) with `rule_score` = authenticity probability and the `claims_scorer` shadow. |
| Model shadow (B1) | `services/model_shadow.py` (new) — `shadow_score(model_name, features, rule_score)` → `ShadowResult.as_log_fields()` (`rule_score`, `model_score`, `model_version`, `divergence`, `drift_alert`), `DriftMonitor` (rolling window p95 vs `PHINS_AI_DRIFT_THRESHOLD`, default 0.25; `PHINS_AI_DRIFT_WINDOW` 200; `PHINS_AI_DRIFT_MIN_SAMPLES` 20) | The model informs the log only; both bots' decisions are computed before it is consulted. Registry/model failures degrade to `model_score=None`, `model_version=rules-v1`. A drift alert fires once per breach episode (re-armed when the window recovers) as an `ai_model_drift` audit row via `record_ai_audit`. |
| Harness | `services/agent_eval.py` — `evaluate_underwriting_bot`, `EVALUATORS['underwriting_bot']`; `scripts/run_agent_eval.py` help text | Replays `underwriting_bot_assessment` decisions on `1 - risk_score` against the inverted `RiskAssessmentEngine.DECISION_RULES` (`conditional_approve_max_risk`, `refer_max_risk`); proposals are reported per segment in both spaces (`risk_rules`). Reachable through `GET /api/admin/ai-agents/eval/underwriting_bot` and the CLI unchanged. |
| Job adapter | `services/jobs/underwriting_bot_job.py` | Uses `get_underwriting_bot_service(...)` (shared read-through cache) instead of a fresh service per upload; response gains `decision_id`, `model_shadow`. `tests/test_jobs_adapters.py` treats `decision_id` as volatile like `report_id`. |
| Tests | `tests/test_evidence_pipeline.py` (32) | Indexes exact and consistent through trim/reload/reset, conflict detection equals the full-scan result; OCR: second run never rasterises, failed page retried, pool/cap respected, health counters; bundles (facts + contradictions + fingerprint + provenance), deleted documents excluded, feature cache bounded/copy-isolated; shadow: rules-only default, divergence, model errors degrade, alert once per episode and re-armed, audit row; bot STT (provider used, disabled vs failed, caller transcript wins), cache hit on identical bytes only and isolation from the stored object, facts consumed without bytes with provenance, contradiction → suspicious, bytes win over facts; decision logged with rule/model scores and segment, shadow never changes the recommendation, human counter-decision recorded and bot decision not, customers/claims deep-equal after a full run, harness evaluates the bot; accessor rebinding, facade/package identity, job adapter shares the instance; Claims Bot: pipeline docs raise the document score with snippet-free provenance and a logged decision, contradiction lowers it and is flagged with both values kept, shadow never changes the decision, report still generates when the document service is down. |

Deviations from the §B1/§B4 text above, and why:

- **Analyzers stay** — the bots still parse bytes when they are given bytes.
  The route accepts raw uploads that never pass through the document service;
  removing the parsers would break that path. The pipeline's facts are
  consumed whenever a `document_id` is linked, fill gaps, and can stand alone.
- **Claims Bot has no separate audio path**: claim audio reaches the bot as a
  document-service record whose transcript (`_analyze_audio` already uses the
  transcription provider) is on the fact store, so the STT change is in the
  Underwriting Bot's `AudioAnalyzer` only.
- **Claims Bot evidence features are not SHA-cached**: facts for unchanged
  bytes can still arrive later (async enrichment), so a content-keyed cache
  would serve a stale bundle; the indexed lookup is already O(documents).
- **Feature-cache key includes the day** so an expiry-based analyzer verdict
  cannot outlive its expiry date in cache.
- **`decision_id`** was added to the bots' reports (not in §B1) because the
  human counter-decision has to name the AI decision it answers.

### Shipped — §D step 6 (part 2): B5 Pension Data Agent, B9 AI Risk Reports

| Piece | Where | Notes |
|---|---|---|
| Pension package (B5) | `services/pension/{schema,profile,parsers,report,cache,agent}.py` (new); `services/pension_data_agent.py` is a facade re-exporting every historical name (`__getattr__` forwards the `_pension_agent` singleton slot) | `MislakaSchemaMapping` moved verbatim into `schema` together with `tag_variants` / `CompiledFields` (every tag's spelling variants precompiled once at import); `ClientProfile` in `profile`; `MislakaParserMixin` (XML tree + streaming, Excel, CSV) in `parsers`; enrichment, health score, report and recommendations in `report`; `PensionDataAgent`, accessors, health probe and registration in `agent`. `services/mislaka_affiliations.py` and `web_portal/server.py` keep importing `MislakaSchemaMapping` from the facade. Agent descriptor keeps `module='services.pension_data_agent'`. |
| Per-parse text index (B5) | `services/pension/parsers.py` — `_parse_context` (thread-local `_ParseContext`), `_text_index`, `_forget_index`, `_find_text(elem, variants)` | One pass builds `element → {tag → text}`; `_find_text` becomes a dict lookup instead of a `.//` scan per candidate spelling per field. Semantics equal `find()` (first match in document order), verified against the old implementation on the fixture set; the index is released per provider block (tree path) so peak memory stays bounded. |
| Streaming parser (B5) | `services/pension/parsers.py` — `_parse_mislaka_xml_streaming` (`defusedxml` `iterparse`, `start`/`end` events), `_harvest_block`, `_release_block`, `_assemble`; `PHINS_PENSION_STREAM_MIN_BYTES` (default 8 MiB) | Files at or above the threshold are parsed block by block: each provider subtree is harvested into the accumulator and cleared from the tree before the next one is read. Output is identical to the tree parser on every fixture (asserted); malformed XML and entity declarations are rejected on both paths (`defusedxml` stays in the path — no `lxml` bypass); an undeclared legacy encoding (`windows-1255` without an XML declaration) falls back to the tree parser rather than mis-decoding. Measured on a synthetic 4 × 25-account file: 3.6× lower peak allocation and ~2× faster than the tree parse. Health reports `stream_min_bytes`. |
| Parse-result cache (B5) | `services/pension/cache.py` (new) — `ParseResultCache.get/put(kind, sha256)`, key `PENSION-{xml\|zip}-{sha256}-v{PARSER_VERSION}`; process LRU (`PHINS_PENSION_PARSE_CACHE_MAX`, default 128) plus, in DB mode, rows in `agent_artifacts` (`agent_id=pension_data_agent`, `kind=parse_result`); `PHINS_PENSION_PARSE_CACHE=false` disables | Only the deterministic parser output is cached — the `_parse_mislaka_xml` dict for an XML and the aggregated `ClientProfile.to_dict()` for a ZIP — never the enriched/report layer, which depends on the clock. Values are deep-copied on both sides so a consumer normalising the client block in place (Risk Reports does) cannot poison the cache; a checksum-failed or older-`PARSER_VERSION` row is skipped, never served; malformed input is never cached. After a database error the durable tier is paused for 60 s (`durable_paused` in health) so a broken table cannot slow every parse. `process_xml_content` / `process_zip_content` consult it; a ZIP miss still reuses cached members. |
| Risk Reports package (B9) | `services/risk_reports/{models,parsers,analysis,charts,render,service}.py` (new, sliced verbatim by method); `services/ai_risk_reports_service.py` is a facade re-exporting the package and forwarding `AI_REPORTS_DATA_FILE` and the `_ai_reports_service` slot **both ways** (module-class swap), so `monkeypatch.setattr(facade, …)` still steers the service | `AIRiskReportsService(ParserMixin, AnalysisMixin, ChartsMixin, RenderMixin)` keeps orchestration (`parse_file`, `analyze`, `generate_report`), the A4 stores, authorisation, persistence and registration; `parse_content(filename, bytes, type) → (parsed, encoding)` is the pure dispatcher `parse_file` wraps. Output verified byte-identical to the pre-split module for CSV (English, Hebrew, ID/savings), Mislaka XML, mixed-shape XML, ZIP, PDF and PNG inputs across parsed data, analysis, report and download summary. Descriptor keeps `module='services.ai_risk_reports_service'`. |
| Extractor delegation (B9) | `services/risk_reports/parsers.py` — `_parse_pdf`, `_parse_image` call `DocumentProcessingService._extract_pdf_text_with_pages` / `_image_metadata` / `_ocr_image_bytes` through `get_document_service()` | PDF text (pypdf text layer → regex → OCR, with the B4 page cache) arrives as one `page_N_text` row per page (capped at 4,000 chars per row, 50 pages) plus `parsed['text']`, `text_pages` (page → char offsets) and `text_extraction`; image OCR as an `ocr_text` row. The extractor's "no text" marker and sub-threshold text keep the historical metadata-only table, as does an unavailable extractor. `page_count` is exact when the page tree was read (`/Type /Pages` nodes no longer count as pages). `analyze()` uses the extracted text for language detection and Hebrew field extraction when present — tabular uploads have no `text` and are analysed exactly as before. |
| Charts (B9) | `services/risk_reports/charts.py` | Unchanged builders, measured: 0.03 ms (5 configs, CSV) to 0.16 ms (pension fixture), ≤ 1.6 % of `generate_report`; 0.1–8 % of the report payload; JSON only. |
| Tests | `tests/test_pension_agent.py` (31), `tests/test_risk_reports_package.py` (31) | Pension: facade identity, `mislaka_affiliations` mapping, descriptor module; `_find_text` index semantics and thread-locality; streaming == tree on every fixture, threshold selects the path, peak-memory bound, malformed/entity rejection on both paths, legacy-encoding fallback, blocks released; cache keying (version + kind), copy isolation, LRU bound and disable flag, XML served from cache with report regenerated, ZIP by archive and member hash, poisoning impossible, malformed never cached, broken durable tier paused; durable round trip across "processes"/peers, corrupted row skipped, old version ignored, peer parse reused without the parser; Risk Reports parse the same XML once across two uploads. Risk Reports: facade re-exports and two-way forwarding (path honoured by `save_data`), descriptor/capabilities module, layers usable standalone; `parse_content == parse_file` for 8 input kinds, purity, malformed ZIP fails closed, unknown binary fallback, Hebrew/Arabic detection unchanged; PDF text layer reaches rows with page offsets, Hebrew text drives language + policy-number factor + Hebrew report, filename hint, no-text/marker/unavailable-extractor degrade to the legacy table, image dimensions + OCR from the shared extractor, per-row cap; charts are JSON without rendered payloads, cost bound, gauge first; JSON persistence round trip. |

Deviations from the §B5/§B9 text above, and why:

- **No lazy chart rendering / `agent_artifacts` chart cache.** The design
  assumed charts were rendered server-side. They are `ChartConfig` data
  (labels, values, thresholds) the dashboard draws in the browser; building
  them costs 0.03–0.16 ms against a 10–56 ms report. A cache layer would add a
  read path and an invalidation rule for no measurable gain, so charts stay in
  the report as before.
- **CSV/Excel parsing is not delegated** to `DocumentProcessingService`. Its
  `_parse_csv_table` is a plain-comma reader; Risk Reports' `_parse_csv`
  handles delimiter sniffing, BOMs and `windows-1255`, and `_parse_excel`
  recognises Mislaka Excel exports. Delegation was limited to PDF and image
  text extraction, where the document service is strictly more capable.
- **XML parse results are cached, not only ZIP profiles.** Risk Reports
  uploads single XML files far more often than archives; caching the
  per-file parser output also lets a ZIP miss reuse already-seen members.
- **`POST /api/mislaka/import`** was already on the job queue from A3
  (`services/jobs/pension_import_job.py`); nothing to move.
- **`page_count` changed** for PDFs whose only `/Type /Page` hits were the
  page-tree node: it was over-counted by one before.

### Shipped — §D step 6 (part 3): B8 Video Agents, B10 BI Analytics

| Piece | Where | Notes |
|---|---|---|
| Deferred queue rows (A3 primitive for B8/B10) | `services/agent_job_queue.py` — `enqueue(..., delay_seconds=N)`, `RescheduleJob(delay)`; `database/repositories/document_repository.py` `_due_query` | A pending row is parked until `next_retry_at`; a handler that raises `RescheduleJob` puts its **own** row back to pending with a new `next_retry_at` — no attempt consumed, no error recorded, claim released — so a long poll loop is one durable row that survives a restart. SQLite/Postgres claim only pending rows whose `next_retry_at` is null or past (they were claimed immediately before). Stats gain `rescheduled`. |
| Completion mode (B8) | `web_portal/server.py` — `media_video_default_completion_mode`, `resolve_media_video_completion_mode`, `VIDEO_AGENTS_COMPLETION_MODE`; mirrored in `services/video_agents_service.py` `resolve_completion_mode` | Server default is `webhook` (`VIDEO_AGENTS_COMPLETION_MODE`); an explicit `poll_mode` wins; webhook needs a callback base (request `callback_base_url`, else `WEBHOOK_BASE_URL`) and resolves to `poll` when none is configured, echoed to the client instead of a mode that silently degrades. The dashboard's `auto` sends no mode. The inline path arms the regular poll schedule in both modes, so a lost callback cannot strand a job; the service mirror arms its fallback after `VIDEO_AGENTS_WEBHOOK_FALLBACK_SECONDS`. `diagnose_media_video_providers()` reports `default_completion_mode` and `poll_scheduler`. |
| Durable polls + restart re-arm (B8) | `web_portal/server.py` — `poll_media_video_job_once`, `schedule_media_job_poll`, `_media_video_poll_job_handler` (`video_generation_poll` rows, bound in `get_agent_job_queue`), `rearm_media_video_jobs()` at `run_server`; `VIDEO_AGENTS_POLL_TIMEOUT`; `services/video_agents_service.py` `_arm_completion_tracking`, `rearm_in_flight_jobs` | With `PHINS_AGENT_ASYNC` a job's polls are one self-rescheduling queue row keyed per video job (no second row while one is parked; any worker with the handler may pick it up); otherwise a daemon timer thread. At boot every job left `queued` (no provider id) or `processing` is re-armed; terminal jobs are not. A job that never completes within the timeout is failed with a reason rather than polled forever. The handler lives in the web process (needs `MEDIA_PROCESSING_JOBS`), like the BI handler below. |
| Request dedupe (B8) | `web_portal/server.py` — `build_media_video_prompt`, `media_video_request_fingerprint`, `find_duplicate_media_video_job`; batch and single submit routes; `force_regenerate`; `services/video_agents_service.py` `request_fingerprint`, `_JobStore.find_duplicate`, `submit_video_job(force=)`; `video-agents.html` "Force regenerate" | Fingerprint over (campaign, agent, pipeline, prompt, provider, model, aspect, duration, reference image); identical requests reuse the existing non-terminal or completed job (`deduplicated: true`, `queued_count` vs `reused_count` in the batch response) unless forced. Failed/cancelled jobs are never reused. |
| Replay-safe webhooks (B8) | `web_portal/server.py` — `check_media_webhook_replay`, `media_webhook_delivery_fingerprint`, `MEDIA_WEBHOOK_REPLAY_WINDOW_SECONDS` (default 300), per-job `webhook_deliveries` | After the existing HMAC check: a timestamp (header or payload) outside the window → 403; a delivery whose nonce (or body hash when no nonce) was already accepted for that job → 409; a delivery for an already-terminal job → 200 without re-processing. |
| Single terminal transition (B8) | `web_portal/server.py` — `media_job_lock` (per-job `RLock`), `finalize_media_video_job`, cancel route; `services/video_agents_service.py` `handle_webhook` | Poll, webhook and cancel serialise per job and every terminal path re-reads status under the lock, so poll-then-webhook, webhook-then-poll and concurrent finalize yield exactly one terminal state and one asset download; cancelling a terminal job → 409. The service mirror had let a late webhook regress a terminal job — fixed. |
| Write-path invalidation (B10) | `services/bi_analytics_service.py` — `data_version`, `notify_data_change(store)`, `on_data_change(cb)`, `notify_bi_data_change()`, `_on_store_write` (DatabaseDict listener, `BI_INPUT_REPOSITORIES`); `database/data_access.py` — `DatabaseDict.content_version()`, `add_write_listener`; `web_portal/server.py` `mark_ledger_dirty()` | Every DB write to customers/policies/claims/billing/underwriting and every in-memory ledger mutation (all explicit `save_ledger_data` calls go through `mark_ledger_dirty`) bumps the BI `data_version`. The **fingerprint check stays on every read**: `data_version` is additive (diagnostics + re-materialization trigger), so an un-hooked write can at most cost a recompute, never a cached dashboard that contradicts the stores. `content_version()` bumps on each local write and on each TTL refresh that loaded different rows, and refreshes first when the bulk cache is stale — an unchanged version therefore proves the rows are unchanged, and the per-store digest is memoised on it (fingerprint O(1) in DB mode when nothing moved). Plain dicts are always re-hashed. |
| Materialized views (B10) | `services/bi_analytics_service.py` — `materialize_views(data_sources)`, `_materialized_entry`, `VIEW_SCHEMA_VERSION`, `PHINS_BI_SNAPSHOT_DIR/materialized_views.json`; `web_portal/api_bi_analytics.py` `with_freshness`, `handle_bi_materialize`; `POST /api/bi/materialize`; `scripts/run_bi_snapshot.py` (`entrypoint.sh bi-snapshot`, `--snapshot-only` / `--materialize-only`); `bi_materialize` queue rows (`schedule_bi_materialize`, `PHINS_BI_REMATERIALIZE_DELAY_SECONDS`, default 5 s) | `executive_dashboard`, `revenue_forecast` (default parameters) and `customer_analytics` are upserted — one checksummed record per view with input fingerprint, `computed_at`, `data_version`, schema version — by atomic file replace; idempotent (re-run with unchanged inputs reports `changed: false`). A read adopts a view only when its fingerprint equals the live inputs, its checksum verifies and it is younger than `cache_ttl_seconds`; the file's mtime is re-checked on every miss so a cron rewrite reaches a running process. Every `/api/bi/*` cached-view response carries `computed_at`, `served_from` (`cache` \| `materialized` \| `live`), `age_seconds`, `data_version`, `cache_ttl_seconds`. With the agent queue running, a store write enqueues one debounced `bi_materialize` row (a burst collapses into one pending job; the handler clears the flag before computing so a write during the computation schedules a fresh one). `bi_data_sources()` is the single definition of the live stores for GET routes, the materialize route, the queue job and the cron script, so all four fingerprint identically. |
| Forecast as a materialized view (B10) | `services/bi_analytics_service.py` `predict_revenue_forecast` (cached wrapper) / `_compute_revenue_forecast` | The route's default request is the `revenue_forecast` view; other parameter sets cache under `revenue_forecast:custom`. The fingerprint includes the live year-1 lapse rate, so an actuarial table promotion invalidates the forecast; `now=` bypasses the cache. |
| Tests | `tests/test_video_agents_lifecycle.py` (27), `tests/test_bi_materialized_views.py` (30), updates to `test_agent_job_queue.py`, `test_jobs_adapters.py`, `test_agent_async_routes.py`, `test_video_agents_service.py` | B8: completion-mode resolution and batch defaults, diagnostics; dedupe (batch, single, force, fingerprint coverage); replay refusal (409), stale/future timestamp (403), idempotent terminal delivery; poll-then-webhook, webhook-then-poll and concurrent finalize → one transition and one download; restart re-arm (queued/processing only), poll timeout, one self-rescheduling queue row, handler bound; service mirror parity. B10: notify/callback semantics (failing hook never breaks a write), in-place edit still caught, `content_version` on local/peer writes and unchanged refresh, listener filtering, digest memo, freshness on every view route, forecast keys/lapse/`now`, idempotent upsert, cross-process adoption with `computed_at`, stale/mismatched/tampered/schema-changed views refused, mtime pickup, persistence failure reported, health probe, materialize route, cron script (both flags), debounced queue job, HTTP wiring (403 → 200 → `served_from: cache`). |

Deviations from the §B8/§B10 text above, and why:

- **No new `video_jobs` table.** `MEDIA_PROCESSING_JOBS` is already a durable
  A4 store (`services/jobs/video_job.py`, `VideoJob` model) and is what the
  production HTTP path (`server.py`) reads; polls became queue rows and the
  store is re-armed at boot, which is what the table was meant to buy.
- **Dedupe key** is the full request fingerprint (campaign, agent, pipeline,
  prompt, provider, model, aspect ratio, duration, reference image) rather
  than `(pipeline_type, prompt, provider, model)`: two agents in one campaign
  legitimately share a prompt template.
- **`invalidate_cache()` is not called from write paths.** Dropping the cache
  on every write would force a recompute even when the write touched no BI
  input; `notify_data_change` bumps a version and lets the fingerprint decide,
  which is both cheaper and equally safe (the fingerprint was, and is, the
  correctness guard).
- **`scheduler/runner.py` untouched.** It is the Railway cron shim for
  monthly auto-pay; materialization rides the existing `bi-snapshot`
  entrypoint (cron) plus the in-process debounced queue job.

### Shipped — §D step 6 (part 4): B7 Marketing / Sales, B11 Delivery Bidding, B6 Customer agents

| Piece | Where | Notes |
|---|---|---|
| Signed input hash + plan cache (B7) | `services/marketing_sales_agent_service.py` — `PLAN_VERSION`, `compute_input_hash`, `_plan_cache` (LRU, `PLAN_CACHE_MAX_ENTRIES`), `plan_cache_stats`, `clear_plan_cache`; `web_portal/server.py` `generate_marketing_campaign` (shared by the GET and publish routes) | The SHA-256 over every plan-determining input (scope, BI signals, cohorts, `PLAN_VERSION`) is the `campaign_id` seed, so identical inputs yield the same plan across restarts and the in-process cache is a pure speed-up, never a source of truth. The hash is inside the signed `integrity` payload, so a plan cannot be re-signed over different inputs. `_build_bi_signals` ignores zero-amount `ledger_type='event'` rows, so anchoring a publication on the ledger does not change the next plan's inputs (regression test). |
| BI cohort targeting (B7) | `derive_cohorts`, `_apply_cohort_targeting`, `COHORT_DEFINITIONS`; `server.py` `marketing_customer_analytics`, `cohorts=` query flag; `admin.html` "BI Cohort Targeting" | Cohorts are derived deterministically from `bi_analytics_service.get_customer_analytics` (no sampling), re-order the sales playbooks (`target_cohort` badge) and are part of the input hash. Opt-in per request. |
| Ledger-anchored publish (B7) | `MARKETING_PUBLISH_EVENT_TYPE` (`marketing_campaign_published`), `publication_entry_id`, `anchor_publication`, `verify_publication`; `POST /api/admin/marketing-sales-agent/publish`, `GET .../latest` | `anchor_publication` re-verifies the HMAC and input hash and appends one `PlatformEventLedgerService` event **before** any media asset is created; an integrity mismatch → 409, a ledger failure → 503 and nothing is published (fail closed). The entry id is deterministic per `(campaign_id, signature)`, so a retried publish is idempotent. `/latest` re-verifies a published plan against its anchor and reports `ledger_anchor`. |
| Geohash index (B11) | `services/delivery_bidding_service.py` — `geohash_encode/decode_bbox/neighbors`, `geohash_precision_for_radius`, `haversine_km`, `_geo_index`, `find_open_requests_near`, `rebuild_geo_index`, `geo_index_stats`; `GET /api/delivery/nearby` | Pure-Python multi-precision index over `BIDDING_OPEN` requests (indexed on create, removed on select/expiry); candidates from the cell + 8 neighbours, then exact haversine filter — no false negatives inside the radius. Suppliers with coordinates + `service_radius_km` (default `DEFAULT_SUPPLIER_SERVICE_RADIUS_KM`) are matched by distance, others fall back to text service areas; a bid from outside the radius is refused. |
| Reliability from settled orders (B11) | `reliability_for`, `_settled_outcomes_for`, `SETTLED_RELIABILITY_WEIGHT`, `MIN_SETTLED_ORDERS_FOR_BLEND`; `services/supplier_settlement_service.py` `get_settled_outcomes`; `default_settled_outcomes_accessor` | Self-reported on-time % is blended (0.6) with the success rate of **executed** settlement items once a supplier has ≥ 3 settled orders; each bid records `settled_orders`, `reliability_score`, `reliability_source`, so a ranking is explainable. Accessor errors fall back to self-reported (source recorded), never to a silent zero. |
| SLA clock + outbox (B11) | `DeliveryStatus.BIDDING_CLOSED`, `BIDDING_WINDOW_CLOSED_EVENT` (`delivery.bidding_window_closed`, canonical in `marketplace_event_service`), `expire_bidding_windows`, `next_window_deadline`; `services/jobs/delivery_sla_job.py` (`delivery_bidding_sla_tick`, `PHINS_DELIVERY_SLA_TICK_SECONDS`, `RescheduleJob`), `ensure_sla_clock` at `run_server`; `POST /api/delivery/expire-windows` | An elapsed window closes exactly once (`BIDDING_CLOSED` with bids, `CANCELLED` without) and emits one outbox event (marketplace outbox in DB mode, in-process list otherwise). Reads and late bids also close an overdue window lazily, so a stopped clock cannot admit a late bid. The clock is one idempotent self-rescheduling queue row. |
| Role-scoped `/api/delivery/*` (B11) | `web_portal/api_delivery_bidding.py` `handle_get`/`handle_post`; `server.py` `delivery_request_context`, `portal_delivery_bidding_service` | Customers see their own requests, suppliers their eligible/bid requests, admins everything; wired into `do_GET`/`do_POST` (it had been unrouted). |
| Shared interaction log (B6) | `services/customer_agent/interaction_log.py` — `Interaction`, `InteractionLog`, `get_interaction_log`, `mask_recipient` (`agent_artifacts` agent `customer_agent` / kind `interaction` via A4 `ArtifactStore`) | Both facades append to one log; a row is written `pending` **before** a send and finalised `sent` / `failed` / `refused` (an exception is recorded `failed` and re-raised), recipients are stored masked only, rows are never deleted by the agents. Inquiries land as `received` so they do not count against the cap before their acknowledgement is authorised. |
| Consent + daily cap (B6) | `services/customer_agent/consent.py` — `ConsentRegistry` (kind `consent`), `MessagingPolicy.authorize`, `TEMPLATE_PURPOSE`, `PHINS_CUSTOMER_DAILY_MESSAGE_CAP` (default 5, `0` disables), `PHINS_CUSTOMER_MESSAGING_CONSENT_ENFORCED` (default on); `server.py` `admin_set_customer_consent`, `POST /api/admin/customers/{id}/consent` | WhatsApp/SMS only (email keeps the notification service's preferences/suppression). Relational copy (`message`, `offer`) needs consent on file — explicit registry entry first, then flags on the customer record; transactional copy (`welcome`, `bill`, `reminder`, service acknowledgements) is blocked only by an explicit revocation. The cap is counted from the shared (durable) log including `pending` rows, so two concurrent sends cannot both pass. Refusals are logged with their code and surfaced as `status: refused` / `code` (not a provider failure). An OTP verified against the WhatsApp number is stored as `otp_verified` consent. |
| One escalation path (B6) | `services/customer_agent/escalation.py` — `EscalationDesk.escalate` (kind `escalation`), `AuditService` action `customer_agent.escalated`, timeline row | Durable record first (fail closed), then audit, then the `escalation` interaction; an audit outage leaves the record with `audit_id: null` rather than losing it. The report keeps the legacy `report_id/report_type/report_date/assigned_to/details` shape. |
| Service desk on platform rails (B6) | `services/customer_agent/service_desk.py` — `CustomerServiceAgent`, `SERVICE_TEMPLATES`, `ensure_service_templates`, `import_legacy_templates`, `Delivery`; `services/notification_service.py` `TemplateEngine.register_template/get_template/render_registered/registered_ids/unregister_template` | Sends through `NotificationService` (email / SMS / WhatsApp / in-app "portal"), copy from the process-wide `TemplateEngine` registry; customers resolve from a dict lookup (portal `CUSTOMERS`) or the legacy `CustomerValidationService`. Acknowledgement channel follows the inbound channel when a phone is on file, else email, else portal. |
| Shims + wiring (B6) | `services/customer_communication_agent.py`, root `service_agent.py` (legacy `notification_mgr` templates imported into the registry, deliveries mirrored into `delivery_queue`, escalations into `reporter.reports`); `server.py` outreach helper passes `customer_record`, registration passes `actor='registration'`; `api_extensions.py` welcome route passes `actor`; `GET /api/admin/customers/{id}/interactions` (`admin_customer_timeline`); `services/ai_capabilities.py` module list; root `conftest.py` resets the shared state per test | Agent ids `customer_communication` / `customer_service` unchanged; health probes expose PII-free counters (log sizes, consent enforced/cap, escalations). |
| Tests | `tests/test_marketing_sales_agent_ledger.py` (17), `tests/test_delivery_bidding_b11.py` (41), `tests/test_customer_agent_b6.py` (31); updates to `test_jobs_adapters.py`, `test_customer_relations_outreach.py` | B7: signature still verifies with the hash inside; identical inputs hit the cache and reuse the envelope; cohorts change the playbook deterministically; publish writes exactly one ledger entry, retried publish reuses it, tampered plan → 409, ledger failure → 503 with no side effects; anchoring does not change the next plan's inputs. B11: geohash primitives, index add/remove/rebuild, radius eligibility and out-of-radius bid refusal, settled blend (cache, fallback, error), window closure once with one event, lazy expiry and late-bid refusal, recurring queue row, outbox durability in DB mode, HTTP role scoping. B6: both facades in one log, pending-before-send, exception → `failed`, masked recipients, consent required/revoked/record-flag/registry precedence/enforcement switch, cap across channels with pending rows and per-UTC-day, OTP consent capture, one escalation path with audit, template registry, legacy shims, DB-mode durability across a simulated restart, HTTP consent → contact → timeline. |

Deviations from the §B6/§B7/§B11 text above, and why:

- **Consent lives in `agent_artifacts`, not new customer columns.** The
  registry is an A4 store keyed by customer (kind `consent`), so it is durable
  and shared in DB mode without a schema migration, and flags already on the
  customer record are still honoured as the fallback source.
- **Escalation writes an `AuditService` row, not a `pipeline_service`
  ticket.** The pipeline service has no ticket primitive; the durable
  escalation record plus audit row plus timeline entry is the same evidence
  trail without inventing one.
- **Transactional copy is not consent-gated.** Bills, reminders, welcome
  packages and service acknowledgements are account servicing; requiring
  marketing consent for them would silently stop bills. An explicit opt-out
  still blocks them.
- **B7 cohorts are opt-in per request** (`cohorts=1`) rather than always on,
  so an operator can reproduce a pre-B7 plan for comparison.
- **B11 outbox in memory mode is an in-process list**; only DB mode has a
  durable outbox, mirroring how `marketplace_event_service` already behaves.

### Shipped — §D step 6 (part 5): §C human AgentOS follow-ups

| Piece | Where | Notes |
|---|---|---|
| Per-renewal recurring commission | `services/agent_ecosystem_service.py` — `INITIAL_TERM`, `AgentCommission.period`, `_policy_term_start`, `_add_years`, `_term_index`, `renewal_period_for_bill`, `accrue_for_policy(policy, period)`, `accrue_for_paid_bill`, `recompute_commissions(policies, bills)`; `database/models.py` `AgentCommission.period/payout_id/paid_at` (+ `database/__init__.py` upgrade columns) | The initial term accrues once per policy (`source_event_id=policy:{id}`, `period=''`); each later policy year accrues once more (`source_event_id=policy:{id}:{YYYY-MM-DD}`, `source_type=policy_renewal`) when its first premium bill is **paid**. The term is derived from the policy anniversary (start date normalised to midnight, Feb 29 → Feb 28) and the bill's `billing_period_start`/`due_date`/`paid_date`; no start date or an unpaid bill → no accrual (may under-count, never double-counts). The in-memory key is `(source_event_id, affiliation_id, period)`; embedding the period in `source_event_id` lets the existing DB unique constraint enforce it without migrating a monetary table. `connection_integrity` audits every row (`amount = base_amount × rate`), treats renewals as add-ons over the initial term, and checks payout linkage/status consistency. |
| Billing hook | `web_portal/server.py` `accrue_agent_commission_for_paid_bills` (called from `process_customer_premium_payment`), `agent_ecosystem_data_sources` (bills, wallets, investment accounts, transaction ledger, platform ledger handed to the API module) | Best-effort and idempotent: a failure here is logged and can neither lose nor double an accrual, because the read-time and admin recompute sweep the same paid-bill book. |
| Payout runs | `AgentPayout` model (`agent_payouts`, id `APAY`), `AgentPayoutRepository` + `AgentCommissionRepository.list_by_status/list_for_payout`, `DatabaseManager.agent_payouts`; service `PAYOUT_STATUSES` (`calculated`, `settled`), `run_payouts`, `_verify_payout_set`, `settle_payout`, `list_payouts`, `get_payout`; `_persist_records` (run + its commission rows in one transaction), `_find_persisted_payout`, `_find_payouts_by_key`, `_build_commission_ledger` / `_hydrate_from_db` include payouts | `run_payouts` sweeps `accrued` → `payable` into one `calculated` run per agent (suspended agents skipped and reported), copies amounts (never edits them) and content-addresses the run by `commissions_hash`; a repeated caller `idempotency_key` returns every run that request created, untouched. `settle_payout` re-verifies the swept set (existence, ownership, linkage, `payable`, per-row arithmetic, `gross = Σ amount`, chain intact), writes the `agent.payout.settled` anchor on the **platform event ledger** with the deterministic id `AGPAY-{payout_id}` (a retry re-uses the anchor) **before** any status moves, then marks commissions `paid` / run `settled`. Anchor write raises → nothing changes; settling a settled run → `already_settled`. Records the external reference; never calls a payment rail (same stance as `supplier_settlement_service`). Durability: the run and its commission rows land in one transaction or not at all (in-memory move rolled back, accruals re-sweepable); `agent_payouts` has unique keys on `commissions_hash` and `run_key` (`{idempotency_key}:{agent_id}`) and the sweep reconciles against the durable table first, so peer instances cannot double-pay; a caller key is stored on every run of the batch so a retry gets the whole batch back; settlement is refused without a platform-ledger anchor; the `agent.payout.calculated` event is mirrored to the platform ledger only after the durable write. |
| Broker funnel | `agent_funnel`, `_subtree_customer_ids`, `_subtree_bi`, `_pct`; `GET /api/agent/funnel`, `GET /api/admin/agents/funnel?agent_id=` | Stage counts + conversion % (`invitations_created → approved → redeemed → affiliated_customers → customers_with_policy → customers_paying → customers_renewed`), commission totals (lifetime / initial / renewal / accrued / payable / paid), payout counts, and a `bi_analytics_service` summary computed **only over the agent's affiliated customers** with the per-customer `top_customers` block dropped — aggregates only, no PII, no other subtree. |
| Routes + UI | `web_portal/api_agent_ecosystem.py` — agent `GET /api/agent/funnel`, `GET /api/agent/payouts`; admin `GET /api/admin/agents/payouts[?agent_id=&status=]`, `POST /api/admin/agents/payouts/run {agent_id?, idempotency_key?, settle?, external_payout_reference?}`, `POST /api/admin/agents/payouts/settle {payout_id, external_payout_reference?}`; `agent-portal.html` (funnel + payouts cards, renewal KPI), `admin-agents.html` (payout runs card: run / settle) | Role-scoped like the rest of AgentOS (agents 403 on admin routes, admin 403 on agent routes); admin routes recompute from the current book before sweeping so a run reflects the latest paid bills. |
| Tests | `tests/test_agent_ecosystem.py` (35; +15) | Renewal accrues once per term and never twice, follows the policy anniversary not the calendar year, never accrues without a start date or paid status, integrity treats renewals as add-ons, billing hook accrues on premium payment; payout run idempotent on key/content/status and settlement anchored on the platform ledger, fails closed on a tampered swept set and on an anchor-write failure, skips suspended agents and scopes by agent; funnel scoped to the agent's own subtree; HTTP role scope + validation for every new route, run+settle failure is a 409 and the retry with the same key finishes the batch; settlement refused without a platform ledger or an anchor; record timestamps never define a renewal term; DB mode: renewals and payouts survive a simulated restart, a failed run/settlement write never half-persists, concurrent instances cannot double-pay (durable reconcile + unique `run_key` / `commissions_hash`). |

Deviations from the §C text above, and why:

- **Admin routes are flat** (`/api/admin/agents/payouts/run|settle`,
  `/api/admin/agents/funnel?agent_id=`) rather than `/agents/{id}/payouts`, matching
  how the existing admin agent routes are dispatched in `api_agent_ecosystem.py`.
- **The lifecycle verb is `settle`, not `execute`.** `detect_sql_injection` in
  `web_portal/server.py` matches the substring `EXECUTE` in query-string values, so
  `?status=executed` was logged and rejected as an injection attempt (and can trip the
  client-IP block). Statuses are
  `calculated` / `settled`; the ledger events are `agent.payout.calculated` /
  `agent.payout.settled`.
- **Renewal period lives inside `source_event_id`** as well as in the new `period`
  column, so the DB unique constraint `(source_event_id, affiliation_id)` keeps
  enforcing once-per-term without a constraint migration on `agent_commissions`.
- **Accrual is bill-driven, not schedule-driven.** A renewal accrues when its first
  premium bill is *paid*, never on the anniversary alone — the commission basis is
  collected premium, and an unpaid renewal must not create a payable.
- **Marketplace GMV accrual is still not hooked** to order settlement; the `gmv`
  basis is accepted on invitations but only the premium basis is driven from the books.

Health of what has shipped (checked on `main` after PR #589):
`GET /api/admin/ai-agents/health` reports 15 agents, all `ok`, no SLO
breaches, no load failures; gateway idle with no open breakers.

---

_Last updated: September 15, 2026 — A1 + A5 + B12 + A2 (+ tenant-scoped budgets) + A3 + A4 + A6 + B2 + B3 + B1 + B4 + B5 + B9 + B8 + B10 + B7 + B11 + B6 + §C shipped; every workstream in §A–§C is implemented. Remaining follow-ups are tracked in `docs/agent_ecosystem_design.md` §9 (marketplace GMV accrual hook, sub-agent payouts)._
