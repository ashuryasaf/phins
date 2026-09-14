# PHINS Agent Operations — Optimization Design

> **Status: IMPLEMENTING — §D step 1 (A1 + A5) shipped.** This document turns
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
| Gateway | `services/external_call_gateway.py` (new) — `ExternalCallGateway.call(provider_kind, request_fn, *, endpoint, operation, agent_id, budget_scope, cache_key, cache_ttl, max_retries, usage_from, meter, context)` | Order of policy: cache → budget → breaker → retry → meter. Cache values are deep-copied in **and** out (a caller can never mutate what another caller receives); failures are never cached. Budget is per `(scope, agent_id, UTC day)`; scope defaults to `context.customer_id`, else `global`. `BudgetExceeded` is raised **before** the provider is contacted and a `blocked=True` usage row (zero cost, no tokens) is recorded so refusals show in cost reporting. Transient = connection/timeout or HTTP 408/425/429/5xx; only those retry (full jitter, `Retry-After` honoured) and count toward the breaker. `snapshot()` / `reset()` for the admin health view and tests; `conftest.py` resets it before every test. |
| Metering schema | `services/ai_usage_service.py`, `database/models.py` (`AIUsageRecord.agent_id`, `.blocked`), `database/repositories/ai_usage_repository.py`, `database/__init__.py` (`_UPGRADE_NEW_COLUMNS`) | `record_usage(agent_id=, blocked=)`, `summarize(group_by="agent")`, `blocked` count per bucket and in totals, in memory **and** in SQL (`SUM(CASE WHEN blocked ...)`). Existing databases get both columns via `upgrade_schema`; `blocked` defaults to false for pre-existing rows. `usage_hook` no longer mutates the caller's context dict. |
| LLM | `services/llm_providers.py` (`OpenAICompatibleProvider._chat`), `services/assessment_ai_service.py` | HTTP + parse + `usage_hook` run **inside** `request_fn`, so the hook fires exactly once per real provider call — never on a cache hit, never on a failed attempt. Cache key = sha256 of endpoint + full chat payload (model, messages, temperature 0). Per-call usage is captured in a local box (provider instances are shared). `agent_id` (default `assessment_ai`) and `call_context` (assessment service sets `customer_id`) drive budget scope and usage attribution. Budget refusal surfaces as a provider failure → the existing deterministic fallback. |
| Transcription | `services/transcription_providers.py` | Cache key = sha256 of the audio bytes + model + language hint, so an identical upload is not transcribed or billed twice within the TTL. Parsing and `_meter` also moved inside `request_fn` (one usage row per real call). |
| Media generation | `services/media_generation_service.py` (`_read_json_with_diagnostics`) | Breaker per provider host. `submit` is **never retried** (a 5xx after the provider may already have accepted a paid job would double-bill) and is metered as `video_submit`; `poll`/`download` retry and are not billable. No cache on any media call (poll results change). Gateway refusals raise `MediaGenerationError` like any provider failure. |
| Admin view | `web_portal/api_extensions.py` → `GET /api/admin/ai-agents/health` | Additive `gateway` block: stats, breaker states, today's budget usage. |
| Tests | `tests/test_external_call_gateway.py` (18), `tests/test_gateway_provider_integration.py` (8), `tests/test_ai_usage_service.py` (+3: `group_by="agent"`, SQLite persistence round-trip for `agent_id`/`blocked`, legacy-table `upgrade_schema`) | Existing `test_llm_providers.py`, `test_transcription_providers.py`, `test_video_agents_service.py`, `test_video_agents_integrity.py`, `test_notification_service.py`, `test_media_processing.py`, `test_assessment_*` pass unchanged. |

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

### Next — §D step 3

A3 generalized job queue (see §A3), then A4 durable agent state.

---

_Last updated: September 14, 2026 — A1 + A5 + B12 + A2 shipped; A3 next._
