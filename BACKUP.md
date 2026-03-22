# Platform Backup

This repo includes repeatable backup tooling that creates a timestamped bundle containing:

- **System snapshot**: code + configs + docs + static assets + pipeline definitions
- **Runtime platform data**:
  - ledger persistence file (`LEDGER_PERSISTENCE_FILE`) when present
  - dynamic customer and invitation JSON stores
  - media storage files
  - uploads directory
  - optional Postgres / SQLite dumps
- **Metadata**: git commit/status/diffs + environment-independent system info
- **Integrity material**:
  - `backup_manifest.json`
  - `SHA256SUMS`
  - per-file SHA256 entries for copied artifacts and archive outputs

## Run backup

```bash
bash scripts/backup_platform.sh
```

Or run the Python utility directly:

```bash
python3 scripts/create_full_platform_backup.py
```

## Outputs

Backups are written under:

- `backups/<UTC_TIMESTAMP>/platform_snapshot.tar.gz`
- `backups/<UTC_TIMESTAMP>/download/phins_platform_backup_<UTC_TIMESTAMP>.tar.gz`
- `backups/<UTC_TIMESTAMP>/runtime/`
- `backups/<UTC_TIMESTAMP>/db/` (dump files or `backup_notes.txt`)
- `backups/<UTC_TIMESTAMP>/metadata/`
- `backups/<UTC_TIMESTAMP>/backup_manifest.json`
- `backups/<UTC_TIMESTAMP>/SHA256SUMS`

The file under `download/` is the portable, downloadable backup bundle intended
to be transferred or archived outside the repository.

## Integrity validation

Each backup includes:

- a structured `backup_manifest.json`
- SHA256 checksums for all copied artifacts
- a downloadable tarball whose checksum is also included in `SHA256SUMS`

You can verify integrity with:

```bash
cd backups/<UTC_TIMESTAMP>
sha256sum -c SHA256SUMS
```

## Notes (secrets)

- The backup intentionally **does not export environment variables** to avoid capturing secrets.
- If you need DB dumps, set `DATABASE_URL` (Postgres) or `SQLITE_PATH` (SQLite) in the environment **at runtime**.
- The backup does capture runtime data files already persisted by PHINS, such as
  the ledger persistence file, media storage, uploads, and git-tracked JSON
  stores, but it does not serialize raw secret values from environment variables.

