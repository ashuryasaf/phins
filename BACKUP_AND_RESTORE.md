# Backup & Restore (PHINS Platform)

This repo supports **PostgreSQL** (production) and **SQLite** (local/dev). Use the provided script to create a **timestamped backup folder** and to restore from it.

## What gets backed up

- **Database**
  - **Postgres**: `pg_dump` custom-format file: `db/postgres.dump`
  - **SQLite**: `db/sqlite.db` (created via `sqlite3 .backup` when available)
- **Optional file snapshot**: `files/app_files.tar.gz` (useful for offline/air‑gapped restores)
- **Metadata**: `manifest.json` + `SHA256SUMS.txt` (best-effort)

## Backup

```bash
./scripts/phins_backup.sh backup
```

Custom output directory:

```bash
./scripts/phins_backup.sh backup --out /var/backups/phins
```

Database-only (skip tarball):

```bash
./scripts/phins_backup.sh backup --no-files
```

## Restore

Restore requires the same DB environment variables you’d use to run the app.

### Restore to PostgreSQL

Set `DATABASE_URL` (or `DB_HOST`/`DB_*`) to the **target** database, then:

```bash
./scripts/phins_backup.sh restore --from backups/phins_YYYYmmdd_HHMMSS
```

### Restore to SQLite

Optionally set `SQLITE_PATH` (default is `./phins.db` in repo root), then:

```bash
./scripts/phins_backup.sh restore --from backups/phins_YYYYmmdd_HHMMSS
```

## Environment variables (detection)

- **Postgres**
  - `DATABASE_URL=postgresql://...` (or `postgres://...`)
  - or `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- **SQLite**
  - `USE_SQLITE=1`
  - and/or `SQLITE_PATH=/path/to/phins.db`

## Operational notes (recommended)

- **Before backup**: stop writes (or stop the server) to avoid inconsistent snapshots, especially for SQLite when `sqlite3` is not installed.
- **Protect backups**: backups may contain PII; store them encrypted and access-controlled.

