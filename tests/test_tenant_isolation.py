"""
Tenant isolation harness.

Premortem risk #1: tenant isolation in PHINS is enforced by hand, one handler at
a time (``customer_id`` appears thousands of times across ``web_portal/server.py``).
A single missing ownership check leaks another customer's policies, claims, bills,
or balances.

This suite turns "some route might leak" into a concrete, evidence-based answer:

* It seeds two customers (A and B) directly into the in-memory portal stores,
  embedding a data-only sentinel string in customer B's records.
* It then logs in as customer A and probes a curated list of customer-scoped GET
  endpoints, attacking with B's ``customer_id`` and B's resource IDs.
* The universal invariant checked is: **customer B's sentinel must never appear
  in a response served to customer A.**

That invariant is deliberately behaviour-agnostic. Endpoints enforce isolation in
different ways today -- some return 403 (``/api/customer/summary``), some silently
re-scope a requested ``customer_id`` back to the session owner (``/api/policies``),
and some 404 a foreign resource ID. All of those are "no leak". The test only
fails when B's data actually crosses to A.

Positive-control tests prove the harness has teeth: customer A *can* see customer
A's own sentinel through the same endpoints, so a green run means real isolation
rather than blanket errors.

The embedded HTTP server and the in-memory env defaults are provided by the repo
root ``conftest.py`` (reads ``TEST_BASE_URL``); do not hardcode a port here.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal


# --- Sentinels -------------------------------------------------------------
# Sentinels live ONLY inside stored records, never inside request URLs/params,
# so detecting them in a response is unambiguous evidence of a data leak (and
# never a false positive from the server echoing a requested id back).
B_SENTINEL = "ISOLEAKB"   # must never reach customer A
A_SENTINEL = "ISOSELFA"   # used for positive controls (A sees its own data)

CUST_A = "CUST-ISO-A"
CUST_B = "CUST-ISO-B"

TOKEN_A = "phins_iso_token_a"
TOKEN_B = "phins_iso_token_b"

POL_B = "POL-ISO-B"
CLM_B = "CLM-ISO-B"
BILL_B = "BILL-ISO-B"
POL_A = "POL-ISO-A"


def _base_url() -> str:
    return os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _future_iso(hours: int = 2) -> str:
    return (datetime.now() + timedelta(hours=hours)).isoformat()


def _http_get(path: str, token: str | None = None) -> Tuple[int, str]:
    """GET that always returns (status, body), including for error responses.

    Error bodies are returned too, because a leak could just as easily live in a
    500/403 payload as in a 200.
    """
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(_base_url() + path, headers=headers)
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except HTTPError as exc:  # 4xx/5xx still carry a readable body
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body
    except URLError as exc:  # pragma: no cover - environment/network failure
        raise AssertionError(f"Request to {path} failed: {exc}") from exc


def _seed_two_customers() -> None:
    """Seed customers A and B (and their resources) into the in-memory stores.

    Called from within the test body so it runs *after* conftest's
    ``pytest_runtest_setup`` has cleared shared state. USERS is intentionally not
    seeded: every customer-scoped handler falls back to the session's own role /
    customer_id, and leaving USERS untouched avoids cross-test pollution (conftest
    deliberately does not clear USERS).
    """
    # Customer records (name carries the sentinel so any echo of the record leaks).
    portal.CUSTOMERS[CUST_A] = {
        "id": CUST_A,
        "customer_id": CUST_A,
        "name": f"{A_SENTINEL} Self Holdings",
        "email": "iso_a@example.test",
    }
    portal.CUSTOMERS[CUST_B] = {
        "id": CUST_B,
        "customer_id": CUST_B,
        "name": f"{B_SENTINEL} Foreign Holdings",
        "email": "iso_b@example.test",
    }

    # Policies.
    portal.POLICIES[POL_A] = {
        "id": POL_A,
        "customer_id": CUST_A,
        "policy_number": f"{A_SENTINEL}-POL-001",
        "status": "active",
        "coverage_amount": 100000,
        "annual_premium": 1200,
    }
    portal.POLICIES[POL_B] = {
        "id": POL_B,
        "customer_id": CUST_B,
        "policy_number": f"{B_SENTINEL}-POL-001",
        "status": "active",
        "coverage_amount": 999111,
        "annual_premium": 4242,
    }

    # Claim owned by B.
    portal.CLAIMS[CLM_B] = {
        "id": CLM_B,
        "customer_id": CUST_B,
        "policy_id": POL_B,
        "status": "pending",
        "description": f"{B_SENTINEL} foreign claim",
        "amount": 55000,
    }

    # Bill owned by B.
    portal.BILLING[BILL_B] = {
        "id": BILL_B,
        "customer_id": CUST_B,
        "invoice_number": f"{B_SENTINEL}-INV-001",
        "status": "pending",
        "amount": 777222,
        "due_date": "2026-12-31",
    }

    # Sessions (legacy phins_ tokens resolved via the in-memory SESSIONS dict).
    portal.SESSIONS[TOKEN_A] = {
        "username": "iso_customer_a",
        "role": "customer",
        "customer_id": CUST_A,
        "expires": _future_iso(),
    }
    portal.SESSIONS[TOKEN_B] = {
        "username": "iso_customer_b",
        "role": "customer",
        "customer_id": CUST_B,
        "expires": _future_iso(),
    }

    # In test mode the handler wipes the in-memory stores on the first request to
    # a port it hasn't seen (`_ensure_test_port_state`), and conftest resets that
    # tracker before each test. Mark our port as already-initialized so the seed
    # above survives the first probe.
    port = int(os.environ.get("TEST_PORT", "0") or 0)
    if port:
        portal._TEST_PORTS_INITIALIZED.add(port)


# Curated set of customer-scoped GET endpoints and the cross-customer attack
# vector for each (always probing as customer A for customer B's data).
# (name, path_with_query). Endpoints whose optional service is disabled in test
# mode simply return 503/404 -- still "no leak", so they are safe to include.
def _attack(path: str, **params: str) -> str:
    return f"{path}?{urlencode(params)}" if params else path


CROSS_CUSTOMER_GET_PROBES: List[Tuple[str, str]] = [
    ("policies (by customer_id)", _attack("/api/policies", customer_id=CUST_B)),
    ("policies (by id)", _attack("/api/policies", id=POL_B)),
    ("claims (by customer_id)", _attack("/api/claims", customer_id=CUST_B)),
    ("claims (by id)", _attack("/api/claims", id=CLM_B)),
    ("customer summary", _attack("/api/customer/summary", customer_id=CUST_B)),
    ("billing list", _attack("/api/billing", customer_id=CUST_B)),
    ("auto-pay reports", _attack("/api/billing/auto-pay/reports", customer_id=CUST_B)),
    ("customer dashboard-data", _attack("/api/customer/dashboard-data", customer_id=CUST_B)),
    ("customer ai-report", _attack("/api/customer/ai-report", customer_id=CUST_B)),
    ("customer activity-log", _attack("/api/customer/activity-log", customer_id=CUST_B)),
    ("customer allocation", _attack("/api/customer/allocation", customer_id=CUST_B)),
    ("investment unified", _attack("/api/investment/unified", customer_id=CUST_B)),
    ("portfolio unified", _attack("/api/portfolio/unified", customer_id=CUST_B)),
    ("portfolio positions", _attack("/api/portfolio/positions", customer_id=CUST_B)),
    ("balance unified", _attack("/api/balance/unified", customer_id=CUST_B)),
    ("balance transactions", _attack("/api/balance/transactions", customer_id=CUST_B)),
    ("statement", _attack("/api/statement", customer_id=CUST_B)),
    ("allocations", _attack("/api/allocations", customer_id=CUST_B)),
]


def test_no_cross_customer_data_leak():
    """Customer A must never receive customer B's data from any probed endpoint.

    This is the harness: it runs every probe, collects any endpoint that leaks
    B's sentinel, and reports them together so a fix can target the exact routes.
    """
    _seed_two_customers()

    leaks: List[str] = []
    for name, path in CROSS_CUSTOMER_GET_PROBES:
        status, body = _http_get(path, token=TOKEN_A)
        if B_SENTINEL in body:
            leaks.append(f"  - {name}: GET {path} -> HTTP {status} leaked B's data")

    assert not leaks, (
        "Cross-tenant data leak: customer A received customer B's data from "
        f"{len(leaks)} endpoint(s):\n" + "\n".join(leaks)
    )


def test_positive_control_customer_sees_own_data():
    """Sanity: the probes are real -- A can see A's own data via /api/policies.

    If this fails, the harness above could be passing only because every endpoint
    errored, which would make the leak check meaningless.
    """
    _seed_two_customers()

    status, body = _http_get(_attack("/api/policies", customer_id=CUST_A), token=TOKEN_A)
    assert status == 200, f"Expected 200 for own policies, got {status}: {body[:300]}"
    assert A_SENTINEL in body, (
        "Positive control failed: customer A could not see their own policy "
        f"(sentinel {A_SENTINEL!r} missing from response)"
    )
    # And the same response must not contain B's data.
    assert B_SENTINEL not in body


def test_owner_can_read_own_data_proves_detection():
    """Sanity: B's sentinel *is* observable when B legitimately reads B's data.

    Pairs with the leak test -- it proves the sentinel detection mechanism fires
    on real data, so a green leak test cannot be a false negative caused by the
    sentinel being undetectable.
    """
    _seed_two_customers()

    status, body = _http_get(_attack("/api/policies", customer_id=CUST_B), token=TOKEN_B)
    assert status == 200, f"Expected 200 for owner B's own policies, got {status}: {body[:300]}"
    assert B_SENTINEL in body, (
        "Detection sanity failed: owner B could not see their own sentinel, so the "
        "leak test would not be able to detect a real cross-tenant leak."
    )


def test_cross_customer_policy_by_id_is_blocked():
    """A direct fetch of B's policy by id must not return B's policy to A."""
    _seed_two_customers()

    status, body = _http_get(_attack("/api/policies", id=POL_B), token=TOKEN_A)
    assert B_SENTINEL not in body, (
        f"Customer A fetched customer B's policy by id (HTTP {status}): {body[:300]}"
    )
    # Current behaviour returns 404 for a foreign policy id; assert it stays that
    # way so a future regression that 200s someone else's policy is caught.
    assert status == 404, f"Expected 404 for foreign policy id, got {status}: {body[:300]}"


@pytest.mark.parametrize("name,path", CROSS_CUSTOMER_GET_PROBES, ids=[n for n, _ in CROSS_CUSTOMER_GET_PROBES])
def test_each_endpoint_isolated(name: str, path: str):
    """Per-endpoint view of the same invariant for granular pass/fail reporting."""
    _seed_two_customers()
    status, body = _http_get(path, token=TOKEN_A)
    assert B_SENTINEL not in body, (
        f"{name}: customer A received customer B's data (HTTP {status}) from {path}"
    )
