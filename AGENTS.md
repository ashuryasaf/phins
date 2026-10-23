# AGENTS.md - PHINS Agent Playbook

Use this file as concise, repo-specific guidance for PHINS contributions.
Keep changes narrow, follow existing patterns, and let direct user instructions
override this document.

## 1) Quick Mental Model

PHINS is a Python platform built around:

- a large `BaseHTTPRequestHandler` app in `web_portal/server.py` (~60k lines)
- optional extension routing in `web_portal/api_extensions.py` (~3980 lines)
  and domain-specific API modules (`api_bi_analytics.py`,
  `api_delivery_bidding.py`, `api_agent_ecosystem.py`,
  `api_assessment_center.py`, `api_chat_application.py` (chat-style policy
  intake / "Phin"), `api_claims_chat.py` (public claims chat), and
  `api_customer_identity.py` (ID + nationality master))
- service-layer logic in `services/` (139 top-level modules plus the `automation/`, `customer_agent/`, `jobs/`, `underwriting_bot/`, `pension/` and `risk_reports/` packages)
- database access in `database/`
- security utilities in `security/`
- scheduled tasks in `scheduler/`
- operational scripts in `scripts/`
- both `tests/test_*.py` (262 files) and root-level `test_*.py` (11 files)
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
- the pricing kernel (`services/pricing_kernel.py`) is the single writer for
 premium decomposition: `price_policy()` returns a `PremiumComponents` block
 (annual, monthly, mortality PV, disability PV, savings, expense, profit,
 deterministic integrity hash) that the portfolio simulator, inline quote /
 billing pricer, financial reporting service, risk reference, reserve
 calculator, BI feed and the reconciler all call into. Product rules
 (`life_only`, `life+ADL`, `life_only_after_65` — disability cut-off, savings
 rate, life share) live in the kernel registry; age curves
 (`phins_internal_v2` tables-driven, `risk_reference_v1` the locked published
 block) and the claim model (`MUTUALLY_EXCLUSIVE` default, `INDEPENDENT`) are
 parameters. Sandbox, simulator, IFRS 17 waterfall and the actuary dashboard
 all reprice through it — never through a parallel path
- chat intake (Phin) is a parallel surface to the classic forms.
  Any committed answer on `/apply-chat.html` and `/file-a-claim.html` can be
  edited until filing. Edits are an append-only checksum chain
  (`services/chat_answer_revisions.py`); card numbers and full national IDs
  are not stored. `POST .../edit` needs the resume code (a staff session
  cannot rewrite the answer). `GET .../process-review` is the staff-only
  quick and full review (admin, underwriter, claims) of identity, health,
  billing last4, edit times, and prior files matched by email, name, or
  identity hash. Filing seals that chain on the ledger
  (`chat.process_sealed` / `claims_chat.process_sealed`; the seal sits on
  the ledger row) and refuses a broken chain. After the session is gone the
  same review is rebuilt from that seal. The page is
  `/chat-process-review.html`.
  `services/chat_application_service.py` (+ `chat_application_i18n.py`) runs
 the conversational state machine, `web_portal/api_chat_application.py`
 handles OTP + invitation attribution + ledger writes and finalises through
 a loopback `POST /api/policies/create`, and `services/claims_chat_service.py`
 + `web_portal/api_claims_chat.py` do the same for claim filing via a
 loopback into `POST /api/claims/create`. Both routes share the OTP service,
 enforce staff / owning-customer / resume-code authorization, and leave the
 policy, underwriting, billing, wallet and pipeline code paths unchanged. A
 public `/file-a-claim` page never asks the visitor to sign in. ADL-decline
 or ineligible-quote chats still open a durable
 `UNDERWRITING_APPLICATIONS` row (`source=chat_adl_referral`) so no lead is
 lost
- customer identity master (`services/customer_identity_service.py`,
 `web_portal/api_customer_identity.py`): the one writer for a customer's
 national ID + nationality. Public endpoints only expose
 `/api/identity/countries` and `/api/identity/rules`; customer and admin
 writes go through `set_identity` / `reconcile_pipeline_identity`, and
 `/api/admin/customers/identity/report` reports rollout counters. Responses
 never carry a plaintext ID (see the §10 identity contract)
- referral acquisition rewards (`services/referral_reward_service.py`,
 `web_portal/api_referral_rewards.py`, `database/repositories/referral_reward_repository.py`):
 a customer-acquisition fee shared across up to 3 invitation layers
 when a referred customer pays a premium. The default total is $650. Layer 1
 receives that whole fee when nobody stands above them. Layer 2 takes $100
 from the fee when that layer exists, and layer 3 takes $50; the rest stays
 with the direct affiliate. An admin or an actuary sets the total, those
 layer amounts, and whether the fee is fixed or a percent of the annual
 premium sold (`POST /api/admin/referral-rewards/plan`). One affiliated
 customer is one settlement (`CACSET-{referee}`): a single
 `customer_acquisition` expense for the allocated layers, booked at
 allocation and blocked from the referrer for `hold_months` (default 3,
 range 0–60). An admin or an actuary sets the hold
 (`POST /api/admin/referral-rewards/hold`). The reward is released only if
 that customer is still paying when the hold ends. If the paid balance
 lapses before acceptance, the expense is reversed and the settlement is
 not recreated. Acceptance then posts premium credit, the health wallet,
 savings, or cash when that layer allows cash, and does not book the
 expense again. Each affiliate's book shows layer counts, blocked versus
 ready, and the destination, with links to billing, the health wallet, and
 investments. Customer `REF-` codes use this
 rail; agent `AGI-` codes stay on the commission rail and are not paid
 twice. A customer can request an agent or supplier role
 (`PRO-{customer}-{role}`); approval opens that profile and a role-switch
 token without rewriting `USERS.role`. An approved agent invitation cap is
 100 (customer cap stays 10). `affiliated_cac_plan()` is the planning view
 (allocated, blocked, releasable, settled, reversed, projected release,
 layer schedule, and one row per reward).
 State is a checksummed JSON book (`PHINS_REFERRAL_REWARDS_PATH`) or the
 referral tables (including `referral_settlements`) when the database is
 on. A checksum mismatch is not paid. Customer and admin invitation links
 open `/join.html?code=` (an older `/register.html?code=` link still
 accepts the code). A customer, including one who has opened the agent or
 supplier desk, sends that same page (`affiliated_join_link`). The code is
 the only query value, so the sender stays layer 1 and the layers already
 above them stay on `chain_of`. When `BASE_URL` is set the link is that
 origin; otherwise the desk completes a relative path with the host the
 sender is using, so a customer on the public site copies
 `https://www.phins.ai/join.html?code=` the same way an admin does. The
 invitee chooses customer, agent, or supplier on the page. The page carries that code into `apply-chat.html`,
 into `claims-chat.html?start=1` (and `register.html?next=claims`), and
 into `register.html?next=` for the health wallet, investments, credit,
 and the agent or supplier request. `next` is an allowlisted token. A
 claim filing does not book a second acquisition expense. Media assigns
 one video per path (the claims film key is `claims_chat`, separate from the solutions claims walkthrough), one image thumbnail (`join_intro_{key}_poster_id`),
 and one page background (`join_background_id`) on the Customer relations
 tab; an empty slot stays blank. The generator reuses the solution
 blueprint seal with campaign ids `JOIN-{key}`. Engine order is a full
 permutation of `JOIN_INTRO_ENGINES` (`replicate-veo`, `replicate-seedance`,
 `kling`, `gemini-veo`) stored with `join_intro_engine_priority_checksum`.
 A missing record uses the catalog order and is not written. A bad
 checksum blocks that send. The send does not write the public slot or
 the stored priority
- durable document archive (`services/customer_document_vault_service.py`):
 every application-chat, claim-chat and uploaded policy file is sealed by
 SHA-256 and filed into a per-entity lane. `services/document_durability_agent.py`
 is the admin-only durability test — it fingerprints the archive, writes
 one fixed probe through the normal upload path into the reserved
 `durability_probe` lane (excluded from the customer vault), reads it back,
 deletes it, and re-fingerprints to prove nothing else moved. Any failure
 is reported; the agent never repairs a customer file
- document chrome (`services/phins_document.py`, `web_portal/static/phins-document.css`,
 `phins-document.js`, `phins-doc-return.js`): every present and future report
 uses `render_phins_document` (server) or `PhinsDocument.printReport` /
 `PhinsDocument.render` (browser), or includes `<script src="/phins-doc-return.js"></script>`.
 The letterhead is the navy/gold gradient, shield logo, Inter + Space Grotesk.
 The Go back / Close bar is chrome only (hidden in print and when framed);
 role homes live in `PIPELINE_DOCUMENT_HOMES` and must stay aligned with
 `PHINS_DOCUMENT_HOMES`. Same-origin PDF/Markdown opens in a new tab go
 through `/document-viewer.html` (`phins-doc-open.js`). Do not change
 figures, checksums, or stored records when adding chrome

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
| Chat intake (Phin, policy or claim) | `services/chat_application_service.py` or `services/claims_chat_service.py`, then `web_portal/api_chat_application.py` / `api_claims_chat.py` |
| Customer identity (ID + nationality) | `services/customer_identity_service.py` (one writer), `web_portal/api_customer_identity.py` |
| Admin desk (mailboxes, diary, letters, tables) | `services/admin_desk_service.py`, `services/admin_desk_mail.py` (GoDaddy read-only attribution + one-time vault password), `web_portal/api_admin_desk.py`, `/admin-desk.html` |
| Referral CAC / professional roles | `services/referral_reward_service.py`, `web_portal/api_referral_rewards.py`, `database/repositories/referral_reward_repository.py` |
| Customer intro / invitation landing | `web_portal/static/join.html`; films `join_intro_*` on the media Customer relations tab; briefs in `services/solution_video_blueprints.py` (`JOIN_INTRO_OUTLINES`, `JOIN-` campaigns) |
| Document archive / durability probe | `services/customer_document_vault_service.py`, `services/document_durability_agent.py` |
| Unified business plan / investor deck (`/business-plan.html`) | `services/business_plan_model.py` (factor register, `compute_plan`, `ROUND_SEED_ILS` / `ROUND_PRE_MONEY_ILS` — the one writer for seed / pre-money; `appraisal.sensitivity` grid), `services/business_plan_document.py` (narrative, placeholders, founder block, HTML/Markdown renderers), `services/business_plan_charts.py` (chart + Gantt specs read from the plan dict; one layout engine → inline SVG for HTML and `?charts=1`, reportlab Drawing for the PDF; Markdown carries `<!-- phins-chart {json} -->` directives plus a data table), `services/business_plan_sources.py` (figure lineage + research registry kept byte-equal with the pitch-dashboard `sourceRegistry`), `services/business_plan_portrait.py` (Pillow-processed founder portrait), `web_portal/server.py` (`GET /api/business-plan/model[?charts=1]`, `GET /api/business-plan/founder-portrait`); then `python3 scripts/build_business_plan.py` and `python3 scripts/generate_investor_pdfs.py --only unified-business-plan`; tests in `tests/test_business_plan.py` |
| Premium / reserve / simulator pricing | `services/pricing_kernel.py` (sole writer), then `services/actuarial_service.py` and callers; refresh `tests/test_pricing_kernel.py`, `tests/test_actuarial_reserves.py`, `tests/test_ifrs17_waterfall_identities.py` deliberately |
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
| Storyboard / longer media | `services/storyboard_editor.py`, `web_portal/static/storyboard-editor.html`, `web_portal/api_extensions.py` (`/api/admin/media/storyboards`); tests in `tests/test_storyboard_editor.py` |
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
|  |- api_chat_application.py          # Phin chat-style policy intake (loopback into /api/policies/create)
|  |- api_claims_chat.py               # public claims chat (loopback into /api/claims/create)
|  |- api_customer_identity.py         # ID + nationality master surface
|  |- api_referral_rewards.py          # referral CAC, accept, professional role, role switch
|  |- connectors.py
|  `- static/                           # HTML/JS/CSS dashboards and assets
|                                        # (includes `static/locales/he.json` Hebrew i18n)
|- ai_automation_controller.py          # orchestration only; rules in services/automation/
|- prompts/                             # versioned LLM prompt templates (sha256 provenance)
|  `- assessment/                       # narrative v1 (free text) + v2 (structured); onboarding/service/termination v1
|- schemas/                             # JSON schemas for structured LLM output
|- services/                            # 139 service modules
|  |- agent_eval.py                     # A6 replay / propose_thresholds / golden sets
|  |- automation/                       # B2 pure rules: quoting, underwriting_gate, fraud, claims_gate, billing_schedule
|  |- pricing_kernel.py                 # single writer for premium decomposition (PremiumComponents)
|  |- actuarial_service.py              # tables, reserves, portfolio simulator (reprices via pricing_kernel)
|  |- phinsafe_rider.py                 # child catastrophe-hedge rider product + projection
|  |- underwriting_bot/                 # B1 package: report (model+engine), features (analyzers), service
|  |- underwriting_bot_service.py       # facade re-exporting the package
|  |- evidence_facts.py                 # B1 shared evidence pipeline (facts_for, bundles, FeatureCache)
|  |- model_shadow.py                   # B1 shadow scoring + drift monitor (never decides)
|  |- pension/                          # B5 package: schema (mapping + CompiledFields), parsers (tree + iterparse), cache, profile, report, agent
|  |- pension_data_agent.py             # facade re-exporting the package
|  |- risk_reports/                     # B9 package: models, parsers, analysis, charts, render, service, pdf_export (Hebrew-ready)
|  |- ai_risk_reports_service.py        # facade (two-way forwarding of AI_REPORTS_DATA_FILE / singleton)
|  |- customer_agent/                   # B6 package: communication + service_desk facades, interaction_log, consent, escalation
|  |- customer_communication_agent.py   # shim -> customer_agent.communication
|  |- chat_application_service.py       # Phin chat state machine (+ chat_application_i18n.py)
|  |- claims_chat_service.py            # Phin claims chat (loopback into claims pipeline)
|  |- customer_identity_service.py      # sole writer for personal ID + nationality
|  |- customer_document_vault_service.py # SHA-256-sealed per-entity archive for chat/intake/claim files
|  |- document_durability_agent.py      # admin-only archive durability probe (reserved lane)
|  |- financial_reporting_service.py    # unified books / forecast feeds for accountant & regulator surfaces
|  |- regulator_outline.py              # read-only outline (admin+actuary readable, reconciles to financial books)
|  |- regulator_inquiries.py            # inquiry thread stored in agent_artifacts + Business Relations row
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
|  |- repositories/                     # 21 *_repository.py + base.py
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
|- tests/                               # 262 test files
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
- Referral acquisition book: `referral_rewards`

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
   `web_portal/api_assessment_center.py`,
   `web_portal/api_chat_application.py` (Phin policy intake),
   `web_portal/api_claims_chat.py` (public claims chat), or
   `web_portal/api_customer_identity.py` (ID + nationality), or
   `web_portal/api_referral_rewards.py` (referral CAC and professional roles).
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
- `DatabaseManager` exposes 44 repository properties (see §4 for the full list).
- Repository modules (21 `*_repository.py` + `base.py`):
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
  conditional UPDATE so exactly one racer wins),
  `referral_reward_repository.py` (program config, join edges, reward rows,
  professional-role requests).
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
 `PHINS_DEFAULT_MEDIA_ASSET_MAX_BYTES` (scanner/disk cap, default 2GB),
 `PHINS_MEDIA_STORAGE_DIR` (disk cache; default is
 `RAILWAY_VOLUME_MOUNT_PATH/phins_media_assets` or `/data/phins_media_assets`
 when that directory is writable, otherwise the temp dir),
 `PHINS_MEDIA_DB_MAX_BYTES` (database copy cap, default 256 MiB, `0` disables
 the byte copy). With the database on, video and image bytes (and other
 media-library files) are stored in `media_library_blobs` with SHA-256
 checked on read. A checksum clash is not overwritten. `DELETE /api/media/{id}`
 (admin or media) and supplier-offer media delete remove that blob and the
 cache file. `/media-files/{asset_id}/...` resolves the asset's real file,
 restoring it from the database when the cache is gone. Playback stays
 public; the authenticated download is `GET /api/media/{id}/download`.
 Design placements (hero, poster, background, thumbnail, login, solutions,
 solution theaters) are a checksummed singleton in `media_design_documents`.
 A restart loads that row after the media library; a checksum mismatch is
 not applied. The login page reads `login_hero_video_url`,
 `login_background_url`, and `login_thumbnail_url` from
 `GET /api/design/settings`. When a video and a still are both assigned,
 the visitor switches the full-bleed layer between the video and the
 background (thumbnail is the video poster, and the still if no background
 is assigned). The login film is inline on iPhone and Android
 (`playsinline`, `webkit-playsinline`, `x5-video-player-type=h5`) and is
 attached only after its frame is visible, so a phone does not drop it.
 Stored placements are not rewritten for playback. The `founder_portrait_id`
 image slot (admin-media "Business plan founder portrait") feeds
 `GET /api/business-plan/founder-portrait`: the original asset is never
 rewritten; the route serves a square, EXIF-corrected, 720 px progressive
 JPEG (ETag / 304, checksum verified first) and the public settings expose
 only `founder_portrait_url`. The PDF build embeds it when
 `PHINS_BUSINESS_PLAN_PORTRAIT` (local file) or
 `PHINS_PDF_PORTRAIT_BASE_URL` (origin that serves the route) is set,
 otherwise it prints "founder portrait omitted" and draws nothing.
- **Business-plan open links (NDA, protected view, saved factors):**
 `/business-plan.html`, `/business-plan.he.html` and `/api/business-plan/*`
 are one confidential share scope (`confidential_access.share_scope_root`);
 the `investor-docs/phins-unified-business-plan[.he].{pdf,md}` downloads
 stay staff-only and are never share-unlockable. A share on a plan path is
 always `nda_required` and needs a `label` (the Receiving Party). The NDA is
 **the platform NDA** (`/legal/nda.html`, investor context, one-way) rendered
 by `services/business_plan_nda.py` for that label and effective date plus a
 protected-view rider; `nda_sha256` is fixed at link creation. A signed
 unlock (`POST /api/confidential/share-unlock` with `signer_name`,
 `nda_accepted`, optional `signature_png`) is anchored through
 `_legal_doc_sign` (`docType=nda`, role `Receiving Party[ #n]`, instance
 `LGL-NDA-<share>`) — no ledger anchor, no opening (the use is rolled back,
 503). Receipts are visible in `GET /api/confidential/shares`
 (`nda_acceptances[].ledger`), `GET /api/legal-docs/registry?doc_id=LGL-NDA-…`
 and `/api/legal-docs/verify`. Each opening is a session (`access_window_seconds`,
 ≤ 3 h for single use, `idle_timeout_seconds`) bound into the share cookie
 (`sk`). The cookie unlocks only the link it was minted for: a different
 `?share=` is `share_password_required` even when an earlier opening's cookie
 is still valid, and an NDA share with no matching `nda_acceptances` row for
 that session key is closed in every use mode (single, multi, unlimited) —
 the refusal consumes no use. `GET /api/business-plan/access` drives
 `static/business-plan-access.js` (watermark, no print/download/copy/capture,
 whitelisted factors only, +/− folds). Admin tools on the plan page include
 a document-structure allow-list (`services/business_plan_parts.py`: banner,
 chapters, founder photo, investor deck, appendices, factor panel).
 `GET`/`POST /api/business-plan/factors` (admin) persists the saved factor
 set, `viewer_adjustable` and `visible_parts` via
 `services/business_plan_settings.py` (`agent_artifacts` in DB mode, else
 `PHINS_BUSINESS_PLAN_SETTINGS_PATH` / `database/business_plan_settings.json`);
 the saved set is always a scenario, never `canonical`. Creating a plan
 share freezes that composition (`visible_parts`, `viewer_adjustable`,
 `saved_factors`) onto the link. The HTML served to the share viewer is
 filtered before it leaves the server (`filter_share_html`): an unchosen
 chapter element and an unchosen factor control are not in the response, a
 later admin edit does not reopen them, and a share viewer whose frozen
 record cannot be read gets a short error page rather than the full plan.
 The founder portrait route 404s when `founder-photo` is not in that
 snapshot. Each anchored NDA is sealed into the signed-documents folder
 (`PHINS_SIGNED_DOCUMENTS_DIR` or `database/signed_documents/`, created on
 first signature, gitignored): `record_sha256` over the canonical JSON and
 `sha256(nda_text)` must equal `nda_sha256`. Staff read it from the IL pitch
 dashboard and `GET /api/confidential/signed-documents` (anonymous 401); a
 tampered file lists `intact: false` and `get()` refuses it. Any anchored
 signature (`_legal_doc_sign`, not a void) is sealed the same way
 (`store_signature`); the open-link NDA may later promote that attestation
 to the full text only when the digest matches. With `USE_DATABASE=true`
 the bytes also live in `signed_document_blobs` (SHA-256 checked on read;
 a different checksum is not written over the row). `document_use_ledger`
 appends `sent` / `signed` / `opened` / `used` (`PHINS_DOCUMENT_USE_LEDGER_PATH`
 or `database/document_use_ledger.json`, hash-chained, idempotent). Staff
 read both from the pitch dashboard **Signed documents** tab and
 `GET /api/confidential/document-ledger` (anonymous 401). A broken chain
 is reported and blocks the next append. Share viewers of a confidential
 page other than the business plan (which already has its own protected
 view) and the signed-copy HTML get `phins-capture-guard.js`.
- **Link previews:** `GET /link-preview/<file>.png` (and
  `GET /link-preview.png?path=`) is a public 1200×630 card (navy/gold
  gradient, shield logo, document name) from `services/link_preview.py`.
  Served HTML and the confidential gate carry the same Open Graph tags.
  Preview crawlers (WhatsApp, `facebookexternalhit`, and the other unfurl
  bots) receive HTTP 200 with that card and the file name only — never the
  document — and the fetch does not open a share or set a cookie. That
  response is `public, max-age=300, s-maxage=0` with no `noindex` and no
  `Vary: User-Agent` (those three are what make WhatsApp drop the card).
  A browser that is handed the shell continues to the unlock page. The
  title is a known name or the name of a file that exists; an unknown path
  stays `PHINS`. `robots.txt` allows `/link-preview.png` and
  `/link-preview/`.
- **Video agents (B8):** `REPLICATE_API_TOKEN` enables Replicate beside
 Gemini and Kling (Growth Agent and Video Agents). Optional
 `REPLICATE_VIDEO_MODELS` (comma-separated `owner/name`) and
 `REPLICATE_WEBHOOK_SIGNING_SECRET` (`whsec_…`; when unset the per-job
 callback token authenticates the webhook). Completed files are downloaded
 immediately and SHA-256 checksummed. `VIDEO_AGENTS_COMPLETION_MODE` (`webhook` default,
 `poll`; webhook resolves to poll without a `WEBHOOK_BASE_URL`),
 `VIDEO_AGENTS_POLL_TIMEOUT` (fail a job still in flight after this many
 seconds, default 1800), `MEDIA_WEBHOOK_REPLAY_WINDOW_SECONDS` (callback
 timestamp tolerance, default 300); polls ride the agent queue when
 `PHINS_AGENT_ASYNC` is on, and `rearm_media_video_jobs()` resumes
 in-flight jobs at boot. The storyboard editor
 (`services/storyboard_editor.py`, `/storyboard-editor.html`) is embedded on
 the media, growth, solutions, and video-agents surfaces. Each scene uses
 the selected engine's own duration (Veo 4/6/8, Kling 5/10, Kling v3 on
 EvoLink 3–15, Seedance up to 15). A photo-to-photo script starts on one
 sealed library photo and ends on the next; Kling and Seedance receive that
 next photo as the end frame. Solution outlines and Growth Agent storyboard
 lines are the narration. Scene 1 can still open on a chosen reference or a
 provider-generated picture; a chained scene opens on the previous ending
 screenshot. Rendering uses the growth-agent media job (Replicate by default;
 Kling, Gemini, or a later affiliated provider when that provider is selected
 and connected, and it is not swapped for another engine). A solution
 walkthrough send on the Growth Agent uses the selected video provider,
 provider model, library reference image, and completion mode. The prompt
 is that solution's sealed narration in full and does not name an
 eight-second length. The send asks the engine for its longest legal clip
 (Veo 8, official Kling 10, Kling v3/o1/o3 on EvoLink 15, Seedance 15).
 A different prompt is refused and the blueprint checksum is left as stored.
 Fresh defaults use every public bullet; a saved narration is not rewritten.
 Solution theaters play an assigned film to its own length.
 Sealed scene files join into one checksummed film that can be assigned to
 login, solutions, and disclaimer slots. A checksum mismatch is reported;
 library bytes are never rewritten to force a chain.
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
- **Admin desk:** an admin saves a mailbox password once on
  `/admin-desk.html`. The value is Fernet-encrypted in
  `PHINS_ADMIN_DESK_MAIL_VAULT_PATH` (else the Railway volume, `/data`, or the
  temp dir) and is not written on the mailbox record. A vault that cannot
  encrypt refuses the save. `PHINS_ADMIN_DESK_MAIL_ASAF` (and
  `PHINS_ADMIN_DESK_MAIL_ACTUARY`, `_UNDERWRITING`, `_CLAIMS`, `_ACCOUNTANT`,
  `_COMPLIANCE`) remain an optional env credential; the name is stored on the
  binding, the value is not. A mailbox stays disabled until one of those is
  set and an admin enables it. `GODADDY_API_TOKEN` (or `GODADDY_PAT`, or
  `GODADDY_API_KEY` + `GODADDY_API_SECRET`) is read-only: domain ownership,
  `GET /v1/email/mailboxes`, and eligibility. The desk does not create a
  mailbox. Microsoft 365 mail keeps the saved password in the vault and does
  not send it to IMAP. GoDaddy Email / Titan logs in once at
  `imap.secureserver.net:993`. Send stays refused until a provider adapter
  is connected. The desk page is `/admin-desk.html`.
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
- **Regulation viewer:** username `regulator`, role `regulator`. Demo
  password `regulator123` works until `PHINS_REGULATOR_PASSWORD` is set or
  the password is changed in the regulation view. `GET /api/regulator/outline`
  is the sealed book; admin and actuary may read it from their dashboard
  headers. The regulator role cannot call other APIs or write, except its
  own credential change and `GET`/`POST /api/regulator/inquiries` (one open
  inquiry per outlined subject). The thread is stored in `agent_artifacts`
  as `regulator_inquiry` / `inquiry`, and the same write files a Business
  Relations row (`audience` `regulations contact`, organization
  `capital markets authority`, interest `regulator:<subject>`). Full name
  and email are required; those two stamps cannot be overridden. Staff mail
  and the acknowledgement to the contact email use the Business Relations
  notification path. The public form cannot submit that audience. Outline
  totals reconcile to
  `compute_unified_financial_metrics` and are refused if an identifier
  survives redaction (`services/regulator_outline.py`,
  `services/regulator_inquiries.py`, `docs/regulator_view.md`).
- **Security:** `SESSION_SECRET_KEY`, `PHINS_ENCRYPTION_KEY`,
  `PHINS_ENFORCE_SECRET_POLICY`, `PHINS_EMERGENCY_UNLOCK_KEY`,
  `ALLOW_LEGACY_DEMO_PASSWORDS`
- **Cyber crisis drop / autopilot:** admin Login Activity on
  `/cyber-security.html`. `POST /api/security/crisis/drop-all/request` then
  `.../confirm` with the OTP service (`crisis_lockdown`, one use). The drop
  advances a checksummed session generation and closes every open session,
  including the admin who confirmed it. Customer, policy, claim, and billing
  records are only fingerprinted. A broken crisis journal refuses the drop
  until an admin reseals it. `PHINS_CRISIS_OTP_EMAIL` is the code address
  when the admin username is not an email. `PHINS_CYBER_CRISIS_DIR` holds
  the generation file, journal, and autopilot chain. Autopilot
  (`GET`/`POST /api/security/autopilot`, mode `assess` or `off`,
  `PHINS_CYBER_AUTOPILOT_CADENCE_SECONDS`, `PHINS_CYBER_AUTOPILOT_THREAD`)
  is a read-only 24/7 pipeline assessment and does not close sessions.
  With the database on, the generation is also an `agent_artifacts` row
  (`cyber-crisis-session-generation`) so other instances see the drop.
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
  (`./scripts/entrypoint.sh cron`, daily `15 6 * * *` catch-up; due day is
  the 1st and a missed 1st still collects without a second cash posting).
  Statement bills are the quoted installment (monthly, quarterly at 3% off,
  or annual on the policy anniversary); auto-pay and outstanding-bill
  repair settle each cycle exactly once, and `payment_setup.auto_pay=false`
  (or `billing.auto_pay=false`) is honored before any charge or notification
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
python3 scripts/build_business_plan.py --check   # unified business plan HTML/Markdown up to date?
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
- `web_portal/static/business-plan.html` and
  `investor-docs/phins-unified-business-plan.{md,pdf}` are generated, never
  hand-edited: `tests/test_business_plan.py` compares the committed files to
  a fresh `render_html` / `render_markdown`. Because the technology section
  is a live repository census, adding a `services/*.py` module or a
  `tests/test_*.py` file (as well as any factor or narrative change) requires
  `python3 scripts/build_business_plan.py` followed by
  `python3 scripts/generate_investor_pdfs.py --only unified-business-plan`
  in the same PR. Charts never carry their own numbers: every series in
  `business_plan_charts.chart_specs` is read from the plan dict, so a factor
  change re-renders them (the page fetches `?charts=1` and swaps the SVG).
  `RESEARCH_SOURCES` must stay identical to the pitch-dashboard
  `sourceRegistry`; the test parses both
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
 can contain a full database dump. The run also writes
 `repositories/phins.bundle` (every ref; round-tripped against refs, `HEAD`,
 and the reachable object set) and checksum-matched copies of ledger, keyring,
 and media files under `db/runtime/` when those paths exist. A configured dump
 that fails, or a SQLite snapshot that fails `PRAGMA integrity_check`, deletes
 the snapshot. Each successful run writes `restore_record.json` and
 `backups/RESTORE_INDEX.json`. A metadata-only catalog (git SHA + checksums)
 may be written to `PHINS_BACKUP_RECORD_CATALOG` (typically
 `docs/platform_restore_catalog.json`) and listed with
 `scripts/restore_from_backup.sh --list`.
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
- Dashboard hierarchy (`security/access_hierarchy.py`): a customer session
  cannot call `/api/admin/` or open a staff dashboard, and a staff session
  cannot open the customer dashboard (`/dashboard.html`,
  `/savings-portfolio.html`, `/algo-trading.html`) or move that customer's
  private money (health wallet, savings trades, pipeline deposit/settings).
  Assessments, reports, billing, documents, and claims review stay shared;
  row scope is still the caller's own customer id unless the role is
  operational staff. `/api/access/surface` is what the injected
  `ui-clarity.js` consults before it renders a dashboard.
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

Last updated: October 19, 2026
