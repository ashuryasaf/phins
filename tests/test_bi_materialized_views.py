"""
B10 — BI Analytics: write-path invalidation, materialized views, scheduled
forecast.

Data-integrity contract under test:

* A cached dashboard can never contradict the stores. The fingerprint check
  stays on every read; ``data_version`` (write hooks) is additive and only
  drives re-materialization. A ``DatabaseDict`` publishes a
  ``content_version`` that bumps on every local write *and* on every refresh
  that loaded different rows, so its digest memo is exact; plain dicts are
  always re-hashed.
* A materialized view is adopted only when its fingerprint equals the live
  inputs, its checksum verifies, and it is younger than the cache TTL.
* ``materialize_views`` is an upsert: one record per view, idempotent.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from services import bi_analytics_service as bi_mod
from services.bi_analytics_service import BIAnalyticsService, VIEW_SCHEMA_VERSION
from web_portal import api_bi_analytics as bi_api
import web_portal.server as portal


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _stores():
    return {
        'customers': {'C1': {'status': 'active'}, 'C2': {'status': 'active'}},
        'policies': {
            'P1': {'status': 'active', 'monthly_premium': 100, 'annual_premium': 1200,
                   'coverage_amount': 100000, 'customer_id': 'C1'},
        },
        'claims': {'CL1': {'status': 'approved', 'approved_amount': 500}},
        'billing': {'B1': {'status': 'paid', 'amount': 1200}},
        'balance_sheet': {'total_assets': 100000, 'total_liabilities': 20000, 'claims_reserve': 5000},
        'suppliers': {},
        'supplier_orders': {},
        'health_wallets': {},
        'investment_accounts': {},
        'transaction_ledger': {},
        'deliveries': {},
    }


@pytest.fixture
def views_dir(tmp_path):
    return tmp_path / 'bi'


@pytest.fixture
def svc(views_dir):
    return BIAnalyticsService(cache_ttl_seconds=300, materialized_path=str(views_dir / 'materialized_views.json'))


@pytest.fixture
def singleton(svc, monkeypatch):
    """Install ``svc`` as the module singleton the routes and hooks resolve."""
    monkeypatch.setattr(bi_mod, '_bi_analytics_service', svc)
    return svc


def _dashboard(service, ds):
    return service.get_executive_dashboard(
        customers=ds['customers'], policies=ds['policies'], claims=ds['claims'],
        billing=ds['billing'], balance_sheet=ds['balance_sheet'],
        suppliers=ds['suppliers'], deliveries=ds['deliveries'])


# ---------------------------------------------------------------------------
# write-path invalidation
# ---------------------------------------------------------------------------

class TestWritePathInvalidation:
    def test_notify_bumps_version_records_store_and_keeps_valid_cache(self, svc):
        ds = _stores()
        first = _dashboard(svc, ds)
        assert svc.data_version == 0
        assert svc.notify_data_change('policies') == 1
        assert svc.notify_data_change('claims') == 2
        assert svc.describe()['changed_stores'] == {'policies': 1, 'claims': 1}
        assert svc.last_data_change_at is not None
        # The write did not change any BI input: the fingerprint still matches,
        # so the cached object is reused rather than recomputed.
        assert _dashboard(svc, ds) is first
        assert svc.last_served_from() == 'cache'

    def test_callbacks_run_and_a_failing_callback_never_breaks_the_write(self, svc):
        seen = []

        def boom(store):
            raise RuntimeError('hook exploded')

        svc.on_data_change(boom)
        svc.on_data_change(seen.append)
        svc.on_data_change(seen.append)  # duplicate registration is ignored
        assert svc.notify_data_change('billing') == 1
        assert seen == ['billing']
        svc.remove_data_change_callback(seen.append)
        svc.notify_data_change('billing')
        assert seen == ['billing']

    def test_in_memory_write_changes_the_dashboard_on_the_next_read(self, svc):
        ds = _stores()
        first = _dashboard(svc, ds)
        assert first['summary']['active_policies'] == 1
        ds['policies']['P2'] = {'status': 'active', 'monthly_premium': 50, 'annual_premium': 600,
                                'coverage_amount': 500, 'customer_id': 'C2'}
        second = _dashboard(svc, ds)
        assert svc.last_served_from() == 'live'
        assert second is not first and second['summary']['active_policies'] == 2
        # In-place edit of an existing row (no notify at all) is still caught.
        ds['policies']['P2']['status'] = 'cancelled'
        assert _dashboard(svc, ds)['summary']['active_policies'] == 1

    def test_mark_ledger_dirty_is_the_in_memory_write_hook(self, singleton):
        before = singleton.data_version
        portal.mark_ledger_dirty()
        assert singleton.data_version == before + 1
        assert singleton.describe()['changed_stores'].get('ledger') == 1

    def test_module_hook_is_a_noop_without_a_singleton(self, monkeypatch):
        monkeypatch.setattr(bi_mod, '_bi_analytics_service', None)
        assert bi_mod.notify_bi_data_change('policies') is None
        bi_mod._on_store_write('policies', 'set')  # must not raise


class TestVersionedStores:
    """``content_version()`` on DatabaseDict and the digest memo it enables."""

    @pytest.fixture
    def db_customers(self, monkeypatch):
        from database import init_database
        from database.data_access import DatabaseDict
        init_database()
        return DatabaseDict('customers')

    def test_content_version_bumps_on_writes_and_on_changed_refresh_only(self, db_customers, monkeypatch):
        from database import data_access
        store = db_customers
        v0 = store.content_version()
        store['CUST-B10-1'] = {'id': 'CUST-B10-1', 'name': 'Ada', 'email': 'ada-b10@example.test'}
        v1 = store.content_version()
        assert v1 > v0
        # Refresh with unchanged rows: no bump.
        monkeypatch.setattr(data_access, 'DATABASE_DICT_CACHE_TTL_SECONDS', 0.0)
        assert store.content_version() == v1
        assert store.content_version() == v1
        # Another "process" writes the same table through its own DatabaseDict:
        # the refresh sees different rows and bumps.
        peer = data_access.DatabaseDict('customers')
        peer['CUST-B10-2'] = {'id': 'CUST-B10-2', 'name': 'Grace', 'email': 'grace-b10@example.test'}
        v2 = store.content_version()
        assert v2 > v1
        del store['CUST-B10-2']
        assert store.content_version() > v2

    def test_write_listener_notifies_the_bi_singleton_for_bi_inputs_only(self, db_customers, singleton):
        from database import data_access
        before = singleton.data_version
        db_customers['CUST-B10-L'] = {'id': 'CUST-B10-L', 'name': 'Lin', 'email': 'lin-b10@example.test'}
        assert singleton.data_version == before + 1
        assert singleton.describe()['changed_stores'].get('customers') == 1
        sessions = data_access.DatabaseDict('sessions')
        # Non-BI repositories are filtered out before the singleton is touched.
        bi_mod._on_store_write(sessions.repository_name, 'set')
        assert singleton.data_version == before + 1

    def test_versioned_store_digest_is_memoised_until_the_version_moves(self, db_customers, svc, monkeypatch):
        from database import data_access
        store = db_customers
        store['CUST-B10-M'] = {'id': 'CUST-B10-M', 'name': 'Mem', 'email': 'mem-b10@example.test'}
        calls = []
        real = BIAnalyticsService._digest_store

        def counting(rows):
            calls.append(len(rows))
            return real(rows)

        monkeypatch.setattr(BIAnalyticsService, '_digest_store', staticmethod(counting))
        d1 = svc._fingerprint(store)
        d2 = svc._fingerprint(store)
        assert d1 == d2 and len(calls) == 1  # second call served from the memo
        store['CUST-B10-N'] = {'id': 'CUST-B10-N', 'name': 'New', 'email': 'new-b10@example.test'}
        d3 = svc._fingerprint(store)
        assert d3 != d1 and len(calls) == 2
        # A plain dict is never memoised: an in-place edit has no version to trust.
        plain = {'X': {'a': 1}}
        svc._fingerprint(plain)
        plain['X']['a'] = 2
        svc._fingerprint(plain)
        assert len(calls) == 4
        monkeypatch.setattr(data_access, 'DATABASE_DICT_CACHE_TTL_SECONDS', 0.0)
        # Expired TTL forces a refresh; unchanged rows keep the memo.
        assert svc._fingerprint(store) == d3 and len(calls) == 4


# ---------------------------------------------------------------------------
# routes serve with computed_at / served_from
# ---------------------------------------------------------------------------

class TestRouteFreshness:
    def test_dashboard_route_reports_computed_at_and_cache_state(self, singleton):
        ds = _stores()
        status, first = bi_api.handle_executive_dashboard(None, ds)
        assert status == 200
        assert first['served_from'] == 'live' and first['computed_at']
        assert first['cache_ttl_seconds'] == 300 and first['data_version'] == 0
        datetime.fromisoformat(first['computed_at'])  # valid ISO timestamp
        status, second = bi_api.handle_executive_dashboard(None, ds)
        assert second['served_from'] == 'cache'
        assert second['computed_at'] == first['computed_at']
        assert second['age_seconds'] >= 0
        # The route copies; the cached object never grows route-only keys.
        cached = singleton.cache['executive_dashboard']['value']
        assert 'served_from' not in cached and 'age_seconds' not in cached

    @pytest.mark.parametrize('handler,key', [
        (lambda ds: bi_api.handle_customer_analytics(None, ds), 'customer_analytics'),
        (lambda ds: bi_api.handle_supplier_analytics(None, ds), 'supplier_analytics'),
        (lambda ds: bi_api.handle_ai_insights(None, ds), 'executive_dashboard'),
        (lambda ds: bi_api.handle_loss_ratio_by_smoking(None, ds, {}), 'loss_ratio_by_smoking_status'),
        (lambda ds: bi_api.handle_revenue_forecast(None, ds['policies'], {}), 'revenue_forecast'),
        (lambda ds: bi_api.handle_revenue_forecast(None, ds['policies'], {'months_ahead': '6'}),
         'revenue_forecast:custom'),
    ])
    def test_every_cached_view_route_carries_freshness(self, singleton, handler, key):
        ds = _stores()
        status, payload = handler(ds)
        assert status == 200, payload
        assert payload['computed_at'] and payload['served_from'] == 'live'
        assert singleton.cache_entry(key) is not None
        status, again = handler(ds)
        assert again['served_from'] == 'cache' and again['computed_at'] == payload['computed_at']

    def test_forecast_default_and_custom_keys_do_not_evict_each_other(self, singleton):
        policies = _stores()['policies']
        _, default = bi_api.handle_revenue_forecast(None, policies, {})
        _, custom = bi_api.handle_revenue_forecast(None, policies, {'growth_rate': '0.02', 'months_ahead': '3'})
        assert custom['forecast_months'] == 3 and default['forecast_months'] == 12
        _, default_again = bi_api.handle_revenue_forecast(None, policies, {})
        assert default_again['served_from'] == 'cache'
        assert default_again['computed_at'] == default['computed_at']

    def test_forecast_fingerprint_includes_the_live_lapse_rate(self, svc, monkeypatch):
        policies = _stores()['policies']
        first = svc.predict_revenue_forecast(policies, historical_growth_rate=None)
        assert svc.predict_revenue_forecast(policies, historical_growth_rate=None) is first
        monkeypatch.setattr(bi_mod, '_lapse_rate_year1_from_store', lambda: (0.25, 'promoted_table'))
        second = svc.predict_revenue_forecast(policies, historical_growth_rate=None)
        assert second is not first
        assert second['forecast_basis']['lapse_rate_year1'] == 0.25

    def test_explicit_now_bypasses_the_cache(self, svc):
        policies = _stores()['policies']
        fixed = datetime(2026, 3, 1, tzinfo=timezone.utc)
        a = svc.predict_revenue_forecast(policies, historical_growth_rate=None, now=fixed)
        b = svc.predict_revenue_forecast(policies, historical_growth_rate=None, now=fixed)
        assert a is not b and 'computed_at' not in a
        assert svc.cache_entry('revenue_forecast') is None


# ---------------------------------------------------------------------------
# materialized views
# ---------------------------------------------------------------------------

class TestMaterializedViews:
    def test_materialize_is_an_idempotent_upsert_with_one_record_per_view(self, svc, views_dir):
        ds = _stores()
        first = svc.materialize_views(ds, source='test')
        assert first['success'] and first['persisted']
        assert set(first['views']) == {'executive_dashboard', 'revenue_forecast', 'customer_analytics'}
        assert all(v['changed'] for v in first['views'].values())
        second = svc.materialize_views(ds, source='test')
        assert second['success']
        assert not any(v['changed'] for v in second['views'].values())
        on_disk = json.loads((views_dir / 'materialized_views.json').read_text())
        assert on_disk['schema'] == VIEW_SCHEMA_VERSION
        assert set(on_disk['views']) == set(first['views'])
        for name, record in on_disk['views'].items():
            assert record['view'] == name and record['source'] == 'test'
            assert bi_mod._record_sha256(record) == record['record_sha256']
        # A data change flips exactly the views it feeds.
        ds['policies']['P2'] = {'status': 'active', 'monthly_premium': 10, 'annual_premium': 120,
                                'coverage_amount': 1, 'customer_id': 'C2'}
        third = svc.materialize_views(ds, source='test')
        assert third['views']['executive_dashboard']['changed'] is True
        assert third['views']['revenue_forecast']['changed'] is True

    def test_fresh_process_adopts_a_matching_view_with_its_computed_at(self, svc, views_dir):
        ds = _stores()
        svc.materialize_views(ds, source='cron')
        computed_at = svc.materialize_views(ds, source='cron')['views']['executive_dashboard']['computed_at']
        web = BIAnalyticsService(cache_ttl_seconds=300, materialized_path=str(views_dir / 'materialized_views.json'))
        served = _dashboard(web, ds)
        assert web.last_served_from() == 'materialized'
        assert served['computed_at'] == computed_at
        assert served['summary']['active_policies'] == 1
        assert web.cache_entry('executive_dashboard')['data_version'] == svc.data_version
        # The adopted value is a private copy: mutating it never reaches disk.
        served['summary']['active_policies'] = 999
        again = BIAnalyticsService(cache_ttl_seconds=300, materialized_path=str(views_dir / 'materialized_views.json'))
        assert _dashboard(again, ds)['summary']['active_policies'] == 1

    def test_stale_mismatched_or_tampered_views_are_never_adopted(self, svc, views_dir):
        ds = _stores()
        svc.materialize_views(ds, source='cron')
        path = views_dir / 'materialized_views.json'

        def fresh():
            return BIAnalyticsService(cache_ttl_seconds=300, materialized_path=str(path))

        # 1. inputs changed since the job ran -> fingerprint mismatch -> live
        changed = dict(ds, policies=dict(ds['policies'], P9={'status': 'active', 'monthly_premium': 1}))
        web = fresh()
        assert _dashboard(web, changed)['summary']['active_policies'] == 2
        assert web.last_served_from() == 'live'

        # 2. older than the TTL -> live
        payload = json.loads(path.read_text())
        record = payload['views']['executive_dashboard']
        record['computed_at'] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        record['record_sha256'] = bi_mod._record_sha256(record)
        path.write_text(json.dumps(payload))
        web = fresh()
        _dashboard(web, ds)
        assert web.last_served_from() == 'live'

        # 3. tampered value (checksum fails) -> ignored, live
        svc.materialize_views(ds, source='cron')
        payload = json.loads(path.read_text())
        payload['views']['executive_dashboard']['value']['summary']['active_policies'] = 42
        path.write_text(json.dumps(payload))
        web = fresh()
        assert _dashboard(web, ds)['summary']['active_policies'] == 1
        assert web.last_served_from() == 'live'
        assert 'executive_dashboard' not in web.materialized_views()

        # 4. written by a different dashboard schema -> fingerprint differs -> live
        svc.materialize_views(ds, source='cron')
        web = fresh()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(bi_mod, 'VIEW_SCHEMA_VERSION', VIEW_SCHEMA_VERSION + 1)
            _dashboard(web, ds)
            assert web.last_served_from() == 'live'

    def test_running_process_picks_up_a_file_rewritten_by_the_scheduler(self, svc, views_dir):
        ds = _stores()
        path = views_dir / 'materialized_views.json'
        web = BIAnalyticsService(cache_ttl_seconds=300, materialized_path=str(path))
        _dashboard(web, ds)
        assert web.last_served_from() == 'live'
        web.invalidate_cache()
        svc.materialize_views(ds, source='cron')
        os.utime(path, (time.time() + 1, time.time() + 1))  # guarantee an mtime change
        _dashboard(web, ds)
        assert web.last_served_from() == 'materialized'

    def test_persistence_failure_is_reported_not_raised(self, tmp_path):
        blocked = tmp_path / 'not-a-dir'
        blocked.write_text('x')
        svc = BIAnalyticsService(cache_ttl_seconds=300, materialized_path=str(blocked / 'materialized_views.json'))
        result = svc.materialize_views(_stores(), source='test')
        assert result['persisted'] is False and result['success'] is False and result['error']
        # The dashboards were still computed and cached for this process.
        assert svc.cache_entry('executive_dashboard') is not None

    def test_health_probe_describes_cache_and_materialized_views(self, singleton):
        ds = _stores()
        singleton.materialize_views(ds, source='test')
        health = bi_mod._bi_analytics_health()
        assert health['initialized'] is True
        assert set(health['materialized_views']) == {'executive_dashboard', 'revenue_forecast', 'customer_analytics'}
        assert health['cached_views']['executive_dashboard']['computed_at']
        assert health['data_version'] == singleton.data_version


# ---------------------------------------------------------------------------
# scheduled job (cron script) and queue job
# ---------------------------------------------------------------------------

class TestScheduledMaterialization:
    def test_materialize_route_requires_admin_and_writes_views(self, singleton, monkeypatch):
        ds = portal.bi_data_sources()
        ds['_materialize_source'] = 'api'
        status, payload = bi_api.handle_bi_materialize(None, ds)
        assert status == 200 and payload['persisted']
        assert set(payload['views']) == {'executive_dashboard', 'revenue_forecast', 'customer_analytics'}
        # The web route then serves the just-materialized dashboard from cache.
        status, dash = bi_api.handle_executive_dashboard(None, portal.bi_data_sources())
        assert dash['served_from'] == 'cache'
        assert dash['computed_at'] == payload['views']['executive_dashboard']['computed_at']

    def test_cron_script_materializes_and_snapshots_idempotently(self, singleton, monkeypatch, capsys, tmp_path):
        from services.bi_snapshot_service import BISnapshotService
        from services import bi_snapshot_service as snap_mod
        from scripts import run_bi_snapshot
        snap = BISnapshotService(snapshot_dir=str(tmp_path / 'snap'))
        monkeypatch.setattr(snap_mod, '_service', snap)

        assert run_bi_snapshot.main([]) == 0
        first = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert first['success'] and first['snapshot']['snapshot_id'].startswith('BISNAP-')
        assert first['materialized']['persisted'] is True
        assert all(v['changed'] for v in first['materialized']['views'].values())

        assert run_bi_snapshot.main(['--materialize-only']) == 0
        second = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert 'snapshot' not in second
        assert not any(v['changed'] for v in second['materialized']['views'].values())
        assert snap.list_snapshots()['total'] == 1  # snapshots only grow when asked
        assert set(singleton.materialized_views()) == {'executive_dashboard', 'revenue_forecast', 'customer_analytics'}

        assert run_bi_snapshot.main(['--snapshot-only']) == 0
        third = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert 'materialized' not in third and snap.list_snapshots()['total'] == 2

    def test_write_hook_enqueues_one_debounced_job_that_materializes(self, singleton, monkeypatch):
        from services.agent_job_queue import AgentJobQueue
        monkeypatch.setenv('PHINS_AGENT_ASYNC', '1')
        monkeypatch.setenv('PHINS_BI_REMATERIALIZE_DELAY_SECONDS', '30')
        queue = AgentJobQueue(poll_interval=0.01)
        monkeypatch.setattr(portal, 'get_agent_job_queue', lambda: queue)
        portal._BI_MATERIALIZE_PENDING.clear()
        portal._BI_HOOKS_BOUND.clear()
        try:
            portal.bind_bi_write_hooks()
            portal.bind_bi_write_hooks()  # idempotent
            portal.mark_ledger_dirty()
            portal.mark_ledger_dirty()
            portal.mark_ledger_dirty()
            rows = queue.list_jobs(job_type=portal.BI_MATERIALIZE_JOB_TYPE)
            assert len(rows) == 1 and rows[0]['status'] == 'pending'
            assert rows[0]['input_params'] == {'source': 'write_hook', 'store': 'ledger'}
            assert queue.process_once()['claimed'] == 0  # parked by the debounce delay
            queue._update_job(rows[0]['id'], {'next_retry_at': datetime.utcnow() - timedelta(seconds=1)})
            assert queue.process_once()['completed'] == 1
            done = queue.get_job(rows[0]['id'])
            assert done['status'] == 'completed'
            assert done['result']['persisted'] is True
            assert set(done['result']['views']) == {'executive_dashboard', 'revenue_forecast', 'customer_analytics'}
            assert not portal._BI_MATERIALIZE_PENDING.is_set()
            # A write after the job ran schedules a fresh one.
            portal.mark_ledger_dirty()
            assert len(queue.list_jobs(job_type=portal.BI_MATERIALIZE_JOB_TYPE)) == 2
        finally:
            singleton.remove_data_change_callback(portal.schedule_bi_materialize)
            portal._BI_HOOKS_BOUND.clear()
            portal._BI_MATERIALIZE_PENDING.clear()

    def test_write_hook_is_a_noop_without_the_agent_queue(self, singleton, monkeypatch):
        monkeypatch.delenv('PHINS_AGENT_ASYNC', raising=False)
        portal._BI_MATERIALIZE_PENDING.clear()
        assert portal.schedule_bi_materialize('policies') is None
        assert not portal._BI_MATERIALIZE_PENDING.is_set()

    def test_materialize_handler_is_bound_on_the_shared_queue(self, monkeypatch):
        from services.agent_job_queue import reset_job_queue
        reset_job_queue()
        try:
            queue = portal.get_agent_job_queue()
            assert portal.BI_MATERIALIZE_JOB_TYPE in queue.handlers()
        finally:
            reset_job_queue()


# ---------------------------------------------------------------------------
# HTTP wiring on the embedded server (root conftest)
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

    def test_get_routes_carry_freshness_and_post_materialize_is_admin_only(self, singleton, admin_token):
        base = self._base()
        status, payload = _http(f'{base}/api/bi/materialize', method='POST')
        assert status == 403 and 'error' in payload
        status, payload = _http(f'{base}/api/bi/materialize', method='POST', token=admin_token, payload={})
        assert status == 200, payload
        assert payload['persisted'] and set(payload['views']) >= {'executive_dashboard', 'revenue_forecast'}
        computed_at = payload['views']['executive_dashboard']['computed_at']

        status, dash = _http(f'{base}/api/bi/executive-dashboard', token=admin_token)
        assert status == 200
        assert dash['computed_at'] == computed_at and dash['served_from'] == 'cache'
        status, forecast = _http(f'{base}/api/bi/revenue-forecast', token=admin_token)
        assert status == 200
        assert forecast['computed_at'] == payload['views']['revenue_forecast']['computed_at']
        assert forecast['served_from'] == 'cache'
