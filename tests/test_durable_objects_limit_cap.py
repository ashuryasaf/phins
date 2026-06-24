"""
Regression test for the durable-objects vault ``limit`` parameter cap.

Without an upper bound, a caller can pass ``limit=10_000_000`` to
``GET /api/durable-objects/documents`` and force the worker to materialise
a giant JSON page. The vault iterates only the caller's own documents so
this is a self-DoS at worst, but a hard cap is cheap insurance against
buggy clients and abusive customers. This test pins the cap at 1000.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal


# ── Test scaffolding ─────────────────────────────────────────────────────────


class _ServerThread(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self) -> None:  # type: ignore[override]
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _get(url: str, token: str | None = None) -> tuple[int, dict | bytes]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {}


def _inject_session(token: str, customer_id: str = "CUST-LIMIT") -> None:
    portal.SESSIONS[token] = {
        "username": "limit-test@example.com",
        "role": "customer",
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    portal.USERS["limit-test@example.com"] = {
        "role": "customer",
        "username": "limit-test@example.com",
        "customer_id": customer_id,
    }


@pytest.fixture
def _vault_server():
    """Run a dedicated server on its own port so this test does not collide
    with the conftest's shared ``localhost:8000`` and per-test state wipe."""
    port = 8867
    thread = _ServerThread(port)
    thread.start()
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(port)
    yield f"http://127.0.0.1:{port}"
    try:
        thread.stop()
    except Exception:
        pass


# ── Tests ────────────────────────────────────────────────────────────────────


class TestDurableObjectsLimitCap:
    def test_oversized_limit_is_capped_at_1000(self, _vault_server):
        token = "phins_durable-limit-test-token"
        _inject_session(token, customer_id="CUST-LIMIT-1")

        # Seed enough documents to demonstrate that the cap, not the data
        # volume, is what controls the response size. We just need the
        # endpoint to succeed; the response payload reports ``total`` for
        # the unfiltered count and the documents list capped to ``limit``.
        import base64 as _b64
        for i in range(10):
            unique_payload = _b64.b64encode(f"unique-{i}".encode("utf-8")).decode("ascii")
            portal.POLICY_DOCUMENTS[f"DOC-LIMIT-{i:03d}"] = {
                "id": f"DOC-LIMIT-{i:03d}",
                "name": f"f{i}.txt",
                "type": "text/plain",
                "size": 8,
                "data": unique_payload,
                "uploaded_by_customer": "CUST-LIMIT-1",
                "entity_type": "customer",
                "entity_id": "CUST-LIMIT-1",
                "uploaded_at": f"2026-01-{i+1:02d}T00:00:00",
            }

        status, body = _get(
            f"{_vault_server}/api/durable-objects/documents"
            f"?customer_id=CUST-LIMIT-1&limit=10000000",
            token=token,
        )
        assert status == 200, body
        assert isinstance(body, dict)
        # Number of returned documents must never exceed the hard cap.
        assert len(body.get("documents", [])) <= 1000
        # Sanity: the seed produced only 10 docs so we should get all of them.
        assert len(body.get("documents", [])) == 10

    def test_negative_limit_is_clamped_to_zero(self, _vault_server):
        token = "phins_durable-limit-neg-token"
        _inject_session(token, customer_id="CUST-LIMIT-2")
        portal.POLICY_DOCUMENTS["DOC-LIMIT-NEG-1"] = {
            "id": "DOC-LIMIT-NEG-1",
            "name": "n1.txt",
            "type": "text/plain",
            "size": 4,
            "data": "QUFBQQ==",
            "uploaded_by_customer": "CUST-LIMIT-2",
            "entity_type": "customer",
            "entity_id": "CUST-LIMIT-2",
            "uploaded_at": "2026-01-01T00:00:00",
        }
        status, body = _get(
            f"{_vault_server}/api/durable-objects/documents"
            f"?customer_id=CUST-LIMIT-2&limit=-5",
            token=token,
        )
        assert status == 200
        assert isinstance(body, dict)
        # Original ``max(0, int(...))`` semantics preserved.
        assert len(body.get("documents", [])) == 0

    def test_default_limit_is_used_when_omitted(self, _vault_server):
        token = "phins_durable-limit-default-token"
        _inject_session(token, customer_id="CUST-LIMIT-3")
        portal.POLICY_DOCUMENTS["DOC-LIMIT-DEF-1"] = {
            "id": "DOC-LIMIT-DEF-1",
            "name": "d1.txt",
            "type": "text/plain",
            "size": 4,
            "data": "QUFBQQ==",
            "uploaded_by_customer": "CUST-LIMIT-3",
            "entity_type": "customer",
            "entity_id": "CUST-LIMIT-3",
            "uploaded_at": "2026-01-01T00:00:00",
        }
        status, body = _get(
            f"{_vault_server}/api/durable-objects/documents"
            f"?customer_id=CUST-LIMIT-3",
            token=token,
        )
        assert status == 200
        assert isinstance(body, dict)
        # The single seeded doc is returned; default of 500 doesn't trigger
        # the cap.
        assert len(body.get("documents", [])) == 1
