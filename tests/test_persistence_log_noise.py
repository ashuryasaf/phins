"""Regression tests for Railway log noise reduction.

Covers two fixes:
1. ``save_ledger_data()`` no longer emits one `[PERSISTENCE]` line per call.
   It coalesces log output so repeated saves (the API layer calls it from
   ~70 write paths plus a 60s background thread) emit at most one summary
   line per configured interval.
2. ``PortalHandler`` suppresses bot-scan 404 log output for common probe
   paths (``/.env``, ``/.git/config``, ``/wp-config.php``, ``/%22/...``,
   etc.) so these scanners do not dominate deploy logs.
"""

from __future__ import annotations

import io
import urllib.request
from contextlib import redirect_stdout, redirect_stderr

import pytest

from web_portal import server as server_module


BASE_URL = "http://localhost:8000"


def _trigger_save():
    server_module.save_ledger_data()


def test_save_ledger_data_coalesces_log_lines(monkeypatch):
    """Repeated saves should not each emit a [PERSISTENCE] line."""
    monkeypatch.setattr(server_module, "PERSISTENCE_VERBOSE", False)
    monkeypatch.setattr(server_module, "PERSISTENCE_LOG_INTERVAL_SECONDS", 3600)
    monkeypatch.setitem(
        server_module._persistence_log_state, "first_save_logged", True
    )
    monkeypatch.setitem(
        server_module._persistence_log_state, "last_logged_at", 10**9
    )
    monkeypatch.setitem(
        server_module._persistence_log_state, "saves_since_last_log", 0
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        for _ in range(25):
            _trigger_save()

    output = buf.getvalue()
    assert "[PERSISTENCE] Saved ledger data" not in output, (
        "Repeated save_ledger_data() calls within the log interval must not "
        "produce per-save log lines; got:\n" + output
    )


def test_save_ledger_data_verbose_mode_still_logs(monkeypatch):
    """LEDGER_PERSISTENCE_VERBOSE=true preserves per-save visibility."""
    monkeypatch.setattr(server_module, "PERSISTENCE_VERBOSE", True)
    monkeypatch.setitem(
        server_module._persistence_log_state, "first_save_logged", True
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        _trigger_save()
        _trigger_save()

    assert buf.getvalue().count("[PERSISTENCE] Saved ledger data") >= 2


def test_save_ledger_data_zero_interval_logs_every_save(monkeypatch):
    """A zero interval disables throttling instead of silencing later saves."""
    monkeypatch.setattr(server_module, "PERSISTENCE_VERBOSE", False)
    monkeypatch.setattr(server_module, "PERSISTENCE_LOG_INTERVAL_SECONDS", 0)
    monkeypatch.setitem(
        server_module._persistence_log_state, "first_save_logged", True
    )
    monkeypatch.setitem(
        server_module._persistence_log_state, "last_logged_at", 10**9
    )
    monkeypatch.setitem(
        server_module._persistence_log_state, "saves_since_last_log", 0
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        _trigger_save()
        _trigger_save()

    output = buf.getvalue()
    assert output.count("[PERSISTENCE] Saved ledger data") == 2
    assert "coalesced" not in output


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/.env.bak",
        "/.env.local",
        "/backend/.env",
        "/admin/.env",
        "/.git/config",
        "/wp-config.php",
        "/wp-config.php.old",
        "/config.php",
        "/config.js",
        "/aws-config.js",
        "/aws.config.js",
        "/%22/ui-clarity.js%22",
    ],
)
def test_bot_probe_paths_are_silenced(path):
    """Bot-scan 404s should not emit stderr log output."""
    assert server_module._is_bot_probe_path(path), (
        f"{path!r} should be classified as a bot-probe path so its 404 is "
        f"not logged to Railway."
    )


def test_legit_404_still_logged():
    """Regular 404s (typos, missing pages) must remain observable."""
    assert not server_module._is_bot_probe_path("/dashboard.html")
    assert not server_module._is_bot_probe_path("/api/unknown")
    assert not server_module._is_bot_probe_path("/missing-page")


def test_bot_probe_suppression_only_covers_expected_statuses():
    """Unexpected bot-probe errors should still log their diagnostic message."""
    assert server_module._should_silence_bot_probe_http_log("/.env", 404)
    assert server_module._should_silence_bot_probe_http_log("/.env", 403)
    assert not server_module._should_silence_bot_probe_http_log("/.env", 500)
    assert not server_module._should_silence_bot_probe_http_log("/missing-page", 404)


def test_bot_probe_404_request_is_silent_end_to_end():
    """Hitting /.env over the real embedded test server emits no log line."""
    buf_err = io.StringIO()
    with redirect_stderr(buf_err):
        try:
            urllib.request.urlopen(BASE_URL + "/.env", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        except Exception:
            pytest.skip("Embedded server not reachable in this environment")

    err = buf_err.getvalue()
    assert "GET /.env" not in err, err
    assert "code 404" not in err, err
