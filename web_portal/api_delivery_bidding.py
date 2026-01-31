"""
API Extensions for Delivery Bidding System
==========================================
API endpoints for delivery bidding, supplier matching, and delivery tracking.

Endpoints:
- POST /api/delivery/request - Create delivery request
- POST /api/delivery/bid - Submit supplier bid
- GET /api/delivery/bids/<request_id> - Get bids for request
- POST /api/delivery/accept-bid - Accept winning bid
- POST /api/delivery/update-status - Update delivery status
- GET /api/delivery/track/<delivery_id> - Track delivery
- POST /api/delivery/pay - Process delivery payment
- POST /api/delivery/rate - Rate completed delivery
- GET /api/delivery/supplier-performance/<supplier_id> - Get supplier metrics
"""

import json
from datetime import datetime, timezone
from services.delivery_bidding_service import get_delivery_bidding_service


def handle_delivery_request_create(handler, body: dict) -> tuple:
    """Handle POST /api/delivery/request"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        # Extract request data
        customer_id = body.get('customer_id')
        order_id = body.get('order_id')
        pickup_location = body.get('pickup_location', {})
        delivery_location = body.get('delivery_location', {})
        item_details = body.get('item_details', {})
        urgency = body.get('urgency', 'standard')
        max_budget = body.get('max_budget')
        preferred_time = body.get('preferred_time')
        special_instructions = body.get('special_instructions')
        
        if not all([customer_id, order_id, pickup_location, delivery_location]):
            return 400, {'error': 'Missing required fields'}
        
        result = delivery_service.create_delivery_request(
            customer_id=customer_id,
            order_id=order_id,
            pickup_location=pickup_location,
            delivery_location=delivery_location,
            item_details=item_details,
            urgency=urgency,
            max_budget=max_budget,
            preferred_time=preferred_time,
            special_instructions=special_instructions
        )
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_bid_submit(handler, body: dict) -> tuple:
    """Handle POST /api/delivery/bid"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        # Extract bid data
        request_id = body.get('request_id')
        supplier_id = body.get('supplier_id')
        bid_amount = body.get('bid_amount')
        estimated_pickup_time = body.get('estimated_pickup_time')
        estimated_delivery_time = body.get('estimated_delivery_time')
        vehicle_type = body.get('vehicle_type', 'van')
        notes = body.get('notes')
        
        if not all([request_id, supplier_id, bid_amount, estimated_pickup_time, estimated_delivery_time]):
            return 400, {'error': 'Missing required fields'}
        
        result = delivery_service.submit_bid(
            request_id=request_id,
            supplier_id=supplier_id,
            bid_amount=float(bid_amount),
            estimated_pickup_time=estimated_pickup_time,
            estimated_delivery_time=estimated_delivery_time,
            vehicle_type=vehicle_type,
            notes=notes
        )
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_bids_get(handler, request_id: str) -> tuple:
    """Handle GET /api/delivery/bids/<request_id>"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        request = delivery_service.delivery_requests.get(request_id)
        if not request:
            return 404, {'error': 'Delivery request not found'}
        
        # Get all bids for this request
        bids = [delivery_service.delivery_bids[bid_id] 
                for bid_id in request.get('bids', []) 
                if bid_id in delivery_service.delivery_bids]
        
        return 200, {
            'request_id': request_id,
            'request': request,
            'bids': bids,
            'bid_count': len(bids)
        }
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_bid_accept(handler, body: dict) -> tuple:
    """Handle POST /api/delivery/accept-bid"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        request_id = body.get('request_id')
        bid_id = body.get('bid_id')
        accepted_by = body.get('accepted_by', 'SYSTEM')
        
        if not all([request_id, bid_id]):
            return 400, {'error': 'Missing required fields'}
        
        result = delivery_service.accept_bid(
            request_id=request_id,
            bid_id=bid_id,
            accepted_by=accepted_by
        )
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_bid_evaluate(handler, body: dict) -> tuple:
    """Handle POST /api/delivery/evaluate-bids (AI evaluation)"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        request_id = body.get('request_id')
        auto_accept = body.get('auto_accept', False)
        
        if not request_id:
            return 400, {'error': 'Missing request_id'}
        
        result = delivery_service.evaluate_bids_ai(
            request_id=request_id,
            auto_accept=auto_accept
        )
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_status_update(handler, body: dict) -> tuple:
    """Handle POST /api/delivery/update-status"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        delivery_id = body.get('delivery_id')
        new_status = body.get('status')
        location = body.get('location')
        notes = body.get('notes')
        updated_by = body.get('updated_by')
        
        if not all([delivery_id, new_status]):
            return 400, {'error': 'Missing required fields'}
        
        result = delivery_service.update_delivery_status(
            delivery_id=delivery_id,
            new_status=new_status,
            location=location,
            notes=notes,
            updated_by=updated_by
        )
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_track(handler, delivery_id: str) -> tuple:
    """Handle GET /api/delivery/track/<delivery_id>"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        result = delivery_service.get_delivery_status(delivery_id)
        
        if not result.get('success'):
            return 404, result
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_payment(handler, body: dict, health_wallets: dict) -> tuple:
    """Handle POST /api/delivery/pay"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        delivery_id = body.get('delivery_id')
        customer_id = body.get('customer_id')
        
        if not all([delivery_id, customer_id]):
            return 400, {'error': 'Missing required fields'}
        
        # Get wallet balance
        wallet = health_wallets.get(customer_id, {})
        balance = wallet.get('balance', 0)
        
        # Define wallet transaction callback
        def wallet_tx_callback(customer_id, amount, transaction_type, description, metadata):
            # Record wallet transaction
            tx_id = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            wallet = health_wallets.get(customer_id, {})
            prev_balance = wallet.get('balance', 0)
            new_balance = prev_balance + amount
            
            wallet['balance'] = new_balance
            tx = {
                'transaction_id': tx_id,
                'type': transaction_type,
                'amount': amount,
                'description': description,
                'previous_balance': prev_balance,
                'balance_after': new_balance,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                **metadata
            }
            
            if 'transactions' not in wallet:
                wallet['transactions'] = []
            wallet['transactions'].append(tx)
            
            return tx
        
        result = delivery_service.process_delivery_payment(
            delivery_id=delivery_id,
            customer_id=customer_id,
            health_wallet_balance=balance,
            wallet_transaction_callback=wallet_tx_callback
        )
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_rate(handler, body: dict) -> tuple:
    """Handle POST /api/delivery/rate"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        delivery_id = body.get('delivery_id')
        rating = body.get('rating')
        review = body.get('review')
        rated_by = body.get('rated_by')
        
        if not all([delivery_id, rating]):
            return 400, {'error': 'Missing required fields'}
        
        result = delivery_service.rate_delivery(
            delivery_id=delivery_id,
            rating=float(rating),
            review=review,
            rated_by=rated_by
        )
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_supplier_performance_get(handler, supplier_id: str) -> tuple:
    """Handle GET /api/delivery/supplier-performance/<supplier_id>"""
    try:
        delivery_service = get_delivery_bidding_service()
        
        result = delivery_service.get_supplier_performance(supplier_id)
        
        return 200, result
    
    except Exception as e:
        return 500, {'error': str(e)}
