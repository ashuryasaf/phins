# PHINS Backup Manifest — 20260513T202745Z

This backup was produced before any optimization changes were proposed for
execution. It captures the complete PHINS working tree, full git history (all
branches + all tags), and the metadata needed to verify integrity.

## Quick facts

| Field | Value |
|---|---|
| Backup timestamp (UTC) | `2026-05-13T20:27:45Z` |
| Backup directory | `/workspace/backups/20260513T202745Z/` |
| Git HEAD captured | `d3ad7215bc5ef6ce54e571e11ee16d74296ca98c` |
| Active branch at backup time | _(detached HEAD on `d3ad721`, equal to `origin/main`)_ |
| Working tree state | clean (no staged or unstaged changes) |
| Created by | `scripts/backup_platform.sh` |
| Live workspace size at backup | ~45 MB (excl. `.git`, `.venv`, `backups/`) |
| Archive size (committed) | 4.2 MB (`platform_snapshot.tar.gz`) |
| Total committed size | ~4.3 MB |
| Git bundle (not committed) | 25 MB; see "About the git bundle" below |

## Contents (as committed to git)

```
/workspace/backups/20260513T202745Z/
├── platform_snapshot.tar.gz   # 4.2 MB, 658 entries, gzip CRC OK, SHA256 OK
├── SHA256SUMS                 # checksums for everything in this directory
├── MANIFEST.md                # this file
├── metadata/
│   ├── git_commit.txt              # HEAD commit hash at backup time
│   ├── git_status.txt              # human-readable git status
│   ├── git_status_porcelain.txt    # machine-readable git status
│   ├── git_log_20.txt              # last 20 commits, one-line
│   ├── git_diff_unstaged.patch     # (empty — tree was clean)
│   ├── git_diff_staged.patch       # (empty — index was clean)
│   └── system_info.txt             # uname, python, java, sqlite versions
└── db/
    └── backup_notes.txt            # explains why no Postgres/SQLite dump
                                    # was produced in this environment
```

### About the git bundle (not committed)

A complete git bundle (`phins_repo_full.bundle`, ~25 MB) covering `main`, every
remote branch, and historical tags (`backup_20260102_211354`,
`v1.0.0-architecture-docs`, `v1.1.0-nft-ledger-backup`) was produced during this
backup but **was deliberately not committed** to avoid bloating repo history
with 25 MB of redundant data. The same history is already preserved at
`origin/main` on GitHub. If a fresh bundle is ever needed, recreate it with:

```bash
git bundle create phins_repo_full.bundle --all
git bundle verify phins_repo_full.bundle
```

## Database backup status — IMPORTANT

The `db/` directory only contains `backup_notes.txt`. **No production data was
captured in this backup** because:

- `DATABASE_URL` is unset in the cloud-agent VM (no Postgres reachable).
- No `phins.db` SQLite file exists in the workspace.
- The cloud-agent runs with `USE_DATABASE=false` / `USE_SQLITE=true` against a
  temp DB created by `conftest.py`, which is intentionally ephemeral and not
  worth preserving.

**For real production data, run `scripts/backup_platform.sh` directly on the
Railway/Render host** (or against a `pg_dump`-reachable `DATABASE_URL`) so the
`db/postgres.dump` file gets produced. The code in this repo handles that path
automatically when `DATABASE_URL` is present.

## Integrity verification

All checks passed at backup creation time:

| Check | Result |
|---|---|
| `sha256sum -c SHA256SUMS` | OK on every entry |
| `gzip -t platform_snapshot.tar.gz` | OK |
| `git bundle verify phins_repo_full.bundle` *(at creation)* | "records a complete history" |
| Live workspace ↔ archive file diff | **0 missing, 0 extra** |
| Spot-check of build files in archive | all 11 critical files present |

To re-verify at any time:

```bash
cd backups/20260513T202745Z
sha256sum -c SHA256SUMS
gzip -t platform_snapshot.tar.gz
```

## How to restore from this backup

### Option A — restore working tree only (file-level)

```bash
mkdir -p /tmp/phins_restore
tar -xzf /workspace/backups/20260513T202745Z/platform_snapshot.tar.gz \
    -C /tmp/phins_restore
# Inspect /tmp/phins_restore, then rsync the wanted parts back.
```

This restores every file but **not** the `.git/` directory or commit history.

### Option B — restore git history + working tree (recommended for full revert)

The committed copy of this backup does not include the 25 MB git bundle (see
"About the git bundle" above). Use one of these instead:

```bash
# Preferred: clone fresh from the remote at the captured commit.
git clone https://github.com/ashuryasaf/phins.git phins_restored
cd phins_restored
git checkout d3ad7215bc5ef6ce54e571e11ee16d74296ca98c

# Or, if you have produced a local bundle (see "About the git bundle"):
git clone /path/to/phins_repo_full.bundle phins_restored
cd phins_restored
git checkout d3ad7215bc5ef6ce54e571e11ee16d74296ca98c
```

### Option C — use the repo's own restore script

```bash
./restore_platform.sh d3ad7215bc5ef6ce54e571e11ee16d74296ca98c
```

`restore_platform.sh` resolves the commit hash inside the working repo's git
history (no archive needed), which is appropriate as long as the bad change
hasn't been force-pushed away.

## Why this backup matters

This backup was created in response to the optimization plan in the previous
conversation, which proposes (but has not yet executed) the following file
removals:

| Proposed deletion | Captured in this backup? |
|---|---|
| `app.json` | yes — `platform_snapshot.tar.gz:./app.json`, plus full history in bundle |
| `.deployment-trigger` | yes — same |
| `scheduler/runner.py` | yes — same |

So even if any of those three files were later deleted, they can be recovered
verbatim from this backup without consulting an external system.

## What is NOT in this backup

- Production database contents (see "Database backup status" above).
- Secrets / `.env` files — intentionally excluded by `scripts/backup_platform.sh`
  via its `--exclude="**/.env"` flag. Restore from Cursor Cloud Agent Secrets or
  the Railway/Render dashboard.
- Files under `backups/` itself — excluded to prevent recursive nesting.
- The `.venv/` directory — recreatable from `requirements.txt`.

## Next steps

This backup is now the safety net for any subsequent optimization work.
No code changes have been proposed for execution yet; the optimization plan
remains a written proposal only.
