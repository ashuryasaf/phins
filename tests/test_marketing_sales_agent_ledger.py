#!/usr/bin/env python3
"""B7 — Marketing / Sales Agent: input-hash plan cache, BI cohort targeting,
and platform-ledger anchoring of published plans.

Service-level tests run against an isolated ``MarketingSalesAgentService`` and
an isolated in-memory ``PlatformEventLedgerService``; the HTTP tests go through
the embedded portal started by the root ``conftest.py``.
"""

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.marketing_sales_agent_service import (  # noqa: E402
    MARKETING_PUBLISH_EVENT_TYPE,
    PLAN_VERSION,
    MarketingSalesAgentService,
)
from services.platform_event_ledger_service import (  # noqa: E402
    PlatformEventLedgerService,
    reconcile_ledger_entries,
)


def _datasets():
    return {
        "customers": {
            "CUST-1": {"id": "CUST-1", "status": "active"},
            "CUST-2": {"id": "CUST-2", "status": "active"},
            "CUST-3": {"id": "CUST-3", "status": "active"},
            "CUST-4": {"id": "CUST-4", "status": "active"},
        },
        "policies": {
            "POL-1": {"id": "POL-1", "status": "active", "customer_id": "CUST-1"},
            "POL-2": {"id": "POL-2", "status": "pending_billing", "customer_id": "CUST-2"},
        },
        "billing": {
            "BILL-1": {"id": "BILL-1", "amount_due": 1200.0, "amount_paid": 1200.0, "status": "paid"},
            "BILL-2": {"id": "BILL-2", "amount_due": 300.0, "amount_paid": 100.0, "status": "partial"},
        },
        "claims": {"CLM-1": {"id": "CLM-1", "status": "approved", "approved_amount": 250.0}},
        "health_wallets": {"CUST-1": {"balance": 500.0}},
        "investment_accounts": {"CUST-1": {"balance": 1000.0}, "CUST-2": {"balance": 10.0}},
        "transaction_ledger": {
            "TX-1": {"id": "TX-1", "amount": 200.0, "customer_id": "CUST-1"},
            "TX-2": {"id": "TX-2", "amount": -50.0, "customer_id": "CUST-3"},
        },
    }


def _customer_analytics(ds):
    """The shape ``BIAnalyticsService.get_customer_analytics`` returns."""
    from services.bi_analytics_service import BIAnalyticsService
    svc = BIAnalyticsService(cache_ttl_seconds=0, materialized_path=os.devnull)
    return svc.get_customer_analytics(
        ds["customers"], ds["health_wallets"], ds["investment_accounts"],
        ds["transaction_ledger"], ds["policies"],
    )


def _generate(svc, ds, **overrides):
    kwargs = dict(
        vertical="insurance", objective="growth", persona="families", region="global",
        budget_tier="balanced", social_networks=["linkedin", "x"], generated_by="tester",
    )
    kwargs.update(overrides)
    return svc.generate_campaign(
        customers=ds["customers"], policies=ds["policies"], billing=ds["billing"],
        claims=ds["claims"], health_wallets=ds["health_wallets"],
        investment_accounts=ds["investment_accounts"], transaction_ledger=ds["transaction_ledger"],
        **kwargs,
    )


@pytest.fixture
def svc():
    return MarketingSalesAgentService(secret_key="unit-test-secret")


@pytest.fixture
def ledger():
    return PlatformEventLedgerService(transaction_ledger={}, use_database=False)


# ---------------------------------------------------------------------------
# input hash + plan cache
# ---------------------------------------------------------------------------

class TestInputHashAndPlanCache:
    def test_input_hash_is_signed_and_matches_the_integrity_block(self, svc):
        out = _generate(svc, _datasets())
        campaign, integrity = out["campaign"], out["integrity"]
        assert campaign["plan_version"] == PLAN_VERSION
        assert len(campaign["input_hash"]) == 64
        assert integrity["input_hash"] == campaign["input_hash"]
        assert campaign["campaign_id"] == f"MKT-{campaign['input_hash'][:16].upper()}"
        assert svc.verify_campaign_payload(campaign, integrity["signature"]) is True
        # Editing the recorded input hash breaks the signature — it is covered.
        tampered = copy.deepcopy(campaign)
        tampered["input_hash"] = "0" * 64
        assert svc.verify_campaign_payload(tampered, integrity["signature"]) is False

    def test_identical_inputs_hit_the_cache_and_return_the_same_signed_plan(self, svc):
        ds = _datasets()
        first = _generate(svc, ds)
        second = _generate(svc, ds, generated_by="someone-else")
        assert first["plan_cache"] == {"hit": False, "input_hash": first["campaign"]["input_hash"]}
        assert second["plan_cache"]["hit"] is True
        assert second["campaign"] == first["campaign"]
        assert second["integrity"]["signature"] == first["integrity"]["signature"]
        stats = svc.plan_cache_stats()
        assert stats["hits"] == 1 and stats["misses"] == 1 and stats["entries"] == 1

    def test_cache_returns_copies_so_callers_cannot_poison_it(self, svc):
        ds = _datasets()
        first = _generate(svc, ds)
        first["campaign"]["scope"]["objective"] = "tampered"
        second = _generate(svc, ds)
        assert second["campaign"]["scope"]["objective"] == "growth"
        assert svc.verify_campaign_payload(second["campaign"], second["integrity"]["signature"])

    def test_any_input_change_misses_the_cache(self, svc):
        ds = _datasets()
        base = _generate(svc, ds)
        assert _generate(svc, ds, objective="retention")["plan_cache"]["hit"] is False
        assert _generate(svc, ds, social_networks=["youtube"])["plan_cache"]["hit"] is False
        changed = copy.deepcopy(ds)
        changed["billing"]["BILL-2"]["amount_paid"] = 300.0
        moved = _generate(svc, changed)
        assert moved["plan_cache"]["hit"] is False
        assert moved["campaign"]["input_hash"] != base["campaign"]["input_hash"]
        assert moved["campaign"]["campaign_id"] != base["campaign"]["campaign_id"]

    def test_publication_anchor_on_the_ledger_does_not_change_the_next_plans_inputs(self, svc, ledger):
        ds = _datasets()
        ledger.transaction_ledger = ds["transaction_ledger"]
        first = _generate(svc, ds)
        svc.anchor_publication(ledger, first["campaign"], first["integrity"], publisher="ops")
        assert len(ds["transaction_ledger"]) == 3  # the anchor landed in the same store
        second = _generate(svc, ds)
        assert second["plan_cache"]["hit"] is True
        assert second["campaign"]["bi_signals"]["ledger"] == {"transaction_count": 2, "volume": 250.0}

    def test_use_cache_false_bypasses_but_still_hashes(self, svc):
        ds = _datasets()
        a = _generate(svc, ds, use_cache=False)
        b = _generate(svc, ds, use_cache=False)
        assert a["plan_cache"]["hit"] is False and b["plan_cache"]["hit"] is False
        assert a["campaign"]["input_hash"] == b["campaign"]["input_hash"]
        assert svc.plan_cache_stats()["entries"] == 0

    def test_cache_is_bounded_lru(self):
        svc = MarketingSalesAgentService(secret_key="s", plan_cache_size=2)
        ds = _datasets()
        for objective in ("growth", "retention", "cross_sell"):
            _generate(svc, ds, objective=objective)
        assert svc.plan_cache_stats()["entries"] == 2
        assert _generate(svc, ds, objective="growth")["plan_cache"]["hit"] is False  # evicted
        assert _generate(svc, ds, objective="cross_sell")["plan_cache"]["hit"] is True


# ---------------------------------------------------------------------------
# BI cohort targeting
# ---------------------------------------------------------------------------

class TestCohortTargeting:
    def test_cohorts_are_derived_deterministically_from_bi_customer_analytics(self):
        ds = _datasets()
        analytics = _customer_analytics(ds)
        cohorts = MarketingSalesAgentService.derive_cohorts(analytics)
        by_id = {c["cohort_id"]: c for c in cohorts}
        # 4 customers: 1 wallet, 2 investment accounts, 2 with policies, 2 transactors.
        assert by_id["wallet_gap"]["size"] == 3 and by_id["wallet_gap"]["share_pct"] == 75.0
        assert by_id["investment_gap"]["size"] == 2
        assert by_id["policy_gap"]["size"] == 2
        assert by_id["high_value"]["size"] == 2
        assert [c["cohort_id"] for c in cohorts] == ["wallet_gap", "high_value", "investment_gap", "policy_gap"]
        assert [c["priority"] for c in cohorts] == [1, 2, 3, 4]
        assert cohorts == MarketingSalesAgentService.derive_cohorts(copy.deepcopy(analytics))
        # No customer identifiers leak into the plan.
        assert "CUST-1" not in json.dumps(cohorts)

    def test_empty_or_missing_analytics_means_broad_targeting(self, svc):
        assert MarketingSalesAgentService.derive_cohorts(None) == []
        assert MarketingSalesAgentService.derive_cohorts({}) == []
        out = _generate(svc, _datasets())
        assert out["campaign"]["targeting"] == {"mode": "broad", "source": None, "cohorts": []}
        assert all("target_cohort" not in p for p in out["campaign"]["sales_playbooks"])

    def test_cohorts_reorder_playbooks_deterministically_and_change_the_hash(self, svc):
        ds = _datasets()
        broad = _generate(svc, ds)
        analytics = _customer_analytics(ds)
        targeted = _generate(svc, ds, customer_analytics=analytics)
        again = _generate(svc, ds, customer_analytics=copy.deepcopy(analytics))

        assert targeted["plan_cache"]["hit"] is False
        assert again["plan_cache"]["hit"] is True and again["campaign"] == targeted["campaign"]
        assert targeted["campaign"]["input_hash"] != broad["campaign"]["input_hash"]
        assert targeted["campaign"]["targeting"]["mode"] == "bi_cohorts"

        playbooks = targeted["campaign"]["sales_playbooks"]
        names = [p["playbook"] for p in playbooks]
        # Largest cohort (wallet_gap) leads; then high_value, investment_gap, policy_gap.
        assert names[:4] == [
            "Wallet First, Coverage Second",
            "Trust-to-Upgrade Flywheel",
            "Investment Parallel Offer",
            "Lifecycle Trigger Ladder",
        ]
        assert playbooks[0]["target_cohort"]["cohort_id"] == "wallet_gap"
        assert playbooks[0]["target_cohort"]["priority"] == 1
        # Same set of playbooks as the broad plan — re-ordered and annotated, never dropped.
        assert sorted(names) == sorted(p["playbook"] for p in broad["campaign"]["sales_playbooks"])
        assert svc.verify_campaign_payload(targeted["campaign"], targeted["integrity"]["signature"])


# ---------------------------------------------------------------------------
# ledger anchoring
# ---------------------------------------------------------------------------

class TestLedgerAnchoring:
    def test_publish_anchors_signature_and_input_hash_and_is_idempotent(self, svc, ledger):
        out = _generate(svc, _datasets())
        campaign, integrity = out["campaign"], out["integrity"]

        anchor = svc.anchor_publication(ledger, campaign, integrity, publisher="ops", assets_created=8)
        assert anchor["event_type"] == MARKETING_PUBLISH_EVENT_TYPE
        assert anchor["reused"] is False and anchor["sequence_no"] == 1
        entry = ledger.transaction_ledger[anchor["entry_id"]]
        assert entry["entity_type"] == "marketing_campaign"
        assert entry["entity_id"] == campaign["campaign_id"]
        assert entry["signature"] == integrity["signature"]
        assert entry["input_hash"] == campaign["input_hash"]
        assert entry["assets_created"] == 8 and entry["published_by"] == "ops"
        assert entry["entry_hash"] == anchor["entry_hash"]

        # Same signed plan published again → the same row, no second anchor.
        again = svc.anchor_publication(ledger, campaign, integrity, publisher="ops", assets_created=8)
        assert again["entry_id"] == anchor["entry_id"] and again["reused"] is True
        assert len(ledger.transaction_ledger) == 1
        assert reconcile_ledger_entries(ledger.transaction_ledger.values())["broken_links"] == []

        verdict = svc.verify_publication(ledger.transaction_ledger, campaign, integrity)
        assert verdict["anchored"] is True
        assert verdict["signature_matches"] and verdict["input_hash_matches"] and verdict["signature_verified"]
        assert verdict["entry_id"] == anchor["entry_id"] and verdict["sequence_no"] == 1

    def test_anchor_refuses_a_plan_whose_signature_does_not_verify(self, svc, ledger):
        out = _generate(svc, _datasets())
        forged = copy.deepcopy(out["campaign"])
        forged["scope"]["objective"] = "reactivation"
        with pytest.raises(ValueError):
            svc.anchor_publication(ledger, forged, out["integrity"], publisher="ops")
        assert ledger.transaction_ledger == {}
        with pytest.raises(ValueError):
            svc.anchor_publication(ledger, {}, out["integrity"], publisher="ops")

    def test_ledger_failure_propagates_so_the_caller_fails_closed(self, svc):
        class Broken:
            transaction_ledger = {}

            def append_event(self, **kwargs):
                raise RuntimeError("db down")

        out = _generate(svc, _datasets())
        with pytest.raises(RuntimeError):
            svc.anchor_publication(Broken(), out["campaign"], out["integrity"], publisher="ops")

    def test_verify_detects_post_publication_edits_and_missing_anchors(self, svc, ledger):
        out = _generate(svc, _datasets())
        campaign, integrity = out["campaign"], out["integrity"]
        missing = svc.verify_publication(ledger.transaction_ledger, campaign, integrity)
        assert missing["anchored"] is False and missing["signature_verified"] is True

        svc.anchor_publication(ledger, campaign, integrity, publisher="ops")
        edited = copy.deepcopy(campaign)
        edited["input_hash"] = "f" * 64  # a plan re-derived from other inputs but keeping the id
        verdict = svc.verify_publication(ledger.transaction_ledger, edited, integrity)
        assert verdict["anchored"] is False
        assert verdict["signature_verified"] is False  # edit broke the HMAC too
        # A different signature for the same campaign id resolves to a different (absent) anchor.
        other = dict(integrity, signature="ab" * 32)
        assert svc.verify_publication(ledger.transaction_ledger, campaign, other)["anchored"] is False

    def test_health_probe_reports_cache_and_event_type(self):
        from services import marketing_sales_agent_service as mod
        saved = mod._marketing_sales_agent_service
        try:
            mod._marketing_sales_agent_service = MarketingSalesAgentService(secret_key="s")
            _generate(mod._marketing_sales_agent_service, _datasets())
            health = mod._marketing_agent_health()
            assert health["publish_event_type"] == MARKETING_PUBLISH_EVENT_TYPE
            assert health["plan_version"] == PLAN_VERSION
            assert health["plan_cache"]["entries"] == 1
        finally:
            mod._marketing_sales_agent_service = saved


# ---------------------------------------------------------------------------
# HTTP round-trip through the embedded portal (root conftest starts it)
# ---------------------------------------------------------------------------

def _http(url, method='GET', token=None, payload=None):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    headers = {}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            data = resp.read().decode('utf-8')
            return resp.status, json.loads(data) if data else {}
    except HTTPError as exc:
        data = exc.read().decode('utf-8')
        return exc.code, json.loads(data) if data else {}


class TestHttpWiring:
    @staticmethod
    def _base():
        return os.environ.get('TEST_BASE_URL') or f"http://127.0.0.1:{os.environ.get('TEST_PORT', '8000')}"

    @pytest.fixture
    def admin_token(self):
        status, payload = _http(f'{self._base()}/api/login', method='POST',
                                payload={'username': 'admin', 'password': 'admin123'})
        assert status == 200, payload
        return payload['token']

    @pytest.fixture
    def portal(self):
        import web_portal.server as portal
        return portal

    def test_generate_publish_and_latest_are_ledger_backed(self, admin_token, portal):
        base = self._base()
        from services import marketing_sales_agent_service as mod
        mod.get_marketing_sales_agent_service().clear_plan_cache()
        portal.CUSTOMERS.update(_datasets()["customers"])
        portal.HEALTH_WALLETS.update(_datasets()["health_wallets"])

        q = 'vertical=insurance&objective=growth&persona=families&region=global&budget_tier=balanced&networks=linkedin,x&cohorts=1'
        status, first = _http(f'{base}/api/admin/marketing-sales-agent?{q}', token=admin_token)
        assert status == 200, first
        campaign = first['generated']['campaign']
        assert first['cohort_targeting'] is True
        assert campaign['targeting']['mode'] == 'bi_cohorts'
        assert first['plan_cache']['hit'] is False
        campaign_id = campaign['campaign_id']

        # Same inputs again: plan cache hit, same campaign id, envelope not reset.
        status, second = _http(f'{base}/api/admin/marketing-sales-agent?{q}', token=admin_token)
        assert status == 200 and second['plan_cache']['hit'] is True
        assert second['generated']['campaign']['campaign_id'] == campaign_id
        assert second['generated']['integrity']['signature'] == first['generated']['integrity']['signature']

        # Publish anchors on the platform ledger.
        ledger_before = len(portal.TRANSACTION_LEDGER)
        status, published = _http(f'{base}/api/admin/marketing-sales-agent/publish', method='POST',
                                  token=admin_token, payload={'campaign_id': campaign_id})
        assert status == 201, published
        anchor = published['ledger_anchor']
        assert anchor['event_type'] == MARKETING_PUBLISH_EVENT_TYPE and anchor['reused'] is False
        assert len(portal.TRANSACTION_LEDGER) == ledger_before + 1
        entry = portal.TRANSACTION_LEDGER[anchor['entry_id']]
        assert entry['entity_id'] == campaign_id
        assert entry['signature'] == first['generated']['integrity']['signature']
        assert entry['input_hash'] == campaign['input_hash']
        assert published['latest_campaign']['integrity']['ledger_anchor']['entry_id'] == anchor['entry_id']
        assert published['latest_campaign']['lifecycle_status'] == 'published'

        # /latest verifies against the ledger.
        status, latest = _http(f'{base}/api/admin/marketing-sales-agent/latest?campaign_id={campaign_id}',
                               token=admin_token)
        assert status == 200, latest
        verdict = latest['latest_campaign']['integrity']['ledger_anchor']
        assert verdict['anchored'] is True and verdict['entry_id'] == anchor['entry_id']

        # Re-publishing the identical signed plan reuses the anchor; the ledger does not grow.
        status, republished = _http(f'{base}/api/admin/marketing-sales-agent/publish', method='POST',
                                    token=admin_token, payload={'campaign_id': campaign_id})
        assert status == 201 and republished['ledger_anchor']['reused'] is True
        assert len(portal.TRANSACTION_LEDGER) == ledger_before + 1

        # Regenerating after a cache hit must not downgrade a published envelope.
        status, third = _http(f'{base}/api/admin/marketing-sales-agent?{q}', token=admin_token)
        assert status == 200 and third['plan_cache']['hit'] is True
        assert third['latest_campaign']['lifecycle_status'] == 'published'
        assert third['latest_campaign']['integrity']['ledger_anchor']['entry_id'] == anchor['entry_id']

    def test_publish_of_a_tampered_stored_plan_is_refused_with_no_side_effects(self, admin_token, portal):
        base = self._base()
        q = 'vertical=investments&objective=cross_sell&persona=founders&networks=youtube'
        status, generated = _http(f'{base}/api/admin/marketing-sales-agent?{q}', token=admin_token)
        assert status == 200, generated
        campaign_id = generated['generated']['campaign']['campaign_id']

        store = portal.marketing_state_dict()['campaign_store']
        store[campaign_id]['campaign']['scope']['objective'] = 'growth'  # post-signature edit
        assets_before = len(portal.MEDIA_ASSETS)
        ledger_before = len(portal.TRANSACTION_LEDGER)

        status, refused = _http(f'{base}/api/admin/marketing-sales-agent/publish', method='POST',
                                token=admin_token, payload={'campaign_id': campaign_id})
        assert status == 409 and 'error' in refused
        assert len(portal.MEDIA_ASSETS) == assets_before
        assert len(portal.TRANSACTION_LEDGER) == ledger_before
        assert store[campaign_id]['lifecycle_status'] == 'generated'
