"""
Tests for demo/test fixture seeding gating.

Covers:
- demo_data_seeding_enabled() env-flag behavior (POPULATE_DEMO_DATA and
  production detection via PHINS_ENVIRONMENT)
- seed_demo_documents() honoring the gate
- database.seeds._is_db_backed_store() detection used to skip redundant
  in-memory mirror writes when the server stores are DatabaseDict wrappers
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import web_portal.server as portal
from database.seeds import _is_db_backed_store


class TestDemoDataSeedingEnabled:
    def test_enabled_by_default_in_test_mode(self, monkeypatch):
        monkeypatch.setenv('PHINS_TEST_MODE', 'true')
        monkeypatch.delenv('POPULATE_DEMO_DATA', raising=False)
        assert portal.demo_data_seeding_enabled() is True

    def test_disabled_when_populate_demo_data_false(self, monkeypatch):
        monkeypatch.setenv('PHINS_TEST_MODE', 'true')
        monkeypatch.setenv('POPULATE_DEMO_DATA', 'false')
        assert portal.demo_data_seeding_enabled() is False

    def test_explicit_true_enables(self, monkeypatch):
        monkeypatch.setenv('PHINS_TEST_MODE', 'true')
        monkeypatch.setenv('POPULATE_DEMO_DATA', 'true')
        assert portal.demo_data_seeding_enabled() is True

    def test_production_disables_even_with_flag_true(self, monkeypatch):
        # Same safety net as scripts/entrypoint.sh db-init: production wins
        # over an explicit POPULATE_DEMO_DATA=true.
        monkeypatch.delenv('PHINS_TEST_MODE', raising=False)
        monkeypatch.setenv('PHINS_ENVIRONMENT', 'production')
        monkeypatch.setenv('POPULATE_DEMO_DATA', 'true')
        assert portal.demo_data_seeding_enabled() is False

    def test_staging_honors_flag(self, monkeypatch):
        monkeypatch.delenv('PHINS_TEST_MODE', raising=False)
        monkeypatch.setenv('PHINS_ENVIRONMENT', 'staging')
        monkeypatch.setenv('POPULATE_DEMO_DATA', 'true')
        assert portal.demo_data_seeding_enabled() is True
        monkeypatch.setenv('POPULATE_DEMO_DATA', 'false')
        assert portal.demo_data_seeding_enabled() is False


class TestSeedDemoDocumentsGating:
    def _clear_docs(self):
        saved = dict(portal.POLICY_DOCUMENTS)
        portal.POLICY_DOCUMENTS.clear()
        return saved

    def test_skips_when_demo_data_disabled(self, monkeypatch):
        saved = self._clear_docs()
        try:
            monkeypatch.setenv('PHINS_TEST_MODE', 'true')
            monkeypatch.setenv('POPULATE_DEMO_DATA', 'false')
            portal.seed_demo_documents()
            assert portal.POLICY_DOCUMENTS == {}, (
                'seed_demo_documents must not seed when demo data is disabled'
            )
        finally:
            portal.POLICY_DOCUMENTS.clear()
            portal.POLICY_DOCUMENTS.update(saved)

    def test_seeds_when_demo_data_enabled(self, monkeypatch):
        saved = self._clear_docs()
        try:
            monkeypatch.setenv('PHINS_TEST_MODE', 'true')
            monkeypatch.delenv('POPULATE_DEMO_DATA', raising=False)
            portal.seed_demo_documents()
            assert len(portal.POLICY_DOCUMENTS) > 0
        finally:
            portal.POLICY_DOCUMENTS.clear()
            portal.POLICY_DOCUMENTS.update(saved)


class TestDbBackedStoreDetection:
    def test_plain_dict_is_not_db_backed(self):
        assert _is_db_backed_store({}) is False

    def test_database_dict_is_db_backed(self):
        from database.data_access import DatabaseDict
        assert _is_db_backed_store(DatabaseDict('customers')) is True
