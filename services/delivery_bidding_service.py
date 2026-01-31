"""
PHINS Delivery Bidding Service
================================
AI-powered delivery bidding system for B2B marketplace.

Features:
- Location-based supplier matching
- Real-time bidding for delivery services
- Health wallet integration for payments
- AI-powered route optimization
- Supplier performance tracking
- Delivery status tracking with real-time updates

Flow:
1. Customer buys product using health wallet
2. Delivery preferences uploaded to bidding system
3. Eligible delivery suppliers notified (location-based)
4. Suppliers place bids (price, estimated delivery time)
5. AI evaluates bids (price, supplier rating, delivery time, location)
6. Customer/system approves best bid
7. Delivery executed with real-time tracking
8. Payment settled from health wallet to delivery supplier
9. Supplier and customer ratings updated
"""

import json
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
import logging
import math

logger = logging.getLogger('phins.delivery_bidding')


class DeliveryBiddingService:
    """
    Manages delivery bidding workflow for B2B marketplace.
    
    Integrates with:
    - Health Wallets (payment source)
    - Supplier ecosystem (delivery providers)
    - AI optimization (bid evaluation)
    - Location services (distance calculation)
    """
    
    def __init__(self):
        """Initialize delivery bidding service"""
        # Delivery requests awaiting bids
        self.delivery_requests: Dict[str, Dict[str, Any]] = {}
        
        # Active bids from suppliers
        self.delivery_bids: Dict[str, Dict[str, Any]] = {}
        
        # Active deliveries
        self.active_deliveries: Dict[str, Dict[str, Any]] = {}
        
        # Completed deliveries
        self.delivery_history: Dict[str, Dict[str, Any]] = {}
        
        # Supplier performance metrics
        self.supplier_metrics: Dict[str, Dict[str, Any]] = {}
        
        logger.info("Delivery Bidding Service initialized")
    
    def create_delivery_request(
        self,
        customer_id: str,
        order_id: str,
        pickup_location: Dict[str, Any],
        delivery_location: Dict[str, Any],
        item_details: Dict[str, Any],
        urgency: str = 'standard',
        max_budget: float = None,
        preferred_time: str = None,
        special_instructions: str = None
    ) -> Dict[str, Any]:
        """
        Create a new delivery request and open it for bidding.
        
        Args:
            customer_id: Customer placing the order
            order_id: Associated order/purchase ID
            pickup_location: {address, city, state, zip, lat, lon}
            delivery_location: {address, city, state, zip, lat, lon}
            item_details: {description, weight_kg, dimensions, fragile, temperature_controlled}
            urgency: 'express', 'standard', 'economy'
            max_budget: Maximum amount customer willing to pay
            preferred_time: Preferred delivery time window
            special_instructions: Any special handling requirements
            
        Returns:
            Delivery request details
        """
        now = datetime.now(timezone.utc)
        request_id = f"DELREQ-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        
        # Calculate distance between pickup and delivery
        distance_km = self._calculate_distance(
            pickup_location.get('lat', 0),
            pickup_location.get('lon', 0),
            delivery_location.get('lat', 0),
            delivery_location.get('lon', 0)
        )
        
        # Set bidding deadline based on urgency
        urgency_hours = {
            'express': 1,      # 1 hour bidding window
            'standard': 4,     # 4 hour bidding window
            'economy': 24      # 24 hour bidding window
        }
        bidding_deadline = now + timedelta(hours=urgency_hours.get(urgency, 4))
        
        request = {
            'id': request_id,
            'customer_id': customer_id,
            'order_id': order_id,
            'pickup_location': pickup_location,
            'delivery_location': delivery_location,
            'item_details': item_details,
            'urgency': urgency,
            'distance_km': distance_km,
            'max_budget': max_budget,
            'preferred_time': preferred_time,
            'special_instructions': special_instructions,
            'status': 'open_for_bidding',
            'created_at': now.isoformat(),
            'bidding_deadline': bidding_deadline.isoformat(),
            'bids': [],
            'bid_count': 0,
            'winning_bid_id': None,
            'delivery_id': None
        }
        
        self.delivery_requests[request_id] = request
        logger.info(f"Created delivery request {request_id} for customer {customer_id} "
                   f"({distance_km:.1f}km, {urgency} urgency)")
        
        return {
            'success': True,
            'request_id': request_id,
            'request': request,
            'bidding_deadline': bidding_deadline.isoformat(),
            'estimated_suppliers': self._estimate_eligible_suppliers(pickup_location)
        }
    
    def submit_bid(
        self,
        request_id: str,
        supplier_id: str,
        bid_amount: float,
        estimated_pickup_time: str,
        estimated_delivery_time: str,
        vehicle_type: str = 'van',
        notes: str = None
    ) -> Dict[str, Any]:
        """
        Supplier submits a bid for a delivery request.
        
        Args:
            request_id: Delivery request ID
            supplier_id: Supplier/delivery provider ID
            bid_amount: Bid price
            estimated_pickup_time: When supplier can pick up
            estimated_delivery_time: Estimated delivery completion
            vehicle_type: 'bike', 'motorcycle', 'car', 'van', 'truck'
            notes: Additional notes from supplier
            
        Returns:
            Bid submission result
        """
        request = self.delivery_requests.get(request_id)
        if not request:
            return {'success': False, 'error': 'Delivery request not found'}
        
        if request['status'] != 'open_for_bidding':
            return {'success': False, 'error': 'Request is no longer accepting bids'}
        
        # Check if bidding deadline has passed
        deadline = datetime.fromisoformat(request['bidding_deadline'])
        if datetime.now(timezone.utc) > deadline:
            return {'success': False, 'error': 'Bidding deadline has passed'}
        
        # Check budget constraint
        if request.get('max_budget') and bid_amount > request['max_budget']:
            return {'success': False, 'error': f"Bid exceeds max budget ${request['max_budget']:.2f}"}
        
        now = datetime.now(timezone.utc)
        bid_id = f"BID-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        
        # Get supplier metrics for ranking
        supplier_rating = self.supplier_metrics.get(supplier_id, {}).get('rating', 0.0)
        supplier_reliability = self.supplier_metrics.get(supplier_id, {}).get('reliability_score', 0.5)
        
        # Calculate estimated delivery duration
        try:
            pickup_time = datetime.fromisoformat(estimated_pickup_time)
            delivery_time = datetime.fromisoformat(estimated_delivery_time)
            delivery_duration_hours = (delivery_time - pickup_time).total_seconds() / 3600
        except:
            delivery_duration_hours = 0
        
        bid = {
            'id': bid_id,
            'request_id': request_id,
            'supplier_id': supplier_id,
            'bid_amount': bid_amount,
            'estimated_pickup_time': estimated_pickup_time,
            'estimated_delivery_time': estimated_delivery_time,
            'delivery_duration_hours': delivery_duration_hours,
            'vehicle_type': vehicle_type,
            'notes': notes,
            'status': 'pending',
            'submitted_at': now.isoformat(),
            'supplier_rating': supplier_rating,
            'supplier_reliability': supplier_reliability,
            'ai_score': 0.0  # Will be calculated when evaluating
        }
        
        # Add bid to request
        request['bids'].append(bid_id)
        request['bid_count'] += 1
        
        # Store bid
        self.delivery_bids[bid_id] = bid
        
        logger.info(f"Supplier {supplier_id} submitted bid {bid_id} for request {request_id} "
                   f"(${bid_amount:.2f}, {delivery_duration_hours:.1f}h)")
        
        return {
            'success': True,
            'bid_id': bid_id,
            'bid': bid,
            'ranking': self._rank_bid(bid, request)
        }
    
    def evaluate_bids_ai(
        self,
        request_id: str,
        auto_accept: bool = False
    ) -> Dict[str, Any]:
        """
        AI evaluates all bids and recommends the best option.
        
        Evaluation criteria:
        - Price (40% weight)
        - Supplier rating (25% weight)
        - Delivery time (20% weight)
        - Supplier reliability (15% weight)
        
        Args:
            request_id: Delivery request ID
            auto_accept: Automatically accept winning bid
            
        Returns:
            Evaluation results with recommended bid
        """
        request = self.delivery_requests.get(request_id)
        if not request:
            return {'success': False, 'error': 'Delivery request not found'}
        
        if request['bid_count'] == 0:
            return {'success': False, 'error': 'No bids received yet'}
        
        # Get all bids
        bids = [self.delivery_bids[bid_id] for bid_id in request['bids'] 
                if bid_id in self.delivery_bids]
        
        if not bids:
            return {'success': False, 'error': 'No valid bids found'}
        
        # Calculate AI scores for each bid
        scored_bids = []
        for bid in bids:
            score = self._calculate_ai_bid_score(bid, request, bids)
            bid['ai_score'] = score
            scored_bids.append(bid)
        
        # Sort by AI score descending
        scored_bids.sort(key=lambda x: x['ai_score'], reverse=True)
        
        winning_bid = scored_bids[0]
        
        evaluation = {
            'success': True,
            'request_id': request_id,
            'total_bids': len(bids),
            'winning_bid': winning_bid,
            'alternative_bids': scored_bids[1:3] if len(scored_bids) > 1 else [],
            'recommendation': self._generate_bid_recommendation(winning_bid, request),
            'evaluated_at': datetime.now(timezone.utc).isoformat()
        }
        
        if auto_accept:
            acceptance = self.accept_bid(request_id, winning_bid['id'], 'AI_AUTO_ACCEPT')
            evaluation['acceptance'] = acceptance
        
        logger.info(f"AI evaluated {len(bids)} bids for request {request_id}. "
                   f"Winning bid: {winning_bid['id']} from supplier {winning_bid['supplier_id']} "
                   f"(score: {winning_bid['ai_score']:.2f})")
        
        return evaluation
    
    def accept_bid(
        self,
        request_id: str,
        bid_id: str,
        accepted_by: str = 'SYSTEM'
    ) -> Dict[str, Any]:
        """
        Accept a bid and initiate delivery.
        
        Args:
            request_id: Delivery request ID
            bid_id: Winning bid ID
            accepted_by: Who accepted (customer_id or SYSTEM)
            
        Returns:
            Acceptance result with delivery details
        """
        request = self.delivery_requests.get(request_id)
        bid = self.delivery_bids.get(bid_id)
        
        if not request or not bid:
            return {'success': False, 'error': 'Request or bid not found'}
        
        if request['status'] != 'open_for_bidding':
            return {'success': False, 'error': 'Request is no longer accepting bids'}
        
        if bid['request_id'] != request_id:
            return {'success': False, 'error': 'Bid does not match request'}
        
        now = datetime.now(timezone.utc)
        delivery_id = f"DEL-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        
        # Update request status
        request['status'] = 'bid_accepted'
        request['winning_bid_id'] = bid_id
        request['delivery_id'] = delivery_id
        request['accepted_at'] = now.isoformat()
        request['accepted_by'] = accepted_by
        
        # Update bid status
        bid['status'] = 'accepted'
        bid['accepted_at'] = now.isoformat()
        
        # Reject other bids
        for other_bid_id in request['bids']:
            if other_bid_id != bid_id and other_bid_id in self.delivery_bids:
                self.delivery_bids[other_bid_id]['status'] = 'rejected'
        
        # Create active delivery
        delivery = {
            'id': delivery_id,
            'request_id': request_id,
            'bid_id': bid_id,
            'customer_id': request['customer_id'],
            'supplier_id': bid['supplier_id'],
            'order_id': request['order_id'],
            'pickup_location': request['pickup_location'],
            'delivery_location': request['delivery_location'],
            'item_details': request['item_details'],
            'amount': bid['bid_amount'],
            'status': 'confirmed',
            'estimated_pickup_time': bid['estimated_pickup_time'],
            'estimated_delivery_time': bid['estimated_delivery_time'],
            'vehicle_type': bid['vehicle_type'],
            'created_at': now.isoformat(),
            'accepted_at': now.isoformat(),
            'status_updates': [
                {
                    'status': 'confirmed',
                    'timestamp': now.isoformat(),
                    'note': f'Delivery confirmed with supplier {bid["supplier_id"]}'
                }
            ],
            'payment_status': 'pending',
            'tracking_url': f'/api/delivery/track/{delivery_id}'
        }
        
        self.active_deliveries[delivery_id] = delivery
        
        logger.info(f"Bid {bid_id} accepted for request {request_id}. "
                   f"Delivery {delivery_id} initiated with supplier {bid['supplier_id']}")
        
        return {
            'success': True,
            'delivery_id': delivery_id,
            'delivery': delivery,
            'bid': bid,
            'payment_required': bid['bid_amount']
        }
    
    def update_delivery_status(
        self,
        delivery_id: str,
        new_status: str,
        location: Dict[str, float] = None,
        notes: str = None,
        updated_by: str = None
    ) -> Dict[str, Any]:
        """
        Update delivery status with real-time tracking.
        
        Status flow:
        confirmed → en_route_to_pickup → picked_up → in_transit → 
        arriving → delivered → completed
        
        Args:
            delivery_id: Delivery ID
            new_status: New status code
            location: Current location {lat, lon}
            notes: Status update notes
            updated_by: Who updated (supplier_id)
            
        Returns:
            Update result
        """
        delivery = self.active_deliveries.get(delivery_id)
        if not delivery:
            # Check if in history
            delivery = self.delivery_history.get(delivery_id)
            if delivery:
                return {'success': False, 'error': 'Delivery already completed'}
            return {'success': False, 'error': 'Delivery not found'}
        
        now = datetime.now(timezone.utc)
        
        # Create status update
        status_update = {
            'status': new_status,
            'timestamp': now.isoformat(),
            'location': location,
            'note': notes,
            'updated_by': updated_by
        }
        
        # Update delivery
        old_status = delivery['status']
        delivery['status'] = new_status
        delivery['status_updates'].append(status_update)
        delivery['last_updated'] = now.isoformat()
        
        if location:
            delivery['current_location'] = location
        
        # Handle completion
        if new_status == 'delivered':
            delivery['actual_delivery_time'] = now.isoformat()
            delivery['completed'] = True
        elif new_status == 'completed':
            # Move to history
            self.delivery_history[delivery_id] = delivery
            del self.active_deliveries[delivery_id]
        
        logger.info(f"Delivery {delivery_id} status updated: {old_status} → {new_status}")
        
        return {
            'success': True,
            'delivery_id': delivery_id,
            'old_status': old_status,
            'new_status': new_status,
            'timestamp': now.isoformat(),
            'delivery': delivery
        }
    
    def process_delivery_payment(
        self,
        delivery_id: str,
        customer_id: str,
        health_wallet_balance: float,
        wallet_transaction_callback: callable
    ) -> Dict[str, Any]:
        """
        Process payment from customer health wallet to delivery supplier.
        
        Args:
            delivery_id: Delivery ID
            customer_id: Customer making payment
            health_wallet_balance: Current wallet balance
            wallet_transaction_callback: Function to record wallet transaction
            
        Returns:
            Payment result
        """
        delivery = self.active_deliveries.get(delivery_id)
        if not delivery:
            delivery = self.delivery_history.get(delivery_id)
            if not delivery:
                return {'success': False, 'error': 'Delivery not found'}
        
        if delivery['customer_id'] != customer_id:
            return {'success': False, 'error': 'Unauthorized: Customer mismatch'}
        
        if delivery['payment_status'] == 'completed':
            return {'success': False, 'error': 'Payment already processed'}
        
        amount = delivery['amount']
        
        # Check sufficient balance
        if health_wallet_balance < amount:
            return {
                'success': False,
                'error': 'Insufficient wallet balance',
                'required': amount,
                'available': health_wallet_balance
            }
        
        now = datetime.now(timezone.utc)
        
        # Process payment via callback
        payment_tx = wallet_transaction_callback(
            customer_id=customer_id,
            amount=-amount,  # Debit
            transaction_type='delivery_payment',
            description=f"Delivery payment for {delivery_id}",
            metadata={
                'delivery_id': delivery_id,
                'supplier_id': delivery['supplier_id'],
                'order_id': delivery['order_id']
            }
        )
        
        # Update delivery payment status
        delivery['payment_status'] = 'completed'
        delivery['payment_date'] = now.isoformat()
        delivery['payment_transaction_id'] = payment_tx.get('transaction_id')
        
        # Update supplier metrics
        supplier_id = delivery['supplier_id']
        if supplier_id not in self.supplier_metrics:
            self.supplier_metrics[supplier_id] = {
                'total_deliveries': 0,
                'total_revenue': 0.0,
                'rating': 5.0,
                'reliability_score': 1.0,
                'on_time_percentage': 100.0
            }
        
        self.supplier_metrics[supplier_id]['total_deliveries'] += 1
        self.supplier_metrics[supplier_id]['total_revenue'] += amount
        
        logger.info(f"Delivery payment processed: {delivery_id} - ${amount:.2f} "
                   f"from customer {customer_id} to supplier {supplier_id}")
        
        return {
            'success': True,
            'delivery_id': delivery_id,
            'amount_paid': amount,
            'supplier_id': supplier_id,
            'payment_transaction_id': payment_tx.get('transaction_id'),
            'new_wallet_balance': health_wallet_balance - amount
        }
    
    def rate_delivery(
        self,
        delivery_id: str,
        rating: float,
        review: str = None,
        rated_by: str = None
    ) -> Dict[str, Any]:
        """
        Rate a completed delivery.
        
        Args:
            delivery_id: Delivery ID
            rating: Rating (1.0 to 5.0)
            review: Optional review text
            rated_by: Customer ID or supplier ID
            
        Returns:
            Rating result
        """
        delivery = self.delivery_history.get(delivery_id)
        if not delivery:
            delivery = self.active_deliveries.get(delivery_id)
        
        if not delivery:
            return {'success': False, 'error': 'Delivery not found'}
        
        if delivery['status'] not in ['delivered', 'completed']:
            return {'success': False, 'error': 'Delivery not yet completed'}
        
        # Validate rating
        rating = max(1.0, min(5.0, rating))
        
        now = datetime.now(timezone.utc)
        
        delivery['rating'] = rating
        delivery['review'] = review
        delivery['rated_at'] = now.isoformat()
        delivery['rated_by'] = rated_by
        
        # Update supplier metrics
        supplier_id = delivery['supplier_id']
        if supplier_id in self.supplier_metrics:
            metrics = self.supplier_metrics[supplier_id]
            # Running average of ratings
            total_deliveries = metrics['total_deliveries']
            current_rating = metrics['rating']
            new_rating = ((current_rating * (total_deliveries - 1)) + rating) / total_deliveries
            metrics['rating'] = round(new_rating, 2)
        
        logger.info(f"Delivery {delivery_id} rated: {rating:.1f}/5.0 by {rated_by}")
        
        return {
            'success': True,
            'delivery_id': delivery_id,
            'rating': rating,
            'supplier_new_rating': self.supplier_metrics.get(supplier_id, {}).get('rating', 0.0)
        }
    
    def get_delivery_status(
        self,
        delivery_id: str
    ) -> Dict[str, Any]:
        """Get current delivery status and tracking info"""
        delivery = self.active_deliveries.get(delivery_id)
        if not delivery:
            delivery = self.delivery_history.get(delivery_id)
        
        if not delivery:
            return {'success': False, 'error': 'Delivery not found'}
        
        return {
            'success': True,
            'delivery': delivery,
            'current_status': delivery['status'],
            'estimated_delivery': delivery.get('estimated_delivery_time'),
            'status_updates': delivery.get('status_updates', [])
        }
    
    def get_supplier_performance(
        self,
        supplier_id: str
    ) -> Dict[str, Any]:
        """Get supplier performance metrics"""
        metrics = self.supplier_metrics.get(supplier_id)
        if not metrics:
            return {
                'supplier_id': supplier_id,
                'total_deliveries': 0,
                'total_revenue': 0.0,
                'rating': 0.0,
                'reliability_score': 0.0,
                'status': 'No delivery history'
            }
        
        return {
            'supplier_id': supplier_id,
            **metrics,
            'status': 'Active' if metrics['total_deliveries'] > 0 else 'Inactive'
        }
    
    # ========== Private Helper Methods ==========
    
    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two coordinates using Haversine formula (km)"""
        if not all([lat1, lon1, lat2, lon2]):
            return 0.0
        
        R = 6371  # Earth radius in kilometers
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        distance = R * c
        return round(distance, 2)
    
    def _estimate_eligible_suppliers(self, location: Dict[str, Any]) -> int:
        """Estimate number of suppliers within service area"""
        # Simplified estimate based on location
        # In production, would query supplier database with location filter
        return len(self.supplier_metrics)
    
    def _rank_bid(self, bid: Dict[str, Any], request: Dict[str, Any]) -> int:
        """Calculate bid ranking (lower is better)"""
        # Simple ranking based on price
        all_bids = [self.delivery_bids[bid_id] for bid_id in request['bids'] 
                   if bid_id in self.delivery_bids]
        all_bids.sort(key=lambda x: x['bid_amount'])
        
        try:
            rank = all_bids.index(bid) + 1
        except ValueError:
            rank = len(all_bids) + 1
        
        return rank
    
    def _calculate_ai_bid_score(
        self,
        bid: Dict[str, Any],
        request: Dict[str, Any],
        all_bids: List[Dict[str, Any]]
    ) -> float:
        """
        Calculate AI score for bid evaluation.
        
        Weights:
        - Price: 40%
        - Supplier rating: 25%
        - Delivery time: 20%
        - Reliability: 15%
        
        Score range: 0.0 to 100.0 (higher is better)
        """
        # Price score (lower price = higher score)
        prices = [b['bid_amount'] for b in all_bids]
        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price if max_price > min_price else 1
        price_score = ((max_price - bid['bid_amount']) / price_range) * 40.0
        
        # Rating score (0-5 scale normalized to 0-25)
        rating_score = (bid.get('supplier_rating', 0.0) / 5.0) * 25.0
        
        # Delivery time score (faster = higher score)
        delivery_times = [b.get('delivery_duration_hours', 24) for b in all_bids]
        min_time = min(delivery_times)
        max_time = max(delivery_times)
        time_range = max_time - min_time if max_time > min_time else 1
        delivery_time = bid.get('delivery_duration_hours', 24)
        time_score = ((max_time - delivery_time) / time_range) * 20.0
        
        # Reliability score (0-1 scale normalized to 0-15)
        reliability_score = bid.get('supplier_reliability', 0.5) * 15.0
        
        total_score = price_score + rating_score + time_score + reliability_score
        
        return round(total_score, 2)
    
    def _generate_bid_recommendation(
        self,
        winning_bid: Dict[str, Any],
        request: Dict[str, Any]
    ) -> str:
        """Generate human-readable recommendation for bid"""
        supplier_id = winning_bid['supplier_id']
        amount = winning_bid['bid_amount']
        rating = winning_bid.get('supplier_rating', 0.0)
        ai_score = winning_bid.get('ai_score', 0.0)
        
        if ai_score >= 80:
            confidence = "strongly recommended"
        elif ai_score >= 60:
            confidence = "recommended"
        else:
            confidence = "acceptable option"
        
        return (f"Supplier {supplier_id} is {confidence} with an AI score of {ai_score:.1f}/100. "
                f"Bid amount: ${amount:.2f}, Supplier rating: {rating:.1f}/5.0")


# Singleton instance
_delivery_bidding_service: Optional[DeliveryBiddingService] = None


def get_delivery_bidding_service() -> DeliveryBiddingService:
    """Get or create delivery bidding service singleton"""
    global _delivery_bidding_service
    if _delivery_bidding_service is None:
        _delivery_bidding_service = DeliveryBiddingService()
    return _delivery_bidding_service
