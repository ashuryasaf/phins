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
    suppliers = {
        "SUP-1": {"supplier_type": "lawyer", "status": "approved"},
        "SUP-2": {"supplier_type": "doctor", "status": "active"},
        "SUP-3": {"supplier_type": "pharmacy", "status": "pending"},
        "SUP-4": {"supplier_type": "delivery", "status": "approved"},
    }
    supplier_orders = {
        "ORD-1": {"supplier_id": "SUP-1", "amount": 250.0},
        "ORD-2": {"supplier_id": "SUP-2", "amount": 400.0},
        "ORD-3": {"supplier_id": "SUP-4", "amount": 180.0},
    }
    return {
        "customers": customers,
        "policies": policies,
        "billing": billing,
        "claims": claims,
        "health_wallets": health_wallets,
        "investment_accounts": investment_accounts,
        "transaction_ledger": transaction_ledger,
        "suppliers": suppliers,
        "supplier_orders": supplier_orders,
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
        suppliers=datasets["suppliers"],
        supplier_orders=datasets["supplier_orders"],
        audience_mode="hybrid",
        supplier_segments=["lawyers", "doctors"],
        social_provider="veo",
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
    assert "supplier_signals" in campaign
    assert "supplier_sales_playbooks" in campaign
    assert campaign["scope"]["audience_mode"] == "hybrid"

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
        suppliers=datasets["suppliers"],
        supplier_orders=datasets["supplier_orders"],
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
        suppliers=datasets["suppliers"],
        supplier_orders=datasets["supplier_orders"],
    )

    briefs = svc.build_media_briefs(generated["campaign"])
    assert len(briefs) >= 4
    brief_types = {item["brief_type"] for item in briefs}
    assert "story" in brief_types
    assert "video" in brief_types
    assert "article" in brief_types
    assert "social" in brief_types


def test_provider_status_includes_veo_and_kling_entries():
    svc = MarketingSalesAgentService(secret_key="unit-test-secret")
    providers = svc.get_provider_status()

    assert "veo" in providers
    assert "kling" in providers
    assert providers["veo"]["provider"] == "veo"
    assert "connected" in providers["kling"]


def test_build_social_content_package_integrity_and_media_briefs():
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
        suppliers=datasets["suppliers"],
        supplier_orders=datasets["supplier_orders"],
        vertical="suppliers",
        objective="growth",
        persona="providers",
        region="global",
        budget_tier="balanced",
        social_networks=["facebook", "instagram", "youtube"],
        generated_by="tester",
        audience_mode="supplier",
        supplier_segments=["lawyers", "delivery"],
        social_provider="kling",
    )

    package = svc.build_social_content_package(
        campaign_payload=generated["campaign"],
        provider="kling",
        social_networks=["facebook", "instagram", "youtube"],
        hook="Scale high-trust supplier demand now.",
        offer="Verified experts + AI matching for urgent needs.",
        cta="Start today.",
        target_group="facebook and instagram communities",
        duration_seconds=22,
        aspect_ratio="9:16",
        execution_mode="dry_run",
        created_by="tester",
    )
    social_payload = package["social_content"]
    integrity = package["integrity"]
    assert social_payload["provider"] == "kling"
    assert social_payload["duration_seconds"] == 22
    assert len(social_payload["network_packages"]) >= 2
    assert svc.verify_payload_integrity(social_payload, integrity) is True

    briefs = svc.build_social_content_media_briefs(social_payload)
    assert len(briefs) >= 3
    brief_types = {item["brief_type"] for item in briefs}
    assert "social_video_prompt" in brief_types
    assert "social_script" in brief_types
    assert "social_caption" in brief_types


def test_social_learning_aggregation_uses_signed_events():
    svc = MarketingSalesAgentService(secret_key="unit-test-secret")
    event_one = svc.record_social_learning_event(
        campaign_id="MKT-TEST",
        platform="facebook",
        group_name="insurance-growth-group",
        content_id="post-1",
        metrics={
            "impressions": 1000,
            "likes": 80,
            "comments": 22,
            "shares": 10,
            "clicks": 60,
            "leads": 15,
            "conversions": 4,
            "spend": 120,
        },
        recorded_by="tester",
    )
    event_two = svc.record_social_learning_event(
        campaign_id="MKT-TEST",
        platform="instagram",
        group_name="ig-insurance-reels",
        content_id="reel-2",
        metrics={
            "impressions": 1800,
            "likes": 150,
            "comments": 30,
            "shares": 25,
            "clicks": 90,
            "leads": 22,
            "conversions": 7,
            "spend": 180,
        },
        recorded_by="tester",
    )

    summary = svc.aggregate_social_learning([event_one, event_two])
    assert summary["total_events"] == 2
    assert summary["verified_events"] == 2
    assert summary["invalid_events"] == 0
    assert summary["summary"]["impressions"] == 2800.0
    assert len(summary["by_platform"]) >= 2
