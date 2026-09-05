# Platform restore record

Latest recorded snapshot (metadata only — the archive itself is not in git):

| Field | Value |
|---|---|
| Backup ID | `20260905T091515Z` |
| Created | 2026-09-05 09:15:16 UTC |
| Git commit | `fab28047f4abbbff9b36940beeb5fd0a99426138` |
| Working tree | clean |
| Snapshot SHA-256 | `839c4d9a119d03dc7498129100aa418eb9b7eedeefe779d6b1ab9d4d363a78aa` |
| Snapshot size | 8,166,130 bytes |
| Database dump | none (`DATABASE_URL` and `SQLITE_PATH` / `phins.db` were unset) |
| Local path | `backups/20260905T091515Z/` |

An earlier snapshot (`20260905T091343Z`, git `25ecaa01`, dirty working tree) remains on the local volume and in the catalog.

## Restore

```bash
# List recorded snapshots
bash scripts/restore_from_backup.sh --list

# Verify checksums + secret scan
bash scripts/restore_from_backup.sh --verify 20260905T091515Z

# Code from git
./restore_platform.sh fab28047f4abbbff9b36940beeb5fd0a99426138

# Or extract the snapshot to a staging directory (does not overwrite the repo)
mkdir -p /tmp/phins-restore-20260905T091515Z
tar xzf backups/20260905T091515Z/platform_snapshot.tar.gz -C /tmp/phins-restore-20260905T091515Z
```

Machine-readable catalog: `docs/platform_restore_catalog.json`.
Full operator guide: `BACKUP.md`.
