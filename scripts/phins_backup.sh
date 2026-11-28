#!/usr/bin/env bash
set -euo pipefail

# PHINS backup/restore helper
#
# Supports:
# - PostgreSQL via pg_dump/pg_restore (DATABASE_URL or DB_* envs)
# - SQLite via sqlite3 .backup (SQLITE_PATH / USE_SQLITE / default phins.db)
#
# Output is a timestamped folder with:
# - manifest.json
# - db/ (postgres.dump or sqlite.db)
# - files/app_files.tar.gz (optional but useful for offline restores)

usage() {
  cat <<'EOF'
Usage:
  scripts/phins_backup.sh backup  [--out backups] [--no-files]
  scripts/phins_backup.sh restore --from <backup_dir>

Environment (database detection):
  - DATABASE_URL=postgresql://... or postgres://...   (Postgres)
  - or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD   (Postgres)
  - or USE_SQLITE=1 and/or SQLITE_PATH=path/to.db    (SQLite)

Examples:
  # Backup (auto-detect DB type)
  ./scripts/phins_backup.sh backup

  # Backup into a custom folder
  ./scripts/phins_backup.sh backup --out /var/backups/phins

  # Restore from a specific backup directory
  ./scripts/phins_backup.sh restore --from backups/phins_20251227_153012

Notes:
  - For Postgres restores you typically want DATABASE_URL set to the target database.
  - For SQLite restores you typically want SQLITE_PATH set (or default phins.db in repo root).
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

ts_now() {
  date +"%Y%m%d_%H%M%S"
}

repo_root() {
  # script is scripts/phins_backup.sh
  local d
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  echo "$d"
}

normalize_database_url() {
  # Railway/Heroku sometimes provides postgres://, SQLAlchemy prefers postgresql://
  local url="${1:-}"
  if [[ "$url" == postgres://* ]]; then
    echo "postgresql://${url#postgres://}"
  else
    echo "$url"
  fi
}

detect_db_kind() {
  # returns: postgres | sqlite | none
  local root db_url use_sqlite sqlite_path
  root="$(repo_root)"

  db_url="$(normalize_database_url "${DATABASE_URL:-}")"
  use_sqlite="${USE_SQLITE:-}"
  sqlite_path="${SQLITE_PATH:-}"

  if [[ -n "$db_url" ]] && [[ "$db_url" == postgresql://* ]]; then
    echo "postgres"
    return 0
  fi

  if [[ -n "${DB_HOST:-}" ]]; then
    echo "postgres"
    return 0
  fi

  if [[ "${use_sqlite,,}" == "true" || "${use_sqlite}" == "1" || "${use_sqlite,,}" == "yes" ]]; then
    echo "sqlite"
    return 0
  fi

  if [[ -n "$sqlite_path" ]]; then
    echo "sqlite"
    return 0
  fi

  if [[ -f "${root}/phins.db" ]]; then
    echo "sqlite"
    return 0
  fi

  echo "none"
}

postgres_conn() {
  # Prefer DATABASE_URL; else assemble from DB_* variables
  local url host port name user pass
  url="$(normalize_database_url "${DATABASE_URL:-}")"
  if [[ -n "$url" ]]; then
    echo "$url"
    return 0
  fi

  host="${DB_HOST:-}"; port="${DB_PORT:-5432}"; name="${DB_NAME:-phins}"; user="${DB_USER:-postgres}"; pass="${DB_PASSWORD:-}"
  [[ -n "$host" ]] || die "DB_HOST not set and DATABASE_URL not set"
  # Embed password (can be empty). Users may prefer PG* envs; this keeps it simple.
  echo "postgresql://${user}:${pass}@${host}:${port}/${name}"
}

sqlite_path_resolve() {
  local root path
  root="$(repo_root)"
  path="${SQLITE_PATH:-}"
  if [[ -n "$path" ]]; then
    echo "$path"
    return 0
  fi
  echo "${root}/phins.db"
}

write_manifest() {
  local out_dir db_kind
  out_dir="$1"
  db_kind="$2"
  local root commit host now
  root="$(repo_root)"
  host="$(hostname 2>/dev/null || echo "unknown")"
  now="$(date -Is)"
  commit="unknown"
  if have git; then
    commit="$(git -C "$root" rev-parse HEAD 2>/dev/null || echo "unknown")"
  fi

  cat > "${out_dir}/manifest.json" <<EOF
{
  "created_at": "${now}",
  "host": "${host}",
  "repo_root": "${root}",
  "git_commit": "${commit}",
  "db_kind": "${db_kind}",
  "env_hints": {
    "DATABASE_URL_set": $( [[ -n "${DATABASE_URL:-}" ]] && echo "true" || echo "false" ),
    "DB_HOST_set": $( [[ -n "${DB_HOST:-}" ]] && echo "true" || echo "false" ),
    "USE_SQLITE": "${USE_SQLITE:-}",
    "SQLITE_PATH": "${SQLITE_PATH:-}"
  }
}
EOF
}

backup_postgres() {
  local out_dir conn
  out_dir="$1"
  conn="$(postgres_conn)"

  have pg_dump || die "pg_dump not found. Install PostgreSQL client tools (pg_dump/pg_restore) and retry."

  mkdir -p "${out_dir}/db"
  # Custom format is best for restores (pg_restore --clean, etc).
  pg_dump --format=custom --file "${out_dir}/db/postgres.dump" "$conn"
}

restore_postgres() {
  local from_dir conn dump
  from_dir="$1"
  conn="$(postgres_conn)"
  dump="${from_dir}/db/postgres.dump"
  [[ -f "$dump" ]] || die "Expected Postgres dump not found: $dump"

  have pg_restore || die "pg_restore not found. Install PostgreSQL client tools and retry."

  # --clean drops objects before recreating. --if-exists avoids errors if missing.
  # --no-owner helps restore across different DB users.
  pg_restore --clean --if-exists --no-owner --dbname "$conn" "$dump"
}

backup_sqlite() {
  local out_dir db
  out_dir="$1"
  db="$(sqlite_path_resolve)"
  [[ -f "$db" ]] || die "SQLite DB file not found at: $db (set SQLITE_PATH or create phins.db)"

  mkdir -p "${out_dir}/db"

  if have sqlite3; then
    # Safe, consistent backup regardless of WAL state
    sqlite3 "$db" ".backup '${out_dir}/db/sqlite.db'"
    sqlite3 "${out_dir}/db/sqlite.db" "PRAGMA integrity_check;" >/dev/null || die "SQLite integrity_check failed on backup"
  else
    # Fallback: copy file (may be inconsistent if there is concurrent writing)
    cp -f "$db" "${out_dir}/db/sqlite.db"
  fi

  # Capture WAL/SHM if present (helpful if user is using WAL mode + copy fallback)
  [[ -f "${db}-wal" ]] && cp -f "${db}-wal" "${out_dir}/db/sqlite.db-wal" || true
  [[ -f "${db}-shm" ]] && cp -f "${db}-shm" "${out_dir}/db/sqlite.db-shm" || true
}

restore_sqlite() {
  local from_dir target src
  from_dir="$1"
  target="$(sqlite_path_resolve)"
  src="${from_dir}/db/sqlite.db"
  [[ -f "$src" ]] || die "Expected SQLite backup not found: $src"

  mkdir -p "$(dirname "$target")" 2>/dev/null || true
  cp -f "$src" "$target"
}

backup_files() {
  local out_dir root
  out_dir="$1"
  root="$(repo_root)"

  mkdir -p "${out_dir}/files"

  # We back up "operationally relevant" files; code is already in git,
  # but this tarball is useful for offline restores or air-gapped ops.
  #
  # Excludes: .git, caches, venvs, large binaries (pdfs) by default.
  tar -czf "${out_dir}/files/app_files.tar.gz" \
    --directory "$root" \
    --exclude=".git" \
    --exclude="__pycache__" \
    --exclude="**/__pycache__" \
    --exclude=".venv" \
    --exclude="venv" \
    --exclude="backups" \
    --exclude="**/*.pdf" \
    --exclude="server.log" \
    database services security web_portal scripts *.py *.md Dockerfile railway.json 2>/dev/null || true
}

backup_cmd() {
  local out_base="backups" include_files="true"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --out) out_base="$2"; shift 2;;
      --no-files) include_files="false"; shift;;
      -h|--help) usage; exit 0;;
      *) die "Unknown argument: $1";;
    esac
  done

  local root out_dir db_kind
  root="$(repo_root)"
  mkdir -p "$out_base"
  out_dir="${out_base%/}/phins_$(ts_now)"

  db_kind="$(detect_db_kind)"
  mkdir -p "$out_dir"
  write_manifest "$out_dir" "$db_kind"

  case "$db_kind" in
    postgres) backup_postgres "$out_dir";;
    sqlite) backup_sqlite "$out_dir";;
    none) echo "WARN: No database configuration detected; creating file-only backup." >&2;;
    *) die "Unknown db kind: $db_kind";;
  esac

  if [[ "$include_files" == "true" ]]; then
    backup_files "$out_dir"
  fi

  # Checksums (best-effort) — computed in Python for portability
  if have python3; then
    python3 - "$out_dir" <<'PY' 2>/dev/null || true
import hashlib
import os
import sys

root = sys.argv[1]
paths: list[str] = []
for dirpath, _dirnames, filenames in os.walk(root):
    for name in filenames:
        if name == "SHA256SUMS.txt":
            continue
        full = os.path.join(dirpath, name)
        rel = os.path.relpath(full, root)
        paths.append(rel)

paths.sort()

out_path = os.path.join(root, "SHA256SUMS.txt")
with open(out_path, "w", encoding="utf-8") as f:
    for rel in paths:
        full = os.path.join(root, rel)
        h = hashlib.sha256()
        with open(full, "rb") as rf:
            for chunk in iter(lambda: rf.read(1024 * 1024), b""):
                h.update(chunk)
        f.write(f"{h.hexdigest()}  {rel}\n")
PY
  fi

  echo "$out_dir"
}

restore_cmd() {
  local from=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --from) from="$2"; shift 2;;
      -h|--help) usage; exit 0;;
      *) die "Unknown argument: $1";;
    esac
  done
  [[ -n "$from" ]] || die "--from <backup_dir> is required"
  [[ -d "$from" ]] || die "Backup directory not found: $from"

  if [[ -f "${from}/db/postgres.dump" ]]; then
    restore_postgres "$from"
    return 0
  fi

  if [[ -f "${from}/db/sqlite.db" ]]; then
    restore_sqlite "$from"
    return 0
  fi

  die "No recognizable DB backup found under: ${from}/db/"
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 2
  fi

  local cmd="$1"; shift
  case "$cmd" in
    backup) backup_cmd "$@";;
    restore) restore_cmd "$@";;
    -h|--help|help) usage;;
    *) usage; die "Unknown command: $cmd";;
  esac
}

main "$@"

