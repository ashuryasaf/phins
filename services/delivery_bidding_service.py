"""
PHINS AI-Powered Delivery Bidding Service
==========================================
Location-based delivery system with competitive bidding for B2B healthcare marketplace.

Flow:
1. Customer purchases product using Health Wallet
2. Delivery preference uploaded to bidding pool
3. Delivery suppliers bid on delivery jobs
4. AI evaluates and ranks bids
5. Customer/system selects best bid
6. Deliverer fulfills order with real-time tracking
7. Pipeline refreshes with wallet transactions

Features:
- Location-based delivery matching
- AI-optimized bid ranking
- Real-time delivery tracking
- Wallet integration for payments
- Supplier performance scoring
- Route optimization suggestions
"""

import json
import math
import hashlib
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger('phins.delivery_bidding')


class DeliveryStatus(Enum):
    CREATED = "created"
    BIDDING_OPEN = "bidding_open"
    BID_SELECTED = "bid_selected"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BidStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class DeliveryPriority(Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    SAME_DAY = "same_day"
    URGENT = "urgent"
    MEDICAL_CRITICAL = "medical_critical"


@dataclass
class GeoLocation:
    latitude: float
    longitude: float
    address: str = ""
    city: str = ""
    state: str = ""
    country: str = "US"
    postal_code: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    def distance_to(self, other: 'GeoLocation') -> float:
        R = 6371
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return R * c


@dataclass
class DeliveryRequest:
    request_id: str
    order_id: str
    customer_id: str
    pickup_location: GeoLocation
    pickup_contact: Dict
    delivery_location: GeoLocation
    delivery_contact: Dict
    package_description: str
    package_weight_kg: float
    package_dimensions: Dict
    requires_signature: bool = True
    temperature_controlled: bool = False
    fragile: bool = False
    medical_item: bool = True
    priority: DeliveryPriority = DeliveryPriority.STANDARD
    earliest_pickup: Optional[str] = None
    latest_delivery: Optional[str] = None
    max_price: Optional[float] = None
    insurance_value: float = 0.0
    wallet_payment: bool = True
    status: DeliveryStatus = DeliveryStatus.CREATED
    selected_bid_id: Optional[str] = None
    assigned_supplier_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    bidding_ends_at: Optional[str] = None
    picked_up_at: Optional[str] = None
    delivered_at: Optional[str] = None
    nft_token_id: Optional[str] = None

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['pickup_location'] = self.pickup_location.to_dict()
        result['delivery_location'] = self.delivery_location.to_dict()
        result['priority'] = self.priority.value
        result['status'] = self.status.value
        return result


@dataclass
class DeliveryBid:
    bid_id: str
    request_id: str
    supplier_id: str
    supplier_name: str
    bid_price: float
    estimated_pickup_time: str
    estimated_delivery_time: str
    estimated_duration_hours: float
    vehicle_type: str
    currency: str = "USD"
    includes_insurance: bool = True
    temperature_controlled: bool = False
    has_medical_certification: bool = True
    supplier_rating: float = 4.5
    on_time_percentage: float = 95.0
    total_deliveries: int = 0
    status: BidStatus = BidStatus.PENDING
    ai_score: float = 0.0
    ai_ranking: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['status'] = self.status.value
        return result


@dataclass
class DeliveryTracking:
    tracking_id: str
    request_id: str
    timestamp: str
    status: DeliveryStatus
    location: Optional[GeoLocation]
    notes: str = ""
    updated_by: str = ""

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['status'] = self.status.value
        if self.location:
            result['location'] = self.location.to_dict()
        return result


class DeliveryBiddingService:
    """
    AI-powered delivery bidding service for B2B healthcare marketplace.

    Integrates with:
    - Health Wallets (payment source)
    - Supplier ecosystem (delivery providers)
    - AI optimization (bid evaluation)
    - Location services (distance calculation)
    """

    def __init__(self,
                 delivery_requests: Dict = None,
                 delivery_bids: Dict = None,
                 tracking_events: Dict = None,
                 suppliers: Dict = None,
                 health_wallets: Dict = None,
                 transaction_ledger: Dict = None,
                 nft_ledger: Dict = None,
                 record_transaction_func=None,
                 generate_nft_func=None):
        self.delivery_requests = delivery_requests if delivery_requests is not None else {}
        self.delivery_bids = delivery_bids if delivery_bids is not None else {}
        self.tracking_events = tracking_events if tracking_events is not None else {}
        self.suppliers = suppliers if suppliers is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self.nft_ledger = nft_ledger if nft_ledger is not None else {}
        self.record_transaction = record_transaction_func
        self.generate_nft = generate_nft_func

        self.DEFAULT_BIDDING_WINDOW_HOURS = 4
        self.MIN_BIDS_BEFORE_AUTO_SELECT = 3
        self.MAX_BIDS_PER_REQUEST = 10

        self.WEIGHT_PRICE = 0.30
        self.WEIGHT_TIME = 0.25
        self.WEIGHT_RATING = 0.25
        self.WEIGHT_RELIABILITY = 0.20

        self.supplier_metrics: Dict[str, Dict[str, Any]] = {}

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    # =========================================================================
    # DELIVERY REQUEST MANAGEMENT
    # =========================================================================

    def create_delivery_request(self,
                                order_id: str,
                                customer_id: str,
                                pickup_location: Dict,
                                delivery_location: Dict,
                                package_info: Dict,
                                priority: str = "standard",
                                max_price: float = None) -> Dict[str, Any]:
        request_id = self._generate_id("DEL")

        pickup_geo = GeoLocation(
            latitude=float(pickup_location.get('latitude', 0)),
            longitude=float(pickup_location.get('longitude', 0)),
            address=pickup_location.get('address', ''),
            city=pickup_location.get('city', ''),
            state=pickup_location.get('state', ''),
            country=pickup_location.get('country', 'US'),
            postal_code=pickup_location.get('postal_code', '')
        )

        delivery_geo = GeoLocation(
            latitude=float(delivery_location.get('latitude', 0)),
            longitude=float(delivery_location.get('longitude', 0)),
            address=delivery_location.get('address', ''),
            city=delivery_location.get('city', ''),
            state=delivery_location.get('state', ''),
            country=delivery_location.get('country', 'US'),
            postal_code=delivery_location.get('postal_code', '')
        )

        priority_enum = DeliveryPriority(priority.lower())
        delivery_windows = {
            DeliveryPriority.STANDARD: 120,
            DeliveryPriority.EXPRESS: 48,
            DeliveryPriority.SAME_DAY: 12,
            DeliveryPriority.URGENT: 4,
            DeliveryPriority.MEDICAL_CRITICAL: 2
        }

        now = datetime.now(timezone.utc)
        bidding_ends = now + timedelta(hours=self.DEFAULT_BIDDING_WINDOW_HOURS)
        latest_delivery = now + timedelta(hours=delivery_windows.get(priority_enum, 120))

        distance_km = pickup_geo.distance_to(delivery_geo)
        if max_price is None:
            priority_multipliers = {
                DeliveryPriority.STANDARD: 1.0,
                DeliveryPriority.EXPRESS: 1.5,
                DeliveryPriority.SAME_DAY: 2.0,
                DeliveryPriority.URGENT: 3.0,
                DeliveryPriority.MEDICAL_CRITICAL: 4.0
            }
            max_price = round(5 + (distance_km * 1.50) * priority_multipliers.get(priority_enum, 1.0), 2)

        request = DeliveryRequest(
            request_id=request_id,
            order_id=order_id,
            customer_id=customer_id,
            pickup_location=pickup_geo,
            pickup_contact=pickup_location.get('contact', {}),
            delivery_location=delivery_geo,
            delivery_contact=delivery_location.get('contact', {}),
            package_description=package_info.get('description', ''),
            package_weight_kg=float(package_info.get('weight_kg', 1.0)),
            package_dimensions=package_info.get('dimensions', {'length': 30, 'width': 20, 'height': 15}),
            requires_signature=package_info.get('requires_signature', True),
            temperature_controlled=package_info.get('temperature_controlled', False),
            fragile=package_info.get('fragile', False),
            medical_item=package_info.get('medical_item', True),
            priority=priority_enum,
            latest_delivery=latest_delivery.isoformat(),
            max_price=max_price,
            insurance_value=package_info.get('insurance_value', 0),
            wallet_payment=True,
            status=DeliveryStatus.BIDDING_OPEN,
            bidding_ends_at=bidding_ends.isoformat()
        )

        self.delivery_requests[request_id] = request

        self._add_tracking_event(request_id, DeliveryStatus.BIDDING_OPEN, None,
                                 "Delivery request created, open for bidding", "system")

        eligible_suppliers = self._find_eligible_suppliers(request)

        return {
            'success': True,
            'request_id': request_id,
            'status': 'bidding_open',
            'distance_km': round(distance_km, 2),
            'max_price': max_price,
            'bidding_ends_at': bidding_ends.isoformat(),
            'latest_delivery': latest_delivery.isoformat(),
            'eligible_suppliers_count': len(eligible_suppliers),
            'request': request.to_dict()
        }

    def _find_eligible_suppliers(self, request: DeliveryRequest) -> List[Dict]:
        eligible = []
        for supplier_id, supplier in self.suppliers.items():
            if supplier.get('status') != 'approved':
                continue
            if supplier.get('supplier_type') != 'delivery':
                continue

            service_areas = supplier.get('service_areas', [])
            if isinstance(service_areas, str):
                try:
                    service_areas = json.loads(service_areas)
                except Exception:
                    service_areas = []

            if service_areas:
                delivery_city = request.delivery_location.city.lower()
                delivery_state = request.delivery_location.state.lower()
                is_covered = any(
                    delivery_city in str(area).lower() or
                    delivery_state in str(area).lower() or
                    'nationwide' in str(area).lower()
                    for area in service_areas
                )
                if not is_covered:
                    continue

            eligible.append({
                'supplier_id': supplier_id,
                'company_name': supplier.get('company_name'),
                'rating': supplier.get('average_rating', 4.0),
                'total_orders': supplier.get('total_orders', 0)
            })

        return eligible

    # =========================================================================
    # BIDDING SYSTEM
    # =========================================================================

    def submit_bid(self,
                   request_id: str,
                   supplier_id: str,
                   bid_price: float,
                   estimated_pickup_time: str,
                   estimated_delivery_time: str,
                   vehicle_type: str = "van",
                   includes_insurance: bool = True,
                   notes: str = "") -> Dict[str, Any]:
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Delivery request not found'}

        request = self.delivery_requests[request_id]

        if request.status != DeliveryStatus.BIDDING_OPEN:
            return {'success': False, 'error': f'Bidding is closed. Status: {request.status.value}'}

        if request.bidding_ends_at:
            deadline = datetime.fromisoformat(request.bidding_ends_at.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > deadline:
                return {'success': False, 'error': 'Bidding deadline has passed'}

        if request.max_price and bid_price > request.max_price:
            return {'success': False, 'error': f'Bid exceeds maximum price of ${request.max_price}'}

        existing_bids = [b for b in self.delivery_bids.values()
                         if b.request_id == request_id and b.supplier_id == supplier_id]
        if existing_bids:
            return {'success': False, 'error': 'You have already submitted a bid'}

        current_bids = [b for b in self.delivery_bids.values() if b.request_id == request_id]
        if len(current_bids) >= self.MAX_BIDS_PER_REQUEST:
            return {'success': False, 'error': 'Maximum bids reached for this request'}

        supplier = self.suppliers.get(supplier_id, {})

        try:
            pickup_dt = datetime.fromisoformat(estimated_pickup_time.replace('Z', '+00:00'))
            delivery_dt = datetime.fromisoformat(estimated_delivery_time.replace('Z', '+00:00'))
            duration_hours = (delivery_dt - pickup_dt).total_seconds() / 3600
        except Exception:
            duration_hours = 24.0

        bid_id = self._generate_id("BID")

        bid = DeliveryBid(
            bid_id=bid_id,
            request_id=request_id,
            supplier_id=supplier_id,
            supplier_name=supplier.get('company_name', 'Unknown'),
            bid_price=bid_price,
            includes_insurance=includes_insurance,
            estimated_pickup_time=estimated_pickup_time,
            estimated_delivery_time=estimated_delivery_time,
            estimated_duration_hours=duration_hours,
            vehicle_type=vehicle_type,
            temperature_controlled=supplier.get('temperature_controlled', False),
            has_medical_certification=True,
            supplier_rating=supplier.get('average_rating', 4.0),
            on_time_percentage=supplier.get('on_time_rate', 95.0),
            total_deliveries=supplier.get('total_orders', 0),
            status=BidStatus.PENDING,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        )

        bid.ai_score = self._calculate_bid_score(bid, request)
        self.delivery_bids[bid_id] = bid
        self._rank_bids(request_id)

        return {
            'success': True,
            'bid_id': bid_id,
            'ai_score': round(bid.ai_score, 2),
            'ranking': bid.ai_ranking,
            'bid': bid.to_dict()
        }

    def _calculate_bid_score(self, bid: DeliveryBid, request: DeliveryRequest) -> float:
        if request.max_price and request.max_price > 0:
            price_score = 1 - (bid.bid_price / request.max_price)
        else:
            price_score = 0.5
        price_score = max(0, min(1, price_score))

        priority_hours = {
            DeliveryPriority.STANDARD: 120,
            DeliveryPriority.EXPRESS: 48,
            DeliveryPriority.SAME_DAY: 12,
            DeliveryPriority.URGENT: 4,
            DeliveryPriority.MEDICAL_CRITICAL: 2
        }
        max_hours = priority_hours.get(request.priority, 120)
        time_score = 1 - (bid.estimated_duration_hours / max_hours)
        time_score = max(0, min(1, time_score))

        rating_score = bid.supplier_rating / 5.0
        reliability_score = bid.on_time_percentage / 100.0

        total_score = (
            self.WEIGHT_PRICE * price_score +
            self.WEIGHT_TIME * time_score +
            self.WEIGHT_RATING * rating_score +
            self.WEIGHT_RELIABILITY * reliability_score
        )

        if request.medical_item and bid.has_medical_certification:
            total_score += 0.05
        if bid.includes_insurance:
            total_score += 0.02

        return min(1.0, total_score) * 100

    def _rank_bids(self, request_id: str):
        request_bids = [b for b in self.delivery_bids.values()
                        if b.request_id == request_id and b.status == BidStatus.PENDING]
        request_bids.sort(key=lambda x: x.ai_score, reverse=True)
        for rank, bid in enumerate(request_bids, 1):
            bid.ai_ranking = rank

    def get_bids_for_request(self, request_id: str) -> Dict[str, Any]:
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Request not found'}

        request = self.delivery_requests[request_id]
        bids = [b for b in self.delivery_bids.values() if b.request_id == request_id]
        bids.sort(key=lambda x: x.ai_ranking if x.ai_ranking > 0 else 999)

        return {
            'success': True,
            'request_id': request_id,
            'request_status': request.status.value,
            'total_bids': len(bids),
            'bidding_ends_at': request.bidding_ends_at,
            'ai_recommended': bids[0].to_dict() if bids else None,
            'bids': [b.to_dict() for b in bids]
        }

    def select_bid(self, request_id: str, bid_id: str, selected_by: str = "customer") -> Dict[str, Any]:
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Request not found'}
        if bid_id not in self.delivery_bids:
            return {'success': False, 'error': 'Bid not found'}

        request = self.delivery_requests[request_id]
        bid = self.delivery_bids[bid_id]

        if bid.request_id != request_id:
            return {'success': False, 'error': 'Bid does not belong to this request'}
        if request.status != DeliveryStatus.BIDDING_OPEN:
            return {'success': False, 'error': f'Cannot select bid. Status: {request.status.value}'}

        wallet = None
        if request.wallet_payment:
            wallet = self.health_wallets.get(request.customer_id)
            if not wallet:
                return {'success': False, 'error': 'Customer health wallet not found'}

            current_balance = float(wallet.get('balance', 0))
            if current_balance < bid.bid_price:
                return {'success': False, 'error': f'Insufficient wallet balance. Required: ${bid.bid_price}, Available: ${current_balance}'}

            wallet['balance'] = current_balance - bid.bid_price
            wallet.setdefault('transactions', []).append({
                'id': f"DEL-PAY-{bid_id}",
                'type': 'delivery_payment',
                'amount': -bid.bid_price,
                'description': f'Delivery payment to {bid.supplier_name}',
                'delivery_request_id': request_id,
                'bid_id': bid_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

            if self.record_transaction:
                self.record_transaction(
                    customer_id=request.customer_id,
                    tx_type='delivery_payment',
                    amount=bid.bid_price,
                    description=f'Delivery payment for order {request.order_id}',
                    metadata={
                        'request_id': request_id,
                        'bid_id': bid_id,
                        'supplier_id': bid.supplier_id,
                        'supplier_name': bid.supplier_name
                    }
                )

        bid.status = BidStatus.ACCEPTED

        for other_bid in self.delivery_bids.values():
            if other_bid.request_id == request_id and other_bid.bid_id != bid_id:
                other_bid.status = BidStatus.REJECTED

        request.status = DeliveryStatus.BID_SELECTED
        request.selected_bid_id = bid_id
        request.assigned_supplier_id = bid.supplier_id

        if self.generate_nft:
            nft_token = self.generate_nft(
                owner_id=request.customer_id,
                asset_type='delivery_contract',
                asset_id=request_id,
                metadata={
                    'order_id': request.order_id,
                    'bid_id': bid_id,
                    'supplier_id': bid.supplier_id,
                    'price': bid.bid_price,
                    'estimated_delivery': bid.estimated_delivery_time
                }
            )
            request.nft_token_id = nft_token.get('token_id')

        self._add_tracking_event(
            request_id, DeliveryStatus.BID_SELECTED, None,
            f'Bid selected: {bid.supplier_name} for ${bid.bid_price}',
            selected_by
        )

        return {
            'success': True,
            'request_id': request_id,
            'bid_id': bid_id,
            'supplier_id': bid.supplier_id,
            'supplier_name': bid.supplier_name,
            'price_paid': bid.bid_price,
            'new_wallet_balance': wallet['balance'] if wallet else None,
            'estimated_delivery': bid.estimated_delivery_time,
            'nft_token_id': request.nft_token_id,
            'status': 'bid_selected'
        }

    def auto_select_best_bid(self, request_id: str) -> Dict[str, Any]:
        bids_result = self.get_bids_for_request(request_id)
        if not bids_result['success']:
            return bids_result
        if not bids_result['ai_recommended']:
            return {'success': False, 'error': 'No bids to select from'}

        best_bid_id = bids_result['ai_recommended']['bid_id']
        return self.select_bid(request_id, best_bid_id, selected_by='ai_system')

    # =========================================================================
    # DELIVERY TRACKING
    # =========================================================================

    def _add_tracking_event(self, request_id: str, status: DeliveryStatus,
                            location: Optional[GeoLocation], notes: str, updated_by: str):
        tracking_id = self._generate_id("TRK")
        event = DeliveryTracking(
            tracking_id=tracking_id,
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
            location=location,
            notes=notes,
            updated_by=updated_by
        )
        self.tracking_events[tracking_id] = event

    def update_delivery_status(self, request_id: str, new_status: str,
                               supplier_id: str, location: Dict = None,
                               notes: str = "") -> Dict[str, Any]:
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Request not found'}

        request = self.delivery_requests[request_id]

        if request.assigned_supplier_id != supplier_id:
            return {'success': False, 'error': 'Not authorized to update this delivery'}

        try:
            status_enum = DeliveryStatus(new_status.lower())
        except ValueError:
            return {'success': False, 'error': f'Invalid status: {new_status}'}

        geo_location = None
        if location:
            geo_location = GeoLocation(
                latitude=float(location.get('latitude', 0)),
                longitude=float(location.get('longitude', 0)),
                address=location.get('address', '')
            )

        old_status = request.status
        request.status = status_enum

        if status_enum == DeliveryStatus.PICKED_UP:
            request.picked_up_at = datetime.now(timezone.utc).isoformat()
        elif status_enum in [DeliveryStatus.DELIVERED, DeliveryStatus.CONFIRMED]:
            request.delivered_at = datetime.now(timezone.utc).isoformat()

        self._add_tracking_event(request_id, status_enum, geo_location, notes, supplier_id)

        if status_enum == DeliveryStatus.DELIVERED:
            self._process_supplier_payment(request)

        return {
            'success': True,
            'request_id': request_id,
            'old_status': old_status.value,
            'new_status': status_enum.value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

    def _process_supplier_payment(self, request: DeliveryRequest):
        if not request.selected_bid_id:
            return
        bid = self.delivery_bids.get(request.selected_bid_id)
        if not bid:
            return
        supplier = self.suppliers.get(bid.supplier_id)
        if supplier:
            supplier['total_orders'] = supplier.get('total_orders', 0) + 1
            supplier['total_revenue'] = supplier.get('total_revenue', 0) + bid.bid_price

    def get_delivery_tracking(self, request_id: str) -> Dict[str, Any]:
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Request not found'}

        request = self.delivery_requests[request_id]
        events = [e for e in self.tracking_events.values() if e.request_id == request_id]
        events.sort(key=lambda x: x.timestamp)

        return {
            'success': True,
            'request_id': request_id,
            'current_status': request.status.value,
            'tracking_events': [e.to_dict() for e in events],
            'total_events': len(events),
            'nft_token_id': request.nft_token_id
        }

    # =========================================================================
    # ANALYTICS & BI
    # =========================================================================

    def get_delivery_analytics(self, supplier_id: str = None) -> Dict[str, Any]:
        requests = list(self.delivery_requests.values())
        bids = list(self.delivery_bids.values())

        if supplier_id:
            supplier_bids = [b for b in bids if b.supplier_id == supplier_id]
            supplier_requests = [r for r in requests if r.assigned_supplier_id == supplier_id]
            accepted = [b for b in supplier_bids if b.status == BidStatus.ACCEPTED]

            return {
                'supplier_id': supplier_id,
                'total_bids_submitted': len(supplier_bids),
                'bids_accepted': len(accepted),
                'bids_rejected': len([b for b in supplier_bids if b.status == BidStatus.REJECTED]),
                'acceptance_rate': len(accepted) / len(supplier_bids) * 100 if supplier_bids else 0,
                'total_deliveries': len(supplier_requests),
                'completed_deliveries': len([r for r in supplier_requests if r.status in [DeliveryStatus.DELIVERED, DeliveryStatus.CONFIRMED]]),
                'average_bid_score': sum(b.ai_score for b in supplier_bids) / len(supplier_bids) if supplier_bids else 0,
                'total_revenue': sum(b.bid_price for b in accepted)
            }
        else:
            selected = [r for r in requests if r.selected_bid_id]
            selected_prices = []
            for r in selected:
                bid = self.delivery_bids.get(r.selected_bid_id)
                if bid:
                    selected_prices.append(bid.bid_price)

            return {
                'total_delivery_requests': len(requests),
                'open_requests': len([r for r in requests if r.status == DeliveryStatus.BIDDING_OPEN]),
                'in_progress': len([r for r in requests if r.status in [DeliveryStatus.BID_SELECTED, DeliveryStatus.PICKED_UP, DeliveryStatus.IN_TRANSIT, DeliveryStatus.OUT_FOR_DELIVERY]]),
                'completed': len([r for r in requests if r.status in [DeliveryStatus.DELIVERED, DeliveryStatus.CONFIRMED]]),
                'cancelled': len([r for r in requests if r.status == DeliveryStatus.CANCELLED]),
                'total_bids': len(bids),
                'average_bids_per_request': len(bids) / len(requests) if requests else 0,
                'average_winning_bid': sum(selected_prices) / len(selected_prices) if selected_prices else 0,
                'by_priority': {
                    p.value: len([r for r in requests if r.priority == p])
                    for p in DeliveryPriority
                },
                'by_status': {
                    s.value: len([r for r in requests if r.status == s])
                    for s in DeliveryStatus
                }
            }

    def get_ai_delivery_insights(self) -> Dict[str, Any]:
        requests = list(self.delivery_requests.values())
        bids = list(self.delivery_bids.values())

        insights = {
            'recommendations': [],
            'alerts': [],
            'optimizations': []
        }

        open_no_bids = [r for r in requests
                        if r.status == DeliveryStatus.BIDDING_OPEN and
                        not any(b.request_id == r.request_id for b in bids)]
        if open_no_bids:
            insights['alerts'].append({
                'type': 'no_bids',
                'count': len(open_no_bids),
                'message': f'{len(open_no_bids)} delivery requests have no bids yet. Consider expanding supplier network.'
            })

        supplier_stats = {}
        for bid in bids:
            if bid.supplier_id not in supplier_stats:
                supplier_stats[bid.supplier_id] = {'total': 0, 'accepted': 0}
            supplier_stats[bid.supplier_id]['total'] += 1
            if bid.status == BidStatus.ACCEPTED:
                supplier_stats[bid.supplier_id]['accepted'] += 1

        low_performers = [
            sid for sid, stats in supplier_stats.items()
            if stats['total'] >= 5 and (stats['accepted'] / stats['total']) < 0.2
        ]
        if low_performers:
            insights['recommendations'].append({
                'type': 'low_acceptance_suppliers',
                'count': len(low_performers),
                'message': f'{len(low_performers)} suppliers have <20% bid acceptance rate. Recommend price optimization training.'
            })

        avg_bid_prices = {}
        for bid in bids:
            request = self.delivery_requests.get(bid.request_id)
            if request:
                prio = request.priority.value
                if prio not in avg_bid_prices:
                    avg_bid_prices[prio] = []
                avg_bid_prices[prio].append(bid.bid_price)

        for prio, prices in avg_bid_prices.items():
            if len(prices) >= 3:
                avg = sum(prices) / len(prices)
                insights['optimizations'].append({
                    'priority': prio,
                    'average_bid_price': round(avg, 2),
                    'bid_count': len(prices),
                    'suggested_max_price': round(avg * 1.1, 2)
                })

        return insights


# Singleton instances
_delivery_service: Optional[DeliveryBiddingService] = None


def get_delivery_bidding_service(**kwargs) -> DeliveryBiddingService:
    global _delivery_service
    if _delivery_service is None:
        _delivery_service = DeliveryBiddingService(**kwargs)
    return _delivery_service


def init_delivery_bidding_service(**kwargs) -> DeliveryBiddingService:
    global _delivery_service
    _delivery_service = DeliveryBiddingService(**kwargs)
    return _delivery_service
