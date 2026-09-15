"""
API Extensions for Delivery Bidding System
==========================================
Thin, role-scoped HTTP layer over ``services/delivery_bidding_service.py``.
Wired from ``web_portal/server.py`` (``/api/delivery/*``); every handler
returns ``(status_code, payload)`` and errors are ``{"error": "..."}``.

Endpoints:
- POST /api/delivery/request                 - create a delivery request (customer/admin)
- GET  /api/delivery/nearby?latitude&longitude&radius_km
                                              - open requests near a point via the
                                                geohash index (supplier/admin)  [B11]
- GET  /api/delivery/eligible/<request_id>    - suppliers eligible for a request (admin)
- POST /api/delivery/bid                      - submit a supplier bid (supplier/admin)
- GET  /api/delivery/bids/<request_id>        - ranked bids + ranking weights
- POST /api/delivery/evaluate-bids            - AI recommendation for a request;
                                                ``auto_accept`` selects it (customer/admin)
- POST /api/delivery/accept-bid               - select a bid (customer/admin)
- POST /api/delivery/update-status            - fulfilment status update (assigned supplier)
- GET  /api/delivery/track/<request_id>       - tracking timeline
- POST /api/delivery/expire-windows           - run the SLA sweep now (admin)     [B11]
- GET  /api/delivery/analytics[?supplier_id=] - delivery analytics (admin; supplier: own)
- GET  /api/delivery/insights                 - AI insights (admin)

Scope rules: a customer only sees/acts on requests whose ``customer_id`` is
their own; a supplier only bids/updates as itself (``supplier_id`` from the
session); admins are unrestricted.
"""

from typing import Any, Dict, Optional, Tuple

from services.delivery_bidding_service import get_delivery_bidding_service

Response = Tuple[int, Dict[str, Any]]

ADMIN_ROLES = ('admin',)


def _role(ctx: Dict[str, Any]) -> str:
    return str(ctx.get('role') or '').lower()


def _is_admin(ctx: Dict[str, Any]) -> bool:
    return _role(ctx) in ADMIN_ROLES


def _session_supplier_id(ctx: Dict[str, Any]) -> str:
    return str(ctx.get('supplier_id') or (ctx.get('username') if _role(ctx) == 'supplier' else '') or '')


def _float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _request_visible(ctx: Dict[str, Any], request) -> bool:
    if _is_admin(ctx):
        return True
    role = _role(ctx)
    if role == 'customer':
        return bool(ctx.get('customer_id')) and request.customer_id == ctx.get('customer_id')
    if role == 'supplier':
        return True  # suppliers may inspect any open request to decide whether to bid
    return False


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

def handle_delivery_request_create(body: dict, ctx: Dict[str, Any]) -> Response:
    if _role(ctx) not in ('admin', 'customer'):
        return 403, {'error': 'Customer or admin access required'}
    customer_id = str(body.get('customer_id') or ctx.get('customer_id') or '')
    if _role(ctx) == 'customer':
        customer_id = str(ctx.get('customer_id') or '')
    order_id = body.get('order_id')
    pickup_location = body.get('pickup_location') or {}
    delivery_location = body.get('delivery_location') or {}
    if not all([customer_id, order_id, pickup_location, delivery_location]):
        return 400, {'error': 'Missing required fields: customer_id, order_id, pickup_location, delivery_location'}
    try:
        result = get_delivery_bidding_service().create_delivery_request(
            order_id=str(order_id),
            customer_id=customer_id,
            pickup_location=pickup_location,
            delivery_location=delivery_location,
            package_info=body.get('package_info') or body.get('item_details') or {},
            priority=str(body.get('priority') or body.get('urgency') or 'standard'),
            max_price=_float(body.get('max_price', body.get('max_budget'))),
        )
    except ValueError as exc:
        return 400, {'error': str(exc)}
    return 201, result


def handle_delivery_nearby(qs: Dict[str, Any], ctx: Dict[str, Any]) -> Response:
    if _role(ctx) not in ('admin', 'supplier'):
        return 403, {'error': 'Supplier or admin access required'}

    def first(key, default=None):
        value = qs.get(key, default)
        return value[0] if isinstance(value, list) and value else value

    latitude = _float(first('latitude'))
    longitude = _float(first('longitude'))
    if latitude is None or longitude is None:
        return 400, {'error': 'latitude and longitude are required'}
    radius = _float(first('radius_km'), 50.0)
    limit = first('limit')
    result = get_delivery_bidding_service().find_open_requests_near(
        latitude, longitude, radius_km=radius, limit=int(limit) if limit else None)
    return 200, result


def handle_delivery_eligible(request_id: str, ctx: Dict[str, Any]) -> Response:
    if not _is_admin(ctx):
        return 403, {'error': 'Admin access required'}
    result = get_delivery_bidding_service().eligible_suppliers_for(request_id)
    return (200 if result.get('success') else 404), result


def handle_delivery_bid_submit(body: dict, ctx: Dict[str, Any]) -> Response:
    if _role(ctx) not in ('admin', 'supplier'):
        return 403, {'error': 'Supplier or admin access required'}
    supplier_id = str(body.get('supplier_id') or _session_supplier_id(ctx) or '')
    if _role(ctx) == 'supplier':
        own = _session_supplier_id(ctx)
        if not own:
            return 403, {'error': 'Supplier session has no supplier_id'}
        if supplier_id and supplier_id != own:
            return 403, {'error': 'A supplier may only bid as itself'}
        supplier_id = own
    request_id = body.get('request_id')
    bid_price = _float(body.get('bid_price', body.get('bid_amount')))
    pickup = body.get('estimated_pickup_time')
    delivery = body.get('estimated_delivery_time')
    if not all([request_id, supplier_id, pickup, delivery]) or bid_price is None:
        return 400, {'error': 'Missing required fields: request_id, supplier_id, bid_price, '
                              'estimated_pickup_time, estimated_delivery_time'}
    result = get_delivery_bidding_service().submit_bid(
        request_id=str(request_id),
        supplier_id=supplier_id,
        bid_price=bid_price,
        estimated_pickup_time=str(pickup),
        estimated_delivery_time=str(delivery),
        vehicle_type=str(body.get('vehicle_type') or 'van'),
        includes_insurance=bool(body.get('includes_insurance', True)),
        notes=str(body.get('notes') or ''),
    )
    if not result.get('success'):
        return 409, {'error': result.get('error', 'Bid rejected'), **{k: v for k, v in result.items() if k != 'success'}}
    return 201, result


def handle_delivery_bids_get(request_id: str, ctx: Dict[str, Any]) -> Response:
    service = get_delivery_bidding_service()
    request = service.delivery_requests.get(request_id)
    if request is None:
        return 404, {'error': 'Delivery request not found'}
    if not _request_visible(ctx, request):
        return 403, {'error': 'Not authorized for this delivery request'}
    return 200, service.get_bids_for_request(request_id)


def handle_delivery_bid_evaluate(body: dict, ctx: Dict[str, Any]) -> Response:
    request_id = str(body.get('request_id') or '')
    if not request_id:
        return 400, {'error': 'Missing request_id'}
    service = get_delivery_bidding_service()
    request = service.delivery_requests.get(request_id)
    if request is None:
        return 404, {'error': 'Delivery request not found'}
    if _role(ctx) not in ('admin', 'customer') or not _request_visible(ctx, request):
        return 403, {'error': 'Not authorized for this delivery request'}
    ranked = service.get_bids_for_request(request_id)
    if bool(body.get('auto_accept')):
        selected = service.auto_select_best_bid(request_id)
        if not selected.get('success'):
            return 409, {'error': selected.get('error', 'No bid selected'), 'evaluation': ranked}
        return 200, {'evaluation': ranked, 'selection': selected}
    return 200, {'evaluation': ranked, 'selection': None}


def handle_delivery_bid_accept(body: dict, ctx: Dict[str, Any]) -> Response:
    request_id = str(body.get('request_id') or '')
    bid_id = str(body.get('bid_id') or '')
    if not request_id or not bid_id:
        return 400, {'error': 'Missing required fields: request_id, bid_id'}
    service = get_delivery_bidding_service()
    request = service.delivery_requests.get(request_id)
    if request is None:
        return 404, {'error': 'Delivery request not found'}
    if _role(ctx) not in ('admin', 'customer') or not _request_visible(ctx, request):
        return 403, {'error': 'Not authorized for this delivery request'}
    result = service.select_bid(request_id, bid_id, selected_by=str(ctx.get('username') or 'customer'))
    if not result.get('success'):
        return 409, {'error': result.get('error', 'Bid not selected')}
    return 200, result


def handle_delivery_status_update(body: dict, ctx: Dict[str, Any]) -> Response:
    if _role(ctx) not in ('admin', 'supplier'):
        return 403, {'error': 'Supplier or admin access required'}
    request_id = str(body.get('request_id') or body.get('delivery_id') or '')
    new_status = body.get('status')
    if not request_id or not new_status:
        return 400, {'error': 'Missing required fields: request_id, status'}
    supplier_id = str(body.get('supplier_id') or _session_supplier_id(ctx) or '')
    if _role(ctx) == 'supplier':
        supplier_id = _session_supplier_id(ctx)
    result = get_delivery_bidding_service().update_delivery_status(
        request_id=request_id, new_status=str(new_status), supplier_id=supplier_id,
        location=body.get('location'), notes=str(body.get('notes') or ''))
    if not result.get('success'):
        error = result.get('error', 'Update rejected')
        return (403 if 'authorized' in error.lower() else 409), {'error': error}
    return 200, result


def handle_delivery_track(request_id: str, ctx: Dict[str, Any]) -> Response:
    service = get_delivery_bidding_service()
    request = service.delivery_requests.get(request_id)
    if request is None:
        return 404, {'error': 'Delivery request not found'}
    if not _request_visible(ctx, request):
        return 403, {'error': 'Not authorized for this delivery request'}
    return 200, service.get_delivery_tracking(request_id)


def handle_delivery_expire_windows(ctx: Dict[str, Any]) -> Response:
    if not _is_admin(ctx):
        return 403, {'error': 'Admin access required'}
    return 200, get_delivery_bidding_service().expire_bidding_windows()


def handle_delivery_analytics(qs: Dict[str, Any], ctx: Dict[str, Any]) -> Response:
    value = qs.get('supplier_id')
    supplier_id = value[0] if isinstance(value, list) and value else value
    if _role(ctx) == 'supplier':
        supplier_id = _session_supplier_id(ctx)
    elif not _is_admin(ctx):
        return 403, {'error': 'Admin or supplier access required'}
    return 200, get_delivery_bidding_service().get_delivery_analytics(supplier_id or None)


def handle_delivery_insights(ctx: Dict[str, Any]) -> Response:
    if not _is_admin(ctx):
        return 403, {'error': 'Admin access required'}
    return 200, get_delivery_bidding_service().get_ai_delivery_insights()


# ---------------------------------------------------------------------------
# dispatchers used by server.py
# ---------------------------------------------------------------------------

def handle_get(path: str, qs: Dict[str, Any], ctx: Dict[str, Any]) -> Response:
    if not ctx.get('username'):
        return 401, {'error': 'Authentication required'}
    if path == '/api/delivery/nearby':
        return handle_delivery_nearby(qs, ctx)
    if path.startswith('/api/delivery/eligible/'):
        return handle_delivery_eligible(path.rsplit('/', 1)[1], ctx)
    if path.startswith('/api/delivery/bids/'):
        return handle_delivery_bids_get(path.rsplit('/', 1)[1], ctx)
    if path.startswith('/api/delivery/track/'):
        return handle_delivery_track(path.rsplit('/', 1)[1], ctx)
    if path == '/api/delivery/analytics':
        return handle_delivery_analytics(qs, ctx)
    if path == '/api/delivery/insights':
        return handle_delivery_insights(ctx)
    return 404, {'error': 'Unknown delivery endpoint'}


def handle_post(path: str, body: dict, ctx: Dict[str, Any]) -> Response:
    if not ctx.get('username'):
        return 401, {'error': 'Authentication required'}
    body = body if isinstance(body, dict) else {}
    if path == '/api/delivery/request':
        return handle_delivery_request_create(body, ctx)
    if path == '/api/delivery/bid':
        return handle_delivery_bid_submit(body, ctx)
    if path == '/api/delivery/evaluate-bids':
        return handle_delivery_bid_evaluate(body, ctx)
    if path == '/api/delivery/accept-bid':
        return handle_delivery_bid_accept(body, ctx)
    if path == '/api/delivery/update-status':
        return handle_delivery_status_update(body, ctx)
    if path == '/api/delivery/expire-windows':
        return handle_delivery_expire_windows(ctx)
    return 404, {'error': 'Unknown delivery endpoint'}
