# PHINS Cybersecurity Overview

This document is the single operator-facing reference for how the PHINS
platform defends itself against common attacks and preserves data integrity.
It complements the older, more historical notes in `SECURITY*.md` and is the
file to update first when the security posture changes.

## 1. Threat model (short)

| Attacker capability | Mitigation surface |
|---|---|
| External opportunistic scanner (bots scraping `.env`, `wp-admin`, etc.) | Input pattern detection, automatic IP block, silent-404 logging |
| Credential stuffing / brute force | Login lockout, rate limiting, strong password hashing |
| Stolen bearer token / replay | Short TTL, full-HMAC signatures, revocation registry, logout endpoint |
| XSS / clickjacking / framed UI | Security headers (CSP, X-Frame-Options, COOP/CORP, Referrer/Permissions policies) |
| SQL / command / path-traversal injection | Central `validate_input_security` + SQLAlchemy ORM + path normalization |
| Supply-chain / outbound-SSRF abuse | `security.network.validate_remote_url` + scheme/host allow-lists |
| Leaked static secrets | Startup secret audit refuses production boot on weak/default keys |
| Tenant cross-access | `authorize_customer_data`, strict role matrix, audit logging |
| Data tampering on write paths | Hash-chained platform ledger + Fernet vault for sensitive blobs |

## 2. Authentication

### 2.1 Token formats

Two token formats coexist:

| Format | Prefix | Signature | Revocable | Status |
|---|---|---|---|---|
| v2 (hardened) | `phins2_` | Full HMAC-SHA256 (32 B, URL-safe base64) | Yes – via `jti` registry | Default for new logins |
| v1 (legacy) | `phins_` | Truncated HMAC-SHA256 (64-bit) | No (TTL only) | Accepted until existing sessions expire |

v2 tokens are minted by `security.auth_tokens.create_token`. The payload is
JSON with `sub`, `role`, `cid`, `iat`, `exp`, `jti`, and `v` fields, signed
with the full 32-byte SHA-256 HMAC of the payload base64. Verification always
uses `hmac.compare_digest` and checks every registered signing key to support
zero-downtime rotation.

If `SESSION_SECRET_KEY` is unset or shorter than 32 bytes, v2 token minting
raises `TokenSecretError` and the login handler falls back to v1 while logging
a loud warning. The startup secret audit (see §6) catches this before it can
persist in production.

### 2.2 Revocation

`security.auth_tokens` maintains an in-memory registry keyed by `jti` with
each entry's absolute expiry. Entries are pruned lazily and bounded at 20 000
active revocations (oldest-expiry eviction).

Flows that revoke tokens:

- `POST /api/logout` (new endpoint): revokes the presented token.
- `POST /api/reset-password`: revokes every v2 `jti` associated with the user.
- `POST /api/change-password`: revokes every v2 `jti` for the user *except*
  the current one, so the actor remains logged in on their current device.
- Admin IP-block flows indirectly invalidate future logins via the lockout
  counter (not via token revocation).

### 2.3 Password storage

Passwords use PBKDF2-HMAC-SHA256 with 100 000 iterations and a 16-byte
per-password salt. Verification uses `secrets.compare_digest`.
`UserRepository.authenticate` was previously a tautology (`hash == hash`); it
now performs a constant-time comparison against the stored hash.

### 2.4 Lockout & rate limits

| Control | Default | Override env |
|---|---|---|
| Per-IP request rate | 300 req/min (60 in test) | — |
| Trusted-IP multiplier | 5× | Internal prefixes list in `server.py` |
| Bulk operation rate | 5/min | — |
| Failed-login lockout | 5 attempts → 15 min | — |
| Per-IP session cap | 10 | — |
| Request size cap | 10 MB | — |
| Session TTL | 1 hour | — |

## 3. HTTP security headers

All security headers are centralised in `security/headers.py`. The portal
handler emits three tiers:

- **JSON** (`_set_json_headers`): strict CSP with no `unsafe-inline`,
  `X-Frame-Options: DENY`, `Cache-Control: no-store`.
- **HTML** (`_set_file_headers` for `.html`): CSP that retains
  `'unsafe-inline'` for script/style (needed by legacy inline handlers) but
  adds `object-src 'none'`, `frame-ancestors 'self'`, and
  `upgrade-insecure-requests`.
- **Static assets** (`.css`, `.js`, media): minimal cross-origin isolation
  headers only.

Common to all tiers: HSTS, `Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy` that denies camera, microphone, geolocation, payment,
USB, MIDI, sensors, and sync-XHR, plus `Cross-Origin-Opener-Policy:
same-origin` and `Cross-Origin-Resource-Policy: same-origin`.

## 4. Input validation & injection protection

`validate_input_security` is invoked on every query string and on
security-relevant JSON fields (login username, registration, admin form
inputs). It detects:

- SQL injection heuristics
- Cross-site scripting payloads
- Path traversal
- Command injection
- Generic "malicious payload" patterns (Perl/Bash one-liners, webshell stubs)

Detections are logged via `log_malicious_attempt` and trigger automatic
`block_ip` with either a temporary or permanent block depending on severity.
The IP block list is cleared only by admin Bearer auth or – if configured –
by `PHINS_EMERGENCY_UNLOCK_KEY` (see §6).

SQL access uses SQLAlchemy ORM exclusively in `database/repositories/*`.
Raw-SQL `text()` is not used in repositories; static file paths are
canonicalised through `os.path.realpath` and compared to `ROOT` before being
served.

## 5. Outbound request safety

`security/network.py` wraps `urllib.urlopen` with `validate_remote_url` so
callers must declare an allow-list of schemes (defaults to `https`) and
optionally hosts before any outbound call. This blocks SSRF pivots against
internal metadata services and prevents accidental downgrade to `http`.

## 6. Secrets & configuration

### 6.1 Required in production

- `SESSION_SECRET_KEY` – ≥32 bytes. Used to sign v2 bearer tokens. Rotate by
  setting the new key as `SESSION_SECRET_KEY` and the previous key(s) in
  `SESSION_SECRET_KEYS_PREVIOUS` (comma-separated) for the rotation window.
- `PHINS_ENCRYPTION_KEY` – Fernet key for the vault (`security/vault.py`).
- `PHINS_ADMIN_PASSWORD`, `PHINS_*_PASSWORD` – per-role admin passwords.
  Leave unset to emit random passwords (login-disabled by default).

### 6.2 Optional

- `PHINS_EMERGENCY_UNLOCK_KEY` – pre-shared key for
  `/api/security/clear-blocks`. The historical default literal
  `phins-emergency-unlock-2026` is **rejected** at both runtime and startup
  audit. The key must be ≥32 bytes and is compared in constant time.
- `SESSION_SECRET_KEYS_PREVIOUS` – comma-separated list of retired signing
  keys accepted for verification during rotation.
- `ALLOW_LEGACY_DEMO_PASSWORDS` – enables short demo passwords
  (`admin123`, …). Startup audit flags this as an error in production.
- `PHINS_ENFORCE_SECRET_POLICY` – enforcement override. Production now
  **fails closed by default**: if the audit finds any error in production,
  startup aborts with exit code 2. Set this to a falsy value
  (`false`/`0`/`no`/`off`) as a deliberate escape hatch to continue despite
  violations (NOT recommended). A truthy value is now redundant but still
  honored. The override has no effect outside production.

### 6.3 Startup secret audit

`security/secrets_policy.py:audit_environment_secrets` runs at server
startup (`run_server`) and logs its findings. In production
(`ENVIRONMENT=production`, any `RAILWAY_ENVIRONMENT`, or `RENDER=1`):

- Missing/short `SESSION_SECRET_KEY` is an error.
- Known-insecure defaults (`admin`, `admin123`, `phins-emergency-unlock-2026`,
  `change-me`, …) are errors.
- `ALLOW_LEGACY_DEMO_PASSWORDS=true` is an error.

**Missing `SESSION_SECRET_KEY` (secure auto-provision):**

- If `SESSION_SECRET_KEY` is *not set*, startup provisions a strong random key
  for the process (`security/secrets_policy.py:ensure_session_secret_key`) and
  logs a `[SECURITY][WARN]`. Auth then signs with a strong key instead of
  degrading to legacy v1 tokens, and a deploy that simply hasn't populated the
  env var still boots. The key is process-local, so **set a stable
  `SESSION_SECRET_KEY`** for durable sessions that survive restarts and are
  valid across replicas.

**Behaviour on error (production) — explicitly insecure config:**

- Default (fail-closed): when a secret is *explicitly set to an insecure value*
  (weak/known-default/short key, weak `PHINS_EMERGENCY_UNLOCK_KEY` /
  `PHINS_ADMIN_PASSWORD`, or `ALLOW_LEGACY_DEMO_PASSWORDS=true` in production),
  abort startup with exit code 2, logging the violations and override
  instructions. A service can never come up knowingly insecure.
- With `PHINS_ENFORCE_SECRET_POLICY=false`: emit `[SECURITY][WARN]` log lines
  and continue despite violations. This is the deliberate, documented escape
  hatch; remove it as soon as the configuration is corrected.

In test/dev mode these conditions downgrade to warnings regardless of the
enforce flag so the suite still runs on developer machines.

## 7. Data integrity

- `services/platform_event_ledger_service.py` hash-chains every ledger entry
  (`entry_hash`, `previous_hash`). Tampering with any record invalidates the
  chain from that point forward.
- `services/audit_service.py` bridges portal audit events into the ledger
  and keeps an in-memory ring buffer for fast admin queries.
- `services/data_integrity_service.py` and
  `services/advanced_portfolio_integrity_service.py` provide cryptographic
  reconciliation for savings/wallet state.
- `security/vault.py` wraps sensitive datasets (actuarial tables, regulated
  config) with Fernet (AES-128 + HMAC) when `PHINS_ENCRYPTION_KEY` is set,
  and with a plain JSON blob otherwise (explicitly marked `scheme="plain"`).

## 8. Monitoring & response

- `MALICIOUS_ATTEMPTS`, `BLOCKED_IPS`, `FAILED_LOGINS`, and
  `SUSPICIOUS_PATTERNS` expose counts via `/api/security/*` endpoints for
  admin dashboards.
- `/api/audit` streams the audit ring + ledger for admin review.
- Railway log noise from bot-scan 404s is suppressed by
  `_is_bot_probe_path` so genuine security signal is not buried.

### Runbook: incident of suspected token leak

1. Rotate `SESSION_SECRET_KEY` (add the old key to
   `SESSION_SECRET_KEYS_PREVIOUS` for the rotation window).
2. Redeploy. All v2 tokens minted with the leaked key stop validating.
3. If leaving the old key active during rotation, force-logout affected
   users via `/api/reset-password` for each account or admin "clear blocks"
   tooling (which also drops server-side SESSIONS entries).
4. Review `/api/audit` for anomalous activity since the suspected leak
   window.

### Runbook: IP flood / DoS

1. Verify that `MAX_REQUESTS_PER_MINUTE` limits are firing via
   `/api/security/status`.
2. If legitimate traffic is impacted, temporarily lift by raising
   `MAX_REQUESTS_PER_MINUTE` via code + redeploy (no env override exists
   today).
3. For persistent abuse, consider a reverse-proxy WAF (Cloudflare,
   Railway Shield) upstream.

## 9. Test coverage

`tests/test_security_hardening.py` exercises:

- v2 token round-trip, expiry, tamper, signature-length, revocation, and
  key-rotation behaviour.
- Missing/short signing secret rejection.
- Legacy v1 verifier wiring.
- Secrets policy refusals (missing key, known-insecure defaults,
  `ALLOW_LEGACY_DEMO_PASSWORDS` in production).
- Security headers completeness and CSP correctness.
- `UserRepository.authenticate` hash matching.

Related existing coverage:

- `tests/test_security_performance.py` – rate limit and malicious-pattern
  lockouts.
- `tests/test_claims_dashboard_security_integrity.py` – role-based access.
- `tests/test_customer_data_isolation.py` – cross-tenant access guard.
- `tests/test_head_semantics_security.py` – HEAD method must enforce
  security checks (two pre-existing failures on `main` tracked separately).
- `tests/test_persistence_log_noise.py` – bot-scan log suppression.

## 10. Outstanding items

Tracked here so the security posture doesn't regress:

- Migrate inline scripts out of legacy HTML templates so the HTML CSP can
  drop `'unsafe-inline'`.
- Add TOTP / WebAuthn second factor to `/api/login` for admin roles.
- Replace in-memory revocation / lockout / rate-limit stores with a shared
  Redis/DB backend for multi-instance deploys. Today each Railway replica
  has its own view; tokens revoked on replica A can still validate on B
  until the leaked `jti` naturally expires (≤ 1 hour).
- Sign or MAC the persistent ledger snapshot file at
  `LEDGER_PERSISTENCE_FILE` so tampering is detected on restore.
- `get_customer_id_guaranteed` still auto-generates a `customer_id` in
  layer 5; revisit to prefer hard failure over synthetic-customer creation.
