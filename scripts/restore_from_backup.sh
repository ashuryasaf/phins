#!/usr/bin/env bash
set -euo pipefail

# List, show, and verify platform backups recorded for restoration.
#
# Usage:
#   scripts/restore_from_backup.sh --list
#   scripts/restore_from_backup.sh --latest
#   scripts/restore_from_backup.sh --show [BACKUP_ID]
#   scripts/restore_from_backup.sh --verify [BACKUP_ID]
#   scripts/restore_from_backup.sh --print-commands [BACKUP_ID]
#
# BACKUP_ID defaults to the latest recorded snapshot. This script does not
# overwrite the working tree; it prints the recorded restore commands.

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
BACKUP_ROOT="${BACKUP_ROOT:-${WORKSPACE_DIR}/backups}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log()  { printf '%s\n' "$*"; }

[ -d "${BACKUP_ROOT}" ] || die "No backup root at ${BACKUP_ROOT}. Run scripts/backup_platform.sh first."
command -v python3 >/dev/null 2>&1 || die "python3 is required."

INDEX_PATH="${BACKUP_ROOT}/RESTORE_INDEX.json"

ensure_index() {
  if [ ! -f "${INDEX_PATH}" ]; then
    # Rebuild from any restore_record.json files already on disk.
    python3 - "${BACKUP_ROOT}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1]).resolve()
entries = []
for child in sorted(root.iterdir(), reverse=True):
    record_path = child / "restore_record.json"
    if not child.is_dir() or not record_path.is_file():
        continue
    data = json.loads(record_path.read_text(encoding="utf-8"))
    snapshot = (data.get("artifacts") or {}).get("platform_snapshot") or {}
    entries.append({
        "backup_id": data.get("backup_id") or child.name,
        "created_at": data.get("created_at"),
        "git_commit": data.get("git_commit") or "",
        "path": str(child),
        "has_restore_record": True,
        "has_db_dump": bool(data.get("has_db_dump")),
        "snapshot_sha256": snapshot.get("sha256") or "",
        "verify_command": data.get("verify_command") or "",
    })
index = {
    "schema_version": 1,
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "latest": entries[0]["backup_id"] if entries else None,
    "count": len(entries),
    "backups": entries,
}
(root / "RESTORE_INDEX.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
PY
  fi
  [ -f "${INDEX_PATH}" ] || die "No RESTORE_INDEX.json and no restore_record.json files under ${BACKUP_ROOT}."
}

resolve_backup_id() {
  local requested="${1:-}"
  python3 - "${INDEX_PATH}" "${requested}" <<'PY'
import json
import sys
from pathlib import Path

index = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
requested = sys.argv[2].strip()
backups = index.get("backups") or []
if not backups:
    raise SystemExit("No backups are recorded in the restore index.")
if not requested or requested in ("latest", "--latest"):
    print(index.get("latest") or backups[0]["backup_id"])
    raise SystemExit(0)
for item in backups:
    if item.get("backup_id") == requested:
        print(requested)
        raise SystemExit(0)
# Also accept a full directory path.
for item in backups:
    if item.get("path") == requested:
        print(item["backup_id"])
        raise SystemExit(0)
raise SystemExit(f"Backup not recorded: {requested}")
PY
}

load_record() {
  local backup_id="$1"
  python3 - "${INDEX_PATH}" "${backup_id}" <<'PY'
import json
import sys
from pathlib import Path

index = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
backup_id = sys.argv[2]
for item in index.get("backups") or []:
    if item.get("backup_id") != backup_id:
        continue
    record_path = Path(item["path"]) / "restore_record.json"
    if not record_path.is_file():
        raise SystemExit(f"Restore record missing: {record_path}")
    print(record_path.read_text(encoding="utf-8"), end="")
    raise SystemExit(0)
raise SystemExit(f"Backup not recorded: {backup_id}")
PY
}

cmd_list() {
  python3 - "${INDEX_PATH}" <<'PY'
import json
import sys
from pathlib import Path

index = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(f"Recorded backups: {index.get('count', 0)}")
print(f"Latest: {index.get('latest') or '(none)'}")
print(f"Updated: {index.get('updated_at') or '(unknown)'}")
print("")
for item in index.get("backups") or []:
    dump = "db-dump" if item.get("has_db_dump") else "code-snapshot"
    commit = (item.get("git_commit") or "")[:12] or "no-commit"
    print(f"- {item.get('backup_id')}  {dump}  git={commit}  {item.get('path')}")
PY
}

cmd_show() {
  local backup_id="$1"
  load_record "${backup_id}"
}

cmd_print_commands() {
  local backup_id="$1"
  RECORD_JSON="$(load_record "${backup_id}")" python3 - <<'PY'
import json
import os

record = json.loads(os.environ["RECORD_JSON"])
restore = record.get("restore") or {}
print(f"backup_id={record.get('backup_id')}")
print(f"git_commit={record.get('git_commit') or '(unavailable)'}")
print("")
print("Verify:")
print(f"  {restore.get('verify') or record.get('verify_command')}")
print("Code from git:")
print(f"  {restore.get('code_from_git')}")
print("Code from snapshot (staging directory, does not overwrite the repo):")
print(f"  {restore.get('code_from_snapshot')}")
print("Postgres (only if db/postgres.dump exists):")
print(f"  {restore.get('database_postgres')}")
print("SQLite (only if a .db file exists under db/):")
print(f"  {restore.get('database_sqlite')}")
PY
}

cmd_verify() {
  local backup_id="$1"
  local backup_dir
  backup_dir="$(python3 - "${INDEX_PATH}" "${backup_id}" <<'PY'
import json
import sys
from pathlib import Path

index = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
backup_id = sys.argv[2]
for item in index.get("backups") or []:
    if item.get("backup_id") == backup_id:
        print(item["path"])
        raise SystemExit(0)
raise SystemExit(f"Backup not recorded: {backup_id}")
PY
)"
  exec bash "${SCRIPT_DIR}/backup_platform.sh" --verify "${backup_dir}"
}

usage() {
  cat <<EOF
Usage:
  scripts/restore_from_backup.sh --list
  scripts/restore_from_backup.sh --latest
  scripts/restore_from_backup.sh --show [BACKUP_ID]
  scripts/restore_from_backup.sh --verify [BACKUP_ID]
  scripts/restore_from_backup.sh --print-commands [BACKUP_ID]

Lists backups recorded for restoration. Does not modify the working tree.
EOF
}

ACTION="${1:-}"
ARG="${2:-}"

case "${ACTION}" in
  --list)
    ensure_index
    cmd_list
    ;;
  --latest)
    ensure_index
    cmd_show "$(resolve_backup_id latest)"
    ;;
  --show)
    ensure_index
    cmd_show "$(resolve_backup_id "${ARG}")"
    ;;
  --verify)
    ensure_index
    cmd_verify "$(resolve_backup_id "${ARG}")"
    ;;
  --print-commands)
    ensure_index
    cmd_print_commands "$(resolve_backup_id "${ARG}")"
    ;;
  -h|--help|"")
    usage
    [ -n "${ACTION}" ] || exit 1
    ;;
  *)
    usage
    die "Unknown action: ${ACTION}"
    ;;
esac
