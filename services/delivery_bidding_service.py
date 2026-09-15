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

B11 (docs/agent_operations_optimization_design.md §B11):

- **Geohash index** over open requests (pickup location, precisions 1–7) so
  "open jobs near this supplier" is a cell + 8-neighbour lookup followed by an
  exact haversine filter, not a scan of every request. Suppliers that publish
  coordinates and a ``service_radius_km`` are excluded from eligibility and
  from bidding when the pickup is outside their radius.
- **Reliability from settled orders**: when a read-only settlement accessor is
  wired, the ranking's reliability term blends the supplier's settled-order
  success rate with the self-reported on-time rate
  (``SETTLED_RELIABILITY_WEIGHT``); with too few settled orders it falls back
  to the on-time rate alone. The blend is recorded on every bid.
- **SLA clock**: a bidding window that has elapsed closes the request
  (``bidding_closed`` when bids exist — no new bids, the customer may still
  select one; ``cancelled`` with ``closed_reason`` when none arrived) and
  emits a ``delivery.bidding_window_closed`` outbox event. Expiry runs lazily
  on every bid/read of an overdue request and eagerly from
  ``expire_bidding_windows()`` (queue job ``services/jobs/delivery_sla_job``).
"""

import json
import math
import hashlib
import os
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

from services.agent_metrics import instrument_agent

logger = logging.getLogger('phins.delivery_bidding')


# ---------------------------------------------------------------------------
# Geohash (pure Python; standard base32 alphabet, interleaved lon/lat bits)
# ---------------------------------------------------------------------------

_GEOHASH_BASE32 = '0123456789bcdefghjkmnpqrstuvwxyz'
_GEOHASH_DECODE = {ch: i for i, ch in enumerate(_GEOHASH_BASE32)}
GEOHASH_INDEX_PRECISION = 7
# Smaller cell side (km) per precision — the conservative dimension that
# guarantees a cell plus its 8 neighbours cover a circle of that radius
# around any point inside the centre cell.
_GEOHASH_MIN_CELL_KM = {1: 4990.0, 2: 624.0, 3: 156.0, 4: 19.5, 5: 4.89, 6: 0.61, 7: 0.076}

# Reliability blend (documented weight): with at least
# MIN_SETTLED_ORDERS_FOR_BLEND settled orders,
#   reliability = SETTLED_RELIABILITY_WEIGHT * settled_success_rate
#               + (1 - SETTLED_RELIABILITY_WEIGHT) * on_time_rate / 100
# otherwise reliability = on_time_rate / 100 (self-reported only).
SETTLED_RELIABILITY_WEIGHT = 0.6
MIN_SETTLED_ORDERS_FOR_BLEND = 3

DEFAULT_SUPPLIER_SERVICE_RADIUS_KM = 50.0
BIDDING_WINDOW_CLOSED_EVENT = 'delivery.bidding_window_closed'


def geohash_encode(latitude: float, longitude: float, precision: int = GEOHASH_INDEX_PRECISION) -> str:
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    lat = max(-90.0, min(90.0, float(latitude)))
    lon = ((float(longitude) + 180.0) % 360.0) - 180.0
    out: List[str] = []
    bits = (16, 8, 4, 2, 1)
    bit = 0
    ch = 0
    even = True
    while len(out) < max(1, int(precision)):
        if even:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                ch |= bits[bit]
                lon_lo = mid
            else:
                lon_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                ch |= bits[bit]
                lat_lo = mid
            else:
                lat_hi = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_GEOHASH_BASE32[ch])
            bit = 0
            ch = 0
    return ''.join(out)


def geohash_decode_bbox(geohash: str) -> Tuple[float, float, float, float]:
    """``(lat_min, lat_max, lon_min, lon_max)`` of the cell."""
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    even = True
    for ch in str(geohash or '').lower():
        value = _GEOHASH_DECODE[ch]
        for mask in (16, 8, 4, 2, 1):
            if even:
                mid = (lon_lo + lon_hi) / 2
                if value & mask:
                    lon_lo = mid
                else:
                    lon_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if value & mask:
                    lat_lo = mid
                else:
                    lat_hi = mid
            even = not even
    return lat_lo, lat_hi, lon_lo, lon_hi


def geohash_neighbors(geohash: str) -> List[str]:
    """The up-to-8 distinct cells around ``geohash`` at the same precision."""
    precision = len(geohash)
    lat_lo, lat_hi, lon_lo, lon_hi = geohash_decode_bbox(geohash)
    clat = (lat_lo + lat_hi) / 2
    clon = (lon_lo + lon_hi) / 2
    dlat = lat_hi - lat_lo
    dlon = lon_hi - lon_lo
    cells: List[str] = []
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            if i == 0 and j == 0:
                continue
            lat = clat + i * dlat
            if lat > 90.0 or lat < -90.0:
                continue  # no cell beyond the poles
            lon = clon + j * dlon
            cell = geohash_encode(lat, lon, precision)
            if cell != geohash and cell not in cells:
                cells.append(cell)
    return cells


def geohash_precision_for_radius(radius_km: float) -> int:
    """Largest precision whose cell (+ neighbours) still covers ``radius_km``."""
    radius = max(0.0, float(radius_km or 0))
    for precision in sorted(_GEOHASH_MIN_CELL_KM, reverse=True):
        if _GEOHASH_MIN_CELL_KM[precision] >= radius:
            return precision
    return 1


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2) - math.radians(lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


class DeliveryStatus(Enum):
    CREATED = "created"
    BIDDING_OPEN = "bidding_open"
    BIDDING_CLOSED = "bidding_closed"
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
    # B11: SLA clock + geo index
    bidding_closed_at: Optional[str] = None
    closed_reason: Optional[str] = None
    pickup_geohash: str = ""
    delivery_geohash: str = ""

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
    # B11: explainable reliability term (see SETTLED_RELIABILITY_WEIGHT)
    settled_orders: int = 0
    settled_success_rate: Optional[float] = None
    reliability_score: float = 0.0
    reliability_source: str = "on_time_rate"
    distance_to_pickup_km: Optional[float] = None

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
                 generate_nft_func=None,
                 settled_outcomes_func: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
                 event_publisher: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
                 outbox_events: Optional[List[Dict[str, Any]]] = None):
        self.delivery_requests = delivery_requests if delivery_requests is not None else {}
        self.delivery_bids = delivery_bids if delivery_bids is not None else {}
        self.tracking_events = tracking_events if tracking_events is not None else {}
        self.suppliers = suppliers if suppliers is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self.nft_ledger = nft_ledger if nft_ledger is not None else {}
        self.record_transaction = record_transaction_func
        self.generate_nft = generate_nft_func
        # B11: read-only accessor ``supplier_id -> settled outcome summary``
        # (see SupplierSettlementService.get_settled_outcomes); None = not wired.
        self.settled_outcomes = settled_outcomes_func
        # B11: outbox publisher ``(event_type, aggregate_type, aggregate_id, payload) -> row``.
        # Every emitted event is also kept in ``outbox_events`` (in-memory mode,
        # tests, and as the process-local record of what was published).
        self.event_publisher = event_publisher if event_publisher is not None else self._default_event_publisher
        self.outbox_events: List[Dict[str, Any]] = outbox_events if outbox_events is not None else []

        self.DEFAULT_BIDDING_WINDOW_HOURS = 4
        self.MIN_BIDS_BEFORE_AUTO_SELECT = 3
        self.MAX_BIDS_PER_REQUEST = 10

        self.WEIGHT_PRICE = 0.30
        self.WEIGHT_TIME = 0.25
        self.WEIGHT_RATING = 0.25
        self.WEIGHT_RELIABILITY = 0.20

        self.supplier_metrics: Dict[str, Dict[str, Any]] = {}
        self._settled_cache: Dict[str, Optional[Dict[str, Any]]] = {}

        # B11: geohash index over open requests, keyed by pickup cell at every
        # precision 1..GEOHASH_INDEX_PRECISION: {precision: {cell: {request_id}}}
        self._geo_index: Dict[int, Dict[str, Set[str]]] = {
            p: {} for p in range(1, GEOHASH_INDEX_PRECISION + 1)}
        self._indexed: Dict[str, str] = {}  # request_id -> full-precision pickup geohash
        self.rebuild_geo_index()

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    # =========================================================================
    # B11: GEOHASH INDEX
    # =========================================================================

    def _index_request(self, request: DeliveryRequest) -> None:
        if not request.pickup_geohash:
            request.pickup_geohash = geohash_encode(
                request.pickup_location.latitude, request.pickup_location.longitude)
        if not request.delivery_geohash:
            request.delivery_geohash = geohash_encode(
                request.delivery_location.latitude, request.delivery_location.longitude)
        self._unindex_request(request.request_id)
        full = request.pickup_geohash
        for precision, cells in self._geo_index.items():
            cells.setdefault(full[:precision], set()).add(request.request_id)
        self._indexed[request.request_id] = full

    def _unindex_request(self, request_id: str) -> None:
        full = self._indexed.pop(request_id, None)
        if not full:
            return
        for precision, cells in self._geo_index.items():
            bucket = cells.get(full[:precision])
            if bucket is not None:
                bucket.discard(request_id)
                if not bucket:
                    del cells[full[:precision]]

    def rebuild_geo_index(self) -> int:
        """Re-derive the index from ``delivery_requests`` (startup / injected stores)."""
        for cells in self._geo_index.values():
            cells.clear()
        self._indexed.clear()
        for request in list(self.delivery_requests.values()):
            if isinstance(request, DeliveryRequest) and request.status == DeliveryStatus.BIDDING_OPEN:
                self._index_request(request)
        return len(self._indexed)

    def geo_index_stats(self) -> Dict[str, Any]:
        return {
            'indexed_open_requests': len(self._indexed),
            'cells_by_precision': {p: len(cells) for p, cells in self._geo_index.items()},
        }

    def find_open_requests_near(self, latitude: float, longitude: float,
                                radius_km: float = DEFAULT_SUPPLIER_SERVICE_RADIUS_KM,
                                limit: Optional[int] = None,
                                now: Optional[datetime] = None) -> Dict[str, Any]:
        """Open requests whose pickup is within ``radius_km`` of a point.

        Candidates come from the geohash cell containing the point plus its 8
        neighbours at the precision chosen for the radius; each candidate is
        then confirmed with an exact haversine distance, so a request just
        across a cell boundary is found and one inside the cells but farther
        than the radius is excluded. Overdue windows are closed first so an
        expired request is never offered as open.
        """
        self.expire_bidding_windows(now=now)
        radius = max(0.0, float(radius_km or 0))
        precision = geohash_precision_for_radius(radius)
        centre = geohash_encode(latitude, longitude, precision)
        cells = [centre] + geohash_neighbors(centre)
        candidates: Set[str] = set()
        bucket = self._geo_index[precision]
        for cell in cells:
            candidates.update(bucket.get(cell, ()))

        matches: List[Dict[str, Any]] = []
        for request_id in candidates:
            request = self.delivery_requests.get(request_id)
            if not isinstance(request, DeliveryRequest) or request.status != DeliveryStatus.BIDDING_OPEN:
                continue
            distance = haversine_km(latitude, longitude,
                                    request.pickup_location.latitude, request.pickup_location.longitude)
            if distance > radius:
                continue
            matches.append({
                'request_id': request_id,
                'distance_km': round(distance, 3),
                'route_km': round(request.pickup_location.distance_to(request.delivery_location), 3),
                'priority': request.priority.value,
                'max_price': request.max_price,
                'bidding_ends_at': request.bidding_ends_at,
                'pickup_geohash': request.pickup_geohash,
            })
        matches.sort(key=lambda m: (m['distance_km'], m['request_id']))
        if limit:
            matches = matches[:int(limit)]
        return {
            'success': True,
            'precision': precision,
            'cells_searched': len(cells),
            'candidates': len(candidates),
            'matches': matches,
        }

    @staticmethod
    def _supplier_coordinates(supplier: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        location = supplier.get('location') if isinstance(supplier.get('location'), dict) else supplier
        lat = location.get('latitude')
        lon = location.get('longitude')
        if lat is None or lon is None:
            return None
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            return None

    def _supplier_distance_check(self, supplier: Dict[str, Any], request: DeliveryRequest
                                 ) -> Tuple[bool, Optional[float], Optional[float]]:
        """``(within_radius, distance_km, radius_km)``; no coordinates → allowed."""
        coords = self._supplier_coordinates(supplier)
        if coords is None:
            return True, None, None
        try:
            radius = float(supplier.get('service_radius_km') or DEFAULT_SUPPLIER_SERVICE_RADIUS_KM)
        except (TypeError, ValueError):
            radius = DEFAULT_SUPPLIER_SERVICE_RADIUS_KM
        distance = haversine_km(coords[0], coords[1],
                                request.pickup_location.latitude, request.pickup_location.longitude)
        return distance <= radius, round(distance, 3), radius

    # =========================================================================
    # B11: RELIABILITY FROM SETTLED ORDERS
    # =========================================================================

    def _settled_outcomes_for(self, supplier_id: str) -> Optional[Dict[str, Any]]:
        if self.settled_outcomes is None:
            return None
        if supplier_id in self._settled_cache:
            return self._settled_cache[supplier_id]
        try:
            outcome = self.settled_outcomes(supplier_id)
        except Exception as exc:  # accessor failure degrades to self-reported data
            logger.warning("settled outcomes unavailable for %s: %s", supplier_id, exc)
            outcome = None
        if not isinstance(outcome, dict):
            outcome = None
        self._settled_cache[supplier_id] = outcome
        return outcome

    def invalidate_settled_cache(self, supplier_id: Optional[str] = None) -> None:
        if supplier_id is None:
            self._settled_cache.clear()
        else:
            self._settled_cache.pop(supplier_id, None)

    def reliability_for(self, supplier_id: str, on_time_percentage: float) -> Dict[str, Any]:
        """Blend settled-order outcomes into the reliability term (documented weight).

        Returns ``score`` in [0, 1] plus the inputs so a bid's ranking is
        explainable. Monotone in ``settled_success_rate``.
        """
        on_time = max(0.0, min(1.0, float(on_time_percentage or 0) / 100.0))
        outcome = self._settled_outcomes_for(supplier_id)
        settled = int((outcome or {}).get('settled_orders') or 0)
        rate = (outcome or {}).get('success_rate')
        if outcome is None or settled < MIN_SETTLED_ORDERS_FOR_BLEND or rate is None:
            return {'score': on_time, 'source': 'on_time_rate',
                    'settled_orders': settled, 'settled_success_rate': None if rate is None else float(rate)}
        rate = max(0.0, min(1.0, float(rate)))
        score = SETTLED_RELIABILITY_WEIGHT * rate + (1.0 - SETTLED_RELIABILITY_WEIGHT) * on_time
        return {'score': round(score, 6), 'source': 'settled_blend',
                'settled_orders': settled, 'settled_success_rate': rate}

    # =========================================================================
    # B11: SLA CLOCK (bidding window expiry) + OUTBOX
    # =========================================================================

    @staticmethod
    def _default_event_publisher(event_type: str, aggregate_type: str, aggregate_id: str,
                                 payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Durable outbox row in DB mode; in-memory mode records locally only."""
        if str(os.environ.get('USE_DATABASE', '')).strip().lower() != 'true':
            return None
        from services.marketplace_event_service import get_marketplace_event_service
        return get_marketplace_event_service().publish(
            event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id, payload=payload)

    def _emit_event(self, event_type: str, aggregate_type: str, aggregate_id: str,
                    payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            'id': f"EVT-{uuid.uuid4().hex[:12].upper()}",
            'event_type': event_type,
            'aggregate_type': aggregate_type,
            'aggregate_id': aggregate_id,
            'payload': dict(payload),
            'emitted_at': datetime.now(timezone.utc).isoformat(),
            'published': False,
            'publish_error': None,
        }
        try:
            published = self.event_publisher(event_type, aggregate_type, aggregate_id, dict(payload))
            if published:
                record['published'] = True
                record['outbox_id'] = published.get('id') if isinstance(published, dict) else None
        except Exception as exc:
            record['publish_error'] = str(exc)
            logger.warning("outbox publish failed for %s/%s: %s", event_type, aggregate_id, exc)
        self.outbox_events.append(record)
        return record

    @staticmethod
    def _parse_ts(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _window_elapsed(self, request: DeliveryRequest, now: datetime) -> bool:
        deadline = self._parse_ts(request.bidding_ends_at)
        return deadline is not None and now >= deadline

    def _close_bidding_window(self, request: DeliveryRequest, now: datetime) -> Dict[str, Any]:
        """Single terminal transition out of ``bidding_open`` for an elapsed window."""
        pending = [b for b in self.delivery_bids.values()
                   if b.request_id == request.request_id and b.status == BidStatus.PENDING]
        pending.sort(key=lambda b: (b.ai_ranking if b.ai_ranking > 0 else 999, -b.ai_score))
        closed_at = now.isoformat()
        request.bidding_closed_at = closed_at
        if pending:
            request.status = DeliveryStatus.BIDDING_CLOSED
            request.closed_reason = 'bidding_window_elapsed'
            outcome = 'closed_with_bids'
            note = f'Bidding window closed with {len(pending)} bid(s); awaiting selection'
        else:
            request.status = DeliveryStatus.CANCELLED
            request.closed_reason = 'bidding_window_elapsed_no_bids'
            outcome = 'cancelled_no_bids'
            note = 'Bidding window closed with no bids; request cancelled'
        self._unindex_request(request.request_id)
        self._add_tracking_event(request.request_id, request.status, None, note, 'sla_clock')
        event = self._emit_event(
            BIDDING_WINDOW_CLOSED_EVENT, 'delivery_request', request.request_id, {
                'request_id': request.request_id,
                'order_id': request.order_id,
                'customer_id': request.customer_id,
                'outcome': outcome,
                'status': request.status.value,
                'bidding_ends_at': request.bidding_ends_at,
                'closed_at': closed_at,
                'bid_count': len(pending),
                'recommended_bid_id': pending[0].bid_id if pending else None,
                'recommended_supplier_id': pending[0].supplier_id if pending else None,
            })
        return {'request_id': request.request_id, 'outcome': outcome,
                'status': request.status.value, 'bid_count': len(pending), 'event_id': event['id']}

    def expire_bidding_windows(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Close every open request whose bidding window has elapsed (idempotent)."""
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        closed: List[Dict[str, Any]] = []
        for request in list(self.delivery_requests.values()):
            if not isinstance(request, DeliveryRequest) or request.status != DeliveryStatus.BIDDING_OPEN:
                continue
            if self._window_elapsed(request, now):
                closed.append(self._close_bidding_window(request, now))
        return {
            'success': True,
            'checked_at': now.isoformat(),
            'closed': len([c for c in closed if c['outcome'] == 'closed_with_bids']),
            'cancelled': len([c for c in closed if c['outcome'] == 'cancelled_no_bids']),
            'transitions': closed,
            'open_remaining': sum(1 for r in self.delivery_requests.values()
                                  if isinstance(r, DeliveryRequest) and r.status == DeliveryStatus.BIDDING_OPEN),
        }

    def next_window_deadline(self) -> Optional[str]:
        deadlines = [self._parse_ts(r.bidding_ends_at) for r in self.delivery_requests.values()
                     if isinstance(r, DeliveryRequest) and r.status == DeliveryStatus.BIDDING_OPEN]
        deadlines = [d for d in deadlines if d is not None]
        return min(deadlines).isoformat() if deadlines else None

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
        self._index_request(request)

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
            'pickup_geohash': request.pickup_geohash,
            'request': request.to_dict()
        }

    def _find_eligible_suppliers(self, request: DeliveryRequest) -> List[Dict]:
        eligible = []
        for supplier_id, supplier in self.suppliers.items():
            if supplier.get('status') != 'approved':
                continue
            if supplier.get('supplier_type') != 'delivery':
                continue

            # B11: a supplier with coordinates is matched by distance to the
            # pickup (exact haversine within its service radius); one without
            # falls back to the textual service-area match below.
            within, distance_km, radius_km = self._supplier_distance_check(supplier, request)
            if not within:
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
                'total_orders': supplier.get('total_orders', 0),
                'distance_to_pickup_km': distance_km,
                'service_radius_km': radius_km,
            })

        eligible.sort(key=lambda s: (s['distance_to_pickup_km'] is None,
                                     s['distance_to_pickup_km'] or 0.0, s['supplier_id']))
        return eligible

    def eligible_suppliers_for(self, request_id: str) -> Dict[str, Any]:
        request = self.delivery_requests.get(request_id)
        if not isinstance(request, DeliveryRequest):
            return {'success': False, 'error': 'Delivery request not found'}
        suppliers = self._find_eligible_suppliers(request)
        return {'success': True, 'request_id': request_id, 'count': len(suppliers), 'suppliers': suppliers}

    # =========================================================================
    # BIDDING SYSTEM
    # =========================================================================

    @instrument_agent('delivery_bidding',
                      decision_fn=lambda r: 'accepted' if r.get('success') else 'rejected')
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

        # B11 SLA clock: an elapsed window closes the request (and emits the
        # outbox event) the moment anyone touches it, so a late bid is refused
        # for the same reason the scheduled sweep would have applied.
        now = datetime.now(timezone.utc)
        if request.status == DeliveryStatus.BIDDING_OPEN and self._window_elapsed(request, now):
            self._close_bidding_window(request, now)
            return {'success': False, 'error': 'Bidding deadline has passed',
                    'status': request.status.value}

        if request.status != DeliveryStatus.BIDDING_OPEN:
            return {'success': False, 'error': f'Bidding is closed. Status: {request.status.value}'}

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

        within, distance_km, radius_km = self._supplier_distance_check(supplier, request)
        if not within:
            return {'success': False,
                    'error': f'Pickup is {distance_km} km away, outside your {radius_km:g} km service radius',
                    'distance_to_pickup_km': distance_km, 'service_radius_km': radius_km}

        try:
            pickup_dt = datetime.fromisoformat(estimated_pickup_time.replace('Z', '+00:00'))
            delivery_dt = datetime.fromisoformat(estimated_delivery_time.replace('Z', '+00:00'))
            duration_hours = (delivery_dt - pickup_dt).total_seconds() / 3600
        except Exception:
            duration_hours = 24.0

        bid_id = self._generate_id("BID")
        reliability = self.reliability_for(supplier_id, supplier.get('on_time_rate', 95.0))

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
            expires_at=(now + timedelta(hours=12)).isoformat(),
            settled_orders=reliability['settled_orders'],
            settled_success_rate=reliability['settled_success_rate'],
            reliability_score=reliability['score'],
            reliability_source=reliability['source'],
            distance_to_pickup_km=distance_km,
        )

        bid.ai_score = self._calculate_bid_score(bid, request)
        self.delivery_bids[bid_id] = bid
        self._rank_bids(request_id)

        return {
            'success': True,
            'bid_id': bid_id,
            'ai_score': round(bid.ai_score, 2),
            'ranking': bid.ai_ranking,
            'reliability': reliability,
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
        # B11: settled-order blend when available (bid.reliability_source tells which).
        if bid.reliability_source == 'settled_blend':
            reliability_score = bid.reliability_score
        else:
            reliability_score = bid.on_time_percentage / 100.0
            bid.reliability_score = reliability_score

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
        now = datetime.now(timezone.utc)
        if request.status == DeliveryStatus.BIDDING_OPEN and self._window_elapsed(request, now):
            self._close_bidding_window(request, now)
        bids = [b for b in self.delivery_bids.values() if b.request_id == request_id]
        bids.sort(key=lambda x: x.ai_ranking if x.ai_ranking > 0 else 999)

        return {
            'success': True,
            'request_id': request_id,
            'request_status': request.status.value,
            'total_bids': len(bids),
            'bidding_ends_at': request.bidding_ends_at,
            'bidding_closed_at': request.bidding_closed_at,
            'closed_reason': request.closed_reason,
            'ranking_weights': {
                'price': self.WEIGHT_PRICE, 'time': self.WEIGHT_TIME,
                'rating': self.WEIGHT_RATING, 'reliability': self.WEIGHT_RELIABILITY,
                'reliability_settled_weight': SETTLED_RELIABILITY_WEIGHT,
                'min_settled_orders_for_blend': MIN_SETTLED_ORDERS_FOR_BLEND,
            },
            'ai_recommended': bids[0].to_dict() if bids else None,
            'bids': [b.to_dict() for b in bids]
        }

    @instrument_agent('delivery_bidding',
                      decision_fn=lambda r: 'selected' if r.get('success') else 'rejected')
    def select_bid(self, request_id: str, bid_id: str, selected_by: str = "customer") -> Dict[str, Any]:
        if request_id not in self.delivery_requests:
            return {'success': False, 'error': 'Request not found'}
        if bid_id not in self.delivery_bids:
            return {'success': False, 'error': 'Bid not found'}

        request = self.delivery_requests[request_id]
        bid = self.delivery_bids[bid_id]

        if bid.request_id != request_id:
            return {'success': False, 'error': 'Bid does not belong to this request'}
        # A closed window still allows selecting among the bids that arrived in time.
        if request.status not in (DeliveryStatus.BIDDING_OPEN, DeliveryStatus.BIDDING_CLOSED):
            return {'success': False, 'error': f'Cannot select bid. Status: {request.status.value}'}
        if bid.status != BidStatus.PENDING:
            return {'success': False, 'error': f'Bid is not pending. Status: {bid.status.value}'}

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
        self._unindex_request(request_id)

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

    @instrument_agent('delivery_bidding',
                      decision_fn=lambda r: 'auto_selected' if r.get('success') else 'no_selection')
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


def default_settled_outcomes_accessor() -> Optional[Callable[[str], Optional[Dict[str, Any]]]]:
    """Settled-order accessor for the singleton: the settlement service in DB mode, else None."""
    if str(os.environ.get('USE_DATABASE', '')).strip().lower() != 'true':
        return None
    try:
        from services.supplier_settlement_service import get_supplier_settlement_service
        return get_supplier_settlement_service().get_settled_outcomes
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("settled-outcomes accessor unavailable: %s", exc)
        return None


def get_delivery_bidding_service(**kwargs) -> DeliveryBiddingService:
    global _delivery_service
    if _delivery_service is None:
        kwargs.setdefault('settled_outcomes_func', default_settled_outcomes_accessor())
        _delivery_service = DeliveryBiddingService(**kwargs)
    return _delivery_service


def init_delivery_bidding_service(**kwargs) -> DeliveryBiddingService:
    global _delivery_service
    kwargs.setdefault('settled_outcomes_func', default_settled_outcomes_accessor())
    _delivery_service = DeliveryBiddingService(**kwargs)
    return _delivery_service


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# ---------------------------------------------------------------------------
def _delivery_bidding_health() -> Dict[str, Any]:
    """Read-only probe: never instantiates the service."""
    instance = _delivery_service
    if instance is None:
        return {'status': 'ok', 'initialized': False}
    return {
        'status': 'ok',
        'initialized': True,
        'delivery_requests': len(getattr(instance, 'delivery_requests', {}) or {}),
        'delivery_bids': len(getattr(instance, 'delivery_bids', {}) or {}),
        'geo_index': instance.geo_index_stats(),
        'settled_outcomes_wired': instance.settled_outcomes is not None,
        'reliability_blend': {
            'settled_weight': SETTLED_RELIABILITY_WEIGHT,
            'min_settled_orders': MIN_SETTLED_ORDERS_FOR_BLEND,
        },
        'outbox_events': len(instance.outbox_events),
        'next_window_deadline': instance.next_window_deadline(),
    }


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='delivery_bidding',
        name='Delivery Bidding AI',
        version='1.0.0',
        module=__name__,
        description=(
            'Location-based marketplace delivery bidding: ranks supplier bids, '
            'auto-selects the best offer, tracks fulfilment, and settles through '
            'the health wallet.'
        ),
        entry_url='/admin-supplier-dashboard.html',
        api={'method': 'POST', 'path': '/api/delivery/evaluate-bids'},
        roles=('admin', 'supplier', 'customer'),
        deterministic=True,
        sample_prompts=(
            'Rank the bids for delivery request DLV-1001',
        ),
    ), health_fn=_delivery_bidding_health)
except Exception as _reg_exc:  # pragma: no cover
    logger.warning("delivery bidding agent registration skipped: %s", _reg_exc)
