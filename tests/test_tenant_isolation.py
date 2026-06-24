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


def _http_post(path: str, payload: Dict[str, Any], token: str | None = None) -> Tuple[int, str]:
    """POST that always returns (status, body), including for error responses."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = Request(_base_url() + path, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body
    except URLError as exc:  # pragma: no cover - environment/network failure
        raise AssertionError(f"POST to {path} failed: {exc}") from exc


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

    # Health wallets (used by the wallet write-isolation tests). The transaction
    # description carries the per-customer sentinel so any wallet read that leaks
    # across tenants is detectable.
    for cid, sentinel in ((CUST_A, A_SENTINEL), (CUST_B, B_SENTINEL)):
        portal.HEALTH_WALLETS[cid] = {
            "customer_id": cid,
            "balance": 500.0,
            "monthly_deposit": 0.0,
            "transactions": [
                {
                    "id": f"WALTX-{cid}",
                    "type": "deposit",
                    "amount": 500.0,
                    "description": f"{sentinel} wallet seed deposit",
                    "timestamp": _future_iso(0),
                }
            ],
            "created_at": _future_iso(0),
        }

    # Investment accounts (read by /api/investment/unified, ai-report, dashboard).
    for cid, sentinel in ((CUST_A, A_SENTINEL), (CUST_B, B_SENTINEL)):
        portal.INVESTMENT_ACCOUNTS[cid] = {
            "customer_id": cid,
            "balance": 1000.0,
            "index_balance": 400.0,
            "bonds_balance": 400.0,
            "crypto_balance": 200.0,
            "deposits": [
                {
                    "id": f"INVDEP-{cid}",
                    "amount": 1000.0,
                    "source": f"{sentinel}-investment-seed",
                    "timestamp": _future_iso(0),
                }
            ],
            "allocations": [],
            "created_at": _future_iso(0),
        }

    # Medical purchases (read by GET /api/health-wallet/purchases).
    for cid, sentinel in ((CUST_A, A_SENTINEL), (CUST_B, B_SENTINEL)):
        pid = f"PURCH-ISO-{cid}"
        portal.MEDICAL_PURCHASES[pid] = {
            "id": pid,
            "customer_id": cid,
            "product_name": f"{sentinel} medical purchase",
            "amount": 42.0,
            "category": "general",
            "timestamp": _future_iso(0),
        }

    # Transaction-ledger entries (read by /api/ledger, /api/customer/activity-log).
    for cid, sentinel in ((CUST_A, A_SENTINEL), (CUST_B, B_SENTINEL)):
        tx_id = f"TX-ISO-{cid}"
        portal.TRANSACTION_LEDGER[tx_id] = {
            "id": tx_id,
            "customer_id": cid,
            "type": "investment_deposit",
            "amount": 1000.0,
            "description": f"{sentinel} ledger seed entry",
            "metadata": {},
            "timestamp": _future_iso(0),
            "status": "completed",
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
    ("ledger", _attack("/api/ledger", customer_id=CUST_B)),
    ("billing transactions", _attack("/api/billing/transactions", customer_id=CUST_B)),
    ("service transactions", _attack("/api/service-transactions", customer_id=CUST_B)),
    ("customer status", _attack("/api/customer/status", customer_id=CUST_B)),
    ("health-wallet purchases", _attack("/api/health-wallet/purchases", customer_id=CUST_B)),
    ("documents list", _attack("/api/documents/list", customer_id=CUST_B)),
    ("notifications history", _attack("/api/notifications/history", customer_id=CUST_B)),
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


def test_owner_can_read_own_ledger_proves_new_seeds_detectable():
    """Sanity for the enriched seeds: B's ledger sentinel is observable by B.

    Proves the new ledger/investment/wallet probes can actually detect a leak,
    so their green cross-tenant runs are not false negatives.
    """
    _seed_two_customers()
    status, body = _http_get(_attack("/api/ledger", customer_id=CUST_B), token=TOKEN_B)
    assert status == 200, f"owner B could not read own ledger (HTTP {status}): {body[:300]}"
    assert B_SENTINEL in body, (
        "Detection sanity failed: owner B's ledger sentinel was not observable, so "
        "the ledger leak probe could not detect a real cross-tenant leak."
    )


def test_owner_can_read_own_purchases_proves_detection():
    """Sanity: B's purchase sentinel is observable to B via health-wallet purchases."""
    _seed_two_customers()
    status, body = _http_get(
        _attack("/api/health-wallet/purchases", customer_id=CUST_B), token=TOKEN_B
    )
    assert status == 200, f"owner B could not read own purchases (HTTP {status}): {body[:300]}"
    assert B_SENTINEL in body, (
        "Detection sanity failed: owner B's purchase sentinel was not observable."
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


# --- Mutation (write) isolation -------------------------------------------
# Read leaks expose data; write leaks let one tenant *change* another tenant's
# records. The latter is strictly more dangerous, so the harness also probes a
# representative money-movement mutation: paying a bill.

def test_customer_cannot_pay_another_customers_bill():
    """Customer A must not be able to pay/mutate customer B's bill.

    ``/api/billing/pay`` resolves the bill (and its customer) purely from the
    ``bill_id`` in the request body. Without an ownership check, A could mark B's
    bill paid -- and via the health_wallet path drain B's wallet -- by guessing a
    bill_id. This asserts the guard rejects the cross-tenant write and leaves B's
    bill untouched.
    """
    _seed_two_customers()

    status, body = _http_post(
        "/api/billing/pay",
        {"bill_id": BILL_B, "amount": 100.0, "payment_method": "card"},
        token=TOKEN_A,
    )

    assert status == 403, (
        f"Customer A was allowed to pay customer B's bill (HTTP {status}): {body[:300]}"
    )
    # B's bill must be completely untouched.
    bill_after = portal.BILLING.get(BILL_B, {})
    assert bill_after.get("status") == "pending", (
        f"Customer B's bill status changed after A's blocked payment: {bill_after}"
    )
    assert float(bill_after.get("amount_paid", 0) or 0) == 0.0, (
        f"Customer B's bill recorded a payment from customer A: {bill_after}"
    )


def test_owner_can_pay_own_bill_proves_guard_not_overbroad():
    """Positive control: customer B can still pay B's own bill.

    Ensures the ownership guard blocks only cross-tenant writes and does not
    break the legitimate self-service payment path.
    """
    _seed_two_customers()

    status, body = _http_post(
        "/api/billing/pay",
        {"bill_id": BILL_B, "amount": 100.0, "payment_method": "card"},
        token=TOKEN_B,
    )

    assert status == 200, (
        f"Owner B was blocked from paying their own bill (HTTP {status}): {body[:300]}"
    )
    bill_after = portal.BILLING.get(BILL_B, {})
    assert float(bill_after.get("amount_paid", 0) or 0) == 100.0, (
        f"Owner B's payment was not recorded: {bill_after}"
    )


def test_customer_cannot_deposit_to_another_customers_wallet():
    """Customer A must not deposit into / mutate customer B's health wallet."""
    _seed_two_customers()
    before = float(portal.HEALTH_WALLETS[CUST_B]["balance"])

    status, body = _http_post(
        "/api/health-wallet/deposit",
        {"customer_id": CUST_B, "amount": 50.0, "payment_method": "card_on_file"},
        token=TOKEN_A,
    )

    assert status == 403, (
        f"Customer A was allowed to deposit into customer B's wallet (HTTP {status}): {body[:300]}"
    )
    after = float(portal.HEALTH_WALLETS[CUST_B]["balance"])
    assert after == before, f"Customer B's wallet balance changed ({before} -> {after})"


def test_customer_cannot_spend_another_customers_wallet():
    """Customer A must not spend from customer B's health wallet via purchase."""
    _seed_two_customers()
    before = float(portal.HEALTH_WALLETS[CUST_B]["balance"])

    status, body = _http_post(
        "/api/health-wallet/purchase",
        {
            "customer_id": CUST_B,
            "product_id": "PROD-ISO-X",
            "product_name": "Foreign purchase",
            "amount": 25.0,
            "payment_method": "health_wallet",
        },
        token=TOKEN_A,
    )

    assert status == 403, (
        f"Customer A was allowed to spend customer B's wallet (HTTP {status}): {body[:300]}"
    )
    after = float(portal.HEALTH_WALLETS[CUST_B]["balance"])
    assert after == before, f"Customer B's wallet was charged ({before} -> {after})"


# Customer-scoped money-movement POST routes that take the target customer_id in
# the request body. Probing as A with B's customer_id must never succeed (200).
# Service-gated endpoints may answer 503 in test mode; that is still "no write".
CROSS_CUSTOMER_WRITE_PROBES: List[Tuple[str, str, Dict[str, Any]]] = [
    ("billing pay-all-from-wallet", "/api/billing/pay-all-from-wallet", {"customer_id": CUST_B}),
    ("billing credits withdraw", "/api/billing/credits/withdraw",
     {"customer_id": CUST_B, "amount": 10.0, "method": "bank_transfer"}),
    ("billing credits transfer-to-wallet", "/api/billing/credits/transfer-to-wallet",
     {"customer_id": CUST_B, "amount": 10.0}),
    ("balance withdraw-from-algo", "/api/balance/withdraw-from-algo",
     {"customer_id": CUST_B, "amount": 10.0}),
    ("balance transfer-to-algo", "/api/balance/transfer-to-algo",
     {"customer_id": CUST_B, "amount": 10.0}),
    ("portfolio deposit-to-algo", "/api/portfolio/deposit-to-algo",
     {"customer_id": CUST_B, "amount": 10.0}),
    ("portfolio transfer", "/api/portfolio/transfer",
     {"customer_id": CUST_B, "amount": 10.0, "from": "investment", "to": "algo_trading"}),
]


@pytest.mark.parametrize(
    "name,path,payload",
    CROSS_CUSTOMER_WRITE_PROBES,
    ids=[n for n, _, _ in CROSS_CUSTOMER_WRITE_PROBES],
)
def test_money_route_write_isolation(name: str, path: str, payload: Dict[str, Any]):
    """Customer A must not perform a money-movement write against customer B.

    A successful cross-tenant write would return 200. A correctly guarded route
    returns 403 (denied) -- or 503 when its optional service is disabled in test
    mode, which also means no write happened. Anything other than 200 is safe;
    200 means the guard is missing.
    """
    _seed_two_customers()
    status, body = _http_post(path, payload, token=TOKEN_A)
    assert status != 200, (
        f"{name}: customer A performed a cross-tenant write against B "
        f"(HTTP {status}): {body[:300]}"
    )


def test_billing_credits_withdraw_cross_tenant_is_forbidden():
    """Strong assertion for the highest-severity route: credit withdrawal.

    Without the guard, A could withdraw B's billing credit to attacker-supplied
    bank details. The billing credit service is enabled in test mode, so the
    guard must produce a concrete 403 here.
    """
    _seed_two_customers()
    status, body = _http_post(
        "/api/billing/credits/withdraw",
        {"customer_id": CUST_B, "amount": 10.0, "method": "bank_transfer",
         "bank_details": {"account": "attacker-acct"}},
        token=TOKEN_A,
    )
    assert status == 403, (
        f"Customer A was not blocked from withdrawing B's credit (HTTP {status}): {body[:300]}"
    )


def test_billing_pay_all_from_wallet_cross_tenant_is_forbidden():
    """Strong assertion: A cannot sweep B's wallet to pay B's bills."""
    _seed_two_customers()
    status, body = _http_post(
        "/api/billing/pay-all-from-wallet",
        {"customer_id": CUST_B},
        token=TOKEN_A,
    )
    assert status == 403, (
        f"Customer A was not blocked from sweeping B's wallet (HTTP {status}): {body[:300]}"
    )


def test_savings_account_routes_block_cross_tenant_writes():
    """Account_id-keyed savings routes must enforce ownership.

    ``/api/savings/withdraw|invest|sell`` act on a portfolio account identified by
    ``account_id``. The owning customer is resolvable from ``portfolio_service``,
    so a customer must not be able to withdraw / invest / sell against another
    customer's account by supplying its ``account_id``.

    The account is created through the real API as customer B; if the portfolio
    service is disabled in this test build, the route returns 503 and the test
    skips rather than asserting on an unavailable feature.
    """
    _seed_two_customers()

    create_status, create_body = _http_post(
        "/api/savings/create-account",
        {
            "customer_id": CUST_B,
            "policy_id": POL_B,
            "monthly_contribution": 500,
            "savings_rate_pct": 25,
            "risk_profile": "moderate",
        },
        token=TOKEN_B,
    )
    if create_status == 503:
        pytest.skip("portfolio/savings service disabled in this build")
    assert create_status in (200, 201), (
        f"could not create B's savings account: {create_status} {create_body[:300]}"
    )
    account_id = json.loads(create_body).get("account_id")
    assert account_id, f"no account_id returned: {create_body[:300]}"

    cross_tenant_probes = [
        ("/api/savings/withdraw", {"account_id": account_id, "amount": 10.0}),
        ("/api/savings/invest", {"account_id": account_id, "symbol": "AAPL", "amount": 10.0}),
        ("/api/savings/sell", {"account_id": account_id, "symbol": "AAPL", "quantity": 1.0}),
    ]
    for path, payload in cross_tenant_probes:
        status, body = _http_post(path, payload, token=TOKEN_A)
        assert status == 403, (
            f"customer A was not blocked from {path} on B's account "
            f"(HTTP {status}): {body[:300]}"
        )

    # Positive control: the owner (B) is never blocked by the ownership guard.
    # (The service may still return 400 for insufficient funds, but never 403.)
    owner_status, owner_body = _http_post(
        "/api/savings/withdraw",
        {"account_id": account_id, "amount": 10.0},
        token=TOKEN_B,
    )
    assert owner_status != 403, (
        f"owner B was wrongly blocked from their own savings account "
        f"(HTTP {owner_status}): {owner_body[:300]}"
    )


def test_savings_read_routes_block_cross_tenant():
    """Savings read routes must not return another customer's accounts/portfolio.

    /api/savings/accounts and /api/savings/portfolio derived role from the USERS
    map only; a session-only customer was misclassified as staff and the requested
    ?customer_id= was honored. This creates a real B-owned account and asserts A
    cannot see it (skips if the portfolio service is disabled).
    """
    _seed_two_customers()

    create_status, create_body = _http_post(
        "/api/savings/create-account",
        {"customer_id": CUST_B, "policy_id": POL_B, "monthly_contribution": 500,
         "savings_rate_pct": 25, "risk_profile": "moderate"},
        token=TOKEN_B,
    )
    if create_status == 503:
        pytest.skip("portfolio/savings service disabled in this build")
    assert create_status in (200, 201), f"could not create B's account: {create_body[:300]}"
    account_id = json.loads(create_body).get("account_id")
    assert account_id

    for path in ("/api/savings/accounts", "/api/savings/portfolio"):
        status, body = _http_get(_attack(path, customer_id=CUST_B), token=TOKEN_A)
        assert account_id not in body, (
            f"{path} leaked customer B's account to customer A (HTTP {status}): {body[:300]}"
        )

    # Positive control: owner B can see their own account.
    status_b, body_b = _http_get(_attack("/api/savings/accounts", customer_id=CUST_B), token=TOKEN_B)
    assert status_b == 200 and account_id in body_b, (
        f"owner B could not see their own savings account (HTTP {status_b}): {body_b[:300]}"
    )


def test_owner_can_deposit_to_own_wallet_proves_guard_not_overbroad():
    """Positive control: customer B can still deposit into B's own wallet."""
    _seed_two_customers()
    before = float(portal.HEALTH_WALLETS[CUST_B]["balance"])

    status, body = _http_post(
        "/api/health-wallet/deposit",
        {"customer_id": CUST_B, "amount": 50.0, "payment_method": "card_on_file"},
        token=TOKEN_B,
    )

    assert status == 200, (
        f"Owner B was blocked from depositing into their own wallet (HTTP {status}): {body[:300]}"
    )
    after = float(portal.HEALTH_WALLETS[CUST_B]["balance"])
    assert after == before + 50.0, f"Owner B's deposit was not applied ({before} -> {after})"
