"""Customer statement / allocation defaults follow the actuarial kernel.

The retired dashboard split of 75% risk / 25% savings must not be used
when a customer has no stored preference or when a policy carries a
kernel pin.
"""

import web_portal.server as portal


def test_default_customer_allocation_is_kernel_50_50():
    alloc = portal.DEFAULT_CUSTOMER_ALLOCATION
    assert alloc["savings_pct"] == 50.0
    assert alloc["risk_pct"] == 50.0
    assert abs(alloc["savings_pct"] + alloc["risk_pct"] - 100.0) < 0.01
    assert abs(alloc["wallet_pct"] + alloc["investment_pct"] + alloc["algo_pct"] - 100.0) < 0.01


def test_get_customer_allocation_defaults_without_override():
    cid = "CUST-KERNEL-DEFAULT-TEST"
    portal.CUSTOMER_ALLOCATIONS.pop(cid, None)
    alloc = portal.get_customer_allocation(cid)
    assert alloc["savings_pct"] == 50.0
    assert alloc["risk_pct"] == 50.0


def test_get_mock_statement_uses_allocation_not_legacy_75_25():
    cid = "CUST-STMT-SPLIT-001"
    policy_id = "POL-STMT-SPLIT-001"
    portal.CUSTOMER_ALLOCATIONS.pop(cid, None)
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": cid,
        "status": "active",
        "type": "life",
        "monthly_premium": 200.0,
        "annual_premium": 2400.0,
        "coverage_amount": 100000,
    }
    try:
        stmt = portal.get_mock_statement(cid)
        assert stmt["policies_count"] == 1
        assert stmt["total_premium"] == 200.0
        assert stmt["risk_pct"] == 50.0
        assert stmt["savings_pct"] == 50.0
        assert stmt["risk_total"] == 100.0
        assert stmt["savings_total"] == 100.0
        assert stmt["allocations"][0]["risk_amount"] == 100.0
        assert stmt["allocations"][0]["savings_amount"] == 100.0
    finally:
        portal.POLICIES.pop(policy_id, None)


def test_empty_engine_statement_falls_back_to_kernel_book():
    cid = "CUST-STMT-ENGINE-EMPTY"
    policy_id = "POL-STMT-ENGINE-EMPTY"
    portal.CUSTOMER_ALLOCATIONS.pop(cid, None)
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": cid,
        "status": "active",
        "type": "phins_unified",
        "monthly_premium": 150.0,
        "annual_premium": 1800.0,
        "risk_premium_annual": 1200.0,
        "savings_premium_annual": 600.0,
        "pricing_source": "pricing_kernel",
    }
    try:
        assert portal.try_get_statement_from_engine(cid) is None
        stmt = portal.try_get_statement_from_engine(cid) or portal.get_mock_statement(cid)
        assert stmt["policies_count"] == 1
        assert stmt["total_premium"] == 150.0
        assert abs(stmt["risk_total"] - 100.0) <= 0.02
        assert abs(stmt["savings_total"] - 50.0) <= 0.02
        assert stmt["allocations"][0]["split_source"].startswith("kernel")
    finally:
        portal.POLICIES.pop(policy_id, None)


def test_get_mock_statement_prefers_kernel_pin_over_allocation():
    cid = "CUST-STMT-KERNEL-001"
    policy_id = "POL-STMT-KERNEL-001"
    portal.CUSTOMER_ALLOCATIONS[cid] = {
        **portal.DEFAULT_CUSTOMER_ALLOCATION,
        "savings_pct": 50.0,
        "risk_pct": 50.0,
        "customer_id": cid,
    }
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": cid,
        "status": "Active",
        "type": "life",
        "monthly_premium": 100.0,
        "annual_premium": 1200.0,
        "risk_premium_annual": 900.0,
        "savings_premium_annual": 300.0,
        "pricing_source": "pricing_kernel",
        "integrity_hash": "abc123",
    }
    try:
        stmt = portal.get_mock_statement(cid)
        assert stmt["total_premium"] == 100.0
        # 900/1200 = 75% risk of the monthly premium → $75 / $25
        assert stmt["risk_total"] == 75.0
        assert stmt["savings_total"] == 25.0
        assert stmt["risk_pct"] == 75.0
        assert stmt["savings_pct"] == 25.0
        assert stmt["allocations"][0]["split_source"].startswith("kernel")
        assert stmt["allocations"][0]["integrity_hash"] == "abc123"
    finally:
        portal.POLICIES.pop(policy_id, None)
        portal.CUSTOMER_ALLOCATIONS.pop(cid, None)
