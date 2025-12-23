# PHINS Architecture Optimization Roadmap (AI-First Insurer)

## Current State (as implemented)

- **API/Web runtime**: `web_portal/server.py` uses stdlib `ThreadingHTTPServer` + `BaseHTTPRequestHandler` (demo-grade).
- **Domain logic**: `phins_system.py`, plus division services in `services/`.
- **AI automation**: `ai_automation_controller.py` is **rule-based** with in-process singleton metrics.
- **Persistence**: SQLAlchemy repositories under `database/` with a DB-backed dict interface (`database/data_access.py`) used by the server when `USE_DATABASE=1`.
- **Operational state**: sessions/rate-limits/security counters are **in-process** dicts in `web_portal/server.py`.

## North Star Architecture (optimized for an AI insurance company)

### Separation of concerns (minimal set)
- **API Gateway / Web API**: stateless request/response, authN/authZ, validation, orchestration.
- **Workflow engine**: long-running insurance workflows (underwriting, claims, billing, docs).
- **Decisioning service**: underwriting/fraud/pricing decisions with versioning + explainability + audit.
- **Data platform**: system-of-record (OLTP) + analytics/training (OLAP) + feature store.
- **Observability + governance**: metrics/tracing/logs, model drift/fairness, regulatory reporting.

## Phase 1 (0–2 weeks): Make current runtime scalable + correct

### Goals
- Support real concurrency safely (within the current codebase).
- Remove “per-process correctness” problems (sessions, limits) as much as possible without a big rewrite.
- Establish instrumentation + audit completeness for AI decisions.

### Deliverables (mapped to repo)
- **Thread-safe in-process state**
  - File: `web_portal/server.py`
  - Done: introduced a global lock for shared state and moved to `ThreadingHTTPServer`.
  - Next: apply the same lock pattern to high-write endpoints that mutate `POLICIES/CLAIMS/BILLING/UNDERWRITING_APPLICATIONS`.

- **Consistent session expiry**
  - File: `web_portal/server.py`
  - Done: login session expiration now uses `SESSION_TIMEOUT`.

- **Centralize rate limiting + caching**
  - Files: `web_portal/server.py`, `scalability.py`
  - Action: choose **one** implementation; delete/redirect the other to prevent drift.

- **Decision audit payload standard**
  - Files: `ai_automation_controller.py`, `services/audit_service.py`, `web_portal/server.py`
  - Action: when calling AI automation, always log:
    - `decision`, `score`, `thresholds`, `reason_codes`, `model_version`, `feature_snapshot`, `request_id`.

### Acceptance checks
- API concurrency test: 100 parallel requests should not corrupt sessions/rate-limits.
- All “write” endpoints remain correct under concurrent calls (no lost updates).

## Phase 2 (2–6 weeks): Stateless API + shared operational state

### Goals
- Run multiple API instances behind a load balancer without session/rate-limit inconsistencies.
- Keep OLTP in Postgres, move operational state to Redis (or Postgres if simpler).

### Deliverables
- **Sessions in shared store**
  - Files: `database/models.py` (sessions table exists), `database/repositories/session_repository.py`, `web_portal/server.py`
  - Action: session create/validate/delete backed by DB (or Redis).

- **Rate limiting in shared store**
  - Files: new `services/rate_limit_service.py` (or reuse `scalability.RateLimiter` with Redis backend)
  - Action: per-IP and per-user quotas stored centrally.

- **Move static UI behind CDN**
  - Folder: `web_portal/static/`
  - Action: serve via object storage/CDN; API becomes JSON-only.

## Phase 3 (6–12 weeks): Workflow orchestration + event-driven core

### Goals
- Make underwriting/claims/billing robust to retries, partial failures, and long-running steps.
- Reduce synchronous request latency; improve reliability.

### Deliverables
- **Workflow engine integration**
  - New: `workflows/` (Temporal/Celery/RQ tasks)
  - Action: move document verification, fraud checks, billing reconciliation, and claim payment to background jobs with:
    - idempotency keys, retries, dead-letter handling, and state transitions persisted in DB.

- **Event log**
  - New: `events/` or `database/models.py` additions
  - Action: append-only business events for analytics, audit, replay.

## Phase 4 (3–6 months): Production ML platform (AI-first insurer)

### Goals
- Replace rules with trained models safely (governed, observable, explainable).
- Control risk: calibration, drift detection, fairness audits, and human-in-the-loop overrides.

### Deliverables
- **Model interface + versioning**
  - File: `ai_automation_controller.py` (refactor)
  - Action: introduce an interface like:
    - `predict(features) -> {score, decision, explanations, model_version}`

- **Feature pipeline**
  - New: `ml/features/`, `ml/training/`, `ml/evaluation/`
  - Action: offline/online feature parity, training data lineage, label capture from human decisions.

- **Model monitoring**
  - New: `ml/monitoring/`
  - Action: drift + performance + bias metrics; alerting.

## Phase 5 (ongoing): Compliance, security, and cost optimization

### Insurance-specific requirements to implement explicitly
- **Adverse action notices**: required reason codes + explanation templates.
- **Fairness audits**: scheduled bias testing, approval rate monitoring by protected classes (where legally permitted).
- **Data retention**: enforce retention windows in DB, export audit reports.
- **PII minimization**: log redaction, field-level encryption, access controls.

---

## Immediate next actions (recommended)
1. Finish locking/atomicity for all write endpoints in `web_portal/server.py` (policies/claims/underwriting/billing).
2. Move sessions to DB-backed repository (already present) so multi-worker deployments behave correctly.
3. Refactor AI decisions to emit structured `reason_codes` + `model_version` and log to audit.

