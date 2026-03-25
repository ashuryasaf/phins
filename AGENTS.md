# AGENTS.md - PHINS Agent Playbook

Use this file as concise, repo-specific guidance for PHINS contributions.
Keep changes narrow, follow existing patterns, and let direct user instructions
take priority over this document.

## 1) Quick Mental Model

PHINS is a Python insurance platform with:

- a lightweight HTTP portal in `web_portal/server.py`
- service-layer business logic in `services/`
- optional SQLite/PostgreSQL persistence in `database/`
- both `tests/test_*.py` and root-level `test_*.py` suites

Default behavior often uses in-memory data structures. Preserve backward
compatibility for in-memory/demo flows unless the task explicitly requires
different behavior.

Preferred file-by-task:

| Task | Start here |
|---|---|
| API route/response change | `web_portal/server.py`, `web_portal/api_extensions.py` |
| Business rule/workflow | `services/`, then route/engine caller |
| Database/schema/repository | `database/models.py`, `database/manager.py`, `database/repositories/` |
| Billing/accounting behavior | `billing_engine.py`, `accounting_engine.py`, related tests |
| Test harness/debugging | `conftest.py`, affected `tests/test_*.py`, root `test_*.py` |
| Deployment/config | `DEPLOYMENT.md`, `railway.json`, `render.yaml`, `vercel.json`, `Dockerfile` |

## 2) High-Value Paths

```text
/workspace
|- AGENTS.md
|- README.md
|- DEPLOYMENT.md
|- SECURITY.md
|- conftest.py
|- phins_system.py
|- billing_engine.py
|- accounting_engine.py
|- validate_system.py
|- web_portal/server.py
|- web_portal/api_extensions.py
|- web_portal/static/
|- services/
|- database/manager.py
|- database/models.py
|- database/repositories/
|- tests/
`- docs/platform_data_architecture.md
```

Start with adjacent code before adding helpers, modules, or abstractions.
`web_portal/server.py` is large and multi-purpose; many patterns are implemented
in place rather than behind clean controller boundaries.

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
```

Database patterns:

- Use `DatabaseManager` in `database/manager.py` for repository access.
- Prefer `DatabaseManager.session_scope()` for grouped transactional work.
- Repository writes may auto-commit; read surrounding code before composing
  multiple repository operations.

Common ID prefixes:

- Company: `COM`
- Customer: `CUST`
- Policy: `POL`
- Claim: `CLM`
- Bill: `BILL`

## 5) API Task Playbook

When changing or adding an API endpoint:

1. Inspect the surrounding route in `web_portal/server.py` first.
2. Check whether the endpoint belongs in `server.py` or `web_portal/api_extensions.py`.
3. Reuse service-layer logic from `services/` instead of embedding new business
   rules directly in the handler.
4. Validate request payloads and preserve response shape conventions.
5. Confirm whether related dashboard, billing, underwriting, or ledger behavior
   depends on the same data.
6. Add success and failure-path tests.

Watch-outs:

- This is **not** Flask or FastAPI; it uses `BaseHTTPRequestHandler`.
- Do not assume auxiliary API modules are wired; verify route registration first.
- Changes to handler setup or port assumptions can break many tests.

## 6) Database Task Playbook

When changing persistence or schema behavior:

1. Inspect `database/models.py`, `database/manager.py`, and the relevant
   repository in `database/repositories/`.
2. Update related models, repositories, and dict-compatibility code together if
   the schema affects both DB and in-memory flows.
3. Review seeds, initialization, and migration helpers when schema changes.
4. Preserve compatibility with the default in-memory fallback unless the task
   explicitly removes it.
5. Run database-focused tests plus at least one broader workflow check.

Key facts:

- Storage modes include in-memory, SQLite, and PostgreSQL.
- `database/manager.py` exposes repositories including customers, policies,
  claims, underwriting, billing, users, sessions, audit, platform ledger,
  actuarial, and tokens.
- Connection handling includes recovery logic; avoid bypassing existing session
  patterns without a clear reason.

## 7) Deployment Task Playbook

When working on deployment or environment configuration:

1. Read `DEPLOYMENT.md` and any relevant `RAILWAY_*.md` files first.
2. Verify the actual deployment files before editing assumptions:
   - `railway.json`
   - `render.yaml`
   - `vercel.json`
   - `Dockerfile`
3. Confirm how the app starts in production before changing commands or ports.
4. Keep startup behavior compatible with `python3 web_portal/server.py` unless
   the task explicitly changes the entrypoint.
5. Document any environment-variable or operator-facing changes.

Environment variables commonly used:

- `USE_DATABASE`
- `USE_SQLITE`
- `SQLITE_PATH`
- `DATABASE_URL`
- `ENABLE_LEDGER_PERSISTENCE`
- `PORT`
- `PHINS_TEST_MODE`

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
```

Important test harness facts from `conftest.py`:

- pytest starts an embedded server on `127.0.0.1:8000`
- `TEST_BASE_URL` defaults to `http://localhost:8000`
- `USE_DATABASE=false`
- `USE_SQLITE=true`
- `PHINS_TEST_MODE=true`
- tests reset in-memory portal dictionaries between cases

## 9) Common Pitfalls

- Fixing only the database path can leave in-memory HTTP flows inconsistent; if
  a feature exists in both modes, check both code paths before finishing.
- Repository or schema changes can require matching updates in
  `database/data_access.py`, seeds, or migration helpers.
- Handler initialization, port assumptions, or shared module state can break many
  tests because pytest starts a real embedded `PortalHandler` server.
- Route changes may need updates in both `web_portal/server.py` and
  `web_portal/api_extensions.py`; verify actual wiring rather than assuming.

Docs-only changes usually do not need tests, but they do require verifying that
referenced files, commands, paths, and ports still exist.

## 10) Security and Reliability

- Avoid exposing PII, tokens, secrets, or sensitive logs.
- Use defensive numeric conversion and status normalization helpers where
  appropriate.
- Preserve graceful fallback behavior for external dependencies.
- Use audit-oriented patterns for sensitive operations if the surrounding code
  already does so.

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

Last updated: March 25, 2026
