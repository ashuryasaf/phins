# AGENTS.md - PHINS Agent Playbook

Use this file as concise, repo-specific guidance for PHINS contributions.
Keep changes narrow, follow existing patterns, and let direct user instructions
override this document.

## 1) Quick Mental Model

PHINS is a Python platform built around:

- a large `BaseHTTPRequestHandler` app in `web_portal/server.py` (~47.9k lines)
- extension routing modules under `web_portal/`:
  - `api_extensions.py` (~3.2k lines) — community foundations, OTP/CAPTCHA,
    contribution payments, wallet, admin foundation routes, backup/persistence,
    invitations, and video agents
  - `api_assessment_center.py` — customer 360 / assessment center export hooks
  - `api_bi_analytics.py` and `api_delivery_bidding.py` — domain handler
    modules that exist on disk but are **not currently wired** into
    `server.py`'s dispatcher; treat them as scaffolding/reference until wired
- service-layer logic in `services/` (74 modules)
- database access in `database/` (incl. health-marketplace foundation models)
- security utilities in `security/`
- scheduled tasks in `scheduler/`
- operational scripts in `scripts/` (including `entrypoint.sh`, the single
  PaaS dispatcher)
- both `tests/test_*.py` (107 files) and root-level `test_*.py` (11 files)

Runtime defaults are important:

- `web_portal/server.py` defaults to `USE_DATABASE=true`
- pytest config in root `conftest.py` sets `USE_DATABASE=false`,
  `USE_SQLITE=true`, `PHINS_TEST_MODE=true`, picks a test port (defaults to
  `8000`, honors `TEST_PORT`, falls back to a kernel-assigned port if `8000`
  is busy), and starts an embedded `ThreadingHTTPServer` with `PortalHandler`
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
| Community foundations / OTP / video agents | `web_portal/api_extensions.py`, `services/video_agents_service.py` |
| Assessment center / customer 360 | `web_portal/api_assessment_center.py`, `services/assessment_center_service.py` |
| BI/analytics handlers (reference) | `web_portal/api_bi_analytics.py`, `services/bi_analytics_service.py` |
| Delivery/bidding handlers (reference) | `web_portal/api_delivery_bidding.py`, `services/delivery_bidding_service.py` |
| Business rule/workflow | `services/`, then the route or engine that calls it |
| Database/schema/repository | `database/models.py`, `database/manager.py`, `database/repositories/`, `database/config.py` |
| Health-marketplace foundation | `database/marketplace_models.py`, `database/repositories/marketplace_repository.py`, `docs/health_marketplace_*.md` |
| Billing/accounting behavior | `billing_engine.py`, `accounting_engine.py`, related tests |
| Security/auth/tokens | `security/`, `web_portal/server.py` (session/login routes) |
| Scheduled jobs | `scheduler/runner.py`, `scripts/run_monthly_auto_pay.py` |
| Test harness/debugging | root `conftest.py`, affected `tests/test_*.py`, root `test_*.py` |
| Deployment/config | `DEPLOYMENT.md`, `RAILWAY_*.md`, `railway.json`, `render.yaml`, `Dockerfile`, `scripts/entrypoint.sh` |

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
|  |- server.py                         # ~47.9k lines, BaseHTTPRequestHandler
|  |- api_extensions.py                 # ~3.2k lines, conditional dispatcher
|  |- api_assessment_center.py          # assessment center export hooks
|  |- api_bi_analytics.py               # NOT wired into server.py
|  |- api_delivery_bidding.py           # NOT wired into server.py
|  |- connectors.py
|  `- static/                           # ~117 HTML/JS/CSS dashboards & assets
|- services/                            # 74 service modules
|- database/
|  |- config.py
|  |- manager.py
|  |- models.py
|  |- marketplace_models.py             # health-marketplace foundation models
|  |- data_access.py
|  |- seeds.py
|  |- notification_models.py
|  |- migrate_data.py
|  |- migrations/                       # add_notification_tables.py, ...
|  `- repositories/                     # 14 *_repository.py + base.py
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
|  |- entrypoint.sh                     # serve | cron | db-init | shell | exec
|  |- run_monthly_auto_pay.py
|  |- reset_customer_asaf.py
|  |- test_asaf_welcome_notification.py
|  |- trading_cli.py
|  `- validate_premium_pricing.py
|- tests/                               # 107 test files
|- docs/
|  |- platform_data_architecture.md
|  |- health_marketplace_architecture.md
|  |- health_marketplace_implementation_spec.md
|  `- uml/                              # .puml sources + rendered/
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

`DatabaseManager` repositories (as properties, 19 total):

- Core: `customers`, `policies`, `claims`, `underwriting`, `billing`
- Auth/audit: `users`, `sessions`, `audit`, `tokens`
- Platform: `platform_ledger`, `actuarial`
- Documents: `documents`, `processing_jobs`
- Supply chain: `suppliers`, `supplier_invitations`, `supplier_offers`,
  `supplier_orders`, `supplier_documents`, `supply_chain_ledger`
- Health marketplace: `marketplace_claims`

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
   `web_portal/api_extensions.py`, or `web_portal/api_assessment_center.py`.
   `api_bi_analytics.py` and `api_delivery_bidding.py` exist but are not
   currently dispatched from `server.py`; do not assume their handlers run
   without first wiring them in.
3. Verify the extension is actually wired; `server.py` imports
   `api_extensions` and `api_assessment_center` conditionally and can run
   without them (`api_extensions_enabled` flag).
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
- `api_extensions.py` covers community foundations, OTP/CAPTCHA, contribution
  payments, community messaging, wallet, admin foundation routes,
  backup/persistence, invitations, and video-agents integration.

## 6) Database Task Playbook

When changing persistence or schema behavior:

1. Inspect `database/models.py`, `database/manager.py`, and the relevant
   repository in `database/repositories/`.
2. Update related models, repositories, and dict-compatibility code together if
   the schema affects both DB and in-memory flows.
3. Review `database/seeds.py`, initialization, and migration helpers
   (`database/migrate_data.py`, `database/migrations/`) when schema changes.
4. Check `database/notification_models.py` if notification-related tables are
   involved, and `database/marketplace_models.py` for health-marketplace tables.
5. Preserve compatibility with the in-memory fallback unless the task explicitly
   removes it.
6. Run database-focused tests plus at least one broader workflow check.

Key facts:

- Storage modes include in-memory, SQLite, and PostgreSQL.
- `DatabaseManager` exposes 19 repository properties (see §4 for the full list).
- Repository modules (14 `*_repository.py` + `base.py`):
  `customer_repository.py`, `policy_repository.py`, `claim_repository.py`,
  `underwriting_repository.py`, `billing_repository.py`,
  `user_repository.py`, `session_repository.py`, `audit_repository.py`,
  `platform_ledger_repository.py`, `actuarial_repository.py`,
  `token_repository.py`, `document_repository.py`,
  `marketplace_repository.py`, `supplier_repository.py`
  (the supplier module bundles supplier, invitation, offer, order, document,
  and supply-chain ledger repositories).
- Connection handling includes recovery logic; avoid bypassing existing session
  patterns without a clear reason.

## 7) Deployment Task Playbook

When working on deployment or environment configuration:

1. Read `DEPLOYMENT.md` and any relevant `RAILWAY_*.md` file first.
2. Verify the actual deployment files before editing assumptions:
   - `railway.json`
   - `render.yaml`
   - `Dockerfile` (multi-stage: wheel builder + `python:3.12-slim` runtime)
   - `app.json`, `vercel.json`
   - `scripts/entrypoint.sh` — the **single** dispatcher referenced by
     Dockerfile CMD, `railway.json`, and `render.yaml`. Modes:
     `serve` (default), `cron`, `db-init`, `shell`, `exec`.
3. Confirm how the app starts in production before changing commands or ports.
4. Keep startup behavior compatible with `./scripts/entrypoint.sh serve`
   (which exec's `python3 web_portal/server.py`) unless the task explicitly
   changes the entrypoint contract.
5. Document any environment-variable or operator-facing changes.

Railway-specific docs (6 files):
`RAILWAY_DEPLOYMENT.md`, `RAILWAY_QUICKSTART.md`,
`RAILWAY_POSTGRES_SETUP.md`, `RAILWAY_POSTGRES_FIX.md`,
`RAILWAY_DEPLOYMENT_COMPLETE.md`, `RAILWAY_REDEPLOY_REQUIRED.md`

Additional deployment docs:
`DEPLOYMENT_CHECKLIST.md`, `DEPLOYMENT_VALIDATION.md`,
`DEPLOYMENT_READY_REPORT.md`

Environment variables commonly used (see `.env.example` for the full list):

- **Database:** `USE_DATABASE`, `DATABASE_URL`, `DATABASE_PUBLIC_URL`,
  `USE_SQLITE`, `SQLITE_PATH`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
  `DB_PASSWORD`
- **Server / env:** `PORT`, `HOST`, `BASE_URL`, `ENVIRONMENT`,
  `PHINS_ENVIRONMENT`, `LOG_LEVEL`, `DEBUG`
- **Test:** `PHINS_TEST_MODE`, `TEST_BASE_URL`, `TEST_PORT`
- **Files / uploads:** `PHINS_UPLOAD_DIR`
- **Ledger:** `ENABLE_LEDGER_PERSISTENCE`, `LEDGER_PERSISTENCE_VERBOSE`,
  `LEDGER_PERSISTENCE_LOG_INTERVAL`
- **Media / video agents:** `MEDIA_PROVIDER_WEBHOOK_SECRET`,
  `DEFAULT_MEDIA_SUBTITLE_PROVIDER`, `DEFAULT_MEDIA_VIDEO_PROVIDER`,
  `PHINS_MEDIA_INLINE_MAX_BYTES`, `GEMINI_API_KEY`,
  `PHINS_GEMINI_VIDEO_MODEL`, `KLING_API_KEY`, `KLING_ACCESS_KEY`,
  `KLING_SECRET_KEY`, `KLING_API_BASE_URL`
- **Auto-pay / cron:** `PHINS_DEFAULT_AUTO_PAY_CARD_NUMBER`,
  `MONTHLY_AUTO_PAY_COMMAND_TOKEN`, `POPULATE_DEMO_DATA`
- **Security:** `SESSION_SECRET_KEY`, `PHINS_ENCRYPTION_KEY`,
  `PHINS_ENFORCE_SECRET_POLICY`, `PHINS_EMERGENCY_UNLOCK_KEY`,
  `ALLOW_LEGACY_DEMO_PASSWORDS`, `WEBHOOK_SIGNING_SECRET`,
  `NOTIFICATION_SIGNING_SECRET`
- **Role / demo passwords:** `PHINS_ADMIN_PASSWORD`,
  `PHINS_UNDERWRITER_PASSWORD`, `PHINS_CLAIMS_PASSWORD`,
  `PHINS_ACCOUNTANT_PASSWORD`, `PHINS_ACTUARY_PASSWORD`,
  `PHINS_SUPPLIER_PASSWORD`, `PHINS_MEDIA_PASSWORD`,
  `PHINS_DEFAULT_CUSTOMER_PASSWORD`, `PHINS_TEST_CUSTOMER_PASSWORD`
- **Email/SMS/notifications:** `EMAIL_PROVIDER`, `SMTP_*`, `SENDGRID_API_KEY`,
  `AWS_SES_REGION`, `MAILGUN_*`, `RESEND_API_KEY`, `SMS_PROVIDER`,
  `TWILIO_*`, `AWS_SNS_REGION`, `VONAGE_*`, `MESSAGEBIRD_API_KEY`,
  `OTP_*`, `RATE_LIMIT_*`, `NOTIFICATION_QUEUE_*`,
  `NOTIFICATION_AUDIT_*`, `ACTIVE_NOTIFICATIONS_*`
- **Integrations:** `PLAID_*`, `STRIPE_*`, `ACH_*`, `ALPACA_*`, `COINBASE_*`,
  `IB_*`, `WEBHOOK_BASE_URL`, `ALPHA_VANTAGE_API_KEY`

Operational notes:

- `web_portal/server.py` defaults `PORT` to `8000`
- when `PORT` is provided, `HOST` is set to `0.0.0.0`; otherwise local runs use
  `127.0.0.1`
- `Dockerfile` is a multi-stage build (wheel builder → `python:3.12-slim`
  runtime); healthcheck hits `/api/health`; CMD invokes
  `scripts/entrypoint.sh serve`
- `render.yaml` includes a cron service `phins-monthly-auto-pay` that runs
  `./scripts/entrypoint.sh cron`
- `scripts/entrypoint.sh db-init` refuses to seed demo data when
  `PHINS_ENVIRONMENT=production` (force-sets `POPULATE_DEMO_DATA=false`)

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

- **Root `conftest.py`** starts an embedded `ThreadingHTTPServer` with
  `PortalHandler`; picks a port via `_pick_test_port()` (honors `TEST_PORT`,
  defaults to `8000`, falls back to a kernel-assigned port if `8000` is busy);
  publishes the bound port back to `TEST_PORT` and `TEST_BASE_URL`. Env
  defaults: `USE_DATABASE=false`, `USE_SQLITE=true`,
  `SQLITE_PATH=<tmp>/phins_test.db`, `PHINS_TEST_MODE=true`.
- **`tests/conftest.py`** only adds `sys.path` and sets `PHINS_TEST_MODE`; it
  does **not** start the server.
- Per-test state resets (see `pytest_runtest_setup` in root `conftest.py`):
  - clears in-memory dicts (`POLICIES`, `CLAIMS`, `CUSTOMERS`,
    `UNDERWRITING_APPLICATIONS`, `SESSIONS`, `BILLING`, `HEALTH_WALLETS`,
    `MEDICAL_PURCHASES`, `INVESTMENT_ACCOUNTS`, `CUSTOMER_ALLOCATIONS`,
    `TRANSACTION_LEDGER`, `RATE_LIMIT`, `FAILED_LOGINS`, `BLOCKED_IPS`,
    `SUSPICIOUS_PATTERNS`) — but **not** `USERS`
  - resets `_TEST_PORTS_INITIALIZED`, options wheel, document processing,
    assessment center, accounting engine, firewall, and intrusion detector
- 107 test files under `tests/`, 11 root-level `test_*.py` files.

Docs-only changes usually do not need tests, but they do require verifying that
referenced files, commands, paths, and ports still exist.

## 9) Common Pitfalls

- Fixing only the database path can leave in-memory HTTP flows inconsistent; if
  a feature exists in both modes, check both code paths before finishing.
- Repository or schema changes can require matching updates in seeds,
  initialization, or migration helpers.
- Route changes may need updates in `web_portal/server.py` **and** one or more
  of the API extension modules; verify actual wiring rather than assuming.
  `api_bi_analytics.py` and `api_delivery_bidding.py` are currently
  unreferenced from `server.py`.
- Handler initialization, port assumptions, or shared module state can break many
  tests because pytest starts a real embedded `PortalHandler` server.
- `supplier_repository.py` bundles multiple repository classes (suppliers,
  invitations, offers, orders, documents, supply-chain ledger); changes there
  can have a wide blast radius.
- The two `conftest.py` files (root vs `tests/`) serve different purposes;
  putting server setup in `tests/conftest.py` will not apply to root-level
  test files.
- Changing the deployment entrypoint requires updating `scripts/entrypoint.sh`
  rather than only one PaaS manifest, because `Dockerfile`, `railway.json`,
  and `render.yaml` all dispatch through it.

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

Last updated: May 18, 2026
