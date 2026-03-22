#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"

exec python3 "${WORKSPACE_DIR}/scripts/create_full_platform_backup.py" "$@"

