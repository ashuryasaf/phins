"""
PHINS Delivery Bidding Service
Location-aware, supplier bidding workflow for delivery fulfillment.

Flow:
1) Customer creates delivery request (with preferences + location)
2) Approved delivery suppliers submit bids
3) Customer awards bid -> wallet reservation (optional)
4) Supplier accepts and delivers
5) Wallet is charged, ledger + transaction trail updated
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
import json
import math
import secrets
import statistics


REQUEST_STATUSES = {
    "open",
    "bidding",
    "awarded",
    "accepted",
    "in_transit",
    "delivered",
    "cancelled",
    "pending_suppliers",
}

BID_STATUSES = {
    "submitted",
    "awarded",
    "accepted",
    "completed",
    "rejected",
    "withdrawn",
}


def _generate_id(prefix: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{prefix}-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))
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
PHINS AI-Powered Delivery Bidding Service
Location-based delivery system with competitive bidding for B2B healthcare:

Flow:
1. Customer purchases product using Health Wallet
2. Delivery preference uploaded to bidding pool
3. Delivery suppliers bid on delivery jobs
4. Customer/system selects best bid
5. Deliverer fulfills order
6. Pipeline refreshes with wallet transactions

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
import random
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


class DeliveryStatus(Enum):
    """Delivery lifecycle status"""
    CREATED = "created"                    # Order created, awaiting bids
    BIDDING_OPEN = "bidding_open"          # Open for delivery bids
    BID_SELECTED = "bid_selected"          # Bid selected, awaiting pickup
    PICKED_UP = "picked_up"                # Package picked up
    IN_TRANSIT = "in_transit"              # En route to destination
    OUT_FOR_DELIVERY = "out_for_delivery"  # Final delivery leg
    DELIVERED = "delivered"                # Successfully delivered
    CONFIRMED = "confirmed"                # Customer confirmed receipt
    CANCELLED = "cancelled"                # Delivery cancelled
    FAILED = "failed"                      # Delivery failed


class BidStatus(Enum):
    """Bid status"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class DeliveryPriority(Enum):
    """Delivery priority levels"""
    STANDARD = "standard"        # 3-5 days
    EXPRESS = "express"          # 1-2 days
    SAME_DAY = "same_day"        # Same day
    URGENT = "urgent"            # Within hours
    MEDICAL_CRITICAL = "medical_critical"  # Immediate


@dataclass
class GeoLocation:
    """Geographic location"""
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
        """Calculate distance in km using Haversine formula"""
        R = 6371  # Earth's radius in km
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c


@dataclass
class DeliveryRequest:
    request_id: str
    customer_id: str
    order_id: Optional[str] = None
    status: str = "open"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    location: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    max_bid_amount: Optional[float] = None
    currency: str = "USD"
    payment_method: str = "health_wallet"
    eligible_suppliers: List[str] = field(default_factory=list)
    bids: List[str] = field(default_factory=list)
    awarded_bid_id: Optional[str] = None
    accepted_bid_id: Optional[str] = None
    reserved_amount: float = 0.0
    delivered_at: Optional[str] = None
    cancellation_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    """Delivery request from marketplace order"""
    request_id: str
    order_id: str
    customer_id: str
    
    # Origin (pickup)
    pickup_location: GeoLocation
    pickup_contact: Dict  # name, phone, instructions
    
    # Destination
    delivery_location: GeoLocation
    delivery_contact: Dict  # name, phone, instructions
    
    # Package details
    package_description: str
    package_weight_kg: float
    package_dimensions: Dict  # length, width, height in cm
    requires_signature: bool = True
    temperature_controlled: bool = False
    fragile: bool = False
    medical_item: bool = True
    
    # Priority and timing
    priority: DeliveryPriority = DeliveryPriority.STANDARD
    earliest_pickup: Optional[str] = None  # ISO datetime
    latest_delivery: Optional[str] = None  # ISO datetime
    
    # Pricing
    max_price: Optional[float] = None  # Customer's max acceptable price
    insurance_value: float = 0.0
    wallet_payment: bool = True  # Pay from health wallet
    
    # Status
    status: DeliveryStatus = DeliveryStatus.CREATED
    selected_bid_id: Optional[str] = None
    assigned_supplier_id: Optional[str] = None
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    bidding_ends_at: Optional[str] = None
    picked_up_at: Optional[str] = None
    delivered_at: Optional[str] = None
    
    # NFT tracking
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
    amount: float
    eta_minutes: int
    notes: str = ""
    status: str = "submitted"
    ai_score: float = 0.0
    ai_recommendation: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    over_budget: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    """Bid from a delivery supplier"""
    # Required fields (no defaults) must come first
    bid_id: str
    request_id: str
    supplier_id: str
    supplier_name: str
    bid_price: float
    estimated_pickup_time: str  # ISO datetime
    estimated_delivery_time: str  # ISO datetime
    estimated_duration_hours: float
    vehicle_type: str  # car, van, truck, motorcycle, drone
    
    # Optional fields with defaults
    currency: str = "USD"
    includes_insurance: bool = True
    temperature_controlled: bool = False
    has_medical_certification: bool = True
    
    # Supplier metrics (for AI ranking)
    supplier_rating: float = 4.5
    on_time_percentage: float = 95.0
    total_deliveries: int = 0
    
    # Status
    status: BidStatus = BidStatus.PENDING
    
    # AI score (calculated)
    ai_score: float = 0.0
    ai_ranking: int = 0
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['status'] = self.status.value
        return result


@dataclass
class DeliveryTracking:
    """Real-time delivery tracking record"""
    tracking_id: str
    request_id: str
    timestamp: str
    status: DeliveryStatus
    location: Optional[GeoLocation]
    notes: str = ""
    updated_by: str = ""  # supplier_id or system
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['status'] = self.status.value
        if self.location:
            result['location'] = self.location.to_dict()
        return result


class DeliveryBiddingService:
    """
    Delivery bidding orchestration with wallet reservation + ledger tracking.
    """

    def __init__(
        self,
        requests_store: Dict[str, Dict[str, Any]] = None,
        bids_store: Dict[str, Dict[str, Any]] = None,
        suppliers_store: Dict[str, Dict[str, Any]] = None,
        health_wallets: Dict[str, Dict[str, Any]] = None,
        transaction_ledger: Dict[str, Dict[str, Any]] = None,
        supply_chain_service=None,
        record_transaction_func: Optional[Callable[..., Dict[str, Any]]] = None,
    ):
        self.requests = requests_store if requests_store is not None else {}
        self.bids = bids_store if bids_store is not None else {}
        self.suppliers = suppliers_store if suppliers_store is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self.supply_chain_service = supply_chain_service
        self.record_transaction = record_transaction_func

    # ---------------------------------------------------------------------
    # Request lifecycle
    # ---------------------------------------------------------------------
    def create_request(
        self,
        customer_id: str,
        order_id: Optional[str] = None,
        preferences: Optional[Dict[str, Any]] = None,
        location: Optional[Dict[str, Any]] = None,
        max_bid_amount: Optional[float] = None,
        payment_method: str = "health_wallet",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        if not customer_id:
            raise ValueError("customer_id is required")

        request_id = _generate_id("DLR")
        eligible_suppliers = self._eligible_suppliers(location or {})
        status = "bidding" if eligible_suppliers else "pending_suppliers"

        request = DeliveryRequest(
            request_id=request_id,
            customer_id=customer_id,
            order_id=order_id,
            status=status,
            location=location or {},
            preferences=preferences or {},
            max_bid_amount=_safe_float(max_bid_amount, None) if max_bid_amount is not None else None,
            currency=currency or "USD",
            payment_method=payment_method or "health_wallet",
            eligible_suppliers=eligible_suppliers,
        )

        self.requests[request_id] = request.to_dict()
        self._record_delivery_event(
            event_type="delivery_request_created",
            customer_id=customer_id,
            supplier_id="SYSTEM",
            request_id=request_id,
            amount=request.max_bid_amount or 0.0,
            metadata={
                "order_id": order_id,
                "eligible_suppliers": len(eligible_suppliers),
                "payment_method": request.payment_method,
            },
        )
        return request.to_dict()

    def list_requests(
        self,
        customer_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        requests = list(self.requests.values())

        if customer_id:
            requests = [r for r in requests if r.get("customer_id") == customer_id]

        if supplier_id:
            filtered = []
            for r in requests:
                eligible = supplier_id in (r.get("eligible_suppliers") or [])
                awarded_bid = r.get("awarded_bid_id")
                accepted_bid = r.get("accepted_bid_id")
                supplier_bids = [
                    bid_id for bid_id in (r.get("bids") or [])
                    if self.bids.get(bid_id, {}).get("supplier_id") == supplier_id
                ]
                if eligible or awarded_bid in supplier_bids or accepted_bid in supplier_bids:
                    filtered.append(r)
            requests = filtered

        if status:
            requests = [r for r in requests if r.get("status") == status]

        requests.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return requests[:limit]

    def cancel_request(self, request_id: str, reason: str = "") -> Dict[str, Any]:
        request = self._get_request(request_id)
        if request.get("status") in ["delivered", "cancelled"]:
            raise ValueError("Request already closed")

        request["status"] = "cancelled"
        request["updated_at"] = _now_iso()
        request["cancellation_reason"] = reason or "cancelled"

        if request.get("reserved_amount"):
            self._release_wallet_reservation(
                customer_id=request["customer_id"],
                request_id=request_id,
                amount=_safe_float(request.get("reserved_amount"), 0.0),
            )
            request["reserved_amount"] = 0.0

        self._record_delivery_event(
            event_type="delivery_request_cancelled",
            customer_id=request["customer_id"],
            supplier_id="SYSTEM",
            request_id=request_id,
            amount=0.0,
            metadata={"reason": reason},
        )
        return request

    # ---------------------------------------------------------------------
    # Bidding workflow
    # ---------------------------------------------------------------------
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
    AI-powered delivery bidding service for B2B healthcare marketplace.
    
    Features:
    - Location-based job matching
    - Competitive bidding with AI ranking
    - Wallet integration for seamless payments
    - Real-time tracking
    - Performance analytics
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
        """Initialize with data stores"""
        self.delivery_requests = delivery_requests if delivery_requests is not None else {}
        self.delivery_bids = delivery_bids if delivery_bids is not None else {}
        self.tracking_events = tracking_events if tracking_events is not None else {}
        self.suppliers = suppliers if suppliers is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self.nft_ledger = nft_ledger if nft_ledger is not None else {}
        self.record_transaction = record_transaction_func
        self.generate_nft = generate_nft_func
        
        # Bidding configuration
        self.DEFAULT_BIDDING_WINDOW_HOURS = 4
        self.MIN_BIDS_BEFORE_AUTO_SELECT = 3
        self.MAX_BIDS_PER_REQUEST = 10
        
        # AI scoring weights
        self.WEIGHT_PRICE = 0.30
        self.WEIGHT_TIME = 0.25
        self.WEIGHT_RATING = 0.25
        self.WEIGHT_RELIABILITY = 0.20
    
    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID"""
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
        """
        Create a delivery request from a marketplace order.
        
        This is triggered when a customer purchases a product that needs delivery.
        """
        request_id = self._generate_id("DEL")
        
        # Parse locations
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
        
        # Calculate delivery window based on priority
        priority_enum = DeliveryPriority(priority.lower())
        delivery_windows = {
            DeliveryPriority.STANDARD: 120,  # 5 days in hours
            DeliveryPriority.EXPRESS: 48,
            DeliveryPriority.SAME_DAY: 12,
            DeliveryPriority.URGENT: 4,
            DeliveryPriority.MEDICAL_CRITICAL: 2
        }
        
        now = datetime.now(timezone.utc)
        bidding_ends = now + timedelta(hours=self.DEFAULT_BIDDING_WINDOW_HOURS)
        latest_delivery = now + timedelta(hours=delivery_windows.get(priority_enum, 120))
        
        # Calculate estimated max price based on distance if not provided
        distance_km = pickup_geo.distance_to(delivery_geo)
        if max_price is None:
            # Base pricing: $5 base + $1.50 per km + priority multiplier
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
        
        # Store request
        self.delivery_requests[request_id] = request
        
        # Add initial tracking event
        self._add_tracking_event(request_id, DeliveryStatus.BIDDING_OPEN, None, 
                                "Delivery request created, open for bidding", "system")
        
        # Notify eligible delivery suppliers (AI-matched)
        eligible_suppliers = self._find_eligible_suppliers(request)
        
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
        amount: float,
        eta_minutes: int,
        notes: str = "",
    ) -> Dict[str, Any]:
        request = self._get_request(request_id)
        if request.get("status") in ["delivered", "cancelled"]:
            raise ValueError("Request is closed")

        supplier = self._get_supplier(supplier_id)
        if not supplier:
            raise ValueError("Supplier not found")

        if supplier_id not in (request.get("eligible_suppliers") or []):
            raise ValueError("Supplier not eligible for this request")

        bid_amount = _safe_float(amount)
        if bid_amount <= 0:
            raise ValueError("Bid amount must be greater than 0")

        eta = _safe_int(eta_minutes)
        if eta <= 0:
            raise ValueError("ETA must be a positive number of minutes")

        max_bid = request.get("max_bid_amount")
        over_budget = max_bid is not None and bid_amount > _safe_float(max_bid, 0.0)

        bid_id = _generate_id("DLB")
        ai_score, ai_recommendation = self._score_bid(request, supplier, bid_amount, eta)

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
            'status': 'bidding_open',
            'distance_km': round(distance_km, 2),
            'max_price': max_price,
            'bidding_ends_at': bidding_ends.isoformat(),
            'latest_delivery': latest_delivery.isoformat(),
            'eligible_suppliers_count': len(eligible_suppliers),
            'request': request.to_dict()
        }
    
    def _find_eligible_suppliers(self, request: DeliveryRequest) -> List[Dict]:
        """Find delivery suppliers eligible for this request"""
        eligible = []
        
        for supplier_id, supplier in self.suppliers.items():
            # Only approved delivery suppliers
            if supplier.get('status') != 'approved':
                continue
            if supplier.get('supplier_type') != 'delivery':
                continue
            
            # Check service areas (if defined)
            service_areas = supplier.get('service_areas', [])
            if isinstance(service_areas, str):
                try:
                    service_areas = json.loads(service_areas)
                except:
                    service_areas = []
            
            # If service areas defined, check if delivery location is covered
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
            
            # Check medical certification if needed
            if request.medical_item:
                certifications = supplier.get('certifications', [])
                if isinstance(certifications, str):
                    try:
                        certifications = json.loads(certifications)
                    except:
                        certifications = []
                # For now, assume all delivery suppliers can handle medical items
            
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
        """
        Submit a delivery bid from a supplier.
        """
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Delivery request not found'}
        
        request = self.delivery_requests[request_id]
        
        # Check bidding is still open
        if request.status != DeliveryStatus.BIDDING_OPEN:
            return {'success': False, 'error': f'Bidding is closed. Status: {request.status.value}'}
        
        # Check bidding deadline
        if request.bidding_ends_at:
            deadline = datetime.fromisoformat(request.bidding_ends_at.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > deadline:
                return {'success': False, 'error': 'Bidding deadline has passed'}
        
        # Check max price constraint
        if request.max_price and bid_price > request.max_price:
            return {'success': False, 'error': f'Bid exceeds maximum price of ${request.max_price}'}
        
        # Check supplier hasn't already bid
        existing_bids = [b for b in self.delivery_bids.values() 
                        if b.request_id == request_id and b.supplier_id == supplier_id]
        if existing_bids:
            return {'success': False, 'error': 'You have already submitted a bid'}
        
        # Check max bids not exceeded
        current_bids = [b for b in self.delivery_bids.values() if b.request_id == request_id]
        if len(current_bids) >= self.MAX_BIDS_PER_REQUEST:
            return {'success': False, 'error': 'Maximum bids reached for this request'}
        
        # Get supplier info
        supplier = self.suppliers.get(supplier_id, {})
        
        # Calculate estimated duration
        try:
            pickup_dt = datetime.fromisoformat(estimated_pickup_time.replace('Z', '+00:00'))
            delivery_dt = datetime.fromisoformat(estimated_delivery_time.replace('Z', '+00:00'))
            duration_hours = (delivery_dt - pickup_dt).total_seconds() / 3600
        except:
            duration_hours = 24.0
        
        bid_id = self._generate_id("BID")
        
        bid = DeliveryBid(
            bid_id=bid_id,
            request_id=request_id,
            supplier_id=supplier_id,
            amount=bid_amount,
            eta_minutes=eta,
            notes=notes or "",
            ai_score=ai_score,
            ai_recommendation=ai_recommendation,
            over_budget=over_budget,
        )

        self.bids[bid_id] = bid.to_dict()
        request.setdefault("bids", []).append(bid_id)
        request["status"] = request.get("status") or "bidding"
        request["updated_at"] = _now_iso()

        self._record_delivery_event(
            event_type="delivery_bid_submitted",
            customer_id=request["customer_id"],
            supplier_id=supplier_id,
            request_id=request_id,
            amount=bid_amount,
            metadata={
                "bid_id": bid_id,
                "eta_minutes": eta,
                "ai_score": ai_score,
                "over_budget": over_budget,
            },
        )
        return bid.to_dict()

    def list_bids(
        self,
        request_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        bids = list(self.bids.values())
        if request_id:
            bids = [b for b in bids if b.get("request_id") == request_id]
        if supplier_id:
            bids = [b for b in bids if b.get("supplier_id") == supplier_id]
        if status:
            bids = [b for b in bids if b.get("status") == status]
        bids.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return bids[:limit]

    def award_bid(self, request_id: str, bid_id: str, awarded_by: str) -> Dict[str, Any]:
        request = self._get_request(request_id)
        if request.get("status") in ["delivered", "cancelled"]:
            raise ValueError("Request is closed")

        bid = self._get_bid(bid_id)
        if bid.get("request_id") != request_id:
            raise ValueError("Bid does not match request")

        if request.get("awarded_bid_id"):
            raise ValueError("Request already awarded")

        request["awarded_bid_id"] = bid_id
        request["status"] = "awarded"
        request["updated_at"] = _now_iso()

        bid["status"] = "awarded"
        bid["updated_at"] = _now_iso()

        if request.get("payment_method") in ["health_wallet", "wallet"]:
            self._reserve_wallet(
                customer_id=request["customer_id"],
                request_id=request_id,
                amount=_safe_float(bid.get("amount")),
            )
            request["reserved_amount"] = _safe_float(bid.get("amount"))

        self._record_delivery_event(
            event_type="delivery_bid_awarded",
            customer_id=request["customer_id"],
            supplier_id=bid["supplier_id"],
            request_id=request_id,
            amount=_safe_float(bid.get("amount")),
            metadata={"bid_id": bid_id, "awarded_by": awarded_by},
        )
        return {"request": request, "bid": bid}

    def accept_assignment(self, request_id: str, supplier_id: str) -> Dict[str, Any]:
        request = self._get_request(request_id)
        bid_id = request.get("awarded_bid_id")
        if not bid_id:
            raise ValueError("No awarded bid to accept")

        bid = self._get_bid(bid_id)
        if bid.get("supplier_id") != supplier_id:
            raise ValueError("Supplier not authorized for this bid")

        request["accepted_bid_id"] = bid_id
        request["status"] = "accepted"
        request["updated_at"] = _now_iso()

        bid["status"] = "accepted"
        bid["updated_at"] = _now_iso()

        self._record_delivery_event(
            event_type="delivery_bid_accepted",
            customer_id=request["customer_id"],
            supplier_id=supplier_id,
            request_id=request_id,
            amount=_safe_float(bid.get("amount")),
            metadata={"bid_id": bid_id},
        )
        return {"request": request, "bid": bid}

    def mark_delivered(self, request_id: str, supplier_id: str) -> Dict[str, Any]:
        request = self._get_request(request_id)
        if request.get("status") not in ["accepted", "in_transit", "awarded"]:
            raise ValueError("Request is not in a deliverable state")

        bid_id = request.get("awarded_bid_id") or request.get("accepted_bid_id")
        bid = self._get_bid(bid_id) if bid_id else None
        if not bid or bid.get("supplier_id") != supplier_id:
            raise ValueError("Supplier not authorized to close this request")

        request["status"] = "delivered"
        request["delivered_at"] = _now_iso()
        request["updated_at"] = request["delivered_at"]

        bid["status"] = "completed"
        bid["updated_at"] = request["delivered_at"]

        amount = _safe_float(bid.get("amount"))
        if request.get("payment_method") in ["health_wallet", "wallet"]:
            self._capture_wallet_payment(
                customer_id=request["customer_id"],
                supplier_id=supplier_id,
                request_id=request_id,
                amount=amount,
            )
            request["reserved_amount"] = 0.0

        self._record_delivery_event(
            event_type="delivery_completed",
            customer_id=request["customer_id"],
            supplier_id=supplier_id,
            request_id=request_id,
            amount=amount,
            metadata={"bid_id": bid_id},
        )
        return {"request": request, "bid": bid}

    # ---------------------------------------------------------------------
    # BI & integrity
    # ---------------------------------------------------------------------
    def get_bi_summary(self, supplier_id: Optional[str] = None) -> Dict[str, Any]:
        requests = list(self.requests.values())
        bids = list(self.bids.values())

        if supplier_id:
            requests = [
                r for r in requests
                if supplier_id in (r.get("eligible_suppliers") or [])
                or any(self.bids.get(b, {}).get("supplier_id") == supplier_id for b in r.get("bids", []))
            ]
            bids = [b for b in bids if b.get("supplier_id") == supplier_id]

        request_count = len(requests)
        bid_count = len(bids)
        bids_per_request = bid_count / max(1, request_count)

        amounts = [float(b.get("amount", 0) or 0) for b in bids]
        etas = [int(b.get("eta_minutes", 0) or 0) for b in bids if b.get("eta_minutes")]

        summary = {
            "total_requests": request_count,
            "total_bids": bid_count,
            "bids_per_request": round(bids_per_request, 2),
            "requests_by_status": self._count_by_status(requests),
            "avg_bid_amount": round(statistics.mean(amounts), 2) if amounts else 0.0,
            "median_bid_amount": round(statistics.median(amounts), 2) if amounts else 0.0,
            "avg_eta_minutes": round(statistics.mean(etas), 1) if etas else 0.0,
            "supplier_scope": supplier_id,
            "generated_at": _now_iso(),
        }
        return summary

    def validate_integrity(self) -> Dict[str, Any]:
        issues = []
        reserved_by_customer: Dict[str, float] = {}

        for req in self.requests.values():
            request_id = req.get("request_id") or req.get("id")
            status = req.get("status")
            awarded = req.get("awarded_bid_id")
            accepted = req.get("accepted_bid_id")

            if status in ["awarded", "accepted", "delivered"] and not awarded:
                issues.append(f"Request {request_id} missing awarded_bid_id")

            if awarded and awarded not in self.bids:
                issues.append(f"Request {request_id} references missing bid {awarded}")

            if accepted and accepted not in self.bids:
                issues.append(f"Request {request_id} references missing accepted bid {accepted}")

            if status == "delivered" and not req.get("delivered_at"):
                issues.append(f"Request {request_id} delivered without delivered_at timestamp")

            if req.get("payment_method") in ["health_wallet", "wallet"]:
                reserved = _safe_float(req.get("reserved_amount"), 0.0)
                if status in ["awarded", "accepted", "in_transit"]:
                    reserved_by_customer[req.get("customer_id")] = reserved_by_customer.get(req.get("customer_id"), 0.0) + reserved
                if status in ["cancelled", "delivered"] and reserved > 0:
                    issues.append(f"Request {request_id} has reserved funds after close: ${reserved:.2f}")

            if status == "delivered":
                if not self._has_delivery_payment(request_id):
                    issues.append(f"Request {request_id} delivered without delivery_payment transaction")

        for bid_id, bid in self.bids.items():
            if bid.get("request_id") not in self.requests:
                issues.append(f"Bid {bid_id} references missing request {bid.get('request_id')}")
            if bid.get("status") not in BID_STATUSES:
                issues.append(f"Bid {bid_id} has invalid status {bid.get('status')}")

        for customer_id, reserved in reserved_by_customer.items():
            wallet = self.health_wallets.get(customer_id, {})
            wallet_reserved = _safe_float(wallet.get("reserved"), 0.0)
            if abs(wallet_reserved - reserved) > 0.01:
                issues.append(
                    f"Customer {customer_id} reserved mismatch: wallet={wallet_reserved:.2f} requests={reserved:.2f}"
                )

        status = "HEALTHY" if not issues else "WARNING" if len(issues) < 5 else "CRITICAL"
        return {
            "integrity_status": status,
            "issues": issues,
            "requests_checked": len(self.requests),
            "bids_checked": len(self.bids),
            "checked_at": _now_iso(),
        }

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _get_request(self, request_id: str) -> Dict[str, Any]:
        request = self.requests.get(request_id)
        if not request:
            raise ValueError(f"Delivery request {request_id} not found")
        return request

    def _get_bid(self, bid_id: str) -> Dict[str, Any]:
        bid = self.bids.get(bid_id)
        if not bid:
            raise ValueError(f"Delivery bid {bid_id} not found")
        return bid

    def _get_supplier(self, supplier_id: str) -> Optional[Dict[str, Any]]:
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            return None
        if (supplier.get("supplier_type") or "").lower() != "delivery":
            raise ValueError("Supplier is not a delivery provider")
        if supplier.get("status") not in ["approved", "active"]:
            raise ValueError("Supplier is not approved")
        return supplier

    def _eligible_suppliers(self, location: Dict[str, Any]) -> List[str]:
        eligible = []
        for supplier_id, supplier in self.suppliers.items():
            if (supplier.get("supplier_type") or "").lower() != "delivery":
                continue
            if supplier.get("status") not in ["approved", "active"]:
                continue
            if not self._matches_location(supplier, location):
                continue
            eligible.append(supplier_id)
        return eligible

    def _matches_location(self, supplier: Dict[str, Any], location: Dict[str, Any]) -> bool:
        if not location:
            return True

        service_areas = supplier.get("service_areas")
        if isinstance(service_areas, str):
            try:
                service_areas = json.loads(service_areas)
            except Exception:
                service_areas = _normalize_list(service_areas)
        areas = _normalize_list(service_areas)

        city = (location.get("city") or "").lower()
        region = (location.get("region") or location.get("state") or "").lower()
        postal_code = (location.get("postal_code") or location.get("zip") or "").lower()

        if areas:
            combined = " ".join(areas).lower()
            if city and city not in combined:
                return False
            if region and region not in combined:
                return False
            if postal_code and postal_code not in combined:
                return False

        # Optional lat/lng distance filtering
        lat = location.get("lat")
        lng = location.get("lng")
        radius = _safe_float(location.get("radius_km"), 25.0)
        if lat is not None and lng is not None:
            supplier_location = supplier.get("location") or {}
            s_lat = supplier_location.get("lat") or supplier.get("lat")
            s_lng = supplier_location.get("lng") or supplier.get("lng")
            if s_lat is not None and s_lng is not None:
                distance = _haversine_km(float(lat), float(lng), float(s_lat), float(s_lng))
                if distance > radius:
                    return False

        return True

    def _score_bid(
        self,
        request: Dict[str, Any],
        supplier: Dict[str, Any],
        bid_amount: float,
        eta_minutes: int,
    ) -> tuple[float, str]:
        preferences = request.get("preferences") or {}
        priority = (preferences.get("priority") or "balanced").lower()

        if priority in ["cost", "cheapest", "budget"]:
            price_weight, eta_weight, rating_weight = 0.6, 0.25, 0.15
        elif priority in ["speed", "fast", "urgent"]:
            price_weight, eta_weight, rating_weight = 0.25, 0.6, 0.15
        else:
            price_weight, eta_weight, rating_weight = 0.4, 0.4, 0.2

        max_bid = request.get("max_bid_amount") or preferences.get("budget")
        max_bid = _safe_float(max_bid, 0.0)
        baseline = max_bid if max_bid > 0 else 50.0
        price_score = 1 / (1 + (bid_amount / baseline))

        target_eta = _safe_float(preferences.get("target_eta_minutes"), 120.0)
        eta_score = max(0.0, 1 - (eta_minutes / max(target_eta, 1.0)))

        rating = _safe_float(supplier.get("average_rating"), 0.0) / 5.0
        on_time = _safe_float(supplier.get("on_time_delivery_rate"), 100.0) / 100.0
        reliability = (rating * 0.6) + (on_time * 0.4)

        score = (price_weight * price_score) + (eta_weight * eta_score) + (rating_weight * reliability)
        score = max(0.0, min(score, 1.0)) * 100

        recommendation = "review"
        if score >= 80:
            recommendation = "approve"
        elif score <= 40:
            recommendation = "reject"

        return round(score, 2), recommendation

    def _reserve_wallet(self, customer_id: str, request_id: str, amount: float) -> None:
        wallet = self.health_wallets.get(customer_id)
        if not wallet:
            raise ValueError("Health wallet not found")

        balance = _safe_float(wallet.get("balance"), 0.0)
        reserved = _safe_float(wallet.get("reserved"), 0.0)
        available = balance - reserved
        if available < amount:
            raise ValueError("Insufficient wallet balance for reservation")

        wallet["reserved"] = reserved + amount
        wallet.setdefault("transactions", []).append({
            "id": _generate_id("WAL-RES"),
            "type": "delivery_reservation",
            "amount": 0.0,
            "reserved_amount": amount,
            "reference_id": request_id,
            "timestamp": _now_iso(),
            "balance_after": balance,
        })

        if self.record_transaction:
            try:
                self.record_transaction(
                    customer_id=customer_id,
                    tx_type="delivery_reservation",
                    amount=0.0,
                    description=f"Delivery reservation for request {request_id}",
                    metadata={"delivery_request_id": request_id, "reserved_amount": amount},
                )
            except Exception:
                pass

    def _release_wallet_reservation(self, customer_id: str, request_id: str, amount: float) -> None:
        wallet = self.health_wallets.get(customer_id, {})
        reserved = _safe_float(wallet.get("reserved"), 0.0)
        wallet["reserved"] = max(0.0, reserved - amount)
        wallet.setdefault("transactions", []).append({
            "id": _generate_id("WAL-REL"),
            "type": "delivery_reservation_release",
            "amount": 0.0,
            "reserved_amount": -amount,
            "reference_id": request_id,
            "timestamp": _now_iso(),
            "balance_after": _safe_float(wallet.get("balance"), 0.0),
        })

    def _capture_wallet_payment(
        self,
        customer_id: str,
        supplier_id: str,
        request_id: str,
        amount: float,
    ) -> None:
        wallet = self.health_wallets.get(customer_id)
        if not wallet:
            raise ValueError("Health wallet not found")

        balance = _safe_float(wallet.get("balance"), 0.0)
        reserved = _safe_float(wallet.get("reserved"), 0.0)
        if balance < amount:
            raise ValueError("Insufficient wallet balance for delivery payment")

        wallet["balance"] = balance - amount
        wallet["reserved"] = max(0.0, reserved - amount)
        wallet.setdefault("transactions", []).append({
            "id": _generate_id("WAL-DLV"),
            "type": "delivery_payment",
            "amount": -amount,
            "reference_id": request_id,
            "timestamp": _now_iso(),
            "balance_after": wallet["balance"],
        })

        if self.record_transaction:
            try:
                self.record_transaction(
                    customer_id=customer_id,
                    tx_type="delivery_payment",
                    amount=amount,
                    description=f"Delivery payment for request {request_id}",
                    metadata={
                        "delivery_request_id": request_id,
                        "supplier_id": supplier_id,
                        "payment_source": "health_wallet",
                    },
                )
            except Exception:
                pass

    def _record_delivery_event(
        self,
        event_type: str,
        customer_id: str,
        supplier_id: str,
        request_id: str,
        amount: float,
        metadata: Dict[str, Any],
    ) -> None:
        if not self.supply_chain_service:
            return
        try:
            self.supply_chain_service.record_delivery_event(
                event_type=event_type,
                customer_id=customer_id,
                supplier_id=supplier_id,
                delivery_request_id=request_id,
                amount=amount,
                metadata=metadata,
            )
        except Exception:
            pass

    def _has_delivery_payment(self, request_id: str) -> bool:
        for tx in self.transaction_ledger.values():
            metadata = tx.get("metadata", {}) if isinstance(tx, dict) else {}
            if metadata.get("delivery_request_id") == request_id and str(tx.get("tx_type")) == "delivery_payment":
                return True
        return False

    def _count_by_status(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in items:
            status = item.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        return counts


_delivery_bidding_service: Optional[DeliveryBiddingService] = None


def init_delivery_bidding_service(
    requests: Dict[str, Dict[str, Any]] = None,
    bids: Dict[str, Dict[str, Any]] = None,
    suppliers: Dict[str, Dict[str, Any]] = None,
    health_wallets: Dict[str, Dict[str, Any]] = None,
    transaction_ledger: Dict[str, Dict[str, Any]] = None,
    supply_chain_service=None,
    record_transaction_func: Optional[Callable[..., Dict[str, Any]]] = None,
) -> DeliveryBiddingService:
    global _delivery_bidding_service
    _delivery_bidding_service = DeliveryBiddingService(
        requests_store=requests,
        bids_store=bids,
        suppliers_store=suppliers,
        health_wallets=health_wallets,
        transaction_ledger=transaction_ledger,
        supply_chain_service=supply_chain_service,
        record_transaction_func=record_transaction_func,
    )
    return _delivery_bidding_service


def get_delivery_bidding_service() -> Optional[DeliveryBiddingService]:
    return _delivery_bidding_service
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
        
        # Calculate AI score
        bid.ai_score = self._calculate_bid_score(bid, request)
        
        # Store bid
        self.delivery_bids[bid_id] = bid
        
        logger.info(f"Supplier {supplier_id} submitted bid {bid_id} for request {request_id} "
                   f"(${bid_amount:.2f}, {delivery_duration_hours:.1f}h)")
        # Re-rank all bids for this request
        self._rank_bids(request_id)
        
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
            'ai_score': round(bid.ai_score, 2),
            'ranking': bid.ai_ranking,
            'bid': bid.to_dict()
        }
    
    def _calculate_bid_score(self, bid: DeliveryBid, request: DeliveryRequest) -> float:
        """
        AI scoring algorithm for bids.
        
        Considers:
        - Price competitiveness
        - Delivery speed
        - Supplier rating
        - On-time reliability
        """
        # Normalize price score (lower is better)
        if request.max_price and request.max_price > 0:
            price_score = 1 - (bid.bid_price / request.max_price)
        else:
            price_score = 0.5
        price_score = max(0, min(1, price_score))
        
        # Time score (faster is better within constraints)
        # Normalize based on priority window
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
        
        # Rating score (higher is better)
        rating_score = bid.supplier_rating / 5.0
        
        # Reliability score
        reliability_score = bid.on_time_percentage / 100.0
        
        # Weighted combination
        total_score = (
            self.WEIGHT_PRICE * price_score +
            self.WEIGHT_TIME * time_score +
            self.WEIGHT_RATING * rating_score +
            self.WEIGHT_RELIABILITY * reliability_score
        )
        
        # Bonus for medical certification on medical items
        if request.medical_item and bid.has_medical_certification:
            total_score += 0.05
        
        # Bonus for including insurance
        if bid.includes_insurance:
            total_score += 0.02
        
        return min(1.0, total_score) * 100  # Convert to 0-100 scale
    
    def _rank_bids(self, request_id: str):
        """Rank all bids for a request by AI score"""
        request_bids = [b for b in self.delivery_bids.values() 
                       if b.request_id == request_id and b.status == BidStatus.PENDING]
        
        # Sort by AI score descending
        request_bids.sort(key=lambda x: x.ai_score, reverse=True)
        
        # Assign rankings
        for rank, bid in enumerate(request_bids, 1):
            bid.ai_ranking = rank
    
    def get_bids_for_request(self, request_id: str) -> Dict[str, Any]:
        """Get all bids for a delivery request with AI rankings"""
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Request not found'}
        
        request = self.delivery_requests[request_id]
        bids = [b for b in self.delivery_bids.values() if b.request_id == request_id]
        
        # Sort by AI ranking
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
        """
        Select a winning bid for a delivery request.
        
        This initiates the delivery process.
        """
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
        
        # Process payment from wallet
        if request.wallet_payment:
            wallet = self.health_wallets.get(request.customer_id)
            if not wallet:
                return {'success': False, 'error': 'Customer health wallet not found'}
            
            current_balance = float(wallet.get('balance', 0))
            if current_balance < bid.bid_price:
                return {'success': False, 'error': f'Insufficient wallet balance. Required: ${bid.bid_price}, Available: ${current_balance}'}
            
            # Deduct from wallet
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
            
            # Record transaction in ledger
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
        
        # Update bid status
        bid.status = BidStatus.ACCEPTED
        
        # Update other bids to rejected
        for other_bid in self.delivery_bids.values():
            if other_bid.request_id == request_id and other_bid.bid_id != bid_id:
                other_bid.status = BidStatus.REJECTED
        
        # Update request
        request.status = DeliveryStatus.BID_SELECTED
        request.selected_bid_id = bid_id
        request.assigned_supplier_id = bid.supplier_id
        
        # Generate NFT for delivery tracking
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
        
        # Add tracking event
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
            'new_wallet_balance': wallet['balance'] if request.wallet_payment else None,
            'estimated_delivery': bid.estimated_delivery_time,
            'nft_token_id': request.nft_token_id,
            'status': 'bid_selected'
        }
    
    def auto_select_best_bid(self, request_id: str) -> Dict[str, Any]:
        """
        AI automatically selects the best bid based on scoring.
        
        Called when bidding window closes or min bids reached.
        """
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
        """Add a tracking event"""
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
        """
        Update delivery status (called by delivery supplier).
        """
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Request not found'}
        
        request = self.delivery_requests[request_id]
        
        # Verify supplier
        if request.assigned_supplier_id != supplier_id:
            return {'success': False, 'error': 'Not authorized to update this delivery'}
        
        # Parse new status
        try:
            status_enum = DeliveryStatus(new_status.lower())
        except ValueError:
            return {'success': False, 'error': f'Invalid status: {new_status}'}
        
        # Parse location
        geo_location = None
        if location:
            geo_location = GeoLocation(
                latitude=float(location.get('latitude', 0)),
                longitude=float(location.get('longitude', 0)),
                address=location.get('address', '')
            )
        
        # Update request status
        old_status = request.status
        request.status = status_enum
        
        # Update timestamps
        if status_enum == DeliveryStatus.PICKED_UP:
            request.picked_up_at = datetime.now(timezone.utc).isoformat()
        elif status_enum in [DeliveryStatus.DELIVERED, DeliveryStatus.CONFIRMED]:
            request.delivered_at = datetime.now(timezone.utc).isoformat()
        
        # Add tracking event
        self._add_tracking_event(request_id, status_enum, geo_location, notes, supplier_id)
        
        # If delivered, credit supplier
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
        """Process payment to supplier upon delivery completion"""
        if not request.selected_bid_id:
            return
        
        bid = self.delivery_bids.get(request.selected_bid_id)
        if not bid:
            return
        
        # In production, this would credit the supplier's account
        # For now, update supplier metrics
        supplier = self.suppliers.get(bid.supplier_id)
        if supplier:
            supplier['total_orders'] = supplier.get('total_orders', 0) + 1
            supplier['total_revenue'] = supplier.get('total_revenue', 0) + bid.bid_price
    
    def get_delivery_tracking(self, request_id: str) -> Dict[str, Any]:
        """Get complete tracking history for a delivery"""
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
        """Get delivery analytics for BI dashboard"""
        requests = list(self.delivery_requests.values())
        bids = list(self.delivery_bids.values())
        
        if supplier_id:
            # Filter for specific supplier
            supplier_bids = [b for b in bids if b.supplier_id == supplier_id]
            supplier_requests = [r for r in requests if r.assigned_supplier_id == supplier_id]
            
            return {
                'supplier_id': supplier_id,
                'total_bids_submitted': len(supplier_bids),
                'bids_accepted': len([b for b in supplier_bids if b.status == BidStatus.ACCEPTED]),
                'bids_rejected': len([b for b in supplier_bids if b.status == BidStatus.REJECTED]),
                'acceptance_rate': len([b for b in supplier_bids if b.status == BidStatus.ACCEPTED]) / len(supplier_bids) * 100 if supplier_bids else 0,
                'total_deliveries': len(supplier_requests),
                'completed_deliveries': len([r for r in supplier_requests if r.status in [DeliveryStatus.DELIVERED, DeliveryStatus.CONFIRMED]]),
                'average_bid_score': sum(b.ai_score for b in supplier_bids) / len(supplier_bids) if supplier_bids else 0,
                'total_revenue': sum(b.bid_price for b in supplier_bids if b.status == BidStatus.ACCEPTED)
            }
        else:
            # Platform-wide analytics
            return {
                'total_delivery_requests': len(requests),
                'open_requests': len([r for r in requests if r.status == DeliveryStatus.BIDDING_OPEN]),
                'in_progress': len([r for r in requests if r.status in [DeliveryStatus.BID_SELECTED, DeliveryStatus.PICKED_UP, DeliveryStatus.IN_TRANSIT, DeliveryStatus.OUT_FOR_DELIVERY]]),
                'completed': len([r for r in requests if r.status in [DeliveryStatus.DELIVERED, DeliveryStatus.CONFIRMED]]),
                'cancelled': len([r for r in requests if r.status == DeliveryStatus.CANCELLED]),
                'total_bids': len(bids),
                'average_bids_per_request': len(bids) / len(requests) if requests else 0,
                'average_winning_bid': sum(self.delivery_bids[r.selected_bid_id].bid_price 
                                          for r in requests if r.selected_bid_id and r.selected_bid_id in self.delivery_bids) / 
                                       len([r for r in requests if r.selected_bid_id]) if [r for r in requests if r.selected_bid_id] else 0,
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
        """Get AI-powered insights for delivery optimization"""
        requests = list(self.delivery_requests.values())
        bids = list(self.delivery_bids.values())
        
        insights = {
            'recommendations': [],
            'alerts': [],
            'optimizations': []
        }
        
        # Check for open requests with no bids
        open_no_bids = [r for r in requests 
                       if r.status == DeliveryStatus.BIDDING_OPEN and
                       not any(b.request_id == r.request_id for b in bids)]
        if open_no_bids:
            insights['alerts'].append({
                'type': 'no_bids',
                'count': len(open_no_bids),
                'message': f'{len(open_no_bids)} delivery requests have no bids yet. Consider expanding supplier network.'
            })
        
        # Check for suppliers with low acceptance rates
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
        
        # Suggest pricing optimization
        avg_bid_prices = {}
        for bid in bids:
            request = self.delivery_requests.get(bid.request_id)
            if request:
                priority = request.priority.value
                if priority not in avg_bid_prices:
                    avg_bid_prices[priority] = []
                avg_bid_prices[priority].append(bid.bid_price)
        
        for priority, prices in avg_bid_prices.items():
            if len(prices) >= 3:
                avg = sum(prices) / len(prices)
                insights['optimizations'].append({
                    'priority': priority,
                    'average_bid_price': round(avg, 2),
                    'bid_count': len(prices),
                    'suggested_max_price': round(avg * 1.1, 2)  # 10% above average
                })
        
        return insights


# Singleton instance
_delivery_service: Optional[DeliveryBiddingService] = None


def get_delivery_bidding_service(**kwargs) -> DeliveryBiddingService:
    """Get or create delivery bidding service singleton"""
    global _delivery_service
    if _delivery_service is None:
        _delivery_service = DeliveryBiddingService(**kwargs)
    return _delivery_service


def init_delivery_bidding_service(**kwargs) -> DeliveryBiddingService:
    """Initialize delivery bidding service with dependencies"""
    global _delivery_service
    _delivery_service = DeliveryBiddingService(**kwargs)
    return _delivery_service
