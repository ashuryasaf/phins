import json
import threading
import time
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal


class ServerThread(threading.Thread):
    """Run the portal server in a background thread for endpoint tests."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _get_json(url: str):
    req = Request(url)
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture
def isolated_sqlite_db(tmp_path, monkeypatch):
    """Point database tests at an isolated SQLite file."""
    db_path = tmp_path / "auth_safeguards.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    import database

    database.reset_connection()
    database.init_database(drop_existing=True)
    try:
        yield
    finally:
        database.reset_connection()


def test_seed_default_users_preserves_existing_staff_password_without_env_override(isolated_sqlite_db, monkeypatch):
    """Existing seeded staff accounts must keep their current password unless explicitly overridden."""
    monkeypatch.delenv("PHINS_ADMIN_PASSWORD", raising=False)

    from database import get_db_session
    from database.repositories import UserRepository
    from database.seeds import hash_password, seed_default_users

    session = get_db_session()
    try:
        repo = UserRepository(session)
        original = hash_password("persisted-admin-password")
        repo.create(
            username="admin",
            password_hash=original["hash"],
            password_salt=original["salt"],
            role="admin",
            name="Admin User",
            email="admin@phins.ai",
            active=True,
        )
        session.commit()
    finally:
        session.close()

    seed_default_users()

    session = get_db_session()
    try:
        repo = UserRepository(session)
        admin = repo.get_by_username("admin")
        assert admin is not None
        assert admin.password_hash == original["hash"]
        assert admin.password_salt == original["salt"]
    finally:
        session.close()


def test_seed_default_users_preserves_existing_customer_password_without_env_override(isolated_sqlite_db, monkeypatch):
    """Existing seeded customers must not be rotated to fallback/default passwords during deploys."""
    monkeypatch.delenv("PHINS_USER_EFRAT_PASSWORD", raising=False)

    from database import get_db_session
    from database.repositories import CustomerRepository
    from database.seeds import hash_password, seed_default_users

    session = get_db_session()
    try:
        repo = CustomerRepository(session)
        original = hash_password("persisted-customer-password")
        repo.create(
            id="CUST-EFRAT-001",
            name="Efrat PHINS",
            email="efrat@phins.ai",
            password_hash=original["hash"],
            password_salt=original["salt"],
            portal_active=True,
        )
        session.commit()
    finally:
        session.close()

    seed_default_users()

    session = get_db_session()
    try:
        repo = CustomerRepository(session)
        customer = repo.get_by_email("efrat@phins.ai")
        assert customer is not None
        assert customer.password_hash == original["hash"]
        assert customer.password_salt == original["salt"]
    finally:
        session.close()


def test_token_secret_resolves_documented_aliases(monkeypatch):
    """Deployment docs use multiple env names; token signing must honor them."""
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)
    monkeypatch.delenv("PHINS_ADMIN_PASSWORD", raising=False)

    monkeypatch.setenv("SESSION_SECRET", "session-secret")
    assert portal._resolve_token_secret() == "session-secret"

    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("PHINS_SECRET_KEY", "phins-secret")
    assert portal._resolve_token_secret() == "phins-secret"

    monkeypatch.delenv("PHINS_SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "framework-secret")
    assert portal._resolve_token_secret() == "framework-secret"


def test_health_endpoint_reports_degraded_when_database_mode_loses_connection():
    """A broken DB-backed deploy must not advertise itself as healthy."""
    port = 8311
    srv = ServerThread(port)

    original_use_database = portal.USE_DATABASE
    original_database_enabled = portal.database_enabled

    portal.USE_DATABASE = True
    portal.database_enabled = False

    try:
        srv.start()
        time.sleep(0.2)

        status, payload = _get_json(f"http://127.0.0.1:{port}/api/health")
        assert status == 503
        assert payload["status"] == "degraded"
        assert payload["database"] == "disabled"
        assert payload["configured_storage_mode"] == "database"
        assert payload["storage_mode"] == "in-memory"
        assert payload["degraded_reason"] == "database_unavailable"
    finally:
        portal.USE_DATABASE = original_use_database
        portal.database_enabled = original_database_enabled
        srv.stop()
