# AGENTS.md - AI Agent Guide for PHINS

This document is the working guide for AI agents contributing to the PHINS codebase.

## 1) Project Summary

**PHINS (Professional Insurance Management System)** is an insurance platform with:
- Customer, policy, underwriting, claims, and billing workflows
- Web portal + REST-style API
- SQLite/PostgreSQL persistence via SQLAlchemy
- Automation services for underwriting, claims, and analytics

Primary runtime language is **Python**.

## 2) Repository Map (High Value Paths)

```text
/workspace
|- phins_system.py                    # Core domain entities and logic
|- web_portal/
|  |- server.py                       # Main API/server module (large file)
|  |- api_extensions.py               # API extension routes/helpers
|  |- connectors.py                   # External integration connectors
|  `- static/                         # Frontend assets (HTML/CSS/JS)
|- services/                          # Business services (50+ modules)
|- database/
|  |- models.py                       # SQLAlchemy ORM models
|  |- manager.py                      # DB initialization/manager
|  |- config.py                       # DB config
|  |- seeds.py                        # Seed data
|  `- repositories/                   # Repository pattern implementations
|- tests/                             # pytest suite
|- security/                          # Security helpers/utilities
`- docs/                              # Design and implementation docs
```

## 3) Architecture Notes

1. **Domain layer**: `phins_system.py` contains core insurance entities.
2. **Service layer**: `services/*.py` contains business workflows.
3. **Data access layer**: `database/repositories/*` encapsulates persistence.
4. **Transport/API layer**: `web_portal/server.py` and related modules expose endpoints.
5. **Storage modes**:
   - SQLite in local/dev mode
   - PostgreSQL in production mode
   - In-memory fallback when DB is unavailable

## 4) Local Setup and Common Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run server (default):

```bash
python3 web_portal/server.py
```

Run with SQLite:

```bash
export USE_DATABASE=1
export USE_SQLITE=1
python3 web_portal/server.py
```

Run targeted tests:

```bash
pytest -v tests/
pytest tests/test_api_integration.py
pytest -k "billing" tests/
```

Useful validations:

```bash
python3 validate_system.py
python3 check_database_connection.py
```

## 5) Coding and Design Conventions

### Python Style
- Follow PEP 8.
- Use `snake_case` for functions/variables.
- Use `PascalCase` for classes.
- Use `UPPER_CASE` for constants.
- Add type hints for new/updated function signatures when practical.

### Domain Conventions
- ID prefixes:
  - Company: `COM`
  - Customer: `CUST`
  - Policy: `POL`
  - Claim: `CLM`
  - Bill: `BILL`

### Status Handling
Use existing helpers to avoid fragile string checks and conversion errors:

```python
status_eq(item, "approved", "paid")
safe_float(value, default=0.0)
safe_int(value, default=0)
```

## 6) API and Data Expectations

- Keep API contracts backward compatible unless explicitly migrating.
- Validate request inputs on every endpoint.
- Return consistent JSON error payloads:

```json
{ "error": "Error message description" }
```

- For list endpoints, preserve paginated response shape where applicable:

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0
}
```

## 7) Standard Agent Workflows

### Add a New Service
1. Create module in `services/`.
2. Wire it into `web_portal/server.py` (or extension module).
3. Add/update tests in `tests/`.
4. Update related docs when behavior changes.

### Add a New API Endpoint
1. Add route handler.
2. Reuse existing service logic where possible.
3. Validate inputs and error paths.
4. Add endpoint tests (success + failure cases).

### Modify Database Schema
1. Update `database/models.py`.
2. Add migration strategy if needed.
3. Update affected repositories/services/tests.
4. Verify startup + data seeding paths.

### Add/Update Repository Layer
1. Follow existing repository pattern.
2. Keep data access concerns inside repository modules.
3. Avoid embedding SQL/ORM query logic directly in route handlers.

## 8) Testing Guidance

Before merging non-trivial changes:

1. Run targeted tests related to changed area.
2. Run at least one broader integration/smoke test for impacted workflow.
3. Verify no regressions in auth, billing, underwriting, or data integrity paths.

High-value test modules include:
- `tests/test_api_integration.py`
- `tests/test_database.py`
- `tests/test_e2e_insurance_pipeline.py`
- `tests/test_security_performance.py`
- `tests/test_dashboard_data_integrity.py`
- `tests/test_billing_engine.py`

## 9) Security and Reliability Rules

- Never hardcode credentials, secrets, or tokens.
- Avoid customer data leakage across accounts/tenants.
- Use audit logging for sensitive/admin operations.
- Handle missing/invalid numeric values defensively.
- Keep graceful fallback behavior for degraded external dependencies.

## 10) Deployment and Ops Notes

Environment variables commonly used:

| Variable | Purpose |
|---|---|
| `USE_DATABASE` | Enable persistence mode |
| `USE_SQLITE` | Use SQLite instead of PostgreSQL |
| `DATABASE_URL` | PostgreSQL connection string |
| `ENABLE_LEDGER_PERSISTENCE` | Enable ledger persistence |
| `SECRET_KEY` | Session encryption key |
| `PORT` | Server port (default 8000) |

Diagnostic endpoints:
- `/api/health`
- `/api/diagnostics/db-test`
- `/api/diagnostics/env-check`

## 11) Agent Checklist Before Commit

- [ ] Changes are scoped to requested task.
- [ ] Existing patterns were followed (service/repository/api split).
- [ ] Relevant tests were run and passed locally.
- [ ] Docs/comments were updated if behavior changed.
- [ ] No secrets introduced.
- [ ] Error handling and validation paths were considered.

## 12) Reference Docs

Start with:
- `README.md`
- `DEPLOYMENT.md`
- `SECURITY.md`
- `DATABASE_IMPLEMENTATION_SUMMARY.md`
- `AI_ARCHITECTURE.md`
- `RAILWAY_DEPLOYMENT.md`
- `RAILWAY_POSTGRES_FIX.md`

## 13) Agent Operating Rules (Practical)

Use these guardrails during implementation work:

1. Keep changes tightly scoped to the requested task.
2. Reuse existing services/repositories before introducing new abstractions.
3. Preserve API response shape and error payload conventions.
4. Avoid modifying unrelated files, even if they are already changed locally.
5. Add or update tests whenever behavior changes.
6. Prefer targeted test runs for speed, then run a broader smoke test for high-risk areas.
7. Document non-obvious behavior changes in code comments or docs when needed.
8. Commit with clear, descriptive messages that explain what changed and why.
9. Never include secrets, tokens, or environment-specific credentials in code or logs.
10. If a request is ambiguous, choose the least disruptive implementation path.

## 14) Quick Start Workflow (Per Task)

Use this sequence for most requests:

1. Read the task and confirm impacted layer(s): API, service, repository, or domain.
2. Inspect nearby existing patterns before introducing new abstractions.
3. Implement the smallest viable change that solves the request.
4. Add or update tests in `tests/` for success and failure paths.
5. Run targeted tests first, then one broader smoke/integration test if risk is moderate/high.
6. Verify API responses remain backward compatible unless migration is requested.
7. Update docs/comments only where behavior changed or logic is non-obvious.
8. Commit with a clear message describing scope and intent.

## 15) Cloud Agent Git Workflow (Required)

When running in cloud agent mode, follow this sequence:

1. Confirm you are on the assigned feature branch before editing.
2. Keep commits small and task-focused (prefer multiple small commits over one large commit).
3. Stage only intended files (`git add <paths>`), then commit with a clear message.
4. Push with upstream tracking when needed:

```bash
git push -u origin <branch-name>
```

5. If push fails due to transient network issues, retry with exponential backoff (4s, 8s, 16s, 32s).
6. Do not rewrite history (`push --force`) unless explicitly requested.
7. If the change is documentation-only, note that tests were not required in the task summary.

---

Last updated: February 27, 2026
