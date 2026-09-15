#!/usr/bin/env python3
"""B11 — Delivery Bidding AI: geohash index, reliability from settled orders,
SLA clock (bidding-window expiry) with outbox events, the recurring queue job,
and the role-scoped ``/api/delivery/*`` HTTP layer.

Service tests run on isolated ``DeliveryBiddingService`` instances; the
settlement accessor is proven on a throwaway SQLite database; the HTTP tests
go through the embedded portal started by the root ``conftest.py``.
"""

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import delivery_bidding_service as dbs  # noqa: E402
from services.delivery_bidding_service import (  # noqa: E402
    BIDDING_WINDOW_CLOSED_EVENT,
    DEFAULT_SUPPLIER_SERVICE_RADIUS_KM,
    MIN_SETTLED_ORDERS_FOR_BLEND,
    SETTLED_RELIABILITY_WEIGHT,
    BidStatus,
    DeliveryBiddingService,
    DeliveryRequest,
    DeliveryStatus,
    geohash_decode_bbox,
    geohash_encode,
    geohash_neighbors,
    geohash_precision_for_radius,
    haversine_km,
)

NYC = {'latitude': 40.7128, 'longitude': -74.0060, 'address': '1 Main St',
       'city': 'New York', 'state': 'NY'}
BROOKLYN = {'latitude': 40.6782, 'longitude': -73.9442, 'address': '2 Flatbush Ave',
            'city': 'Brooklyn', 'state': 'NY'}
NEWARK = {'latitude': 40.7357, 'longitude': -74.1724, 'address': '3 Broad St',
          'city': 'Newark', 'state': 'NJ'}
LOS_ANGELES = {'latitude': 34.0522, 'longitude': -118.2437, 'address': '4 Sunset Blvd',
               'city': 'Los Angeles', 'state': 'CA'}
PACKAGE = {'description': 'Insulin', 'weight_kg': 1.0, 'medical_item': True}


def _supplier(name, **extra):
    base = {'company_name': name, 'status': 'approved', 'supplier_type': 'delivery',
            'average_rating': 4.5, 'on_time_rate': 90.0, 'total_orders': 40}
    base.update(extra)
    return base


def _create(svc, pickup=NYC, delivery=BROOKLYN, customer_id='CUST-1', order_id=None, **kw):
    kw.setdefault('max_price', 100.0)
    result = svc.create_delivery_request(
        order_id=order_id or f'ORD-{uuid.uuid4().hex[:6]}', customer_id=customer_id,
        pickup_location=pickup, delivery_location=delivery, package_info=PACKAGE, **kw)
    assert result['success'], result
    return result['request_id']


def _bid(svc, request_id, supplier_id, price=20.0, hours=3):
    now = datetime.now(timezone.utc)
    return svc.submit_bid(
        request_id=request_id, supplier_id=supplier_id, bid_price=price,
        estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=1 + hours)).isoformat())


def _expire(svc, request_id, seconds_ago=60):
    svc.delivery_requests[request_id].bidding_ends_at = (
        datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


@pytest.fixture
def svc():
    """Isolated service with an in-memory outbox and no settlement accessor."""
    return DeliveryBiddingService(
        suppliers={
            'SUP-NYC': _supplier('NYC Couriers', latitude=40.73, longitude=-73.99, service_radius_km=25),
            'SUP-LA': _supplier('LA Runners', latitude=34.05, longitude=-118.24, service_radius_km=50),
            'SUP-ANY': _supplier('Nationwide Freight', service_areas=['nationwide']),
            'SUP-TX': _supplier('Texas Only', service_areas=['Houston, TX']),
        },
        health_wallets={'CUST-1': {'balance': 1000.0, 'transactions': []}},
        event_publisher=lambda *a, **k: None,
    )


# ---------------------------------------------------------------------------
# geohash primitives
# ---------------------------------------------------------------------------

class TestGeohash:
    def test_encode_matches_the_reference_example(self):
        # The canonical geohash example: Jaén, Spain.
        assert geohash_encode(42.605, -5.603, 5) == 'ezs42'
        assert geohash_encode(42.605, -5.603, 12).startswith('ezs42')
        # Every prefix is the coarser cell containing the point.
        full = geohash_encode(40.7128, -74.0060, 7)
        for p in range(1, 7):
            assert geohash_encode(40.7128, -74.0060, p) == full[:p]

    def test_decoded_bbox_contains_the_encoded_point(self):
        for lat, lon in [(40.7128, -74.006), (-33.86, 151.21), (0.0, 0.0), (89.9, 179.9), (-89.9, -179.9)]:
            for p in (1, 3, 5, 7):
                lat_lo, lat_hi, lon_lo, lon_hi = geohash_decode_bbox(geohash_encode(lat, lon, p))
                assert lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi

    def test_longitude_wraps_at_the_antimeridian(self):
        assert geohash_encode(10.0, 180.0, 6) == geohash_encode(10.0, -180.0, 6)
        assert geohash_encode(10.0, 190.0, 6) == geohash_encode(10.0, -170.0, 6)

    def test_neighbors_are_eight_distinct_adjacent_cells(self):
        centre = geohash_encode(40.7128, -74.006, 5)
        cells = geohash_neighbors(centre)
        assert len(cells) == 8 and len(set(cells)) == 8 and centre not in cells
        lat_lo, lat_hi, lon_lo, lon_hi = geohash_decode_bbox(centre)
        for cell in cells:
            n_lat_lo, n_lat_hi, n_lon_lo, n_lon_hi = geohash_decode_bbox(cell)
            # Same size, sharing an edge or a corner with the centre cell.
            assert abs((n_lat_hi - n_lat_lo) - (lat_hi - lat_lo)) < 1e-9
            assert abs((n_lon_hi - n_lon_lo) - (lon_hi - lon_lo)) < 1e-9
            assert abs(n_lat_lo - lat_lo) <= (lat_hi - lat_lo) + 1e-9
            assert abs(n_lon_lo - lon_lo) <= (lon_hi - lon_lo) + 1e-9

    def test_neighbors_stop_at_the_poles(self):
        north = geohash_encode(89.99, 0.0, 3)
        assert len(geohash_neighbors(north)) == 5  # no row above the pole

    def test_precision_for_radius_is_the_finest_cell_that_still_covers_it(self):
        assert geohash_precision_for_radius(50) == 3
        assert geohash_precision_for_radius(5) == 4
        assert geohash_precision_for_radius(1) == 5
        assert geohash_precision_for_radius(0.5) == 6
        assert geohash_precision_for_radius(0.01) == 7
        assert geohash_precision_for_radius(20000) == 1
        assert geohash_precision_for_radius(0) == 7

    def test_haversine_reference_distance(self):
        # NYC -> LA great-circle distance is ~3,936 km.
        d = haversine_km(40.7128, -74.006, 34.0522, -118.2437)
        assert 3900 < d < 3970
        assert haversine_km(1, 2, 1, 2) == 0.0


# ---------------------------------------------------------------------------
# geo index + spatial queries
# ---------------------------------------------------------------------------

class TestGeoIndex:
    def test_open_requests_are_indexed_at_every_precision(self, svc):
        rid = _create(svc)
        request = svc.delivery_requests[rid]
        assert request.pickup_geohash == geohash_encode(NYC['latitude'], NYC['longitude'], 7)
        assert request.delivery_geohash == geohash_encode(BROOKLYN['latitude'], BROOKLYN['longitude'], 7)
        stats = svc.geo_index_stats()
        assert stats['indexed_open_requests'] == 1
        assert all(count == 1 for count in stats['cells_by_precision'].values())

    def test_nearby_uses_cells_then_exact_distance(self, svc):
        nyc = _create(svc, pickup=NYC)
        bk = _create(svc, pickup=BROOKLYN)
        la = _create(svc, pickup=LOS_ANGELES)

        found = svc.find_open_requests_near(40.75, -73.99, radius_km=15)
        ids = [m['request_id'] for m in found['matches']]
        assert ids == [nyc, bk]  # sorted by distance
        assert la not in ids
        assert found['precision'] == geohash_precision_for_radius(15) == 4
        assert found['cells_searched'] == 9
        assert all(m['distance_km'] <= 15 for m in found['matches'])
        assert found['matches'][0]['route_km'] > 0

        # Tight radius keeps only the request whose pickup is within it.
        tight = svc.find_open_requests_near(NYC['latitude'], NYC['longitude'], radius_km=2)
        assert [m['request_id'] for m in tight['matches']] == [nyc]

        # A candidate inside the searched cells but beyond the radius is dropped.
        assert tight['candidates'] >= 1
        far_in_cells = svc.find_open_requests_near(40.72, -74.0, radius_km=3)
        assert bk not in [m['request_id'] for m in far_in_cells['matches']]

    def test_request_just_across_a_cell_boundary_is_found(self, svc):
        radius = 5.0
        precision = geohash_precision_for_radius(radius)
        centre_lat, centre_lon = 40.7128, -74.0060
        _, _, _, lon_hi = geohash_decode_bbox(geohash_encode(centre_lat, centre_lon, precision))
        # Pickup a few hundred metres east of the centre cell's edge -> neighbour cell.
        across = dict(NYC, latitude=centre_lat, longitude=lon_hi + 0.002)
        rid = _create(svc, pickup=across)
        assert svc.delivery_requests[rid].pickup_geohash[:precision] != geohash_encode(
            centre_lat, centre_lon, precision)
        # Search from a point right inside the edge so the request is within the radius.
        found = svc.find_open_requests_near(centre_lat, lon_hi - 0.001, radius_km=radius)
        assert rid in [m['request_id'] for m in found['matches']]

    def test_limit_and_empty_results(self, svc):
        for _ in range(3):
            _create(svc, pickup=NYC)
        found = svc.find_open_requests_near(NYC['latitude'], NYC['longitude'], radius_km=10, limit=2)
        assert len(found['matches']) == 2 and found['candidates'] == 3
        nothing = svc.find_open_requests_near(LOS_ANGELES['latitude'], LOS_ANGELES['longitude'], radius_km=10)
        assert nothing['matches'] == [] and nothing['candidates'] == 0

    def test_selection_and_expiry_remove_requests_from_the_index(self, svc):
        chosen = _create(svc)
        expired = _create(svc)
        assert svc.geo_index_stats()['indexed_open_requests'] == 2

        bid = _bid(svc, chosen, 'SUP-NYC')
        assert bid['success'], bid
        assert svc.select_bid(chosen, bid['bid_id'])['success']
        assert svc.geo_index_stats()['indexed_open_requests'] == 1

        _expire(svc, expired)
        svc.expire_bidding_windows()
        assert svc.geo_index_stats()['indexed_open_requests'] == 0
        assert svc.geo_index_stats()['cells_by_precision'] == {p: 0 for p in range(1, 8)}

    def test_rebuild_from_an_injected_store_indexes_only_open_requests(self, svc):
        open_id = _create(svc)
        closed_id = _create(svc)
        svc.delivery_requests[closed_id].status = DeliveryStatus.DELIVERED
        svc.delivery_requests['junk'] = {'not': 'a request'}

        rebuilt = DeliveryBiddingService(delivery_requests=svc.delivery_requests,
                                         event_publisher=lambda *a, **k: None)
        assert rebuilt.geo_index_stats()['indexed_open_requests'] == 1
        assert open_id in rebuilt._indexed and closed_id not in rebuilt._indexed
        assert rebuilt.rebuild_geo_index() == 1


# ---------------------------------------------------------------------------
# supplier eligibility by distance
# ---------------------------------------------------------------------------

class TestSupplierDistance:
    def test_eligible_suppliers_are_matched_by_radius_then_service_area(self, svc):
        rid = _create(svc, pickup=NYC, delivery=NEWARK)
        result = svc.eligible_suppliers_for(rid)
        assert result['success']
        by_id = {s['supplier_id']: s for s in result['suppliers']}
        assert 'SUP-NYC' in by_id and by_id['SUP-NYC']['distance_to_pickup_km'] < 25
        assert by_id['SUP-NYC']['service_radius_km'] == 25
        assert 'SUP-LA' not in by_id           # coordinates far outside its radius
        assert 'SUP-ANY' in by_id and by_id['SUP-ANY']['distance_to_pickup_km'] is None
        assert 'SUP-TX' not in by_id           # no coordinates and service area does not cover NJ
        # Suppliers with a known distance sort first.
        assert [s['supplier_id'] for s in result['suppliers']] == ['SUP-NYC', 'SUP-ANY']
        assert svc.eligible_suppliers_for('nope')['success'] is False

    def test_default_radius_applies_when_the_supplier_has_coordinates_but_no_radius(self, svc):
        svc.suppliers['SUP-NORAD'] = _supplier('No Radius', latitude=40.9, longitude=-74.0)
        rid = _create(svc, pickup=NYC, delivery=NEWARK)
        by_id = {s['supplier_id']: s for s in svc.eligible_suppliers_for(rid)['suppliers']}
        assert by_id['SUP-NORAD']['service_radius_km'] == DEFAULT_SUPPLIER_SERVICE_RADIUS_KM

    def test_bid_from_outside_the_service_radius_is_refused(self, svc):
        rid = _create(svc)
        rejected = _bid(svc, rid, 'SUP-LA')
        assert rejected['success'] is False
        assert 'outside your 50 km service radius' in rejected['error']
        assert rejected['distance_to_pickup_km'] > 3000
        accepted = _bid(svc, rid, 'SUP-NYC')
        assert accepted['success'] and accepted['bid']['distance_to_pickup_km'] < 25
        no_coords = _bid(svc, rid, 'SUP-ANY')
        assert no_coords['success'] and no_coords['bid']['distance_to_pickup_km'] is None

    def test_supplier_coordinates_may_live_under_location(self, svc):
        svc.suppliers['SUP-NESTED'] = _supplier(
            'Nested', location={'latitude': 40.71, 'longitude': -74.0}, service_radius_km=10)
        svc.suppliers['SUP-BADCOORDS'] = _supplier('Bad', latitude='north', longitude='west')
        rid = _create(svc)
        by_id = {s['supplier_id']: s for s in svc.eligible_suppliers_for(rid)['suppliers']}
        assert by_id['SUP-NESTED']['distance_to_pickup_km'] < 10
        assert by_id['SUP-BADCOORDS']['distance_to_pickup_km'] is None  # unparsable -> no filter


# ---------------------------------------------------------------------------
# reliability from settled orders
# ---------------------------------------------------------------------------

class TestReliabilityBlend:
    def test_without_an_accessor_reliability_is_the_on_time_rate(self, svc):
        r = svc.reliability_for('SUP-NYC', 90.0)
        assert r == {'score': 0.9, 'source': 'on_time_rate', 'settled_orders': 0, 'settled_success_rate': None}
        assert svc.reliability_for('SUP-NYC', 250.0)['score'] == 1.0  # clamped
        assert svc.reliability_for('SUP-NYC', None)['score'] == 0.0

    def test_blend_applies_only_with_enough_settled_orders(self):
        outcomes = {
            'SUP-FEW': {'settled_orders': MIN_SETTLED_ORDERS_FOR_BLEND - 1, 'success_rate': 0.0},
            'SUP-GOOD': {'settled_orders': 10, 'success_rate': 1.0},
            'SUP-POOR': {'settled_orders': 10, 'success_rate': 0.5},
            'SUP-NORATE': {'settled_orders': 10},
        }
        svc = DeliveryBiddingService(settled_outcomes_func=outcomes.get, event_publisher=lambda *a, **k: None)

        few = svc.reliability_for('SUP-FEW', 90.0)
        assert few['source'] == 'on_time_rate' and few['score'] == 0.9
        assert few['settled_orders'] == MIN_SETTLED_ORDERS_FOR_BLEND - 1 and few['settled_success_rate'] == 0.0

        good = svc.reliability_for('SUP-GOOD', 90.0)
        expected = SETTLED_RELIABILITY_WEIGHT * 1.0 + (1 - SETTLED_RELIABILITY_WEIGHT) * 0.9
        assert good['source'] == 'settled_blend' and abs(good['score'] - expected) < 1e-9

        poor = svc.reliability_for('SUP-POOR', 90.0)
        assert poor['source'] == 'settled_blend' and poor['score'] < good['score']  # monotone in rate

        assert svc.reliability_for('SUP-NORATE', 90.0)['source'] == 'on_time_rate'
        assert svc.reliability_for('SUP-UNKNOWN', 90.0)['source'] == 'on_time_rate'

    def test_accessor_is_cached_and_failures_degrade_to_self_reported(self):
        calls = []

        def accessor(supplier_id):
            calls.append(supplier_id)
            if supplier_id == 'SUP-BOOM':
                raise RuntimeError('db down')
            return {'settled_orders': 5, 'success_rate': 0.8}

        svc = DeliveryBiddingService(settled_outcomes_func=accessor, event_publisher=lambda *a, **k: None)
        svc.reliability_for('SUP-A', 90.0)
        svc.reliability_for('SUP-A', 90.0)
        assert calls == ['SUP-A']  # one lookup per supplier until invalidated

        boom = svc.reliability_for('SUP-BOOM', 70.0)
        assert boom == {'score': 0.7, 'source': 'on_time_rate', 'settled_orders': 0, 'settled_success_rate': None}
        assert calls.count('SUP-BOOM') == 1
        svc.reliability_for('SUP-BOOM', 70.0)
        assert calls.count('SUP-BOOM') == 1  # negative result cached too

        svc.invalidate_settled_cache('SUP-A')
        svc.reliability_for('SUP-A', 90.0)
        assert calls.count('SUP-A') == 2
        svc.invalidate_settled_cache()
        svc.reliability_for('SUP-BOOM', 70.0)
        assert calls.count('SUP-BOOM') == 2

    def test_blend_is_recorded_on_the_bid_and_moves_the_ranking(self):
        outcomes = {'SUP-GOOD': {'settled_orders': 10, 'success_rate': 1.0},
                    'SUP-POOR': {'settled_orders': 10, 'success_rate': 0.2}}
        svc = DeliveryBiddingService(
            suppliers={'SUP-GOOD': _supplier('Good'), 'SUP-POOR': _supplier('Poor'),
                       'SUP-SELF': _supplier('Self-reported only')},
            settled_outcomes_func=outcomes.get, event_publisher=lambda *a, **k: None)
        rid = _create(svc)
        good = _bid(svc, rid, 'SUP-GOOD')
        poor = _bid(svc, rid, 'SUP-POOR')
        self_only = _bid(svc, rid, 'SUP-SELF')
        assert good['bid']['reliability_source'] == 'settled_blend'
        assert good['bid']['settled_orders'] == 10 and good['bid']['settled_success_rate'] == 1.0
        assert self_only['bid']['reliability_source'] == 'on_time_rate'
        assert self_only['bid']['reliability_score'] == 0.9
        # Identical price/time/rating: only the settled outcome differs.
        assert good['ai_score'] > self_only['ai_score'] > poor['ai_score']
        ranked = svc.get_bids_for_request(rid)
        assert ranked['ai_recommended']['supplier_id'] == 'SUP-GOOD'
        assert ranked['ranking_weights']['reliability_settled_weight'] == SETTLED_RELIABILITY_WEIGHT
        assert ranked['ranking_weights']['min_settled_orders_for_blend'] == MIN_SETTLED_ORDERS_FOR_BLEND


# ---------------------------------------------------------------------------
# settlement accessor on a real database
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch):
    db_path = os.path.join(tempfile.gettempdir(), f"phins_delivery_b11_{uuid.uuid4().hex}.db")
    monkeypatch.setenv('USE_SQLITE', '1')
    monkeypatch.setenv('SQLITE_PATH', db_path)
    monkeypatch.setenv('PHINS_TEST_MODE', 'true')
    import database
    database.reset_connection()
    from database import init_database
    init_database(drop_existing=True)
    import services.marketplace_accounting_service as mas
    import services.supplier_settlement_service as sss
    import services.marketplace_event_service as mes
    mas._marketplace_accounting_service = None
    sss._supplier_settlement_service = None
    mes._marketplace_event_service = None
    yield db_path
    mas._marketplace_accounting_service = None
    sss._supplier_settlement_service = None
    mes._marketplace_event_service = None
    try:
        os.remove(db_path)
    except OSError:
        pass
    database.reset_connection()


class TestSettledOutcomesAccessor:
    def test_only_executed_settlements_count_and_penalties_are_failures(self, isolated_db):
        from services.supplier_settlement_service import get_supplier_settlement_service
        settle = get_supplier_settlement_service()
        assert settle.get_settled_outcomes('SUP-A') is None
        assert settle.get_settled_outcomes('') is None

        run = settle.build_settlement_run('SUP-A', order_payloads=[
            {'order_id': 'ORD-1', 'gross_sales_amount': 120.0, 'supplier_cost_amount': 100.0},
            {'order_id': 'ORD-2', 'gross_sales_amount': 60.0, 'supplier_cost_amount': 50.0, 'penalty_amount': 5.0},
            {'order_id': 'ORD-3', 'gross_sales_amount': 30.0, 'supplier_cost_amount': 20.0},
        ])
        assert run['success']
        # Calculated but not executed: not an outcome yet.
        assert settle.get_settled_outcomes('SUP-A') is None

        assert settle.execute_settlement_run(run['run']['id'], executed_by='admin')['success']
        outcome = settle.get_settled_outcomes('SUP-A')
        assert outcome['settled_orders'] == 3 and outcome['penalized_orders'] == 1
        assert outcome['clawback_runs'] == 0 and outcome['executed_runs'] == 1
        assert abs(outcome['success_rate'] - 2 / 3) < 1e-6
        assert outcome['gross_settled_amount'] == 210.0 and outcome['penalty_total'] == 5.0
        assert outcome['last_settled_at'] is not None

        # A clawback after execution counts against the supplier once.
        assert settle.apply_clawback(run['run']['id'], amount=10.0, reason='damaged goods')['success']
        outcome = settle.get_settled_outcomes('SUP-A')
        assert outcome['clawback_runs'] == 1 and abs(outcome['success_rate'] - 1 / 3) < 1e-6

        # Wired into the bidding service the blend kicks in (3 settled orders).
        svc = DeliveryBiddingService(suppliers={'SUP-A': _supplier('A')},
                                     settled_outcomes_func=settle.get_settled_outcomes,
                                     event_publisher=lambda *a, **k: None)
        r = svc.reliability_for('SUP-A', 90.0)
        assert r['source'] == 'settled_blend' and r['settled_orders'] == 3
        assert abs(r['score'] - (SETTLED_RELIABILITY_WEIGHT * (1 / 3) + (1 - SETTLED_RELIABILITY_WEIGHT) * 0.9)) < 1e-6

    def test_default_accessor_is_only_wired_in_database_mode(self, monkeypatch):
        monkeypatch.setenv('USE_DATABASE', 'false')
        assert dbs.default_settled_outcomes_accessor() is None
        monkeypatch.setenv('USE_DATABASE', 'true')
        accessor = dbs.default_settled_outcomes_accessor()
        assert accessor is not None and accessor.__name__ == 'get_settled_outcomes'

    def test_outbox_event_is_durable_in_database_mode(self, isolated_db, monkeypatch):
        from services.marketplace_event_service import get_marketplace_event_service
        monkeypatch.setenv('USE_DATABASE', 'true')
        events = get_marketplace_event_service()
        svc = DeliveryBiddingService()  # default publisher -> marketplace outbox in DB mode
        rid = _create(svc)
        _expire(svc, rid)
        svc.expire_bidding_windows()
        record = svc.outbox_events[-1]
        assert record['published'] is True and record['outbox_id']
        pending = {e['id']: e for e in events.list_pending(limit=50)}
        assert record['outbox_id'] in pending
        row = pending[record['outbox_id']]
        assert row['event_type'] == BIDDING_WINDOW_CLOSED_EVENT and row['aggregate_id'] == rid


# ---------------------------------------------------------------------------
# SLA clock + outbox
# ---------------------------------------------------------------------------

class TestSlaClock:
    def test_window_with_bids_closes_and_recommends_the_top_bid(self, svc):
        rid = _create(svc)
        cheap = _bid(svc, rid, 'SUP-NYC', price=10.0)
        pricey = _bid(svc, rid, 'SUP-ANY', price=30.0)
        assert cheap['success'] and pricey['success']
        _expire(svc, rid)

        sweep = svc.expire_bidding_windows()
        assert sweep['closed'] == 1 and sweep['cancelled'] == 0 and sweep['open_remaining'] == 0
        transition = sweep['transitions'][0]
        assert transition == {'request_id': rid, 'outcome': 'closed_with_bids', 'status': 'bidding_closed',
                              'bid_count': 2, 'event_id': transition['event_id']}

        request = svc.delivery_requests[rid]
        assert request.status == DeliveryStatus.BIDDING_CLOSED
        assert request.closed_reason == 'bidding_window_elapsed' and request.bidding_closed_at

        event = svc.outbox_events[-1]
        assert event['event_type'] == BIDDING_WINDOW_CLOSED_EVENT
        assert event['aggregate_type'] == 'delivery_request' and event['aggregate_id'] == rid
        assert event['payload']['outcome'] == 'closed_with_bids'
        assert event['payload']['recommended_bid_id'] == cheap['bid_id']
        assert event['payload']['recommended_supplier_id'] == 'SUP-NYC'
        assert event['payload']['bid_count'] == 2 and event['payload']['customer_id'] == 'CUST-1'

        # Tracking log records the transition attributed to the clock.
        tracking = svc.get_delivery_tracking(rid)
        assert tracking['tracking_events'][-1]['updated_by'] == 'sla_clock'
        assert tracking['tracking_events'][-1]['status'] == 'bidding_closed'

        # The customer can still select among the bids that arrived in time.
        selected = svc.select_bid(rid, pricey['bid_id'])
        assert selected['success'] and svc.delivery_requests[rid].status == DeliveryStatus.BID_SELECTED
        assert svc.health_wallets['CUST-1']['balance'] == 970.0

    def test_window_without_bids_is_cancelled_with_a_reason(self, svc):
        rid = _create(svc)
        _expire(svc, rid)
        sweep = svc.expire_bidding_windows()
        assert sweep['closed'] == 0 and sweep['cancelled'] == 1
        request = svc.delivery_requests[rid]
        assert request.status == DeliveryStatus.CANCELLED
        assert request.closed_reason == 'bidding_window_elapsed_no_bids'
        assert svc.outbox_events[-1]['payload']['outcome'] == 'cancelled_no_bids'
        assert svc.outbox_events[-1]['payload']['recommended_bid_id'] is None
        # Nothing to select.
        assert svc.auto_select_best_bid(rid)['success'] is False

    def test_sweep_is_idempotent_and_leaves_live_windows_alone(self, svc):
        live = _create(svc)
        due = _create(svc)
        _expire(svc, due)
        first = svc.expire_bidding_windows()
        events_after_first = len(svc.outbox_events)
        second = svc.expire_bidding_windows()
        assert first['cancelled'] == 1 and second['transitions'] == []
        assert len(svc.outbox_events) == events_after_first
        assert svc.delivery_requests[live].status == DeliveryStatus.BIDDING_OPEN
        assert second['open_remaining'] == 1
        assert svc.next_window_deadline() == svc.delivery_requests[live].bidding_ends_at

    def test_explicit_now_drives_the_clock(self, svc):
        rid = _create(svc)
        deadline = datetime.fromisoformat(svc.delivery_requests[rid].bidding_ends_at)
        before = svc.expire_bidding_windows(now=deadline - timedelta(seconds=1))
        assert before['transitions'] == [] and before['checked_at'] == (deadline - timedelta(seconds=1)).isoformat()
        at = svc.expire_bidding_windows(now=deadline)  # inclusive: now >= deadline closes
        assert at['cancelled'] == 1
        # Naive datetimes are treated as UTC.
        other = _create(svc)
        naive_future = datetime.now() + timedelta(days=1)
        assert svc.expire_bidding_windows(now=naive_future.replace(tzinfo=None))['cancelled'] == 1
        assert svc.delivery_requests[other].status == DeliveryStatus.CANCELLED

    def test_late_bid_closes_the_window_and_is_refused(self, svc):
        rid = _create(svc)
        ok = _bid(svc, rid, 'SUP-NYC')
        assert ok['success']
        _expire(svc, rid)
        late = _bid(svc, rid, 'SUP-ANY')
        assert late == {'success': False, 'error': 'Bidding deadline has passed', 'status': 'bidding_closed'}
        assert svc.outbox_events[-1]['payload']['outcome'] == 'closed_with_bids'
        # A second late bid sees the already-closed status; no second event.
        again = _bid(svc, rid, 'SUP-TX')
        assert again['success'] is False and 'Bidding is closed' in again['error']
        assert len([e for e in svc.outbox_events if e['aggregate_id'] == rid]) == 1

    def test_reading_bids_or_searching_nearby_applies_expiry_lazily(self, svc):
        rid = _create(svc)
        _expire(svc, rid)
        listing = svc.get_bids_for_request(rid)
        assert listing['request_status'] == 'cancelled'
        assert listing['closed_reason'] == 'bidding_window_elapsed_no_bids' and listing['bidding_closed_at']

        other = _create(svc)
        _expire(svc, other)
        found = svc.find_open_requests_near(NYC['latitude'], NYC['longitude'], radius_km=10)
        assert found['matches'] == []
        assert svc.delivery_requests[other].status == DeliveryStatus.CANCELLED

    def test_unparsable_or_missing_deadlines_never_expire(self, svc):
        rid = _create(svc)
        svc.delivery_requests[rid].bidding_ends_at = 'not-a-date'
        assert svc.expire_bidding_windows()['transitions'] == []
        svc.delivery_requests[rid].bidding_ends_at = None
        assert svc.expire_bidding_windows()['transitions'] == []
        assert svc.next_window_deadline() is None

    def test_publisher_receives_the_event_and_failures_are_recorded_not_raised(self):
        published = []

        def publisher(event_type, aggregate_type, aggregate_id, payload):
            published.append((event_type, aggregate_type, aggregate_id, payload))
            return {'id': 'OUTBOX-1'}

        svc = DeliveryBiddingService(event_publisher=publisher)
        rid = _create(svc)
        _expire(svc, rid)
        svc.expire_bidding_windows()
        assert published[0][:3] == (BIDDING_WINDOW_CLOSED_EVENT, 'delivery_request', rid)
        record = svc.outbox_events[-1]
        assert record['published'] is True and record['outbox_id'] == 'OUTBOX-1'

        def broken(*_a, **_k):
            raise RuntimeError('outbox unavailable')

        svc_broken = DeliveryBiddingService(event_publisher=broken)
        rid2 = _create(svc_broken)
        _expire(svc_broken, rid2)
        sweep = svc_broken.expire_bidding_windows()
        assert sweep['cancelled'] == 1  # the state transition still happens
        record = svc_broken.outbox_events[-1]
        assert record['published'] is False and record['publish_error'] == 'outbox unavailable'

    def test_default_publisher_is_local_only_outside_database_mode(self, monkeypatch):
        monkeypatch.setenv('USE_DATABASE', 'false')
        svc = DeliveryBiddingService()
        rid = _create(svc)
        _expire(svc, rid)
        svc.expire_bidding_windows()
        record = svc.outbox_events[-1]
        assert record['published'] is False and record['publish_error'] is None

    def test_health_probe_reports_b11_state(self, svc, monkeypatch):
        monkeypatch.setattr(dbs, '_delivery_service', None)
        assert dbs._delivery_bidding_health() == {'status': 'ok', 'initialized': False}
        monkeypatch.setattr(dbs, '_delivery_service', svc)
        rid = _create(svc)
        health = dbs._delivery_bidding_health()
        assert health['initialized'] is True and health['delivery_requests'] == 1
        assert health['geo_index']['indexed_open_requests'] == 1
        assert health['settled_outcomes_wired'] is False
        assert health['reliability_blend'] == {'settled_weight': SETTLED_RELIABILITY_WEIGHT,
                                               'min_settled_orders': MIN_SETTLED_ORDERS_FOR_BLEND}
        assert health['next_window_deadline'] == svc.delivery_requests[rid].bidding_ends_at
        assert health['outbox_events'] == 0


# ---------------------------------------------------------------------------
# recurring queue job
# ---------------------------------------------------------------------------

class TestSlaJob:
    @pytest.fixture
    def bound(self, svc, monkeypatch):
        """Make the job's ``get_delivery_bidding_service()`` resolve to ``svc``."""
        monkeypatch.setattr(dbs, '_delivery_service', svc)
        from services.agent_job_queue import AgentJobQueue, reset_job_queue
        from services.jobs import delivery_sla_job
        reset_job_queue()
        queue = AgentJobQueue(poll_interval=0.01)
        delivery_sla_job.register(queue)
        yield queue, delivery_sla_job
        reset_job_queue()

    def test_clock_is_enqueued_once_and_reschedules_itself_without_consuming_attempts(self, bound, svc, monkeypatch):
        queue, job = bound
        monkeypatch.setenv('PHINS_DELIVERY_SLA_TICK_SECONDS', '45')
        first = job.ensure_sla_clock(queue)
        second = job.ensure_sla_clock(queue, submitted_by='another-process')
        assert first['id'] == second['id'] and first['idempotency_key'] == job.IDEMPOTENCY_KEY
        assert first['subject_type'] == job.SUBJECT_TYPE and first['subject_id'] == job.SUBJECT_ID
        assert queue.queue_stats().get('pending') == 1

        rid = _create(svc)
        _expire(svc, rid)
        stats = queue.process_once()
        assert stats['rescheduled'] == 1 and stats['completed'] == 0 and stats['failed'] == 0
        assert svc.delivery_requests[rid].status == DeliveryStatus.CANCELLED

        row = queue.get_job(first['id'])
        assert row['status'] == 'pending' and row['attempts'] == 0 and row['error_message'] is None
        next_at = row['next_retry_at']
        if isinstance(next_at, str):
            next_at = datetime.fromisoformat(next_at)
        seconds = (next_at - datetime.utcnow()).total_seconds()
        assert 40 <= seconds <= 46
        # Not due yet: nothing is claimed on the next poll.
        assert queue.process_once()['claimed'] == 0

    def test_single_sweep_completes_with_the_summary(self, bound, svc):
        queue, job = bound
        rid = _create(svc)
        _expire(svc, rid)
        once = job.enqueue_once(queue, submitted_by='admin', idempotency_key='sweep-1')
        assert once['max_attempts'] == 1
        assert job.enqueue_once(queue, idempotency_key='sweep-1')['id'] == once['id']
        stats = queue.process_once()
        assert stats['completed'] == 1
        row = queue.get_job(once['id'])
        result = row['result'] if isinstance(row['result'], dict) else json.loads(row['result'])
        assert result['cancelled'] == 1 and result['transitions'][0]['request_id'] == rid

    def test_tick_seconds_is_clamped_and_defaults(self, monkeypatch):
        from services.jobs import delivery_sla_job as job
        monkeypatch.delenv('PHINS_DELIVERY_SLA_TICK_SECONDS', raising=False)
        assert job.tick_seconds() == job.DEFAULT_TICK_SECONDS
        monkeypatch.setenv('PHINS_DELIVERY_SLA_TICK_SECONDS', '0.2')
        assert job.tick_seconds() == 1.0
        monkeypatch.setenv('PHINS_DELIVERY_SLA_TICK_SECONDS', 'soon')
        assert job.tick_seconds() == job.DEFAULT_TICK_SECONDS

    def test_register_all_binds_the_handler(self):
        from services.agent_job_queue import AgentJobQueue
        from services.jobs import delivery_sla_job, register_all
        queue = AgentJobQueue(poll_interval=0.01)
        register_all(queue)
        assert delivery_sla_job.JOB_TYPE in queue.handlers()


# ---------------------------------------------------------------------------
# HTTP layer (embedded portal from the root conftest)
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
    SUPPLIER_IDS = ('SUP-HTTP-NYC', 'SUP-HTTP-LA')

    @staticmethod
    def _base():
        return os.environ.get('TEST_BASE_URL') or f"http://127.0.0.1:{os.environ.get('TEST_PORT', '8000')}"

    @pytest.fixture
    def portal(self):
        import web_portal.server as portal
        previous = dbs._delivery_service
        dbs._delivery_service = None  # bind a fresh singleton to the portal stores
        portal.SUPPLIERS['SUP-HTTP-NYC'] = _supplier('HTTP NYC Couriers', latitude=40.73, longitude=-73.99,
                                                     service_radius_km=25)
        portal.SUPPLIERS['SUP-HTTP-LA'] = _supplier('HTTP LA Runners', latitude=34.05, longitude=-118.24,
                                                    service_radius_km=50)
        yield portal
        for sid in self.SUPPLIER_IDS:
            portal.SUPPLIERS.pop(sid, None)
        dbs._delivery_service = previous

    @pytest.fixture
    def tokens(self, portal):
        status, payload = _http(f'{self._base()}/api/login', method='POST',
                                payload={'username': 'admin', 'password': 'admin123'})
        assert status == 200, payload
        # The portal wipes in-memory stores on the first request of a test
        # (``_ensure_test_port_state``); seed wallets only after that login.
        portal.HEALTH_WALLETS['CUST-HTTP-1'] = {'balance': 500.0, 'transactions': []}
        portal.HEALTH_WALLETS['CUST-HTTP-2'] = {'balance': 500.0, 'transactions': []}
        expires = (datetime.now() + timedelta(hours=1)).isoformat()
        seeded = {
            'customer1': {'username': 'cust-http-1', 'role': 'customer', 'customer_id': 'CUST-HTTP-1'},
            'customer2': {'username': 'cust-http-2', 'role': 'customer', 'customer_id': 'CUST-HTTP-2'},
            'supplier_nyc': {'username': 'SUP-HTTP-NYC', 'role': 'supplier', 'supplier_id': 'SUP-HTTP-NYC'},
            'supplier_la': {'username': 'sup-http-la', 'role': 'supplier', 'supplier_id': 'SUP-HTTP-LA'},
        }
        out = {'admin': payload['token']}
        with portal.STATE_LOCK:
            for name, session in seeded.items():
                token = f'phins_b11_{name}_{uuid.uuid4().hex[:8]}'
                portal.SESSIONS[token] = dict(session, expires=expires, jti=f'{token}-jti')
                out[name] = token
        return out

    def test_full_bidding_flow_is_role_scoped(self, portal, tokens):
        base = self._base()
        now = datetime.now(timezone.utc)

        # Unauthenticated and unknown routes.
        assert _http(f'{base}/api/delivery/insights')[0] == 401
        assert _http(f'{base}/api/delivery/whatever', token=tokens['admin'])[0] == 404
        assert _http(f'{base}/api/delivery/whatever', method='POST', token=tokens['admin'], payload={})[0] == 404

        # A customer creates a request; customer_id comes from the session, not the body.
        status, created = _http(f'{base}/api/delivery/request', method='POST', token=tokens['customer1'], payload={
            'order_id': 'ORD-HTTP-1', 'customer_id': 'CUST-HTTP-2',
            'pickup_location': NYC, 'delivery_location': NEWARK,
            'package_info': PACKAGE, 'priority': 'express', 'max_price': 100.0})
        assert status == 201, created
        rid = created['request_id']
        assert created['request']['customer_id'] == 'CUST-HTTP-1'
        assert created['pickup_geohash'] == geohash_encode(NYC['latitude'], NYC['longitude'], 7)
        assert created['eligible_suppliers_count'] >= 1
        assert portal.portal_delivery_bidding_service().delivery_requests[rid].customer_id == 'CUST-HTTP-1'

        # Suppliers cannot create requests; a bad priority is a 400.
        assert _http(f'{base}/api/delivery/request', method='POST', token=tokens['supplier_nyc'],
                     payload={'order_id': 'x', 'pickup_location': NYC, 'delivery_location': NEWARK})[0] == 403
        status, bad = _http(f'{base}/api/delivery/request', method='POST', token=tokens['customer1'], payload={
            'order_id': 'ORD-BAD', 'pickup_location': NYC, 'delivery_location': NEWARK, 'priority': 'teleport'})
        assert status == 400 and 'error' in bad

        # Nearby search via the geohash index (supplier/admin only).
        status, nearby = _http(f'{base}/api/delivery/nearby?latitude=40.75&longitude=-73.99&radius_km=15',
                               token=tokens['supplier_nyc'])
        assert status == 200 and rid in [m['request_id'] for m in nearby['matches']]
        assert nearby['precision'] == 4
        assert _http(f'{base}/api/delivery/nearby?latitude=40.75&longitude=-73.99', token=tokens['customer1'])[0] == 403
        assert _http(f'{base}/api/delivery/nearby?latitude=abc', token=tokens['supplier_nyc'])[0] == 400

        # Eligible suppliers are admin-only and reflect the distance filter.
        assert _http(f'{base}/api/delivery/eligible/{rid}', token=tokens['supplier_nyc'])[0] == 403
        status, eligible = _http(f'{base}/api/delivery/eligible/{rid}', token=tokens['admin'])
        ids = [s['supplier_id'] for s in eligible['suppliers']]
        assert 'SUP-HTTP-NYC' in ids and 'SUP-HTTP-LA' not in ids
        assert _http(f'{base}/api/delivery/eligible/DEL-NOPE', token=tokens['admin'])[0] == 404

        # A supplier bids as itself only.
        bid_body = {'request_id': rid, 'bid_price': 15.0,
                    'estimated_pickup_time': (now + timedelta(hours=1)).isoformat(),
                    'estimated_delivery_time': (now + timedelta(hours=4)).isoformat()}
        status, spoof = _http(f'{base}/api/delivery/bid', method='POST', token=tokens['supplier_nyc'],
                              payload=dict(bid_body, supplier_id='SUP-HTTP-LA'))
        assert status == 403 and 'only bid as itself' in spoof['error']
        status, bid = _http(f'{base}/api/delivery/bid', method='POST', token=tokens['supplier_nyc'], payload=bid_body)
        assert status == 201, bid
        assert bid['bid']['supplier_id'] == 'SUP-HTTP-NYC' and bid['reliability']['source'] == 'on_time_rate'
        # Out-of-radius supplier is refused with the distance explanation.
        status, far = _http(f'{base}/api/delivery/bid', method='POST', token=tokens['supplier_la'], payload=bid_body)
        assert status == 409 and 'service radius' in far['error'] and far['distance_to_pickup_km'] > 3000
        # Customers cannot bid; missing fields are a 400.
        assert _http(f'{base}/api/delivery/bid', method='POST', token=tokens['customer1'], payload=bid_body)[0] == 403
        assert _http(f'{base}/api/delivery/bid', method='POST', token=tokens['admin'],
                     payload={'request_id': rid})[0] == 400

        # Bids listing: owner and admin see it, another customer does not.
        status, bids = _http(f'{base}/api/delivery/bids/{rid}', token=tokens['customer1'])
        assert status == 200 and bids['total_bids'] == 1 and bids['ranking_weights']['reliability'] == 0.20
        assert _http(f'{base}/api/delivery/bids/{rid}', token=tokens['customer2'])[0] == 403
        assert _http(f'{base}/api/delivery/bids/{rid}', token=tokens['admin'])[0] == 200
        assert _http(f'{base}/api/delivery/bids/DEL-NOPE', token=tokens['admin'])[0] == 404

        # Evaluate without auto-accept leaves the request open.
        status, evaluated = _http(f'{base}/api/delivery/evaluate-bids', method='POST', token=tokens['customer1'],
                                  payload={'request_id': rid})
        assert status == 200 and evaluated['selection'] is None
        assert evaluated['evaluation']['ai_recommended']['bid_id'] == bid['bid_id']
        assert _http(f'{base}/api/delivery/evaluate-bids', method='POST', token=tokens['customer2'],
                     payload={'request_id': rid})[0] == 403

        # Accepting debits the owner's wallet (and only the owner may accept).
        assert _http(f'{base}/api/delivery/accept-bid', method='POST', token=tokens['customer2'],
                     payload={'request_id': rid, 'bid_id': bid['bid_id']})[0] == 403
        status, accepted = _http(f'{base}/api/delivery/accept-bid', method='POST', token=tokens['customer1'],
                                 payload={'request_id': rid, 'bid_id': bid['bid_id']})
        assert status == 200, accepted
        assert accepted['new_wallet_balance'] == 485.0
        assert portal.HEALTH_WALLETS['CUST-HTTP-1']['balance'] == 485.0
        assert any(tx.get('metadata', {}).get('bid_id') == bid['bid_id'] for tx in portal.TRANSACTION_LEDGER.values())
        # Accepting again is a 409 (bid no longer pending / request not open).
        assert _http(f'{base}/api/delivery/accept-bid', method='POST', token=tokens['customer1'],
                     payload={'request_id': rid, 'bid_id': bid['bid_id']})[0] == 409

        # Only the assigned supplier may update fulfilment status.
        assert _http(f'{base}/api/delivery/update-status', method='POST', token=tokens['supplier_la'],
                     payload={'request_id': rid, 'status': 'picked_up'})[0] == 403
        status, updated = _http(f'{base}/api/delivery/update-status', method='POST', token=tokens['supplier_nyc'],
                                payload={'request_id': rid, 'status': 'picked_up', 'location': NYC})
        assert status == 200 and updated['new_status'] == 'picked_up'
        assert _http(f'{base}/api/delivery/update-status', method='POST', token=tokens['supplier_nyc'],
                     payload={'request_id': rid, 'status': 'beamed'})[0] == 409

        # Tracking follows the same visibility rule.
        status, track = _http(f'{base}/api/delivery/track/{rid}', token=tokens['customer1'])
        assert status == 200 and track['current_status'] == 'picked_up'
        assert _http(f'{base}/api/delivery/track/{rid}', token=tokens['customer2'])[0] == 403

        # Analytics: supplier sees itself regardless of the query; admin may pick.
        status, own = _http(f'{base}/api/delivery/analytics?supplier_id=SUP-HTTP-LA', token=tokens['supplier_nyc'])
        assert status == 200 and own['supplier_id'] == 'SUP-HTTP-NYC' and own['bids_accepted'] == 1
        assert _http(f'{base}/api/delivery/analytics', token=tokens['customer1'])[0] == 403
        status, overall = _http(f'{base}/api/delivery/analytics', token=tokens['admin'])
        assert status == 200 and overall['total_delivery_requests'] >= 1
        assert _http(f'{base}/api/delivery/insights', token=tokens['supplier_nyc'])[0] == 403
        assert _http(f'{base}/api/delivery/insights', token=tokens['admin'])[0] == 200

    def test_expire_windows_is_admin_only_and_closes_overdue_requests(self, portal, tokens):
        base = self._base()
        status, created = _http(f'{base}/api/delivery/request', method='POST', token=tokens['customer1'], payload={
            'order_id': 'ORD-HTTP-SLA', 'pickup_location': NYC, 'delivery_location': NEWARK, 'package_info': PACKAGE})
        assert status == 201, created
        rid = created['request_id']
        service = portal.portal_delivery_bidding_service()
        _expire(service, rid)

        assert _http(f'{base}/api/delivery/expire-windows', method='POST', token=tokens['supplier_nyc'], payload={})[0] == 403
        status, sweep = _http(f'{base}/api/delivery/expire-windows', method='POST', token=tokens['admin'], payload={})
        assert status == 200 and sweep['cancelled'] == 1
        assert sweep['transitions'][0]['request_id'] == rid
        assert service.outbox_events[-1]['event_type'] == BIDDING_WINDOW_CLOSED_EVENT

        status, bids = _http(f'{base}/api/delivery/bids/{rid}', token=tokens['customer1'])
        assert status == 200 and bids['request_status'] == 'cancelled'
        assert bids['closed_reason'] == 'bidding_window_elapsed_no_bids'

    def test_invalid_json_body_is_a_400(self, portal, tokens):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        req = Request(f'{self._base()}/api/delivery/request', data=b'{not json', method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': f"Bearer {tokens['admin']}"})
        try:
            with urlopen(req, timeout=30) as resp:
                status, body = resp.status, json.loads(resp.read().decode('utf-8'))
        except HTTPError as exc:
            status, body = exc.code, json.loads(exc.read().decode('utf-8'))
        assert status == 400 and body == {'error': 'Invalid JSON body'}
