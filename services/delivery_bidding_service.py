"""
PHINS Delivery Bidding Service
==============================
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
