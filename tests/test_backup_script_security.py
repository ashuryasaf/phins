"""Backup pipeline security contract (F1).

A platform snapshot aggregates the whole deployment and can include a full
database dump. The daily backup job previously wrote its output into the
repository working tree, where it was committed — publishing that payload
permanently in git history and to every clone and fork.

These tests pin the guards in ``scripts/backup_platform.sh``:

* it refuses to write where git would track the output,
* real ``.env`` files, database files and keys never enter the archive (while
  safe templates are kept so a restore still documents configuration),
* a credential that reaches a finished backup fails the run and the archive is
  deleted rather than shipped,
* the integrity manifest covers every artifact and ``--verify`` validates it.

The script is exercised against a throwaway workspace, never the real repo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "backup_platform.sh"

pytestmark = pytest.mark.skipif(
    not SCRIPT.exists() or shutil.which("bash") is None,
    reason="backup script or bash unavailable",
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _run_backup(workspace: Path, backup_root: Path, **env_overrides):
    env = {
        **os.environ,
        "WORKSPACE_DIR": str(workspace),
        "BACKUP_ROOT": str(backup_root),
        # Keep the tests independent of the host's retention setting.
        "PHINS_BACKUP_RETENTION": env_overrides.pop("PHINS_BACKUP_RETENTION", "0"),
    }
    # A developer shell may point at a real database or keyring. Tests opt in
    # explicitly so a missing host path cannot abort the fixture backup.
    for key in (
        "DATABASE_URL",
        "DATABASE_PUBLIC_URL",
        "SQLITE_PATH",
        "LEDGER_PERSISTENCE_FILE",
        "PHINS_KEYRING_PATH",
        "PHINS_MEDIA_STORAGE_DIR",
    ):
        env.pop(key, None)
    env.update({k: str(v) for k, v in env_overrides.items()})
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A minimal git-backed workspace that stands in for the platform repo."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (ws / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    (ws / ".env.production.template").write_text("API_KEY=\n", encoding="utf-8")
    (ws / ".gitignore").write_text(".env\nbackups/\n", encoding="utf-8")
    _git(ws, "init", "-q", ".")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "init")
    return ws


def _backup_dirs(backup_root: Path):
    return sorted(p for p in backup_root.glob("*") if p.is_dir())


# ---------------------------------------------------------------------------
# Guard: never write where git would commit the backup
# ---------------------------------------------------------------------------

def test_refuses_to_write_into_a_tracked_path(workspace: Path):
    """The exact failure that committed 35MB of snapshots to the repo."""
    tracked_root = workspace / "committed-backups"  # not in .gitignore
    result = _run_backup(workspace, tracked_root)

    assert result.returncode != 0
    assert "NOT ignored by it" in result.stderr
    # Nothing may be left behind for a later `git add -A` to pick up.
    assert not tracked_root.exists() or not _backup_dirs(tracked_root)


def test_allows_a_gitignored_destination(workspace: Path):
    result = _run_backup(workspace, workspace / "backups")
    assert result.returncode == 0, result.stderr
    assert len(_backup_dirs(workspace / "backups")) == 1


def test_allows_a_destination_outside_the_repository(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode == 0, result.stderr
    assert len(_backup_dirs(outside)) == 1


def test_in_repo_override_is_available_for_operators(workspace: Path):
    tracked_root = workspace / "committed-backups"
    result = _run_backup(workspace, tracked_root, PHINS_BACKUP_ALLOW_IN_REPO="true")
    assert result.returncode == 0, result.stderr
    assert len(_backup_dirs(tracked_root)) == 1


# ---------------------------------------------------------------------------
# Archive contents
# ---------------------------------------------------------------------------

def test_secrets_are_excluded_but_templates_are_kept(workspace: Path, tmp_path: Path):
    """Real .env files at any depth, DB files and keys must not be archived."""
    (workspace / ".env").write_text("DB_PASSWORD=hunter2\n", encoding="utf-8")
    (workspace / ".env.production").write_text("TOKEN=abc\n", encoding="utf-8")
    nested = workspace / "svc"
    nested.mkdir()
    (nested / ".env").write_text("NESTED=secret\n", encoding="utf-8")
    (workspace / "phins.db").write_bytes(b"SQLite format 3\x00")
    (workspace / "server.key").write_text("key-material\n", encoding="utf-8")
    (workspace / "phins_ledger_state.json").write_text("{}\n", encoding="utf-8")

    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode == 0, result.stderr

    archive = _backup_dirs(outside)[0] / "platform_snapshot.tar.gz"
    with tarfile.open(archive) as tar:
        # Strip the "./" prefix only. (str.lstrip removes *characters*, so it
        # would also eat the leading dot of "./.env" and mask a real leak.)
        names = {
            n[2:] if n.startswith("./") else n
            for n in tar.getnames()
        }
    # Guard the guard: the archive must contain recognisable dotfiles, proving
    # the normalisation above did not silently strip leading dots.
    assert ".gitignore" in names

    assert ".env" not in names
    assert ".env.production" not in names
    assert "svc/.env" not in names
    assert "phins.db" not in names
    assert "server.key" not in names
    assert not any(n.startswith("phins_ledger") for n in names)

    # Safe templates and code are still present.
    assert ".env.example" in names
    assert ".env.production.template" in names
    assert "app.py" in names


def test_backup_directory_is_not_world_readable(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    assert _run_backup(workspace, outside).returncode == 0
    mode = (_backup_dirs(outside)[0]).stat().st_mode & 0o777
    assert mode == 0o700, oct(mode)


# ---------------------------------------------------------------------------
# Fail-closed secret scan
# ---------------------------------------------------------------------------

# Credential shapes are assembled at runtime from fragments. A literal
# secret-looking string here would be flagged by push protection and by the
# repository's own gitleaks scan, blocking this very test from being committed.
FAKE_CREDENTIALS = {
    "aws": "aws_key = " + "AKIA" + "IOSFODNN7EXAMPLE",
    "stripe": "stripe: " + "sk_" + "live_" + ("a" * 24),
    "private_key": "-----BEGIN " + "RSA PRIVATE KEY" + "-----\nabc",
    "slack": "slack: " + "xoxb" + "-1234567890-abcdefghijkl",
}


@pytest.mark.parametrize("kind", sorted(FAKE_CREDENTIALS))
def test_credential_in_the_archive_aborts_and_deletes_the_backup(
    workspace: Path, tmp_path: Path, kind: str
):
    filename = f"leak_{kind}.txt"
    (workspace / filename).write_text(FAKE_CREDENTIALS[kind] + "\n", encoding="utf-8")
    outside = tmp_path / "external-backups"

    result = _run_backup(workspace, outside)

    assert result.returncode != 0, "backup with a credential must fail"
    assert "secret material detected" in result.stderr
    # The leaking archive must not survive.
    assert not _backup_dirs(outside)


def test_scan_can_be_skipped_explicitly(workspace: Path, tmp_path: Path):
    (workspace / "notes.txt").write_text(FAKE_CREDENTIALS["aws"] + "\n", encoding="utf-8")
    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside, PHINS_BACKUP_SKIP_SCAN="true")
    assert result.returncode == 0, result.stderr
    assert len(_backup_dirs(outside)) == 1


def test_clean_workspace_reports_a_clean_scan(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode == 0, result.stderr
    assert "Secret scan: clean." in result.stdout
    # The scratch extraction directory must not be left inside the backup.
    assert not (_backup_dirs(outside)[0] / ".scan").exists()


# ---------------------------------------------------------------------------
# Integrity manifest + verify mode
# ---------------------------------------------------------------------------

def test_manifest_covers_every_artifact_and_verifies(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    assert _run_backup(workspace, outside).returncode == 0

    backup = _backup_dirs(outside)[0]
    manifest = (backup / "SHA256SUMS").read_text(encoding="utf-8")
    listed = {line.split(maxsplit=1)[1].strip() for line in manifest.splitlines() if line.strip()}

    on_disk = {
        "./" + str(p.relative_to(backup))
        for p in backup.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS"
    }
    assert on_disk == listed, "manifest does not cover every artifact"

    verify = subprocess.run(
        ["bash", str(SCRIPT), "--verify", str(backup)],
        cwd=workspace,
        env={**os.environ, "WORKSPACE_DIR": str(workspace)},
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0, verify.stderr
    assert "Backup verified" in verify.stdout


def test_verify_accepts_a_relative_backup_path(workspace: Path, tmp_path: Path):
    """BACKUP.md documents `--verify backups/<timestamp>`."""
    outside = tmp_path / "external-backups"
    assert _run_backup(workspace, outside).returncode == 0
    backup = _backup_dirs(outside)[0]

    verify = subprocess.run(
        ["bash", str(SCRIPT), "--verify", f"{outside.name}/{backup.name}"],
        cwd=tmp_path,
        env={**os.environ, "WORKSPACE_DIR": str(workspace)},
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0, verify.stderr
    assert "Backup verified" in verify.stdout


def test_verify_ignores_runtime_files_that_only_look_like_databases(
    workspace: Path, tmp_path: Path
):
    """A customer upload named *.db is checksummed data, not a SQLite dump."""
    documents = workspace / "data" / "documents"
    documents.mkdir(parents=True)
    (documents / "upload.db").write_text("not a database\n", encoding="utf-8")

    outside = tmp_path / "external-backups"
    assert _run_backup(workspace, outside).returncode == 0
    backup = _backup_dirs(outside)[0]
    assert (backup / "db" / "runtime" / "data" / "documents" / "upload.db").is_file()

    verify = subprocess.run(
        ["bash", str(SCRIPT), "--verify", str(backup)],
        cwd=workspace,
        env={**os.environ, "WORKSPACE_DIR": str(workspace)},
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0, verify.stderr


def test_verify_detects_tampering(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    assert _run_backup(workspace, outside).returncode == 0
    backup = _backup_dirs(outside)[0]

    (backup / "metadata" / "system_info.txt").write_text("tampered\n", encoding="utf-8")

    verify = subprocess.run(
        ["bash", str(SCRIPT), "--verify", str(backup)],
        cwd=workspace,
        env={**os.environ, "WORKSPACE_DIR": str(workspace)},
        capture_output=True,
        text=True,
    )
    assert verify.returncode != 0
    assert "FAILED" in verify.stdout + verify.stderr


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_retention_prunes_older_backups(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    outside.mkdir()
    # Pre-existing backups that retention should prune (keep newest 2).
    for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
        (outside / stamp).mkdir()

    result = _run_backup(workspace, outside, PHINS_BACKUP_RETENTION="2")
    assert result.returncode == 0, result.stderr

    remaining = [p.name for p in _backup_dirs(outside)]
    assert len(remaining) == 2
    # The freshly created backup (newest timestamp) is retained.
    assert "20260101T000000Z" not in remaining


# ---------------------------------------------------------------------------
# Repository hygiene
# ---------------------------------------------------------------------------

def test_repo_does_not_track_backup_artifacts():
    """The committed snapshots are gone and cannot come back silently."""
    tracked = subprocess.run(
        ["git", "ls-files", "backups/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tracked == "", f"backup artifacts are tracked again:\n{tracked}"


def test_backups_directory_is_gitignored():
    check = subprocess.run(
        ["git", "check-ignore", "-q", "backups/"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert check.returncode == 0, "backups/ is not gitignored"


# ---------------------------------------------------------------------------
# Restoration record
# ---------------------------------------------------------------------------

RESTORE_HELPER = REPO_ROOT / "scripts" / "restore_from_backup.sh"


def test_backup_writes_a_restore_record_and_index(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode == 0, result.stderr

    backup = _backup_dirs(outside)[0]
    record_path = backup / "restore_record.json"
    assert record_path.is_file()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["backup_id"] == backup.name
    assert record["git_commit"]
    assert record["artifacts"]["platform_snapshot"]["sha256"]
    assert "code_from_git" in record["restore"]
    assert (backup / "RESTORE.txt").is_file()

    index = json.loads((outside / "RESTORE_INDEX.json").read_text(encoding="utf-8"))
    assert index["latest"] == backup.name
    assert index["count"] == 1
    assert index["backups"][0]["git_commit"] == record["git_commit"]


def test_restore_catalog_is_metadata_only(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    catalog = tmp_path / "catalog.json"
    result = _run_backup(
        workspace, outside, PHINS_BACKUP_RECORD_CATALOG=str(catalog)
    )
    assert result.returncode == 0, result.stderr
    assert catalog.is_file()

    payload = catalog.read_bytes()
    assert b"SQLite format" not in payload
    data = json.loads(payload.decode("utf-8"))
    assert data["latest"]
    assert data["backups"][0]["git_commit"]
    assert data["backups"][0]["snapshot_sha256"]
    # Catalog must not embed archive or dump bytes.
    assert len(payload) < 64_000


def test_restore_from_backup_lists_and_prints_commands(workspace: Path, tmp_path: Path):
    outside = tmp_path / "external-backups"
    assert _run_backup(workspace, outside).returncode == 0
    backup = _backup_dirs(outside)[0]
    record = json.loads((backup / "restore_record.json").read_text(encoding="utf-8"))

    listed = subprocess.run(
        ["bash", str(RESTORE_HELPER), "--list"],
        cwd=workspace,
        env={**os.environ, "WORKSPACE_DIR": str(workspace), "BACKUP_ROOT": str(outside)},
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stderr
    assert backup.name in listed.stdout

    commands = subprocess.run(
        ["bash", str(RESTORE_HELPER), "--print-commands", backup.name],
        cwd=workspace,
        env={**os.environ, "WORKSPACE_DIR": str(workspace), "BACKUP_ROOT": str(outside)},
        capture_output=True,
        text=True,
    )
    assert commands.returncode == 0, commands.stderr
    assert record["git_commit"] in commands.stdout
    assert "Verify:" in commands.stdout


def test_failed_secret_scan_is_not_recorded_in_the_index(
    workspace: Path, tmp_path: Path
):
    (workspace / "leak_aws.txt").write_text(FAKE_CREDENTIALS["aws"] + "\n", encoding="utf-8")
    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode != 0
    assert not (outside / "RESTORE_INDEX.json").exists()
    assert not _backup_dirs(outside)


# ---------------------------------------------------------------------------
# Repository bundle + consistent data snapshots
# ---------------------------------------------------------------------------

def _git_out(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_repository_bundle_round_trips_every_ref_without_remote_urls(
    workspace: Path, tmp_path: Path
):
    """The bundle is a complete, verifiable copy of every ref, not .git/config."""
    token = "backup-probe-token-value"
    default_branch = _git_out(workspace, "branch", "--show-current")
    _git(workspace, "remote", "add", "origin", f"https://user:{token}@example.com/phins.git")
    _git(workspace, "checkout", "-q", "-b", "feature")
    (workspace / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(workspace, "add", "feature.txt")
    _git(workspace, "commit", "-qm", "feature")
    _git(workspace, "checkout", "-q", default_branch)

    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Repository bundle: complete history" in result.stdout

    backup = _backup_dirs(outside)[0]
    bundle = backup / "repositories" / "phins.bundle"
    refs = (backup / "repositories" / "refs.txt").read_text(encoding="utf-8")
    assert f"refs/heads/{default_branch}" in refs
    assert "refs/heads/feature" in refs
    assert token.encode() not in bundle.read_bytes()
    leaked = subprocess.run(
        ["grep", "-R", "-F", "-l", token, str(backup)],
        capture_output=True,
        text=True,
    )
    assert leaked.stdout.strip() == ""

    restored = tmp_path / "restored"
    subprocess.run(
        ["git", "clone", "--mirror", str(bundle), str(restored)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert _git_out(restored, "rev-parse", "refs/heads/feature") == _git_out(
        workspace, "rev-parse", "refs/heads/feature"
    )
    assert _git_out(restored, "rev-parse", "HEAD") == (
        backup / "repositories" / "HEAD"
    ).read_text(encoding="utf-8").strip()

    record = json.loads((backup / "restore_record.json").read_text(encoding="utf-8"))
    assert record["artifacts"]["repository_bundle"]["sha256"]
    assert record["artifacts"]["repository_refs"]["ref_count"] >= 2
    assert record["restore"]["repository_from_bundle"]


def test_verify_rejects_a_bundle_whose_refs_were_rewritten(
    workspace: Path, tmp_path: Path
):
    outside = tmp_path / "external-backups"
    assert _run_backup(workspace, outside).returncode == 0
    backup = _backup_dirs(outside)[0]
    (backup / "repositories" / "refs.txt").write_text(
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef refs/heads/missing\n",
        encoding="utf-8",
    )
    # Refresh the manifest so this fails the bundle check, not the checksum check.
    subprocess.run(
        [
            "bash",
            "-c",
            "find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS",
        ],
        cwd=backup,
        check=True,
    )

    verify = subprocess.run(
        ["bash", str(SCRIPT), "--verify", str(backup)],
        cwd=workspace,
        env={**os.environ, "WORKSPACE_DIR": str(workspace)},
        capture_output=True,
        text=True,
    )
    assert verify.returncode != 0
    assert "Repository bundle verification FAILED" in verify.stderr
    # --verify must not delete a backup the operator asked to inspect.
    assert backup.is_dir()
    assert (backup / "repositories" / "phins.bundle").is_file()


def test_sqlite_backup_is_consistent_and_stays_out_of_the_archive(
    workspace: Path, tmp_path: Path
):
    db = workspace / "phins.db"
    subprocess.run(
        [
            "sqlite3",
            str(db),
            "CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT); INSERT INTO t(name) VALUES ('alpha');",
        ],
        check=True,
    )
    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode == 0, result.stderr

    backup = _backup_dirs(outside)[0]
    copied = backup / "db" / "phins.db"
    check = subprocess.run(
        ["sqlite3", str(copied), "PRAGMA integrity_check;"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert check.stdout.strip() == "ok"
    row = subprocess.run(
        ["sqlite3", str(copied), "SELECT name FROM t;"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert row.stdout.strip() == "alpha"
    assert "INSERT INTO t VALUES(1,'alpha');" in (backup / "db" / "phins.db.sql").read_text(encoding="utf-8")

    with tarfile.open(backup / "platform_snapshot.tar.gz") as tar:
        names = {n[2:] if n.startswith("./") else n for n in tar.getnames()}
    assert "phins.db" not in names
    assert "app.py" in names


def test_ledger_file_is_copied_with_matching_checksum(
    workspace: Path, tmp_path: Path
):
    payload = '{"ledger":1}\n'
    source = workspace / "phins_ledger_state.json"
    source.write_text(payload, encoding="utf-8")
    outside = tmp_path / "external-backups"
    result = _run_backup(workspace, outside)
    assert result.returncode == 0, result.stderr

    backup = _backup_dirs(outside)[0]
    copied = backup / "db" / "runtime" / "phins_ledger_state.json"
    assert copied.read_text(encoding="utf-8") == payload
    assert (copied.stat().st_mode & 0o777) == 0o600
    with tarfile.open(backup / "platform_snapshot.tar.gz") as tar:
        names = {n[2:] if n.startswith("./") else n for n in tar.getnames()}
    assert "phins_ledger_state.json" not in names

    record = json.loads((backup / "restore_record.json").read_text(encoding="utf-8"))
    copied_entry = next(
        item for item in record["artifacts"]["db_files"]
        if item["path"] == "db/runtime/phins_ledger_state.json"
    )
    assert copied_entry["sha256"]
    assert record["has_db_dump"] is True


def test_configured_database_that_cannot_be_dumped_discards_the_backup(
    workspace: Path, tmp_path: Path
):
    outside = tmp_path / "external-backups"
    result = _run_backup(
        workspace,
        outside,
        DATABASE_URL="postgresql://127.0.0.1:1/phins",
    )
    assert result.returncode != 0
    assert "refusing" in result.stderr
    assert not _backup_dirs(outside)
