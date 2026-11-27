"""U1: production boot fail-closed for durable DB + non-ephemeral ledger."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from security.boot_integrity import (
    database_required,
    ephemeral_ledger_forbidden,
    ledger_path_is_ephemeral,
    refuse_ephemeral_ledger_boot,
    refuse_in_memory_boot,
)


def test_database_required_defaults_true_in_real_production():
    assert database_required({
        "PHINS_ENVIRONMENT": "production",
        "RAILWAY_ENVIRONMENT": "production",
    }) is True


def test_database_required_false_in_test_mode_even_if_labeled_production():
    assert database_required({
        "PHINS_ENVIRONMENT": "production",
        "PHINS_TEST_MODE": "true",
    }) is False


@pytest.mark.parametrize(
    "railway_env",
    ("pr-788", "phins-pr-788", "phins-pr-529-5eb7"),
)
def test_database_required_false_on_railway_pr_preview(railway_env):
    """PR previews inherit PHINS_ENVIRONMENT=production; must not abort."""
    assert database_required({
        "PHINS_ENVIRONMENT": "production",
        "RAILWAY_ENVIRONMENT": railway_env,
    }) is False


def test_database_required_explicit_false_wins_in_production():
    assert database_required({
        "PHINS_ENVIRONMENT": "production",
        "PHINS_REQUIRE_DATABASE": "false",
    }) is False


def test_database_required_explicit_true_wins_outside_production():
    assert database_required({
        "PHINS_ENVIRONMENT": "development",
        "PHINS_REQUIRE_DATABASE": "true",
    }) is True


@pytest.mark.parametrize("raw", ("maybe", "TRUE ", "Required", "1x", "enable"))
def test_database_required_unrecognized_explicit_fails_closed(raw):
    """Typos / non-falsy values must not silently soft-open production."""
    assert database_required({
        "PHINS_ENVIRONMENT": "production",
        "RAILWAY_ENVIRONMENT": "production",
        "PHINS_REQUIRE_DATABASE": raw,
    }) is True


def test_database_required_false_by_default_in_development():
    assert database_required({"PHINS_ENVIRONMENT": "development"}) is False


def test_refuse_in_memory_boot_when_required_and_db_down():
    assert refuse_in_memory_boot(
        required=True, use_database=False, database_enabled=False
    ) is True
    assert refuse_in_memory_boot(
        required=True, use_database=True, database_enabled=False
    ) is True
    assert refuse_in_memory_boot(
        required=True, use_database=True, database_enabled=True
    ) is False
    assert refuse_in_memory_boot(
        required=False, use_database=False, database_enabled=False
    ) is False


def test_ephemeral_ledger_forbidden_in_real_production():
    assert ephemeral_ledger_forbidden({
        "PHINS_ENVIRONMENT": "production",
        "RAILWAY_ENVIRONMENT": "production",
    }) is True


def test_ephemeral_ledger_allowed_with_escape_hatch():
    assert ephemeral_ledger_forbidden({
        "PHINS_ENVIRONMENT": "production",
        "PHINS_ALLOW_EPHEMERAL_LEDGER": "true",
    }) is False


@pytest.mark.parametrize("raw", ("maybe", "TURE", "yesplease", "1x"))
def test_ephemeral_ledger_unrecognized_allow_fails_closed(raw):
    assert ephemeral_ledger_forbidden({
        "PHINS_ENVIRONMENT": "production",
        "RAILWAY_ENVIRONMENT": "production",
        "PHINS_ALLOW_EPHEMERAL_LEDGER": raw,
    }) is True


def test_ephemeral_ledger_allowed_in_test_mode():
    assert ephemeral_ledger_forbidden({
        "PHINS_ENVIRONMENT": "production",
        "PHINS_TEST_MODE": "1",
    }) is False


def test_ledger_path_is_ephemeral_under_tempdir(tmp_path, monkeypatch):
    fake_tmp = tmp_path / "tmp"
    fake_tmp.mkdir()
    ephemeral = fake_tmp / "phins_ledger_data.json"
    durable = tmp_path / "data" / "phins_ledger_data.json"
    durable.parent.mkdir()
    assert ledger_path_is_ephemeral(str(ephemeral), temp_root=str(fake_tmp)) is True
    assert ledger_path_is_ephemeral(str(durable), temp_root=str(fake_tmp)) is False


def test_ledger_path_unclassifiable_fails_closed(monkeypatch):
    """Path errors must not soft-open the durability gate."""

    def _boom(_path):
        raise OSError("cannot classify")

    monkeypatch.setattr(os.path, "abspath", _boom)
    assert ledger_path_is_ephemeral("/data/phins_ledger_data.json") is True


def test_refuse_ephemeral_ledger_boot_uses_real_tempdir(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    ephemeral = str(tmp_path / "phins_ledger_data.json")
    durable = str(Path("/data/phins_ledger_data.json"))
    assert refuse_ephemeral_ledger_boot(forbidden=True, ledger_path=ephemeral) is True
    assert refuse_ephemeral_ledger_boot(forbidden=True, ledger_path=durable) is False
    assert refuse_ephemeral_ledger_boot(forbidden=False, ledger_path=ephemeral) is False


def test_render_platform_defaults_to_require_database_without_explicit_label():
    # secrets_policy treats bare RENDER as production when no env label is set.
    assert database_required({"RENDER": "true"}) is True


def test_ae1_kill_postgres_shape_production_requires_db_and_refuses_memory():
    """AE1: production + DB down → refuse in-memory (SystemExit at entry points)."""
    env = {
        "PHINS_ENVIRONMENT": "production",
        "RAILWAY_ENVIRONMENT": "production",
    }
    assert database_required(env) is True
    assert refuse_in_memory_boot(
        required=True, use_database=False, database_enabled=False
    ) is True


def test_durable_database_enforce_is_noop_under_test_mode():
    """Import + entry-point enforce must not abort the pytest harness."""
    import web_portal.server as portal

    # PHINS_TEST_MODE is set by root conftest; enforce must be a no-op.
    portal._enforce_durable_database()


def test_import_time_no_longer_systemexits_on_db_refuse():
    """DB refuse lives in _enforce_durable_database, not bare import side effects."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "web_portal" / "server.py"
    text = src.read_text(encoding="utf-8")
    marker = "# DI-1 / U1: durability is required"
    start = text.index(marker)
    # The import-time block ends at the enforce helper definition.
    end = text.index("def _enforce_durable_database()", start)
    chunk = text[start:end]
    assert "raise SystemExit" not in chunk
    assert "WARNING: Durable database storage is required" in chunk
    assert "def run_server" in text
    assert "_enforce_durable_database()" in text.split("def run_server", 1)[1].split(
        "def ", 1
    )[0]
    assert "_enforce_durable_database()" in text.split(
        "def execute_monthly_auto_pay_cli", 1
    )[1].split("bootstrap_runtime_state_for_command", 1)[0]
