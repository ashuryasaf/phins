"""U1: production boot fail-closed for durable DB + non-ephemeral ledger."""

from __future__ import annotations

import os
import re
import subprocess
import sys
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


def test_database_required_folds_case_for_test_mode_and_previews():
    """Shell used to miss these and export an explicit true, which wins."""
    assert database_required({
        "PHINS_ENVIRONMENT": "production",
        "PHINS_TEST_MODE": "TRUE",
    }) is False
    assert database_required({
        "PHINS_ENVIRONMENT": "Production",
        "RAILWAY_ENVIRONMENT": "PR-123",
    }) is False
    assert database_required({"PHINS_ENVIRONMENT": "Production"}) is True


def test_entrypoint_serve_does_not_export_require_database():
    text = (Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh").read_text()
    serve = text.split("\n    serve)", 1)[1].split("\n        ;;", 1)[0]
    statements = [
        line for line in serve.splitlines()
        if line.split("#", 1)[0].strip()
    ]
    body = "\n".join(statements)
    assert not re.search(r"\bexport\s+PHINS_REQUIRE_DATABASE\b", body)
    assert "PHINS_REQUIRE_DATABASE=" not in body
    assert "_default_require_db" not in body


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


def _render_cron_env() -> dict:
    """Production Render flag and a tempdir ledger file.

    ``PHINS_REQUIRE_DATABASE=false`` keeps the durable-DB gate out of this
    check. A healthy database still reaches the ledger gate, which is what
    aborted monthly auto-pay on an older import-time abort.
    """
    env = os.environ.copy()
    for name in (
        "PHINS_TEST_MODE",
        "PHINS_ENVIRONMENT",
        "ENVIRONMENT",
        "ENV",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_ENVIRONMENT_NAME",
        "PHINS_ALLOW_EPHEMERAL_LEDGER",
        "PHINS_REQUIRE_DATABASE",
    ):
        env.pop(name, None)
    env["RENDER"] = "true"
    env["USE_DATABASE"] = "false"
    env["PHINS_REQUIRE_DATABASE"] = "false"
    env["LEDGER_PERSISTENCE_FILE"] = os.path.join(
        tempfile.gettempdir(), f"phins-ledger-boot-{os.getpid()}.json"
    )
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_one_shot_import_survives_render_ephemeral_ledger():
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import web_portal.server; print('imported')"],
        cwd=repo,
        env=_render_cron_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "imported" in result.stdout


def test_server_main_still_refuses_render_ephemeral_ledger():
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "web_portal" / "server.py")],
        cwd=repo,
        env=_render_cron_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 1, result.stdout[-2000:]
    assert "FATAL: Ledger persistence path is ephemeral" in result.stdout


def test_ledger_gate_is_serve_only_not_import():
    src = Path(__file__).resolve().parents[1] / "web_portal" / "server.py"
    text = src.read_text(encoding="utf-8")
    persist = text.split("LEDGER_PERSISTENCE_FILE = _resolve_persistence_file()", 1)[1]
    import_chunk = persist.split("def _enforce_durable_ledger_at_serve()", 1)[0]
    assert "raise SystemExit" not in import_chunk
    serve = text.split("def run_server", 1)[1].split("def ", 1)[0]
    assert "_enforce_durable_ledger_at_serve()" in serve
    auto_pay = text.split("def execute_monthly_auto_pay_cli", 1)[1].split(
        "bootstrap_runtime_state_for_command", 1
    )[0]
    assert "_enforce_durable_ledger_at_serve()" not in auto_pay


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
