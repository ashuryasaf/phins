"""
Regression tests for project-relative storage path defaults.
"""

import os
import sys
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.contribution_payment_service as contribution_payment_service
import services.foundation_persistence_service as foundation_persistence_service
import services.ledger_backup_service as ledger_backup_service
import web_portal.server as portal_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestStoragePathDefaults:
    def test_portal_upload_storage_defaults_are_project_relative(self):
        assert portal_server.UPLOAD_STORAGE_DIR == str(PROJECT_ROOT / "data" / "uploads")
        assert portal_server.MEDIA_STORAGE_DIR == str(PROJECT_ROOT / "data" / "media")
        assert portal_server.LEDGER_PERSISTENCE_FILE == str(PROJECT_ROOT / "data" / "phins_ledger_data.json")

    def test_document_upload_default_is_project_relative(self, monkeypatch):
        created_dirs = []
        expected_dir = str(PROJECT_ROOT / "uploads" / "contributions")

        monkeypatch.delenv("WORKSPACE_PATH", raising=False)
        monkeypatch.setattr(
            contribution_payment_service.os,
            "makedirs",
            lambda path, exist_ok=True: created_dirs.append(path)
        )

        handler = contribution_payment_service.DocumentUploadHandler()

        assert handler.upload_dir == expected_dir
        assert created_dirs == [expected_dir]

    def test_document_upload_falls_back_to_temp_dir_on_permission_error(self, monkeypatch, tmp_path):
        created_dirs = []
        expected_dir = str(PROJECT_ROOT / "uploads" / "contributions")
        expected_fallback = os.path.join(
            str(tmp_path),
            "phins",
            "uploads",
            "contributions"
        )

        def fake_makedirs(path, exist_ok=True):
            created_dirs.append(path)
            if path == expected_dir:
                raise PermissionError("read-only filesystem")

        monkeypatch.delenv("WORKSPACE_PATH", raising=False)
        monkeypatch.setattr(contribution_payment_service.os, "makedirs", fake_makedirs)
        monkeypatch.setattr(
            contribution_payment_service.tempfile,
            "gettempdir",
            lambda: str(tmp_path)
        )

        handler = contribution_payment_service.DocumentUploadHandler()

        assert handler.upload_dir == expected_fallback
        assert created_dirs == [expected_dir, expected_fallback]

    def test_foundation_persistence_default_is_project_relative(self, monkeypatch):
        created_dirs = []
        expected_dir = str(PROJECT_ROOT / "data" / "foundations")
        expected_backup_dir = os.path.join(expected_dir, "backups")

        monkeypatch.delenv("WORKSPACE_PATH", raising=False)
        monkeypatch.setattr(
            foundation_persistence_service.os,
            "makedirs",
            lambda path, exist_ok=True: created_dirs.append(path)
        )

        service = foundation_persistence_service.FoundationPersistenceService()

        assert service.data_dir == expected_dir
        assert service.backup_dir == expected_backup_dir
        assert created_dirs == [expected_dir, expected_backup_dir]

    def test_ledger_backup_default_is_project_relative(self, monkeypatch):
        created_dirs = []
        expected_dir = str(PROJECT_ROOT / "data" / "backups")
        expected_children = [
            os.path.join(expected_dir, "ledgers"),
            os.path.join(expected_dir, "transactions"),
            os.path.join(expected_dir, "foundations"),
            os.path.join(expected_dir, "billing"),
        ]

        monkeypatch.delenv("WORKSPACE_PATH", raising=False)
        monkeypatch.setattr(
            ledger_backup_service.os,
            "makedirs",
            lambda path, exist_ok=True: created_dirs.append(path)
        )

        service = ledger_backup_service.LedgerBackupService()

        assert service.backup_base_dir == expected_dir
        assert created_dirs == expected_children
