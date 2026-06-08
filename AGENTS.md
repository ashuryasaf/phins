# AGENTS.md - PHINS Agent Playbook

Use this file as concise, repo-specific guidance for PHINS contributions.
Keep changes narrow, follow existing patterns, and let direct user instructions
override this document.

## 1) Quick Mental Model

PHINS is a Python platform built around:

- a large `BaseHTTPRequestHandler` app in `web_portal/server.py` (~49.6k lines)
- optional extension routing in `web_portal/api_extensions.py` (~3260 lines)
  and domain-specific API modules:
  - `web_portal/api_assessment_center.py` (~1400 lines) — Customer 360 /
    Assessment Center upload + fact-mining routes
  - `web_portal/api_bi_analytics.py` — BI/analytics
  - `web_portal/api_delivery_bidding.py` — delivery bidding
- service-layer logic in `services/` (78 modules)
- database access in `database/`
- security utilities in `security/`
- scheduled tasks in `scheduler/`
- operational scripts in `scripts/`
- both `tests/test_*.py` (114 files) and root-level `test_*.py` (11 files)

Runtime defaults are important:

- `web_portal/server.py` defaults to `USE_DATABASE=true`
- pytest config in root `conftest.py` sets `USE_DATABASE=false`,
  `USE_SQLITE=true`, `PHINS_TEST_MODE=true`, and starts an embedded
  `ThreadingHTTPServer` on `127.0.0.1`. Port resolution: honors `TEST_PORT`
  if set, then tries `8000` (so legacy tests that hard-code
  `http://localhost:8000` keep working), then falls back to a kernel-assigned
  free port. The actual bound port is republished to `TEST_PORT` and
  `TEST_BASE_URL`.
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
| Assessment Center / Customer 360 | `web_portal/api_assessment_center.py`, `services/assessment_center_service.py` |
| Wallet / marketplace settlement | `database/repositories/marketplace_repository.py`, `database/marketplace_models.py` |
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
|  |- api_assessment_center.py         # Customer 360 / fact ingestion
|  |- api_bi_analytics.py
|  |- api_delivery_bidding.py
|  |- connectors.py
|  `- static/                           # HTML/JS/CSS dashboards and assets
|- services/                            # 78 service modules
|- database/
|  |- config.py
|  |- manager.py
|  |- models.py
|  |- marketplace_models.py            # wallet / settlement / outbox models
|  |- data_access.py
|  |- seeds.py
|  |- notification_models.py
|  |- migrate_data.py
|  |- migrations/
|  |- dynamic_customers.json           # in-memory/demo seed data
|  |- invitation_codes.json
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
|- scripts/                             # operational utilities (entrypoint.sh, run_monthly_auto_pay.py, ...)
|- tests/                               # 114 test files
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

`DatabaseManager` repositories (as properties, 33 total):

- Core: `customers`, `policies`, `claims`, `underwriting`, `billing`
- Auth/audit: `users`, `sessions`, `audit`, `tokens`
- Platform: `platform_ledger`, `actuarial`
- Documents: `documents`, `processing_jobs`
- Supply chain: `suppliers`, `supplier_invitations`, `supplier_offers`,
  `supplier_orders`, `supplier_documents`, `supply_chain_ledger`
- Wallet / payments: `wallet_accounts`, `wallet_holds`, `wallet_ledger`,
  `payment_intents`, `refunds`, `journal`
- Marketplace settlement: `supplier_settlement_runs`,
  `supplier_settlement_items`, `external_payers`, `marketplace_claims`,
  `remittances`, `payer_receivables`
- Operational: `idempotency`, `outbox`

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
   `web_portal/api_extensions.py`, `web_portal/api_assessment_center.py`,
   `web_portal/api_bi_analytics.py`, or `web_portal/api_delivery_bidding.py`.
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
  and invitation handling.
- `api_assessment_center.py` owns `/api/assessment-center/*` (uploads, fact
  mining, customer profile, risk indicators, charts, export/import, Mislaka
  linking). Auth model: `customer` sessions are scoped to their own
  `customer_id`; admin / underwriter / actuary / analyst / claims roles can
  read/write any customer.

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
  payments, journal, settlement, external-payer, marketplace-claim,
  remittance, payer-receivable, idempotency, and outbox repositories).
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
4. Keep startup behavior compatible with `python3 web_portal/server.py` unless
   the task explicitly changes the entrypoint.
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
- **Server:** `PORT`, `HOST`, `BASE_URL`
- **Test:** `PHINS_TEST_MODE`, `TEST_BASE_URL`
- **Ledger:** `ENABLE_LEDGER_PERSISTENCE`, `LEDGER_PERSISTENCE_VERBOSE`,
  `LEDGER_PERSISTENCE_LOG_INTERVAL`
- **Media:** `MEDIA_PROVIDER_WEBHOOK_SECRET`, `DEFAULT_MEDIA_SUBTITLE_PROVIDER`,
  `DEFAULT_MEDIA_VIDEO_PROVIDER`, `PHINS_MEDIA_INLINE_MAX_BYTES`
- **Auto-pay:** `PHINS_DEFAULT_AUTO_PAY_CARD_NUMBER`,
  `MONTHLY_AUTO_PAY_COMMAND_TOKEN`
- **Security:** `SESSION_SECRET_KEY`, `PHINS_ENCRYPTION_KEY`,
  `PHINS_ENFORCE_SECRET_POLICY`, `PHINS_EMERGENCY_UNLOCK_KEY`,
  `ALLOW_LEGACY_DEMO_PASSWORDS`
- **Integrations:** `PLAID_*`, `STRIPE_*`, `ACH_*`, `ALPACA_*`, `COINBASE_*`,
  `IB_*`, `WEBHOOK_BASE_URL`, `ALPHA_VANTAGE_API_KEY`

Operational notes:

- `web_portal/server.py` defaults `PORT` to `8000`
- when `PORT` is provided, `HOST` is set to `0.0.0.0`; otherwise local runs use
  `127.0.0.1`
- `Dockerfile` uses `python:3.12-slim`, healthcheck hits `/api/health`
- `render.yaml` includes a cron service `phins-monthly-auto-pay`

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
  `127.0.0.1` with `PortalHandler`; sets env defaults (`USE_DATABASE=false`,
  `USE_SQLITE=true`, `PHINS_TEST_MODE=true`, `SQLITE_PATH=<tmp>/phins_test.db`).
  Port is chosen via `_pick_test_port()`: `TEST_PORT` env > `8000` >
  kernel-assigned. `TEST_PORT` and `TEST_BASE_URL` are republished to the
  bound port, so tests should read them rather than hard-coding `8000`.
- **`tests/conftest.py`** only adds `sys.path` and sets `PHINS_TEST_MODE`; it
  does **not** start the server.
- `pytest_runtest_setup` resets in-memory portal state between cases:
  clears the dict stores (`POLICIES`, `CLAIMS`, `CUSTOMERS`,
  `UNDERWRITING_APPLICATIONS`, `SESSIONS`, `BILLING`, `HEALTH_WALLETS`,
  `MEDICAL_PURCHASES`, `INVESTMENT_ACCOUNTS`, `CUSTOMER_ALLOCATIONS`,
  `TRANSACTION_LEDGER`, `RATE_LIMIT`, `FAILED_LOGINS`, `BLOCKED_IPS`,
  `SUSPICIOUS_PATTERNS`) plus the per-port init tracker, and calls
  `reset_*` on options wheel, document processing, assessment center,
  accounting engine, firewall, and intrusion detector. `USERS` is **not**
  cleared.
- 114 test files under `tests/`, 11 root-level `test_*.py` files.

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
- `supplier_repository.py` bundles multiple repository classes (suppliers,
  invitations, offers, orders, documents, supply-chain ledger); changes there
  can have a wide blast radius. The same applies to
  `marketplace_repository.py`, which bundles wallet / payment / settlement /
  outbox repositories.
- The two `conftest.py` files (root vs `tests/`) serve different purposes;
  putting server setup in `tests/conftest.py` will not apply to root-level
  test files.
- Hard-coding `http://localhost:8000` in new tests is fragile — the embedded
  server may bind a different port under parallel pytest or when 8000 is
  busy. Read `TEST_BASE_URL` / `TEST_PORT` instead.

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

Last updated: June 8, 2026
