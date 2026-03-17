"""
Regression tests for redacted dynamic customer seed credentials.
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_CUSTOMERS_FILE = PROJECT_ROOT / "database" / "dynamic_customers.json"


def test_dynamic_customer_seed_credentials_are_redacted():
    """Seed data must not store reusable password hashes or salts."""
    dynamic_customers = json.loads(DYNAMIC_CUSTOMERS_FILE.read_text())

    exposed_fields = []
    for customer in dynamic_customers:
        identifier = (
            customer.get("email")
            or customer.get("username")
            or customer.get("customer_id")
            or "<unknown>"
        )
        for field in ("password_hash", "password_salt"):
            value = customer.get(field)
            if value is not None and value != "REDACTED":
                exposed_fields.append(f"{identifier}:{field}")

    assert not exposed_fields, (
        "dynamic_customers.json contains unredacted credential material: "
        + ", ".join(exposed_fields)
    )
