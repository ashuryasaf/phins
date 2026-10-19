# Platform restore record

Latest recorded snapshot on this volume (metadata only — the archive and the git bundle are not in git):

| Field | Value |
|---|---|
| Backup ID | `20261019T060332Z` |
| Created | 2026-10-19 06:03:43 UTC |
| Git commit | `bf3454d672b12728c5cd96fdd807769ab4e7c4ab` |
| Working tree | clean |
| Refs in bundle | 805 |
| Bundle SHA-256 | `cedf7eb4907b7c5c3e6e79dcdb6312ac6e851bd3319ed62dd8cf4930f60edecb` |
| Bundle size | 442,409,468 bytes |
| Snapshot SHA-256 | `eea4fa0ef7da1b8fdd56e0862870bd4c3e4180f35bd690859b8c20f341b89828` |
| Snapshot size | 21,582,446 bytes |
| Database dump | none (`DATABASE_URL`, `SQLITE_PATH` / `phins.db`, ledger files, keyring, and media store were unset or absent) |
| Local path | `backups/20261019T060332Z/` |
| Verification | checksums match, bundle round-trips (805 refs, HEAD, object set), secret scan clean |

## Restore

```bash
# List recorded snapshots
bash scripts/restore_from_backup.sh --list

# Verify checksums, the repository bundle, and the secret scan
bash scripts/restore_from_backup.sh --verify 20261019T060332Z

# Every branch, tag, and remote-tracking ref
git clone backups/20261019T060332Z/repositories/phins.bundle /tmp/phins-repo-20261019T060332Z

# Code from the recorded commit
./restore_platform.sh bf3454d672b12728c5cd96fdd807769ab4e7c4ab

# Or extract the snapshot to a staging directory (does not overwrite the repo)
mkdir -p /tmp/phins-restore-20261019T060332Z
tar xzf backups/20261019T060332Z/platform_snapshot.tar.gz -C /tmp/phins-restore-20261019T060332Z
```

No database dump was produced. This machine had no `DATABASE_URL`, no `phins.db`, no ledger file, no keyring, and no media store. Restoring customer data requires a later run wherever those paths are configured.

Machine-readable catalog: `docs/platform_restore_catalog.json`.
Full operator guide: `BACKUP.md`.

## Earlier snapshots

Metadata-only (archives for these snapshots live on their origin volumes, not in git). Checksums are kept so a reattached volume can still be verified.

| Backup ID | Git commit | Snapshot SHA-256 |
|---|---|---|
| `20261010T122007Z` | `49ddc064bdfdd55e00f8a3950c33de041c4241fa` | `53a69e4cbaf2370ad801d3e4438ffe4a28114c2a70c46df35facbe830055b485` |
| `20260905T091515Z` | `fab28047f4abbbff9b36940beeb5fd0a99426138` | `839c4d9a119d03dc7498129100aa418eb9b7eedeefe779d6b1ab9d4d363a78aa` |
| `20260905T091343Z` | `25ecaa013ed5c7cb7670618f6f3de63ea4c2e133` | `755c5a723bbc4a28c1b61b41282aa463ed61875767e549e7c8de65e863dfce3b` |
