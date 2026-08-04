#!/usr/bin/env bash
set -euo pipefail

# Platform backup script (code + docs + configs + optional DB dump).
#
# Produces:
#   <BACKUP_ROOT>/<timestamp>/
#     - platform_snapshot.tar.gz
#     - db/ (optional: postgres/sqlite dump)
#     - metadata/ (git + system info)
#     - SHA256SUMS
#
# SECURITY CONTRACT
# -----------------
# A backup concentrates everything sensitive about a deployment into one file,
# so this script is deliberately paranoid:
#
#   1. It refuses to write into a location that git would commit. Snapshots and
#      database dumps must never become repository content — once committed they
#      live in history forever and are copied to every clone and fork.
#   2. Secret-bearing artifacts are excluded from the archive: real .env files,
#      database files, keys/certificates, and the ledger persistence snapshots.
#      Anything git ignores is excluded too (that is where secrets live).
#   3. The finished backup is scanned for credential patterns and the run FAILS,
#      deleting the archive, if any are found — a leak is never shipped silently.
#   4. Output is written with restrictive permissions (dir 700 / files 600).
#   5. SHA256SUMS covers every artifact and errors are not swallowed, so the
#      manifest can be trusted for integrity verification (`--verify`).
#
# Usage:
#   scripts/backup_platform.sh                # create a backup
#   scripts/backup_platform.sh --verify PATH  # verify an existing backup dir
#
# Environment:
#   BACKUP_ROOT                   destination root (default: <workspace>/backups)
#   PHINS_BACKUP_RETENTION        keep the N newest backups (default 7, 0 = keep all)
#   PHINS_BACKUP_ALLOW_IN_REPO    set to 'true' to bypass the git-tracking guard
#   PHINS_BACKUP_SKIP_SCAN        set to 'true' to skip the secret scan (NOT advised)

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
BACKUP_ROOT="${BACKUP_ROOT:-${WORKSPACE_DIR}/backups}"

# ---------------------------------------------------------------------------
# Secret / sensitive-artifact patterns
# ---------------------------------------------------------------------------

# Filename patterns excluded from the snapshot archive.
SENSITIVE_EXCLUDES=(
  ".git"
  "backups"
  "**/__pycache__"
  "**/*.pyc"
  "**/.pytest_cache"
  "**/node_modules"
  "**/.venv"
  "**/venv"
  # Real environment files. Templates/examples are safe and intentionally kept
  # (.env.example / .env.production.template) so a restore still documents the
  # required configuration.
  "**/.env"
  "**/.env.local"
  "**/.env.development"
  "**/.env.staging"
  "**/.env.production"
  "**/.env.test"
  "**/.env.railway"
  "**/.env.*.local"
  # Databases and dumps.
  "**/*.db"
  "**/*.db-journal"
  "**/*.sqlite"
  "**/*.sqlite3"
  "**/*.dump"
  # Keys and certificates.
  "**/*.pem"
  "**/*.key"
  "**/*.p12"
  "**/*.pfx"
  "**/*.jks"
  "**/id_rsa*"
  "**/id_ed25519*"
  # Ledger persistence snapshots hold live platform transaction data.
  "**/phins_ledger*.json"
  "**/phins_ledger_chain_backup_*.json"
)

# Regexes that must not appear anywhere in a finished backup.
SECRET_SCAN_PATTERNS=(
  'BEGIN (RSA|EC|DSA|OPENSSH|PGP)? ?PRIVATE KEY'
  'AKIA[0-9A-Z]{16}'
  'sk_live_[0-9a-zA-Z]{20,}'
  'rk_live_[0-9a-zA-Z]{20,}'
  'xox[baprs]-[0-9a-zA-Z-]{10,}'
  'gh[pousr]_[0-9a-zA-Z]{30,}'
  'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}'
)

log()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Guard: never write a backup where git would pick it up
# ---------------------------------------------------------------------------
# Committing snapshots/DB dumps is how a backup turns into a permanent public
# data leak. Refuse unless the destination is outside a repo or explicitly
# ignored by it.
assert_destination_not_tracked() {
  local target="$1"
  if [ "${PHINS_BACKUP_ALLOW_IN_REPO:-}" = "true" ]; then
    warn "PHINS_BACKUP_ALLOW_IN_REPO=true — writing backups inside the repository."
    return 0
  fi
  command -v git >/dev/null 2>&1 || return 0

  local repo_root
  repo_root="$(git -C "$(dirname "${target}")" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "${repo_root}" ] || return 0

  if git -C "${repo_root}" check-ignore -q "${target}" 2>/dev/null; then
    return 0
  fi

  die "$(cat <<EOF
Backup destination is inside a git repository and is NOT ignored by it:
  destination: ${target}
  repository : ${repo_root}

Committing platform snapshots or database dumps would publish them permanently
in git history. Fix one of the following, then re-run:
  * add '$(basename "${target}")/' to ${repo_root}/.gitignore (recommended), or
  * set BACKUP_ROOT to a path outside the repository, e.g.
      BACKUP_ROOT=/var/backups/phins scripts/backup_platform.sh
  * or set PHINS_BACKUP_ALLOW_IN_REPO=true to override (NOT recommended).
EOF
)"
}

# ---------------------------------------------------------------------------
# Secret scan
# ---------------------------------------------------------------------------
scan_for_secrets() {
  local dir="$1"
  local found=0
  local scan_dir="${dir}/.scan"

  if [ "${PHINS_BACKUP_SKIP_SCAN:-}" = "true" ]; then
    warn "PHINS_BACKUP_SKIP_SCAN=true — skipping the backup secret scan."
    return 0
  fi

  # Expand the archive to a scratch dir so archived contents are inspected, not
  # just the loose metadata files.
  rm -rf "${scan_dir}"
  mkdir -p "${scan_dir}"
  if [ -f "${dir}/platform_snapshot.tar.gz" ]; then
    tar xzf "${dir}/platform_snapshot.tar.gz" -C "${scan_dir}" 2>/dev/null || true
  fi

  # Forbidden file types that must never be inside a backup.
  local offenders
  offenders="$(find "${scan_dir}" "${dir}/metadata" "${dir}/db" \
      \( -name '.env' -o -name '.env.local' -o -name '.env.production' \
         -o -name '.env.staging' -o -name '.env.development' \
         -o -name '*.pem' -o -name '*.key' -o -name 'id_rsa*' \
         -o -name '*.sqlite' -o -name '*.sqlite3' \) \
      -type f 2>/dev/null || true)"
  if [ -n "${offenders}" ]; then
    warn "Backup contains secret-bearing files:"
    printf '%s\n' "${offenders}" >&2
    found=1
  fi

  # Credential patterns anywhere in the backup.
  local pattern
  for pattern in "${SECRET_SCAN_PATTERNS[@]}"; do
    local hits
    hits="$(grep -rlEI "${pattern}" "${scan_dir}" "${dir}/metadata" 2>/dev/null || true)"
    if [ -n "${hits}" ]; then
      warn "Backup matches credential pattern /${pattern}/ in:"
      printf '%s\n' "${hits}" >&2
      found=1
    fi
  done

  rm -rf "${scan_dir}"

  if [ "${found}" -ne 0 ]; then
    return 1
  fi
  log "Secret scan: clean."
  return 0
}

# ---------------------------------------------------------------------------
# Verify mode
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--verify" ]; then
  VERIFY_DIR="${2:-}"
  [ -n "${VERIFY_DIR}" ] || die "--verify requires a backup directory path."
  [ -f "${VERIFY_DIR}/SHA256SUMS" ] || die "No SHA256SUMS in ${VERIFY_DIR}."
  log "Verifying ${VERIFY_DIR} ..."
  ( cd "${VERIFY_DIR}" && sha256sum -c SHA256SUMS ) || die "Checksum verification FAILED."
  scan_for_secrets "${VERIFY_DIR}" || die "Secret scan FAILED for ${VERIFY_DIR}."
  log "Backup verified: checksums match and no secrets detected."
  exit 0
fi

# ---------------------------------------------------------------------------
# Create backup
# ---------------------------------------------------------------------------
TS="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${BACKUP_ROOT}/${TS}"

mkdir -p "${BACKUP_ROOT}"
assert_destination_not_tracked "${BACKUP_ROOT}"

mkdir -p "${OUT_DIR}/metadata" "${OUT_DIR}/db"
# Restrictive permissions: a backup aggregates the whole platform.
chmod 700 "${OUT_DIR}" 2>/dev/null || true

log "Backup output: ${OUT_DIR}"

if command -v git >/dev/null 2>&1 && [ -d "${WORKSPACE_DIR}/.git" ]; then
  (
    cd "${WORKSPACE_DIR}"
    git rev-parse HEAD > "${OUT_DIR}/metadata/git_commit.txt" || true
    git status --porcelain=v1 > "${OUT_DIR}/metadata/git_status_porcelain.txt" || true
    git status > "${OUT_DIR}/metadata/git_status.txt" || true
    git log -n 20 --oneline > "${OUT_DIR}/metadata/git_log_20.txt" || true
    # Working-tree diffs can contain in-progress edits to config files; they are
    # covered by the secret scan below.
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

# -------------------------
# Database backup (optional)
# -------------------------

DB_BACKUP_NOTES=()

if [ -n "${DATABASE_URL:-}" ]; then
  if command -v pg_dump >/dev/null 2>&1; then
    log "Creating Postgres dump via pg_dump..."
    # Custom format: compressed, supports restore options.
    if pg_dump --format=custom --no-owner --no-privileges \
        --file "${OUT_DIR}/db/postgres.dump" "${DATABASE_URL}"; then
      chmod 600 "${OUT_DIR}/db/postgres.dump" 2>/dev/null || true
      log "postgres.dump created"
      DB_BACKUP_NOTES+=("Postgres dump created (contains LIVE customer data — keep out of version control).")
    else
      DB_BACKUP_NOTES+=("Postgres dump failed; check DATABASE_URL network/auth.")
    fi
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
        log "Backing up SQLite DB: ${sqlite_file}"
        # .backup takes a consistent snapshot even while the DB is in use; a
        # plain cp can capture a torn page mid-write.
        if ! sqlite3 "${sqlite_file}" ".backup '${OUT_DIR}/db/${base}'"; then
          DB_BACKUP_NOTES+=("SQLite .backup failed for ${sqlite_file}; falling back to cp.")
          cp -f "${sqlite_file}" "${OUT_DIR}/db/${base}"
        fi
        log "Exporting SQLite SQL dump: ${sqlite_file}"
        sqlite3 "${sqlite_file}" ".dump" > "${OUT_DIR}/db/${base}.sql"
        chmod 600 "${OUT_DIR}/db/${base}" "${OUT_DIR}/db/${base}.sql" 2>/dev/null || true
        DB_BACKUP_NOTES+=("SQLite backup created for ${base} (contains LIVE data — keep out of version control).")
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

printf "%s\n" "${DB_BACKUP_NOTES[@]}" > "${OUT_DIR}/db/backup_notes.txt"

# -------------------------
# Platform snapshot archive
# -------------------------

log "Creating platform snapshot archive..."

TAR_EXCLUDES=()
for pattern in "${SENSITIVE_EXCLUDES[@]}"; do
  TAR_EXCLUDES+=("--exclude=${pattern}")
done

# --exclude-vcs-ignores honours .gitignore, which is where secret-bearing files
# (.env, *.db, keys) are already listed — belt and braces with the explicit
# patterns above, and it automatically covers anything added to .gitignore later.
tar \
  --exclude-vcs-ignores \
  "${TAR_EXCLUDES[@]}" \
  -czf "${OUT_DIR}/platform_snapshot.tar.gz" \
  -C "${WORKSPACE_DIR}" \
  .

chmod 600 "${OUT_DIR}/platform_snapshot.tar.gz" 2>/dev/null || true

# -------------------------
# Integrity manifest
# -------------------------
# No `|| true`: a manifest that silently failed to generate is worse than none,
# because it makes an unverifiable backup look verified.
(
  cd "${OUT_DIR}"
  find . -type f ! -name 'SHA256SUMS' -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
)
chmod 600 "${OUT_DIR}/SHA256SUMS" 2>/dev/null || true

# -------------------------
# Secret scan (fail closed)
# -------------------------
if ! scan_for_secrets "${OUT_DIR}"; then
  warn "Deleting ${OUT_DIR} because it contains secrets."
  rm -rf "${OUT_DIR}"
  die "Backup aborted: secret material detected. Fix the exclusions (or remove the secret from the workspace) and re-run."
fi

# -------------------------
# Retention
# -------------------------
RETENTION="${PHINS_BACKUP_RETENTION:-7}"
if [ "${RETENTION}" -gt 0 ] 2>/dev/null; then
  # Keep the N newest timestamped directories; prune the rest.
  mapfile -t ALL_BACKUPS < <(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r)
  if [ "${#ALL_BACKUPS[@]}" -gt "${RETENTION}" ]; then
    for old in "${ALL_BACKUPS[@]:${RETENTION}}"; do
      log "Pruning old backup: ${old}"
      rm -rf "${BACKUP_ROOT}/${old}"
    done
  fi
fi

log "Backup complete."
log "Archive: ${OUT_DIR}/platform_snapshot.tar.gz"
log "DB dir : ${OUT_DIR}/db"
log "Meta   : ${OUT_DIR}/metadata"
log "Verify : scripts/backup_platform.sh --verify ${OUT_DIR}"
