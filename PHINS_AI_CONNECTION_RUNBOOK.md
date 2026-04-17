# www.phins.ai Connectivity Runbook

Use this document when `https://www.phins.ai` is unreachable or returning
unexpected errors.

## 1. Run the connectivity check

```bash
python3 scripts/check_phins_ai_connection.py
```

The script reports DNS, HTTP `/api/health`, HTTP `/`, and a verdict with
remediation steps. Non-zero exit codes:

| Exit code | Meaning |
|-----------|---------|
| 0 | Site reachable and healthy |
| 1 | Site reachable but returned an unexpected status |
| 2 | Site not reachable (timeout, TLS, or origin `Application not found`) |
| 3 | DNS resolution failed |

To see a machine-readable report: `python3 scripts/check_phins_ai_connection.py --json`.

## 2. Interpreting results

### 2.1 DNS fails (exit 3)

- Verify the domain is still registered and the nameservers are correct.
- Confirm the CNAME for `www.phins.ai` still points at the Railway app
 target (previously `umlnri93.up.railway.app`).

### 2.2 Railway edge returns `Application not found` (exit 2)

This comes from Railway's edge itself and means there is **no running
service behind the custom domain**. The hosting side is at fault, not
the code. Remediation, from the Railway dashboard:

1. Open the PHINS project.
2. Check the web service status:
 - If it exists, open the most recent deployment, inspect its logs,
 and **Redeploy**.
 - If it was deleted, create a new service from this repo
 (Dockerfile build) and re-add the `www.phins.ai` custom domain.
3. Confirm the web service has the environment variables listed in
 `RAILWAY_POSTGRES_FIX.md` (`DATABASE_URL`, `USE_DATABASE`, etc.).
4. Re-run `python3 scripts/check_phins_ai_connection.py` to verify.

### 2.3 TLS completes but request times out (exit 2)

The upstream proxy is accepting TLS but no backend is answering HTTP.
This is typically a crashed container. Same remediation as 2.2 — check
deploy logs and redeploy.

### 2.4 5xx or unexpected status (exit 1)

The container is running but failing. Run the database-focused
diagnostic from the host (or from the public URL when it is partially
reachable):

```bash
python3 check_database_connection.py
curl -sS https://www.phins.ai/api/diagnostics/db-test
curl -sS https://www.phins.ai/api/diagnostics/env-check
```

## 3. Local verification

Before deploying a fix, make sure the server still starts cleanly:

```bash
python3 web_portal/server.py --test
PORT=8765 python3 web_portal/server.py &
curl -sS http://127.0.0.1:8765/api/health
```

The `/api/health` response should be JSON with `"status": "healthy"`.

## 4. Related documents

- `RAILWAY_POSTGRES_FIX.md` — fixing the PostgreSQL sidecar when the web
 service is up but the database is down.
- `DOMAIN_SETUP.md` — DNS and custom-domain configuration.
- `DEPLOYMENT.md` — general deployment overview.
