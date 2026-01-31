"""
Tests for Delivery Bidding Service
===================================
Tests AI-powered delivery bidding system with location-based matching.
"""

import pytest
from datetime import datetime, timedelta, timezone
from services.delivery_bidding_service import DeliveryBiddingService


@pytest.fixture
def delivery_service():
    """Create delivery bidding service instance"""
    return DeliveryBiddingService()


@pytest.fixture
def sample_pickup_location():
    """Sample pickup location"""
    return {
        'address': '123 Main St',
        'city': 'New York',
        'state': 'NY',
        'zip': '10001',
        'lat': 40.7128,
        'lon': -74.0060
    }


@pytest.fixture
def sample_delivery_location():
    """Sample delivery location"""
    return {
        'address': '456 Broadway',
        'city': 'New York',
        'state': 'NY',
        'zip': '10013',
        'lat': 40.7209,
        'lon': -74.0007
    }


@pytest.fixture
def sample_item_details():
    """Sample item details"""
    return {
        'description': 'Medical supplies package',
        'weight_kg': 5.0,
        'dimensions': '30x20x15cm',
        'fragile': True,
        'temperature_controlled': False
    }


def test_create_delivery_request(delivery_service, sample_pickup_location, 
                                 sample_delivery_location, sample_item_details):
    """Test creating a delivery request"""
    result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details,
        urgency='standard',
        max_budget=50.00
    )
    
    assert result['success'] == True
    assert 'request_id' in result
    assert 'request' in result
    assert result['request']['urgency'] == 'standard'
    assert result['request']['max_budget'] == 50.00
    assert result['request']['status'] == 'open_for_bidding'
    
    # Check distance calculation
    assert result['request']['distance_km'] > 0


def test_submit_bid(delivery_service, sample_pickup_location, 
                   sample_delivery_location, sample_item_details):
    """Test submitting a supplier bid"""
    # Create request first
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details,
        urgency='standard'
    )
    
    request_id = request_result['request_id']
    
    # Submit bid
    now = datetime.now(timezone.utc)
    pickup_time = (now + timedelta(hours=1)).isoformat()
    delivery_time = (now + timedelta(hours=3)).isoformat()
    
    bid_result = delivery_service.submit_bid(
        request_id=request_id,
        supplier_id='SUP-001',
        bid_amount=35.00,
        estimated_pickup_time=pickup_time,
        estimated_delivery_time=delivery_time,
        vehicle_type='van',
        notes='Fast and reliable delivery'
    )
    
    assert bid_result['success'] == True
    assert 'bid_id' in bid_result
    assert bid_result['bid']['bid_amount'] == 35.00
    assert bid_result['bid']['status'] == 'pending'


def test_submit_multiple_bids(delivery_service, sample_pickup_location, 
                              sample_delivery_location, sample_item_details):
    """Test multiple suppliers bidding on same request"""
    # Create request
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details,
        urgency='standard'
    )
    
    request_id = request_result['request_id']
    now = datetime.now(timezone.utc)
    
    # Submit 3 bids from different suppliers
    bids = []
    for i, (supplier, amount) in enumerate([
        ('SUP-001', 35.00),
        ('SUP-002', 30.00),  # Lower price
        ('SUP-003', 40.00)
    ]):
        bid_result = delivery_service.submit_bid(
            request_id=request_id,
            supplier_id=supplier,
            bid_amount=amount,
            estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=2+i)).isoformat(),
            vehicle_type='van'
        )
        assert bid_result['success'] == True
        bids.append(bid_result['bid_id'])
    
    # Check request has all bids
    request = delivery_service.delivery_requests[request_id]
    assert request['bid_count'] == 3
    assert len(request['bids']) == 3


def test_bid_exceeds_budget(delivery_service, sample_pickup_location, 
                            sample_delivery_location, sample_item_details):
    """Test bid rejection when exceeding max budget"""
    # Create request with max budget
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details,
        urgency='standard',
        max_budget=30.00
    )
    
    request_id = request_result['request_id']
    now = datetime.now(timezone.utc)
    
    # Try to submit bid exceeding budget
    bid_result = delivery_service.submit_bid(
        request_id=request_id,
        supplier_id='SUP-001',
        bid_amount=50.00,  # Exceeds budget
        estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=3)).isoformat()
    )
    
    assert bid_result['success'] == False
    assert 'budget' in bid_result['error'].lower()


def test_evaluate_bids_ai(delivery_service, sample_pickup_location, 
                         sample_delivery_location, sample_item_details):
    """Test AI evaluation of bids"""
    # Create request
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details,
        urgency='standard'
    )
    
    request_id = request_result['request_id']
    now = datetime.now(timezone.utc)
    
    # Submit multiple bids with varying attributes
    # Supplier 1: Lower price, slower delivery
    delivery_service.submit_bid(
        request_id=request_id,
        supplier_id='SUP-001',
        bid_amount=25.00,
        estimated_pickup_time=(now + timedelta(hours=2)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=6)).isoformat()
    )
    
    # Supplier 2: Medium price, fast delivery, good rating
    delivery_service.supplier_metrics['SUP-002'] = {
        'rating': 4.8,
        'reliability_score': 0.95
    }
    delivery_service.submit_bid(
        request_id=request_id,
        supplier_id='SUP-002',
        bid_amount=35.00,
        estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=2)).isoformat()
    )
    
    # Supplier 3: Higher price, fastest delivery
    delivery_service.submit_bid(
        request_id=request_id,
        supplier_id='SUP-003',
        bid_amount=45.00,
        estimated_pickup_time=(now + timedelta(minutes=30)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=1)).isoformat()
    )
    
    # Evaluate bids with AI
    evaluation = delivery_service.evaluate_bids_ai(request_id, auto_accept=False)
    
    assert evaluation['success'] == True
    assert evaluation['total_bids'] == 3
    assert 'winning_bid' in evaluation
    assert 'ai_score' in evaluation['winning_bid']
    assert evaluation['winning_bid']['ai_score'] > 0
    
    # Winning bid should be SUP-002 (best balance of price, speed, and rating)
    assert evaluation['winning_bid']['supplier_id'] == 'SUP-002'


def test_accept_bid(delivery_service, sample_pickup_location, 
                   sample_delivery_location, sample_item_details):
    """Test accepting a bid and creating delivery"""
    # Create request and bid
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details
    )
    
    request_id = request_result['request_id']
    now = datetime.now(timezone.utc)
    
    bid_result = delivery_service.submit_bid(
        request_id=request_id,
        supplier_id='SUP-001',
        bid_amount=35.00,
        estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=3)).isoformat()
    )
    
    bid_id = bid_result['bid_id']
    
    # Accept bid
    acceptance = delivery_service.accept_bid(request_id, bid_id, 'CUST-001')
    
    assert acceptance['success'] == True
    assert 'delivery_id' in acceptance
    assert acceptance['delivery']['status'] == 'confirmed'
    assert acceptance['delivery']['customer_id'] == 'CUST-001'
    assert acceptance['delivery']['supplier_id'] == 'SUP-001'
    
    # Check request status updated
    request = delivery_service.delivery_requests[request_id]
    assert request['status'] == 'bid_accepted'
    assert request['winning_bid_id'] == bid_id


def test_update_delivery_status(delivery_service, sample_pickup_location, 
                                sample_delivery_location, sample_item_details):
    """Test updating delivery status with tracking"""
    # Create and accept delivery
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details
    )
    
    request_id = request_result['request_id']
    now = datetime.now(timezone.utc)
    
    bid_result = delivery_service.submit_bid(
        request_id=request_id,
        supplier_id='SUP-001',
        bid_amount=35.00,
        estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=3)).isoformat()
    )
    
    acceptance = delivery_service.accept_bid(request_id, bid_result['bid_id'])
    delivery_id = acceptance['delivery_id']
    
    # Update status: en route to pickup
    update1 = delivery_service.update_delivery_status(
        delivery_id=delivery_id,
        new_status='en_route_to_pickup',
        location={'lat': 40.7128, 'lon': -74.0060},
        notes='Driver heading to pickup location',
        updated_by='SUP-001'
    )
    
    assert update1['success'] == True
    assert update1['new_status'] == 'en_route_to_pickup'
    
    # Update status: picked up
    update2 = delivery_service.update_delivery_status(
        delivery_id=delivery_id,
        new_status='picked_up',
        location={'lat': 40.7128, 'lon': -74.0060},
        notes='Package picked up'
    )
    
    assert update2['success'] == True
    
    # Update status: delivered
    update3 = delivery_service.update_delivery_status(
        delivery_id=delivery_id,
        new_status='delivered',
        location={'lat': 40.7209, 'lon': -74.0007},
        notes='Package delivered successfully'
    )
    
    assert update3['success'] == True
    assert update3['delivery']['completed'] == True
    
    # Check status history
    delivery = delivery_service.active_deliveries[delivery_id]
    assert len(delivery['status_updates']) >= 4  # confirmed + 3 updates


def test_delivery_payment(delivery_service, sample_pickup_location, 
                         sample_delivery_location, sample_item_details):
    """Test processing delivery payment from health wallet"""
    # Create and complete delivery
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details
    )
    
    now = datetime.now(timezone.utc)
    bid_result = delivery_service.submit_bid(
        request_id=request_result['request_id'],
        supplier_id='SUP-001',
        bid_amount=35.00,
        estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=3)).isoformat()
    )
    
    acceptance = delivery_service.accept_bid(
        request_result['request_id'], 
        bid_result['bid_id']
    )
    delivery_id = acceptance['delivery_id']
    
    # Mock wallet transaction callback
    wallet_transactions = []
    
    def mock_wallet_callback(customer_id, amount, transaction_type, description, metadata):
        tx = {
            'transaction_id': 'TXN-001',
            'customer_id': customer_id,
            'amount': amount,
            'type': transaction_type,
            'description': description,
            **metadata
        }
        wallet_transactions.append(tx)
        return tx
    
    # Process payment
    payment = delivery_service.process_delivery_payment(
        delivery_id=delivery_id,
        customer_id='CUST-001',
        health_wallet_balance=100.00,
        wallet_transaction_callback=mock_wallet_callback
    )
    
    assert payment['success'] == True
    assert payment['amount_paid'] == 35.00
    assert payment['supplier_id'] == 'SUP-001'
    assert payment['new_wallet_balance'] == 65.00
    
    # Check wallet transaction was created
    assert len(wallet_transactions) == 1
    assert wallet_transactions[0]['amount'] == -35.00


def test_rate_delivery(delivery_service, sample_pickup_location, 
                      sample_delivery_location, sample_item_details):
    """Test rating a completed delivery"""
    # Create, accept, and complete delivery
    request_result = delivery_service.create_delivery_request(
        customer_id='CUST-001',
        order_id='ORD-001',
        pickup_location=sample_pickup_location,
        delivery_location=sample_delivery_location,
        item_details=sample_item_details
    )
    
    now = datetime.now(timezone.utc)
    bid_result = delivery_service.submit_bid(
        request_id=request_result['request_id'],
        supplier_id='SUP-001',
        bid_amount=35.00,
        estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
        estimated_delivery_time=(now + timedelta(hours=3)).isoformat()
    )
    
    acceptance = delivery_service.accept_bid(
        request_result['request_id'],
        bid_result['bid_id']
    )
    delivery_id = acceptance['delivery_id']
    
    # Mark as delivered
    delivery_service.update_delivery_status(
        delivery_id=delivery_id,
        new_status='delivered',
        notes='Delivered successfully'
    )
    
    # Rate delivery
    rating_result = delivery_service.rate_delivery(
        delivery_id=delivery_id,
        rating=4.5,
        review='Fast and professional service',
        rated_by='CUST-001'
    )
    
    assert rating_result['success'] == True
    assert rating_result['rating'] == 4.5
    
    # Check supplier metrics updated
    metrics = delivery_service.supplier_metrics.get('SUP-001')
    assert metrics is not None
    assert metrics['total_deliveries'] > 0


def test_distance_calculation(delivery_service):
    """Test Haversine distance calculation"""
    # New York to Los Angeles (approx 3936 km)
    ny_lat, ny_lon = 40.7128, -74.0060
    la_lat, la_lon = 34.0522, -118.2437
    
    distance = delivery_service._calculate_distance(ny_lat, ny_lon, la_lat, la_lon)
    
    assert distance > 3900
    assert distance < 4000  # Approximately correct
    
    # Same location (distance = 0)
    distance_zero = delivery_service._calculate_distance(ny_lat, ny_lon, ny_lat, ny_lon)
    assert distance_zero == 0.0


def test_supplier_performance_tracking(delivery_service):
    """Test supplier performance metrics tracking"""
    # Initialize supplier
    supplier_id = 'SUP-TEST'
    delivery_service.supplier_metrics[supplier_id] = {
        'total_deliveries': 0,
        'total_revenue': 0.0,
        'rating': 5.0,
        'reliability_score': 1.0,
        'on_time_percentage': 100.0
    }
    
    # Simulate delivery payment (updates metrics)
    delivery_service.supplier_metrics[supplier_id]['total_deliveries'] += 1
    delivery_service.supplier_metrics[supplier_id]['total_revenue'] += 35.00
    
    # Get performance
    performance = delivery_service.get_supplier_performance(supplier_id)
    
    assert performance['supplier_id'] == supplier_id
    assert performance['total_deliveries'] == 1
    assert performance['total_revenue'] == 35.00
    assert performance['status'] == 'Active'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
