"""Role surfaces for customer, staff, and other portals.

Customers and staff share a few operational tools (assessments, reports,
billing, documents). Everything else stays on the caller's own dashboard:

* a customer session cannot call ``/api/admin/`` or open a staff dashboard
* a staff session cannot open the customer dashboard or move a customer's
  private money (wallet, savings, pipeline deposit)
* a supplier, agent, or regulator session cannot read another customer's book

The HTTP gate in ``web_portal/server.py`` and the page decision used by
``/api/access/surface`` both call this module so the two stay aligned.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Optional

ACCESS_DENIED = "Access denied"

# Staff who operate the book: assessments, reports, billing, claims, policies.
OPERATIONAL_STAFF_ROLES: FrozenSet[str] = frozenset({
    "admin",
    "underwriter",
    "claims",
    "claims_adjuster",
    "adjuster",
    "accountant",
    "actuary",
    "compliance",
    "founder",
})

# May pass the /api/admin/ prefix. Handlers still narrow further.
ADMIN_API_ROLES: FrozenSet[str] = OPERATIONAL_STAFF_ROLES | frozenset({"media"})

# Another principal's own portal. Admin does not inherit these.
PRIVATE_PORTAL_PAGES: Dict[str, FrozenSet[str]] = {
    "/supplier-dashboard.html": frozenset({"supplier"}),
    "/supplier-portal.html": frozenset({"supplier"}),
    "/supplier-login.html": frozenset({"supplier"}),
    "/supplier-register.html": frozenset({"supplier"}),
    "/agent-portal.html": frozenset({"agent"}),
    "/regulator-dashboard.html": frozenset({"regulator"}),
}

# Staff tools. ``admin`` is added for every page except the private portals above.
STAFF_PAGES: Dict[str, FrozenSet[str]] = {
    "/admin.html": frozenset(),
    "/admin-portal.html": frozenset(),
    "/admin-agents.html": frozenset(),
    "/admin-foundations.html": frozenset(),
    "/admin-supplier-dashboard.html": frozenset(),
    "/admin-media.html": frozenset({"media"}),
    "/underwriter-dashboard.html": frozenset({"underwriter"}),
    "/claims-adjuster-dashboard.html": frozenset({"claims", "claims_adjuster", "adjuster"}),
    "/accountant-dashboard.html": frozenset({"accountant"}),
    "/actuary-dashboard.html": frozenset({"actuary"}),
    "/customer-management.html": frozenset({"accountant", "underwriter", "claims", "claims_adjuster", "adjuster"}),
    "/unified-workbench.html": frozenset({"underwriter", "actuary", "accountant", "claims", "claims_adjuster", "adjuster"}),
    "/risk-dashboard.html": frozenset({"underwriter", "actuary"}),
    "/risk-reports-dashboard.html": frozenset({"underwriter", "actuary", "accountant"}),
    "/video-agents.html": frozenset({"media"}),
    "/pitch-dashboard.html": frozenset(),
    "/corporate-legal-dashboard.html": frozenset(),
    "/nda-dashboard.html": frozenset(),
    "/settlement-approval.html": frozenset({"accountant"}),
    **PRIVATE_PORTAL_PAGES,
}

# The customer's own dashboard. Staff use assessments, reports, and billing
# instead of signing in as that customer.
CUSTOMER_PRIVATE_PAGES: FrozenSet[str] = frozenset({
    "/dashboard.html",
    "/savings-portfolio.html",
    "/algo-trading.html",
    # Each customer's own Mislaka tool. Staff stay on the admin assessment
    # surfaces and are not given this personal view.
    "/mislaka-report.html",
})

# Both sides may open these. APIs still scope rows to the caller.
SHARED_OPERATIONAL_PAGES: FrozenSet[str] = frozenset({
    "/assessment-center.html",
    "/billing.html",
    "/documents.html",
    "/customer-ai-report.html",
    "/risk-assessment-viewer.html",
    "/file-a-claim.html",
    "/claims-chat.html",
    "/apply.html",
    "/apply-chat.html",
})

ROLE_HOME: Dict[str, str] = {
    "admin": "/admin-portal.html",
    "media": "/admin-media.html",
    "underwriter": "/underwriter-dashboard.html",
    "claims": "/claims-adjuster-dashboard.html",
    "claims_adjuster": "/claims-adjuster-dashboard.html",
    "adjuster": "/claims-adjuster-dashboard.html",
    "accountant": "/accountant-dashboard.html",
    "actuary": "/actuary-dashboard.html",
    "compliance": "/admin-portal.html",
    "founder": "/admin-portal.html",
    "regulator": "/regulator-dashboard.html",
    "supplier": "/supplier-dashboard.html",
    "agent": "/agent-portal.html",
    "customer": "/dashboard.html",
}

# Customer-private mutations and the wallet read that creates a wallet row.
# Purchase history stays available to staff (it is the billing trail).
_CUSTOMER_PRIVATE_POST_PREFIXES = (
    "/api/health-wallet/deposit",
    "/api/health-wallet/purchase",
    "/api/pipeline/deposit",
    "/api/pipeline/settings",
    "/api/unified-payment/deposit",
    "/api/marketplace/wallet",
    "/api/savings/deposit",
    "/api/savings/invest",
    "/api/savings/sell",
    "/api/savings/update-risk-profile",
    "/api/balance/transfer-to-algo",
)

_STAFF_ONLY_EXACT = frozenset({
    "/api/pipeline/summary",
    "/api/pipeline/market-conditions",
})


def normalize_role(role: Optional[str]) -> str:
    return str(role or "").strip().lower()


def normalize_page(path: Optional[str]) -> str:
    raw = str(path or "").split("?", 1)[0].split("#", 1)[0].strip()
    if not raw:
        return "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw[:-1]
    return raw.lower()


def is_operational_staff(role: Optional[str]) -> bool:
    return normalize_role(role) in OPERATIONAL_STAFF_ROLES


def home_for_role(role: Optional[str]) -> str:
    return ROLE_HOME.get(normalize_role(role), "/login.html")


def page_roles(page: str) -> FrozenSet[str]:
    """Roles allowed to open a staff page. Admin oversees staff tools only."""
    extra = STAFF_PAGES.get(page, frozenset())
    if page in PRIVATE_PORTAL_PAGES:
        return extra
    return extra | frozenset({"admin"})


def surface_decision(role: Optional[str], path: Optional[str]) -> Dict[str, Optional[str]]:
    """Decide whether this role may render ``path``.

    Unknown pages stay open (marketing, login, settings). Known dashboards
    redirect to the role's own home instead of rendering the other side.
    """
    normalized_role = normalize_role(role)
    page = normalize_page(path)
    if not normalized_role:
        return {"allowed": True, "redirect": None, "surface": "anonymous", "role": ""}

    if page in SHARED_OPERATIONAL_PAGES:
        return {"allowed": True, "redirect": None, "surface": "shared", "role": normalized_role}

    if page in CUSTOMER_PRIVATE_PAGES:
        if normalized_role == "customer":
            return {"allowed": True, "redirect": None, "surface": "customer", "role": normalized_role}
        return {
            "allowed": False,
            "redirect": home_for_role(normalized_role),
            "surface": "customer_private",
            "role": normalized_role,
        }

    if page in STAFF_PAGES:
        allowed = page_roles(page)
        if normalized_role in allowed:
            return {"allowed": True, "redirect": None, "surface": "staff", "role": normalized_role}
        return {
            "allowed": False,
            "redirect": home_for_role(normalized_role),
            "surface": "staff",
            "role": normalized_role,
        }

    return {"allowed": True, "redirect": None, "surface": "public", "role": normalized_role}


_CUSTOMER_PERSONAL_MISLAKA = "/api/assessment-center/mislaka/personal"


def _customer_private_api(method: str, path: str) -> bool:
    if path == _CUSTOMER_PERSONAL_MISLAKA or path.startswith(_CUSTOMER_PERSONAL_MISLAKA + "/"):
        return method in ("GET", "POST")
    if method == "GET":
        if path == "/api/health-wallet":
            return True
        if path.startswith("/api/health-wallet/") and not path.startswith("/api/health-wallet/purchases"):
            return True
        return False
    if method != "POST":
        return False
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _CUSTOMER_PRIVATE_POST_PREFIXES)


def api_denial(role: Optional[str], method: str, path: Optional[str]) -> Optional[str]:
    """Return an error string when this role must not call the path.

    ``None`` means this gate does not deny. Handlers still enforce ownership.
    Anonymous callers are left to the handler so test-mode probes and the
    existing 401/403 responses stay intact.
    """
    normalized_role = normalize_role(role)
    if not normalized_role:
        return None
    normalized_path = normalize_page(path)
    normalized_method = str(method or "GET").strip().upper()

    if normalized_path.startswith("/api/admin/"):
        if normalized_role not in ADMIN_API_ROLES:
            return ACCESS_DENIED
        return None

    if normalized_path in _STAFF_ONLY_EXACT:
        if not is_operational_staff(normalized_role):
            return ACCESS_DENIED
        return None

    if _customer_private_api(normalized_method, normalized_path):
        if normalized_role != "customer":
            return ACCESS_DENIED
        return None

    return None
