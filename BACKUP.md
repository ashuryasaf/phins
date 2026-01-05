# Platform Backup

This repo includes a repeatable backup script that creates a timestamped bundle containing:

- **System snapshot**: code + configs + docs + static assets + pipeline definitions
- **Metadata**: git commit/status/diffs + environment-independent system info
- **Data dump (optional)**:
  - Postgres: uses `DATABASE_URL` + `pg_dump` when available
  - SQLite: uses `SQLITE_PATH` or `phins.db` when present

## Run backup

```bash
bash scripts/backup_platform.sh
```

## Outputs

Backups are written under:

- `backups/<UTC_TIMESTAMP>/platform_snapshot.tar.gz`
- `backups/<UTC_TIMESTAMP>/db/` (dump files or `backup_notes.txt`)
- `backups/<UTC_TIMESTAMP>/metadata/`
- `backups/<UTC_TIMESTAMP>/SHA256SUMS`

## Notes (secrets)

- The backup intentionally **does not export environment variables** to avoid capturing secrets.
- If you need DB dumps, set `DATABASE_URL` (Postgres) or `SQLITE_PATH` (SQLite) in the environment **at runtime**.

