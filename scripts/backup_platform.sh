#!/usr/bin/env bash
set -euo pipefail

# Platform backup script (code + docs + configs + optional DB dump).
#
# Produces:
#   /workspace/backups/<timestamp>/
#     - platform_snapshot.tar.gz
#     - db/ (optional: postgres/sqlite dump + structured export)
#     - metadata/ (git + system info)
#     - manifest.json
#     - SHA256SUMS

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
BACKUP_ROOT="${BACKUP_ROOT:-${WORKSPACE_DIR}/backups}"
TS="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${BACKUP_ROOT}/${TS}"
export TS

if [ -n "${SQLITE_PATH:-}" ] && [[ "${SQLITE_PATH}" != /* ]]; then
  SQLITE_PATH="${WORKSPACE_DIR}/${SQLITE_PATH}"
  export SQLITE_PATH
fi

mkdir -p "${OUT_DIR}/metadata" "${OUT_DIR}/db"

echo "Backup output: ${OUT_DIR}"

if command -v git >/dev/null 2>&1 && [ -d "${WORKSPACE_DIR}/.git" ]; then
  (
    cd "${WORKSPACE_DIR}"
    git rev-parse HEAD > "${OUT_DIR}/metadata/git_commit.txt" || true
    git status --porcelain=v1 > "${OUT_DIR}/metadata/git_status_porcelain.txt" || true
    git status > "${OUT_DIR}/metadata/git_status.txt" || true
    git log -n 20 --oneline > "${OUT_DIR}/metadata/git_log_20.txt" || true
    git diff > "${OUT_DIR}/metadata/git_diff_unstaged.patch" || true
    git diff --cached > "${OUT_DIR}/metadata/git_diff_staged.patch" || true
  )
fi

{
  echo "timestamp_utc=${TS}"
  echo "uname=$(uname -a)"
  echo "python3=$(python3 -V 2>/dev/null || true)"
  echo "java=$(java -version 2>&1 | head -n 1 || true)"
  echo "plantuml=$(plantuml -version 2>/dev/null || true)"
  echo "pg_dump=$(pg_dump --version 2>/dev/null || true)"
  echo "sqlite3=$(sqlite3 --version 2>/dev/null || true)"
} > "${OUT_DIR}/metadata/system_info.txt"

python3 - "${WORKSPACE_DIR}" "${OUT_DIR}/metadata/workspace_inventory.json" <<'PY'
import json
import os
import sys
from pathlib import Path

workspace_dir = Path(sys.argv[1]).resolve()
output_path = Path(sys.argv[2])
excluded = {
    ".git",
    "backups",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
}

inventory = []
for root, dirs, files in os.walk(workspace_dir):
    dirs[:] = [d for d in dirs if d not in excluded]
    root_path = Path(root)
    for filename in sorted(files):
        if filename.endswith((".pyc", ".pyo")):
            continue
        file_path = root_path / filename
        rel_path = file_path.relative_to(workspace_dir)
        try:
            stat = file_path.stat()
        except OSError:
            continue
        inventory.append(
            {
                "path": str(rel_path),
                "size_bytes": stat.st_size,
                "modified_utc": str(stat.st_mtime),
            }
        )

output_path.write_text(json.dumps({"generated_at": os.environ.get("TS", ""), "files": inventory}, indent=2) + "\n")
PY

# -------------------------
# Database backup (optional)
# -------------------------

DB_BACKUP_NOTES=()

if [ -n "${DATABASE_URL:-}" ]; then
  if command -v pg_dump >/dev/null 2>&1; then
    echo "Creating Postgres dump via pg_dump..."
    # Custom format: compressed, supports restore options.
    pg_dump --format=custom --no-owner --no-privileges --file "${OUT_DIR}/db/postgres.dump" "${DATABASE_URL}" \
      && echo "postgres.dump created" \
      || DB_BACKUP_NOTES+=("Postgres dump failed; check DATABASE_URL network/auth.")
  else
    DB_BACKUP_NOTES+=("DATABASE_URL set but pg_dump not available.")
  fi
else
  DB_BACKUP_NOTES+=("DATABASE_URL not set; skipping Postgres dump.")
fi

# SQLite: backup if SQLITE_PATH exists or if any *.db file exists under workspace root.
SQLITE_CANDIDATES=()
if [ -n "${SQLITE_PATH:-}" ]; then
  SQLITE_CANDIDATES+=("${SQLITE_PATH}")
fi
if [ -f "${WORKSPACE_DIR}/phins.db" ]; then
  SQLITE_CANDIDATES+=("${WORKSPACE_DIR}/phins.db")
fi

if [ "${#SQLITE_CANDIDATES[@]}" -gt 0 ]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    for sqlite_file in "${SQLITE_CANDIDATES[@]}"; do
      if [ -f "${sqlite_file}" ]; then
        base="$(basename "${sqlite_file}")"
        echo "Copying SQLite DB: ${sqlite_file}"
        cp -f "${sqlite_file}" "${OUT_DIR}/db/${base}"
        echo "Exporting SQLite SQL dump: ${sqlite_file}"
        sqlite3 "${sqlite_file}" ".dump" > "${OUT_DIR}/db/${base}.sql"
      else
        DB_BACKUP_NOTES+=("SQLite candidate not found: ${sqlite_file}")
      fi
    done
  else
    DB_BACKUP_NOTES+=("SQLite candidates found but sqlite3 not available.")
  fi
else
  DB_BACKUP_NOTES+=("No SQLITE_PATH/phins.db found; skipping SQLite backup.")
fi

echo "Creating structured database export manifest..."
if python3 - "${OUT_DIR}/db/structured_export" <<'PY'
import json
import sys

from database.backup_export import export_database_snapshot

manifest = export_database_snapshot(sys.argv[1])
print(json.dumps(manifest))
PY
then
  echo "Structured database export complete."
else
  DB_BACKUP_NOTES+=("Structured database export failed; review script output.")
fi

printf "%s\n" "${DB_BACKUP_NOTES[@]}" > "${OUT_DIR}/db/backup_notes.txt"

python3 - "${OUT_DIR}" <<'PY'
import json
import os
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])

manifest = {
    "backup_created_at_utc": out_dir.name,
    "paths": {
        "platform_snapshot": "platform_snapshot.tar.gz",
        "db": "db",
        "metadata": "metadata",
    },
    "db_artifacts": sorted(
        str(path.relative_to(out_dir))
        for path in out_dir.joinpath("db").rglob("*")
        if path.is_file()
    ),
    "metadata_artifacts": sorted(
        str(path.relative_to(out_dir))
        for path in out_dir.joinpath("metadata").rglob("*")
        if path.is_file()
    ),
}

out_dir.joinpath("manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

# -------------------------
# Platform snapshot archive
# -------------------------

echo "Creating platform snapshot archive..."

# Exclusions: git internals, backups output, caches, typical local artifacts.
tar \
  --exclude=".git" \
  --exclude="backups" \
  --exclude="**/__pycache__" \
  --exclude="**/*.pyc" \
  --exclude="**/.pytest_cache" \
  --exclude="**/node_modules" \
  --exclude="**/.venv" \
  --exclude="**/.env" \
  -czf "${OUT_DIR}/platform_snapshot.tar.gz" \
  -C "${WORKSPACE_DIR}" \
  .

(
  cd "${OUT_DIR}"
  sha256sum platform_snapshot.tar.gz manifest.json $(rg --files metadata db) > SHA256SUMS 2>/dev/null || true
)

echo "Backup complete."
echo "Archive: ${OUT_DIR}/platform_snapshot.tar.gz"
echo "DB dir : ${OUT_DIR}/db"
echo "Meta   : ${OUT_DIR}/metadata"

