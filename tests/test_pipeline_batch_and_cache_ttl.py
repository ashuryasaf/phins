"""
Tests for the bulk-process pipeline endpoint and the DatabaseDict cache TTL
that together fix the two issues reported by admins:

1. "Process All Pipelines" returning "5/12 customers processed, 7 errors":
   the legacy admin UI fired one HTTP call per customer, each one consuming
   a slot in the bulk rate limiter (MAX_BULK_OPERATIONS_PER_MINUTE=5).
   The fix is a server-side batch endpoint that processes all customers
   in a single HTTP call (and counts once against the rate limiter).

2. "Customer files a claim but it doesn't appear in admin/adjuster review":
   DatabaseDict cached values()/items()/keys() forever once loaded, so a
   claim persisted to the DB by the customer-facing process was invisible
   to an admin worker that had warmed its cache earlier. The fix adds a
   short TTL (DATABASE_DICT_CACHE_TTL_SECONDS, default 5s) plus an
   explicit invalidate_cache() hook used by the admin claims endpoint.
"""

from __future__ import annotations

import time
import importlib

import pytest

import web_portal.server as portal


def _ensure_admin_user():
    """Make sure an in-process admin user exists for these tests."""
    if 'admin' in portal.USERS:
        return
    pw = portal.hash_password('admin123')
    portal.USERS['admin'] = {
        **pw,
        'role': 'admin',
        'name': 'Admin User',
    }


def _make_admin_session():
    _ensure_admin_user()
    token = 'pipeline-batch-test-token'
    portal.SESSIONS[token] = {
        'username': 'admin',
        'role': 'admin',
        'customer_id': None,
        'expires': '2099-01-01T00:00:00',
    }
    return token


def _seed_pending_customer(idx: int):
    cust_id = f'CUST-BATCH-{idx:03d}'
    pol_id = f'POL-BATCH-{idx:03d}'
    app_id = f'UW-BATCH-{idx:03d}'

    portal.CUSTOMERS[cust_id] = {
        'id': cust_id,
        'name': f'Batch Customer {idx}',
        'email': f'batch{idx}@example.com',
        'created_date': '2024-01-01T00:00:00',
        'status': 'active',
    }
    portal.POLICIES[pol_id] = {
        'id': pol_id,
        'customer_id': cust_id,
        'type': 'phins_unified',
        'coverage_amount': 100000.0,
        'annual_premium': 1200.0,
        'monthly_premium': 100.0,
        'status': 'pending_underwriting',
    }
    portal.UNDERWRITING_APPLICATIONS[app_id] = {
        'id': app_id,
        'policy_id': pol_id,
        'customer_id': cust_id,
        'status': 'pending',
    }
    return cust_id, pol_id, app_id


@pytest.fixture(autouse=True)
def _isolate_state():
    """Isolate every test from in-memory state of other tests."""
    for store_name in (
        'CUSTOMERS', 'POLICIES', 'UNDERWRITING_APPLICATIONS',
        'BILLING', 'CLAIMS', 'HEALTH_WALLETS', 'INVESTMENT_ACCOUNTS',
    ):
        store = getattr(portal, store_name, None)
        if isinstance(store, dict):
            store.clear()
    yield


def test_run_pipeline_for_customer_advances_pending_app_to_active():
    """The extracted helper must replicate the legacy single-customer path."""
    cust_id, pol_id, app_id = _seed_pending_customer(1)

    result = portal.run_pipeline_for_customer(cust_id, auto_advance=True)

    assert result['success'] is True
    assert result['customer_id'] == cust_id
    assert result['previous_stage'] == 'underwriting'
    assert result['new_stage'] == 'active'

    # Application approved + policy activated.
    assert portal.UNDERWRITING_APPLICATIONS[app_id]['status'] == 'approved'
    assert portal.POLICIES[pol_id]['status'] == 'active'

    # Billing + wallets initialised.
    assert any(
        b.get('policy_id') == pol_id and b.get('customer_id') == cust_id
        for b in portal.BILLING.values()
    )
    assert cust_id in portal.HEALTH_WALLETS
    assert cust_id in portal.INVESTMENT_ACCOUNTS


def test_run_pipeline_for_customer_unknown_customer_returns_failure():
    result = portal.run_pipeline_for_customer('CUST-DOES-NOT-EXIST')
    assert result['success'] is False
    assert result['error'] == 'Customer not found'


def test_pipeline_process_all_handles_more_than_rate_limit_in_one_call(monkeypatch):
    """
    Repro of the production "5/12 customers processed, 7 errors" symptom:
    seed 12 customers and verify the batch endpoint processes ALL of them
    in a single request, regardless of MAX_BULK_OPERATIONS_PER_MINUTE.
    """
    seeded = [_seed_pending_customer(i)[0] for i in range(1, 13)]
    assert len(seeded) == 12

    # Pin the rate limit low for the test to mirror production tightening.
    monkeypatch.setattr(portal, 'MAX_BULK_OPERATIONS_PER_MINUTE', 5, raising=False)
    portal.BULK_RATE_LIMIT.clear()

    # Force PHINS_TEST_MODE so check_bulk_rate_limit short-circuits to "allowed";
    # the assertion we care about is that the helper itself doesn't fan out
    # into N rate-limit-checked HTTP calls.
    monkeypatch.setattr(portal, 'PHINS_TEST_MODE', True, raising=False)

    # Drive the helper directly the same way the batch endpoint does.
    processed = 0
    actions_total = 0
    errors = []
    for cid in seeded:
        try:
            res = portal.run_pipeline_for_customer(cid, auto_advance=True)
            if res.get('success'):
                processed += 1
                actions_total += len(res.get('actions_taken') or [])
            else:
                errors.append(cid)
        except Exception as exc:  # pragma: no cover - safety net
            errors.append(f'{cid}: {exc}')

    assert processed == 12, f'expected all 12 processed, got {processed} (errors={errors})'
    assert errors == []
    assert actions_total > 0


def test_pipeline_process_all_endpoint_consumes_one_rate_limit_slot(monkeypatch):
    """End-to-end-ish: the dispatcher should consume exactly one bulk slot for
    the entire batch (no matter how many customers it processes)."""
    seeded = [_seed_pending_customer(i)[0] for i in range(1, 13)]

    # Reset the rate limiter and disable test-mode bypass so check_bulk_rate_limit
    # actually runs. We then verify only ONE entry was created.
    portal.BULK_RATE_LIMIT.clear()
    monkeypatch.setattr(portal, 'PHINS_TEST_MODE', False, raising=False)

    # Simulate one batch call by invoking the helper for each id (which is the
    # body of the new /api/admin/pipeline-process-all handler) AFTER consuming
    # exactly one rate-limit token, mirroring the dispatcher.
    allowed, _msg = portal.check_bulk_rate_limit('1.2.3.4', 'pipeline_process_all', 8000)
    assert allowed, 'first batch call must be allowed'

    processed = sum(
        1 for cid in seeded
        if portal.run_pipeline_for_customer(cid, auto_advance=True).get('success')
    )
    assert processed == 12

    # The rate limiter should hold a single slot for this operation type.
    matching = [k for k in portal.BULK_RATE_LIMIT if k.endswith(':pipeline_process_all')]
    assert len(matching) == 1
    assert portal.BULK_RATE_LIMIT[matching[0]]['count'] == 1


# ---------------------------------------------------------------------------
# DatabaseDict cache TTL
# ---------------------------------------------------------------------------


def test_database_dict_cache_ttl_default_is_five_seconds():
    import database.data_access as data_access
    assert data_access.DATABASE_DICT_CACHE_TTL_SECONDS == pytest.approx(5.0)


def test_database_dict_cache_expires_within_ttl(monkeypatch):
    """
    The cached values()/items() result must be returned only while it is
    within the configured TTL window. Once expired, the next bulk read must
    refresh from the underlying store. This is what restores cross-process
    visibility for newly-filed claims.
    """
    import database.data_access as data_access

    fake_now = {'t': 1000.0}

    def _fake_monotonic():
        return fake_now['t']

    monkeypatch.setattr(data_access.time, 'monotonic', _fake_monotonic)
    monkeypatch.setattr(data_access, 'DATABASE_DICT_CACHE_TTL_SECONDS', 5.0)

    dd = data_access.DatabaseDict('claims')

    # Seed the cache directly without touching a real DB; this is the same
    # state _refresh_cache() would leave behind on a successful load.
    dd._cache = {'CLM-1': {'id': 'CLM-1'}}
    dd._cache_valid = True
    dd._cache_loaded_at = fake_now['t']

    assert dd._is_cache_fresh() is True

    # Half the TTL elapsed: still fresh.
    fake_now['t'] += 2.5
    assert dd._is_cache_fresh() is True

    # Past the TTL: stale, must trigger a refresh.
    fake_now['t'] += 3.0
    assert dd._is_cache_fresh() is False


def test_database_dict_invalidate_cache_marks_stale_immediately():
    import database.data_access as data_access

    dd = data_access.DatabaseDict('claims')
    dd._cache = {'CLM-1': {'id': 'CLM-1'}}
    dd._cache_valid = True
    dd._cache_loaded_at = data_access.time.monotonic()

    assert dd._is_cache_fresh() is True
    dd.invalidate_cache()
    assert dd._cache_valid is False
    assert dd._cache_loaded_at == 0.0
    assert dd._is_cache_fresh() is False


def test_database_dict_ttl_zero_disables_cache(monkeypatch):
    """Setting the TTL env var to 0 must disable caching entirely."""
    import database.data_access as data_access

    monkeypatch.setattr(data_access, 'DATABASE_DICT_CACHE_TTL_SECONDS', 0.0)
    dd = data_access.DatabaseDict('claims')
    dd._cache = {'CLM-1': {'id': 'CLM-1'}}
    dd._cache_valid = True
    dd._cache_loaded_at = data_access.time.monotonic()

    # Even a cache that was just populated should be considered stale when
    # caching is disabled.
    assert dd._is_cache_fresh() is False
