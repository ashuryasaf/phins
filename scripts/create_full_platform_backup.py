#!/usr/bin/env python3
"""
Create a comprehensive PHINS platform backup with integrity metadata.

Outputs a timestamped directory under backups/ containing:
- repo_snapshot.tar.gz          source/config/docs snapshot (excluding secrets and generated backups)
- runtime_data/                persisted platform state files copied as-is
- uploads/                     platform uploads/media copies when present
- db/                          optional database dumps/copies
- metadata/                    git + environment-independent system metadata
- manifest.json                structured backup manifest with SHA256 checksums
- platform_backup_<ts>.tar.gz  downloadable archive of the entire backup folder
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKUP_ROOT = Path(os.environ.get("BACKUP_ROOT", str(REPO_ROOT / "backups")))
TIMESTAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BACKUP_DIR = BACKUP_ROOT / TIMESTAMP
METADATA_DIR = BACKUP_DIR / "metadata"
RUNTIME_DATA_DIR = BACKUP_DIR / "runtime_data"
DB_DIR = BACKUP_DIR / "db"
UPLOADS_DIR = BACKUP_DIR / "uploads"
DOWNLOADABLE_ARCHIVE = BACKUP_DIR / f"platform_backup_{TIMESTAMP}.tar.gz"
REPO_SNAPSHOT = BACKUP_DIR / "repo_snapshot.tar.gz"
MANIFEST_PATH = BACKUP_DIR / "manifest.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: List[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(
            cmd,
            returncode=127,
            stdout="",
            stderr=str(exc),
        )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_if_exists(src: Path, dest: Path, notes: List[str], *, label: str) -> bool:
    if not src.exists():
        notes.append(f"{label} not found: {src}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dest)
    return True


def _safe_rel(path: Path) -> str:
    return path.relative_to(BACKUP_DIR).as_posix()


def _load_runtime_paths() -> Dict[str, Path]:
    import web_portal.server as portal

    return {
        "ledger_persistence_file": Path(portal.LEDGER_PERSISTENCE_FILE),
        "media_storage_dir": Path(portal.MEDIA_STORAGE_DIR),
        "dynamic_customers_file": (REPO_ROOT / "database" / "dynamic_customers.json"),
        "invitation_codes_file": Path(portal.INVITATION_CODES_FILE),
        "uploads_dir": Path(os.environ.get("PHINS_UPLOAD_DIR", str(REPO_ROOT / "uploads"))),
    }


def _create_repo_snapshot(notes: List[str]) -> None:
    excludes = [
        ".git",
        "backups",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        ".env",
    ]
    with tarfile.open(REPO_SNAPSHOT, "w:gz") as archive:
        for root, dirs, files in os.walk(REPO_ROOT):
            root_path = Path(root)
            rel_root = root_path.relative_to(REPO_ROOT).as_posix()
            if any(part in excludes for part in root_path.parts):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in excludes]
            for filename in files:
                file_path = root_path / filename
                rel_path = file_path.relative_to(REPO_ROOT)
                if any(part in excludes for part in rel_path.parts):
                    continue
                archive.add(file_path, arcname=rel_path.as_posix())
    notes.append("Created repository snapshot archive")


def _capture_git_metadata() -> Dict[str, Any]:
    git_meta: Dict[str, Any] = {}
    if not (REPO_ROOT / ".git").exists():
        return git_meta

    commands = {
        "git_commit.txt": ["git", "rev-parse", "HEAD"],
        "git_status.txt": ["git", "status"],
        "git_status_porcelain.txt": ["git", "status", "--porcelain=v1"],
        "git_log_20.txt": ["git", "log", "-n", "20", "--oneline"],
        "git_diff_unstaged.patch": ["git", "diff"],
        "git_diff_staged.patch": ["git", "diff", "--cached"],
    }
    for filename, cmd in commands.items():
        result = _run(cmd, cwd=REPO_ROOT)
        _write_text(METADATA_DIR / filename, result.stdout if result.stdout else result.stderr)
        git_meta[filename] = {"exit_code": result.returncode}
    return git_meta


def _capture_system_metadata() -> None:
    lines = [
        f"timestamp_utc={TIMESTAMP}",
        f"hostname={socket.gethostname()}",
        f"platform={platform.platform()}",
        f"python={platform.python_version()}",
    ]
    for label, cmd in [
        ("python3", ["python3", "-V"]),
        ("sqlite3", ["sqlite3", "--version"]),
        ("pg_dump", ["pg_dump", "--version"]),
    ]:
        result = _run(cmd)
        lines.append(f"{label}={(result.stdout or result.stderr).strip()}")
    _write_text(METADATA_DIR / "system_info.txt", "\n".join(lines) + "\n")


def _copy_runtime_state(notes: List[str]) -> Dict[str, List[str]]:
    runtime_paths = _load_runtime_paths()
    copied: Dict[str, List[str]] = {"files": [], "directories": []}

    file_targets = {
        "ledger_persistence_file": RUNTIME_DATA_DIR / "phins_ledger_data.json",
        "dynamic_customers_file": RUNTIME_DATA_DIR / "dynamic_customers.json",
        "invitation_codes_file": RUNTIME_DATA_DIR / "invitation_codes.json",
    }
    for label, dest in file_targets.items():
        src = runtime_paths[label]
        if _copy_if_exists(src, dest, notes, label=label):
            copied["files"].append(dest.name)

    dir_targets = {
        "media_storage_dir": UPLOADS_DIR / "media_storage",
        "uploads_dir": UPLOADS_DIR / "uploads",
    }
    for label, dest in dir_targets.items():
        src = runtime_paths[label]
        if _copy_if_exists(src, dest, notes, label=label):
            copied["directories"].append(dest.name)

    return copied


def _capture_database_backups(notes: List[str]) -> List[str]:
    outputs: List[str] = []
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        result = _run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(DB_DIR / "postgres.dump"), database_url]
        )
        if result.returncode == 0 and (DB_DIR / "postgres.dump").exists():
            outputs.append("postgres.dump")
        else:
            notes.append("Postgres dump failed or pg_dump unavailable")
            _write_text(DB_DIR / "postgres_dump_error.txt", result.stdout + result.stderr)
    else:
        notes.append("DATABASE_URL not set; skipped Postgres dump")

    sqlite_candidates = []
    sqlite_path = os.environ.get("SQLITE_PATH", "").strip()
    if sqlite_path:
        sqlite_candidates.append(Path(sqlite_path))
    default_sqlite = REPO_ROOT / "phins.db"
    if default_sqlite.exists():
        sqlite_candidates.append(default_sqlite)

    seen: set[str] = set()
    for candidate in sqlite_candidates:
        if not candidate.exists():
            notes.append(f"SQLite candidate missing: {candidate}")
            continue
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        db_copy = DB_DIR / candidate.name
        shutil.copy2(candidate, db_copy)
        outputs.append(db_copy.name)
        result = _run(["sqlite3", str(candidate), ".dump"])
        if result.returncode == 0:
            dump_path = DB_DIR / f"{candidate.name}.sql"
            _write_text(dump_path, result.stdout)
            outputs.append(dump_path.name)
        else:
            notes.append(f"SQLite dump failed for {candidate}")
            _write_text(DB_DIR / f"{candidate.name}.dump_error.txt", result.stdout + result.stderr)

    return outputs


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def _create_downloadable_archive(notes: List[str]) -> None:
    with tarfile.open(DOWNLOADABLE_ARCHIVE, "w:gz") as archive:
        for item in sorted(BACKUP_DIR.iterdir()):
            if item == DOWNLOADABLE_ARCHIVE:
                continue
            archive.add(item, arcname=item.name)
    notes.append("Created downloadable backup archive")


def _build_manifest(notes: List[str], git_meta: Dict[str, Any], runtime_copy_summary: Dict[str, List[str]], db_outputs: List[str]) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    for path in _iter_files(BACKUP_DIR):
        if path == MANIFEST_PATH:
            continue
        files.append(
            {
                "path": _safe_rel(path),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )

    manifest = {
        "backup_version": "3.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backup_root": str(BACKUP_DIR),
        "downloadable_archive": DOWNLOADABLE_ARCHIVE.name,
        "repo_snapshot": REPO_SNAPSHOT.name,
        "notes": notes,
        "git": git_meta,
        "runtime_copy_summary": runtime_copy_summary,
        "database_outputs": db_outputs,
        "files": files,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    notes: List[str] = []
    git_meta = _capture_git_metadata()
    _capture_system_metadata()
    _create_repo_snapshot(notes)
    runtime_copy_summary = _copy_runtime_state(notes)
    db_outputs = _capture_database_backups(notes)
    _create_downloadable_archive(notes)
    manifest = _build_manifest(notes, git_meta, runtime_copy_summary, db_outputs)

    print(json.dumps(
        {
            "backup_dir": str(BACKUP_DIR),
            "downloadable_archive": str(DOWNLOADABLE_ARCHIVE),
            "manifest": str(MANIFEST_PATH),
            "file_count": len(manifest["files"]),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
