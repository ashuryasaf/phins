# Platform restore record

Latest recorded snapshot (metadata only — the archive itself is not in git):

| Field | Value |
|---|---|
| Backup ID | `20260905T091343Z` |
| Created | 2026-09-05 09:13:44 UTC |
| Git commit | `25ecaa013ed5c7cb7670618f6f3de63ea4c2e133` |
| Snapshot SHA-256 | `755c5a723bbc4a28c1b61b41282aa463ed61875767e549e7c8de65e863dfce3b` |
| Snapshot size | 8,163,623 bytes |
| Database dump | none (`DATABASE_URL` and `SQLITE_PATH` / `phins.db` were unset) |
| Local path | `backups/20260905T091343Z/` |

## Restore

```bash
# List recorded snapshots
bash scripts/restore_from_backup.sh --list

# Verify checksums + secret scan
bash scripts/restore_from_backup.sh --verify 20260905T091343Z

# Code from git
./restore_platform.sh 25ecaa013ed5c7cb7670618f6f3de63ea4c2e133

# Or extract the snapshot to a staging directory (does not overwrite the repo)
mkdir -p /tmp/phins-restore-20260905T091343Z
tar xzf backups/20260905T091343Z/platform_snapshot.tar.gz -C /tmp/phins-restore-20260905T091343Z
```

Machine-readable catalog: `docs/platform_restore_catalog.json`.
Full operator guide: `BACKUP.md`.
