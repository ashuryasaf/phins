import hashlib
import importlib.util
import json
import tarfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "create_full_platform_backup.py"


def _load_backup_module():
    spec = importlib.util.spec_from_file_location("create_full_platform_backup", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load backup script module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_script_writes_manifest_with_hashes(monkeypatch, tmp_path):
    module = _load_backup_module()
    backup_dir = tmp_path / "backups" / "20260322T000000Z"
    metadata_dir = backup_dir / "metadata"
    runtime_dir = backup_dir / "runtime_data"
    db_dir = backup_dir / "db"
    uploads_dir = backup_dir / "uploads"
    archive_path = backup_dir / "platform_backup_20260322T000000Z.tar.gz"
    repo_snapshot_path = backup_dir / "repo_snapshot.tar.gz"
    manifest_path = backup_dir / "manifest.json"

    for path in [metadata_dir, runtime_dir, db_dir, uploads_dir]:
        path.mkdir(parents=True, exist_ok=True)

    repo_snapshot_path.write_bytes(b"repo-snapshot")
    archive_path.write_bytes(b"downloadable-archive")
    (runtime_dir / "phins_ledger_data.json").write_text('{"ok": true}', encoding="utf-8")
    (metadata_dir / "system_info.txt").write_text("platform=test\n", encoding="utf-8")

    monkeypatch.setattr(module, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(module, "DOWNLOADABLE_ARCHIVE", archive_path)
    monkeypatch.setattr(module, "REPO_SNAPSHOT", repo_snapshot_path)
    monkeypatch.setattr(module, "MANIFEST_PATH", manifest_path)

    manifest = module._build_manifest(
        notes=["unit test"],
        git_meta={"git_commit.txt": {"exit_code": 0}},
        runtime_copy_summary={"files": ["phins_ledger_data.json"], "directories": []},
        db_outputs=[],
    )

    assert manifest_path.exists()
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["downloadable_archive"] == archive_path.name
    assert saved["repo_snapshot"] == repo_snapshot_path.name
    paths = {item["path"] for item in saved["files"]}
    assert "repo_snapshot.tar.gz" in paths
    assert "runtime_data/phins_ledger_data.json" in paths
    archive_entry = next(item for item in saved["files"] if item["path"] == archive_path.name)
    assert archive_entry["sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()


def test_backup_script_creates_downloadable_archive_without_self_inclusion(monkeypatch, tmp_path):
    module = _load_backup_module()
    backup_dir = tmp_path / "backups" / "20260322T000001Z"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "metadata").mkdir()
    (backup_dir / "metadata" / "system_info.txt").write_text("ok\n", encoding="utf-8")
    (backup_dir / "runtime_data").mkdir()
    (backup_dir / "runtime_data" / "phins_ledger_data.json").write_text('{"ok": true}', encoding="utf-8")
    archive_path = backup_dir / "platform_backup_20260322T000001Z.tar.gz"

    monkeypatch.setattr(module, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(module, "DOWNLOADABLE_ARCHIVE", archive_path)

    module._create_downloadable_archive(notes=[])

    assert archive_path.exists()
    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
    assert "metadata/system_info.txt" in names
    assert "runtime_data/phins_ledger_data.json" in names
    assert archive_path.name not in names
