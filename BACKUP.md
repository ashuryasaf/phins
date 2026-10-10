# Platform Backup

This repo includes a repeatable backup script that creates a timestamped bundle containing:

- **System snapshot**: code + configs + docs + static assets + pipeline definitions
- **Repository bundle**: every branch, tag, and remote-tracking ref in `repositories/phins.bundle` (a complete history, not `.git/config`)
- **Metadata**: git commit/status/diffs + environment-independent system info. Remote URLs are never recorded.
- **Data dump (when configured or present)**:
  - Postgres: `DATABASE_URL` + `pg_dump`. A failed dump aborts the run.
  - SQLite: `SQLITE_PATH` or `phins.db`, via `sqlite3 .backup`, then `PRAGMA integrity_check`. A failed snapshot aborts the run.
  - Ledger files (`phins_ledger*.json`), `LEDGER_PERSISTENCE_FILE`, the keyring (`PHINS_KEYRING_PATH`), the media store (`PHINS_MEDIA_STORAGE_DIR`), and runtime files under `data/assessment_center`, `data/documents`, `database/confidential_shares.json`, and `database/meeting_notes.json`. Each copy is checksum-matched to the source and stored under `db/runtime/` (mode `0600`).

## Run backup

```bash
bash scripts/backup_platform.sh
```

Every successful run writes a **restoration record**:

- `backups/<UTC_TIMESTAMP>/restore_record.json` — git commit, artifact checksums, restore commands
- `backups/<UTC_TIMESTAMP>/RESTORE.txt` — short human-readable pointer
- `backups/RESTORE_INDEX.json` — local index of remaining snapshots

To also write a metadata-only catalog that is safe to commit (checksums and git SHAs, never the archive or a database dump):

```bash
PHINS_BACKUP_RECORD_CATALOG=docs/platform_restore_catalog.json bash scripts/backup_platform.sh
```

List or verify recorded backups without touching the working tree:

```bash
bash scripts/restore_from_backup.sh --list
bash scripts/restore_from_backup.sh --latest
bash scripts/restore_from_backup.sh --verify
bash scripts/restore_from_backup.sh --print-commands
```

## Verify an existing backup

Checks every file against `SHA256SUMS`, reads the snapshot archive, round-trips the git bundle (mirror clone; refs, `HEAD`, and the reachable object set), runs `PRAGMA integrity_check` on every SQLite dump, and re-runs the secret scan. `--verify` never deletes a backup.

```bash
bash scripts/backup_platform.sh --verify backups/<UTC_TIMESTAMP>
```

The create path runs those same checks before it writes the restore index. A failed database dump, a SQLite snapshot that is not `ok`, a bundle that does not round-trip, or a checksum mismatch deletes the incomplete snapshot.

## Outputs

Backups are written under:

- `backups/<UTC_TIMESTAMP>/platform_snapshot.tar.gz`
- `backups/<UTC_TIMESTAMP>/repositories/phins.bundle` plus `refs.txt`, `HEAD`, and `objects.sha256`
- `backups/<UTC_TIMESTAMP>/db/` (dumps, `db/runtime/`, or `backup_notes.txt`)
- `backups/<UTC_TIMESTAMP>/metadata/`
- `backups/<UTC_TIMESTAMP>/SHA256SUMS`

## Backups are never committed

`backups/` is listed in `.gitignore` and the script **refuses to run** when its
destination sits inside a git repository without being ignored.

A snapshot aggregates the whole deployment and can include a full database dump.
Committing one publishes that payload permanently in git history and copies it to
every clone and fork — and history cannot be cleaned without a force-push
rewrite. Keep backups on a volume or in object storage, not in the repo.

If you deliberately need a backup inside a tracked path, set
`PHINS_BACKUP_ALLOW_IN_REPO=true` (not recommended).

## What is excluded (secrets)

- Environment variables are **never exported**.
- Real `.env` files (`.env`, `.env.local`, `.env.production`, …) are excluded at
  every directory depth. Safe templates (`.env.example`,
  `.env.production.template`) are kept so a restore still documents the required
  configuration.
- Database files and dumps (`*.db`, `*.sqlite*`, `*.dump`), keys and
  certificates (`*.pem`, `*.key`, `*.p12`, `id_rsa*`), and the ledger
  persistence snapshots (`phins_ledger*.json`) are excluded from the archive.
- Everything `.gitignore` covers is excluded as well (`--exclude-vcs-ignores`),
  so entries added there are picked up automatically.

## Secret scan (fail closed)

After the archive and manifest are written, the script expands the backup and
scans it for secret-bearing filenames and credential patterns (private keys,
`AKIA…` AWS keys, `sk_live_…`/`rk_live_…` Stripe keys, Slack and GitHub tokens,
JWTs). **If anything matches, the backup is deleted and the run fails** — a leak
is never shipped silently. Override with `PHINS_BACKUP_SKIP_SCAN=true` (not
recommended).

## Database dumps

If you need DB dumps, set `DATABASE_URL` (Postgres) or `SQLITE_PATH` (SQLite) in
the environment **at runtime**. SQLite is captured with `sqlite3 .backup`, which
takes a consistent snapshot even while the database is in use, and the copy must
pass `PRAGMA integrity_check`. There is no plain-copy fallback. If `DATABASE_URL`
or `SQLITE_PATH` is set and the dump cannot be taken, the run fails and the
snapshot is deleted. Dump files are written `0600` and the containing directory
`0700`.

A dump contains live customer data. It must never be committed, and the
git-destination guard above is what enforces that.

Ledger files and other runtime stores are excluded from `platform_snapshot.tar.gz`
and copied under `db/runtime/` only when they exist. Each copy's SHA-256 is
compared to the source before the backup is accepted. When `PHINS_KEYRING_PATH`
or `PHINS_MEDIA_STORAGE_DIR` is set, the path must exist or the run fails — a
backup that silently omitted the keyring could not decrypt vaulted data.

If no database, ledger, or runtime file is present, the script records that in
`db/backup_notes.txt` instead of inventing a dump.

## Repository bundle

`.git` stays out of the code archive (it can contain remote credentials). The
full repository is `repositories/phins.bundle`, created with `git bundle create --all`.
That is every branch, tag, and remote-tracking ref, and every object reachable
from them. Dangling objects and reflogs are not included. Remote URLs are not
written anywhere in the backup.

Before the snapshot is accepted, the script clones the bundle as a mirror and
requires:

- `git bundle verify` to report a complete history
- the mirror's refs to match `repositories/refs.txt`
- the mirror's `HEAD` to match `repositories/HEAD`
- the SHA-256 of the mirror's reachable object ids to match `repositories/objects.sha256`

A shallow clone is refused (`git fetch --unshallow` first). Uncommitted work is
not inside the bundle; it is in the snapshot archive and in `metadata/git_diff_*.patch`.

## Restore from a recorded backup

1. Identify the snapshot:
   ```bash
   bash scripts/restore_from_backup.sh --list
   ```
2. Verify checksums, the repository bundle, SQLite integrity, and the secret scan:
   ```bash
   bash scripts/restore_from_backup.sh --verify <UTC_TIMESTAMP>
   ```
3. Restore **code** from git (preferred) using the commit stored in the record:
   ```bash
   ./restore_platform.sh "$(jq -r .git_commit backups/<UTC_TIMESTAMP>/restore_record.json)"
   ```
   Or extract the snapshot into a staging directory (does not overwrite the repo):
   ```bash
   mkdir -p /tmp/phins-restore && tar xzf backups/<UTC_TIMESTAMP>/platform_snapshot.tar.gz -C /tmp/phins-restore
   ```
4. Restore the **repository** (every ref) from the bundle:
   ```bash
   git clone backups/<UTC_TIMESTAMP>/repositories/phins.bundle /tmp/phins-repo
   ```
5. Restore **database** only when a dump exists under `backups/<UTC_TIMESTAMP>/db/`:
   - Postgres: `pg_restore --no-owner --no-privileges -d "$DATABASE_URL" backups/<UTC_TIMESTAMP>/db/postgres.dump`
   - SQLite: `sqlite3 "$SQLITE_PATH" ".restore 'backups/<UTC_TIMESTAMP>/db/<name>.db'"`
   - Runtime files: copy `backups/<UTC_TIMESTAMP>/db/runtime/` back after checking `restore_record.json` checksums

The recorded catalog at `docs/platform_restore_catalog.json` is metadata only.
Use it to find the git commit and snapshot checksum after the `backups/` volume
is attached; it is not a substitute for the snapshot itself.

## Retention

The newest `PHINS_BACKUP_RETENTION` backups are kept (default `7`); older
timestamped directories are pruned automatically. Set `0` to keep everything.

## Environment reference

| Variable | Purpose |
|---|---|
| `BACKUP_ROOT` | Destination root (default `<workspace>/backups`) |
| `PHINS_BACKUP_RETENTION` | Keep the N newest backups (default `7`, `0` = keep all) |
| `PHINS_BACKUP_ALLOW_IN_REPO` | Bypass the git-destination guard (not recommended) |
| `PHINS_BACKUP_SKIP_SCAN` | Skip the secret scan (not recommended) |
| `PHINS_BACKUP_RECORD_CATALOG` | Write a commit-safe metadata catalog (no archive/dump bytes) |
| `DATABASE_URL` | Enables the Postgres dump |
| `SQLITE_PATH` | Enables the SQLite backup |
