"""PostgreSQL connect timeout must fail fast for Railway PR previews.

An unreachable ``*.railway.internal`` host (fresh PR environment, Postgres
not ready, or DATABASE_URL still pointing at another environment) used to
hang until the kernel SYN retry budget — past Railway's healthcheck — so
the HTTP server never bound and the deploy was marked failed.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def postgres_url(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://phins:phins@127.0.0.1:5432/phins",
    )
    monkeypatch.delenv("USE_SQLITE", raising=False)
    yield
    # DatabaseConfig reads env at call time; nothing else to reset.


def test_postgres_engine_options_set_connect_timeout(postgres_url):
    from database.config import DatabaseConfig

    options = DatabaseConfig.get_engine_options()
    assert options["connect_args"]["connect_timeout"] == DatabaseConfig.CONNECT_TIMEOUT
    assert DatabaseConfig.CONNECT_TIMEOUT <= 10


def test_sqlite_engine_options_do_not_use_pg_connect_timeout(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", "phins.db")

    from database.config import DatabaseConfig

    options = DatabaseConfig.get_engine_options()
    assert "check_same_thread" in options.get("connect_args", {})
    assert "connect_timeout" not in options.get("connect_args", {})
