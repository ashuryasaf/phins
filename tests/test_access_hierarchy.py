"""Customer and staff dashboards stay on their own side of the book.

Customers cannot call admin APIs or open staff pages. Staff cannot open the
customer dashboard or move a customer's private money. Assessments, reports,
and billing stay available to both, with row scope still enforced.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
from security.access_hierarchy import (
    ACCESS_DENIED,
    api_denial,
    home_for_role,
    surface_decision,
)


BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def test_customer_cannot_open_staff_pages_or_admin_apis():
    decision = surface_decision("customer", "/admin-portal.html")
    assert decision["allowed"] is False
    assert decision["redirect"] == "/dashboard.html"
    assert surface_decision("customer", "/admin.html")["redirect"] == "/dashboard.html"
    assert surface_decision("customer", "/underwriter-dashboard.html")["allowed"] is False
    assert api_denial("customer", "GET", "/api/admin/customers") == ACCESS_DENIED
    assert api_denial("customer", "POST", "/api/admin/pipeline-process-all") == ACCESS_DENIED
    assert api_denial("customer", "GET", "/api/pipeline/summary") == ACCESS_DENIED
    assert api_denial("supplier", "GET", "/api/admin/customers") == ACCESS_DENIED
    assert api_denial("agent", "POST", "/api/health-wallet/purchase") == ACCESS_DENIED


def test_staff_cannot_open_customer_private_surfaces():
    for role in ("admin", "underwriter", "accountant", "claims", "actuary"):
        decision = surface_decision(role, "/dashboard.html")
        assert decision["allowed"] is False, role
        assert decision["redirect"] == home_for_role(role)
        assert surface_decision(role, "/savings-portfolio.html")["allowed"] is False
        assert api_denial(role, "GET", "/api/health-wallet") == ACCESS_DENIED
        assert api_denial(role, "POST", "/api/health-wallet/purchase") == ACCESS_DENIED
        assert api_denial(role, "POST", "/api/pipeline/deposit") == ACCESS_DENIED
        assert api_denial(role, "POST", "/api/savings/invest") == ACCESS_DENIED
        assert api_denial(role, "POST", "/api/unified-payment/deposit") == ACCESS_DENIED


def test_shared_operational_surfaces_stay_open():
    for role in ("customer", "admin", "accountant", "underwriter"):
        for page in ("/billing.html", "/assessment-center.html", "/documents.html", "/customer-ai-report.html"):
            decision = surface_decision(role, page)
            assert decision["allowed"] is True, (role, page)
            assert decision["surface"] == "shared"
    assert api_denial("admin", "GET", "/api/admin/customers") is None
    assert api_denial("accountant", "GET", "/api/billing") is None
    assert api_denial("admin", "GET", "/api/health-wallet/purchases") is None
    assert api_denial("customer", "GET", "/api/pipeline/analytics") is None
    assert api_denial("admin", "POST", "/api/pipeline/allocate") is None
    assert surface_decision("underwriter", "/admin.html")["allowed"] is False
    assert surface_decision("admin", "/underwriter-dashboard.html")["allowed"] is True
    assert surface_decision("admin", "/supplier-portal.html")["allowed"] is False
    assert surface_decision("supplier", "/dashboard.html")["redirect"] == "/supplier-dashboard.html"


def test_anonymous_api_gate_does_not_invent_a_role():
    assert api_denial("", "GET", "/api/admin/customers") is None
    assert api_denial(None, "POST", "/api/health-wallet/purchase") is None
    assert surface_decision("", "/admin.html")["allowed"] is True


def _mark_test_port_initialized() -> None:
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    port = int(os.environ.get("TEST_PORT", "8000"))
    if isinstance(init_set, set):
        init_set.add(port)


def _session(token: str, role: str, customer_id: str | None = None) -> str:
    username = f"hierarchy-{role}"
    portal.USERS[username] = {
        "role": role,
        "customer_id": customer_id,
        "name": username,
    }
    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": customer_id,
        "expires": "2099-01-01T00:00:00",
    }
    _mark_test_port_initialized()
    return token


def _cleanup(token: str, role: str) -> None:
    portal.SESSIONS.pop(token, None)
    portal.USERS.pop(f"hierarchy-{role}", None)


def _get(path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(BASE_URL + path, headers=headers), timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"error": raw}
        return exc.code, body


def _post(path: str, payload: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE_URL + path, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"error": raw}
        return exc.code, body


def test_http_customer_is_blocked_from_admin_and_other_customers():
    token = _session("phins_hierarchy_customer", "customer", "CUST-HIER-A")
    portal.POLICIES["POL-HIER-A"] = {"id": "POL-HIER-A", "customer_id": "CUST-HIER-A", "status": "active"}
    portal.POLICIES["POL-HIER-B"] = {"id": "POL-HIER-B", "customer_id": "CUST-HIER-B", "status": "active"}
    portal.CUSTOMERS["CUST-HIER-B"] = {"id": "CUST-HIER-B", "name": "Other Customer", "email": "other@hier.test"}
    try:
        status, body = _get("/api/admin/customers", token)
        assert status == 403
        assert body.get("error") == ACCESS_DENIED

        status, body = _get("/api/pipeline/summary", token)
        assert status == 403

        status, own_policy = _get("/api/policies?id=POL-HIER-A", token)
        assert status == 200
        assert own_policy.get("customer_id") == "CUST-HIER-A"

        status, body = _get("/api/policies?page_size=500", token)
        assert status == 200
        assert all(item.get("customer_id") == "CUST-HIER-A" for item in body.get("items", []))
        assert "POL-HIER-B" not in [item.get("id") for item in body.get("items", [])]

        status, body = _get("/api/policies?id=POL-HIER-B", token)
        assert status == 404

        status, body = _get("/api/customers?id=CUST-HIER-B", token)
        assert status == 403

        status, body = _get("/api/pipeline/analytics?customer_id=CUST-HIER-B", token)
        assert status == 403

        status, own = _get("/api/pipeline/analytics?customer_id=CUST-HIER-A", token)
        assert status != 403
        if status == 200:
            assert own.get("error") != ACCESS_DENIED

        status, surface = _get("/api/access/surface?path=/admin.html", token)
        assert status == 200
        assert surface["allowed"] is False
        assert surface["redirect"] == "/dashboard.html"

        status, shared = _get("/api/access/surface?path=/billing.html", token)
        assert status == 200
        assert shared["allowed"] is True
    finally:
        _cleanup(token, "customer")
        portal.POLICIES.pop("POL-HIER-A", None)
        portal.POLICIES.pop("POL-HIER-B", None)
        portal.CUSTOMERS.pop("CUST-HIER-B", None)


def test_http_admin_keeps_operations_and_loses_customer_private_actions():
    token = _session("phins_hierarchy_admin", "admin")
    try:
        status, body = _get("/api/admin/customers", token)
        assert status == 200
        assert "error" not in body or "customers" in body

        status, body = _get("/api/health-wallet?customer_id=CUST-HIER-A", token)
        assert status == 403
        assert body.get("error") == ACCESS_DENIED

        status, body = _post(
            "/api/health-wallet/purchase",
            {"customer_id": "CUST-HIER-A", "product_id": "x", "amount": 10},
            token,
        )
        assert status == 403

        status, body = _post(
            "/api/pipeline/deposit",
            {"customer_id": "CUST-HIER-A", "amount": 25},
            token,
        )
        assert status == 403

        status, surface = _get("/api/access/surface?path=/dashboard.html", token)
        assert status == 200
        assert surface["allowed"] is False
        assert surface["redirect"] == "/admin-portal.html"

        status, billing = _get("/api/access/surface?path=/assessment-center.html", token)
        assert billing["allowed"] is True
        status, reports = _get("/api/access/surface?path=/customer-ai-report.html", token)
        assert reports["allowed"] is True
    finally:
        _cleanup(token, "admin")


def test_http_supplier_cannot_read_the_customer_book():
    token = _session("phins_hierarchy_supplier", "supplier")
    portal.POLICIES["POL-HIER-SUP"] = {
        "id": "POL-HIER-SUP",
        "customer_id": "CUST-HIER-SUP",
        "status": "active",
    }
    try:
        status, body = _get("/api/policies", token)
        assert status == 403
        assert body.get("error") == "Access denied"
        status, surface = _get("/api/access/surface?path=/dashboard.html", token)
        assert surface["redirect"] == "/supplier-dashboard.html"
    finally:
        _cleanup(token, "supplier")
        portal.POLICIES.pop("POL-HIER-SUP", None)


def test_ui_clarity_enforces_the_surface_and_drops_customer_portfolio_for_staff():
    with urlopen(BASE_URL + "/ui-clarity.js", timeout=20) as resp:
        content = resp.read().decode("utf-8")
    assert "async function enforceSurface()" in content
    assert "/api/access/surface?path=" in content
    assert "A staff account cannot open a customer's savings portfolio." in content
    assert "A staff account cannot open a customer's wallet." in content
    assert 'url: "/savings-portfolio.html"' not in content
    assert 'if (isAdminRole(role))' in content
    assert 'return "admin";' in content
    assert "hasAdminAssistant || isStaffPath" not in content
    assert "open savings portfolio dashboard" not in content
