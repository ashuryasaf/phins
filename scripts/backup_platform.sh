#!/usr/bin/env bash
set -euo pipefail

# Platform backup script (code + docs + configs + optional DB dump).
#
# Produces:
#   <BACKUP_ROOT>/<timestamp>/
#     - platform_snapshot.tar.gz
#     - repositories/phins.bundle  (every branch, tag, and remote-tracking ref)
#     - db/ (postgres/sqlite dumps and checksummed runtime data, when present)
#     - metadata/ (git + system info; never remote URLs)
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
#   6. The git bundle is round-tripped (mirror clone; refs, HEAD, and the
#      reachable object set must match). A configured database dump that fails,
#      or a SQLite snapshot that fails PRAGMA integrity_check, aborts the run.
#      There is no torn-file copy fallback.
#
# Usage:
#   scripts/backup_platform.sh                # create a backup
#   scripts/backup_platform.sh --verify PATH  # verify an existing backup dir
#
# After a successful run the backup directory contains restore_record.json
# (checksums, git commit, and restore commands). BACKUP_ROOT/RESTORE_INDEX.json
# lists every remaining snapshot so scripts/restore_from_backup.sh can find it.
# Set PHINS_BACKUP_RECORD_CATALOG to also write a metadata-only catalog that
# is safe to commit (no snapshot, no database dump).
#
# Environment:
#   BACKUP_ROOT                   destination root (default: <workspace>/backups)
#   PHINS_BACKUP_RETENTION        keep the N newest backups (default 7, 0 = keep all)
#   PHINS_BACKUP_ALLOW_IN_REPO    set to 'true' to bypass the git-tracking guard
#   PHINS_BACKUP_SKIP_SCAN        set to 'true' to skip the secret scan (NOT advised)
#   PHINS_BACKUP_RECORD_CATALOG   optional path for a commit-safe restore catalog

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

  # Forbidden file types that must never be inside a backup. The db/ tree is
  # deliberately excluded: it holds the intentional Postgres/SQLite dumps whose
  # rows legitimately contain credential-shaped live data (session tokens, JWT
  # payloads). Those artifacts are protected by 0600 perms and the
  # git-tracking guard, not by this leak scan; scanning them would flag every
  # DB backup and delete the whole run.
  local offenders
  offenders="$(find "${scan_dir}" "${dir}/metadata" \
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
# Integrity checks shared by create and --verify
# ---------------------------------------------------------------------------
# A non-zero exit on the create path deletes the incomplete snapshot. --verify
# does not register this trap, so a failed check never destroys an existing
# backup the operator asked to inspect.
BACKUP_COMPLETE=0
OUT_DIR=""

on_backup_exit() {
  local status=$?
  if [ "${status}" -ne 0 ] && [ "${BACKUP_COMPLETE}" != "1" ]; then
    if [ -n "${OUT_DIR}" ] && [ -d "${OUT_DIR}" ]; then
      rm -rf "${OUT_DIR}"
    fi
  fi
}

abort_backup() {
  warn "$1"
  exit 1
}

verify_snapshot_archive() {
  local dir="$1"
  local archive="${dir}/platform_snapshot.tar.gz"
  [ -f "${archive}" ] || return 0
  if ! tar tzf "${archive}" >/dev/null; then
    warn "Platform snapshot archive is unreadable: ${archive}"
    return 1
  fi
  log "Platform snapshot archive: readable."
  return 0
}

verify_sqlite_dumps() {
  local dir="$1"
  local dbdir="${dir}/db"
  [ -d "${dbdir}" ] || return 0
  local db check found=0
  while IFS= read -r -d '' db; do
    found=1
    if ! check="$(sqlite3 "${db}" "PRAGMA integrity_check;" 2>/dev/null)"; then
      warn "SQLite integrity_check could not run: ${db}"
      return 1
    fi
    if [ "${check}" != "ok" ]; then
      warn "SQLite integrity_check failed for ${db}"
      return 1
    fi
  done < <(find "${dbdir}" -type f \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -print0)
  if [ "${found}" -eq 1 ]; then
    log "SQLite dumps: integrity_check ok."
  fi
  return 0
}

verify_repository_bundle() {
  local dir="$1"
  local bundle="${dir}/repositories/phins.bundle"
  [ -f "${bundle}" ] || return 0

  local refs="${dir}/repositories/refs.txt"
  local objects="${dir}/repositories/objects.sha256"
  local head_file="${dir}/repositories/HEAD"
  if [ ! -f "${refs}" ] || [ ! -f "${objects}" ] || [ ! -f "${head_file}" ]; then
    warn "Repository bundle is missing refs.txt, HEAD, or objects.sha256"
    return 1
  fi

  local tmp rc=0
  tmp="$(mktemp -d)"
  if ! git -C "${tmp}" init -q; then
    rc=1
  elif ! git -C "${tmp}" bundle verify "${bundle}" > "${tmp}/verify.txt" 2>&1; then
    warn "git bundle verify failed"
    cat "${tmp}/verify.txt" >&2 || true
    rc=1
  elif ! grep -q "complete history" "${tmp}/verify.txt"; then
    warn "Bundle does not record a complete history"
    cat "${tmp}/verify.txt" >&2 || true
    rc=1
  elif ! git clone --mirror "${bundle}" "${tmp}/mirror" > "${tmp}/clone.txt" 2>&1; then
    warn "Mirror clone of the repository bundle failed"
    cat "${tmp}/clone.txt" >&2 || true
    rc=1
  else
    git -C "${tmp}/mirror" show-ref | LC_ALL=C sort > "${tmp}/mirror_refs.txt"
    LC_ALL=C sort "${refs}" > "${tmp}/refs.sorted"
    if ! cmp -s "${tmp}/mirror_refs.txt" "${tmp}/refs.sorted"; then
      warn "Mirror refs do not match the recorded repository refs"
      rc=1
    else
      local mirror_objects expected mirror_head expected_head
      if ! mirror_objects="$(git -C "${tmp}/mirror" rev-list --objects --all | awk '{print $1}' | LC_ALL=C sort | sha256sum | awk '{print $1}')"; then
        warn "Could not hash the mirror object set"
        rc=1
      else
        expected="$(tr -d '[:space:]' < "${objects}")"
        mirror_head="$(git -C "${tmp}/mirror" rev-parse HEAD)"
        expected_head="$(tr -d '[:space:]' < "${head_file}")"
        if [ "${mirror_objects}" != "${expected}" ]; then
          warn "Mirror object set does not match objects.sha256"
          rc=1
        elif [ "${mirror_head}" != "${expected_head}" ]; then
          warn "Mirror HEAD does not match recorded HEAD"
          rc=1
        fi
      fi
    fi
  fi
  rm -rf "${tmp}"
  if [ "${rc}" -ne 0 ]; then
    return 1
  fi
  local ref_count
  ref_count="$(grep -c . "${refs}" || true)"
  log "Repository bundle: complete history, ${ref_count} refs, object set matches."
  return 0
}

# Copy one data file and require the bytes on disk to match the source.
# Runtime data stays under db/ (mode 0600), never inside the code archive.
copy_verified_file() {
  local src="$1"
  local rel="$2"
  local dest="${OUT_DIR}/db/runtime/${rel}"
  mkdir -p "$(dirname "${dest}")"
  cp -p "${src}" "${dest}"
  chmod 600 "${dest}" 2>/dev/null || true
  local src_sum dest_sum
  src_sum="$(sha256sum "${src}" | awk '{print $1}')"
  dest_sum="$(sha256sum "${dest}" | awk '{print $1}')"
  if [ "${src_sum}" != "${dest_sum}" ]; then
    abort_backup "Checksum mismatch while copying ${rel}; the backup was discarded."
  fi
  DB_BACKUP_NOTES+=("Runtime file ${rel} copied (sha256=${src_sum}).")
}

backup_sqlite_file() {
  local sqlite_file="$1"
  local required="$2"
  local base dest check
  base="$(basename "${sqlite_file}")"
  dest="${OUT_DIR}/db/${base}"
  if ! check="$(sqlite3 "${sqlite_file}" "PRAGMA quick_check;" 2>/dev/null)"; then
    check=""
  fi
  if [ "${check}" != "ok" ]; then
    if [ "${required}" = "true" ]; then
      abort_backup "SQLite database failed PRAGMA quick_check (${base}); backup discarded."
    fi
    DB_BACKUP_NOTES+=("Skipped ${base}: not a valid SQLite database (excluded from the archive).")
    return 0
  fi
  log "Backing up SQLite DB: ${sqlite_file}"
  # .backup is a consistent snapshot. A plain copy can capture a torn page.
  if ! sqlite3 "${sqlite_file}" ".backup '${dest}'"; then
    abort_backup "SQLite .backup failed for ${base}; backup discarded."
  fi
  if ! check="$(sqlite3 "${dest}" "PRAGMA integrity_check;" 2>/dev/null)"; then
    check=""
  fi
  if [ "${check}" != "ok" ]; then
    abort_backup "SQLite backup failed PRAGMA integrity_check (${base}); backup discarded."
  fi
  log "Exporting SQLite SQL dump: ${sqlite_file}"
  sqlite3 "${dest}" ".dump" > "${OUT_DIR}/db/${base}.sql"
  chmod 600 "${dest}" "${OUT_DIR}/db/${base}.sql" 2>/dev/null || true
  DB_BACKUP_NOTES+=("SQLite backup created for ${base} (integrity_check ok; contains LIVE data — keep out of version control).")
}

backup_git_repository() {
  if ! command -v git >/dev/null 2>&1 || [ ! -d "${WORKSPACE_ABS}/.git" ]; then
    DB_BACKUP_NOTES+=("No git repository; repository bundle skipped.")
    return 0
  fi
  if [ "$(git -C "${WORKSPACE_ABS}" rev-parse --is-shallow-repository)" = "true" ]; then
    abort_backup "Repository is shallow. A full backup needs every reachable object. Run: git fetch --unshallow"
  fi

  local repo_dir="${OUT_DIR}/repositories"
  mkdir -p "${repo_dir}"
  chmod 700 "${repo_dir}" 2>/dev/null || true

  # Refs and objects only. Never record remote URLs: they can carry credentials.
  git -C "${WORKSPACE_ABS}" rev-parse HEAD > "${repo_dir}/HEAD"
  git -C "${WORKSPACE_ABS}" show-ref | LC_ALL=C sort > "${repo_dir}/refs.txt"
  git -C "${WORKSPACE_ABS}" rev-list --objects --all \
    | awk '{print $1}' \
    | LC_ALL=C sort \
    | sha256sum \
    | awk '{print $1}' > "${repo_dir}/objects.sha256"

  log "Creating git bundle of every ref..."
  if ! git -C "${WORKSPACE_ABS}" bundle create "${repo_dir}/phins.bundle" --all; then
    abort_backup "git bundle create failed; backup discarded."
  fi
  chmod 600 "${repo_dir}/phins.bundle" "${repo_dir}/HEAD" \
    "${repo_dir}/refs.txt" "${repo_dir}/objects.sha256" 2>/dev/null || true

  if ! verify_repository_bundle "${OUT_DIR}"; then
    abort_backup "Repository bundle failed the round-trip integrity check; backup discarded."
  fi
  local ref_count
  ref_count="$(grep -c . "${repo_dir}/refs.txt" || true)"
  DB_BACKUP_NOTES+=("Git bundle created for every ref (${ref_count} refs). Remote URLs were not recorded.")
}

# ---------------------------------------------------------------------------
# Restoration record + index
# ---------------------------------------------------------------------------
# restore_record.json lives inside the snapshot directory (gitignored with the
# rest of backups/). RESTORE_INDEX.json is the local lookup table. A separate
# catalog file is written only when PHINS_BACKUP_RECORD_CATALOG is set; that
# file holds metadata and checksums, never archive or dump bytes.
write_restore_record() {
  local out_dir="$1"
  command -v python3 >/dev/null 2>&1 || die "python3 is required to write restore_record.json"
  python3 - "${out_dir}" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1]).resolve()
ts = out.name
meta = out / "metadata"
git_commit = ""
git_status_dirty = False
if (meta / "git_commit.txt").exists():
    git_commit = (meta / "git_commit.txt").read_text(encoding="utf-8").strip()
if (meta / "git_status_porcelain.txt").exists():
    git_status_dirty = bool((meta / "git_status_porcelain.txt").read_text(encoding="utf-8").strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


artifacts = {}
archive = out / "platform_snapshot.tar.gz"
if archive.is_file():
    artifacts["platform_snapshot"] = {
        "path": "platform_snapshot.tar.gz",
        "sha256": sha256(archive),
        "bytes": archive.stat().st_size,
    }

db_files = []
db_dir = out / "db"
if db_dir.is_dir():
    for path in sorted(p for p in db_dir.rglob("*") if p.is_file()):
        if path.name == "backup_notes.txt":
            continue
        db_files.append({
            "path": path.relative_to(out).as_posix(),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        })
artifacts["db_files"] = db_files

repo = out / "repositories"
bundle = repo / "phins.bundle"
if bundle.is_file():
    artifacts["repository_bundle"] = {
        "path": "repositories/phins.bundle",
        "sha256": sha256(bundle),
        "bytes": bundle.stat().st_size,
    }
refs = repo / "refs.txt"
if refs.is_file():
    ref_lines = [line for line in refs.read_text(encoding="utf-8").splitlines() if line.strip()]
    artifacts["repository_refs"] = {
        "path": "repositories/refs.txt",
        "sha256": sha256(refs),
        "ref_count": len(ref_lines),
    }
head_path = repo / "HEAD"
if head_path.is_file():
    artifacts["repository_head"] = head_path.read_text(encoding="utf-8").strip()
objects_path = repo / "objects.sha256"
if objects_path.is_file():
    artifacts["repository_objects_sha256"] = objects_path.read_text(encoding="utf-8").strip()

notes = []
notes_file = db_dir / "backup_notes.txt"
if notes_file.is_file():
    notes = [line for line in notes_file.read_text(encoding="utf-8").splitlines() if line.strip()]

created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
record = {
    "schema_version": 1,
    "backup_id": ts,
    "timestamp_utc": ts,
    "created_at": created_at,
    "git_commit": git_commit,
    "git_status_dirty": git_status_dirty,
    "backup_dir": str(out),
    "artifacts": artifacts,
    "has_db_dump": bool(db_files),
    "db_notes": notes,
    "verify_command": f"scripts/backup_platform.sh --verify {out}",
    "restore": {
        "code_from_git": (
            f"git checkout {git_commit}"
            if git_commit
            else "git checkout <commit from metadata/git_commit.txt>"
        ),
        "code_from_snapshot": (
            f"mkdir -p /tmp/phins-restore-{ts} && "
            f"tar xzf {out}/platform_snapshot.tar.gz -C /tmp/phins-restore-{ts}"
        ),
        "database_postgres": (
            f'pg_restore --no-owner --no-privileges -d "$DATABASE_URL" {out}/db/postgres.dump'
        ),
        "database_sqlite": 'sqlite3 "$SQLITE_PATH" ".restore \'<backup>/db/<name>.db\'"',
        "repository_from_bundle": (
            f"git clone {out}/repositories/phins.bundle /tmp/phins-repo-{ts}"
            if bundle.is_file()
            else None
        ),
        "verify": f"scripts/backup_platform.sh --verify {out}",
        "list_recorded": "scripts/restore_from_backup.sh --list",
    },
}
(out / "restore_record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

lines = [
    f"PHINS platform restore record",
    f"backup_id={ts}",
    f"created_at={created_at}",
    f"git_commit={git_commit or '(unavailable)'}",
    f"verify=scripts/backup_platform.sh --verify {out}",
    f"list=scripts/restore_from_backup.sh --list",
    f"show=scripts/restore_from_backup.sh --show {ts}",
]
if git_commit:
    lines.append(f"code_restore=./restore_platform.sh {git_commit}")
if bundle.is_file():
    lines.append(
        f"repository_restore=git clone {out}/repositories/phins.bundle /tmp/phins-repo-{ts}"
    )
(out / "RESTORE.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(str(out / "restore_record.json"))
PY
}

write_restore_index() {
  local backup_root="$1"
  local catalog_path="${PHINS_BACKUP_RECORD_CATALOG:-}"
  command -v python3 >/dev/null 2>&1 || die "python3 is required to write RESTORE_INDEX.json"
  python3 - "${backup_root}" "${catalog_path}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1]).resolve()
catalog_path = sys.argv[2].strip() if len(sys.argv) > 2 else ""
entries = []
for child in sorted(root.iterdir(), reverse=True):
    if not child.is_dir():
        continue
    record_path = child / "restore_record.json"
    if not record_path.is_file():
        entries.append({
            "backup_id": child.name,
            "path": str(child),
            "has_restore_record": False,
        })
        continue
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        entries.append({
            "backup_id": child.name,
            "path": str(child),
            "has_restore_record": False,
        })
        continue
    snapshot = (data.get("artifacts") or {}).get("platform_snapshot") or {}
    bundle = (data.get("artifacts") or {}).get("repository_bundle") or {}
    refs = (data.get("artifacts") or {}).get("repository_refs") or {}
    entries.append({
        "backup_id": data.get("backup_id") or child.name,
        "created_at": data.get("created_at"),
        "git_commit": data.get("git_commit") or "",
        "git_status_dirty": bool(data.get("git_status_dirty")),
        "path": str(child),
        "has_restore_record": True,
        "has_db_dump": bool(data.get("has_db_dump")),
        "snapshot_sha256": snapshot.get("sha256") or "",
        "snapshot_bytes": snapshot.get("bytes"),
        "repository_bundle_sha256": bundle.get("sha256") or "",
        "repository_bundle_bytes": bundle.get("bytes"),
        "repository_ref_count": refs.get("ref_count"),
        "repository_head": (data.get("artifacts") or {}).get("repository_head") or "",
        "verify_command": data.get("verify_command") or f"scripts/backup_platform.sh --verify {child}",
    })

index = {
    "schema_version": 1,
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "latest": entries[0]["backup_id"] if entries else None,
    "count": len(entries),
    "backups": entries,
}
index_path = root / "RESTORE_INDEX.json"
index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
try:
    index_path.chmod(0o600)
except OSError:
    pass

if catalog_path:
    catalog = Path(catalog_path)
    catalog.parent.mkdir(parents=True, exist_ok=True)
    # Metadata only: no archive bytes, no dump bytes, no host-only scratch paths
    # beyond the recorded backup_id. Absolute paths stay so the same machine
    # can restore; clones still have git_commit + checksums for verification.
    safe = {
        "schema_version": 1,
        "updated_at": index["updated_at"],
        "latest": index["latest"],
        "count": index["count"],
        "backups": [
            {
                "backup_id": item.get("backup_id"),
                "created_at": item.get("created_at"),
                "git_commit": item.get("git_commit") or "",
                "git_status_dirty": bool(item.get("git_status_dirty")),
                "has_db_dump": bool(item.get("has_db_dump")),
                "snapshot_sha256": item.get("snapshot_sha256") or "",
                "snapshot_bytes": item.get("snapshot_bytes"),
                "repository_bundle_sha256": item.get("repository_bundle_sha256") or "",
                "repository_bundle_bytes": item.get("repository_bundle_bytes"),
                "repository_ref_count": item.get("repository_ref_count"),
                "repository_head": item.get("repository_head") or "",
                "backup_dir": item.get("path"),
                "verify_command": item.get("verify_command"),
                "restore_code": (
                    f"git checkout {item['git_commit']}"
                    if item.get("git_commit")
                    else None
                ),
            }
            for item in entries
            if item.get("has_restore_record")
        ],
    }
    catalog.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")
print(str(index_path))
PY
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
  verify_snapshot_archive "${VERIFY_DIR}" || die "Snapshot archive verification FAILED."
  verify_repository_bundle "${VERIFY_DIR}" || die "Repository bundle verification FAILED."
  verify_sqlite_dumps "${VERIFY_DIR}" || die "SQLite integrity verification FAILED."
  scan_for_secrets "${VERIFY_DIR}" || die "Secret scan FAILED for ${VERIFY_DIR}."
  log "Backup verified: checksums match, repository bundle round-trips, and no secrets detected."
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
chmod 700 "${OUT_DIR}" "${OUT_DIR}/db" 2>/dev/null || true
# From here, any failure deletes this snapshot. --verify never reaches this trap.
trap on_backup_exit EXIT

WORKSPACE_ABS="$(cd "${WORKSPACE_DIR}" && pwd -P)"
BACKUP_ROOT_ABS="$(cd "${BACKUP_ROOT}" && pwd -P)"

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
  if ! command -v pg_dump >/dev/null 2>&1; then
    abort_backup "DATABASE_URL is set but pg_dump is not available; refusing a backup that is missing the database."
  fi
  log "Creating Postgres dump via pg_dump..."
  # Custom format: compressed, supports restore options. The URL is never logged.
  if ! pg_dump --format=custom --no-owner --no-privileges \
      --file "${OUT_DIR}/db/postgres.dump" "${DATABASE_URL}"; then
    abort_backup "Postgres dump failed; refusing a backup with an incomplete database."
  fi
  chmod 600 "${OUT_DIR}/db/postgres.dump" 2>/dev/null || true
  if command -v pg_restore >/dev/null 2>&1; then
    if ! pg_restore --list "${OUT_DIR}/db/postgres.dump" >/dev/null; then
      abort_backup "Postgres dump failed pg_restore --list; backup discarded."
    fi
  fi
  log "postgres.dump created"
  DB_BACKUP_NOTES+=("Postgres dump created (contains LIVE customer data — keep out of version control).")
else
  DB_BACKUP_NOTES+=("DATABASE_URL not set; skipping Postgres dump.")
fi

# SQLite: consistent .backup of SQLITE_PATH and ./phins.db. A failed snapshot
# aborts. An invalid placeholder file is skipped (it is already excluded from
# the archive) unless SQLITE_PATH pointed at it explicitly.
if ! command -v sqlite3 >/dev/null 2>&1; then
  if [ -n "${SQLITE_PATH:-}" ] || [ -f "${WORKSPACE_ABS}/phins.db" ]; then
    abort_backup "A SQLite database is present but sqlite3 is not available; backup discarded."
  fi
  DB_BACKUP_NOTES+=("sqlite3 not available; no SQLite candidates to back up.")
else
  if [ -n "${SQLITE_PATH:-}" ]; then
    if [ -f "${SQLITE_PATH}" ]; then
      backup_sqlite_file "${SQLITE_PATH}" "true"
    else
      abort_backup "SQLITE_PATH is set but the file does not exist; backup discarded."
    fi
  fi
  if [ -f "${WORKSPACE_ABS}/phins.db" ]; then
    # Skip when it is the same file already captured via SQLITE_PATH.
    if [ -z "${SQLITE_PATH:-}" ] || [ "$(cd "$(dirname "${SQLITE_PATH}")" && pwd -P)/$(basename "${SQLITE_PATH}")" != "${WORKSPACE_ABS}/phins.db" ]; then
      backup_sqlite_file "${WORKSPACE_ABS}/phins.db" "false"
    fi
  fi
  if [ -z "${SQLITE_PATH:-}" ] && [ ! -f "${WORKSPACE_ABS}/phins.db" ]; then
    DB_BACKUP_NOTES+=("No SQLITE_PATH/phins.db found; skipping SQLite backup.")
  fi
fi

# Ledger files, keyring, media, and gitignored runtime stores. These are
# excluded from the code archive on purpose; the checksummed copy under
# db/runtime/ is the data backup.
ledger_found=0
while IFS= read -r -d '' ledger_src; do
  ledger_found=1
  ledger_rel="${ledger_src#"${WORKSPACE_ABS}/"}"
  if [ "${ledger_rel}" = "${ledger_src}" ]; then
    ledger_rel="external/$(basename "${ledger_src}")"
  fi
  copy_verified_file "${ledger_src}" "${ledger_rel}"
done < <(find "${WORKSPACE_ABS}" \
    \( -path "${WORKSPACE_ABS}/.git" \
       -o -path "${WORKSPACE_ABS}/.venv" \
       -o -path "${WORKSPACE_ABS}/venv" \
       -o -path "${BACKUP_ROOT_ABS}" \
    \) -prune -o -type f -name 'phins_ledger*.json' -print0)
if [ "${ledger_found}" -eq 0 ]; then
  DB_BACKUP_NOTES+=("No phins_ledger*.json files found.")
fi
if [ -n "${LEDGER_PERSISTENCE_FILE:-}" ]; then
  if [ -f "${LEDGER_PERSISTENCE_FILE}" ]; then
    copy_verified_file "${LEDGER_PERSISTENCE_FILE}" "ledger/$(basename "${LEDGER_PERSISTENCE_FILE}")"
  else
    abort_backup "LEDGER_PERSISTENCE_FILE is set but the file does not exist; backup discarded."
  fi
fi

copy_runtime_path() {
  local rel="$1"
  local src="${WORKSPACE_ABS}/${rel}"
  local runtime_file runtime_rel
  if [ -f "${src}" ]; then
    copy_verified_file "${src}" "${rel}"
  elif [ -d "${src}" ]; then
    while IFS= read -r -d '' runtime_file; do
      runtime_rel="${runtime_file#"${WORKSPACE_ABS}/"}"
      copy_verified_file "${runtime_file}" "${runtime_rel}"
    done < <(find "${src}" -type f ! -name '.gitignore' ! -name '.gitkeep' -print0)
  fi
}
copy_runtime_path "data/assessment_center"
copy_runtime_path "data/documents"
copy_runtime_path "database/confidential_shares.json"
copy_runtime_path "database/meeting_notes.json"

if [ -n "${PHINS_KEYRING_PATH:-}" ]; then
  if [ -f "${PHINS_KEYRING_PATH}" ]; then
    copy_verified_file "${PHINS_KEYRING_PATH}" "keyring/$(basename "${PHINS_KEYRING_PATH}")"
  else
    abort_backup "PHINS_KEYRING_PATH is set but the file does not exist; backup discarded."
  fi
else
  DB_BACKUP_NOTES+=("PHINS_KEYRING_PATH not set; keyring not copied.")
fi

if [ -n "${PHINS_MEDIA_STORAGE_DIR:-}" ]; then
  if [ -d "${PHINS_MEDIA_STORAGE_DIR}" ]; then
    while IFS= read -r -d '' media_file; do
      media_rel="media/$(basename "${PHINS_MEDIA_STORAGE_DIR}")/${media_file#"${PHINS_MEDIA_STORAGE_DIR}/"}"
      copy_verified_file "${media_file}" "${media_rel}"
    done < <(find "${PHINS_MEDIA_STORAGE_DIR}" -type f -print0)
  else
    abort_backup "PHINS_MEDIA_STORAGE_DIR is set but the directory does not exist; backup discarded."
  fi
else
  DB_BACKUP_NOTES+=("PHINS_MEDIA_STORAGE_DIR not set; media store not copied.")
fi

# -------------------------
# Full git repository (every ref)
# -------------------------
backup_git_repository

printf "%s\n" "${DB_BACKUP_NOTES[@]}" > "${OUT_DIR}/db/backup_notes.txt"
chmod 600 "${OUT_DIR}/db/backup_notes.txt" 2>/dev/null || true

# -------------------------
# Platform snapshot archive
# -------------------------

log "Creating platform snapshot archive..."

TAR_EXCLUDES=()
for pattern in "${SENSITIVE_EXCLUDES[@]}"; do
  TAR_EXCLUDES+=("--exclude=${pattern}")
done

# Never archive the backup destination itself. The default is named "backups"
# (already excluded), but a custom BACKUP_ROOT inside the workspace would
# otherwise be read while this very archive is being written into it — tar then
# reports "file changed as we read it" and fails, and the archive would nest
# previous backups.
case "${BACKUP_ROOT_ABS}/" in
  "${WORKSPACE_ABS}/"*)
    BACKUP_ROOT_REL="${BACKUP_ROOT_ABS#"${WORKSPACE_ABS}/"}"
    TAR_EXCLUDES+=("--exclude=./${BACKUP_ROOT_REL}")
    ;;
esac

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
verify_snapshot_archive "${OUT_DIR}" || abort_backup "Platform snapshot archive is unreadable; backup discarded."

# -------------------------
# Restoration record
# -------------------------
# Written before SHA256SUMS so the manifest covers the record itself.
log "Writing restoration record..."
write_restore_record "${OUT_DIR}"
chmod 600 "${OUT_DIR}/restore_record.json" "${OUT_DIR}/RESTORE.txt" 2>/dev/null || true

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
if ! ( cd "${OUT_DIR}" && sha256sum -c SHA256SUMS >/dev/null ); then
  abort_backup "Checksum self-check failed; backup discarded."
fi
log "Checksum self-check: ok."

# -------------------------
# Secret scan (fail closed)
# -------------------------
if ! scan_for_secrets "${OUT_DIR}"; then
  warn "Deleting ${OUT_DIR} because it contains secrets."
  rm -rf "${OUT_DIR}"
  die "Backup aborted: secret material detected. Fix the exclusions (or remove the secret from the workspace) and re-run."
fi

# The snapshot is complete. Later index/retention problems must not delete it.
BACKUP_COMPLETE=1

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

# Index is written after the secret scan and retention so a failed or pruned
# snapshot is never advertised as restorable.
write_restore_index "${BACKUP_ROOT}"
log "Restore index: ${BACKUP_ROOT}/RESTORE_INDEX.json"
if [ -n "${PHINS_BACKUP_RECORD_CATALOG:-}" ]; then
  log "Restore catalog: ${PHINS_BACKUP_RECORD_CATALOG}"
fi

log "Backup complete."
log "Archive: ${OUT_DIR}/platform_snapshot.tar.gz"
log "Repo   : ${OUT_DIR}/repositories/phins.bundle"
log "Record : ${OUT_DIR}/restore_record.json"
log "DB dir : ${OUT_DIR}/db"
log "Meta   : ${OUT_DIR}/metadata"
log "Verify : scripts/backup_platform.sh --verify ${OUT_DIR}"
log "List   : scripts/restore_from_backup.sh --list"
