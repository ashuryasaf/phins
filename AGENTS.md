# AGENTS.md - AI Agent Guide for PHINS

This file is the working guide for AI agents contributing to the PHINS codebase.
Keep changes narrow, verify behavior with targeted tests, and prefer existing
patterns over new abstractions. Treat this document as repo-specific operating
context, not as permission to ignore direct user instructions.

## 1) Project Summary

**PHINS (Professional Insurance Management System)** is a Python-first insurance
platform with:

- Customer, policy, underwriting, claims, billing, and reporting workflows
- A lightweight HTTP portal and JSON API in `web_portal/server.py`
- Optional persistence through SQLite or PostgreSQL via SQLAlchemy
- A large set of service modules for domain workflows, analytics, integrity, and
  automation

The repository mixes demo-style in-memory flows with production-oriented database
support. When changing behavior, preserve backward compatibility unless the task
explicitly says otherwise.

## 2) Repository Map (High-Value Paths)

```text
/workspace
|- AGENTS.md                          # This guide
|- README.md                          # Product overview and deployment pointers
|- phins_system.py                    # Core insurance domain entities/logic
|- billing_engine.py                  # Billing engine used by validation/tests
|- accounting_engine.py               # Accounting engine used by validation/tests
|- customer_validation.py             # Validation models/utilities
|- config.py                          # Root-level application/config helpers
|- conftest.py                        # Global pytest setup; embedded server for tests
|- validate_system.py                 # Broad validation script
|- check_database_connection.py       # Database health check helper
|- init_database.py                   # Database initialization helper
|- quick_smoke_test.sh                # Lightweight HTTP smoke test
|- web_portal/
|  |- server.py                       # Main HTTP server and many route handlers
|  |- api_extensions.py               # Extension dispatch for extra API routes
|  |- connectors.py                   # Integration connectors
|  |- api_bi_analytics.py             # Additional API module; verify wiring before use
|  |- api_delivery_bidding.py         # Additional API module; verify wiring before use
|  `- static/                         # Frontend assets (HTML/CSS/JS)
|- services/                          # 50+ business/service modules
|- database/
|  |- __init__.py                     # Connection/session helpers
|  |- config.py                       # DB config
|  |- models.py                       # SQLAlchemy ORM models
|  |- notification_models.py          # Additional ORM models
|  |- manager.py                      # High-level repository manager
|  |- data_access.py                  # Dict-like bridge for DB-backed storage
|  |- seeds.py                        # Seed data
|  |- migrate_data.py                 # Data migration helpers
|  |- migrations/                     # Migration scripts/assets
|  `- repositories/                   # Repository implementations
|- security/                          # Security helpers/utilities
|- scripts/                           # Operational and one-off scripts
|- tests/                             # Main pytest suite
|- test_*.py                          # Additional root-level integration tests
`- docs/
   `- platform_data_architecture.md   # Platform data and event architecture
```

Notes:

- The repository contains many additional docs, reports, and implementation
  summaries beyond the paths above; use the map as a starting point, not a full
  inventory.
- There are both `tests/test_*.py` files and root-level `test_*.py` files.
- Some functionality exists in large, multi-purpose modules, especially
  `web_portal/server.py`, so inspect nearby code before introducing new helpers
  or abstractions.

## 3) Architecture Notes

1. **Transport/API layer**
   - `web_portal/server.py` is the main HTTP entry point.
   - This is **not** a Flask/FastAPI app; it is built on
     `http.server.BaseHTTPRequestHandler`.
   - Tests start `portal.PortalHandler` under `ThreadingHTTPServer`, so changes
     to handler initialization and port assumptions can ripple into many suites.
   - `web_portal/api_extensions.py` provides extension dispatch used by the main
     server for some GET/POST/PUT paths.

2. **Domain and engine layer**
   - `phins_system.py` contains core insurance entities and orchestration logic.
   - `billing_engine.py` and `accounting_engine.py` are important root-level
     engines and are part of validation flows.

3. **Service layer**
   - `services/*.py` contains most business workflows.
   - Reuse service modules from route handlers instead of embedding new business
     logic directly in `web_portal/server.py` where practical.

4. **Persistence layer**
   - Default/demo flows often use in-memory dictionaries in `web_portal/server.py`.
   - Database-backed flows go through `database/manager.py`,
     `database/repositories/*`, and `database/data_access.py`.
   - Storage modes:
     - In-memory fallback/default for many HTTP tests and demos
     - SQLite for local/dev persistence
     - PostgreSQL for production deployments

5. **Testing harness**
   - Root `conftest.py` starts an embedded server on `http://localhost:8000`
     during pytest runs and sets default test environment variables.
   - The embedded server binds to `127.0.0.1:8000`.
   - Read it before changing server startup assumptions, ports, or storage mode
     behavior in tests.

## 4) Important Existing Patterns

### Status and Numeric Helpers

Case-insensitive status and defensive numeric conversion helpers already exist in
`web_portal/server.py`:

```python
status_eq(item, "approved", "paid")
status_in(item, ["pending", "under_review"])
get_status_lower(item)
safe_float(value, default=0.0)
safe_int(value, default=0)
```

Prefer reusing these helpers for portal/data-integrity work instead of redoing
string normalization or unsafe numeric casting.

### Repository Usage

- `database/manager.py` exposes repository properties such as `customers`,
  `policies`, `claims`, `billing`, `audit`, `platform_ledger`, `actuarial`,
  `tokens`, `sessions`, and `underwriting`.
- `DatabaseManager.session_scope()` is the preferred pattern for grouped
  transactional work.
- `database/repositories/base.py` auto-commits write operations. Keep that in
  mind when composing multiple repository calls.

### Before Adding New Code

Before creating new modules, helpers, or tests:

1. Search for an existing implementation or adjacent pattern first.
2. Check whether the behavior already exists in `services/`, `database/`, or
   `web_portal/server.py`.
3. Prefer extending an existing test module that covers the same workflow rather
   than creating a near-duplicate test file.
4. Preserve backward compatibility for default in-memory flows unless the task
   explicitly requires a behavior change.

### API Shape

- Validate request payloads on every endpoint.
- Preserve JSON error responses in the form:

```json
{ "error": "Error message description" }
```

- Preserve paginated/list response shapes where applicable:

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0
}
```

## 5) Local Setup and Common Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the server:

```bash
python3 web_portal/server.py
```

Run the server's lightweight self-check:

```bash
python3 web_portal/server.py --test
```

Run with SQLite persistence:

```bash
export USE_DATABASE=1
export USE_SQLITE=1
python3 web_portal/server.py
```

Useful validation commands:

```bash
python3 validate_system.py
python3 check_database_connection.py
bash quick_smoke_test.sh
```

Useful git checks:

```bash
git status --short
git diff -- AGENTS.md
```

Targeted pytest examples:

```bash
pytest tests/test_api_integration.py
pytest tests/test_database.py
pytest tests/test_billing_engine.py
pytest tests/test_accounting_engine.py
pytest -k "billing" tests/
pytest tests/ -q --tb=line
```

Full-repo pytest note:

```bash
pytest
```

Running `pytest` from the repo root may collect both `tests/` and root-level
`test_*.py` files. Running `pytest tests/` will skip the root-level tests.

## 6) Coding and Design Conventions

### Python Style

- Follow PEP 8.
- Use `snake_case` for functions/variables.
- Use `PascalCase` for classes.
- Use `UPPER_CASE` for constants.
- Add type hints for new or updated function signatures when practical.

### Domain Conventions

Common ID prefixes:

- Company: `COM`
- Customer: `CUST`
- Policy: `POL`
- Claim: `CLM`
- Bill: `BILL`

### Design Guidance

- Keep route handlers thin when possible.
- Reuse existing services/repositories before adding new modules.
- Avoid embedding raw SQL or ORM-heavy logic inside route handlers.
- For database changes, update models, repositories, seeds/migrations, and tests
  together.
- For large `server.py` edits, inspect nearby patterns first; many behaviors are
  implemented in-place rather than through a clean controller split.
- Prefer the least disruptive change that matches existing conventions in the
  touched area.

## 7) Standard Agent Workflows

### Add or Update an API Endpoint

1. Inspect existing routes in `web_portal/server.py`.
2. Check whether the behavior belongs in `server.py` or `api_extensions.py`.
3. Reuse existing service logic where possible.
4. Validate request inputs and preserve response conventions.
5. Add tests for success and failure paths.

### Add or Update a Service

1. Create or modify the module in `services/`.
2. Wire it into the relevant route/engine layer.
3. Add or update targeted tests.
4. Update docs if behavior or operator workflow changes.

### Modify Database Schema or Persistence Logic

1. Update `database/models.py` and any related model files.
2. Update repositories, `database/manager.py`, and `database/data_access.py`
   if the schema affects dict-like compatibility.
3. Review seeds, initialization, and migrations.
4. Run database-focused tests and startup checks.

### Modify Billing/Accounting Workflows

1. Inspect `billing_engine.py`, `accounting_engine.py`, and related services.
2. Check matching tests in `tests/test_billing_engine.py`,
   `tests/test_accounting_engine.py`, and any affected API/integration tests.
3. Run `python3 validate_system.py` if the change is broad enough to affect the
   validation flow.

## 8) Testing Guidance

Before merging non-trivial changes:

1. Run targeted tests for the files or workflow you changed.
2. Run at least one broader integration or smoke test for the impacted area.
3. Verify no regressions in auth, billing, underwriting, data isolation, or
   dashboard integrity when those areas are touched.

For docs-only changes:

- Verify the referenced files, commands, and paths still exist.
- Tests are usually not required, but you should still review the rendered diff
  for formatting or factual regressions.

High-value test modules include:

- `tests/test_api_integration.py`
- `tests/test_database.py`
- `tests/test_billing_engine.py`
- `tests/test_accounting_engine.py`
- `tests/test_dashboard_data_integrity.py`
- `tests/test_security_performance.py`
- `tests/test_customer_data_isolation.py`
- `tests/test_api_customer_ledger_isolation.py`
- `tests/test_e2e_insurance_pipeline.py`
- `tests/test_platform_event_ledger.py`
- `tests/test_notification_service.py`
- `tests/test_process_pipeline_orchestrator.py`

Useful root-level integration tests include:

- `test_complete_flow.py`
- `test_portal_complete.py`
- `test_integration.py`
- `test_pr_complete.py`

### Test Environment Notes

- `conftest.py` defaults HTTP tests to in-memory portal storage:
  - `TEST_BASE_URL=http://localhost:8000`
  - `USE_DATABASE=false`
  - `USE_SQLITE=true`
  - `PHINS_TEST_MODE=true`
- It also starts an embedded server on `127.0.0.1:8000`.
- Each test resets the in-memory portal dictionaries to avoid fixed-ID/email collisions.
- Be careful when changing startup, port binding, or state-reset behavior.

## 9) Security and Reliability Rules

- Never hardcode credentials, secrets, or tokens.
- Avoid customer/account data leakage across tenants or users.
- Use audit logging for sensitive or admin-facing operations when the surrounding
  code already supports it.
- Handle missing or invalid numeric values defensively.
- Preserve graceful fallback behavior for degraded external dependencies.
- Be careful with logs and test fixtures so they do not expose secrets or PII.

## 10) Deployment and Ops Notes

Environment variables commonly used:

| Variable | Purpose |
|---|---|
| `USE_DATABASE` | Enable persistence mode |
| `USE_SQLITE` | Use SQLite instead of PostgreSQL |
| `SQLITE_PATH` | Override SQLite database path |
| `DATABASE_URL` | PostgreSQL connection string |
| `ENABLE_LEDGER_PERSISTENCE` | Enable ledger persistence |
| `PORT` | Server port (default 8000) |
| `PHINS_TEST_MODE` | Test-mode behavior for server/tests |

Common health and diagnostics endpoints include:

- `/api/health`
- `/health`
- `/api/diagnostics/db-test`
- `/api/diagnostics/env-check`

Do not assume every auxiliary API module is live. For files such as
`web_portal/api_bi_analytics.py` or `web_portal/api_delivery_bidding.py`,
confirm the route wiring before making behavior assumptions.

## 11) Agent Checklist Before Commit

- [ ] Changes are scoped to the requested task.
- [ ] Nearby existing patterns were inspected before editing.
- [ ] Relevant tests or validations were run, or the task is docs-only.
- [ ] Referenced files/commands/paths were verified if docs were changed.
- [ ] Docs/comments were updated if behavior changed.
- [ ] No secrets or environment-specific credentials were introduced.
- [ ] Error handling, validation, and backward compatibility were considered.

## 12) Reference Docs

Start with:

- `README.md`
- `DEPLOYMENT.md`
- `DATABASE_SETUP.md`
- `SECURITY.md`
- `DATABASE_IMPLEMENTATION_SUMMARY.md`
- `AI_ARCHITECTURE.md`
- `RAILWAY_DEPLOYMENT.md`
- `RAILWAY_POSTGRES_FIX.md`
- `docs/platform_data_architecture.md`
- Other `RAILWAY_*.md` files in the repo root when deployment work is involved

## 13) Practical Operating Rules

Use these guardrails during implementation work:

1. Keep changes tightly scoped to the request.
2. Reuse existing services, repositories, and helper functions first.
3. Preserve API response shape and error conventions.
4. Avoid modifying unrelated files, even if they are already changed locally.
5. Add or update tests whenever behavior changes.
6. Prefer targeted tests first, then a broader smoke/integration check for
   moderate- or high-risk work.
7. Document non-obvious behavior changes when needed.
8. Commit with clear, descriptive messages.
9. Verify whether `pytest` should include or exclude root-level `test_*.py`
   files for your task.
10. If the request is ambiguous, choose the least disruptive implementation path.

## 14) AGENTS.md Maintenance Rules

When updating this file in future tasks:

1. Prefer corrections and targeted additions over broad rewrites.
2. Validate claims about file locations, commands, ports, and environment
   variables against the current repository.
3. Keep instructions specific to this repo; avoid generic agent-policy prose
   unless it changes how contributors should work in PHINS.
4. If a section becomes stale, fix or remove it rather than preserving outdated
   guidance for completeness.

## 15) Quick Start Workflow (Per Task)

Use this sequence for most tasks:

1. Identify the impacted layer: API, service, engine, repository, or domain.
2. Inspect adjacent code for patterns already used in that area.
3. Implement the smallest viable change.
4. Add or update tests for the affected workflow.
5. Run targeted tests first.
6. Run a broader validation step if the change crosses module boundaries.
7. Update docs/comments only where behavior or assumptions changed.
8. Commit with a clear message describing scope and intent.

## 16) Cloud Agent Git Workflow (Required)

When running in cloud agent mode:

1. Confirm you are on the assigned feature branch before editing.
2. Keep commits small and task-focused where practical.
3. Stage only intended files, then commit with a clear message.
4. Push with upstream tracking when needed:

```bash
git push -u origin <branch-name>
```

5. Retry transient network push failures with exponential backoff.
6. Do not rewrite history unless explicitly requested.
7. If the change is documentation-only, note that tests were not required in the
   task summary.

---

Last updated: March 25, 2026
