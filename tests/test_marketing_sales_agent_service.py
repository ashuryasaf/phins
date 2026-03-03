#!/usr/bin/env python3
"""Tests for the AI + BI marketing sales agent service."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.marketing_sales_agent_service import MarketingSalesAgentService


def _sample_data():
    customers = {
        "CUST-1": {"id": "CUST-1", "status": "active"},
        "CUST-2": {"id": "CUST-2", "status": "active"},
    }
    policies = {
        "POL-1": {"id": "POL-1", "status": "active", "customer_id": "CUST-1"},
        "POL-2": {"id": "POL-2", "status": "pending_billing", "customer_id": "CUST-2"},
    }
    billing = {
        "BILL-1": {"id": "BILL-1", "amount_due": 1200.0, "amount_paid": 1200.0, "status": "paid"},
        "BILL-2": {"id": "BILL-2", "amount_due": 300.0, "amount_paid": 100.0, "status": "partial"},
    }
    claims = {
        "CLM-1": {"id": "CLM-1", "status": "approved", "approved_amount": 250.0},
    }
    health_wallets = {
        "CUST-1": {"balance": 500.0},
    }
    investment_accounts = {
        "CUST-1": {"balance": 1000.0},
    }
    transaction_ledger = {
        "TX-1": {"id": "TX-1", "amount": 200.0},
        "TX-2": {"id": "TX-2", "amount": -50.0},
    }
    return {
        "customers": customers,
        "policies": policies,
        "billing": billing,
        "claims": claims,
        "health_wallets": health_wallets,
        "investment_accounts": investment_accounts,
        "transaction_ledger": transaction_ledger,
    }


def test_generate_campaign_returns_expected_sections_and_signature():
    svc = MarketingSalesAgentService(secret_key="unit-test-secret")
    datasets = _sample_data()

    generated = svc.generate_campaign(
        customers=datasets["customers"],
        policies=datasets["policies"],
        billing=datasets["billing"],
        claims=datasets["claims"],
        health_wallets=datasets["health_wallets"],
        investment_accounts=datasets["investment_accounts"],
        transaction_ledger=datasets["transaction_ledger"],
        vertical="insurance",
        objective="growth",
        persona="families",
        region="global",
        budget_tier="balanced",
        social_networks=["linkedin", "x", "unknown-network"],
        generated_by="tester",
    )

    assert "campaign" in generated
    assert "integrity" in generated
    assert generated["integrity"]["verified"] is True

    campaign = generated["campaign"]
    assert campaign["scope"]["vertical"] == "insurance"
    assert campaign["scope"]["objective"] == "growth"
    assert len(campaign["sales_playbooks"]) >= 4
    assert len(campaign["story_outlines"]) >= 2
    assert len(campaign["targeted_articles"]) >= 2
    assert len(campaign["ai_video_blueprints"]) >= 2
    assert len(campaign["social_network_plan"]) >= 2

    # Unknown networks should be removed by normalization.
    social_networks = {item["network"] for item in campaign["social_network_plan"]}
    assert "unknown-network" not in social_networks
    assert "linkedin" in social_networks

    assert svc.verify_campaign_payload(campaign, generated["integrity"]["signature"]) is True


def test_campaign_signature_fails_after_payload_tampering():
    svc = MarketingSalesAgentService(secret_key="unit-test-secret")
    datasets = _sample_data()
    generated = svc.generate_campaign(
        customers=datasets["customers"],
        policies=datasets["policies"],
        billing=datasets["billing"],
        claims=datasets["claims"],
        health_wallets=datasets["health_wallets"],
        investment_accounts=datasets["investment_accounts"],
        transaction_ledger=datasets["transaction_ledger"],
        vertical="health_wallet",
        objective="retention",
        persona="professionals",
        region="emea",
        budget_tier="efficient",
        social_networks=["linkedin", "youtube"],
        generated_by="tester",
    )

    signature = generated["integrity"]["signature"]
    tampered_campaign = dict(generated["campaign"])
    tampered_scope = dict(tampered_campaign["scope"])
    tampered_scope["objective"] = "growth"
    tampered_campaign["scope"] = tampered_scope

    assert svc.verify_campaign_payload(tampered_campaign, signature) is False


def test_build_media_briefs_creates_multiple_campaign_assets():
    svc = MarketingSalesAgentService(secret_key="unit-test-secret")
    datasets = _sample_data()
    generated = svc.generate_campaign(
        customers=datasets["customers"],
        policies=datasets["policies"],
        billing=datasets["billing"],
        claims=datasets["claims"],
        health_wallets=datasets["health_wallets"],
        investment_accounts=datasets["investment_accounts"],
        transaction_ledger=datasets["transaction_ledger"],
        vertical="investments",
        objective="cross_sell",
        persona="entrepreneurs",
        region="north_america",
        budget_tier="aggressive",
        social_networks=["linkedin", "youtube", "instagram"],
        generated_by="tester",
    )

    briefs = svc.build_media_briefs(generated["campaign"])
    assert len(briefs) >= 4
    brief_types = {item["brief_type"] for item in briefs}
    assert "story" in brief_types
    assert "video" in brief_types
    assert "article" in brief_types
