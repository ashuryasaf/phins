"""
Tests for Delivery Bidding Service
===================================
Tests AI-powered delivery bidding system with location-based matching.
"""

import pytest
import math
from datetime import datetime, timedelta, timezone
from services.delivery_bidding_service import (
    DeliveryBiddingService,
    DeliveryRequest,
    DeliveryBid,
    DeliveryStatus,
    BidStatus,
    GeoLocation,
    DeliveryPriority,
)


@pytest.fixture
def delivery_service():
    return DeliveryBiddingService()


@pytest.fixture
def delivery_service_with_suppliers():
    suppliers = {
        'SUP-001': {'company_name': 'MediDeliver', 'status': 'approved',
                     'supplier_type': 'delivery', 'average_rating': 4.5,
                     'on_time_rate': 96.0, 'total_orders': 50},
        'SUP-002': {'company_name': 'QuickShip', 'status': 'approved',
                     'supplier_type': 'delivery', 'average_rating': 4.8,
                     'on_time_rate': 99.0, 'total_orders': 100},
        'SUP-003': {'company_name': 'BudgetCarry', 'status': 'approved',
                     'supplier_type': 'delivery', 'average_rating': 3.8,
                     'on_time_rate': 88.0, 'total_orders': 20},
    }
    wallets = {
        'CUST-001': {'balance': 500.0, 'transactions': []},
    }
    return DeliveryBiddingService(suppliers=suppliers, health_wallets=wallets)


@pytest.fixture
def sample_pickup():
    return {
        'latitude': 40.7128, 'longitude': -74.0060,
        'address': '123 Main St', 'city': 'New York', 'state': 'NY',
        'contact': {'name': 'Pharmacy', 'phone': '555-0100'}
    }


@pytest.fixture
def sample_delivery():
    return {
        'latitude': 40.9176, 'longitude': -74.1719,
        'address': '456 Broad St', 'city': 'Newark', 'state': 'NJ',
        'contact': {'name': 'Patient', 'phone': '555-0200'}
    }


@pytest.fixture
def sample_package():
    return {
        'description': 'Medical supplies package',
        'weight_kg': 5.0,
        'dimensions': {'length': 30, 'width': 20, 'height': 15},
        'fragile': True,
        'temperature_controlled': False,
        'medical_item': True,
    }


def _create_request(svc, pickup, delivery, package, **kwargs):
    return svc.create_delivery_request(
        order_id=kwargs.get('order_id', 'ORD-001'),
        customer_id=kwargs.get('customer_id', 'CUST-001'),
        pickup_location=pickup,
        delivery_location=delivery,
        package_info=package,
        priority=kwargs.get('priority', 'standard'),
        max_price=kwargs.get('max_price', None),
    )


def _submit_bid(svc, request_id, supplier_id, price, hours_offset=1, duration_hours=3):
    now = datetime.now(timezone.utc)
    return svc.submit_bid(
        request_id=request_id,
        supplier_id=supplier_id,
        bid_price=price,
        estimated_pickup_time=(now + timedelta(hours=hours_offset)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=hours_offset + duration_hours)).isoformat(),
        vehicle_type='van',
    )


def test_create_delivery_request(delivery_service, sample_pickup,
                                 sample_delivery, sample_package):
    result = _create_request(delivery_service, sample_pickup, sample_delivery, sample_package)

    assert result['success'] is True
    assert 'request_id' in result
    assert result['status'] == 'bidding_open'
    assert result['distance_km'] > 0
    assert result['max_price'] > 0


def test_submit_bid(delivery_service_with_suppliers, sample_pickup,
                    sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    bid = _submit_bid(svc, req['request_id'], 'SUP-001', 35.00)

    assert bid['success'] is True
    assert 'bid_id' in bid
    assert bid['ai_score'] > 0
    assert bid['bid']['bid_price'] == 35.00
    assert bid['bid']['status'] == 'pending'


def test_submit_multiple_bids(delivery_service_with_suppliers, sample_pickup,
                               sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']

    for supplier, price in [('SUP-001', 35.0), ('SUP-002', 30.0), ('SUP-003', 40.0)]:
        bid = _submit_bid(svc, req_id, supplier, price)
        assert bid['success'] is True

    bids_result = svc.get_bids_for_request(req_id)
    assert bids_result['total_bids'] == 3
    assert bids_result['ai_recommended'] is not None


def test_bid_exceeds_budget(delivery_service_with_suppliers, sample_pickup,
                             sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package, max_price=30.00)
    bid = _submit_bid(svc, req['request_id'], 'SUP-001', 50.00)

    assert bid['success'] is False
    assert 'exceeds' in bid['error'].lower() or 'maximum' in bid['error'].lower() or 'price' in bid['error'].lower()


def test_evaluate_bids_ai(delivery_service_with_suppliers, sample_pickup,
                           sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']

    _submit_bid(svc, req_id, 'SUP-001', 25.00, duration_hours=6)
    _submit_bid(svc, req_id, 'SUP-002', 35.00, duration_hours=2)
    _submit_bid(svc, req_id, 'SUP-003', 45.00, duration_hours=1)

    bids_result = svc.get_bids_for_request(req_id)
    assert bids_result['success'] is True
    assert bids_result['total_bids'] == 3

    recommended = bids_result['ai_recommended']
    assert recommended is not None
    assert recommended['ai_score'] > 0

    top_bid = svc.delivery_bids[recommended['bid_id']]
    assert top_bid.ai_ranking == 1


def test_accept_bid(delivery_service_with_suppliers, sample_pickup,
                     sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']
    bid = _submit_bid(svc, req_id, 'SUP-001', 35.00)
    bid_id = bid['bid_id']

    result = svc.select_bid(req_id, bid_id, 'CUST-001')

    assert result['success'] is True
    assert result['supplier_id'] == 'SUP-001'
    assert result['price_paid'] == 35.00
    assert result['status'] == 'bid_selected'
    assert result['new_wallet_balance'] == 465.0

    request_obj = svc.delivery_requests[req_id]
    assert request_obj.status == DeliveryStatus.BID_SELECTED
    assert request_obj.selected_bid_id == bid_id


def test_update_delivery_status(delivery_service_with_suppliers, sample_pickup,
                                 sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']
    bid = _submit_bid(svc, req_id, 'SUP-001', 35.00)
    svc.select_bid(req_id, bid['bid_id'], 'CUST-001')

    update1 = svc.update_delivery_status(
        request_id=req_id,
        new_status='picked_up',
        supplier_id='SUP-001',
        notes='Package picked up from pharmacy'
    )
    assert update1['success'] is True
    assert update1['new_status'] == 'picked_up'

    update2 = svc.update_delivery_status(
        request_id=req_id,
        new_status='in_transit',
        supplier_id='SUP-001',
        location={'latitude': 40.715, 'longitude': -74.003},
        notes='En route'
    )
    assert update2['success'] is True

    update3 = svc.update_delivery_status(
        request_id=req_id,
        new_status='delivered',
        supplier_id='SUP-001',
        notes='Delivered to patient'
    )
    assert update3['success'] is True
    assert svc.delivery_requests[req_id].delivered_at is not None


def test_delivery_payment(delivery_service_with_suppliers, sample_pickup,
                           sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']
    bid = _submit_bid(svc, req_id, 'SUP-001', 35.00)

    result = svc.select_bid(req_id, bid['bid_id'], 'CUST-001')
    assert result['success'] is True
    assert result['price_paid'] == 35.00
    assert result['new_wallet_balance'] == 465.0

    wallet = svc.health_wallets['CUST-001']
    assert wallet['balance'] == 465.0
    assert len(wallet['transactions']) == 1
    assert wallet['transactions'][0]['type'] == 'delivery_payment'
    assert wallet['transactions'][0]['amount'] == -35.00


def test_rate_delivery(delivery_service_with_suppliers, sample_pickup,
                        sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']
    bid = _submit_bid(svc, req_id, 'SUP-001', 35.00)
    svc.select_bid(req_id, bid['bid_id'], 'CUST-001')

    svc.update_delivery_status(req_id, 'picked_up', 'SUP-001')
    svc.update_delivery_status(req_id, 'delivered', 'SUP-001')

    tracking = svc.get_delivery_tracking(req_id)
    assert tracking['success'] is True
    assert tracking['current_status'] == 'delivered'
    assert tracking['total_events'] >= 3


def test_distance_calculation():
    ny = GeoLocation(latitude=40.7128, longitude=-74.0060)
    la = GeoLocation(latitude=34.0522, longitude=-118.2437)

    distance = ny.distance_to(la)
    assert distance > 3900
    assert distance < 4000

    same = ny.distance_to(ny)
    assert same == 0.0


def test_supplier_performance_tracking(delivery_service_with_suppliers,
                                        sample_pickup, sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']
    bid = _submit_bid(svc, req_id, 'SUP-001', 35.00)
    svc.select_bid(req_id, bid['bid_id'], 'CUST-001')
    svc.update_delivery_status(req_id, 'picked_up', 'SUP-001')
    svc.update_delivery_status(req_id, 'delivered', 'SUP-001')

    supplier = svc.suppliers['SUP-001']
    assert supplier['total_orders'] == 51
    assert supplier['total_revenue'] > 0


def test_auto_select_best_bid(delivery_service_with_suppliers, sample_pickup,
                                sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']

    _submit_bid(svc, req_id, 'SUP-001', 30.00)
    _submit_bid(svc, req_id, 'SUP-002', 35.00)

    result = svc.auto_select_best_bid(req_id)
    assert result['success'] is True
    assert result['status'] == 'bid_selected'


def test_delivery_analytics(delivery_service_with_suppliers, sample_pickup,
                             sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    _submit_bid(svc, req['request_id'], 'SUP-001', 30.00)

    analytics = svc.get_delivery_analytics()
    assert analytics['total_delivery_requests'] == 1
    assert analytics['total_bids'] == 1
    assert 'by_priority' in analytics

    supplier_analytics = svc.get_delivery_analytics('SUP-001')
    assert supplier_analytics['total_bids_submitted'] == 1


def test_ai_delivery_insights(delivery_service):
    insights = delivery_service.get_ai_delivery_insights()
    assert 'recommendations' in insights
    assert 'alerts' in insights
    assert 'optimizations' in insights


def test_duplicate_bid_rejected(delivery_service_with_suppliers, sample_pickup,
                                 sample_delivery, sample_package):
    svc = delivery_service_with_suppliers
    req = _create_request(svc, sample_pickup, sample_delivery, sample_package)
    req_id = req['request_id']

    _submit_bid(svc, req_id, 'SUP-001', 30.00)
    dup = _submit_bid(svc, req_id, 'SUP-001', 25.00)
    assert dup['success'] is False
    assert 'already' in dup['error'].lower()


def test_bid_on_nonexistent_request(delivery_service):
    result = _submit_bid(delivery_service, 'FAKE-REQUEST', 'SUP-001', 10.0)
    assert result['success'] is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
