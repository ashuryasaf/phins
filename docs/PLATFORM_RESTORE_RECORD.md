# Platform restore record

Latest recorded snapshot on this volume (metadata only — the archive and the git bundle are not in git):

| Field | Value |
|---|---|
| Backup ID | `20261010T122007Z` |
| Created | 2026-10-10 12:20:19 UTC |
| Git commit | `49ddc064bdfdd55e00f8a3950c33de041c4241fa` |
| Working tree | clean |
| Refs in bundle | 784 |
| Bundle SHA-256 | `b2c44fadf417e730903b8fa45262d310424b36ae826569f74c2231cb04d1d9da` |
| Bundle size | 437,052,142 bytes |
| Snapshot SHA-256 | `53a69e4cbaf2370ad801d3e4438ffe4a28114c2a70c46df35facbe830055b485` |
| Snapshot size | 23,734,556 bytes |
| Database dump | none (`DATABASE_URL`, `SQLITE_PATH` / `phins.db`, ledger files, keyring, and media store were unset or absent) |
| Local path | `backups/20261010T122007Z/` |
| Verification | checksums match, bundle round-trips (784 refs, HEAD, object set), secret scan clean |

## Restore

```bash
# List recorded snapshots
bash scripts/restore_from_backup.sh --list

# Verify checksums, the repository bundle, and the secret scan
bash scripts/restore_from_backup.sh --verify 20261010T122007Z

# Every branch, tag, and remote-tracking ref
git clone backups/20261010T122007Z/repositories/phins.bundle /tmp/phins-repo-20261010T122007Z

# Code from the recorded commit
./restore_platform.sh 49ddc064bdfdd55e00f8a3950c33de041c4241fa

# Or extract the snapshot to a staging directory (does not overwrite the repo)
mkdir -p /tmp/phins-restore-20261010T122007Z
tar xzf backups/20261010T122007Z/platform_snapshot.tar.gz -C /tmp/phins-restore-20261010T122007Z
```

No database dump was produced. This machine had no `DATABASE_URL`, no `phins.db`, no ledger file, no keyring, and no media store. Restoring customer data requires a later run wherever those paths are configured.

Machine-readable catalog: `docs/platform_restore_catalog.json`.
Full operator guide: `BACKUP.md`.

## Earlier volume

These snapshots were recorded on 2026-09-05. Their archives are not on this volume; the checksums are kept so they can still be checked if that volume is attached.

| Backup ID | Git commit | Snapshot SHA-256 |
|---|---|---|
| `20260905T091515Z` | `fab28047f4abbbff9b36940beeb5fd0a99426138` | `839c4d9a119d03dc7498129100aa418eb9b7eedeefe779d6b1ab9d4d363a78aa` |
| `20260905T091343Z` | `25ecaa013ed5c7cb7670618f6f3de63ea4c2e133` | `755c5a723bbc4a28c1b61b41282aa463ed61875767e549e7c8de65e863dfce3b` |
