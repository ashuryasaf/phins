#!/usr/bin/env sh
# PHINS container entrypoint
# -----------------------------------------------------------------------------
# A single dispatcher used by every PaaS manifest so the entrypoint contract
# lives in ONE place. Used by:
#   - Dockerfile CMD              -> "serve"      (Railway, Docker)
#   - railway.json startCommand   -> "./scripts/entrypoint.sh serve"
#   - render.yaml web startCommand-> "./scripts/entrypoint.sh serve"
#   - render.yaml cron startCommand-> "./scripts/entrypoint.sh cron"
#
# Modes:
#   serve     - run the production web portal (default)
#   cron      - run the monthly auto-pay batch (Render cron, Railway cron)
#   db-init   - bootstrap the database (manual; NOT called automatically
#               from serve to avoid multi-replica race conditions and to
#               prevent default-admin credentials from being seeded into
#               a real production database by accident)
#   shell     - drop into /bin/sh inside the running image (debugging)
#   exec ...  - run an arbitrary command (e.g. ./scripts/entrypoint.sh exec
#               python3 some_script.py)
#
# Posix-only on purpose: this script must run under the minimal /bin/sh in
# python:3.12-slim. Avoid bashisms.
# -----------------------------------------------------------------------------

set -eu

mode="${1:-serve}"
if [ "$#" -gt 0 ]; then
    shift
fi

case "$mode" in
    serve)
        exec python3 web_portal/server.py "$@"
        ;;
    cron)
        exec python3 scripts/run_monthly_auto_pay.py "$@"
        ;;
    db-init)
        # Refuse to seed demo data if the deployment looks like production.
        # This is a safety net for risk R8 (default admin creds in prod).
        if [ "${PHINS_ENVIRONMENT:-}" = "production" ] && \
           [ "${POPULATE_DEMO_DATA:-true}" != "false" ]; then
            echo "entrypoint.sh: PHINS_ENVIRONMENT=production; forcing POPULATE_DEMO_DATA=false" >&2
            export POPULATE_DEMO_DATA=false
        fi
        exec python3 init_database.py "$@"
        ;;
    shell)
        exec /bin/sh
        ;;
    exec)
        exec "$@"
        ;;
    *)
        echo "entrypoint.sh: unknown mode '$mode'" >&2
        echo "Usage: $0 {serve|cron|db-init|shell|exec ...}" >&2
        exit 64
        ;;
esac
