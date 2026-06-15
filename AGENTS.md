# AGENTS.md - PHINS Agent Playbook

Use this file as concise, repo-specific guidance for PHINS contributions.
Keep changes narrow, follow existing patterns, and let direct user instructions
override this document.

## 1) Quick Mental Model

PHINS is a Python platform built around:

- a large `BaseHTTPRequestHandler` app in `web_portal/server.py` (~50k lines)
- optional extension routing in `web_portal/api_extensions.py` (~3450 lines)
  and domain-specific API modules (`api_bi_analytics.py`,
  `api_delivery_bidding.py`)
- service-layer logic in `services/` (80 modules)
- database access in `database/`
- security utilities in `security/`
- scheduled tasks in `scheduler/`
- operational scripts in `scripts/`
- both `tests/test_*.py` (121 files) and root-level `test_*.py` (11 files)

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
| Business rule/workflow | `services/`, then the route or engine that calls it |
| Database/schema/repository | `database/models.py`, `database/manager.py`, `database/repositories/`, `database/config.py` |
| Billing/accounting behavior | `billing_engine.py`, `accounting_engine.py`, related tests |
| Security/auth/tokens | `security/`, `web_portal/server.py` (session/login routes) |
| Scheduled jobs | `scheduler/runner.py`, `scripts/run_monthly_auto_pay.py` |
| Test harness/debugging | root `conftest.py`, affected `tests/test_*.py`, root `test_*.py` |
| Deployment/config | `DEPLOYMENT.md`, `RAILWAY_*.md`, `railway.json`, `render.yaml`, `Dockerfile` |

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
|  |- connectors.py
|  `- static/                           # HTML/JS/CSS dashboards and assets
|- services/                            # 80 service modules
|- database/
|  |- config.py
|  |- manager.py
|  |- models.py
|  |- marketplace_models.py
|  |- data_access.py
|  |- seeds.py
|  |- notification_models.py
|  |- migrate_data.py
|  |- migrations/
|  |- repositories/                     # 14 *_repository.py + base.py
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
|  `- migrate_passwords.py
|- scheduler/
|  `- runner.py
|- scripts/                             # operational utilities
|  `- entrypoint.sh                     # container dispatcher (serve/cron/db-init)
|- tests/                               # 121 test files
|- docs/
|  |- platform_data_architecture.md
|  |- health_marketplace_architecture.md
|  |- health_marketplace_implementation_spec.md
|  |- INVESTOR_AI_BI_OPTIMIZATION_REVIEW.md
|  `- uml/
`- .github/workflows/                   # CI (visual_test, security_scan)
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

## 5) API Task Playbook

When changing or adding an API endpoint:

1. Inspect the surrounding route in `web_portal/server.py` first.
2. Check whether the endpoint belongs in `server.py`,
   `web_portal/api_extensions.py`, `web_portal/api_bi_analytics.py`, or
   `web_portal/api_delivery_bidding.py`.
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
- `DatabaseManager` exposes 33 repository properties (see §4 for the full list).
- Repository modules (14 `*_repository.py` + `base.py`):
  `customer_repository.py`, `policy_repository.py`, `claim_repository.py`,
  `underwriting_repository.py`, `billing_repository.py`,
  `user_repository.py`, `session_repository.py`, `audit_repository.py`,
  `platform_ledger_repository.py`, `actuarial_repository.py`,
  `token_repository.py`, `document_repository.py`, `supplier_repository.py`
  (bundles supplier, invitation, offer, order, document, and supply-chain
  ledger repositories), and `marketplace_repository.py` (bundles wallet,
  payment-intent, refund, journal, settlement, external-payer,
  marketplace-claim, remittance, receivable, idempotency, and outbox
  repositories).
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
   `db-init`, `shell`, `exec`). Keep startup behavior compatible with it
   unless the task explicitly changes the entrypoint.
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
- **Test:** `PHINS_TEST_MODE`, `TEST_BASE_URL`, `TEST_PORT`
- **Ledger:** `ENABLE_LEDGER_PERSISTENCE`, `LEDGER_PERSISTENCE_VERBOSE`,
 `LEDGER_PERSISTENCE_LOG_INTERVAL`, `PHINS_LEDGER_DB_AUTOREPAIR`
- **Media:** `MEDIA_PROVIDER_WEBHOOK_SECRET`, `DEFAULT_MEDIA_SUBTITLE_PROVIDER`,
  `DEFAULT_MEDIA_VIDEO_PROVIDER`, `PHINS_MEDIA_INLINE_MAX_BYTES`
- **Auto-pay:** `PHINS_DEFAULT_AUTO_PAY_CARD_NUMBER`,
  `MONTHLY_AUTO_PAY_COMMAND_TOKEN`
- **Security:** `SESSION_SECRET_KEY`, `PHINS_ENCRYPTION_KEY`,
  `PHINS_ENFORCE_SECRET_POLICY`, `PHINS_EMERGENCY_UNLOCK_KEY`,
  `ALLOW_LEGACY_DEMO_PASSWORDS`
- **SMS/OTP:** `SMS_PROVIDER` (`twilio` or `telesign`), `TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `TELESIGN_CUSTOMER_ID`,
  `TELESIGN_API_KEY`, `TELESIGN_BASE_URL`, `TELESIGN_SEND_PATH`,
  `TELESIGN_MESSAGE_TYPE`, `TELESIGN_SENDER_ID`,
  `SMS_RATE_LIMIT_PER_MINUTE`, `SMS_RATE_LIMIT_PER_HOUR`,
  `SMS_RATE_LIMIT_PER_DAY` (password-reset/OTP auto-falls back to the
  configured SMS provider when email delivery is unconfigured)
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
```

Important test harness facts:

- **Root `conftest.py`** starts an embedded `ThreadingHTTPServer` on
  `127.0.0.1` with `PortalHandler`; sets env defaults
  (`USE_DATABASE=false`, `USE_SQLITE=true`, `PHINS_TEST_MODE=true`)
- Port selection: honors a `TEST_PORT` env override, prefers `8000`, and
  falls back to a free kernel-assigned port if `8000` is busy; the bound
  port is published via `TEST_PORT` and `TEST_BASE_URL`, so tests should
  read `TEST_BASE_URL` rather than hardcoding `http://localhost:8000`
- **`tests/conftest.py`** only adds `sys.path` and sets `PHINS_TEST_MODE`; it
  does **not** start the server
- Tests reset in-memory portal state between cases (clears `POLICIES`,
  `CLAIMS`, `CUSTOMERS`, `SESSIONS`, `BILLING`, etc.)
- Options wheel service and document processing service are also reset per test
- 121 test files under `tests/`, 11 root-level `test_*.py` files

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

## 10) Security and Reliability

- Avoid exposing PII, tokens, secrets, or sensitive logs.
- Use defensive numeric conversion and status normalization helpers where
  appropriate.
- Preserve graceful fallback behavior for external dependencies.
- Use audit-oriented patterns for sensitive operations if the surrounding code
  already does so.
- Security utilities live in `security/` (`vault.py`, `auth_tokens.py`,
  `headers.py`, `network.py`, `secrets_policy.py`, `firewall.py`,
  `intrusion_detector.py`, `request_sanitizer.py`, `file_scanner.py`); reuse
  them rather than rolling custom auth/crypto.

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

Last updated: June 15, 2026
